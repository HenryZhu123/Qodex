# 面向408全范围的通用创作（实验阶段）

新路径把考查范围、材料获取、题目设计与可执行验证分开：具体考点无需新增生成函数；单选和综合题使用同一个引擎。原规则题及五考点创作保持不变。章节导航覆盖四科，不等于完整考纲的内容质量已经验证。

当前提供八道助手自编[样题](question-generalization-examples.md)，用于检验题目表达、评分结构与反例检查；不能作为模型生成效果证据。真实模型对照实验见[实测报告](question-generalization-evaluation.md)。

## 设计选择

旧创作入口复用规则题校验、固定材料标签与数值求解器，导致有新材料也无法创作新考点。新路径以材料实际解释的知识关系为依据，围绕可观察学习表现形成任务，不要求逐考点编写生成函数。

作者交付知识结论及支持原文、学生可见条件、推导依赖和条件变化检查。程序检查引文存在、ID与依赖合法且无环；未关联的依据与步骤作为审计诊断。v0.5将未逐字匹配的题设也列为诊断，交由审计区分同义概括与隐藏前提，不直接把词面不同认定为题目错误。这些检查不能证明引用蕴含结论，也不能证明推理有深度，仍需语义核查。

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

有知识库的HTTP服务可据`material_query`检索。显式`evidence`（含空数组）不被替换；无检索时可直接传原格式材料。新路径允许`rules=[]`，知识支持来自实际引文和语义核查；旧规则题的标签要求不变。

通用约束使用`requirements`文本数组；综合题另要求`total_score`（2至30的整数），通过`comprehensive`入口调用。批量/补题也可使用通用题，题目总分必须与槽位一致。原路径的数值约束如`page_size`保持原含义。完整直接材料示例：[单选](../question_generation/examples/general-authoring.json)、[综合题](../question_generation/examples/general-comprehensive.json)。示例中的自编材料明确标注来源，不冒充教材。

综合题保留`student_view.parts`、`instructor_view.parts`结构，加入小问依赖、评分点和等价方法。通用题暂不支持`revise`版本修订，会返回`UNSUPPORTED_REQUEST`，旧综合题修订不变。题目仍为`PENDING`；只将`student_view`展示给学生。新路径有独立版本缓存键，不使旧路径缓存失效。

原TCP迁移考点的禁用检查仍保留；这不代表通用路径所有TCP信息可见性问题已经解决。

## 材料发现及边界

显式`material_query`启用来源固定的材料发现模式。它只搜索原目录已登记、文档指纹匹配的教材，核对当前分块内容指纹并排除已标记冲突。使用中文二字片段、英文词和文档频率排序，无向量服务，不修改知识库。

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

这24个范围参照[高教社大纲解析目录](https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=68b8764ae119ac9729e8a8bc)。已找到2027大纲产品信息，但未获得完整内容逐项核对，因此不能声称完成最新考纲细粒度映射。`coverage_report`分别列材料考点、实测考点和章节质量状态，不根据入口接受请求就标记质量通过。

## 研究依据与未完成验证

[SwissText 2026教师评测](https://aclanthology.org/2026.swisstext-1.4/)支持概念与任务复杂性导向，同时揭示范围漂移、题面自带答案及高阶迁移仍需人工修改。[COLING 2025知识增强追问](https://aclanthology.org/2025.coling-main.55/)启发关系发现，但并非考试命题证据。[PrairieLearn](https://docs.prairielearn.com/question/server/)提供生成、评分与测试分离的工程参考。没有复制这些项目代码或宣称复现论文效果。

两轮真实实验已结束，结果与失败分布见[实测报告](question-generalization-evaluation.md)。仍需证明：新流程相对同材料直接提示的可用题收益、教材噪声稳健性，以及v0.5语义诊断相对硬性逐字检查的漏检/误拒变化。完整考纲细粒度覆盖、教师盲评、学生区分度及学习成效均未完成。
