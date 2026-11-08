# 自主命题模块

自主命题面向 408 专项练习和模拟卷补题。模块依据题型、考点和可追溯的资料生成题目、参考答案和解析，完成自检后交由独立审校。收到审校反馈时修订题目并重新自检。

| 职责 | 边界 |
| --- | --- |
| 命题与自检 | 设计题目和考法，校验题面、答案及解析，提供可定位的依据 |
| 知识库 | 提供知识点和引用材料，命题以结构化输入接收 |
| 单题审校 | 独立给出审校结论，自检结果与审校结论分别记录 |
| 组卷 | 提供缺题槽位及分值约束，管理整卷蓝图和整卷验证 |
| Pi | 组织工具调用，传递材料和反馈，协调重试与交付 |

现有 [自主命题设计稿](../research-assets/docs/feature-designs/question-generation-agent.md) 提出了单选题、综合应用题及生成和修订接口。短期 S1–S3 已验收，L1 的单选题通过同一命令行入口和浏览器验证台生成。对接时以实际服务接口和经团队确认的契约为准。个人开发计划和调研过程放在 `.local/question-generation/`。

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

## 本地命题契约 v0.1

| 科目 | 单选题型 | 自检 |
| --- | --- | --- |
| 操作系统 | [单级页表地址转换](../question_generation/examples/paging.json) | 用位运算独立复算物理地址 |
| 数据结构 | [单栈出栈序列判定](../question_generation/examples/stack.json) | 逐项模拟入栈与出栈，检查可达性和答案唯一性 |
| 计算机组成原理 | 待扩展 | — |
| 计算机网络 | 待扩展 | — |

分页题按字节寻址，页大小为 2 的幂，题面所列映射均有效。生成器拆分虚页号和页内偏移，用页表查出物理页框号，保留页内偏移。[OSTEP 分页章节](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-paging.pdf)

出栈题设定初始空栈且容量足够，元素按 1 至 n 的顺序各入栈一次。生成器按相对次序分类。如果候选序列依次出现 a、b、c，且 b < c < a，先弹出 a 就已让 c 入栈，随后 c 会挡住 b。自检用另一种方法逐项模拟四个选项，并要求唯一可达的序列与答案 ID 一致。[Princeton 栈练习](https://algs4.cs.princeton.edu/13stacks/index.php) · [Python 栈操作说明](https://docs.python.org/3/tutorial/datastructures.html#using-lists-as-stacks)

### 本地运行

从仓库根目录运行以下命令。需要 Python 3.9 或更新版本，依赖为 Python 标准库。

```bash
python3 -m question_generation question_generation/examples/paging.json
python3 -m question_generation question_generation/examples/stack.json
python3 -m unittest discover -s tests
```

两道样例均把 UTF-8 JSON 结果写到标准输出。成功退出码为 0，命题失败退出码为 1。重复使用同一个请求、生成器和 Python 版本可重放同一道题。修改示例中的 `seed` 可生成另一变体。Python 调用方也可以使用 `question_generation.generation.generate_question(payload)`。

### 浏览器验证台

在仓库根目录运行 `python3 -m question_generation.ui`，打开 [本地验证台](http://127.0.0.1:8765/)。验证台只在本机监听，可用 `--port` 更换端口。按 Ctrl+C 停止。

| 预设 | 预期结果 |
| --- | --- |
| 标准样例 | 生成并自检一道题。教师答案、逐项解析和完整 JSON 可分别展开 |
| 分页 · 零偏移 | 仍有四个互异选项，和答案碰撞的干扰项被另一条错误规则替换 |
| 出栈序列 · 最少元素 | 以 4 个元素生成四个互异选项，只有一个序列可达 |
| 缺少材料 | 返回 `NEEDS_MATERIAL`，显示缺失的规则，无题目 |
| 分页 · 非法页大小 | 以 300 B 发出请求，返回 `INVALID_REQUEST`，无题目 |
| 出栈序列 · 非法元素个数 | 以 3 个元素发出请求，返回 `INVALID_REQUEST`，无题目 |

从题型下拉框切换样例，可调整种子、该题型的参数和材料规则覆盖。验证台复用命令行入口的命题逻辑，题目保留待独立审校状态。Pi、真实知识库、独立审校、入库和组卷在后续接入阶段验收。

### 请求

请求使用 UTF-8 JSON。

| 字段 | v0.1 约定 |
| --- | --- |
| `schema_version`、`request_id` | 版本为字符串 `0.1`，请求 ID 为非空字符串 |
| `subject`、`topic` | 分页使用 `operating_systems`、`single_level_paging`。出栈序列使用 `data_structures`、`stack_pop_sequence` |
| `question_type` | `single_choice`，每次生成一道题 |
| `seed` | 0 至 4294967295 的整数，用于复现生成与选项顺序 |
| `constraints` | 可省略。分页的 `page_size` 为 2 至 65536 字节之间的 2 的幂，默认 256。`offset` 可省略，显式给出时须为 0 至 `page_size - 1` 的整数。出栈序列的 `element_count` 为 4 至 6 的整数，默认 5 |
| `evidence` | 材料数组。每条含唯一 `id`、来源 `source`、`version`、定位 `anchor`、材料摘要 `summary` 和标记数组 `rules`。分页要求 `split_address`、`map_virtual_page`、`preserve_offset`。出栈序列要求 `stack_push_top`、`stack_pop_top` |

材料由调用方预先核验并标记。模块检查字段、出处元数据及规则覆盖，使用内置规则求解。材料摘要的语义和引用可访问性由提供方核验。省略材料或传入空数组会得到缺材料结果。

### 输出与验收

成功时返回 `GENERATED` 和一个含一道题的 `questions` 数组。面向学生的输出使用 `student_view`，含题干和带稳定 ID 的四个选项。教师视图提供答案 ID、解法和逐项说明。题目包还记录生成器版本、种子、实际题设、出处、自检结果和 `PENDING` 审校状态。选项显示字母可按顺序分配，答案按 ID 关联。

失败时返回 `INVALID_REQUEST`、`UNSUPPORTED_REQUEST`、`NEEDS_MATERIAL` 或 `SELF_CHECK_FAILED`，附原因及空题目列表。材料不足时列出缺失的规则。未知请求字段视为无效，避免忽略约束。

手算对照使用 256 B 页、虚拟地址 `0x02B4` 和映射 `VPN 2 → PFN 5`。虚页号为 2，偏移为 `0xB4`，物理地址为 `0x05B4`。同一映射下，虚拟地址 `0x0200` 的正确结果为 `0x0500`，此时“丢弃偏移”会与正确答案重合，必须换一个干扰项。

出栈序列样例以 1 至 5 入栈。先压入 1 至 4，再弹出 4，随后压入并弹出 5，依次弹出剩余元素，得到 `4、5、3、2、1`。例如 `4、1、2、3、5` 无法出现，因为弹出 4 后，1 仍在 2 的下方。
