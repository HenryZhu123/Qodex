# Agent 工作流：政策、护栏与模块接线

> 状态（2026-11-15，合并 `origin/main` 后）：链路是 `命题(8093, task_id) → 审校(8091, /tasks/.../review) → PASS 自动 annotate + 入库 → 组卷(8092) → 导出`，
> 由 Pi 的 `qodex-workflow` 扩展承担政策与代码护栏。本文只写已验证事实；未实现能力见文末「已知边界」。
>
> **本文不覆盖题目质量。** 题目“像不像真题”（超纲、计算量、考点粒度、图题/题组）属于待开工的
> **问题 1（质量层）**，当前状态是“只完成诊断、一行代码未改”，见 `TASK_STATE.md` 的「⛔ 未开工：问题 1」。
> 也就是说：本文说的“链路跑通”只证明流程可用，**不证明产出的题合格**。

## 1. 用户与需求

| 用户 | 需求 | 允许的动作序列 |
| --- | --- | --- |
| 命题老师 | 按章节/考点出题并进待审 | 取材 → 命题 → 审校（PASS 才入库） |
| 组卷老师 | 出一份卷子 | 查题库 → 组卷 → 缺口补题 → 补的题再审校入库 → 重排一次 |
| 考生 | 练某个考点 | 命题 → 只交付 `student_view` + 讲解，不给评分点与错因表 |

## 2. 决策路径（一张图）

```mermaid
flowchart TD
    IN([用户一句话]) --> ID{能判断身份与参数?<br/>命题 / 组卷 / 练题<br/>科目·章节·题量·分值·题型}
    ID -- 缺 --> ASK[追问, 一次最多 3 个问题<br/>不替用户编参数] --> IN
    ID -- 明确不支持 --> BOUND[说明边界 + 可替代方案<br/>综合题入卷/题组/图题/难度配额] --> END1([到此为止, 不硬做])
    ID -- 命题老师 --> GEN[question_generation]
    ID -- 组卷老师 --> ASM[question_bank 查池 → exam_assembly]
    ID -- 考生 --> STU[出题后只给 student_view + 讲解] --> END2([交付, 不给评分点/错因])

    GEN --> G{status / failure.code}
    G -- GENERATED --> REV[exam_checker.review_question<br/>task_id + question_id + version]
    G -- NEEDS_MATERIAL --> M1[换一次检索范围/检索词] --> M2{够了吗}
    M2 -- 否 --> ASK
    M2 -- 是 --> GEN
    G -- SELF_CHECK_FAILED --> R{retry 字段}
    R -- same_request --> GEN2[原样重来 1 次]
    R -- new_request --> CHANGE[换考点/换写法, 或交回用户]
    G -- MODEL_UNAVAILABLE / 其它 --> STOP1([如实报告失败 + 已完成部分])

    REV --> V{review.status}
    V -- PASS --> ING[(自动 annotate + 入库<br/>ingestion=STORED)]
    V -- NEEDS_REVISION --> ONE[revise_question 修 1 轮] --> V2{还不过?}
    V2 -- 是 --> STOP2([停下, 附审校理由])
    V2 -- 否 --> ING
    V -- UNRESOLVED --> STOP3([说明"审校不完整", 不写成通过])

    ING --> ASM
    ASM --> A{status}
    A -- STRUCTURAL_PASS --> OUT([学生卷 + 答案卷 HTML<br/>+ 组卷历史])
    A -- NEEDS_QUESTIONS --> SUP[读 deficits 补题] --> REV2[补的题必须再审校入库] --> ASM2[重排 1 次] --> A2{还缺?}
    A2 -- 是 --> GAP([交回缺口报告, 不硬凑])
    A2 -- 否 --> OUT
    A -- UNRESOLVED --> STOP4([候选池不完整, 不能断言缺题])
    A -- INVALID_REQUEST --> FIX[按 errors 修参数, 不支持的能力要说明]

    subgraph GUARD[护栏: 不依赖模型自觉]
        B1[tool_call: 预算 6/6/3 · 墙钟 45min · 同参数重复付费拦截 · 连续失败 3 次停]
        B2[tool_result: 失败置 isError + 压成 observation<br/>ok/status/code/retry/needs/next/errors/artifact]
        B3[message_end: 没有 STORED 就不许说"已入库"<br/>引号内文字不算断言 · 只在出题/审校后生效]
        B4[trace: 输入→调用→观察→拦截 全部落盘]
    end
```

**读法**：实线是"正常路径"；每个 `STOP` 都是**安全停止**（如实说明 + 交回用户），不是异常崩溃。
图中任何一步都可能被右下角护栏打断，打断时给出可读理由（预算耗尽 / 重复调用 / 连续失败）。

## 2-A. 身份与接线

命题与审校用 `task_id + question_id + version` 对齐（详见 `docs/QUESTION_GENERATION_REVIEW_INTEGRATION.zh-CN.md`）：

```text
Pi Agent（qodex-workflow）
  ├── question_generation → 8093 → generation_tasks + pending_questions（每题带 task_id）
  ├── exam_checker
  │     review_question(task_id, question_id, version)
  │       → 8091 从待审表导入不可变快照 question_snapshots
  │       → 九类专项检查 → PASS 时 annotate（难度/知识点）→ 幂等写入 question_bank
  └── exam_assembly → 8092 → 选题 + 导出学生卷/答案卷（组卷历史写 PostgreSQL）
```

**接入是 Pi 显式调用两个工具完成的，不是数据库后台自动消费。**

> 上一版曾新增 `POST /v1/exam-checker/documents/import` + `question_generation/handoff.py` 作为"作者题包 → 审校"的接缝。
> 合并 `origin/main` 后该路径与新身份模型（`question_snapshots`，主键含 `task_id`）重复且不兼容，已删除；
> 现在只有一条登记机制，避免两套版本语义并存。

## 3. 政策（提示词，可被模型自行裁量）

写在 `qodex-workflow` 的 `before_agent_start`（**追加**到系统提示，不替换）：人物识别、候选动作、观察-响应、澄清、停止。

保留给模型的自由度：检索词自选、换词重试、改请求或拒绝并说明代价、只起草不入库、预算内提前收尾。
不给的自由度：判定 PASS、自造 `knowledge_points` / `task_id` / 版本号、声称未发生的入库。

## 4. 护栏（代码，模型无法绕过）

| 护栏 | 行为 | 配置 |
| --- | --- | --- |
| 调用预算 | 超限 `tool_call` 直接 block，并给出"停止新调用 + 报告已完成部分" | `QODEX_MAX_GENERATION_CALLS`(6) / `QODEX_MAX_REVIEW_CALLS`(6) / `QODEX_MAX_ASSEMBLY_CALLS`(3) / `QODEX_MAX_WALL_CLOCK_MS`(45 min) |
| 重复付费 | 同 `(tool, 参数)` 摘要已成功执行 → block（失败不占用，允许重试） | — |
| 失败可见 | 服务返回 `status=SELF_CHECK_FAILED/UNRESOLVED/…` 或 `{error}` 时置 `isError=true`，把结果压成 `{observation:{ok,status,code,retry,needs,next,detail,errors,artifact}}` | — |
| 入库措辞 | 拿不到 `ingestion.status=STORED` 时，助手若写"已入库/已通过"，`message_end` 追加纠正 | — |
| trace | 每次调用/结果/拦截写 `.local/qodex-traces/workflow-*.jsonl` | `QODEX_TRACE_DIR` |
| 政策开关 | `QODEX_WORKFLOW_POLICY=0/off/false` 关闭政策注入（护栏保留） | — |

命题侧新增 `failure.code`（追加字段，不改 `status/message`）：`candidate_shape`、`material_gap`、`design_invalid`、
`quality_gate`、`condition_test_incomplete`、`blind_disagreement`、`blind_incomplete`、`audit_rejected`，
每项带 `retry`（`same_request`/`new_request`/`no`）与 `needs`（`material`/`human`/null）。

## 5-A. 运行与验证

```bash
# 数据库（PG 5433 + 命题侧表）
bash pi-coding-agent/start-exam-checker-db.sh
docker exec -i qodex-exam-checker-postgres-1 psql -U qodex -d qodex < question_generation/sql/001_pending_questions.sql
docker exec -i qodex-exam-checker-postgres-1 psql -U qodex -d qodex < question_generation/sql/002_generation_tasks.sql

# 服务：8091（审校，需 EXAM_CHECKER_* 模型配置）、8092（组卷）、8093（命题，需 DEEPSEEK_* 与 KB）
cd pi-coding-agent/services/exam-checker && .venv/bin/python -m exam_checker
QODEX_PYTHON=$PWD/pi-coding-agent/services/exam-checker/.venv/bin/python bash scripts/start-exam-assembly.sh
bash scripts/start-question-generation.sh

# 测试
python3 -m unittest discover -s tests
cd pi-coding-agent/services/exam-checker && .venv/bin/python -m pytest
cd pi-coding-agent/packages/coding-agent && node ../../node_modules/vitest/dist/cli.js --run test/suite/qodex-workflow.test.ts
```

## 5-B. 实测记录（2026-11-15，合并 origin/main 后）

环境：PostgreSQL 17（compose，5433）+ 8091/8092/8093 本机；命题与审校均用官方 `deepseek-flash`。

| 轮次 | 请求 | 结果 |
| --- | --- | --- |
| run1 | 循环队列单选 | 命题 200 / 审校 **NEEDS_REVISION**（选项缺 A–D 标识，见下"接缝缺陷 2"） |
| run2 | 循环队列单选 | 命题 200 → 审校 **PASS** → `ingestion=STORED` |
| run3 | 时间片轮转单选 | 命题 **MODEL_UNAVAILABLE**（author `content_decode`，两次都截断；属于可复现的模型失败） |
| run4 | 哈夫曼 WPL 单选 | 命题 200 → **PASS** → STORED |
| run5 | 栈与队列单选 | 命题 200 → **PASS** → STORED |
| run6 | 二叉树遍历单选 | 命题 200 → **PASS** → STORED |
| run7 | 单链表头插尾插单选 | 命题 200 → **PASS** → STORED → 组 **1 题 2 分** → **STRUCTURAL_PASS**（学生卷/答案卷 HTML 落盘） |

耗时：命题 90–130 s（plan 18–20 s / author 40–92 s / reader 5 s / audit 28 s）；审校 9–11 s（9 项检查并发，3 项走 JEV 路由 + 1 次 annotate）。

### 合并后发现并修好的 6 个接缝缺陷

这些都是真实跑出来的，不是推测；每条都会让链路在某一环整体失败：

1. `generation_tasks.generation_mode` 的 CHECK 不含 `author`/`replenishment`
   → 命题花完模型钱后写库失败，返回 `QUEUE_UNAVAILABLE`（run1 前实测）。
2. 生成题选项进审校时丢了 A–D 标识 → `options_check` 判"选项缺少标识符"，**每道题都 NEEDS_REVISION**（run1）。
3. `subject` 用考纲 slug（`data_structures`），题库与组卷用中文 → 组卷查不到候选（run2 后实测 `points=None` 同类问题同源）。
4. 单选没有分值（`points=None`）→ 组卷拒绝（"不自动修改分值"）；按 408 约定在交接处补 2 分。
5. `answer_text` 存的是教师视图整段 JSON → 组卷拒绝（"答案必须是单个 A–D 或唯一匹配的选项全文"）。
6. `reference` 装了材料出处 → 组卷把它当"共享材料/题组"，拒绝渲染（"不能输出残缺题面"）。

### 仍未解决的（交给组卷侧）

- 组卷按题逐条调用 `/tasks/{task_id}/questions/{question_id}/state`，**一条历史脏记录（有题库行、无快照）会让整次组卷 502**，
  而不是跳过该记录。本地测试库中已删除该脏行；生产代码需要容错（建议按 `record_id` 跳过并记 `rejected_records`）。
- 组卷契约仍只支持四选项单选、同题型单一分值；综合题/题组/带图题不支持（见 §6）。

## 6. 已知边界（不要当成已实现）

1. **组卷只支持四选项单选、同题型单一分值**；综合题不能入卷。真实 408 需要 40×2 单选 + 41–47 共 70 分综合题，
   且综合题分值异质（6–16 分/题），当前契约表达不了。
2. **题组**（2024 年 43/44 共用同一台机器 M）与**带图题**在全系统没有对应实体。
3. **审校看不到答案**：`CheckerPayload` 只有 `reference` + `detection_content`，答案/解析/评分不进审校，
   因此 `PASS` 不证明答案正确；答案正确性由命题侧盲解 + 审计与人工负责。
4. 难度与知识点由 annotate 决定，属模型判断而非校准量表；组卷必须用 `question_bank search` 读真值。
5. 金额没有代码强制上限，只有调用次数与墙钟；付费实验仍需事先授权 + 子 agent 审方案。
6. 题目与真题的贴合度（计算量、题型配比、超纲判定）**未做**，见 `TASK_STATE.md` 问题 1。
