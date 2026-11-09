# Qodex Agent 开发指南

本文件是仓库级 Agent 指令入口。用户使用与启动方式以 `README.md` 为准，设计、接口和验收资料从 `docs/README.md` 进入。进入子目录工作前继续读取该目录内更具体的 `AGENTS.md`；修改 Pi 时必须同时遵守 `pi-coding-agent/AGENTS.md`。

## 当前系统

Qodex main 已合并四个业务模块：

| 模块 | 主要代码 | 服务/工具 |
| --- | --- | --- |
| 自主命题 | `question_generation/` | HTTP 8093；Pi 工具 `question_generation` |
| AI 审校与题库 | `pi-coding-agent/services/exam-checker/` | HTTP 8091；Pi 工具 `exam_checker`、`question_bank` |
| 智能组卷 | `exam_assembly_agent/`、`pi-coding-agent/services/exam-assembly/` | HTTP 8092；Pi 工具 `exam_assembly` |
| Pi Agent | `pi-coding-agent/packages/coding-agent/` | 统一注册和调用业务工具 |

知识库检索已经接入 exam-checker 专项审校。自主命题已支持单题、批量槽位、综合题和按反馈修订，并把自检通过的版本写入 `question_generation.pending_questions`。

不要声称命题到审校已经全自动闭环：当前 exam-checker 尚未自动消费命题待审表。接入时必须保留 `(question_id, version)`，将审校结果绑定不可变题目版本，PASS 后才能写 `question_bank`。

## 服务与脚本

| 名称 | 作用 |
| --- | --- |
| `npm run demo:setup` | 首次创建 Python 环境、安装 Pi 依赖并生成本地环境模板 |
| `npm run demo` | 准备数据库、启动三个服务、健康检查后进入 Pi |
| `npm run demo:db` | 只准备 PostgreSQL、Alembic 迁移和命题待审表 |
| `npm run demo:services` | 只启动三个 Python 服务，不进入 Pi |
| `npm run demo:status` | 检查 8091、8092、8093 健康状态 |
| `scripts/demo.sh` | NPM 演示命令的 Bash 编排实现 |
| `pi-coding-agent/start-exam-checker-db.sh` | 启动 PostgreSQL 并运行 exam-checker 迁移 |
| `pi-coding-agent/start-exam-checker.sh` | 启动 exam-checker，默认端口 8091 |
| `scripts/start-question-generation.sh` | 启动命题服务，默认端口 8093 |
| `scripts/start-exam-assembly.sh` | 启动组卷服务，默认端口 8092 |
| `pi-coding-agent/pi-test.sh` | 从源码启动 Pi |

根目录 `pyproject.toml` 定义 `qodex-exam-assembly-core`，是组卷服务的本地依赖，不得当作冗余文件删除。

## 数据边界

- `question_generation.pending_questions`：命题产生的不可变待审版本。
- `question_versions`：审校侧不可变题目版本。
- `question_reviews`：每次审校的追加记录。
- `question_bank`：仅保存绑定 PASS 审校和同一内容版本的正式题目。
- `research-assets/`：历史研究资料，不是运行时事实来源；复用前核验来源、许可、质量和当前接口。

题目修订不得覆盖旧版本。取题时可以选择最新版本，但开始审校后必须固定具体版本；入库前再次确认 PASS 审校、来源版本和题目快照完全一致。

## 开发与验证

- 以最新 `origin/main` 为基线，在任务分支开发；不要在功能分支之间复制过期接口。
- 优先修改模块内实现，通过明确契约连接命题、审校、题库和组卷。
- 新增或修改数据库结构时使用现有 Alembic/SQL 迁移，不在启动代码里临时建表。
- 真实密钥只放本地环境文件，不写入代码、文档、测试或提交历史。
- 个人计划、调研记录、运行日志和临时数据放在 `.local/`；共享文档放在 `docs/`。
- 保护用户已有改动，只暂存本次任务涉及的明确路径。

按改动范围运行验证：

```bash
python -m unittest discover -s tests
python -m pytest pi-coding-agent/services/exam-checker/tests -q
python -m pytest pi-coding-agent/services/exam-assembly/tests -q

cd pi-coding-agent
npm run check
```

未运行的检查和已知限制必须在交付说明中明确列出。
