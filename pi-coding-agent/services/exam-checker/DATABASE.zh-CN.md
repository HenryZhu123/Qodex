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
    exam_documents ||--o{ question_versions : contains
    exam_documents ||--o{ question_reviews : receives
    exam_documents ||--o{ question_bank : supplies
    question_versions ||--o{ question_versions : parent_of
    question_versions ||--o{ question_reviews : reviewed_as
    question_versions ||--o{ question_bank : stored_as
    question_reviews ||--o| question_bank : approves
```

### 7.1 `exam_documents`

每次成功解析文件后保存一份完整试卷。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `document_id` | string, PK | 本次解析生成的试卷 ID |
| `document_json` | JSONB | 完整试卷层级、题目节点和来源信息 |
| `created_at` | timestamp | 创建时间 |

相同文件重新解析时，目前会生成新的 `document_id`，尚未按文件哈希自动去重。

### 7.2 `question_versions`

保存不可变的题目版本。解析完成后每道题生成 version 1；修改题目时追加新版本，
不覆盖原题。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `version_id` | UUID, PK | 题目版本 ID |
| `document_id` | string, FK | 所属试卷 |
| `question_id` | string | 试卷内题目 ID |
| `version_number` | integer | 从 1 开始递增的版本号 |
| `parent_version_id` | UUID, FK | 上一个版本，初始版本为空 |
| `revision_source` | string | `PARSED`、`AI_EDIT` 或 `USER_EDIT` |
| `question_json` | JSONB | 该版本的完整单题 JSON |
| `change_log` | JSONB | 用户要求、审校意见、修改记录和模型信息 |
| `created_at` | timestamp | 创建时间 |

`document_id + question_id + version_number` 具有唯一约束。

### 7.3 `question_reviews`

每次单题审校追加一条完整记录，不覆盖历史审校结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `review_id` | UUID, PK | 单次审校记录 ID |
| `document_id` | string, FK | 所属试卷 |
| `question_id` | string | 被审校题目 ID |
| `question_version_id` | UUID, FK | 被审校的题目版本 |
| `review_json` | JSONB | 路由、专项检查、错误汇总和耗时 |
| `created_at` | timestamp | 审校时间 |

同一个题目版本可以被审校多次，每次生成不同的 `review_id`。目前尚无
`review_runs` 表，因此整卷审校产生的多条单题记录没有共同的批次 ID。

### 7.4 `question_bank`

保存审校通过并完成元数据标注的题目。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `record_id` | UUID, PK | 题库记录 ID |
| `document_id` | string, FK | 来源试卷 |
| `question_id` | string | 来源题目 |
| `source_review_id` | UUID, FK | 允许入库的 PASS 审校记录 |
| `source_version_id` | UUID, FK | 入库所使用的题目版本 |
| `question_json` | JSONB | 完整单题、难度和知识点元数据 |
| `created_at` | timestamp | 首次入库时间 |
| `updated_at` | timestamp | 更新时间 |

`document_id + question_id` 具有唯一约束，防止同一来源题目重复入库。

### 7.5 `alembic_version`

Alembic 用该表记录当前数据库迁移版本，不应手动修改。

## 8. 数据关系概览

```text
exam_documents
  -> question_versions（初始版本及后续修改版本）
  -> question_reviews（每次审校追加一条记录）
  -> question_bank（审校通过的题目）
```

题目修改不会覆盖旧版本；`parent_version_id` 和 `version_number` 保存完整版本链，
`source_review_id` 和 `source_version_id` 可以追溯题库记录的来源。
