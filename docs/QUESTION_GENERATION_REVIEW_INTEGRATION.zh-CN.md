# AI 命题与 AI 审校接入说明

本文用于帮助组员理解 2026-11-15 完成的题目身份、版本和数据库改造，以及自主命题如何连接 AI 审校与正式题库。

## 1. 改动目标

改造前，命题侧和审校侧分别维护版本：

- 命题侧使用 `question_generation.pending_questions` 中的 `question_id + version`。
- 审校侧使用 `question_versions.version_id`（UUID）和 `document_id`。
- 两边没有稳定的任务级身份，命题产生的题不能直接按版本送审。

改造后统一使用：

```text
task_id + question_id + version
```

- `task_id`：一次命题任务的 UUID。批量生成时，同一批所有题共享一个 `task_id`。
- `question_id`：任务内的题目 ID。
- `version`：该题从 1 开始递增的整数版本号。

这个三元组唯一确定一份不可变题目内容。审校结果和题库记录必须绑定同一个三元组，不能把旧版本的 PASS 结果用于新版本。

## 2. 完整连接流程

```text
Pi Agent
  │
  │ 1. 调用 question_generation
  ▼
自主命题服务 :8093
  │ 创建 generation_tasks
  │ 写入 pending_questions
  │ 返回 task_id、question_id、version
  ▼
Pi Agent
  │
  │ 2. 调用 exam_checker.review_question
  ▼
AI 审校服务 :8091
  │ 从 pending_questions 读取指定版本
  │ 导入 question_snapshots 不可变快照
  │ 执行九类专项检查和知识库检索
  │ 写入 question_reviews
  │
  ├─ NEEDS_REVISION / UNRESOLVED → 不入正式题库
  │
  └─ PASS → 标注难度和知识点
              │
              ▼
          question_bank
              │
              ▼
        组卷服务 :8092
```

这里的“连接”是由 Pi Agent 显式调用两个工具完成的，不是数据库后台自动消费。只调用命题工具时，题目仅进入待审队列；必须继续调用审校工具才能审校和入库。

## 3. 数据库表和职责

### 3.1 `question_generation.generation_tasks`

一条记录代表一次命题任务，主要保存：

- `task_id`：UUID 主键。
- `request_id`：命题模块原有的请求追踪 ID，不是主键或幂等键。
- `generation_mode`：`single`、`batch`、`comprehensive`、`revise`、`author`、`replenishment` 或迁移产生的 `legacy`。
- `question_count`：任务计划或首次生成的题量。
- `request_json`：完整命题请求。
- 模型、Prompt 版本、状态和时间字段。

### 3.2 `question_generation.pending_questions`

保存命题自检通过、等待审校的版本：

```text
主键：(task_id, question_id, version)
外键：task_id → generation_tasks.task_id
```

旧版本不会删除。新版本入队后，旧版本写入 `superseded_at`。部分唯一索引：

```sql
UNIQUE (task_id, question_id) WHERE superseded_at IS NULL
```

保证同一任务中的同一道题只有一个当前版本。查询最新待审版本时不需要计算 `MAX(version)`。

### 3.3 `question_snapshots`

这是审校侧的不可变题目版本表，替代已经删除的 `question_versions`：

```text
主键：(task_id, question_id, version)
```

- AI 命题题目通过 `generation_task_id` 物理外键连接 `generation_tasks`。
- 上传 PDF/DOC/DOCX 得到的题目通过 `source_document_id` 连接 `exam_documents`。
- `revision_source` 记录 `GENERATED`、`PARSED`、`AI_EDIT` 或 `USER_EDIT`。
- `question_json` 保存完整题目快照。
- `change_log` 保存修订说明、审校反馈和模型信息。

AI 命题快照还有检查约束，保证文本 `task_id` 与 UUID `generation_task_id` 一致，避免题目被挂到错误任务。

### 3.4 `question_reviews`

每次审校追加一条记录：

- 物理复合外键连接相同的 `(task_id, question_id, version)` 快照。
- `question_json` 保存开始审校时的完整题目快照。
- `review_json` 保存路由、九类检查、知识库查询、错误和耗时。
- `idempotency_key` 唯一；相同调用重试不会重复执行和插入。

同一个版本如果使用不同的幂等键，可以主动重新审校并保留多次审校历史。

### 3.5 `question_bank`

只保存 PASS 的题目版本：

```text
唯一约束：(task_id, question_id, version)
```

入库前会同时检查：

1. 该版本存在 PASS 审校。
2. 入库的题目内容与被审校的不可变快照完全一致。
3. `task_id`、`question_id` 和 `version` 全部一致。
4. 已生成难度和非空知识点列表。

同一版本重复入库会返回已有题库记录；新版本审校通过后可以形成新的题库记录。

## 4. Pi 工具调用方式

### 4.1 命题

Pi 工具名：`question_generation`

```json
{
  "operation": "single",
  "request": {
    "schema_version": "0.1",
    "request_id": "paging-demo",
    "subject": "operating_systems",
    "topic": "single_level_paging",
    "question_type": "single_choice",
    "seed": 42,
    "constraints": {
      "page_size": 256
    },
    "evidence": [
      {
        "id": "ostep-paging",
        "source": "https://pages.cs.wisc.edu/~remzi/OSTEP/vm-paging.pdf",
        "version": "OSTEP 1.10, chapter 18",
        "anchor": "§18.1",
        "summary": "将虚拟地址拆为虚页号和页内偏移，再映射到物理页框。",
        "rules": ["split_address", "map_virtual_page", "preserve_offset"]
      }
    ]
  }
}
```

Pi 扩展会在请求中自动生成 UUID `task_id`。命题服务的响应包含：

```json
{
  "task_id": "b4d4d9f0-5f57-4e52-8e1f-87f72551c7bd",
  "questions": [
    {
      "question_id": "question_1",
      "version": 1,
      "review_status": "PENDING"
    }
  ],
  "queue_receipts": [
    {
      "question_id": "question_1",
      "version": 1,
      "status": "QUEUED"
    }
  ]
}
```

批量命题返回多道题时，它们共享同一个 `task_id`。

### 4.2 审校指定版本

Pi 工具名：`exam_checker`

```json
{
  "operation": "review_question",
  "task_id": "b4d4d9f0-5f57-4e52-8e1f-87f72551c7bd",
  "question_id": "question_1",
  "version": 1
}
```

`version` 可以省略。省略时审校服务读取 `pending_questions` 中当前未被替代的版本；正式工作流建议在取得命题回执后显式传入版本，避免并发修订时审错对象。

Pi 扩展使用工具调用 ID 作为 `idempotency_key`，网页端使用 `crypto.randomUUID()`。HTTP 调用方必须自己提供非空幂等键。

### 4.3 查询状态

```json
{
  "operation": "get_question_state",
  "task_id": "b4d4d9f0-5f57-4e52-8e1f-87f72551c7bd",
  "question_id": "question_1"
}
```

返回当前 `version`、完整题目、修订来源、审校状态和题库状态。

### 4.4 Agent 自主决定是否重新命题

```json
{
  "operation": "revise",
  "request": {
    "task_id": "b4d4d9f0-5f57-4e52-8e1f-87f72551c7bd",
    "schema_version": "0.1",
    "request_id": "paging-revise-001",
    "current_question": "命题工具先前返回的完整 v1 题目包",
    "feedback": {
      "feedback_id": "exam_checker 返回的 review_id",
      "question_id": "命题工具返回的 question_id",
      "target_version": 1,
      "part_id": "cross-page",
      "action": "replace_next_frame",
      "replacement_frame": 18,
      "comment": "根据 exam_checker.errors 归纳出的修订原因"
    }
  }
}
```

exam-checker 只返回 `NEEDS_REVISION`、`review_id` 和结构化错误，不调用命题服务，也不创建版本。Pi Agent 读取结果后自主判断是否调用 `question_generation.revise`。其中 `feedback_id` 使用真实的 `review_id`，用于追溯新版本依据的审校记录；`target_version` 必须等于被审校版本。命题工具沿用原 `task_id`，校验反馈目标版本并创建 version 2；Agent 随后再自主判断是否调用审校工具。工具提示要求同一题最多处理三个被拒绝版本，但没有后端把调用顺序写死。

## 5. HTTP 接口

命题：

```text
POST /v1/question-generation/single
POST /v1/question-generation/batch
POST /v1/question-generation/comprehensive
POST /v1/question-generation/revise
```

AI 命题题目的审校：

```text
GET  /v1/exam-checker/tasks/{task_id}/questions/{question_id}/state
POST /v1/exam-checker/tasks/{task_id}/questions/{question_id}/review
```

审校请求体：

```json
{
  "version": 1,
  "idempotency_key": "调用方生成的唯一值"
}
```

上传文档的 `/documents/{document_id}/...` 接口继续保留。上传题目的 `task_id` 使用解析产生的 `document_id`，但不会创建虚假的命题任务记录。

## 6. 状态和异常处理

### 命题入队状态

- `QUEUED`：首次成功入队。
- `ALREADY_QUEUED`：相同版本、相同内容的幂等重试。
- `VERSION_CONFLICT`：同一版本出现不同内容，或修订基线不匹配。
- `SUPERSEDED`：尝试重新提交已经被替代的版本。

### 审校状态

- `PASS`：所有检查完成且无错误，随后尝试标注并入库。
- `NEEDS_REVISION`：发现明确问题，不入库。
- `UNRESOLVED`：至少一个检查最终失败，不能视为通过。

### 题库状态

- `STORED`：当前版本已经入库。
- `OUTDATED`：同一道题的旧版本已入库，但当前版本尚未入库。
- `NOT_STORED`：没有题库记录。
- `NOT_CONFIGURED`：当前服务没有配置 PostgreSQL。

## 7. 本地启动与验证

在仓库根目录运行：

```bash
npm run demo:db        # PostgreSQL、Alembic 和命题表
npm run demo:services  # 启动 8091、8092、8093
npm run demo:status    # 检查服务健康状态
```

完整网页与 Pi Agent：

```bash
npm run demo
```

数据库迁移已经包含在 `demo:db` 和 `demo` 中。后续新增表或索引时，应继续新增 Alembic 或按序 SQL 迁移，不要在服务启动代码中临时 `CREATE TABLE`。

## 8. 当前边界与后续工作

目前已经完成命题版本到审校版本的可靠连接，但仍有以下边界：

1. 没有后台进程自动消费 `pending_questions`，必须由 Pi Agent 或调用方发起审校。
2. “审校不通过后是否重新命题”由 Pi Agent 根据结构化结果自主决定，不是后端状态机。Pi 侧的政策 + 护栏（`qodex-workflow`）要求逐轮换改法，拦截同参数重复提交并记账，最多审校 v1、v2、v3；但它不是独立编排服务，也不由审校服务驱动，经其他入口调用时需自行遵守。见 [agent-workflow.md](agent-workflow.md) §4 和 §9。
3. 命题服务当前创建和保存任务，但尚未在所有题都审校完成后自动汇总更新任务最终状态。
4. 当前命题侧通用修订能力仍受具体题型生成器支持范围约束；不支持的反馈必须明确返回失败，不能让审校服务代为修改。
5. 文档解析和 AI 命题共用审校快照模型，但来源外键不同，不应把 `document_id` 当成 AI 命题任务 ID。

演示 Agent 自主性时应保留 `question_generation → exam_checker → question_generation → exam_checker` 的独立工具轨迹，不新增隐藏这些决策的复合工具。

## 9. 主要代码位置

| 内容 | 路径 |
| --- | --- |
| 命题 HTTP 服务和任务写入 | `question_generation/service.py` |
| 命题任务与待审表迁移 | `question_generation/sql/002_generation_tasks.sql` |
| 审校数据库迁移 | `pi-coding-agent/services/exam-checker/migrations/versions/20261115_01_unified_question_tasks.py` 起 |
| 命题版本导入审校 | `pi-coding-agent/services/exam-checker/src/exam_checker/services/generated_question_service.py` |
| 审校任务接口 | `pi-coding-agent/services/exam-checker/src/exam_checker/api/app.py` |
| 固定版本审校工作流 | `pi-coding-agent/services/exam-checker/src/exam_checker/services/question_workflow_service.py` |
| PASS 入库校验 | `pi-coding-agent/services/exam-checker/src/exam_checker/services/question_bank_service.py` |
| Pi 命题工具 | `pi-coding-agent/packages/coding-agent/src/extensions/question-generation/index.ts` |
| Pi 审校与题库工具 | `pi-coding-agent/packages/coding-agent/src/extensions/exam-checker/index.ts` |
| 完整数据库结构 | `pi-coding-agent/services/exam-checker/DATABASE.zh-CN.md` |
