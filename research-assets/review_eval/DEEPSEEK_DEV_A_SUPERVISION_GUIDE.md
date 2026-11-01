# DeepSeek 接管 Dev A 全量测试操作手册

## 1. 任务目标

监督并完成 strict Dev A 的生产端到端评测，生成完整、可复现的结果和报告。

本任务只允许操作 Dev A。**禁止读取、搜索、运行或修改任何 Blind、blind_test、blind_v2、blind_v2_expansion 目录。** 不得运行旧脚本 `run_review_eval.py`，因为它会依据 gold 类别选择 specialist，存在评测泄漏。

从仓库根目录运行下文命令：

```text
<repository-root>
```

## 2. 当前状态（接管时先重新核实）

- strict Dev A：318 条。
- 数据集：`research-assets/review_eval/taxonomy_v2/dev_a/strict/review_eval_dataset.csv`
- 当前输出：`research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031/full_v1/results.jsonl`
- 本手册生成时已落盘：12/318 条。
- 原完整测试进程已经停止，需要使用下文命令断点续跑。
- 冒烟 `smoke_v7` 已通过：Recall 75%、exact-type Recall 68.75%、Clean FPR 0%、UNRESOLVED 0。

运行状态文件：

```text
research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031/run_state.json
```

## 3. 冻结配置

不得在全量测试过程中调整以下配置：

- Reviewer model：`gpu-qwen3.8-27b`
- Reviewer endpoint：`https://llm.talkweb.com.cn/v1`
- JEV 精确 endpoint：从 `.env.local` 读取，当前应为 `https://aihubmix.com/v1/systemone`
- JEV 请求模型：`jev-1.14`，实际返回版本可能为 `jev-1.14.0`
- Runner 外层并发：1
- Reviewer 内部并发：2
- Reviewer 最大尝试次数：3
- 主运行器：`research-assets/review_eval/scripts/run_end_to_end_evaluation.py`

API Key 从以下本地配置自动加载：

```text
pi-coding-agent/services/exam-checker/.env.local
```

只确认文件和变量存在，**禁止在终端、日志或报告中打印 Key 内容**。

## 4. 接管前检查

### 4.1 检查已完成数量和最后一条结果

在 PowerShell 中执行：

```powershell
$result = 'research-assets\review_eval\dev_a_latest_round\dev_a_e2e_20261031\full_v1\results.jsonl'
(Get-Content -LiteralPath $result).Count
Get-Content -LiteralPath $result -Tail 1
```

### 4.2 确认没有另一个 Python 评测进程

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match '^python' -and
    $_.CommandLine -like '*run_end_to_end_evaluation.py*full_v1*'
  } |
  Select-Object ProcessId, CreationDate, CommandLine
```

- 若没有输出：可以执行断点续跑。
- 若已有匹配进程：**不要再启动第二个进程**，直接进入监控步骤。
- 不得同时让两个进程写同一个 `results.jsonl`。

### 4.3 检查数据集条数

```powershell
python -c "import csv,pathlib; p=pathlib.Path(r'research-assets/review_eval/taxonomy_v2/dev_a/strict/review_eval_dataset.csv'); print(len(list(csv.DictReader(p.open(encoding='utf-8-sig', newline='')))))"
```

必须输出 `318`。不是 318 时停止，不要自行重建数据。

## 5. 断点续跑命令

从项目根目录运行：

```powershell
python research-assets\review_eval\scripts\run_end_to_end_evaluation.py `
  --dataset research-assets\review_eval\taxonomy_v2\dev_a\strict\review_eval_dataset.csv `
  --output research-assets\review_eval\dev_a_latest_round\dev_a_e2e_20261031\full_v1\results.jsonl `
  --concurrency 1 `
  --review-max-concurrency 2 `
  --review-base-url https://llm.talkweb.com.cn/v1 `
  --review-model gpu-qwen3.8-27b
```

运行器会读取已有 JSONL，并跳过已完成 `sample_id`，因此不要删除或清空当前结果文件。

## 6. 监督方式

### 6.1 正常监控

每 5～10 分钟检查一次即可，不要高频轮询：

```powershell
$result = 'research-assets\review_eval\dev_a_latest_round\dev_a_e2e_20261031\full_v1\results.jsonl'
"completed=$((Get-Content -LiteralPath $result).Count)/318"
Get-Content -LiteralPath $result -Tail 1
```

本配置可能出现数分钟的单题长尾。只要 Python 进程仍在，且没有明确异常退出，不要因为暂时没有新行而中断。

### 6.2 进程意外退出

若 Python 进程消失且结果不足 318 条：

1. 记录当前完成数量和最后一条 JSONL。
2. 保存终端错误信息。
3. 不删除现有结果。
4. 使用完全相同的命令重新启动。
5. 在监督日志中记录退出时间、完成数量和错误原因。

### 6.3 明确失败时停止

遇到以下情况应停止并报告，不要擅自改代码、Prompt、数据或阈值：

- 认证失败：401/403、`AUTHENTICATION_FAILED`。
- 数据集无法解析或数量不是 318。
- 输出 JSONL 出现无法解析的行。
- 同一个配置错误连续重启仍复现。
- 结果文件出现重复 `sample_id`。
- 发现另一个进程正在写同一输出文件。

上游超时、HTTP 5xx、模型 JSON 截断已经有重试机制；单次出现时让运行器自行处理。

## 7. 完成校验

进程正常结束后，执行以下只读校验：

```powershell
python -c "import json,pathlib; p=pathlib.Path(r'research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031/full_v1/results.jsonl'); rows=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]; ids=[r['sample_id'] for r in rows]; print({'rows':len(rows),'unique_ids':len(set(ids)),'duplicates':len(ids)-len(set(ids)),'unresolved':sum(r['status']=='UNRESOLVED' for r in rows)})"
```

必须满足：

- `rows = 318`
- `unique_ids = 318`
- `duplicates = 0`

运行器正常结束后应生成：

```text
research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031/full_v1/summary.json
```

若结果已经 318 条但没有 summary，可以用完全相同命令再运行一次；它会跳过全部样本并重新生成 summary。

## 8. UNRESOLVED 处理

主结果中的 `UNRESOLVED` 不得删除、覆盖或偷偷改成 CLEAN/DETECTED。

先列出未决样本和失败检查：

```powershell
python -c "import json,pathlib; p=pathlib.Path(r'research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031/full_v1/results.jsonl'); rows=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]; print(json.dumps([{'sample_id':r['sample_id'],'unresolved_checks':r['unresolved_checks'],'failures':[c for c in r['checks'] if c['execution_status']=='FAILED']} for r in rows if r['status']=='UNRESOLVED'],ensure_ascii=False,indent=2))"
```

若需要判断是否只是偶发上游故障，可将未决 ID 用重复的 `--sample-id` 参数单独重跑，并写入新文件：

```text
full_v1/unresolved_retries/results.jsonl
```

不得覆盖主结果。最终报告同时给出：

- 主运行的 conservative 指标；
- UNRESOLVED 数量和错误码；
- 定向重试是否恢复。

## 9. 最终停止门

以下任一条件触发时，不得进入盲测：

- 结果不足 318 条或存在重复 ID；
- runner 异常退出且无法断点恢复；
- JEV 大面积 `FALLBACK_RUN`，建议将超过全部路由决策 5% 视为系统性异常；
- `UNRESOLVED > 1%`，318 条中即 4 条及以上；
- Clean conservative FPR > 10%；
- 任一错误类型 conservative Recall < 30%；
- exact-type Recall 比题级 conservative Recall 低超过 15 个百分点；
- schema、计数、数据哈希或配置无法复现。

这些是灾难性退化门，不是最终目标线。即使全部通过，也只表示可以提交 Dev A 报告；**不得自行启动 Blind 测试**。

## 10. 最终报告要求

在目录中生成：

```text
research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031/full_v1/dev_a_report.md
```

报告必须包含：

1. 数据集 318 条的标签和类别分布。
2. conservative Recall、exact-type Recall、macro Recall。
3. Clean conservative FPR。
4. Wilson 95% 区间。
5. 5% 和 10% 真实错误率假设下的 calibrated precision。
6. 每类 conservative/conditional Recall 和 exact-type Recall。
7. JEV RUN、SKIP、FALLBACK_RUN 分布。
8. 每个 task 的失败数、重试数、错误码。
9. 题级延迟 p50、p95、最大值。
10. false positive、false negative、wrong-type、UNRESOLVED 的样本 ID 清单。
11. 与 `smoke_v7` 的差异。
12. 每条停止门是否通过，以及最终结论。

同时建议生成：

```text
full_v1/routing_diagnostics.json
full_v1/failure_cases.jsonl
```

## 11. 更新运行状态

完成并验证后更新：

```text
research-assets/review_eval/dev_a_latest_round/dev_a_e2e_20261031/run_state.json
```

- 通过所有停止门：`current_stage = "full_dev_a_complete_ready_for_review"`
- 未通过质量门：`current_stage = "full_dev_a_failed_quality_gate"`
- 不要写成“blind ready”或启动盲测；是否进入盲测由用户决定。

## 12. 严格禁止事项

- 禁止访问或运行 Blind 数据。
- 禁止修改 API Key 或输出其内容。
- 禁止在本轮中途修改 Prompt、代码、路由阈值、并发或数据集。
- 禁止删除已有结果来“重新跑得更好”。
- 禁止用 gold `error_type` 选择 specialist。
- 禁止把 UNRESOLVED 从指标分母中静默删除。
- 禁止为了降低 FPR 压制具有明确文本证据的真实错误。
- 禁止根据 Dev A 结果直接宣布泛化提升；Dev A 只用于开发回归。

DeepSeek 的职责是：保持冻结配置、可靠完成运行、如实诊断结果、生成报告，并在任何停止门失败时阻止盲测。
