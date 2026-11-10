# 审校与组卷接口核对记录

核对日期：2026-10-21。
依据：HenryZhu123/Qodex 的 exam-checker 分支，提交 db50295cb4bf5080666776d9df931dfca0ee7f8d。
本文是代码核对结果和组卷侧接入策略，不表示双方已经批准所有待定规则。
后续用户已明确独立开发阶段选项由组卷侧自定义、题库必有答案；该阶段遵循 LOCAL_BANK_CONTRACT.md，不再等待审校侧确认。
替代早期设计中的推测；当前 checker_adapter.py 仍仅支持显式模拟转换，未接真实服务。

## 一、职责与读取入口

- 审校侧负责解析、单题审校、题目修订、知识点/难度标注和入库。
- 组卷侧负责需求蓝图、有效候选题筛选、整卷约束验证及换题。
- Pi 负责跨模块协调；组卷不能自行创建 PASS 审校结果。
- 题库检索：GET /v1/question-bank/search。
- 单条记录：GET /v1/question-bank/{record_id}。
- 最新题目状态：GET /v1/exam-checker/documents/{document_id}/questions/{question_id}/state。
- 推荐复用审校服务 API，不另建正式题库或直接改其业务表。

## 二、代码已经确定的格式

题库查询返回 questions 列表。单条 StoredQuestionBankEntry 含：

| 字段 | 实际约束/含义 |
| --- | --- |
| record_id | 题库记录标识 |
| document_id + question_id | 来源试卷和卷内题号，question_id 本身不保证跨卷唯一 |
| source_version_id | 入库来源版本 UUID；接口允许 null，组卷遇到 null 应标记不可验证 |
| question_json.question | QuestionView 对象 |
| question_json.review_status | 入库 JSON 中要求 PASS；是历史入库声明，不能单独证明最新状态 |
| question_json.metadata.difficulty | 标注模型规定 easy / medium / hard；组卷也应验证枚举 |
| question_json.metadata.knowledge_points | 标注模型规定 1–8 个字符串；不是已统一的分类体系 |
| question_json.ingestion | 入库服务附加的 STORED 和 record_id |

注意：手工 ingest 的验证比标注模型宽松，只检查 difficulty 非空、knowledge_points 是非空字符串列表，不能假定任意入库记录都严格满足标注模型约束。

QuestionView 的相关字段：

| 审校字段 | 组卷接入策略 |
| --- | --- |
| question_text | 原文保留为题干 |
| options: list[str] | 保留顺序和原始字符串；先确定标识规则，再映射为 A-D |
| answer_text: str | 可以为空；不能视为空答案已被补齐或验证 |
| points: float 或 null | 不默认填分，不截断小数；原型暂只支持整数分值，其他值明确报告不支持 |
| subject / question_type | 当前为自由字符串；通过显式映射处理名称差异 |
| reference / section_titles | 保留共享材料和来源上下文；共享材料缺失时不能把题目当独立完整题使用 |
| numbering_path / numbering_description | 用于来源追溯，不当成全局唯一题号 |

当前模型没有独立 explanation 字段，不从 answer_text 或 reference 猜造解析。
多知识点应完整保留；原型按显式映射选定唯一主分类计数，跨主分类记录需确认，不默认取第一项。

## 三、审校通过与入库是两个状态

- review.status：PASS / NEEDS_REVISION / UNRESOLVED；最新状态接口还可能返回 NOT_REVIEWED。
- ingestion.status：STORED / FAILED / SKIPPED。
- PASS 后还需要标注元数据及写库，可能 FAILED；没有数据库配置则 SKIPPED。
- 因此只有 PASS 不等于题库已有可用记录。

按当前“使用最新有效版本”的组卷侧接入策略，候选题需同时满足：

1. state.question_version_id 与记录的 source_version_id 相同。
2. state.review.status 为 PASS，且 unresolved_checks 为空。
3. state.question_bank.status 为 STORED，record_id 与检索记录相同。
4. 来源标识一致，题目字段完整，满足所请求的组卷模式。

state 中 STORED 只比较入库版本是否等于最新版本，不单独证明最新审校为 PASS，必须分别检查。
state 为 OUTDATED / NOT_STORED / NOT_CONFIGURED 或查询失败时，不自动接受该记录。
这是组卷侧保守接入策略；若团队希望允许历史已审校版本，需另行明确契约。
当前 search 直接查题库表，不自动连接最新版本和最新审校结果，也不会自动排除 OUTDATED。

## 四、选项标识仍需明确

QuestionView 只规定 options 是字符串列表，没有规定每项是否必须包含 A. / B. 等前缀。
结构提取提示词要求保留原文，但未给出选项标识的专门结构或校验。
QuestionService.to_checker_payload_from_view 直接拼接 question_text 与 options，没有补充标识。

已观察联调案例：PDF 有 A-D；保存 options 只含内容；审校因此报告缺标识。
不能据此认定原卷缺标识，也不能由组卷擅自更改审校状态。

待双方确认：
- 选择保留原始标识，还是分开保存 label 与 text？
- 如果 options 是纯内容，审校如何区分“结构化省略标识”与“原文真的没有标识”？
- 展示给学生时生成 A-D 只能作为渲染行为，不能伪造原文合规证据。

## 五、答案完整性与补充责任

解析提示词明确要求原文没有答案时保留空值；当前入库门禁没有要求 answer_text 非空。
所以“已入库”不保证能够导出答案卷。
带答案的正式组卷模式应排除缺答案记录或报告缺口；谁补答案、谁验证需团队确认。
无答案试卷模式可以另外设计，但必须明确不提供已验证答案，不能默默改变交付要求。

## 六、检索范围

支持 subject、question_type、difficulty、knowledge_point、keyword 和 limit。
limit 默认 20，范围 1–100；按 created_at 倒序。当前未见 offset/cursor 或 total。
检索结果为空表示本次条件没有返回记录；结果不足不能无条件断言整个题库不足。
候选截断或查询预算耗尽应报告检索范围和不完整状态，不能静默放宽蓝图。

## 核对的代码位置

- pi-coding-agent/services/exam-checker/src/exam_checker/domain/models.py
- pi-coding-agent/services/exam-checker/src/exam_checker/services/question_service.py
- pi-coding-agent/services/exam-checker/src/exam_checker/services/question_state_service.py
- pi-coding-agent/services/exam-checker/src/exam_checker/services/question_bank_service.py
- pi-coding-agent/services/exam-checker/src/exam_checker/services/question_workflow_service.py
- pi-coding-agent/services/exam-checker/src/exam_checker/database/repositories.py
- pi-coding-agent/services/exam-checker/src/exam_checker/api/app.py
- pi-coding-agent/services/exam-checker/src/exam_checker/parsing/structure_extractor.py
