# Qodex

Qodex 是面向计算机考研 408 的 AI 试题工作流，当前仓库已经合并自主命题、知识库辅助审校、单题审校、正式题库和组卷能力。Pi 是统一的 Agent 入口，各 Python 服务通过本机 HTTP 接口协作。

## 当前能力

| 模块 | 已实现能力 | Pi 工具 | 默认地址 |
| --- | --- | --- | --- |
| 自主命题 | 单选题、批量槽位命题、综合应用题、按反馈修订、确定性自检、待审版本入队 | `question_generation` | `http://127.0.0.1:8093` |
| AI 审校 | PDF/DOC/DOCX 解析、整卷/单题审校、九类专项检查、知识库检索、题目版本修订 | `exam_checker` | `http://127.0.0.1:8091` |
| 正式题库 | 查询审校通过题目，按学科、题型、难度、知识点和关键词检索 | `question_bank` | 复用 8091 |
| 智能组卷 | 从正式题库选题、约束校验、缺题报告、相似题复核、HTML/PDF 导出 | `exam_assembly` | `http://127.0.0.1:8092` |
| Pi Agent | 注册上述内置工具并组织调用 | — | 终端交互 |

当前边界：命题服务已经能把自检通过的题目写入 PostgreSQL 待审队列，但 exam-checker 还没有自动消费该队列。现阶段仍需增加“待审题登记 → 绑定题目版本 → 审校 → PASS 入正式题库”的接入层，才能形成全自动闭环。

## 目录结构

```text
.
├── question_generation/                   # 自主命题、修订、验证台和待审表 SQL
├── exam_assembly_agent/                   # 组卷核心、导出和相似题逻辑
├── pi-coding-agent/
│   ├── packages/coding-agent/src/extensions/
│   │   ├── question-generation/           # Pi 命题工具
│   │   ├── exam-checker/                  # Pi 审校和题库工具
│   │   └── exam-assembly/                 # Pi 组卷工具
│   └── services/
│       ├── exam-checker/                  # 审校、题库、PostgreSQL 迁移
│       └── exam-assembly/                 # 组卷 HTTP 服务
├── scripts/                               # 根项目服务启动脚本
├── docs/                                  # 设计、接口、部署和验收文档
├── tests/                                 # 命题模块测试
└── research-assets/                       # 历史研究资料
```

根目录 `pyproject.toml` 不是启动脚本；它定义 `qodex-exam-assembly-core` Python 包，组卷 HTTP 服务依赖该包，因此需要保留。

## 环境要求

- Python 3.11 或更高版本
- Node.js 22.19.0 或更高版本
- Docker Desktop 与 Docker Compose
- PostgreSQL 客户端可选；建待审表也可以通过 Docker 内的 `psql` 完成

## 1. 安装 Python 依赖

在仓库根目录创建共享开发环境：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e . -e 'pi-coding-agent/services/exam-assembly[pdf]'
python -m pip install -r question_generation/service-requirements.txt
```

exam-checker 使用自己的虚拟环境，便于现有启动脚本定位：

```bash
python3.11 -m venv pi-coding-agent/services/exam-checker/.venv
pi-coding-agent/services/exam-checker/.venv/bin/pip install -e 'pi-coding-agent/services/exam-checker[dev]'
cp pi-coding-agent/services/exam-checker/.env.example pi-coding-agent/.env
```

编辑 `pi-coding-agent/.env`，填写模型和 MinerU 配置。真实 API Key 不得提交到 Git。

## 2. 启动 PostgreSQL

```bash
cd pi-coding-agent
./start-exam-checker-db.sh
cd ..
```

默认连接信息：

```text
Host: 127.0.0.1
Port: 5433
Database: qodex
User: qodex
Password: qodex-local
```

为命题待审队列建表：

```bash
docker compose -f pi-coding-agent/services/exam-checker/compose.yaml \
  exec -T postgres psql -U qodex -d qodex \
  < question_generation/sql/001_pending_questions.sql
```

数据库结构详见 [exam-checker 数据库说明](pi-coding-agent/services/exam-checker/DATABASE.zh-CN.md)。

## 3. 启动服务

建议按以下顺序分别在不同终端启动。

### exam-checker：8091

```bash
cd pi-coding-agent
./start-exam-checker.sh
```

脚本会读取 `pi-coding-agent/.env`、执行 Alembic 迁移，然后启动审校服务。

### question-generation：8093

```bash
source .venv/bin/activate
export QUESTION_GENERATION_DATABASE_URL='postgresql://qodex:qodex-local@127.0.0.1:5433/qodex'
./scripts/start-question-generation.sh
```

不连接数据库、只验证本地命题时，可以使用：

```bash
python -m question_generation question_generation/examples/paging.json
python -m question_generation.ui
```

本地验证台默认地址为 `http://127.0.0.1:8765/`。

### exam-assembly：8092

```bash
source .venv/bin/activate
./scripts/start-exam-assembly.sh
```

组卷服务默认通过 `http://127.0.0.1:8091` 查询正式题库，可用 `QUESTION_BANK_SERVICE_URL` 覆盖。

## 4. 启动 Pi

首次安装：

```bash
cd pi-coding-agent
npm ci --ignore-scripts
npm run hydrate:model-data:release
```

启动：

```bash
./pi-test.sh
```

合并后的 main 会自动注册：

- `question_generation`：`single`、`batch`、`comprehensive`、`revise`
- `exam_checker`：`review_file`、`review_document`、`review_question`、`revise_question`、`get_question_state`
- `question_bank`：`get_question`、`search_questions`
- `exam_assembly`：提交组卷请求并返回试卷或缺题结果

## 常用检查

```bash
python -m unittest discover -s tests
python -m pytest pi-coding-agent/services/exam-checker/tests -q
python -m pytest pi-coding-agent/services/exam-assembly/tests -q

cd pi-coding-agent
npm run check
```

更多设计、接口和验收资料从 [项目开发文档](docs/README.md) 进入。Agent 开发约定见 [AGENTS.md](AGENTS.md)。
