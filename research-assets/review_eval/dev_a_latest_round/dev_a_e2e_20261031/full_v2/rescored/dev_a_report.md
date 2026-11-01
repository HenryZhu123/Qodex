# Dev A strict 全量评测报告（rescored）

运行目录：`research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031`

配置：reviewer `deepseek-v4.1-flash-1017` @ `https://aihubmix.com/v1`，JEV `jev-1.14` @ `https://aihubmix.com/v1/systemone`，外层并发 1，reviewer 内部并发 2，最大尝试 3，max_tokens 4096，reasoning_effort `默认（不发送）`。

监督与报告依据：`research-assets/review_eval/DEEPSEEK_DEV_A_SUPERVISION_GUIDE.md`。本报告只判读 Dev A（开发集），不构成泛化结论。

评分标签文件：`review_eval_dataset_v2.csv`（SHA-256 `a605fdd210e33d307a7255304f300bce413163de8f03902911bc661c9e35238c`）。

> 这是**经人工裁决重标后的标签**，不是原始 v1 标签。逐条依据见 `review_eval_dataset_v2.provenance.json` 与 `clean_adjudication.csv`。模型输出未重跑，仅按 sample_id 重新配对打分。

## 1. 数据集分布（318 条）

| 项目 | 数量 |
| --- | --- |
| 总样本 | 318 |
| clean | 91 |
| 错误样本 | 227 |

| 错误类型 | 数量 |
| --- | --- |
| typo | 65 |
| punctuation | 20 |
| option_structure | 20 |
| type_mismatch | 20 |
| solvability_failure | 44 |
| ambiguity | 18 |
| answer_leakage | 20 |
| factual_logical | 20 |

## 2. 核心指标

| 指标 | 值 | Wilson 95% CI |
| --- | --- | --- |
| conservative Recall | 76.2% (173/227) | [0.703, 0.813] |
| conditional Recall | 76.5% (173/226) | [0.706, 0.816] |
| exact-type Recall | 65.2% (148/227) | [0.588, 0.711] |
| macro conservative Recall | 0.7416 | — |
| Clean conservative FPR | 6.6% (6/91) | [0.031, 0.136] |
| Clean conditional FPR | 6.6% (6/91) | [0.031, 0.136] |

- 检出错误题：173/227；其中类别命中：148
- clean 误报：6/91
- UNRESOLVED：错误题 1 条、clean 0 条

### 5% / 10% 真实错误率假设下的 calibrated precision

| 真实错误率假设 | calibrated precision |
| --- | --- |
| 5% | 0.3782 |
| 10% | 0.5622 |

## 3. 分类别指标

| 类别 | 样本 | conservative Recall | conditional Recall | exact-type Recall | UNRESOLVED |
| --- | --- | --- | --- | --- | --- |
| typo | 65 | 81.5% (53/65) | 81.5% (53/65) | 75.4% (49/65) | 0 |
| punctuation | 20 | 60.0% (12/20) | 60.0% (12/20) | 55.0% (11/20) | 0 |
| option_structure | 20 | 85.0% (17/20) | 85.0% (17/20) | 60.0% (12/20) | 0 |
| type_mismatch | 20 | 85.0% (17/20) | 89.5% (17/19) | 85.0% (17/20) | 1 |
| solvability_failure | 44 | 77.3% (34/44) | 77.3% (34/44) | 63.6% (28/44) | 0 |
| ambiguity | 18 | 44.4% (8/18) | 44.4% (8/18) | 11.1% (2/18) | 0 |
| answer_leakage | 20 | 90.0% (18/20) | 90.0% (18/20) | 85.0% (17/20) | 0 |
| factual_logical | 20 | 70.0% (14/20) | 70.0% (14/20) | 60.0% (12/20) | 0 |
| clean | 91 | 6.6% (6/91) | 6.6% (6/91) | — | 0 |

## 4. JEV 路由分布

| 决策 | 数量 | 占比 |
| --- | --- | --- |
| RUN | 209 | 21.91% |
| SKIP | 745 | 78.09% |
| FALLBACK_RUN | 0 | 0.00% |

路由决策总数：954（每题 3 个 JEV 任务）。FALLBACK_RUN 占 0.00%。

## 5. 各 task 失败、重试与错误码

| task | COMPLETED | SKIPPED | FAILED | 重试样本数 | 错误码 |
| --- | --- | --- | --- | --- | --- |
| ambiguity_check | 318 | 0 | 0 | 0 | — |
| answer_leak_check | 166 | 152 | 0 | 0 | — |
| logic_check | 317 | 0 | 1 | 14 | INVALID_MODEL_RESPONSE=1 |
| mismatch_check | 28 | 290 | 0 | 0 | — |
| options_check | 15 | 303 | 0 | 0 | — |
| punctuation_check | 318 | 0 | 0 | 5 | — |
| solvability_check | 318 | 0 | 0 | 0 | — |
| typo_check | 318 | 0 | 0 | 0 | — |

## 6. 题级延迟

| 统计 | 毫秒 |
| --- | --- |
| p50 | 22423.8 |
| p95 | 60898.8 |
| max | 184109.3 |
| mean | 28457.5 |

| 类别 | n | p50 | p95 | max |
| --- | --- | --- | --- | --- |
| ambiguity | 18 | 27582.0 | 55968.9 | 72055.3 |
| answer_leakage | 20 | 29174.0 | 96288.3 | 184109.3 |
| clean | 91 | 14614.7 | 36146.7 | 52323.8 |
| factual_logical | 20 | 34507.5 | 64422.1 | 154990.6 |
| option_structure | 20 | 26715.7 | 61115.7 | 100991.3 |
| punctuation | 20 | 15458.9 | 24877.2 | 27834.6 |
| solvability_failure | 44 | 24571.3 | 51095.0 | 74607.9 |
| type_mismatch | 20 | 33168.3 | 100155.9 | 150052.2 |
| typo | 65 | 27312.2 | 81399.4 | 163023.0 |

## 7. 异常样本清单

- false positive（clean 被判 DETECTED）：6 条 — clean-006, clean-010, clean-033, clean-041, clean-098, clean-099

- false negative（错误题被判 CLEAN）：53 条 — rev-ambiguity-refq-408-2013-25, rev-ambiguity-refq-408-2016-16, rev-ambiguity-refq-408-2018-29, rev-ambiguity-refq-408-2019-09, rev-ambiguity-refq-408-2020-13, rev-ambiguity-refq-408-2020-16, rev-ambiguity-refq-408-2021-04, rev-ambiguity-refq-408-2022-16, rev-ambiguity-refq-408-2022-31, rev-ambiguity-refq-408-2023-11, rev-answer_leakage-refq-408-2018-16, rev-answer_leakage-refq-408-2021-11, rev-factual_logical-refq-408-2016-14, rev-factual_logical-refq-408-2017-31, rev-factual_logical-refq-408-2023-15, rev-factual_logical-refq-408-2024-20, rev-factual_logical-refq-408-2025-20, rev-factual_logical-refq-408-2026-20, rev-missing_info-refq-408-2011-35, rev-missing_info-refq-408-2013-38, rev-missing_info-refq-408-2014-08, rev-missing_info-refq-408-2014-10, rev-missing_info-refq-408-2014-27, rev-missing_info-refq-408-2014-31, rev-missing_info-refq-408-2015-01, rev-missing_info-refq-408-2015-04, rev-option_structure-refq-408-2013-11, rev-option_structure-refq-408-2018-11, rev-option_structure-refq-408-2021-22, rev-punctuation-refq-408-2009-09, rev-punctuation-refq-408-2009-11, rev-punctuation-refq-408-2009-17, rev-punctuation-refq-408-2009-23, rev-punctuation-refq-408-2009-28, rev-punctuation-refq-408-2009-37, rev-punctuation-refq-408-2010-30, rev-punctuation-refq-408-2011-04, rev-type_mismatch-refq-408-2017-23, rev-type_mismatch-refq-408-2023-20, rev-typo-refq-408-2014-38, rev-typo-refq-408-2016-01, rev-typo-refq-408-2016-27, rev-typo-refq-408-2017-25, rev-typo-refq-408-2018-24, rev-typo-refq-408-2020-14, rev-typo-refq-408-2021-40, rev-typo-refq-408-2022-26, rev-typo-refq-408-2023-19, rev-typo-refq-408-2023-40, rev-typo-refq-408-2025-26, rev-typo-refq-408-2025-33, rev-unsolvable-refq-408-2009-39, rev-unsolvable-refq-408-2020-09

- wrong type（检出但类别不符）：25 条 — clean-061, rev-ambiguity-refq-408-2016-36, rev-ambiguity-refq-408-2017-17, rev-ambiguity-refq-408-2019-19, rev-ambiguity-refq-408-2021-03, rev-ambiguity-refq-408-2021-15, rev-ambiguity-refq-408-2025-14, rev-answer_leakage-refq-408-2015-07, rev-factual_logical-refq-408-2016-25, rev-factual_logical-refq-408-2024-38, rev-missing_info-refq-408-2012-01, rev-missing_info-refq-408-2014-02, rev-missing_info-refq-408-2014-28, rev-missing_info-refq-408-2015-06, rev-missing_info-refq-408-2015-08, rev-option_structure-refq-408-2012-26, rev-option_structure-refq-408-2018-13, rev-option_structure-refq-408-2020-07, rev-option_structure-refq-408-2022-36, rev-option_structure-refq-408-2024-35, rev-punctuation-refq-408-2009-03, rev-typo-refq-408-2020-40, rev-typo-refq-408-2024-32, rev-typo-refq-408-2025-37, rev-unsolvable-refq-408-2009-14

- UNRESOLVED：1 条 — rev-type_mismatch-refq-408-2012-10

明细见 `failure_cases.jsonl`；路由明细见 `routing_diagnostics.json`。

## 8. 与 smoke_v10 对比

| 指标 | smoke_v10（24 条） | rescored（318 条） | 差异 |
| --- | --- | --- | --- |
| conservative Recall | 75.00% | 76.21% | +1.21% |
| exact-type Recall | 62.50% | 65.20% | +2.70% |
| clean conservative FPR | 0.00% | 6.59% | +6.59% |
| UNRESOLVED | 0 | 1 | +1 |

smoke_v10 只覆盖 24 条分层子集，其点估计不具统计稳定性；此处仅用于观察方向是否一致。

## 9. 停止门判定

| 停止门 | 结果 | 依据 |
| --- | --- | --- |
| 结果 318 条且无重复 ID | 通过 | rows=318, unique=318, duplicates=0 |
| runner 异常样本为 0 | 通过 | runner_error=0 |
| JEV FALLBACK_RUN <= 5% | 通过 | 0/954 = 0.00% |
| UNRESOLVED <= 1% | 通过 | 1/318 = 0.31% |
| Clean conservative FPR <= 10% | 通过 | 6.59% (6/91) |
| 每类 conservative Recall >= 30% | 通过 | 全部达标 |
| exact-type Recall 与题级 Recall 差距 <= 15pp | 通过 | 差距 11.01% |
| 数据哈希可复现 | 通过 | dataset sha256 与预期一致 |
| Prompt 哈希可复现 | 通过 | 24/24 匹配 |
| 代码版本可复现 | 通过 | HEAD=4252f822c923 manifest=4252f822c923；工作树含本轮已批准的集成改动（未提交），见 run_state.model_switch.code_change |

### 可复现性

- 标签文件 SHA-256：`a605fdd210e33d307a7255304f300bce413163de8f03902911bc661c9e35238c`，与预期哈希 `a605fdd210e33d307a7255304f300bce413163de8f03902911bc661c9e35238c` 一致。
- Prompt 哈希：24/24 匹配。
- Git HEAD：`4252f822c923717e7e8a28c04a7ce4d19ace6ab8`，run_manifest 记录 `4252f822c923717e7e8a28c04a7ce4d19ace6ab8`（一致）。

## 10. 结论

全部停止门通过。可以提交 Dev A 报告并冻结当前版本。

是否进入 Blind 测试由用户决定，本轮未访问、未运行、未修改任何 Blind 数据。

### 已知限制

- Dev A 是开发集，本报告只用于回归诊断，不能据此宣布泛化能力提升。
- UNRESOLVED 按保守口径计入分母，未从指标中剔除。
- 运行前工作区已有未提交改动，可复现性依赖 `run_manifest.json` 记录的哈希清单。
