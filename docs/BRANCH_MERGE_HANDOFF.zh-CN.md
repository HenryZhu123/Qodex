# 分支合并交接（feat/question-generation → 集成分支）

> 状态：已按本文完成集成。源分支采用 `origin/feat/question-generation@2acd161`，并合入
> `origin/codex/generation-owns-versions` 的版本所有权实现。
> 计划本身见对方提供的《命题分支与版本权限分支合并方案》；本文只写**合并时容易做错的地方**与**必须保留的东西**。

## 1. 已按合并方案修好的四条

| 方案条目 | 我们的提交 | 现状 |
| --- | --- | --- |
| 4.3 工作流覆盖完整工具结果 | `fc9f28d` | 业务结果**原样保留**，`[qodex]{observation}` 追加在后面；`isError` 仍按失败设置 |
| 4.4 `REVISED` 被当成失败 | `e2dff23` | 成功集合 = `GENERATED` \| `REVISED`；`queue_receipts` 出现 `VERSION_CONFLICT`/`SUPERSEDED` 判失败 |
| 4.5 三轮策略与服务能力不一致 | `e2dff23` | 通用创作题修订链放开到 **v1→v2→v3**，v3 之后再改返回 `REVISION_LIMIT`；`REVISION_VERSION` 自身产生的题包可再修订 |
| 4.6 策略文字仍引用旧工具 | `e2dff23` | 提示改指 `question_generation.revise`（沿用 `task_id`、`feedback_id = review_id`、`target_version = 被审校版本`） |

4.1 已采用完整约束；4.2 已在集成时按版本所有权分支实现，结果见第 4 节。

## 2. 合并时必须从我们这边保留的能力

按文件列出，冲突时以这一栏为准：

| 文件 | 必须保留 |
| --- | --- |
| `question_generation/sql/002_generation_tasks.sql` | `generation_mode` 含 `author`、`replenishment`，且是幂等 `DROP CONSTRAINT`/`ADD CONSTRAINT`（演示脚本每次重放 SQL） |
| `question_generation/general_revision.py` | v1→v2→v3 链；接受 `REVISION_VERSION` 题包；`REVISION_LIMIT` 只在 v3 之后 |
| `question_generation/service.py` | `task_id` 注入与 `queue_receipts`；准入 503、阶段日志、`PIPELINE_DEADLINE`；`QUEUE_VERSION_CONFLICT` 409 |
| `pi-coding-agent/.../extensions/qodex-workflow/index.ts` | 政策（五类输入、四类失败处置、三轮换改法）；护栏（预算按目标题量 `2N+2`/`3N+2`、重复付费拦、连续失败/无进展停止、停止后用户回复可续做、`goal_report`、逐题账本、只读查询透传、`tool_result` 追加而非替换） |
| `pi-coding-agent/.../services/exam-checker/.../generated_question_service.py` | `_to_question_view` 的字段归一：`subject` 中文、单选 `points`、选项 `A.`–`D.` 前缀、`answer_text` 取正确选项原文、`reference` 置空 |
| `docs/samples/` | 全目录（成功与失败的真样本，改字段前比对用） |
| `docs/agent-workflow.md`、`docs/workflow-target.md` | 政策/护栏与目标形态说明 |

## 3. 合并时容易做错的四件事

1. **不要为了消除冲突把 `generation_mode` 回退到 main 的旧列表**——`author` 命题会付完模型钱后写库 503。
2. **不要恢复"用 observation 替换工具结果"**。那样模型拿不到题包和 `task_id`；实测中它去连库 `select` 了 7 次才凑出审校参数。
3. **不要整文件 `ours` / `theirs`**。至少这四个文件的改动是**双方都要**的：
   `generated_question_service.py`（我们的归一 + 你们的不可变冲突检查）、
   `exam-checker/index.ts`（删 `revise_question` + 保留 `review_id` 透传）、
   `question_generation/index.ts`（`author`/`replenishment` + 你们的 `task_id` 注入与管理修订提示）、
   `AGENTS.md`（我们的开发原则 + 你们的"只有命题创建版本"）。
4. **不要删 `docs/samples/`**，它不参与冲突，但删了以后没人能对着真实字段排查。

## 4. 4.2 集成结果

集成结果已经删除 `POST /v1/exam-checker/{documents,tasks}/.../revise`、Pi 的 `revise_question`、
审校侧修订模型和版本创建仓储能力。新版本只能由 `question_generation.revise` 创建：

- 通用创作题（`general-authoring-*`）：修订链已开放到 v3，删掉旧入口**没有影响**；
- 综合题：`question_generation.revise` 已支持（`part_id`/`action` 级反馈）；
- **旧确定性单选题**：目前没有通用反馈修订通道。删掉旧入口后，这类题的修订会返回 `UNSUPPORTED_REQUEST`。

旧确定性题被要求修订时，Agent 必须处理 `UNSUPPORTED_REQUEST` 并说明“该题不支持定向修订，需重新命题”，
不得回退到 exam-checker 修改版本。OpenAPI 回归测试保证审校服务不再出现 `/revise`。

## 5. 交接后我们这边还会做什么

- 我们不再改 `codex/generation-owns-versions` 涉及的文件；如需改动会先通知，避免合并期间基线漂移。
- 集成分支上出现的失败（测试红、字段对不上、组卷读不到题）可以直接找我们，附：
  失败命令 + 完整报错 + 相关 trace（`.local/qodex-traces/workflow-*.jsonl`）或服务响应 JSON。

## 6. 我们这边的验证基线（合并后应仍然成立）

```bash
python -m unittest discover -s tests                 # 319 passed, 7 skipped
cd pi-coding-agent/packages/coding-agent
npx vitest run test/suite/qodex-workflow.test.ts \
  test/suite/question-generation.test.ts \
  test/exam-assembly-extension.test.ts \
  test/exam-checker-extension.test.ts                # 45 passed
npx tsgo --noEmit                                    # src/ 0 errors
```
