# 面向408全范围的通用创作（实验阶段）

新路径把考查范围、材料获取、题目设计与可执行验证分开：具体考点无需新增生成函数；单选和综合题使用同一个引擎。原规则题及五考点创作保持不变。章节导航覆盖四科，不等于完整考纲的内容质量已经验证。

[样题](question-generalization-examples.md)包括八道接口测试题、两道依据网络补充材料编写的题和一道跨科环形缓冲区题，均由开发助手编写。模型实测另见[评测报告](question-generalization-evaluation.md)。

## 当前开发进度

更新于 2026-11-10。自主命题已经可以从粗需求生成单选或综合题，并将通过自检的题包交给审校。当前仍处于质量验证阶段，完整 408 考纲的逐项材料覆盖和生产模型的成题可用率尚待验证。

| 主线 | 已实现 | 已有验证 |
| --- | --- | --- |
| 需求细化与创作 | `author` 接受自然语言、参考材料或无指定方向的请求。单次生成一道题，计划可关联 1 至 4 个互异章节，至少一个属于主科目。调用方明确指定的范围、题型、分值和要求进入计划、创作与审计。 | 四科两题型的 8 个粗需求题包通过 HTTP 与临时 PostgreSQL 精确回读和重试去重，使用脚本模型。历史 12 组本机配对中，计划结构通过由 6/12 到 9/12。该结果只衡量计划结构。 |
| 教材取材 | 支持已登记教材、调用方材料和带出处的项目释义。最近补充尾指针删除、三元组转置、阿姆达尔定律、SCAN/LOOK 与曼彻斯特时钟同步。 | 原 24 条具体考点查询的前三段同段字面命中从 19/24 到 24/24。新增 10 条改述仅 4/10，表明自然语言召回仍有缺口。该指标用于检索诊断。 |
| 正确性与交付 | 检查题包结构、材料引文和评分，随后用学生视角盲解并审计。流水线与选择重传支持绑定学生题面的复算。合格题写入 `PENDING` 队列。 | Python 3.9、3.12 各通过 138 项测试，500 个旧规则题的完整题包和 ID 一致。Pi 定向 4 项通过，全仓检查仍有既有模型目录类型错误。 |

本机试题台复用 `author`，支持预览学生题面、教师答案、评分和失败阶段。试题台当前使用项目的 DeepSeek 配置，每次生成由用户确认。切换只验证了启动配置和确认流程，未发起模型请求。审校方可以查看已从临时 PostgreSQL 原样导出的单选、综合题各一行。 [试题台使用说明](question-generation.md#浏览器试题台) · [待审行样例](../question_generation/examples/pending-questions.sample.json)

### 接续顺序

1. **改善粗需求取材。** 用分页误取网络时延、同义改述漏检等案例做回归。分别记录目标机制是否进入检索候选、计划是否选中正确材料、材料能否支撑推导。用独立查询验证改进效果。
2. **实现可定位的定向修订。** 从目标缩水、题设歧义、答案错误和评分不公中选取已复核错例。先验证一次定向修订能否保住原考查目标，修后重新盲解和审计。可复算结论继续用独立程序核对。
3. **按完整考纲分层验收。** 逐项核对正式大纲、材料和合格样题。先冻结四科两题型各 6 组，共 48 组诊断请求，使用同材料配对和独立复核。主指标是独立复核后可直接使用的题目比例。用诊断结果确定确认集规模，新增付费实验先确认范围和预算。 [评测设计与证据](question-generalization-evaluation.md)

## 设计选择

旧创作入口复用规则题校验、固定材料标签与数值求解器，导致有新材料也无法创作新考点。新路径以材料实际解释的知识关系为依据，围绕可观察学习表现形成任务，不要求逐考点编写生成函数。

当前通用入口采用 v0.5。作者提交材料原文中的引文、学生可见条件、推导依赖及条件变化。程序检查引用、依赖、评分和可执行计算。题设表述与题面不同会记录为诊断，由审计区分同义表达和隐藏条件。v0.7 曾用编号材料和简化响应降低输入量，在四个生产模型配对任务中交付少于 v0.5，因此保留为实验记录。两处网络材料补充已单独保留。[对照结果](question-generalization-evaluation.md#v07deepseek-生产模型对照)

当前默认单候选、独立解答、反例审计。单候选是实验起点，不是能力上限或已证实最优策略。旧实测双候选没有救回额外请求，因此不先假设更多候选就更好。是否增加定向修复，应依据实际失败机制。

v0.4独立解题只接收题型和学生视图，看不到教材、命题意图、作者答案、设计、评分点和见证。材料支持与命题目标由后续审计核对，避免解题阶段借助作者上下文补条件。单选重排选项，综合题逐问解答。审计尝试反例与替代读法，并核对解答等价性、引用支持、范围、约束、必要推理、条件变化、歧义、评分与见证对应关系。任一检查失败就不交付；模型判断仍可能有共同盲点。

## 调用方式

Pi工具、HTTP路径及外层题包不变。在`constraints.authoring`增加`syllabus_areas`选择新路径，`topic`是自由的具体任务名。

```json
{
  "schema_version": "0.1",
  "request_id": "topology-design-001",
  "subject": "data_structures",
  "topic": "topological_constraints",
  "question_type": "single_choice",
  "seed": 901,
  "constraints": {
    "requirements": ["同时考查合法序列的存在性与唯一性"],
    "authoring": {
      "objective": "design",
      "syllabus_areas": ["ds.graphs"],
      "focus": "区分有效、冗余与矛盾约束",
      "material_query": "拓扑排序 有向无环"
    }
  }
}
```

HTTP 服务可据 `material_query` 检索已配置的知识库和当前范围内的项目补充材料。显式`evidence`（含空数组）不被替换；无检索时可直接传原格式材料。新路径允许`rules=[]`，知识支持来自实际引文和语义核查；旧规则题的标签要求不变。

通用约束使用`requirements`文本数组；综合题另要求`total_score`（2至30的整数），通过`comprehensive`入口调用。批量/补题也可使用通用题，题目总分必须与槽位一致。原路径的数值约束如`page_size`保持原含义。完整直接材料示例：[单选](../question_generation/examples/general-authoring.json)、[综合题](../question_generation/examples/general-comprehensive.json)。示例中的自编材料明确标注来源，不冒充教材。

综合题保留`student_view.parts`、`instructor_view.parts`结构，加入小问依赖、评分点和等价方法。通用题暂不支持`revise`版本修订，会返回`UNSUPPORTED_REQUEST`，旧综合题修订不变。题目仍为`PENDING`；只将`student_view`展示给学生。新路径有独立版本缓存键，不使旧路径缓存失效。

原TCP迁移考点的禁用检查仍保留；这不代表通用路径所有TCP信息可见性问题已经解决。

## 材料发现及边界

显式 `material_query` 启用材料发现。检索已登记、文档指纹匹配的教材，核对当前分块内容指纹并排除已标记冲突。使用中文二字片段、英文词和文档频率排序，无需额外检索服务。

信道容量和共享半双工碰撞时序已有三条带来源与内容指纹的项目释义，覆盖先前实测中的两个材料缺口。它们按章节与查询匹配，可与教材一起使用。未配置教材索引时，HTTP 服务也可返回命中的这三条释义。来源、定位和公式边界列于[样题](question-generalization-examples.md)。

后续按同一方式补充了单链表删除尾结点、三元组转置、阿姆达尔定律、SCAN 与 LOOK、曼彻斯特时钟同步。参见[具体考点取材复测](question-generalization-evaluation.md#粗需求优化器与材料发现)。

返回版本含`discovery: source-pinned; not chunk-curated`，表示来源和完整性核对，不表示片段已经人工审定或OCR完全正确。旧人工整理目录不会被自动扩充。模型遇到目录、缺图、冲突或缺关键规则，可返回`NEEDS_MATERIAL`及具体缺口。

已有具体考点和改述查询的字面命中探针。还需标注语义相关性和材料对推理的支持程度，才能估计正式召回率。同义词、OCR 误字和错误标题仍会造成漏检或噪声。纯英文内部考点名不自动翻译；用 `material_query` 给出教材用语，或者显式提供材料。跨科任务可指定最多四个章节范围，至少一个属于主科目。

## 可执行验证

复用原四类数值求解器，另增加`finite_domain`有限状态验证。用受限JSON表达整数运算、比较、布尔条件及全称/存在/计数查询，穷举声明的有限定义域。拓扑题可把顶点位置作为变量，加入位置互异和边的先后约束，再计数添加候选边后还有多少合法顺序，无需新考点生成模板。

上限为8变量、4096状态、512表达式节点，不执行模型代码。算术为数学整数，除法向下取整；机器溢出必须显式截断。无合法状态直接拒绝，不能利用空模型证明任意答案。

它只证明声明模型内的结论，不证明与题面一致，不证明无限规模复杂度或一般程序正确性。不适合枚举的题可不用它。题包`verification_scope`区分程序检查、模型判断和实际见证数量，不把空见证说成计算已验证。

## 与学生题面绑定的复算

通用请求可在 `constraints.authoring` 中显式设置 `public_scenario`。例如流水线综合题可用：

```json
{
  "objective": "analyze",
  "syllabus_areas": ["co.cpu"],
  "public_scenario": "pipeline",
  "material_query": "流水线 数据转发"
}
```

`pipeline` 支持五级顺序流水线的寄存器时序和转发比较，`selective_repeat` 支持按题设事件重放的简化选择重传。作者选择参数、目标及答案值。程序从同一组参数生成题干和问题，独立核对单选唯一答案或综合题每个目标的评分答案。程序在盲解前拦截不一致。学生仍只看到普通的题干和选项或小问，教师题包保留 `self_check.public_scenario_verification` 供复核。模型继续检查解析、材料支持和教学价值，题包仍进入待审。

这条路径适合把状态或周期作为可核对得分点。SR 模型要求实际发送的分组在该事件内到达，验证只覆盖题面列出的轨迹。流水线模型按题面明示的转发有效周期和寄存器写读先后计算。两类场景使用同一绑定逻辑，其他题仍走原通用创作。当前选型来自两个真实模型错例，验证使用脚本模型与程序复算。见[绑定复算结果](question-generalization-evaluation.md#题设绑定的离线回归)。

## 章节导航与覆盖声明

| 科目 | 章节ID |
| --- | --- |
| 数据结构 | `ds.foundations`、`ds.linear`、`ds.stack_queue_array`、`ds.trees`、`ds.graphs`、`ds.search`、`ds.sort` |
| 组成原理 | `co.system`、`co.representation`、`co.memory`、`co.instructions`、`co.cpu`、`co.io` |
| 操作系统 | `os.foundations`、`os.process`、`os.memory`、`os.files`、`os.io` |
| 计算机网络 | `cn.architecture`、`cn.physical`、`cn.link`、`cn.network`、`cn.transport`、`cn.application` |

这24个范围参照[高教社大纲解析目录](https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=68b8764ae119ac9729e8a8bc)。高教社已公开 [2027 大纲产品元数据](https://xuanshu.hep.com.cn/front/h5Mobile/bookDetails?bookId=6aa97a0be119ac9729dd09ea)，公开正文仍需逐项核验。`coverage_report`分别列材料考点、实测考点和章节质量状态，不根据入口接受请求就标记质量通过。

## 上游需求细化

Pi 可用 `question_generation` 的 `author` 操作把原始需求直接交给命题服务。HTTP 入口是 `POST /v1/question-generation/author`。

```json
{"schema_version":"0.1","request_id":"memory-practice-001","brief":"想练内存这块"}
```

只需 `schema_version` 和 `request_id`。无具体偏好可省略 `brief`，也可直接写「出一道 408 题」。已有参考材料可直接传 `evidence`，沿用来源、版本、定位、摘要和原文格式。可选 `subject`、`syllabus_areas`、`question_type`、`total_score`、`requirements`、`seed`。`syllabus_areas` 限定可选范围，若要同题考查其中多个章节，可在 `requirements` 写明。给出总分会固定为综合题。自动选择综合题时默认 10 分。省略种子时由请求 ID 稳定推导。

服务先搜集材料，再请模型提出考查计划，包括可观察的学习表现、任务及学生应给出的推理证据。无具体方向时，种子决定先查看哪个章节的材料。检索词只负责找到材料，具体考法由模型根据片段决定。短需求若匹配多个章节，会呈现各章节材料，例如「内存」可同时检索组成原理的 Cache 和操作系统的虚拟内存。显式 `evidence` 优先，空材料返回 `NEEDS_MATERIAL`。如果没有足以支持所需机制的材料，优化器可返回具体缺口。

固定科目、题型和唯一章节由服务填入。模型只能选择可用范围内的章节和确实提供的材料。原始需求与计划进入创作和审计，学生盲解仍只收到 `student_view` 和题型。成功题包仍为 `PENDING`，教师侧的 `generator.parameters.brief_plan` 和返回的 `authoring_report.plan` 可回看实际采用的计划。通常最多四次模型调用，成功结果按请求、材料快照和模型配置缓存。组卷补题及既有结构化入口沿用原契约。见[粗需求验证](question-generalization-evaluation.md#粗需求优化器与材料发现)。

## 研究依据与未完成验证

[SwissText 2026教师评测](https://aclanthology.org/2026.swisstext-1.4/)支持概念与任务复杂性导向，同时揭示范围漂移、题面自带答案及高阶迁移仍需人工修改。[COLING 2025知识增强追问](https://aclanthology.org/2025.coling-main.55/)启发关系发现，但并非考试命题证据。[PrairieLearn](https://docs.prairielearn.com/question/server/)提供生成、评分与测试分离的工程参考。没有复制这些项目代码或宣称复现论文效果。

历史 DeepSeek 和后续本机对照分别记录于[实测报告](question-generalization-evaluation.md)。生产模型的可用题收益、逐考点材料充分性、教师盲评、学生区分度及学习成效仍待验证。
