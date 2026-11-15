# Qodex PostgreSQL 配置与数据库结构

本文面向只需要使用 Qodex 数据库的成员。无需安装或启动 Exam Checker，
也不需要配置 LLM、Jev 或其他模型 API Key。

## 1. 环境要求

- Docker Desktop
- Docker Compose，即 `docker compose` 命令

不需要本地安装 PostgreSQL、Python、Alembic 或 pgvector。

## 2. 一键启动

在仓库根目录运行：

```bash
./start-exam-checker-db.sh
```

首次运行会自动下载 `pgvector/pgvector:pg17` 镜像、创建数据库，并在一次性
Docker 容器中运行 Alembic migration 创建业务表。后续运行会复用已有容器和
数据卷，只应用新增 migration，不会清空数据。

启动完成后，命令行应显示容器状态为 `healthy`。

## 3. 默认连接配置

不创建 `.env` 也可以直接使用以下默认配置：

```text
Host:     127.0.0.1
Port:     5433
Database: qodex
User:     qodex
Password: qodex-local
```

常规 PostgreSQL 连接字符串：

```text
postgresql://qodex:qodex-local@127.0.0.1:5433/qodex
```

异步 SQLAlchemy 连接字符串：

```text
postgresql+asyncpg://qodex:qodex-local@127.0.0.1:5433/qodex
```

默认使用主机端口 `5433`，避免与其他占用 `5432` 的 PostgreSQL 实例冲突。

## 4. 可选：自定义数据库配置

只有需要修改端口、用户名、密码或数据库名时，才需要在仓库根目录创建 `.env`：

```dotenv
EXAM_CHECKER_POSTGRES_USER=qodex
EXAM_CHECKER_POSTGRES_PASSWORD=qodex-local
EXAM_CHECKER_POSTGRES_DB=qodex
EXAM_CHECKER_POSTGRES_PORT=5433
```

然后重新执行：

```bash
./start-exam-checker-db.sh
```

这些初始化变量只在 Docker volume 第一次创建时生效。修改已有 `.env` 不会
自动修改已经创建的数据库用户或密码。如需用新配置重新初始化，必须先删除旧
volume；该操作会永久删除其中的数据。

数据库启动不读取或要求以下变量：

- `EXAM_CHECKER_LLM_API_KEY`
- `EXAM_CHECKER_REVIEW_LLM_API_KEY`
- `EXAM_CHECKER_WORKFLOW_LLM_API_KEY`
- `EXAM_CHECKER_JEV_API_KEY`

## 5. 常用操作

### 查看状态

```bash
docker compose --env-file .env \
  -f services/exam-checker/compose.yaml ps
```

如果没有创建 `.env`，去掉 `--env-file .env`：

```bash
docker compose -f services/exam-checker/compose.yaml ps
```

### 查看日志

```bash
docker compose -f services/exam-checker/compose.yaml logs postgres
```

### 停止并保留数据

```bash
docker compose -f services/exam-checker/compose.yaml stop
```

### 重新启动

```bash
./start-exam-checker-db.sh
```

### 进入 PostgreSQL 命令行

默认配置下运行：

```bash
docker compose -f services/exam-checker/compose.yaml \
  exec postgres psql -U qodex -d qodex
```

进入后可以执行：

```sql
\dt
SELECT current_database(), current_user;
```

### 删除容器和全部数据

```bash
docker compose -f services/exam-checker/compose.yaml down -v
```

`down -v` 会永久删除本地 Qodex 数据库，只应在确认不再需要数据时执行。

## 6. 数据持久化

PostgreSQL 数据存放在 Docker named volume：

```text
qodex-exam-checker_exam_checker_postgres_data
```

停止或删除容器但不使用 `-v` 时，数据仍保留在该 volume 中。其他成员启动的
是相同数据库软件和表结构，但不会自动获得你本机 volume 中的数据。

Compose 首次初始化时还会启用 `vector` 扩展，为后续知识库向量检索预留能力。

## 7. 当前数据库结构

当前采用“关键标识使用关系型字段，完整业务对象使用 JSONB”的设计。题目内容
不会拆成大量列，避免选择题、判断题、简答题等不同题型频繁改变表结构。

```mermaid
erDiagram
    generation_tasks ||--o{ pending_questions : produces
    generation_tasks ||--o{ question_snapshots : imports
    exam_documents ||--o{ question_snapshots : parses
    question_snapshots ||--o{ question_reviews : reviewed_as
    question_snapshots ||--o| question_bank : stored_as
    question_reviews ||--o| question_bank : approves
    assembled_exams ||--o{ assembled_exam_items : snapshots
```

### 7.1 `exam_documents`

每次成功解析文件后保存一份完整试卷。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `document_id` | string, PK | 本次解析生成的试卷 ID |
| `document_json` | JSONB | 完整试卷层级、题目节点和来源信息 |
| `created_at` | timestamp | 创建时间 |

相同文件重新解析时，目前会生成新的 `document_id`，尚未按文件哈希自动去重。

### 7.2 `question_generation.generation_tasks`

一次 Agent 命题调用对应一条任务；批量生成的所有题共享同一个 `task_id`。任务保存 `request_id`、命题模式、状态、题量、完整请求 JSON、模型和提示词版本及时间字段。`task_id` 是 UUID 主键，`request_id` 只用于追踪，不是幂等键。

### 7.3 `question_generation.pending_questions`

保存命题自检通过后的不可变待审版本，复合主键为 `task_id + question_id + version`，并以物理外键连接 `generation_tasks`。部分唯一索引 `(task_id, question_id) WHERE superseded_at IS NULL` 保证每题只有一个当前版本，因此读取当前版本不需要计算 `MAX(version)`。

### 7.4 `question_snapshots`

保存不可变的题目版本。解析完成后每道题生成 version 1；修改题目时追加新版本，
不覆盖原题。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string, PK | 命题任务 ID；上传文档题使用解析任务 ID |
| `question_id` | string, PK | 任务内题目 ID |
| `version` | integer, PK | 从 1 开始递增的版本号 |
| `generation_task_id` | UUID, FK, nullable | AI 命题任务的物理外键；上传文档题为空 |
| `source_document_id` | string, FK, nullable | 上传文档来源；AI 命题题目为空 |
| `revision_source` | string | `GENERATED`、`PARSED`、`AI_EDIT` 或 `USER_EDIT` |
| `question_json` | JSONB | 该版本的完整单题 JSON |
| `change_log` | JSONB | 用户要求、审校意见、修改记录和模型信息 |
| `created_at` | timestamp | 创建时间 |

`task_id + question_id + version` 是复合主键。版本为线性递增，不再保存 UUID 版本 ID 或父版本 UUID。

### 7.5 `question_reviews`

每次单题审校追加一条完整记录，不覆盖历史审校结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `review_id` | UUID, PK | 单次审校记录 ID |
| `task_id` | string | 所属命题或解析任务 |
| `question_id` | string | 被审校题目 ID |
| `version` | integer | 被审校的题目版本 |
| `idempotency_key` | string, unique | 调用重试幂等键 |
| `question_json` | JSONB | 审校开始时固定的题目快照 |
| `review_json` | JSONB | 路由、专项检查、错误汇总和耗时 |
| `created_at` | timestamp | 审校时间 |

`task_id + question_id + version` 是指向 `question_snapshots` 的物理复合外键。同一个题目版本可以显式使用不同幂等键重新审校；相同幂等键重试返回原记录。目前尚无
`review_runs` 表，因此整卷审校产生的多条单题记录没有共同的批次 ID。
索引 `task_id + question_id + version + created_at` 支持读取该不可变版本的最新一次审校，不需要扫描整张审校表。

### 7.6 `question_bank`

保存审校通过并完成元数据标注的题目。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `record_id` | UUID, PK | 题库记录 ID |
| `task_id` | string | 来源任务 |
| `question_id` | string | 来源题目 |
| `version` | integer | 来源题目版本 |
| `source_review_id` | UUID, FK | 允许入库的 PASS 审校记录 |
| `question_json` | JSONB | 完整单题、难度和知识点元数据 |
| `created_at` | timestamp | 首次入库时间 |
| `updated_at` | timestamp | 更新时间 |

`task_id + question_id + version` 具有唯一约束并物理外键绑定 `question_snapshots`。同一版本重复入库返回已有记录；新版本可以形成新的题库记录。
索引 `task_id + question_id + created_at` 支持按来源读取最近入库版本。

### 7.7 `assembled_exams`

保存每次组卷尝试的不可变快照。成功、缺题、待复核、业务配额错误以及能够被服务捕获的上游或导出失败都可以形成记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `exam_id` | UUID, PK | 每次组卷执行的独立 ID |
| `created_at` | timestamp | 创建时间 |
| `request_id` | text | 调用方追踪 ID，目前不是幂等键 |
| `subject` | text | 学科 |
| `status` | text | 当次组卷结果状态 |
| `request_json` | JSONB | 完整组卷请求 |
| `report_json` | JSONB | 完整教师报告和验证结果 |
| `student_html` | text | 学生卷 HTML 快照，未形成完整试卷时为空 |
| `answer_html` | text | 教师答案 HTML 快照，未形成完整试卷时为空 |

HTML 以文本内容而不是本地文件路径保存，因此清理输出目录后仍可下载历史试卷。

### 7.8 `assembled_exam_items`

按试卷顺序保存组卷当时的题目内容与答案，不在历史查询时重新读取最新题库。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `exam_id` | UUID, PK/FK | 所属组卷历史，删除父记录时级联删除 |
| `position` | integer, PK | 从 1 开始的题目顺序 |
| `source_json` | JSONB | 题库记录、来源题目和来源版本快照 |
| `student_json` | JSONB | 不含答案的学生题面快照 |
| `answer_json` | JSONB | 教师答案与解析快照 |

`exam_id + position` 是复合主键。`source_json` 刻意不外键绑定 `question_bank`：历史必须在题库记录清理或修订后仍可还原；来源 ID 和版本只用于追溯。

### 7.9 `alembic_version`

Alembic 用该表记录当前数据库迁移版本，不应手动修改。

## 8. 数据关系概览

```text
question_generation.generation_tasks
  -> question_generation.pending_questions（自检通过的待审版本）
  -> question_snapshots（送审时导入的不可变版本）
  -> question_reviews（每次审校追加一条记录）
  -> question_bank（同一版本 PASS 后入库）

exam_documents
  -> question_snapshots（上传文档解析出的初始版本和后续修改版本）

assembled_exams
  -> assembled_exam_items（组卷时的有序题目与答案快照）
```

题目修改不会覆盖旧版本；`task_id + question_id + version` 保存线性版本链，
`source_review_id` 可以追溯题库记录的 PASS 审校来源。

组卷历史与题库是“快照来源”关系而不是数据库外键关系。`assembled_exam_items.source_json` 保存当时使用的 `record_id`、`task_id`、`question_id` 和 `version`，但历史展示和下载只读取已保存快照，避免源题后续变化影响已生成试卷。
