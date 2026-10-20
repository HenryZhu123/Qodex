# Qwen3.8 Flash / Pro Prompt 选择

模型：`Qwen3.8-27B-FP8`。业务 Prompt 位于 `flash/` 与 `pro/`；思考模式按下表配置。

筛选门槛：FPR 严格低于 10%。Recall 差距不超过 2 个百分点且耗时明显更短时，选择耗时更短的模式。

| 错误类型 | 包 | 思考模式 | Recall | FPR | 耗时(min) | 依据 |
|---|---|---:|---:|---:|---:|---|
| 错别字 | flash | disabled | 93.2% | 6.8% | 15.70 | 完整合并结果；与已发布 v002 为同一候选 |
| 错别字 | pro | disabled | 93.2% | 6.8% | 15.70 | native Recall 91.7%、31.7 min，disabled 更优且更快 |
| 选项错误 | flash | disabled | 99.4% | 0.4% | 10.10 | 完整评测 |
| 选项错误 | pro | disabled | 99.4% | 0.4% | 10.10 | native Recall 仅高 0.2pp，但耗时 56.5 min |
| 语义不清 | flash | disabled | 87.1% | 8.0% | 10.30 | 完整评测 |
| 语义不清 | pro | native | 92.6% | 9.1% | 58.80 | 3 跳过行；Recall 比 disabled R7 高 5.5pp |
| 标点符号 | flash | explicit | 94.3% | 7.9% | 15.56 | 1041 条清洗版完整评测；R4 Prompt |
| 标点符号 | pro | native | 97.4% | 7.2% | 56.60 | 6 跳过行；Recall 比 explicit 候选高约 4pp |
| 题目和题型不一致 | flash | disabled | 96.6% | 1.1% | 7.90 | 完整评测 |
| 题目和题型不一致 | pro | disabled | 96.6% | 1.1% | 7.90 | native Recall 94.2%、33.3 min，disabled 更优且更快 |
| 信息缺失 | flash | disabled | 91.5% | 1.8% | 4.10 | 完整评测 |
| 信息缺失 | pro | disabled | 91.5% | 1.8% | 4.10 | native Recall 84.2%、29.0 min，disabled 更优且更快 |
| 题目无解 | flash | explicit | 67.5% | 8.1% | 23.43 | 完整评测 |
| 题目无解 | pro | explicit | 67.5% | 8.1% | 23.43 | native FPR 10.1%，不满足门槛 |
| 答案泄露 | flash | explicit | 96.1% | 1.2% | 3.39 | 完整评测 |
| 答案泄露 | pro | explicit | 96.1% | 1.2% | 3.39 | native Recall 高 1.9pp，但耗时约 13.3 min，为 explicit 的约 3.9 倍 |
| 图文不一致 | flash | explicit | 待验证 | 待验证 | 待验证 | 暂无 Qwen3.8 完整评测，保留原版待验证 |
| 图文不一致 | pro | native | 待验证 | 待验证 | 待验证 | 暂无 Qwen3.8 完整评测，按 Pro 默认优先 native，保留原版待验证 |
| 逻辑错误 | flash | explicit | 待验证 | 待验证 | 待验证 | 暂无 Qwen3.8 完整评测，保留原版待验证 |
| 逻辑错误 | pro | native | 待验证 | 待验证 | 待验证 | 暂无 Qwen3.8 完整评测，按 Pro 默认优先 native，保留原版待验证 |
| 引导语检查 | flash | explicit | 待验证 | 待验证 | 待验证 | 暂无独立 Qwen3.8 完整评测，保留原版待验证 |
| 引导语检查 | pro | native | 待验证 | 待验证 | 待验证 | 暂无独立 Qwen3.8 完整评测，按 Pro 默认优先 native，保留原版待验证 |
