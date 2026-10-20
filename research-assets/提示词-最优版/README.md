# Qwen3.8-27B-FP8 最优提示词（explicit / disabled）

依据飞书《审校数据集评估结果》截至 2026-09-17 的记录：优先选择误报率（FPR）低于 10% 的完整评测结果，再比较召回率；仅比较 Qwen3.8-27B-FP8 的 explicit 与 disabled，不纳入 native 和其他模型。

| 错误类型 | 文件 | 任务 Prompt 版本 | 召回率 | FPR |
| --- | --- | --- | ---: | ---: |
| 错别字 | `错别字_disabled.txt` | v002（cycle-009，ac8605fe） | 93.2% | 5.8% |
| 选项错误 | `选项错误_disabled.txt` | 27B 专用 Prompt 原始版 | 99.4% | 0.4% |
| 语义不清 | `语义不清_disabled.txt` | R7 候选 | 87.1% | 8.0% |
| 标点符号 | `标点符号_explicit.txt` | R4 Prompt | 94.3% | 7.9% |
| 题目和题型不一致 | `题目和题型不一致_disabled.txt` | 27B 专用 Prompt 原始版 | 96.6% | 1.1% |
| 信息缺失 | `信息缺失_disabled.txt` | 原版 Prompt 优化 R1 | 91.5% | 1.8% |
| 题目无解 | `题目无解_explicit.txt` | 27B 专用 Prompt 原始版 | 64.7% | 9.7% |
| 答案泄露 | `答案泄露_explicit.txt` | 新版候选（仅评测） | 96.1% | 1.2% |

每份 `.txt` 都直接按项目拼装规则连接该模式目录的 `共享核心.txt`、`tasks/<task_id>.txt`、`JSON约束_<with_think|without_think>.txt`，非空段之间以两个换行隔开。当前共享核心为空；explicit 使用 `with_think`，disabled 使用 `without_think`。这些文件是独立交付副本，不会自动改变服务的运行路由。

图文不一致只有一条来源不完整的 explicit 截图参考结果，FPR 为 35.5%，未达到条件；逻辑错误没有评测记录，因此两类均未生成“最优版”。标点符号 R4 的结果来自 1041 条清洗版数据集；题目无解的 9.7% FPR 接近 10% 边界。答案泄露新版在表中标注为“仅评测，未发布”。

评测来源：[飞书《审校数据集评估结果》](https://mcnjls2hcedj.feishu.cn/sheets/ZeBTsoqtfhVbN2tkW8ncFgwVnCe?sheet=aD0SEF)。任务文本来源：`exam_checker_agent/backend/assets/prompt/profiles/qwen38_27b/{disabled,explicit}/`。
