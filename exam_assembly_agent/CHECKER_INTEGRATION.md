# 审校题库适配：第一阶段

依据已读取的 exam-checker 分支提交 `17ff1f5f3` 中的领域模型、题库服务和数据库仓储。
此阶段只转换 JSON 导出/查询响应，没有连接数据库或启动审校 API。

| 审校字段 | 内部字段 | 策略 |
| --- | --- | --- |
| document_id + question_id | question_id | 组合标识，避免不同试卷题号冲突 |
| source_version_id | version | 保留版本 UUID，不伪造递增版本 |
| question.question_text | stem | 原文保留 |
| question.options | options | 四项列表按 A-D 转换；支持统一的 A.、A、等标签，不支持混用/乱序 |
| question.answer_text | answer | 仅支持单个 A-D 字母或唯一匹配的选项全文；含解释的答案不猜测 |
| metadata.knowledge_points | knowledge_points + topic | 全量保留；按显式映射得到唯一主分类才可参与当前单主分类配额 |
| question.points | score | 仅接受正整数或整数值浮点数，不填默认分值 |
| 解析字段未定义 | explanation | 空字符串，explanation_status=NOT_PROVIDED，不从答案或 reference 编造解析 |

知识点跨多个主分类的记录会拒绝转换，等待人工确认；不是自动取第一个知识点。
科目名称目前精确匹配；未知题型、答案表达、缺失分值均记录拒绝原因。
原始 record_id、source_version_id 等保存在 provenance 中。

## 开发运行

在仓库根目录执行：

```powershell
python -m exam_assembly_agent.checker_adapter --input exam_assembly_agent/examples/checker_export_mock.json --topic-map exam_assembly_agent/examples/topic_mapping.json --output-dir exam_assembly_agent/outputs/adapter_demo --mock-input
python exam_assembly_agent/main.py --bank exam_assembly_agent/outputs/adapter_demo/question_bank.json
python -m unittest exam_assembly_agent.test_assembly exam_assembly_agent.test_checker_adapter -v
```

第一条应接受一题，输出转换题库和 conversion_report.json。
第二条使用原来的 10 题需求，应返回 NEEDS_QUESTIONS，而不是报格式错误。
转换报告的 accepted_count 仅代表格式转换成功，不代表正式审校验收。

## 真实接入前待完成

当前查询 API 的 StoredQuestionBankEntry 没有完整的 source_review_id、最新版本和最新审校结果。
题库 JSON 中历史 review_status=PASS 不能证明当前仍然可用。
因此真实模式暂时拒绝记录；开发模式必须显式使用 --mock-input，所有转换记录标记 is_mock=true。
下一阶段需与同学确认旧版本可用策略，读取版本及审校证据，验证来源关系后才能启用正式模式。
还需拿真实样例核对选项、答案表达、知识点粒度、科目及题型命名。
不得把模拟转换结果写回真实审校表，或称为真实审校合格题。
