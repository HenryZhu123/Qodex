# Qodex 开发文档

Qodex 面向计算机考研 408，围绕知识库、命题、单题审校和组卷协作。Pi 是运行入口，现有 `exam-checker` 服务提供试题解析、审校与题库能力。

## 当前开发

| 模块 | 当前入口 |
| --- | --- |
| 自主命题 | [模块说明与本地验证台](question-generation.md#浏览器验证台)。支持单题、批量槽位、综合题、修订、自检和待审入队 |
| Pi 运行与工具集成 | [Pi 源码说明](../pi-coding-agent/README.md) |
| 单题审校与题库 | [exam-checker 服务](../pi-coding-agent/services/exam-checker/README.md) |
| 知识库 | 已接入 exam-checker 专项审校；运行时索引与历史研究资产分开管理 |
| 智能组卷 | [组卷接口契约](ASSEMBLY_CONTRACT.zh-CN.md) 与 [PostgreSQL 历史接口](ASSEMBLY_HISTORY.zh-CN.md) |

## 设计、接口与验收

- [AI 审校 Agent 实现方案](AI审校Agent实现方案.md)
- [自主命题模块](question-generation.md)
- [组卷接口契约](ASSEMBLY_CONTRACT.zh-CN.md)
- [组卷历史表与查询下载接口](ASSEMBLY_HISTORY.zh-CN.md)
- [PostgreSQL 与服务接入](POSTGRES_INTEGRATION.zh-CN.md)
- [相似题复核](SIMILARITY_REVIEW.zh-CN.md)
- [模型目录说明](MODEL_CATALOG.zh-CN.md)
- [验收记录](VALIDATION.zh-CN.md)
- [GitHub 提交说明](GITHUB_SUBMISSION.zh-CN.md)
- [课程项目指南](COMP7608B_LLM_Project_Guideline.pdf)

本地开发从同步后的 `main` 建任务分支，不再从旧功能分支复制接口。开发、调研、验收与提交规则见 [AGENTS.md](../AGENTS.md)。

## 本地开发环境

- Pi 使用 Node.js 22.19.0 或以上。在 `pi-coding-agent/` 运行 `npm ci --ignore-scripts` 安装锁定依赖。首次从源码启动前运行 `npm run hydrate:model-data` 获取本地模型目录，可用 `./pi-test.sh --no-env --help` 检查启动入口。修改 Pi 代码时按 [Pi 开发纪律](../pi-coding-agent/AGENTS.md) 运行检查。
- 联调审校服务时使用 Python 3.11 或以上，按 [服务启动说明](../pi-coding-agent/services/exam-checker/README.md) 配置虚拟环境、PostgreSQL 与本地模型凭据。数据库表结构见 [数据库说明](../pi-coding-agent/services/exam-checker/DATABASE.zh-CN.md)。
- 个人计划、问题修复流水、调研笔记与临时产物存放在 `.local/`。

## 历史研究资料

[根目录 README](../README.md) 保留原有项目结构与启动说明。更早的 README、设计草案、Prompt、数据集和评测结果在 [研究资料目录](../research-assets/README.md)。选用历史资产前核验其来源、质量、许可及与当前接口的兼容性。
