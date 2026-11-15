# 命题分支与版本权限分支合并方案

> 状态：已按本方案集成 `feat/question-generation@2acd161` 与
> `codex/generation-owns-versions@d11e6a3`；本文继续作为冲突决策和验收依据。

## 1. 目的

本文用于合并以下两个远端分支，并把结果交付到 `main`：

| 分支 | 核对提交 | 主要内容 |
| --- | --- | --- |
| `feat/question-generation` | `2acd161` | 通用材料驱动命题、`author`、`replenishment`、命题修订、命题工作台和 Qodex 工作流护栏 |
| `codex/generation-owns-versions` | `d11e6a3` | 只有命题服务能创建题目版本；审校只审固定版本；网页、CLI、服务和文档统一这一权限边界 |

两个分支都以 `main@c2268b5` 为共同基线。`feat/question-generation` 已经合入过该 main，技术上可以合并；但两个分支对“谁创建版本”和“Agent 如何取得修订数据”的理解不同，不能直接采用默认冲突结果。

## 2. 合并后的最终契约

以下规则是验收标准，不因文件冲突而改变：

1. `question_generation` 是唯一可以创建 v2、v3 等新题目版本的服务。
2. `exam_checker` 只读取并审校不可变的 `(task_id, question_id, version)`，不得创建或改写版本。
3. 审校返回 `NEEDS_REVISION` 时，只返回 `review_id`、结构化错误和修改建议。
4. Pi Agent 自主判断是否调用 `question_generation` 的 `revise` 操作；后端不写死“命题 → 审校 → 再命题”的固定状态机。
5. 修订请求必须沿用原 `task_id` 和 `question_id`，并满足：
   - `current_question` 是命题工具返回的完整当前版本题包；
   - `feedback.feedback_id` 等于真实 `review_id`；
   - `feedback.target_version` 等于被审校版本；
   - 新版本重新进入 `PENDING`，必须再次独立审校。
6. 只有同版本的 PASS 审校才能把题目写入 `question_bank`。
7. 网页端和 CLI 端加载同一组 Pi 内置扩展，不保留绕过 Agent 的网页修订按钮。

建议把“一道题最多处理三个被拒绝版本”明确定义为最多审校 v1、v2、v3。v3 仍不通过时，Agent 停止并报告失败。如果团队希望“三次重做”表示允许生成到 v4，需要在实现前统一修改该定义、预算和测试。

## 3. 各分支应保留的能力

### 3.1 从 `feat/question-generation` 保留

- `author` 和 `replenishment` 两个命题模式。
- `generation_mode` 的完整约束：

  ```text
  single, batch, comprehensive, revise, author, replenishment, legacy
  ```

- `002_generation_tasks.sql` 中重新创建 CHECK 约束的逻辑。演示脚本每次按顺序重放 `question_generation/sql/*.sql`，因此该幂等 ALTER 同时覆盖已有数据库和新数据库。
- 通用材料驱动单选题、综合题和已有的定向修订能力。
- 命题模型超时、错误详情、可观测性、缓存、自检、盲解和审计逻辑。
- 组卷补题以及命题成功后的待审入队。
- 生成题导入审校时的字段适配：学科中文名、单选题分值、A–D 选项标签和组卷可接受的答案格式。
- `qodex-workflow` 的预算、重复调用阻断、失败停止、trace 和入库声明护栏。

### 3.2 从 `codex/generation-owns-versions` 保留

- 删除 exam-checker 的两个 `/revise` HTTP 入口。
- 删除 Pi `exam_checker.revise_question` 操作及相关参数。
- 删除审校侧的修订 Prompt、修订模型调用和 `create_revision` 仓储能力。
- 生成版本导入审校时的不可变内容校验：相同 `(task_id, question_id, version)` 不允许不同内容覆盖。
- UUID `task_id` 始终从 `question_generation.pending_questions` 读取并核对，避免审校快照遮蔽命题端冲突版本。
- Pi 审校结果保留真实 `review_id`，供命题修订写入 `feedback_id`。
- 网页工作台移除“审校端 AI 修订与重审”按钮。
- OpenAPI、Pi 扩展和服务测试中“审校无修订入口”的回归断言。

## 4. 已确认的不一致与处理方式

### 4.1 `generation_mode`

`main` 的旧约束不包含 `author/replenishment`。一旦新命题入口写入这两个值，模型可能已经完成调用，但任务写库因 CHECK 失败而返回 503。

处理：采用命题分支的完整约束和幂等 `DROP CONSTRAINT` / `ADD CONSTRAINT`，不得回退到旧列表。

### 4.2 exam-checker 仍能创建版本

`feat/question-generation@8a98b63` 仍保留：

- `/v1/exam-checker/documents/{document_id}/questions/{question_id}/revise`
- `/v1/exam-checker/tasks/{task_id}/questions/{question_id}/revise`
- Pi 操作 `revise_question`

处理：采用版本权限分支的删除结果。不得为了减少冲突恢复这些入口。

### 4.3 Qodex 工作流会覆盖完整工具结果

命题分支的 `qodex-workflow` 当前把命题和审校工具结果替换成简化的 `observation`。这会让模型看不到修订所需的完整题包、`review_id` 和详细错误。

处理：

- trace 和内部账本可以继续记录压缩 observation；
- 不覆盖传给模型的原始业务结果，或者在返回内容中同时保留完整业务结果和 observation；
- 至少保留 `task_id`、`question_id`、`version`、`review_id`、完整 `current_question`、`errors`、`ingestion` 和 `queue_receipts`；
- `question_bank` 继续保持只读结果原样返回。

推荐实现是：`tool_result` hook 只更新内部账本并写 trace，正常情况下返回 `undefined`；只有真正需要阻断或补充安全提示时才修改工具结果。

### 4.4 `REVISED` 被当成失败

现有工作流只把 `status=GENERATED` 视为命题成功，但修订成功返回 `status=REVISED`。

处理：命题成功集合至少包含 `GENERATED` 和 `REVISED`，同时核对返回题目非空以及 `queue_receipts` 没有 `VERSION_CONFLICT` 或 `SUPERSEDED`。

### 4.5 三轮策略与服务能力不一致

当前能力并不等价于“所有单选题都能连续修订三轮”：

- 通用 authored 单选/综合题目前只允许 v1 → v2；
- 分页、栈确定性综合题最多到 v3；
- 旧确定性单选题没有通用反馈修订。

处理：

1. 演示主路径优先使用通用 authored 单选题。
2. 扩展通用修订，使 v2 能继续作为 `current_question` 生成 v3。
3. 修订生成器必须接受自身 `REVISION_VERSION` 产生的题包，同时继续校验原始材料、题目身份和目标版本。
4. 不支持修订的旧生成器返回明确的 `UNSUPPORTED_REQUEST`，不得回退到 exam-checker 修改题目。
5. 工作流策略、预算、停止提示和测试统一使用“最多审校 v1、v2、v3”。

### 4.6 工作流文字仍引用旧工具

命题分支的策略和文档仍出现 `revise_question`，部分提示还写成“第二轮仍不过就停止”，与顶部“三轮”规则冲突。

处理：全部改成明确调用：

```json
{
  "tool": "question_generation",
  "operation": "revise"
}
```

并统一停止条件，避免模型尝试已经删除的 exam-checker 操作。

## 5. 预计冲突文件

使用 `git apply --check` 对两个远端提交做过兼容探测，至少以下文件需要人工合并：

| 文件 | 合并原则 |
| --- | --- |
| `AGENTS.md` | 保留命题分支的长期开发原则，同时保留“只有命题创建版本”的系统事实 |
| `pi-coding-agent/packages/coding-agent/src/extensions/question-generation/index.ts` | 保留 `author/replenishment`、长超时和错误详情，再加入唯一版本所有权、`review_id → feedback_id` 和自主修订提示 |
| `pi-coding-agent/services/exam-checker/src/exam_checker/services/generated_question_service.py` | 同时保留命题分支的字段归一化和版本权限分支的不可变冲突检查 |
| `pi-coding-agent/services/exam-checker/tests/test_generated_question_service.py` | 合并两组测试，不以删除一组断言解决冲突 |

还需人工检查以下无文本冲突但有语义冲突的文件：

- `pi-coding-agent/packages/coding-agent/src/extensions/qodex-workflow/index.ts`
- `pi-coding-agent/packages/coding-agent/src/extensions/exam-checker/index.ts`
- `pi-coding-agent/services/exam-checker/src/exam_checker/api/app.py`
- `question_generation/comprehensive.py`
- `question_generation/general_revision.py`
- `question_generation/service.py`
- `question_generation/sql/002_generation_tasks.sql`
- `docs/agent-workflow.md`
- `docs/QUESTION_GENERATION_REVIEW_INTEGRATION.zh-CN.md`

## 6. 推荐合并步骤

不要直接在 main 上解决冲突。建议由一名组员建立集成分支：

```bash
git fetch origin refs/heads/main:refs/remotes/origin/main
git fetch origin refs/heads/feat/question-generation:refs/remotes/origin/feat/question-generation
git fetch origin refs/heads/codex/generation-owns-versions:refs/remotes/origin/codex/generation-owns-versions

git switch -c integration/question-generation-version-workflow origin/feat/question-generation
git merge --no-ff origin/codex/generation-owns-versions
```

发生冲突后按本文第 3～5 节处理。不要直接选择 `ours` 或 `theirs` 覆盖整个文件。

推荐拆成以下阶段提交，方便审查和回滚：

1. `merge: combine question generation and version ownership branches`
2. `fix(workflow): preserve revision payloads and recognize revised versions`
3. `feat(question-generation): support reviewed v2 to v3 revision`
4. `docs: align autonomous generation and review workflow`
5. `test: cover autonomous revision and immutable version handoff`

集成分支验证完成后再创建面向 main 的 PR。合并前冻结并在 PR 中记录两个源提交；如果源分支在验证期间继续更新，重新评估增量提交，不静默改变验收基线。

## 7. 必须补充的测试

### 7.1 服务与数据库

- `generation_mode=author` 和 `replenishment` 能在已有数据库写入。
- 相同版本、相同内容重试返回幂等成功。
- 相同版本、不同内容返回版本冲突。
- v1 入队后能生成 v2；v2 入队后旧版本被标记 `superseded_at`。
- v2 审校失败后能生成 v3。
- stale feedback、错误 `question_id`、错误 `target_version` 被拒绝。
- exam-checker OpenAPI 不出现任何 `/revise`。
- PASS 入库严格绑定同一个 `task_id + question_id + version + review_id`。

### 7.2 Pi 工具与 Agent

- 网页端与 CLI 都能看到相同四个业务工具。
- `exam_checker` schema 中没有 `revise_question`。
- `question_generation` 包含 `author`、`replenishment` 和 `revise`。
- `NEEDS_REVISION` 后模型仍能看到完整 `review_id`、errors 和原命题题包。
- `REVISED` 不被工作流记为失败。
- Agent 可以自主产生以下可见工具轨迹：

  ```text
  question_generation(author)
  → exam_checker(review_question v1)
  → question_generation(revise v1→v2)
  → exam_checker(review_question v2)
  ```

- v3 仍失败时停止，不继续无界调用。
- `UNRESOLVED` 不得被描述为通过或入库。

### 7.3 全量回归命令

```bash
python -m unittest discover -s tests
python -m pytest pi-coding-agent/services/exam-checker/tests -q
python -m pytest pi-coding-agent/services/exam-assembly/tests -q
python -m unittest discover -s exam_assembly_agent -t .

cd pi-coding-agent
npm run check
npx vitest run packages/coding-agent/test/exam-checker-extension.test.ts
npx vitest run packages/coding-agent/test/suite/qodex-workflow.test.ts
npm --prefix apps/qodex-web run typecheck
npm --prefix apps/qodex-web run build
```

涉及真实模型的验收必须单独记录模型、请求、版本链和最终状态，不能用单元测试代替，也不能在未授权情况下消耗付费额度。

## 8. 完成定义

只有同时满足以下条件，才能把集成分支合入 main：

- 数据库接受所有现有命题模式；
- exam-checker 在 HTTP、Pi 工具和网页上都没有创建版本的入口；
- 命题端能根据真实 `review_id` 创建并入队下一版本；
- 工作流不会吞掉修订所需数据，不会把 `REVISED` 误判为失败；
- v1 → v2 → v3 的版本链和停止条件有自动化测试；
- PASS 题目能够进入题库并被组卷读取；
- 所有相关回归检查通过，已知跳过和限制写入 PR；
- README、AGENTS 和接口文档对版本所有权的描述一致。
