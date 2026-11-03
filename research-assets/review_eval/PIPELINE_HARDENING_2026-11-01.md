# 管线加固批次改动清单（2026-11-01）

范围：`4252f82..eca395f`，**94 个文件，+32,595 / −442 行**。

## 0. 先说一个容易误读的点

这批提交把当时并行的两条工作线合并成了一次提交，所以文件跨度很大：

| 工作线 | 内容 | 归属文件 |
| --- | --- | --- |
| **A. 审校管线加固** | 任务合并、提示词重写、公理守卫扩展、tool 循环补全 | 服务代码 + 提示词 + 测试 |
| **B. 模型接入参数** | 推理模型适配（`reasoning_effort` / `max_tokens`）、`.env.local` 加载、中转站 endpoint | `config.py`、`specialist_reviewer.py` 部分 |

核对依据：`_review_with_tools` 在本批次之前（10-29）就存在；`_reasoning_params` 是本批次才加的。
下面按文件逐条列，不做归属推断。

---

## A. 服务代码（9 个）

| 文件 | 增删 | 改了什么 |
| --- | ---: | --- |
| `integrations/specialist_reviewer.py` | +191 / −24 | 新增 `_reasoning_params()`（仅当配置了 `reasoning_effort` 才注入请求体）；新增 `_regenerate_compact_json()`（JSON 被截断后要求模型重新输出紧凑 JSON）；新增 `_match_ignoring_whitespace()`（锚点文本带空白差异时仍能定位）；`_review_with_tools` 补 `tool_choice` 处理（末轮强制 `none`） |
| `parsing/factual_guard.py` | +182 / −1 | 新增 `_numeric_invariant_guard()`（位宽/容量跨字段矛盾，如 n 位地址空间里放了更大的 cache）；新增 `_protocol_invariant_guard()`（协议参数矛盾）；抽出 `_result()` 构造器 |
| `config.py` | +62 / −3 | 新增 dotenv 加载器 `_load_env_file()` / `_load_local_environment()`（读服务目录 `.env.local`、`.env`，不覆盖已有环境变量，带变量名与格式校验）；新增 4 个配置项：`review_reasoning_effort`、`review_max_tokens`、`agentic_logic_prompt_path`、`jev_endpoint` |
| `prompts/repositories.py` | +1 / −2 | 任务表里 `missing_check`、`unsolvability_check` 合并为 `solvability_check`（模式 `explicit`） |
| `domain/models.py` | +1 / −2 | 任务枚举同步合并 |
| `services/question_review_service.py` | +1 / −2 | 同上，任务集合同步 |
| `api/app.py` | +4 | 向 JEV 客户端传 `endpoint_url`；向 reviewer 传 `reasoning_effort`、`max_tokens`、`agentic_logic_prompt_path` |
| `integrations/openrouter_decisions.py` | +6 / −4 | 支持显式 `endpoint_url`：中转站给完整 URL 时直接使用，不再拼 `/decisions` |
| `.env.example` | +21 | 新增上述配置项说明；补中转站 endpoint 用法 |

## B. 提示词（6 个）

| 文件 | 增删 | 改了什么 |
| --- | ---: | --- |
| `disabled/tasks/ambiguity_check.txt` | **+46 / −358** | **整篇重写**（原 358 行被删）。新版权威界定：只查会改变题意/作答结果的明确语义问题，明令不得越界到错别字、标点、选项结构、缺失、无解、事实错误 |
| `explicit/tasks/solvability_check.txt` | **+56（新增）** | 合并后的统一可解性提示词，替代原 `missing_check` 与 `unsolvability_check` 两份 |
| `explicit/tasks/answer_leak_check.txt` | +7 | 收紧泄露判定 |
| `explicit/tasks/punctuation_check.txt` | +9 | 收紧标点判定 |
| `disabled/tasks/typo_check.txt` | +1 | 新增禁令：不得把可成立的教材术语擅自扩写（例："界地址保护"不得改成"界限地址保护"） |
| `question-revision-prompt/system.txt` | +1 / −1 | 措辞微调 |

## C. 测试（5 个）

| 文件 | 增删 | 说明 |
| --- | ---: | --- |
| `tests/test_specialist_reviewer.py` | +189 / −1 | 覆盖 tool 循环、紧凑重生成、空白容错匹配 |
| `tests/test_factual_guard.py` | +61（新增） | 数值/协议守卫用例 |
| `tests/test_config_env_file.py` | +32（新增） | dotenv 加载与优先级 |
| `tests/test_openrouter_decisions.py` | +36 | 显式 endpoint 分支 |
| `tests/test_question_review_service.py` | +3 / −5 | 任务合并后的断言 |

## D. 评测资产

### D1 新增脚本（7 个，共约 1,300 行）

| 文件 | 行数 | 作用 |
| --- | ---: | --- |
| `run_end_to_end_evaluation.py` | 267 | 端到端运行器：八任务调度、断点续跑、JSONL 追加 |
| `evaluation_metrics.py` | 129 | 题级指标：Wilson 区间、calibrated precision、UNRESOLVED 保守口径 |
| `validate_dataset_quality.py` | 148 | 数据集质检 |
| `prepare_dev_a_smoke.py` | 158 | 24 条分层冒烟子集 |
| `migrate_solvability_taxonomy.py` | 279 | `missing_info`/`unsolvable` → `solvability_failure` 迁移 |
| `exclude_unobservable_dev_a_ambiguity.py` | 105 | 剔除不可观察的 ambiguity 造错 |
| `factual_pipeline_v2.py` | +82 / −25 | 事实流水线调整 |

### D2 `taxonomy_v2/` 数据集（新增 30+ 文件）

- `dev_a/`：320 条（strict 318 条）+ gold + full + summary + exclusion audit
- `dev_b/`：240 条（历史文件名 `blind_test_*`，实为开发集）+ gold + full + summary
- `blind_v2/`：197 条 + gold + full + summary
- 各含 `migration_manifest.jsonl` 记录来源映射
- `generation_report.json`、`README.md`

### D3 改动既有数据集

`dataset/review_eval_dataset.csv`、`review_eval_full.jsonl`、`clean_set.jsonl`、`clean_candidates.jsonl`；`skills/question-error-synthesis/` 三份文档同步。

### D4 Dev A 运行产物（新增）

`dev_a_latest_round/dev_a_e2e_20261031/` 下：`plan.md`、`run_state.json`、`run_manifest.json`、`full_v1/supervision_log.md`、`full_v2/` 全套（results、summary、report、routing_diagnostics、run_manifest_v2、rescored、unresolved_retries）。

> 注意：本批次里的 `full_v2` 是随后被 `full_v2/protocol_eval` 取代的题级结果；`clean_adjudication.csv` 与 `review_eval_dataset_v2.csv` 也在这批入库，但当时尚未产生预测级协议报告。

### D5 文档

`BREAKTHROUGH_PLAN.md`、`DEEPSEEK_DEV_A_SUPERVISION_GUIDE.md`、`taxonomy_v2/README.md`。

### D6 删除

4 个 SQLite 临时文件（`app.db-shm` / `app.db-wal`），同时 `.gitignore` 增加忽略规则。

---

## 核对建议

1. **先看两处行为改变最大**：`specialist_reviewer.py`（+191）与 `factual_guard.py`（+182）——它们直接决定检出与误报。
2. **`ambiguity_check.txt` 是整篇重写不是微调**（−358 行），建议完整读新旧两版再判断是否接受。
3. **任务合并是全局影响**：`missing_check` + `unsolvability_check` → `solvability_check` 同时改了 4 个代码位置 + 提示词 + 测试，任何遗漏都会导致任务查不到 prompt 而报错。
4. **`taxonomy_v2` 的数据是三套集合**，其中 `dev_b` 的文件名仍叫 `blind_test_*`，容易被误认为留出集。

自查命令：

```powershell
# 只看服务代码
git diff 4252f82..eca395f -- pi-coding-agent/services

# 只看提示词
git diff 4252f82..eca395f -- pi-coding-agent/services/exam-checker/prompts

# 只看新增文件清单
git diff --name-status 4252f82..eca395f | Select-String '^A'
```
