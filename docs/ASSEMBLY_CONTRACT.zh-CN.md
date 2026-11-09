# 组卷请求与联合补题契约 v1.0

这是组卷模块当前实现的约定，供团队确认；尚未代表其他模块已接受或完成对接。

## 请求

Pi 工具 `exam_assembly` 与 `POST /v1/exam-assembly/assemble` 使用同一组字段，完整示例见 `pi-coding-agent/services/exam-assembly/examples/request.json`。

| 字段 | 含义 |
| --- | --- |
| schema_version | 1.0；省略时服务按1.0处理 |
| request_id | 调用方提供的追踪编号，不是幂等写入或续跑凭据 |
| subject | 与正式题库一致的学科标签 |
| question_count | 1至100的总题数 |
| total_score | 正整数总分 |
| question_type_counts | 每种题型题数，目前只能有 single_choice 的非零配额 |
| question_type_scores | 每种题型的单题分数，正整数，键与题型题数一致 |
| knowledge_point_counts | 每个知识点分配的题数，精确标签匹配 |
| difficulty_counts | easy、medium、hard 三个键，数量为非负整数 |
| max_repair_rounds | 0至10，默认3 |
| export_pdf | 默认false；HTML默认导出，PDF需要额外依赖 |
| similarity_decisions | 可选人工题对结论数组，默认空；题号、内容哈希、审核人和理由必须完整 |

题型题数、知识点题数、难度题数分别合计到总题数。总分等于各题型题数×该题型单题分数的合计。每个已选题只占一个知识点配额位置，多标签不会使同一道题计数多次。原始题目分值必须符合请求，不自动改题分值。

缺少字段、字段类型错误、未支持的schema版本或额外字段返回HTTP422；字段正确但配额合计冲突、总分冲突、不支持的题型返回HTTP200和INVALID_REQUEST。两种情况均不会查询题库或偷偷调整需求。

尚未实现计算题、混合题型、同题型不同分数。必须明确报错，不能将这些请求转换成单选题。不要向生产工具传 `bank`、`allow_mock_reviews`。旧开发脚本仍可独立使用旧格式，但不属于生产API。

## 联合补题建议

例如要求栈2题、队列1题；简单1题、困难2题。候选池中栈题全是简单，队列题全是困难，即使每个维度单独统计都够，仍不能选出所需组合。

可行建议：保留1道简单栈题和1道困难队列题，再补1道困难栈题。

```json
{
  "status": "NEEDS_QUESTIONS",
  "deficits": [
    {
      "subject": "数据结构",
      "question_type": "single_choice",
      "knowledge_point": "栈",
      "difficulty": "hard",
      "score_per_question": 2,
      "missing_count": 1
    }
  ]
}
```

完整 `replenishment_request` 及其JSON文件还包含：

- `schema_version`、`request_id`：格式版本及来源请求。
- `plan_status=PROPOSED_NOT_EXECUTED`：尚未执行的建议，不表示已经命题或审校。
- `scope=CURRENT_VERIFIED_CANDIDATE_POOL`：只对本次查询并验证的候选快照负责。
- `suggested_additional_count`：本方案新增题数，等于deficits中的missing_count之和。
- `minimum_count_proven`：是否证明当前候选池中已无法保留更多合格题。false时建议仍能补齐，但不保证最少补题。
- `search`：搜索预算与是否耗尽。
- `pairing_basis`：联合配额由剩余边际配额配对，槽位可能存在其他同样可行方案。
- `keep_assignments`：拟保留的record_id、来源版本、分配知识点、难度、题型和分值。
- `avoid_stems`：不得与拟保留题干重复的文本。
- `requirements`：新题必须独立审校PASS、正式入库、答案完整、审校对应当前版本、题号与题干不重复。
- `next_action=SUPPLY_ACCEPTED_BANK_QUESTIONS_THEN_REASSEMBLE`：补题入库后重新发起组卷。

`topic_deficits` 和 `difficulty_deficits` 是诊断用的分维度统计，不是另一批要补的题，不能与deficits相加。判断联合缺口以补题计划为准。

查询截断、搜索未能判定可行性或选题后版本变化时返回UNRESOLVED；不生成确定的联合补题建议。没有自动生成、自动审校或自动续跑功能。

相似题复核也可能返回UNRESOLVED，此时 `similarity_review.status=NEEDS_REVIEW`，返回教师题对包和模板路径，不导出完整试卷。人工确认DUPLICATE后，联合补题规划会避开该已确认题对；题对判断不修改题库审校状态。详见 `SIMILARITY_REVIEW.zh-CN.md`。

## 验收与演示

服务测试覆盖配额冲突、题型不支持、空库、相同题干、多标签、搜索预算及联合无解；小规模枚举结果用于核对保留数量。示例测试数据明确是合成数据，不能视作正式审校通过。

可运行 `pi-coding-agent/services/exam-assembly/examples/demo_joint_deficit.py` 查看分维度缺口全为零、联合缺口仍有1题的演示。结果只写本地outputs，不读写数据库，也不生成学生试卷。
