# 自主命题模块

自主命题面向 408 专项练习和模拟卷补题。模块依据题型、考点和可追溯的资料生成题目、参考答案和解析，完成自检后交由独立审校。收到审校反馈时修订题目并重新自检。

| 职责 | 边界 |
| --- | --- |
| 命题与自检 | 设计题目和考法，校验题面、答案及解析，提供可定位的依据 |
| 知识库 | 提供知识点和引用材料，命题以结构化输入接收 |
| 单题审校 | 独立给出审校结论，自检结果与审校结论分别记录 |
| 组卷 | 提供缺题槽位及分值约束，管理整卷蓝图和整卷验证 |
| Pi | 组织工具调用，传递材料和反馈，协调重试与交付 |

现有 [自主命题设计稿](../research-assets/docs/feature-designs/question-generation-agent.md) 提出了单选题、综合应用题及生成和修订接口。当前基线尚无独立命题服务。对接时以实际服务接口和经团队确认的契约为准。模块文档随已实现能力更新，个人开发计划和调研过程放在 `.local/question-generation/`。

## 工作区与依赖分支

从仓库根目录运行 `git status --short --branch` 可以确认当前分支。本地命题代码在 `feat/question-generation` 开发。`git fetch origin` 更新本地对远程分支的记录，当前分支和工作文件保持原样。`main` 是团队集成基线，`origin/main` 是最近一次获取的远程主分支记录。

以下是 2026-11-08 核对的代码快照。开始联调前重新获取远程记录并核对接口。

| 分支和版本 | 已有能力 | 对命题的影响 |
| --- | --- | --- |
| `origin/main` · `4b1aabe` | [PostgreSQL 和数据库迁移](../pi-coding-agent/services/exam-checker/DATABASE.zh-CN.md)、审校和正式题库接口，以及 SQLite 参考题资产 | 生成草稿可以接收本地材料。通过独立审校后，由审校服务写入正式题库 |
| `origin/exam-checker` · `db50295` | 该版本已包含在 `main` 的历史中。当前[单题审校入口](../pi-coding-agent/services/exam-checker/src/exam_checker/api/app.py#L302)需要已有文档 ID 和题目 ID | 结构化新题如何直接送审，是接通正式入库前需要核实的接口 |
| `origin/Knowledge-base` · `3a993a2` | 未合入 `main` 的[教材检索实现](https://github.com/HenryZhu123/hku_agent/blob/3a993a2/pi-coding-agent/services/exam-checker/src/exam_checker/integrations/knowledge_base.py#L156)，目前接在审校内部 | 命题先接收结构化的证据材料。接入真实检索时，核实如何按考点取材并保留出处 |
| `origin/exam-assembly` · `c891810` | 未合入 `main` 的[组卷补题契约](https://github.com/HenryZhu123/hku_agent/blob/c891810/ASSEMBLY_CONTRACT.zh-CN.md#L30)，组卷已能通过审校服务查正式题库，并返回结构化缺题请求 | 可以用缺题请求样例验证命题输入，正式补题仍需经过审校、入库和重新组卷 |

[SQLite 参考题](../research-assets/skills/build-knowledge-base/references/reference-question-bank.md)可作为考法示例，当前记录尚未附审校状态。PostgreSQL 的 `question_bank` 用于保存通过审校的题目及其来源版本。命题模块通过服务接口交接题目，自检和独立审校分别记录。

## 独立开发与联调

- 用本地证据样例走通单选题生成和自检。最小链路可以验证输入约束、题目与解答格式、材料出处，以及资料不足时的返回。运行这条链路无需启动 PostgreSQL。
- 需要验证其他分支时，先阅读实际接口和测试。需要运行对方代码时，在独立 Git 工作树检出固定提交，并为联调使用独立的测试库。日常命题工作继续留在 `feat/question-generation`。
- 正式联调先核对结构化新题能否送审、入库并回读，再接真实知识检索和组卷补题。现有接口和样例足够时可以独立推进。只有需要上游新增接口、统一共享字段或修改数据库结构时，才提交具体的最小协作事项。
