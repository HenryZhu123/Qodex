# Agent 工作流：政策、护栏与模块接线

> 状态（2026-11-15，合并 `origin/main` 后）：链路是 `命题(8093, task_id) → 审校(8091, /tasks/.../review) → PASS 自动 annotate + 入库 → 组卷(8092) → 导出`，
> 由 Pi 的 `qodex-workflow` 扩展承担政策与代码护栏。本文只写已验证事实；未实现能力见文末「已知边界」。

## 1. 用户与需求

| 用户 | 需求 | 允许的动作序列 |
| --- | --- | --- |
| 命题老师 | 按章节/考点出题并进待审 | 取材 → 命题 → 审校（PASS 才入库） |
| 组卷老师 | 出一份卷子 | 查题库 → 组卷 → 缺口补题 → 补的题再审校入库 → 重排一次 |
| 考生 | 练某个考点 | 命题 → 只交付 `student_view` + 讲解，不给评分点与错因表 |

## 2. 身份与接线

命题与审校用 `task_id + question_id + version` 对齐（详见 `docs/QUESTION_GENERATION_REVIEW_INTEGRATION.zh-CN.md`）：

```text
Pi Agent（qodex-workflow）
  ├── question_generation → 8093 → generation_tasks + pending_questions（每题带 task_id）
  ├── exam_checker
  │     review_question(task_id, question_id, version)
  │       → 8091 从待审表导入不可变快照 question_snapshots
  │       → 九类专项检查 → PASS 时 annotate（难度/知识点）→ 幂等写入 question_bank
  └── exam_assembly → 8092 → 选题 + 导出学生卷/答案卷（组卷历史写 PostgreSQL）
```

**接入是 Pi 显式调用两个工具完成的，不是数据库后台自动消费。**

> 上一版曾新增 `POST /v1/exam-checker/documents/import` + `question_generation/handoff.py` 作为"作者题包 → 审校"的接缝。
> 合并 `origin/main` 后该路径与新身份模型（`question_snapshots`，主键含 `task_id`）重复且不兼容，已删除；
> 现在只有一条登记机制，避免两套版本语义并存。

## 3. 政策（提示词，可被模型自行裁量）

写在 `qodex-workflow` 的 `before_agent_start`（**追加**到系统提示，不替换）：人物识别、候选动作、观察-响应、澄清、停止。

保留给模型的自由度：检索词自选、换词重试、改请求或拒绝并说明代价、只起草不入库、预算内提前收尾。
不给的自由度：判定 PASS、自造 `knowledge_points` / `task_id` / 版本号、声称未发生的入库。

## 4. 护栏（代码，模型无法绕过）

| 护栏 | 行为 | 配置 |
| --- | --- | --- |
| 调用预算 | 超限 `tool_call` 直接 block，并给出"停止新调用 + 报告已完成部分" | `QODEX_MAX_GENERATION_CALLS`(6) / `QODEX_MAX_REVIEW_CALLS`(6) / `QODEX_MAX_ASSEMBLY_CALLS`(3) / `QODEX_MAX_WALL_CLOCK_MS`(45 min) |
| 重复付费 | 同 `(tool, 参数)` 摘要已成功执行 → block（失败不占用，允许重试） | — |
| 失败可见 | 服务返回 `status=SELF_CHECK_FAILED/UNRESOLVED/…` 或 `{error}` 时置 `isError=true`，把结果压成 `{observation:{ok,status,code,retry,needs,next,detail,errors,artifact}}` | — |
| 入库措辞 | 拿不到 `ingestion.status=STORED` 时，助手若写"已入库/已通过"，`message_end` 追加纠正 | — |
| trace | 每次调用/结果/拦截写 `.local/qodex-traces/workflow-*.jsonl` | `QODEX_TRACE_DIR` |
| 政策开关 | `QODEX_WORKFLOW_POLICY=0/off/false` 关闭政策注入（护栏保留） | — |

命题侧新增 `failure.code`（追加字段，不改 `status/message`）：`candidate_shape`、`material_gap`、`design_invalid`、
`quality_gate`、`condition_test_incomplete`、`blind_disagreement`、`blind_incomplete`、`audit_rejected`，
每项带 `retry`（`same_request`/`new_request`/`no`）与 `needs`（`material`/`human`/null）。

## 5. 运行与验证

```bash
# 数据库（PG 5433 + 命题侧表）
bash pi-coding-agent/start-exam-checker-db.sh
docker exec -i qodex-exam-checker-postgres-1 psql -U qodex -d qodex < question_generation/sql/001_pending_questions.sql
docker exec -i qodex-exam-checker-postgres-1 psql -U qodex -d qodex < question_generation/sql/002_generation_tasks.sql

# 服务：8091（审校，需 EXAM_CHECKER_* 模型配置）、8092（组卷）、8093（命题，需 DEEPSEEK_* 与 KB）
cd pi-coding-agent/services/exam-checker && .venv/bin/python -m exam_checker
QODEX_PYTHON=$PWD/pi-coding-agent/services/exam-checker/.venv/bin/python bash scripts/start-exam-assembly.sh
bash scripts/start-question-generation.sh

# 测试
python3 -m unittest discover -s tests
cd pi-coding-agent/services/exam-checker && .venv/bin/python -m pytest
cd pi-coding-agent/packages/coding-agent && node ../../node_modules/vitest/dist/cli.js --run test/suite/qodex-workflow.test.ts
```

## 6. 已知边界（不要当成已实现）

1. **组卷只支持四选项单选、同题型单一分值**；综合题不能入卷。真实 408 需要 40×2 单选 + 41–47 共 70 分综合题，
   且综合题分值异质（6–16 分/题），当前契约表达不了。
2. **题组**（2024 年 43/44 共用同一台机器 M）与**带图题**在全系统没有对应实体。
3. **审校看不到答案**：`CheckerPayload` 只有 `reference` + `detection_content`，答案/解析/评分不进审校，
   因此 `PASS` 不证明答案正确；答案正确性由命题侧盲解 + 审计与人工负责。
4. 难度与知识点由 annotate 决定，属模型判断而非校准量表；组卷必须用 `question_bank search` 读真值。
5. 金额没有代码强制上限，只有调用次数与墙钟；付费实验仍需事先授权 + 子 agent 审方案。
6. 题目与真题的贴合度（计算量、题型配比、超纲判定）**未做**，见 `TASK_STATE.md` 问题 1。
