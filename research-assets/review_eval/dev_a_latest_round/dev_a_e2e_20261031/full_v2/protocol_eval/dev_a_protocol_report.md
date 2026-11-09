# Dev A 审校结果质量评估报告（评估协议 v1.0.0）

依据 `exam-checker-evaluation-system.md`（Qodex 混淆矩阵计数规范）对 Dev A strict 全量结果重新评分。评估粒度为 **Prediction 级**，与此前题级 conservative / exact-type 指标不是同一口径，不可混用。

## 1. 运行与版本信息（§14）

| 项 | 值 |
| --- | --- |
| 被测模型 | `deepseek-v4.1-flash-1017` |
| 被测端点 | `https://aihubmix.com/v1` |
| 解码参数 | temperature 0，seed 42，max_tokens 4096 |
| reviewer 内部并发 | 2 |
| Prompt Profile | `reviewer-prompt/qwen38_27b`，24 个文件哈希在 v1 manifest 中校验 24/24 匹配 |
| 数据集 | `review_eval_dataset_v2.csv`，SHA-256 `a605fdd210e33d307a7255304f300bce413163de8f03902911bc661c9e35238c` |
| 数据集构成 | 318 题：错误 227、无错 91 |
| Judge 模型 | gpu-qwen3.8-27b |
| 评估协议版本 | `1.0.0` |
| 评分样本 / 排除样本 | 311 / 7 |

## 2. 全量汇总指标（§13）

| 指标 | 值 | 计数 |
| --- | ---: | --- |
| Precision | **76.9%** | TP 163 / (TP 163 + FP 49) |
| Recall | **75.5%** | TP 163 / (TP 163 + FN 53) |
| F1 | **76.2%** | — |
| F2 | 75.7% | 更看重 Recall |
| Accuracy | 70.9% | (TP 163 + TN 85) / 全部 |
| FPR（协议公式） | 36.6% | FP 49 / (FP 49 + TN 85) |
| **无错题 FPR** | **6.6%** | 无错题中 6/91 被误报 |

> `Accuracy` 与协议公式的 `FPR` 混合了「错误项级」的 FP 和「题目级」的 TN（§13.2 已提示该限制），不应作为主要判据。**无错题 FPR** 才是可解释的误报率。

## 3. 分类型混淆矩阵（§14 推荐表）

| 错误类型 | TP | TN | FP | FN | Precision | Recall | F1 | F2 | FPR | 成功样本 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 错别字 | 49 | 0 | 18 | 12 | 73.1% | 80.3% | 76.6% | 78.8% | — | 63 |
| 标点符号错误 | 11 | 0 | 3 | 8 | 78.6% | 57.9% | 66.7% | 61.1% | — | 20 |
| 选项结构错误 | 16 | 0 | 5 | 3 | 76.2% | 84.2% | 80.0% | 82.5% | — | 20 |
| 题目与题型不一致 | 16 | 0 | 3 | 2 | 84.2% | 88.9% | 86.5% | 87.9% | — | 18 |
| 信息缺失/题目无解 | 33 | 0 | 8 | 10 | 80.5% | 76.7% | 78.6% | 77.5% | — | 43 |
| 语义不清 | 7 | 0 | 2 | 10 | 77.8% | 41.2% | 53.8% | 45.5% | — | 17 |
| 答案泄露 | 17 | 0 | 1 | 2 | 94.4% | 89.5% | 91.9% | 90.4% | — | 19 |
| 事实/逻辑错误 | 14 | 0 | 3 | 6 | 82.4% | 70.0% | 75.7% | 72.2% | — | 20 |
| 无错样本 | 0 | 85 | 6 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 6.6% | 91 |

> 有错类的 TN 恒为 0（该题必然有 GT），因此按 §13.1 公式 `FP/(FP+TN)` 会恒等于 100%，不具信息量，故记作 —。

## 4. 排除样本（§12）

| 样本 | evaluation_status | 说明 |
| --- | --- | --- |
| `rev-type_mismatch-refq-408-2012-10` | `skipped_timeout` | 上游任务失败 |
| `rev-answer_leakage-refq-408-2010-20` | `llm_call_failed` | parse_fail |
| `rev-ambiguity-refq-408-2025-14` | `llm_call_failed` | parse_fail |
| `rev-missing_info-refq-408-2014-28` | `llm_call_failed` | parse_fail |
| `rev-typo-refq-408-2015-29` | `llm_call_failed` | parse_fail |
| `rev-type_mismatch-refq-408-2026-14` | `llm_call_failed` | parse_fail |
| `rev-typo-refq-408-2016-19` | `llm_call_failed` | parse_fail |

排除率 7/318 = 2.20%，这些样本未进入任何指标。

## 5. 结论

在 Prediction 级、官方协议口径下，本系统表现为 **Precision 76.9%、Recall 75.5%、F1 76.2%**。

- 强项：答案泄露、题目与题型不一致、选项结构、信息缺失，Precision 与 Recall 均在 76% 以上。
- 短板：语义不清（Recall 约 41%）、错别字（FP 18 条，占全部误报的三分之一以上）。
- 无错题误报率 6.6%（6/91），但 Wilson 上界约 13.6%，样本量不足以断言稳定低于 10%。

## 6. 产物

| 文件 | 内容 |
| --- | --- |
| `per_question.jsonl` | 每题的 GT、原始 Prediction、去重后 Prediction、TP/FP/TN/FN、reason、evaluation_status |
| `metrics.json` | 全量与分类型指标、排除清单 |
| `evaluate_protocol.py` | 按 §16 伪代码实现的评估器 |
