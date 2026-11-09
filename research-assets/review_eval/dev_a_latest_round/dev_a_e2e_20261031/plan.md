# Dev A 最新一轮端到端评测计划

## 目标

先用 Dev A 验证当前生产链路是否稳定、是否出现类别退化或误报上升；通过后冻结代码、Prompt、路由阈值和模型配置，再运行 Blind v2 与 Blind v2 expansion v1。

Dev A 是开发集，本轮结果只作为回归诊断，不作为最终泛化结论。

## 固定输入

- 数据集：`taxonomy_v2/dev_a/strict/review_eval_dataset.csv`
- 样本数：318（移除 2 条不可观察的 ambiguity 造错）
- 错误样本：218
- clean 样本：100
- 类型分布：typo 60、solvability_failure 40、ambiguity 18，其余 5 类各 20
- taxonomy：`missing_info` 与 `unsolvable` 已统一为 `solvability_failure`
- 主运行器：`scripts/run_end_to_end_evaluation.py`
- 禁用主指标脚本：`scripts/run_review_eval.py`，因为它会用 gold 类别选择 specialist，存在评测泄漏

## 固定运行配置

- Reviewer 请求模型：`gpu-qwen3.8-27b`
- Reviewer endpoint：Talkweb OpenAI-compatible endpoint
- Router 模型：`typesafe/jev-1.13`
- Runner 外层并发：1（TalkWeb 长尾稳定性修订）
- Specialist 内部最大并发：2（TalkWeb 长尾稳定性修订）
- Specialist 最大尝试：3
- 采用生产 `QuestionReviewService` 的八任务调度、JEV 路由、重试、聚合和三态输出
- 成功输出采用追加式 JSONL，支持只恢复未完成样本

运行前冻结并记录：Git commit、dirty status、数据集 SHA-256、Prompt 目录 SHA-256 清单、路由规则与阈值、模型和 endpoint 标识、环境配置是否存在。不得记录密钥内容。

## 启动配置状态

TalkWeb reviewer 与 JEV 中转站均已配置。JEV 使用精确 endpoint：

`https://aihubmix.com/v1/systemone`

2026-10-31 已通过一次真实 `answer_leak_check` 路由请求：HTTP 200，返回模型 `jev-1.14.0`，概率字段与 choice 结构校验通过。正式评测仍保留“JEV 密钥缺失即停止”的保护，避免意外进入全任务 fallback。

## Stage A：24 条分层冒烟

构造只读的确定性 smoke 子集：

- 8 个错误类型各 2 条，共 16 条
- clean 8 条
- 尽量覆盖四个 408 学科
- `solvability_failure` 覆盖 Dev A 中现有的 `missing_required_condition`

冒烟检查只用于验证链路，不用于判断模型最终质量。

通过条件：

1. 24/24 均落盘且 ID 唯一；
2. 无 runner exception；
3. `UNRESOLVED=0`；
4. JEV routing decision 正常存在，不能全部为 `FALLBACK_RUN`；
5. Reviewer 输出能解析，错误类型使用生产中文标签；
6. 断点续跑不会重复调用已完成样本；
7. summary、routing diagnostics 和配置清单均可复现。

若失败，只修复工程或配置问题，然后重跑 smoke；不得查看 Blind 数据。

## Stage B：Dev A 全量 320 条

冒烟通过后，使用完全相同的 frozen 配置运行全量 Dev A。输出到新的版本目录，不覆盖旧结果。

主指标：

1. 题级 conservative Recall：错误题中状态为 `DETECTED` 的比例；
2. exact-type Recall：检测到错误且命中 gold 顶层类别；
3. clean conservative FPR：clean 题被判为 `DETECTED` 的比例；
4. macro conservative Recall：各错误类型等权平均；
5. `UNRESOLVED`：错误题与 clean 题分别统计；
6. Wilson 95% 区间；
7. 5% 与 10% 真实错误率假设下的 calibrated precision。

诊断指标：

- 每类 conservative/conditional Recall 与 exact-type Recall；
- 目标 specialist 的 RUN、SKIP、FALLBACK_RUN 分布；
- 每题实际 specialist 调用数；
- 各 task 的失败、重试和错误码；
- 整体及分类 latency p50/p95；
- 模型返回错误类型混淆情况；
- false positive、false negative、wrong-type 和 unresolved 的样本 ID 清单。

## 进入盲测前的停止门

以下任一情况出现时，停止，不运行 Blind v2：

- 结果不满 320 条或存在重复 ID；
- runner exception 非零；
- JEV 大面积 `FALLBACK_RUN`；
- `UNRESOLVED` 超过 1%；
- clean FPR 超过 10%；
- 任一错误类型 conservative Recall 低于 30%；
- exact-type Recall 比题级 Recall 低超过 15 个百分点；
- 输出无法通过 schema、计数或可复现性检查。

这些是灾难性退化门，不是最终目标线。若未触发停止门，则产出 Dev A 报告并冻结当前版本；是否进入 Blind v2 由用户确认。

## 计划产物

- `run_manifest.json`：数据、代码、Prompt 与模型配置哈希
- `smoke_dataset.csv`
- `smoke/results.jsonl`
- `smoke/summary.json`
- `full/results.jsonl`
- `full/summary.json`
- `full/routing_diagnostics.json`
- `full/failure_cases.jsonl`
- `dev_a_report.md`

Blind v2 与扩充集路径不写入本轮运行命令，避免误触盲测数据。
