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
| 计算机组成原理 | [直接映射 Cache 地址拆分](../question_generation/examples/cache.json) | 用位切片独立复算标记、行号和块内偏移 |
| 计算机网络 | [IPv4 子网网络地址](../question_generation/examples/subnet.json) | 用 Python 标准库独立复算网络地址 |

分页题按字节寻址，页大小为 2 的幂，题面所列映射均有效。生成器拆分虚页号和页内偏移，用页表查出物理页框号，保留页内偏移。[OSTEP 分页章节](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-paging.pdf)

出栈题设定初始空栈且容量足够，元素按 1 至 n 的顺序各入栈一次。生成器按相对次序分类。如果候选序列依次出现 a、b、c，且 b < c < a，先弹出 a 就已让 c 入栈，随后 c 会挡住 b。自检用另一种方法逐项模拟四个选项，并要求唯一可达的序列与答案 ID 一致。[Princeton 栈练习](https://algs4.cs.princeton.edu/13stacks/index.php) · [Python 栈操作说明](https://docs.python.org/3/tutorial/datastructures.html#using-lists-as-stacks)

Cache 题使用 16 位字节地址。题面给出数据容量及块大小，每行存一块。生成器先按块大小取商和余数，再将主存块号除以行数，得到标记和行号。自检从地址位字段独立提取这三个值。[MIT 6.004 缓存讲义](https://ocw.mit.edu/courses/6-004-computation-structures-spring-2017/pages/c14/c14s1/)

IPv4 子网题给出地址和 CIDR 前缀长度。生成器将地址向下对齐到所属地址块的起点，使用标准库 `IPv4Network` 独立检查答案。[RFC 4632 §3.1](https://www.rfc-editor.org/rfc/rfc4632.html#section-3.1) · [Python ipaddress](https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Network)

### 本地运行

从仓库根目录运行以下命令。需要 Python 3.9 或更新版本，依赖为 Python 标准库。

```bash
python3 -m question_generation question_generation/examples/paging.json
python3 -m question_generation question_generation/examples/stack.json
python3 -m question_generation question_generation/examples/cache.json
python3 -m question_generation question_generation/examples/subnet.json
python3 -m unittest discover -s tests
```

样例均把 UTF-8 JSON 结果写到标准输出。成功退出码为 0，命题失败退出码为 1。重复使用同一个请求、生成器和 Python 版本可重放同一道题。修改示例中的 `seed` 可生成另一变体。Python 调用方也可以使用 `question_generation.generation.generate_question(payload)`。

### 浏览器验证台

在仓库根目录运行 `python3 -m question_generation.ui`，打开 [本地验证台](http://127.0.0.1:8765/)。验证台只在本机监听，可用 `--port` 更换端口。按 Ctrl+C 停止。

| 预设 | 预期结果 |
| --- | --- |
| 标准样例 | 生成并自检一道题。教师答案、逐项解析和完整 JSON 可分别展开 |
| 分页 · 零偏移 | 仍有四个互异选项，和答案碰撞的干扰项被另一条错误规则替换 |
| 出栈序列 · 最少元素 | 以 4 个元素生成四个互异选项，只有一个序列可达 |
| Cache · 块边界 | 地址为 `0x1230`，块内偏移为 0，仍有四个互异选项 |
| IPv4 · 子网起点 | 地址 `10.23.45.64/26` 的主机位已经为零，网络地址仍为 `10.23.45.64` |
| 缺少材料 | 返回 `NEEDS_MATERIAL`，显示缺失的规则，无题目 |
| 分页 · 非法页大小 | 以 300 B 发出请求，返回 `INVALID_REQUEST`，无题目 |
| 出栈序列 · 非法元素个数 | 以 3 个元素发出请求，返回 `INVALID_REQUEST`，无题目 |
| Cache · 非法块大小 | 以 24 B 发出请求，返回 `INVALID_REQUEST`，无题目 |
| IPv4 · 超出前缀范围 | 以 `/31` 发出请求，返回 `INVALID_REQUEST`，无题目 |

从题型下拉框切换样例，可调整种子、该题型的参数和材料规则覆盖。验证台复用命令行入口的命题逻辑，题目保留待独立审校状态。Pi、真实知识库、独立审校、入库和组卷在后续接入阶段验收。

### 请求

请求使用 UTF-8 JSON。

| 字段 | v0.1 约定 |
| --- | --- |
| `schema_version`、`request_id` | 版本为字符串 `0.1`，请求 ID 为非空字符串 |
| `subject`、`topic` | 分页使用 `operating_systems`、`single_level_paging`。出栈序列使用 `data_structures`、`stack_pop_sequence`。Cache 使用 `computer_organization`、`direct_mapped_cache`。IPv4 使用 `computer_networks`、`ipv4_subnet_network_address` |
| `question_type` | `single_choice`，每次生成一道题 |
| `seed` | 0 至 4294967295 的整数，用于复现生成与选项顺序 |
| `constraints` | 可省略。分页的 `page_size` 为 2 至 65536 字节之间的 2 的幂，默认 256。`offset` 可省略，显式给出时须为 0 至 `page_size - 1` 的整数。出栈序列的 `element_count` 为 4 至 6 的整数，默认 5 |
| `evidence` | 材料数组。每条含唯一 `id`、来源 `source`、`version`、定位 `anchor`、材料摘要 `summary` 和标记数组 `rules`。分页要求 `split_address`、`map_virtual_page`、`preserve_offset`。出栈序列要求 `stack_push_top`、`stack_pop_top` |

材料由调用方预先核验并标记。模块检查字段、出处元数据及规则覆盖，使用内置规则求解。材料摘要的语义和引用可访问性由提供方核验。省略材料或传入空数组会得到缺材料结果。

Cache 的 `cache_size` 与 `block_size` 均为 2 的幂。数据容量支持 16–4096 B（默认 256 B），块大小支持 4–256 B（默认 16 B），且至少有两行。可选 `address` 为 0–65535 的整数，省略时由种子决定。材料须覆盖 `cache_byte_offset`、`cache_line_index`、`cache_tag`。

IPv4 的 `prefix_length` 支持 16–30，默认 26。可选 `ipv4_address` 为标准点分十进制字符串，省略时从 `10.0.0.0/8` 以种子选取。材料须覆盖 `ipv4_cidr_prefix` 和 `ipv4_subnet_alignment`。[RFC 1918 §3](https://www.rfc-editor.org/rfc/rfc1918.html#section-3)

### 输出与验收

成功时返回 `GENERATED` 和一个含一道题的 `questions` 数组。面向学生的输出使用 `student_view`，含题干和带稳定 ID 的四个选项。教师视图提供答案 ID、解法和逐项说明。题目包还记录生成器版本、种子、实际题设、出处、自检结果和 `PENDING` 审校状态。选项显示字母可按顺序分配，答案按 ID 关联。

失败时返回 `INVALID_REQUEST`、`UNSUPPORTED_REQUEST`、`NEEDS_MATERIAL` 或 `SELF_CHECK_FAILED`，附原因及空题目列表。材料不足时列出缺失的规则。未知请求字段视为无效，避免忽略约束。

手算对照使用 256 B 页、虚拟地址 `0x02B4` 和映射 `VPN 2 → PFN 5`。虚页号为 2，偏移为 `0xB4`，物理地址为 `0x05B4`。同一映射下，虚拟地址 `0x0200` 的正确结果为 `0x0500`，此时“丢弃偏移”会与正确答案重合，必须换一个干扰项。

出栈序列样例以 1 至 5 入栈。先压入 1 至 4，再弹出 4，随后压入并弹出 5，依次弹出剩余元素，得到 `4、5、3、2、1`。例如 `4、1、2、3、5` 无法出现，因为弹出 4 后，1 仍在 2 的下方。

Cache 样例中 256 B 数据容量与 16 B 块大小给出 16 行。地址 `0x1234` 的主存块号为 `0x123`，块内偏移为 4。块号除以 16，商为 18，余数为 3，因此十进制答案为 `18、3、4`。

IPv4 样例 `10.23.45.77/26` 有 6 位主机位，最后一个八位组按 64 个地址为一块。77 落在 64–127，因此网络地址为 `10.23.45.64`。

## 本地批量命题契约 v0.1

从仓库根目录运行四科混合样例。Python 调用方可直接使用 `question_generation.batch.generate_batch(payload)`。

```bash
python3 -m question_generation --batch question_generation/examples/batch.json
```

请求使用原有的 `schema_version`、`request_id` 和 `seed`，另提供 `question_count`（1–100）、`total_score`（正整数）和非空 `slots` 数组。每个槽位包含批内唯一的 `slot_id`、正整数 `count` 和 `score_per_question`，以及单题契约的 `subject`、`topic`、`question_type`、可选 `constraints` 与 `evidence`。各槽位题数之和必须等于总题量，题数乘单题分值的合计必须等于总分。

批量调用逐题复用单题生成与自检，核对科目、考点、题型及分值，再在结果题目包上记录 `slot_id` 和 `metadata.score`。同一批中，按 Unicode NFKC 和空白折叠后的题干去重。相同题设只保留一次，换种子、题目 ID、选项内容或顺序、分值都不会形成新题。单题请求及其题目包沿用上节契约。

每个槽位最多尝试 `8 × count` 次。分配在本次候选池中尽量填满槽位，同一道题只能归一个槽位。遇到候选重叠时，可替换先前分配的题来填后续槽位。缺口只反映本次候选池及尝试预算。

| 状态 | 结果 | 命令行退出码 |
| --- | --- | --- |
| `GENERATED` | 所有槽位均已填满 | 0 |
| `PARTIAL` | 返回已生成的合格题，并列出每个未填满槽位的缺口 | 1 |
| `NO_QUESTIONS` | 没有合格题，仍返回槽位缺口 | 1 |
| `INVALID_REQUEST` | 批量请求结构无效或题数、总分与配额冲突 | 1 |

有效请求的结果包括请求和实际生成的题数与分值，以及 `deficits` 数组。每项缺口记录槽位、要求数量、实际数量、缺失数量、尝试次数、去重后的候选数和原因。缺材料时会列出缺失的规则。

混合样例预期生成 5 题、11 分。复验部分成功时，将样例中栈槽位的 `evidence` 清空，把固定地址的 Cache 槽位 `count` 改为 2，并将总题量、总分改为 6 和 14。预期得到 4 题、9 分，栈因缺材料少 1 题，Cache 因相同题设去重少 1 题。示例和入口见 [批量请求](../question_generation/examples/batch.json)。
