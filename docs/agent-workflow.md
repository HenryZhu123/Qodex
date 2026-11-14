# Agent 工作流：政策、护栏与模块接线

> 状态（2026-11-15）：**垂直切片已跑通并实测**。链路：待审题包 → 登记进审校 → 九类审校 → PASS 自动 annotate + 入库 → 从题库组卷 → 导出。
> 本文只写已验证的事实；未实现能力在文末「已知边界」单列。

## 1. 用户与需求

| 用户 | 需求 | 允许的动作序列 |
| --- | --- | --- |
| 命题老师 | 按章节/考点出题并进待审 | 取材 → 命题 → 登记 → 审校（PASS 才入库） |
| 组卷老师 | 出一份卷子 | 查题库 → 组卷 → 缺口补题 → 补的题再审校入库 → 重排一次 |
| 考生 | 练某个考点 | 命题 → 只交付 `student_view` + 讲解，不给评分点与错因表 |

## 2. 系统组成

```
Pi Agent（qodex-workflow 政策 + 护栏）
  ├── question_generation  → 8093 → PostgreSQL question_generation.pending_questions
  │        └── question_generation/handoff.py（题包 → QuestionView）
  ├── exam_checker          → 8091 → POST /v1/exam-checker/documents/import（新增接缝）
  │        └── review_question：九类专项 → annotate → ingest → question_bank
  ├── question_bank         → 8091 → 检索/精确取回（annotate 产出的难度与知识点）
  └── exam_assembly         → 8092 → 选题 → 导出学生卷 + 答案卷
```

新增的两处代码：

- `question_generation/handoff.py`：把待审题包投影成 13 字段的 `QuestionView`。只接受四选项单选；综合题明确拒绝（题库与组卷契约尚不支持）。
- `exam-checker` 的 `POST /v1/exam-checker/documents/import`：用与解析文档相同的结构（`ExamDocument` + 每题版本）登记作者题包，
  之后 `review_question` 走原有流程。重复 `document_id` 返回 409——文档存储会覆盖、版本存储会保留旧版本，静默重导会审到旧内容。

## 3. 政策（提示词，可被模型自行裁量）

写在 `qodex-workflow` 的 `before_agent_start`（**追加**到系统提示，不替换）：人物识别、候选动作、观察-响应、澄清、停止。

保留给模型的自由度：检索词自选、换词重试、改请求或拒绝并说明代价、只起草不入库、预算内提前收尾。
不给的自由度：判定 PASS、自造 `knowledge_points`、自定版本号、声称未发生的入库。

## 4. 护栏（代码，模型无法绕过）

| 护栏 | 行为 | 配置 |
| --- | --- | --- |
| 调用预算 | 超限 `tool_call` 直接 block，并给出"停止新调用 + 报告已完成部分"的理由 | `QODEX_MAX_GENERATION_CALLS`(6) / `QODEX_MAX_REVIEW_CALLS`(6) / `QODEX_MAX_ASSEMBLY_CALLS`(3) / `QODEX_MAX_WALL_CLOCK_MS`(45 min) |
| 重复付费 | 同 `(tool, 参数)` 摘要已成功执行 → block（失败不占用，允许重试） | — |
| 失败可见 | 服务返回 `status=SELF_CHECK_FAILED/UNRESOLVED/…` 或 `{error}` 时，`tool_result` 置 `isError=true` 并把结果压成 `{observation:{ok,status,code,retry,needs,next,detail,errors,artifact}}` | — |
| 入库措辞 | 拿不到 `ingestion.status=STORED` 时，助手若写"已入库/已通过"，`message_end` 追加一条纠正 | — |
| trace | 每次调用/结果/拦截写 `.local/qodex-traces/workflow-*.jsonl` | `QODEX_TRACE_DIR` |
| 政策开关 | `QODEX_WORKFLOW_POLICY=0/off/false` 关闭政策注入（护栏保留） | — |

`failure.code`（命题侧新增，追加字段，不破坏既有 `status/message`）：`candidate_shape`、`material_gap`、`design_invalid`、
`quality_gate`、`condition_test_incomplete`、`blind_disagreement`、`blind_incomplete`、`audit_rejected`，
每项带 `retry`（`same_request`/`new_request`/`no`）与 `needs`（`material`/`human`/null）。

## 5. 实测记录（2026-11-15）

环境：PostgreSQL 17（compose，端口 5433）+ 8091/8092 本机；审校与 annotate 用官方 `deepseek-flash`。

| 步 | 结果 |
| --- | --- |
| 历史待审题包（循环队列单选）→ `handoff` | 13 字段齐全，`reference=""`、`subject=数据结构`、`points=2` |
| `POST /documents/import` | `imported=1`，返回 `question_version_id` |
| 重复 import 同一 `document_id` | 409 |
| 无审校模型配置时 `review_question` | `UNRESOLVED`，9 项 `CONFIGURATION_ERROR`，`ingestion=null` |
| 配好模型后 `review_question` | **PASS**，9 项检查全部 `COMPLETED`（3 项走 JEV 路由），**10.6 s**，`ingestion.status=STORED` |
| annotate 产出 | `difficulty=medium`，`knowledge_points=[循环队列, 队空与队满判定, 入队与出队操作, 循环队列指针移动]` |
| 用这些标签组卷（1 题 2 分） | **STRUCTURAL_PASS**，学生卷与答案卷 HTML 落盘，答案键 D |

成本：本次只发生 1 次审校（9 专项 + 3 路由 + 1 annotate），无命题调用；服务端不回报账单，按峰值费率本地估算约 ¥0.1 量级，**属估算不是回执**。

## 6. 运行与验证

```bash
# 1) 数据库
bash pi-coding-agent/start-exam-checker-db.sh          # PG 5433 + alembic
docker exec -i qodex-exam-checker-postgres-1 psql -U qodex -d qodex < question_generation/sql/001_pending_questions.sql

# 2) 三个服务（各自终端）
cd pi-coding-agent/services/exam-checker && .venv/bin/python -m exam_checker     # 8091，需 EXAM_CHECKER_* 模型配置
QODEX_PYTHON=$PWD/pi-coding-agent/services/exam-checker/.venv/bin/python bash scripts/start-exam-assembly.sh  # 8092
bash scripts/start-question-generation.sh                                     # 8093，需 DEEPSEEK_* 与 KB 配置

# 3) 健检
curl -s localhost:8091/health && curl -s localhost:8092/health

# 4) 测试
python3 -m unittest discover -s tests                                   # 命题目录
cd pi-coding-agent/services/exam-checker && .venv/bin/python -m pytest    # 审校
cd pi-coding-agent/packages/coding-agent && node ../../node_modules/vitest/dist/cli.js --run test/suite/qodex-workflow.test.ts
```

## 7. 已知边界（不要当成已实现）

1. **组卷只支持四选项单选、同题型单一分值**；综合题不能入卷（契约在 `docs/ASSEMBLY_CONTRACT.zh-CN.md`，另组维护）。真实 408 需要 40×2 单选 + 41–47 共 70 分的综合题，且综合题分值是异质的（6–16 分/题），当前契约表达不了。
2. **题组**（如 2024 年 43/44 共用同一台机器 M）与**带图题**在全系统不存在对应实体，本切片不产出。
3. **审校看不到答案**：`CheckerPayload` 只有 `reference` + `detection_content`，答案/解析/评分不进审校。因此 `PASS` 不证明答案正确；答案正确性由命题侧盲解 + 审计与人工负责。
4. **难度与知识点由 annotate 决定**，属模型判断而非校准过的量表；组卷必须用 `question_bank search` 读真值，不能自造标签。
5. **一个 document 只能有一个 subject**（审校从 paper 读 subject），混科会被拒绝。
6. 金额没有代码强制上限，只有调用次数与墙钟；付费实验仍需事先授权与方案审校。
7. 题目与真题的贴合度（计算量、题型配比、超纲判定）**未做**，见 `TASK_STATE.md` 的问题 1 计划。
