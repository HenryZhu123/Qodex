# Qodex 开发文档

Qodex 面向计算机考研 408，围绕知识库、命题、单题审校和组卷协作。Pi 是运行入口，现有 `exam-checker` 服务提供试题解析、审校与题库能力。

## 当前开发

| 模块 | 当前入口 |
| --- | --- |
| 自主命题 | [模块接口与本地验证台](question-generation.md)；[通用命题主线](question-generalization.md)；[Agent 工作流](agent-workflow.md) |
| Pi 运行与工具集成 | [Pi 源码说明](../pi-coding-agent/README.md) |
| 单题审校与题库 | [exam-checker 服务](../pi-coding-agent/services/exam-checker/README.md)；[命题↔审校接入](QUESTION_GENERATION_REVIEW_INTEGRATION.zh-CN.md) |
| 知识库 | 已接入 exam-checker 专项审校；运行时索引与历史研究资产分开管理 |
| 智能组卷 | [组卷接口契约](ASSEMBLY_CONTRACT.zh-CN.md) 与 [PostgreSQL 历史接口](ASSEMBLY_HISTORY.zh-CN.md) |

> 当前阶段（2026-11-15）：四模块已接成可运行的 Agent 链路（命题 → 审校 → 入库 → 组卷 → 导出），
> 由 Pi 的 `qodex-workflow` 承担政策与护栏。**题目质量层（问题 1）尚未开工**，当前状态与待办以工作区根目录
> `TASK_STATE.md` 为准（仓库外，不随 Git 分发）。

## 设计、接口与验收

- [完整前端工作台与 Windows 本地验收](LOCAL_WEB_TEST.zh-CN.md)
- [AI 命题与 AI 审校接入说明](QUESTION_GENERATION_REVIEW_INTEGRATION.zh-CN.md)
- [AI 审校 Agent 实现方案](AI审校Agent实现方案.md)
- [自主命题模块](question-generation.md)
- [组卷接口契约](ASSEMBLY_CONTRACT.zh-CN.md)
- [组卷历史表与查询下载接口](ASSEMBLY_HISTORY.zh-CN.md)
- [PostgreSQL 与服务接入](POSTGRES_INTEGRATION.zh-CN.md)
- [相似题复核](SIMILARITY_REVIEW.zh-CN.md)
- [模型目录说明](MODEL_CATALOG.zh-CN.md)
- [接口真样本：成功与失败的真实请求/响应](samples/README.md)（四个模块字段对不上时先比对这里）
- [分支合并交接](BRANCH_MERGE_HANDOFF.zh-CN.md)（把 `feat/question-generation` 合入集成分支前必读）
- [验收记录](VALIDATION.zh-CN.md)
- [GitHub 提交说明](GITHUB_SUBMISSION.zh-CN.md)

课程项目指南 PDF 在工作区根目录（`COMP7608B_Final_Project_Student_Guideline.pdf`，仓库外，不随 Git 分发）。

本地开发从同步后的 `main` 建任务分支，不再从旧功能分支复制接口。开发、调研、验收与提交规则见 [AGENTS.md](../AGENTS.md)。

## 文档状态

先按本表判断一份文档描述的是当前实现还是历史阶段。长期目标与工程原则在 [AGENTS.md](../AGENTS.md)；
当前任务、真实进度与恢复方式在工作区根目录的 `TASK_STATE.md`（仓库外，不随 Git 分发）；
各阶段历史记录在 `TASK_STATE_ARCHIVE.md`。

| 文档 | 状态 | 用途 |
| --- | --- | --- |
| [模块接口与待审交接](question-generation.md) | 当前 | 请求契约、服务启动、待审表、规则题与综合题、模型输出与失败诊断 |
| [通用命题主线](question-generalization.md) | 当前主线设计；其中的「当前开发进度」为 2026-11-13 阶段快照 | 通用创作的设计选择、调用方式、取材与验证边界 |
| [通用命题实测](question-generalization-evaluation.md) | 分阶段追加的实测记录（标题带日期） | 冻结清单、完整分母、反例、失败样例与结论边界；不是当前状态摘要 |
| [协议样题](question-generalization-examples.md) | 当前 | 助手自编样题，用于检验接口与判据，不是模型产出证据 |
| [Agent 工作流](agent-workflow.md) | 当前 | 四模块接线、政策/护栏、7 次真实链路与已知边界 |
| [工作流目标形态](workflow-target.md) | 目标规格 | Goal/Item/Attempt 三层与差距表；标「已实现」的才是现状 |
| [AI 命题与 AI 审校接入](QUESTION_GENERATION_REVIEW_INTEGRATION.zh-CN.md) | 当前 | `task_id + question_id + version` 身份、数据库表与状态流 |
| [五考点 v1.1 实验说明](question-authoring.md) | 历史快照 | 2026-11-09 阶段的十组实验；文中「目前/本轮」仅指该阶段 |
| [五考点 v1.1 设计说明](question-generation-design.md) | 历史快照 | 同阶段的设计与验证记录，不含通用路径 |
| [自主命题模块通俗介绍](overview.md) | 面向非技术读者的说明；开头带 2026-11-15 现状补充 | 给老师和非技术同学；**AI / 开发会话可跳过** |

历史快照保留可追溯性，不随实现更新。若与代码冲突，以代码和可复现验证为准。

## 本地开发环境

- Pi 使用 Node.js 22.19.0 或以上。在 `pi-coding-agent/` 运行 `npm ci --ignore-scripts` 安装锁定依赖。首次从源码启动前运行 `npm run hydrate:model-data` 获取本地模型目录，可用 `./pi-test.sh --no-env --help` 检查启动入口。修改 Pi 代码时按 [Pi 开发纪律](../pi-coding-agent/AGENTS.md) 运行检查。
- 联调审校服务时使用 Python 3.11 或以上，按 [服务启动说明](../pi-coding-agent/services/exam-checker/README.md) 配置虚拟环境、PostgreSQL 与本地模型凭据。数据库表结构见 [数据库说明](../pi-coding-agent/services/exam-checker/DATABASE.zh-CN.md)。
- 个人计划、问题修复流水、调研笔记与临时产物存放在 `.local/`。

## 历史研究资料

[根目录 README](../README.md) 保留原有项目结构与启动说明。更早的 README、设计草案、Prompt、数据集和评测结果在 [研究资料目录](../research-assets/README.md)。选用历史资产前核验其来源、质量、许可及与当前接口的兼容性。
