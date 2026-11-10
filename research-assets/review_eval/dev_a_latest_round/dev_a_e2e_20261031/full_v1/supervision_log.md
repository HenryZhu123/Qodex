# Dev A 全量评测监督日志

监督者：DeepSeek（按 `research-assets/review_eval/DEEPSEEK_DEV_A_SUPERVISION_GUIDE.md` 接管）
运行目录：`research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031/full_v1/`
主输出：`full_v1/results.jsonl`

## 1. 接管前检查（2026-10-31 23:23）

| 检查项 | 结果 |
| --- | --- |
| 结果行数 | 12 |
| 最后一条 | `clean-012` status=DETECTED，文件 mtime 2026/10/31 22:38:45 |
| 已有 Python 评测进程 | 无（`Get-Process python*` 计数 0） |
| 数据集行数 | 318（符合要求） |
| results.jsonl 可解析性 | 12/12 行可解析；unique=12；duplicates=0；无 runner_error |
| 已有 12 条构成 | 全部为 clean（clean-001..clean-012），CLEAN=10、DETECTED=2 |
| 脚本 | `run_end_to_end_evaluation.py` 存在（10511 bytes, mtime 2026/10/31 21:07:18） |
| `.env.local` | 存在；含 REVIEW_LLM 与 JEV 变量名（**未打印任何 Key 内容**） |

### 冻结配置核对（从 `.env.local` 与 CLI 参数读取非密钥字段）

| 配置项 | 值 | 与冻结配置一致 |
| --- | --- | --- |
| Reviewer model | `gpu-qwen3.8-27b` | 是 |
| Reviewer endpoint | `https://llm.talkweb.com.cn/v1` | 是 |
| JEV endpoint | `https://aihubmix.com/v1/systemone` | 是 |
| JEV 请求模型 | `jev-1.14` | 是 |
| Runner 外层并发 | 1 | 是 |
| Reviewer 内部并发 | 2（CLI 覆盖 env 的 8） | 是 |
| Reviewer 最大尝试 | 3 | 是 |
| Reviewer timeout | 180s | 未变更 |

> 说明：`plan.md` 中记有 `typesafe/jev-1.13`，但冻结口径（`run_state.json`、`run_manifest.json`、本手册第 3 节）均为 `jev-1.14`，实际返回 `jev-1.14.0`。本轮按冻结口径执行，未改动任何配置。

## 2. 断点续跑

- 启动时间：2026-10-31 23:23:40（+08:00）
- 后台 job：`pwsh-9`；控制台日志：`full_v1/run_console.log`
- 命令（与手册第 5 节完全一致，未改任何参数）：

```text
python research-assets\review_eval\scripts\run_end_to_end_evaluation.py ^
  --dataset research-assets\review_eval\taxonomy_v2\dev_a\strict\review_eval_dataset.csv ^
  --output research-assets\review_eval\dev_a_latest_round\dev_a_e2e_20261031\full_v1\results.jsonl ^
  --concurrency 1 --review-max-concurrency 2 ^
  --review-base-url https://llm.talkweb.com.cn/v1 --review-model gpu-qwen3.8-27b
```

- 验证断点续跑：进程第一条输出为 `[13/318] clean-013`，说明已有 12 条被正确跳过，未重复调用。

### 监控记录

| 时间 | 完成 | 备注 |
| --- | --- | --- |
| 23:23:40 | 12 | 启动 |
| 23:33 | 15 | clean-013..015；clean-014 判 DETECTED |
| 23:47 | 19 | clean-016..019 全部 CLEAN |
| 23:57 | 20 | clean-020 CLEAN |
| ~00:07 | 22 | clean-021 CLEAN；**clean-022 UNRESOLVED** |

- 初期速率约 4.2 分钟/条（外层并发 1 的预期量级）。318 条预计需要十余小时，属长尾正常现象，不中断。

### 首个 UNRESOLVED（clean-022）诊断

- `unresolved_checks = ["punctuation_check"]`，无 `runner_error`。
- `punctuation_check`：`FAILED`，attempts=3，error_code=`UPSTREAM_SERVER_ERROR`。
- 上游原文：`HTTP 500 ... funding billing ledger adjustment failed: Billing budget period does not match the current team funding period`（TalkWeb 侧计费周期故障，非本地配置或 Prompt 问题）。
- 判定：偶发上游 5xx，已用尽 3 次重试。按手册第 8 节保留原样，**不删除、不改写**；将于全量结束后用 `--sample-id` 定向重跑并写入 `unresolved_retries/results.jsonl`。

### clean 误报观察（截至 23 条）

- clean 前缀段：clean-012、clean-014 等被判 DETECTED，当前 clean FP = 3/23（13.0%）。
- 样本量极小，暂不做结论；全量结束后按 100 条 clean 重算，停止门阈值为 10%。

## 3. 事件：上游计费故障导致暂停（2026-11-01 00:01）

### 现象

- 23:57 之前一切正常（clean-021 判 CLEAN，check 全部 COMPLETED）。
- clean-022 起，所有 specialist 请求返回 HTTP 500。
- clean-023 的 5 个 direct task **全部** 失败（attempts 均为 3，全部用尽重试）。

```text
HTTP 500 {"error":{"message":"funding billing ledger adjustment failed:
Billing budget period does not match the current team funding period.",
"type":"new_api_error","code":"update_data_error"}}
```

### 判定依据

| 证据 | 结论 |
| --- | --- |
| 首个失败 request id `20261031160032...` = 2026-10-31 16:00:32 UTC = **00:00:32 +08** | 故障起始于月度计费周期切换瞬间 |
| clean-021（23:57）全部 task COMPLETED | 午夜前链路健康，不是配置问题 |
| 00:02:10 单独 probe 仍返回同一 500 `update_data_error` | 持续故障，非单次抖动 |
| clean-023 五个任务同时失败 | 影响面为整个 reviewer endpoint，而非单个 task |
| JEV 路由（aihubmix）全部正常返回 RUN/SKIP | 仅 TalkWeb 侧受影响 |

结论：TalkWeb 账号在 11 月计费周期切换后账单状态不一致，属**供应商侧故障**。客户端重试无法修复（同一错误连试 3 次均失败），也不属于本手册列举的可自行重试的偶发 5xx。

### 处置

1. 00:01:58 主动停止运行，确认无 Python 进程残留。
2. 主结果**未删除、未改写**：停在 23 条，23 行均可解析、ID 唯一、无重复。
3. `clean-022`、`clean-023` 保持 `UNRESOLVED` 原样（按第 8 节，结束时定向重跑）。
4. 更新 `run_state.json`：`current_stage = full_dev_a_paused_upstream_billing_outage`，并记录 `blocking_upstream`。
5. 暂停而非继续的原因：若继续运行，后续每条样本都会写入仅由基础设施故障造成的 `UNRESOLVED` 行，既会突破 UNRESOLVED ≤ 1% 停止门，也会污染主结果。

### 恢复条件

- probe 返回 HTTP 200 后再用**完全相同的命令**续跑；续跑会跳过已有 23 条（含 2 条 UNRESOLVED）。
- 需要用户在供应商侧修复 11 月账单周期状态，或等待其自动修复。

### 恢复探测记录

probe 脚本：`full_v1/probe_upstream.py`（只发 1 个 `max_tokens=1` 的请求，只打印状态码与错误摘要，不打印 Key）。

| 时间 | 结果 |
| --- | --- |
| 00:02:10 | HTTP 500 `update_data_error`（同一 billing 错误） |
| 00:08:19 | ReadTimeout（本地网络抖动，非结论） |
| 00:09:23 | ConnectTimeout（同上） |
| 00:10:28 | TCP 443 可连接、`curl` TLS 对所有站点均 exit 35（本地 curl/Schannel 问题，与评测无关；python 正常） |
| 00:10:42 | HTTP 500 `update_data_error` |
| 00:14:56 | ConnectTimeout（本地网络抖动） |
| 00:19:59 | HTTP 500 `update_data_error` |

结论：故障自 00:00:32 起持续 20 分钟未恢复，且 `request id` 每 4 分钟增长，说明是**同一持续状态**，非瞬时抖动。评测保持暂停，不产生新的 UNRESOLVED 行。

### 故障演进为硬配额拦截（00:36 起）

| 时间 | 结果 |
| --- | --- |
| 00:36:18 | HTTP **503**（供应商侧处理/过载） |
| 00:43:50 | HTTP **403** |
| 00:51:37 | HTTP 403 |
| 00:51:43 | HTTP 403 `code=insufficient_user_quota`，`项目配额不足` |
| 00:52:55 | HTTP 403 同上 |

错误内容：

```text
HTTP 403 {"error":{"message":"项目配额不足","type":"new_api_error",
"code":"insufficient_user_quota"}}
```

### 判定

- 状态从「账单周期不一致（500）」演进为「项目配额不足（403）」，说明供应商重启了计费/配额服务，但该账号在新周期的额度为 0 或未生效。
- 403 `insufficient_user_quota` 属手册第 6.3 节列举的**认证/配额类明确失败**：停止并报告，**不得反复重启**。
- 与 key 失效、endpoint 拼错、并发过高无关：同一 key 在 00:00 之前正常完成 21 条样本。

### 处置

- 评测保持暂停（23/318），主结果未改动。
- 不自动重试、不修改任何配置。
- 等待用户在 TalkWeb 侧**充值/开通 11 月项目配额**后，由探针确认返回 200 再续跑。

### 最终确认（00:53–00:57）

| 时间 | 结果 |
| --- | --- |
| 00:53:23 | HTTP 403 `insufficient_user_quota` |
| 00:55:26 | HTTP 403 `insufficient_user_quota` |
| 00:57:30 | HTTP 403 `insufficient_user_quota` |

403 配额不足已持续约 14 分钟且不再变化，判定为稳态阻塞，需要用户侧充值。监督进入 blocked 状态，恢复动作见下。

### 恢复步骤（用户充值后执行其一）

1. 告诉我「配额已加」，我会立刻用与第 5 节完全相同的命令续跑；或
2. 自行执行本日志第 2 节记录的原命令（一条不改）。

续跑会跳过已有 23 条（含 2 条 UNRESOLVED），不会重复调用。

## 4. 事件：更换 reviewer 模型（2026-11-01 上午）

TalkWeb 配额未恢复，用户决定改用 aihubmix 上的 `deepseek-v4.1-flash-1017`。

### 新配置

| 项 | 值 |
| --- | --- |
| Reviewer endpoint | `https://aihubmix.com/v1` |
| Reviewer 请求模型 | `deepseek-v4.1-flash-1017` |
| Reviewer max_tokens | 4096（新增环境变量） |
| reasoning_effort | 空（保留模型原生推理） |
| JEV | 不变（`jev-1.14` @ `/v1/systemone`，实际返回 `jev-1.14.0`） |
| 外层并发 / 内部并发 / 尝试次数 | 1 / 2 / 3（不变） |

### 三个 smoke 的取舍过程

| run | 配置 | recall | exact-type | clean FPR | UNRESOLVED | 失败原因 |
| --- | --- | --- | --- | --- | --- | --- |
| smoke_v8 | 2048 + 原生推理 | 81.25% | 75.0% | 12.5% | 1 | `logic_check` `JSON_TRUNCATED` |
| smoke_v9 | 2048 + 关推理 | 75.0% | **50.0%** | 0% | 1 | 仍截断，且 exact-type 掉 25pp |
| smoke_v10 | 4096 + 原生推理 | 75.0% | 62.5% | 0% | **0** | 选定配置 |

- 该模型是推理模型，`enable_thinking: False` 被 aihubmix 忽略，但 `reasoning_effort: "none"` 有效；实测关掉推理后截断仍存在（说明是 JSON 本身超长），且 exact-type 明显下降，因此放弃关推理、改为提高输出预算。
- smoke_v10：24/24 落盘、ID 唯一、无 runner 异常、无错误码、JEV 72 次决策 0 次 FALLBACK、p50 25s。

### 代码改动（已获用户批准）

| 文件 | 改动 |
| --- | --- |
| `src/exam_checker/config.py` | 新增 `review_reasoning_effort`、`review_max_tokens` 两个 Settings 字段 |
| `src/exam_checker/integrations/specialist_reviewer.py` | 构造函数新增 `reasoning_effort`/`max_tokens`；三处请求体按需注入 `reasoning_effort`；2048/1536 两处硬编码改为 `self.max_tokens` |
| `src/exam_checker/api/app.py` | 透传两个新配置 |
| `scripts/run_end_to_end_evaluation.py` | 透传两个新配置 |
| `.env.example` | 补充两个变量的说明 |

默认值保持旧行为（`reasoning_effort` 为空则不发送、`max_tokens` 默认 2048），因此不影响其他模型。`tests/test_specialist_reviewer.py` 等 8 个测试通过。

### 全量 v2

- 输出：`full_v2/results.jsonl`（不与 `full_v1` 混写；`full_v1` 的 23 条保留原样）
- 启动：2026-11-01 10:27:06
- 结束：318/318，退出码 0
- 说明：这是**不同 reviewer 模型**的结果，不能与 `full_v1` 或 `smoke_v7` 直接比较泛化能力。

## 5. 最终结果与停止门（full_v2）

### 完整性

| 项 | 值 |
| --- | --- |
| rows | 318 |
| unique_ids | 318 |
| duplicates | 0 |
| runner_error | 0 |
| UNRESOLVED | 1（0.31%） |

### 指标

| 指标 | 值 | Wilson 95% |
| --- | --- | --- |
| conservative Recall | 75.23% (164/218) | [0.691, 0.805] |
| exact-type Recall | 64.22% (140/218) | [0.577, 0.703] |
| macro conservative Recall | 0.7368 | — |
| Clean conservative FPR | **15.00% (15/100)** | [0.093, 0.233] |
| calibrated precision @5% | 0.2088 | — |
| calibrated precision @10% | 0.3578 | — |

分类别（conservative / exact-type）：typo 80.0/75.0、punctuation 60.0/55.0、option_structure 85.0/60.0、type_mismatch 85.0/85.0、solvability_failure 75.0/60.0、**ambiguity 44.4/11.1**、answer_leakage 90.0/85.0、factual_logical 70.0/60.0。

### 停止门

| 门 | 结果 |
| --- | --- |
| 318 条且无重复 | 通过 |
| runner 异常 0 | 通过 |
| JEV FALLBACK_RUN ≤5% | 通过（0/954 = 0%） |
| UNRESOLVED ≤1% | 通过（0.31%） |
| Clean FPR ≤10% | **未通过（15.0%）** |
| 每类 recall ≥30% | 通过（最低 ambiguity 44.4%） |
| exact-type 差距 ≤15pp | 通过（11.01pp） |
| 数据哈希 | 通过 |
| Prompt 哈希 | 通过（24/24） |
| 代码版本 | 通过但工作树含本轮已批准改动（已在 `full_v2/run_manifest_v2.json` 记录指纹） |

结论：`current_stage = full_dev_a_failed_quality_gate`。按手册第 9 节不得进入盲测。

### UNRESOLVED 定向重跑

- 样本：`rev-type_mismatch-refq-408-2012-10`
- 主结果失败原因：`INVALID_MODEL_RESPONSE`，模型对 `logic_check` 返回 `逻辑错误`（不在允许标签内），3 次尝试均如此。
- 定向重跑：`full_v2/unresolved_retries/results.jsonl` → 判 `DETECTED` 且类别命中，已恢复。
- 主结果未修改。

### 产物

`full_v2/` 下：`results.jsonl`、`summary.json`、`dev_a_report.md`、`routing_diagnostics.json`、`failure_cases.jsonl`、`run_manifest_v2.json`、`unresolved_retries/results.jsonl`。

### 与 qwen 版的可比性说明

`full_v1`（qwen/talkweb）只有 23 条且全部是 clean，无法与 `full_v2` 做同类对比。smoke_v10 与 smoke_v7 在 recall 上持平（75% 对 75%），但 smoke_v10 的 clean FPR 为 0%（8 条 clean，样本太小），全量 100 条 clean 才暴露出 15% 的真实误报率。

## 6. clean 标签人工裁决与重算（2026-11-01 下午）

用户审阅 15 条 clean 误报后确认裁决：9 条真实缺陷、4 条误报、2 条待定。

### 裁决结果

| 判定 | 样本 |
| --- | --- |
| 真实缺陷（移出 clean） | clean-012、clean-028、clean-029、clean-037、clean-061、clean-071、clean-074、clean-082、clean-096 |
| 误报（维持 clean） | clean-006、clean-010、clean-033、clean-098 —— 均为"……正确的是。"后接选项的真题格式 |
| 待定（暂维持 clean） | clean-041（疑漏"个"）、clean-099（146k vs 146K） |

归类：typo 6 条（012、028 次类、061、071、082、096）、solvability_failure 4 条（028、029、037、074）。新增两个词汇：`error_detailed_type=字符损坏`（clean-061 上划线乱码）、`solvability_subtype=no_valid_answer`（clean-074 无正确项）。

### 重算方式

- `review_eval_dataset_v2.csv`：仅改这 9 行的 label/error_type/详细类型，字段与 v1 完全一致（17 列）。**v1 原文件未改动**。
- `review_eval_dataset_v2.provenance.json`：记录 v1 哈希、裁决表哈希、逐条改动与新词汇。
- `full_v2/rescored/`：按 sample_id 复用同一批 318 条模型输出重新配对打分，**未调用任何模型**。

### 指标变化

| 指标 | v1 标签 | v2 标签 |
| --- | --- | --- |
| clean / 错误 | 100 / 218 | 91 / 227 |
| conservative Recall | 75.23% | **76.21%** |
| exact-type Recall | 64.22% | **65.20%** |
| macro Recall | 73.68% | **74.16%** |
| Clean conservative FPR | 15.00% | **6.59%** (6/91) |
| calibrated precision @5% / @10% | 0.2088 / 0.3578 | 0.3782 / 0.5622 |
| UNRESOLVED | 1 | 1 |

Wilson 95%（v2）：recall [0.7027, 0.8129]、exact [0.5880, 0.7110]、FPR [0.0306, 0.1365]。

**停止门在 v2 标签下全部通过**，`current_stage = full_dev_a_complete_ready_for_review`。这仍不等于可以进盲测——是否进入由用户决定。

### 注意

- 上述 v2 指标的分母已改变（clean 100→91、错误 218→227），**不能与 v1 数字直接做同比解读**；要比较 pipeline 改动，应固定 v2 标签做逐样本配对比较。
- 待定的 2 条若日后确认，重算只需再跑一次 `rescore_with_adjudication.py`。
