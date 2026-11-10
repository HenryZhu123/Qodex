# Review Agent 五类瓶颈突破计划

## 目标与边界

本计划修复评测与生产行为不一致、clean FPR 测量不完整、弱标签、基础设施失败混入 FN，以及事实核验把未知当正确的问题。Blind Test v2 已经完成过一次测量，后续不再宣称它是未见测试集；它作为审计集和成对反事实集使用。

## 1. 端到端评测与生产同构

状态：已实现。

- `scripts/run_end_to_end_evaluation.py` 直接复用生产 `QuestionReviewService`。
- 每道题运行生产定义的八任务、Jev 路由、重试和题级聚合；原 `missing_check` 与 `unsolvability_check` 已合并为 `solvability_check`。
- gold `error_type` 只参与事后分组，不参与 specialist 选择。
- 输出每个任务的路由、尝试次数、错误码、延迟、知识库查询和最终题级状态。

验收：同一输入在 runner 与生产服务中产生相同的八任务调度和聚合语义。

## 2. 完整 clean FPR 与指标校准

状态：已实现。

- clean 与错题经过完全相同的八任务链路。
- `scripts/evaluation_metrics.py` 同时输出 micro、macro、分类指标和 Wilson 95% 区间。
- 同时报告题级“任意错误检出率”和 gold 类别的 exact-type Recall，避免错误 specialist 的误报被算成正确检出。
- 分别报告保守指标与仅有效响应的条件指标。
- 将观测 Recall/FPR 按 5% 和 10% 真实错误先验换算 Precision。

验收：不再使用“clean 只跑 typo”的 FPR；报告必须包含题级 FPR 和 specialist 明细。

## 3. 数据质量门禁与成对评测

状态：已完成人工裁决、统一分类和严格集导出。

- `scripts/validate_dataset_quality.py` 检查 mutation round-trip、唯一锚点、源题重叠和标签强度。
- 答案泄露分为 L2 直接泄露、L1 部分提示、L0 普通提示；只有 L2 自动进入严格指标，L1 需人工证明提示足以唯一确定答案。
- `missing_info` 与 `unsolvable` 已合并为 `solvability_failure`；其中 `missing_required_condition` 必须提供至少两个题面可兼容、答案不同的 necessity witnesses。
- `scripts/export_paired_dataset.py` 为每个 mutation 导出 clean/mutated 对。
- `scripts/score_paired_results.py` 仅在 clean 正确通过且 mutated 正确拒绝时计 pair success。

v2 人工裁决结果：197 条原始记录中移除 12 条，形成 185 条 adjudicated 集；另将 11 条 L0 与 5 条 L1/diagnostic-only 排除出主指标，形成 169 条 strict 集。人工决定与严格资格分字段保存，避免覆盖人工意见。

验收：后续论文主指标仅统计严格合格样本；弱样本单列为诊断集。

## 4. 三态失败模型与可观测性

状态：已实现。

- 统一状态为 `DETECTED`、`CLEAN`、`UNRESOLVED`。
- HTTP 非 200、超时、无效 JSON、无证据、抽取失败均保留结构化原因。
- UNRESOLVED 不再静默转为 CLEAN。
- 保守 Recall 将 UNRESOLVED 计入分母；条件 Recall 明确排除它。
- 端到端结果保存每个 specialist 的 `error_code`、`retryable`、`attempts` 和错误摘要。

验收：任意漏检都能区分模型判错、路由跳过、检索不足和基础设施失败。

## 5. factual_logical 约束核验

状态：已实现第一批通用不变量和证据四态。

- 生产 `factual_guard.py` 新增地址位宽/容量、CPI、调制阶数、TCP SYN、超时拥塞状态和堆不变量。
- 这些规则验证题面内部约束，不依赖具体题号或正确选项。
- `factual_pipeline_v2.py` 为每条 claim 独立保存 subject，修复“最后一条学科覆盖全部 claim”。
- 证据结果区分冲突、明确支持和证据不足；抽取失败、无 claim、无检索结果不再判 clean。
- 数值矛盾由约束守卫处理，RAG 只承担教材定义和协议规则核验。

验收：Blind v2 六种 factual mutation 均被通用守卫覆盖，同时一致的 clean 对照不触发。

## 推荐运行顺序

```powershell
python research-assets/review_eval/scripts/validate_dataset_quality.py `
  --manifest research-assets/review_eval/blind_test_v2/phase2/mutation_manifest.jsonl `
  --report research-assets/review_eval/blind_test_v2/dataset/quality_audit.json

python research-assets/review_eval/scripts/export_paired_dataset.py `
  --manifest research-assets/review_eval/blind_test_v2/phase2/mutation_manifest.jsonl `
  --output research-assets/review_eval/blind_test_v2/dataset/blind_v2_paired.csv

python research-assets/review_eval/scripts/run_end_to_end_evaluation.py `
  --dataset research-assets/review_eval/taxonomy_v2/blind_v2/strict/blind_v2_dataset.csv `
  --output research-assets/review_eval/blind_test_v2/runs/end_to_end_paired/results.jsonl

python research-assets/review_eval/scripts/score_paired_results.py `
  --results research-assets/review_eval/blind_test_v2/runs/end_to_end_paired/results.jsonl
```

完整端到端运行会产生真实模型调用，应在 API 配额和网关稳定时执行。离线单元测试不使用外部模型。
