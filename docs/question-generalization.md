# 面向408全范围的通用创作（实验阶段）

新路径把考查范围、材料获取、题目设计与可执行验证分开：具体考点无需新增生成函数；单选和综合题使用同一个引擎。原规则题及五考点创作保持不变。章节导航覆盖四科，不等于完整考纲的内容质量已经验证。

[样题](question-generalization-examples.md)包括八道接口测试题和两道依据网络补充材料编写的题，均由开发助手编写。模型实测另见[评测报告](question-generalization-evaluation.md)。

## 设计选择

旧创作入口复用规则题校验、固定材料标签与数值求解器，导致有新材料也无法创作新考点。新路径以材料实际解释的知识关系为依据，围绕可观察学习表现形成任务，不要求逐考点编写生成函数。

v0.7 要求作者给出学生可观察的作答目标、实际用到的材料规则、决定结论的题设及其变化结果。程序给连续材料片段编号，验证编号并回填原文或注明来源的项目释义。作者无需抄写原文，也无需把解析再编码成依赖图。题型分别使用对应的响应格式。引用是否支持规则、条件变化是否真能改变结论、任务是否需要相关推理，由后续审计核对。决定性题设与题面不逐字匹配时，记录诊断供审计判断是否存在隐藏前提。

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

返回版本含`discovery: source-pinned; not chunk-curated`，表示来源和完整性核对，不表示片段已经人工审定或OCR完全正确。旧人工整理目录不会被自动扩充。模型遇到目录、缺图、冲突或缺关键规则，可返回`NEEDS_MATERIAL`及具体缺口。

当前没有检索召回率基准；同义词、OCR误字和错误标题仍会漏检或带入噪声。材料数量不等于充分性。纯英文内部考点名不自动翻译；用`material_query`给出教材用语，或者显式提供材料。跨科任务可指定最多四个章节范围，至少一个属于主科目。

## 可执行验证

复用原四类数值求解器，另增加`finite_domain`有限状态验证。用受限JSON表达整数运算、比较、布尔条件及全称/存在/计数查询，穷举声明的有限定义域。拓扑题可把顶点位置作为变量，加入位置互异和边的先后约束，再计数添加候选边后还有多少合法顺序，无需新考点生成模板。

上限为8变量、4096状态、512表达式节点，不执行模型代码。算术为数学整数，除法向下取整；机器溢出必须显式截断。无合法状态直接拒绝，不能利用空模型证明任意答案。

它只证明声明模型内的结论，不证明与题面一致，不证明无限规模复杂度或一般程序正确性。不适合枚举的题可不用它。题包`verification_scope`区分程序检查、模型判断和实际见证数量，不把空见证说成计算已验证。

## 章节导航与覆盖声明

| 科目 | 章节ID |
| --- | --- |
| 数据结构 | `ds.foundations`、`ds.linear`、`ds.stack_queue_array`、`ds.trees`、`ds.graphs`、`ds.search`、`ds.sort` |
| 组成原理 | `co.system`、`co.representation`、`co.memory`、`co.instructions`、`co.cpu`、`co.io` |
| 操作系统 | `os.foundations`、`os.process`、`os.memory`、`os.files`、`os.io` |
| 计算机网络 | `cn.architecture`、`cn.physical`、`cn.link`、`cn.network`、`cn.transport`、`cn.application` |

这24个范围参照[高教社大纲解析目录](https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=68b8764ae119ac9729e8a8bc)。高教社已公开 [2027 大纲产品元数据](https://xuanshu.hep.com.cn/front/h5Mobile/bookDetails?bookId=6aa97a0be119ac9729dd09ea)，公开正文仍需逐项核验。`coverage_report`分别列材料考点、实测考点和章节质量状态，不根据入口接受请求就标记质量通过。

## 上游需求细化

Pi 接受操作名和结构化请求，当前由调用者提供具体科目、考点和题型。通用创作还要求章节范围和目标类型。组卷联合缺题计划本身包含固定的考点、题型、难度、分值与数量，考查能力由命题环节确定。

后续将在自主命题入口支持粗需求，依据材料可支撑的机制提出具体考查目标、题型和分值。自动细化会保留调用者明确指定的条件和组卷原始槽位。当前应按上述结构化契约调用。

## 研究依据与未完成验证

[SwissText 2026教师评测](https://aclanthology.org/2026.swisstext-1.4/)支持概念与任务复杂性导向，同时揭示范围漂移、题面自带答案及高阶迁移仍需人工修改。[COLING 2025知识增强追问](https://aclanthology.org/2025.coling-main.55/)启发关系发现，但并非考试命题证据。[PrairieLearn](https://docs.prairielearn.com/question/server/)提供生成、评分与测试分离的工程参考。没有复制这些项目代码或宣称复现论文效果。

历史 DeepSeek 和后续本机对照分别记录于[实测报告](question-generalization-evaluation.md)。生产模型的可用题收益、逐考点材料充分性、教师盲评、学生区分度及学习成效仍待验证。
