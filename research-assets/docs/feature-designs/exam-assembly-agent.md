AI 组卷 Agent 技术设计

# 1. 背景与目标

在 AI 辅助考试系统中，单题质量高并不自动意味着整张试卷质量高。即使每一道题都已经通过单题级审校，最终组装出的试卷仍然可能出现总分错误、难度失衡、知识点缺失、题目重复、跨题答案泄露等问题。

因此，本文设计一个 **Exam Assembly Agent（组卷 Agent）**，用于从已审校题库中自动生成试卷。该 Agent 负责选择合适题目、组装试卷结构、进行整卷级验证、分析失败原因，并通过替换题目完成自动修复。

本设计明确区分两类质量控制：

- **Question Review Agent（单题审校 Agent）**：负责题目进入题库前或题库中的单题质量审校。
- **Exam-Level Validator（整卷级验证器）**：负责组卷完成后的整张试卷质量与约束检查。

组卷 Agent 不会在组卷后再次调用团队同学负责的 Question Review Agent 来做单题审校。相反，它会在检索阶段使用题库中保存的单题审校结果作为 metadata，并在组卷完成后运行独立的整卷级验证。

核心目标包括：

- 根据教师或用户要求生成满足科目、知识点、题型、总分、考试时长和难度要求的试卷。
- 原则上只从已经通过单题审校的可信题库中选择题目。
- 保证最终试卷同时满足硬性约束和教学质量要求。
- 发现单题级审校无法发现的整卷级问题。
- 当候选试卷验证失败时，支持自动分析原因并替换题目完成修复。

# 2. 系统架构

### 2.1 整体流程

整体流程如下：

```text
                 AI 自主命题 / 人工录入题目
                              |
                              v
                    Question Review Agent
                     （单题级质量审校）
                              |
                              v
                         已审校题库
              保存 review_status / review_confidence
                              |
                              v
                    Exam Assembly Agent
              原则上只检索 review_status = PASS 的题目
                              |
                              v
                         候选试卷
                              |
                              v
                    Exam-Level Validator
                  （整卷级质量与约束验证）
                       |                 |
                       v                 v
                     PASS               FAIL
                       |                 |
                       v                 v
                    最终试卷        Failure Analysis
                                         |
                                         v
                                   Repair Action
                                         |
                                         v
                                     替换题目
                                         |
                                         v
                                重新进行整卷验证
```

### 2.2 模块职责

系统包含以下核心模块：

| 模块 | 职责 |
|---|---|
| Question Review Agent | 在题目被组卷系统使用前，负责单题质量审校。 |
| Reviewed Question Bank | 存储题目、答案、metadata、审校状态、审校置信度、难度、知识点和使用历史。 |
| Requirement Parser | 将教师或用户需求解析为结构化组卷约束。 |
| Candidate Retriever | 从已审校题库中检索符合条件的候选题目。 |
| Exam Planner | 生成试卷蓝图，包括 Section、题型、分值和目标难度分布。 |
| Exam Assembler | 根据试卷蓝图选择题目并组装候选试卷。 |
| Exam-Level Validator | 验证整张试卷，而不是重新检查单题本身是否正确。 |
| Failure Analyzer | 分析哪些约束或哪些题目导致整卷验证失败。 |
| Repair Executor | 替换问题题目，并重新生成受影响的试卷部分。 |

### 2.3 题库 Metadata

题库应将 Question Review Agent 的审校结果保存为结构化 metadata。只有当题目的审校状态和审校置信度满足组卷策略时，该题才可作为可靠候选题。

示例题目 metadata：

```json
{
  "question_id": "Q102",
  "question_type": "single_choice",
  "subject": "Database Systems",
  "knowledge_points": ["normalization", "functional dependency"],
  "difficulty": "medium",
  "score": 5,
  "estimated_time_minutes": 3,
  "review_status": "PASS",
  "review_confidence": 0.96,
  "usage_count": 2,
  "last_used_exam_id": "EXAM_2026_MIDTERM"
}
```

Exam Assembly Agent 原则上只检索满足以下条件的题目：

```text
review_status = PASS
review_confidence >= configured_threshold
```

对于 `review_status = FAIL`、`PENDING` 或 `NEEDS_REVISION` 的题目，默认不应进入自动组卷流程，除非管理员显式覆盖该策略。

### 2.4 组卷规划

Exam Planner 将用户需求转换为试卷蓝图。试卷蓝图在真正选题前定义整张试卷的结构。

示例蓝图：

```json
{
  "exam_title": "Database Systems Midterm Exam",
  "total_score": 100,
  "duration_minutes": 120,
  "sections": [
    {
      "section_id": "A",
      "title": "Multiple Choice",
      "question_type": "single_choice",
      "question_count": 20,
      "score_per_question": 2,
      "section_score": 40
    },
    {
      "section_id": "B",
      "title": "Short Answer",
      "question_type": "short_answer",
      "question_count": 4,
      "score_per_question": 10,
      "section_score": 40
    },
    {
      "section_id": "C",
      "title": "SQL Design",
      "question_type": "programming",
      "question_count": 2,
      "score_per_question": 10,
      "section_score": 20
    }
  ],
  "difficulty_distribution": {
    "easy": 0.3,
    "medium": 0.5,
    "hard": 0.2
  },
  "required_knowledge_points": [
    "relational model",
    "SQL",
    "normalization",
    "transaction"
  ]
}
```

### 2.5 已审校题目检索

试卷蓝图生成后，Candidate Retriever 会从已审校题库中检索可用题目。此阶段会使用 Question Review Agent 已经写入题库的审校结果作为筛选 metadata。

检索策略应包括：

- 只选择 `review_status = PASS` 的题目。
- 优先选择 `review_confidence` 较高的题目。
- 匹配科目、知识点、题型、分值和难度要求。
- 根据使用历史避免过度重复使用同一批题目。
- 排除近期在同一课程或同一考试系列中使用过的题目。
- 为每个 Section 检索备选候选题，以支持后续修复。

这一设计实现了 Exam Assembly Agent 与 Question Review Agent 的衔接，但不混淆两者职责。Question Review Agent 判断一道题本身是否合格；Exam Assembly Agent 判断一组已经合格的题组合起来是否能构成一张好试卷。

### 2.6 独立整卷级验证

候选试卷生成后，系统运行独立的 **Exam-Level Validator**。该验证器检查整张试卷的质量和约束，包括只有多道题组合在一起后才会出现的问题。

Exam-Level Validator 应检查：

- 总分是否正确。
- 各 Section 分值是否正确。
- 题型和题目数量是否正确。
- 难度分布是否符合要求。
- 必要知识点是否被覆盖。
- 是否存在重复题或高度相似题。
- 知识点是否过度集中。
- 是否存在跨题答案泄露或相互提示。
- 整卷结构质量是否合理。
- 最终试卷是否符合用户原始需求。

整卷级问题示例：

```text
问题 1：Q3 和 Q8 考查同一知识点，且题干表达高度相似。
类型：重复或高度相似题

问题 2：Q5 的题干信息直接暴露了 Q12 的答案。
类型：跨题答案泄露

问题 3：70% 的分值集中在 SQL joins，但要求覆盖的 normalization 没有出现。
类型：知识点分布失衡
```

这些问题无法通过孤立地审查单题来可靠发现，必须由能够看到整张候选试卷的整卷级验证器完成。

# 3. 输入输出协议

### 3.1 输入格式

Exam Assembly Agent 接收结构化或半结构化的组卷需求。

示例输入：

```json
{
  "request_id": "REQ_2026_001",
  "course": "Database Systems",
  "exam_type": "midterm",
  "total_score": 100,
  "duration_minutes": 120,
  "language": "English",
  "sections": [
    {
      "question_type": "single_choice",
      "question_count": 20,
      "score_per_question": 2
    },
    {
      "question_type": "short_answer",
      "question_count": 4,
      "score_per_question": 10
    },
    {
      "question_type": "programming",
      "question_count": 2,
      "score_per_question": 10
    }
  ],
  "difficulty_distribution": {
    "easy": 0.3,
    "medium": 0.5,
    "hard": 0.2
  },
  "knowledge_point_requirements": {
    "must_cover": ["SQL", "normalization", "transaction"],
    "avoid_over_concentration": true
  },
  "retrieval_policy": {
    "required_review_status": "PASS",
    "min_review_confidence": 0.8,
    "exclude_recently_used": true
  }
}
```

### 3.2 中间输出：候选试卷

候选试卷包含已选题目和组卷 metadata。

```json
{
  "candidate_exam_id": "CAND_EXAM_001",
  "request_id": "REQ_2026_001",
  "status": "CANDIDATE",
  "total_score": 100,
  "sections": [
    {
      "section_id": "A",
      "title": "Multiple Choice",
      "section_score": 40,
      "questions": ["Q101", "Q102", "Q103"]
    }
  ],
  "assembly_metadata": {
    "selected_question_count": 26,
    "review_policy": "PASS_ONLY",
    "min_review_confidence": 0.8,
    "retrieval_round": 1
  }
}
```

### 3.3 验证输出

Exam-Level Validator 返回结构化验证结果。

```json
{
  "candidate_exam_id": "CAND_EXAM_001",
  "validation_status": "FAIL",
  "overall_score": 0.76,
  "passed_checks": [
    "total_score",
    "section_score",
    "question_count"
  ],
  "failed_checks": [
    {
      "check_type": "knowledge_point_coverage",
      "severity": "HIGH",
      "message": "The exam does not cover transaction isolation, which is required.",
      "affected_questions": []
    },
    {
      "check_type": "cross_question_leakage",
      "severity": "HIGH",
      "message": "Q5 gives information that reveals the answer to Q12.",
      "affected_questions": ["Q5", "Q12"]
    }
  ],
  "repair_required": true
}
```

### 3.4 修复输出

当整卷验证失败时，Failure Analyzer 和 Repair Executor 会生成修复计划。

```json
{
  "candidate_exam_id": "CAND_EXAM_001",
  "repair_round": 1,
  "failure_analysis": [
    {
      "failure_type": "cross_question_leakage",
      "root_cause": "Q5 contains a clue that reveals Q12.",
      "recommended_action": "replace_question",
      "target_question": "Q12"
    },
    {
      "failure_type": "missing_knowledge_point",
      "root_cause": "No selected question covers transaction isolation.",
      "recommended_action": "add_or_replace_question",
      "target_knowledge_point": "transaction isolation"
    }
  ],
  "repair_actions": [
    {
      "action": "replace_question",
      "old_question_id": "Q12",
      "new_question_constraints": {
        "knowledge_point": "transaction isolation",
        "difficulty": "medium",
        "question_type": "short_answer",
        "review_status": "PASS"
      }
    }
  ],
  "next_step": "REVALIDATE_WHOLE_EXAM"
}
```

### 3.5 最终输出

只有当候选试卷通过整卷级验证后，系统才输出最终试卷。

```json
{
  "exam_id": "EXAM_2026_001",
  "status": "PASS",
  "total_score": 100,
  "duration_minutes": 120,
  "sections": [
    {
      "section_id": "A",
      "title": "Multiple Choice",
      "questions": [
        {
          "question_id": "Q101",
          "score": 2
        }
      ]
    }
  ],
  "validation_summary": {
    "total_score_check": "PASS",
    "section_score_check": "PASS",
    "difficulty_distribution_check": "PASS",
    "knowledge_coverage_check": "PASS",
    "similarity_check": "PASS",
    "cross_question_leakage_check": "PASS"
  }
}
```

# 4. 评测指标

Exam Assembly Agent 应从约束满足程度和试卷质量两个层面进行评估。

### 4.1 约束满足指标

| 指标 | 描述 |
|---|---|
| 总分准确率 | 最终试卷总分是否等于要求总分。 |
| Section 分值准确率 | 每个 Section 的分值是否符合试卷蓝图。 |
| 题目数量准确率 | 每种题型的题目数量是否符合要求。 |
| 题型准确率 | 所选题目是否匹配要求题型。 |
| 审校合格题占比 | 所选题目中 `review_status = PASS` 的比例。 |
| 审校置信度合规率 | 所选题目中达到最低 `review_confidence` 阈值的比例。 |

### 4.2 分布与覆盖指标

| 指标 | 描述 |
|---|---|
| 难度分布误差 | 目标难度分布与实际难度分布之间的差异。 |
| 知识点覆盖率 | 最终试卷覆盖了多少必需知识点。 |
| 知识点均衡度 | 衡量分值是否过度集中在少数知识点上。 |
| Section 多样性得分 | 衡量每个 Section 内部题目是否具有合理变化。 |

### 4.3 整卷级质量指标

| 指标 | 描述 |
|---|---|
| 重复题比例 | 被选题目中重复或高度相似题目的比例。 |
| 跨题答案泄露率 | 题目之间出现答案泄露或相互提示的频率。 |
| 整卷连贯性得分 | 衡量试卷结构是否连贯，并与考试类型匹配。 |
| 修复成功率 | 验证失败的候选试卷中，被自动修复成功的比例。 |
| 平均修复轮数 | 候选试卷通过验证前平均需要多少轮修复。 |

### 4.4 人工评估指标

教师或人工评审可以评估：

- 最终试卷是否适合课程水平。
- 难度递进是否合理。
- 知识点覆盖是否符合教学目标。
- 试卷是否显得重复或失衡。
- 自动修复后的试卷是否无需大量人工修改即可接受。

# 5. Challenges & Solutions

### 5.1 Challenge：混淆单题级审校与整卷级验证

如果系统设计没有清晰区分这两个层级，组卷后的质量控制可能看起来像是在重复 Question Review Agent 的工作。

Solution：

- 将单题审校结果作为 metadata 存入题库。
- 在检索阶段使用 `review_status = PASS` 和 `review_confidence`。
- 让 Exam-Level Validator 只关注整卷级约束和多题之间的相互影响。
- 明确划分“单题质量”和“整卷质量”的职责边界。

### 5.2 Challenge：可用合格题目不足

系统可能无法找到足够多同时满足所有约束的已审校题目。

Solution：

- 为每个 Section 检索备选候选题。
- 按可控顺序放宽软约束，例如先放宽难度偏好，而不是放宽必需知识点。
- 当硬约束无法满足时，返回结构化失败信息。
- 建议针对缺失知识点生成或审校更多题目。

### 5.3 Challenge：难度分布难以精确控制

题目难度标签可能存在噪声或不一致。

Solution：

- 结合人工标签、历史作答数据和模型估计难度。
- 使用容忍区间，而不是要求完全精确的比例。
- 在整卷级别验证最终难度分布。
- 在考试使用后，根据学生表现数据更新难度 metadata。

### 5.4 Challenge：检测相似或重复题目

即使题目表述不同，也可能在语义上高度相似。

Solution：

- 使用 embedding similarity 检测语义重叠。
- 比较知识点、解题路径、答案模式和核心概念。
- 对同一 Section 内的相似度设置更严格阈值。
- 在修复阶段替换冲突题目中的一题。

### 5.5 Challenge：跨题答案泄露

一道题可能通过题干、选项、背景材料或上下文泄露另一道题的答案。

Solution：

- 在组卷后进行 pairwise 或 group-level leakage checks。
- 使用 LLM-based validator 判断题目之间是否存在直接或间接提示。
- 优先替换更容易替换、且不会破坏其他约束的题目。
- 每次修复后重新进行完整的整卷级验证。

### 5.6 Challenge：修复可能破坏其他约束

替换一道题可能解决一个问题，但带来新的问题，例如分值不匹配、难度失衡或知识点缺失。

Solution：

- 将修复视为迭代循环。
- 每次修复后运行完整的 Exam-Level Validator。
- 设置最大修复轮数。
- 维护具备相同分值、题型、难度和知识点 metadata 的候选题池。

### 5.7 Challenge：整卷交叉比对成本较高

在整卷级验证中，重复题检测、相似题检测、跨题答案泄露和相互提示都可能需要对题目进行交叉比对。如果对一套试卷中的所有题目都进行两两 LLM 检查，时间复杂度接近 `O(n²)`。当题目数量较多时，这会带来明显的延迟和计算成本。

Solution：

- 使用 embedding similarity 先进行快速粗筛，只保留语义相似度较高的题目对。
- 按知识点、题型、Section、材料来源等 metadata 对题目分组，只在高相关分组内做交叉比对。
- 对明显无关的题目对直接跳过，例如知识点完全不同且语义相似度很低的题目。
- 采用两阶段验证：第一阶段使用规则和 embedding 快速过滤，第二阶段只对高风险题对调用 LLM-based validator。
- 对题库中的题目预先计算 embedding，并缓存题目之间的相似度结果，避免每次组卷重复计算。
- 对跨题答案泄露检查设置优先级，例如优先检查同知识点、同 Section、共享材料、题干包含定义、公式或答案线索的题目。
- 对大型试卷支持并行验证，将高风险题对分批并发处理。

# 6. 实现计划与代码结构

### 6.1 推荐技术方案

系统可以实现为模块化后端服务，结合确定性的约束检查和 LLM 辅助的语义验证。

推荐组件：

- **关系型数据库或文档数据库**：存储题目和 metadata。
- **向量数据库或 embedding index**：用于语义相似度搜索和重复题检测。
- **规则型验证器**：检查总分、Section 分值、题目数量、题型等硬约束。
- **LLM-based validator**：检查跨题答案泄露、相互提示和整卷结构质量。
- **分层交叉比对机制**：先用 metadata 和 embedding 进行低成本筛选，再对高风险题对调用 LLM-based validator，从而降低整卷验证延迟。
- **Repair policy engine**：根据验证失败结果选择替换策略。
- **日志与追踪系统**：记录检索、验证、失败分析和修复决策。

建议验证结构：

```text
Hard Constraint Checks
    total score
    section score
    question count
    question type
    review eligibility

Distribution Checks
    difficulty distribution
    knowledge point coverage
    knowledge point balance

Semantic Exam-Level Checks
    duplicate / highly similar questions
    cross-question leakage
    mutual hints
    whole-exam structure quality
```

### 6.2 建议代码目录

```text
exam_assembly_agent/
├── README.md
├── config/
│   ├── assembly_policy.yaml
│   └── validation_policy.yaml
├── data/
│   ├── question_schema.json
│   └── exam_schema.json
├── src/
│   ├── main.py
│   ├── requirement_parser.py
│   ├── exam_planner.py
│   ├── candidate_retriever.py
│   ├── exam_assembler.py
│   ├── validators/
│   │   ├── __init__.py
│   │   ├── hard_constraint_validator.py
│   │   ├── distribution_validator.py
│   │   ├── similarity_validator.py
│   │   ├── leakage_validator.py
│   │   └── exam_level_validator.py
│   ├── repair/
│   │   ├── __init__.py
│   │   ├── failure_analyzer.py
│   │   ├── repair_policy.py
│   │   └── repair_executor.py
│   ├── storage/
│   │   ├── question_bank.py
│   │   ├── metadata_repository.py
│   │   └── vector_index.py
│   └── schemas/
│       ├── question.py
│       ├── exam_request.py
│       ├── candidate_exam.py
│       ├── validation_result.py
│       └── repair_action.py
├── tests/
│   ├── test_requirement_parser.py
│   ├── test_candidate_retriever.py
│   ├── test_exam_assembler.py
│   ├── test_exam_level_validator.py
│   ├── test_failure_analyzer.py
│   └── test_repair_executor.py
└── docs/
    ├── input_output_protocol.md
    ├── validation_rules.md
    └── repair_strategy.md
```

### 6.3 核心伪代码

```python
def assemble_exam(request):
    blueprint = exam_planner.create_blueprint(request)

    candidate_pool = candidate_retriever.retrieve(
        blueprint=blueprint,
        review_status="PASS",
        min_review_confidence=request.retrieval_policy.min_review_confidence
    )

    candidate_exam = exam_assembler.assemble(
        blueprint=blueprint,
        candidate_pool=candidate_pool
    )

    for repair_round in range(MAX_REPAIR_ROUNDS + 1):
        validation_result = exam_level_validator.validate(candidate_exam, request)

        if validation_result.validation_status == "PASS":
            return finalize_exam(candidate_exam, validation_result)

        failure_report = failure_analyzer.analyze(
            candidate_exam=candidate_exam,
            validation_result=validation_result
        )

        repair_actions = repair_policy.plan(
            failure_report=failure_report,
            blueprint=blueprint,
            candidate_pool=candidate_pool
        )

        candidate_exam = repair_executor.apply(
            candidate_exam=candidate_exam,
            repair_actions=repair_actions,
            candidate_pool=candidate_pool
        )

    return build_failure_response(candidate_exam, validation_result)
```

### 6.4 开发里程碑

| 里程碑 | 目标 |
|---|---|
| M1 | 定义 question、exam request、candidate exam、validation result 和 repair action schema。 |
| M2 | 基于 `review_status` 和 metadata 约束实现已审校题目检索。 |
| M3 | 实现试卷蓝图生成和候选试卷组装。 |
| M4 | 实现硬约束验证器和分布验证器。 |
| M5 | 实现相似题检测和跨题答案泄露检测。 |
| M6 | 实现 Failure Analysis -> Repair Action -> 替换题目 -> 重新整卷验证闭环。 |
| M7 | 添加评测脚本和人工评审界面，用于评估最终试卷质量。 |

### 6.5 预期贡献

本设计的主要贡献不是简单地从题库中选题，而是引入一个完整的 Agentic Loop：

```text
Plan -> Retrieve Reviewed Questions -> Assemble -> Validate Whole Exam -> Diagnose -> Repair -> Revalidate
```

该流程使系统生成的试卷不仅由单题质量合格的题目组成，而且作为整张试卷也具备结构合理、分布均衡、约束合规和教学可用的特点。
