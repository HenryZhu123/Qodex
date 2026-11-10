# Qodex 开发文档

Qodex 面向计算机考研 408，围绕知识库、命题、单题审校和组卷协作。Pi 是运行入口，现有 `exam-checker` 服务提供试题解析、审校与题库能力。

## 当前开发

| 模块 | 当前入口 |
| --- | --- |
| 自主命题 | [当前开发进度与接续顺序](question-generalization.md#当前开发进度)、[试题台](question-generation.md#浏览器试题台)、[评测](question-generalization-evaluation.md)、[协议样题](question-generalization-examples.md) |
| Pi 运行与工具集成 | [Pi 源码说明](../pi-coding-agent/README.md) |
| 单题审校与题库 | [exam-checker 服务](../pi-coding-agent/services/exam-checker/README.md) |
| 知识库、组卷 | 已有集成版本。对接时核对 [依赖版本与接口](question-generation.md#工作区与依赖分支) |

本地开发从同步后的 `main` 建任务分支。自主命题分支为 `feat/question-generation`。开发、调研、验收与提交规则见 [AGENTS.md](../AGENTS.md)。

## 文档状态

先按本表判断一份文档是否描述当前实现。长期目标与工程原则在 [AGENTS.md](../AGENTS.md)；当前任务、真实进度与恢复方式在工作区根目录的 `TASK_STATE.md`（仓库外，不随 Git 分发）。

| 文档 | 状态 | 用途 |
| --- | --- | --- |
| [通用命题主线](question-generalization.md) | 当前 | 通用创作的设计选择、调用方式、取材与验证边界、接续顺序 |
| [通用命题实测](question-generalization-evaluation.md) | 当前（按阶段追加） | 冻结清单、完整分母、反例、失败样例与结论边界 |
| [模块接口与待审交接](question-generation.md) | 当前 | 请求契约、服务启动、待审表、规则题与综合题 |
| [协议样题](question-generalization-examples.md) | 当前 | 助手自编样题，用于检验接口与判据，不是模型产出证据 |
| [五考点 v1.1 实验说明](question-authoring.md) | 历史快照 | 2026-11-09 阶段的十组实验；文中"目前/本轮"仅指该阶段 |
| [五考点 v1.1 设计说明](question-generation-design.md) | 历史快照 | 同阶段的设计与验证记录，不含通用路径 |

历史快照保留可追溯性，不随实现更新。若与代码冲突，以代码和可复现验证为准。

## 本地开发环境

- Pi 使用 Node.js 22.19.0 或以上。在 `pi-coding-agent/` 运行 `npm ci --ignore-scripts` 安装锁定依赖。首次从源码启动前运行 `npm run hydrate:model-data` 获取本地模型目录，可用 `./pi-test.sh --no-env --help` 检查启动入口。修改 Pi 代码时按 [Pi 开发纪律](../pi-coding-agent/AGENTS.md) 运行检查。
- 联调审校服务时使用 Python 3.11 或以上，按 [服务启动说明](../pi-coding-agent/services/exam-checker/README.md) 配置虚拟环境、PostgreSQL 与本地模型凭据。数据库表结构见 [数据库说明](../pi-coding-agent/services/exam-checker/DATABASE.zh-CN.md)。
- 命题模块的单元测试只需 Python 标准库：从仓库根目录运行 `python3 -m unittest discover -s tests`。
- 个人计划、问题修复流水、调研笔记与临时产物存放在 `.local/`。

## 历史研究资料

[根目录 README](../README.md) 保留原有项目结构与启动说明。更早的 README、设计草案、Prompt、数据集和评测结果在 [研究资料目录](../research-assets/README.md)。选用历史资产前核验其来源、质量、许可及与当前接口的兼容性。
