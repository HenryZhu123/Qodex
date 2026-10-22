# AI 智能组卷：逐步开发

## 当前独立开发约定

按用户确认，先使用已筛选题的模拟题库独立开发，最终再与审校模块整合。
详见 LOCAL_BANK_CONTRACT.md。默认 examples/question_bank.json 含 20 道带答案和解析的开发题。
成功组卷会导出完整的 student_exam.html 和独立 answer_key.html，并保留 JSON 与报告。
HTML 可直接用浏览器查看/打印，不需要第三方依赖；PDF 是可选导出。

在 github-upload 仓库根目录执行：

```powershell
python exam_assembly_agent/main.py --output-dir exam_assembly_agent/outputs/complete_exam_1
```

需要 PDF 时，先安装 requirements-pdf.txt，再给同一命令加 --pdf（使用新输出目录）。
Pi 工具也会返回 HTML 路径，export_pdf=true 时另外生成 PDF。
学生卷不包含答案；report.json 是教师/调试文件，可能含答案，不发给学生。
尚未整合真实题库、语义冲突自动修复；不要把模拟 PASS 称为真实审校合格。

## 第一步：约定输入和输出

目标用户：需要按知识点和难度要求制作练习卷的教师。

开发样例：数据结构，10 道单选题，每题 2 分，共 20 分。
线性表、栈、队列、树、图各 2 题；简单 3 题、中等 5 题、困难 2 题。
难度按题数统计，不代表经过学生作答数据校准的真实难度。

本目录已实现需求检查、候选题筛选、缺口统计、联合配额选题和独立结构检查。
已增加相同题干检测及有预算的联合重选修复。
尚未接入真实审校、数据库、大模型或语义检查；这仍是完整 Agent 的开发阶段。

## 第二步：运行候选池检查

在仓库根目录执行（Python 3.10 或以上，无额外依赖）：

```powershell
python exam_assembly_agent/main.py
```

默认读取 10 题需求和 20 道开发样例题，返回 `STRUCTURAL_PASS`。
保留原始单题缺口演示：`python exam_assembly_agent/main.py --bank exam_assembly_agent/examples/question.json`。
`topic_deficits` 表示每类知识点缺几题；`difficulty_deficits` 表示每类难度缺几题。
二者是同一批缺题的不同维度，不应相加。

程序会排除科目、题型、分值不匹配，审校失败或版本失效的题目。
真实使用默认禁止模拟审校，示例需求通过 `allow_mock_reviews: true` 显式开启。
`READY_FOR_SELECTION` 只表示通过候选池数量检查，不代表最终试卷通过。
`max_repair_rounds` 控制修复上限（0 到 10，默认 3），0 表示只检查、不修复。

阅读顺序：

1. `examples/question.json`：题库中一道题的格式。
2. `examples/request.json`：用户的一份组卷要求。
3. `examples/expected_shortage.json`：只有这一道样例题时，应返回的缺题说明。

## 字段约定

- `question_id` 和 `version` 一起标识具体题目版本。
- `topic` 是第一版用于计数的唯一主知识点，避免一道题被重复算入多个配额。
- `review.question_version` 必须等于题目版本，状态为 `PASS` 才能入选。
- 样例中的 `is_mock: true` 表示审校结果是开发占位数据，未经过真实审校。
- `score_per_question` 由组卷要求指定，第一版要求与题库题目分值一致。
- 知识点和难度配额都是硬约束；不能满足就返回缺口，不能自行放宽。
- 最终试卷的学生版只包含题干和选项，答案和解析单独输出。

## 与队友的边界

- 审校模块提供具体题目版本的审校结果；题目内容修改后需要重新审校。
- 组卷模块负责检索、选题、整卷检查和有限次数换题。
- 缺题要求交给主 Agent，协调命题和审校；新题审校通过后才可继续选用。
- 后续接口需要区分 `PASS`、`NEEDS_QUESTIONS`、`INVALID_REQUEST`、`INCOMPLETE`。

## 下一步

准备覆盖这些要求的小题库，再实现读取文件、筛选题目、检查题量和总分。
随后加入约束选题、修复、语义检查、真实模块对接和评测。

## 第三步：联合选题和输出

```powershell
python exam_assembly_agent/main.py --output-dir exam_assembly_agent/outputs/my_first_exam
python -m unittest exam_assembly_agent.test_assembly -v
```

输出 `student_exam.json`（无答案）、`answer_key.json`（答案解析）和 `report.json`（完整开发报告，含答案，仅供教师/调试）。
输出目录请按运行区分，避免把旧试卷与本次失败报告混淆。

- `question_bank.py`：读取 JSON，后续增加数据库或 API 适配器。
- `assembly.py`：回溯搜索，同时扣减知识点和难度配额，不可行就回退；最多搜索 50000 个节点。
- `validate_selection`：独立复核题数、总分、配额、编号、题型和审校版本。
- `STRUCTURAL_PASS`：仅结构检查通过，不代表语义质量或真实审校合格。
- `NEEDS_QUESTIONS`：数量不足或联合配额无可行组合；后一种情况目前只解释冲突，尚不生成精确补题槽位。
- `INCOMPLETE`：搜索预算耗尽或复核失败，不能声称无解。

20 道题均为 AI 辅助编写的开发样例，模拟审校通过，难度未经人工校准。
固定题库顺序和搜索顺序保证本阶段结果可复现；后续评测需要独立数据与对照方法。

## 第四步：相同题干检测与修复

在仓库根目录运行，每条命令一次完整粘贴：

```powershell
python exam_assembly_agent/main.py --request exam_assembly_agent/examples/repair_request.json --bank exam_assembly_agent/examples/repair_bank.json --output-dir exam_assembly_agent/outputs/repair_success
python exam_assembly_agent/main.py --request exam_assembly_agent/examples/repair_request.json --bank exam_assembly_agent/examples/repair_no_alternative_bank.json --output-dir exam_assembly_agent/outputs/repair_failure
python -m unittest exam_assembly_agent.test_assembly exam_assembly_agent.test_checker_adapter exam_assembly_agent.test_repair -v
```

演示需求为 2 道简单栈题、每题 2 分。前三道候选中的前两道题干相同，第三道为替代题。

- 成功案例：初选 MOCK_STACK_1、MOCK_STACK_2，检测重复后联合重选为 MOCK_STACK_1、MOCK_STACK_3，重新验证全卷，返回 STRUCTURAL_PASS。
- 失败案例：只有前两道重复题；返回 NEEDS_QUESTIONS，report.json 保留冲突与失败原因，不产生最终学生卷/答案。
- repair_history 保存替换前后题号、冲突和搜索预算；initial_question_ids 保存初选结果。
- 联合重选允许多题一起替换，不保证最少替换数。每次搜索最多 50000 个节点，耗尽则返回 INCOMPLETE，不能宣称无解。
- 当前修复会把题干唯一性加入联合搜索，一次成功重选即可解决这类冲突；每次重选后仍重新检查整卷。
- 仅统一全半角与连续空白，不删除标点或数字。不检查改写后的语义重复、共享材料关系或跨题提示。
- 相同题干采用保守的整卷禁止策略，包括不同选项的相同题干。后续如需支持共享题干，必须增加题组结构。

这些运行只验证算法行为，样例审校状态仍为模拟，不是实际教学质量评测。

## 第五步：输出具体补题建议

```powershell
python exam_assembly_agent/main.py --request exam_assembly_agent/examples/repair_request.json --bank exam_assembly_agent/examples/repair_no_alternative_bank.json --output-dir exam_assembly_agent/outputs/replenishment_demo
```

修复搜索确认没有可行组合时，重复题案例会输出 `replenishment_request.json`，报告中也有同名字段。
包含 slots（知识点、难度、题型、每题分值及数量）、保留/替换题号、需要避开的题干和独立审校要求。
当前示例建议补 1 道简单栈单选题，每题 2 分。

这是固定保留方案下的可执行补题建议，不保证全局最小补题数。
尚未覆盖一般空库、知识点不足或非重复题联合配额冲突的精确补题计划；这些情况仍返回原有缺口报告。
不会自动调用外部模块。新题必须完成独立审校，再重新执行选题和全卷检查；未审校题不能直接入选。
修复次数为 0 或搜索预算耗尽时，不会假定题库无解并发出此补题请求。

## 第六步：补题后恢复组卷的离线演示

```powershell
python -m exam_assembly_agent.demo_replenishment --output-dir exam_assembly_agent/outputs/resume_demo
```

输出目录必须为空或不存在；重复演示请换目录名，例如 resume_demo_2。
运行 summary.json 中的 passed 应为 true，各阶段的输入和报告均保存，便于独立重跑：

1. `01_initial`：两题题干相同，无替代题，输出补题建议。
2. `02_pending_review`：添加固定新题但尚未审校，新题被排除，不输出最终试卷。
3. `03_mock_review_passed`：使用独立构造的模拟审校通过记录，重新组卷并复核全部结构约束，输出学生卷和答案。
4. `04_stale_review`：模拟题目更新到版本 2，但审校仍针对版本 1，新题再次被排除。

演示直接使用固定开发题模拟补题，没有自动调用命题或审校，也未验证真实服务。
这是普通函数组合的演示，不是持久化会话恢复或自动编排服务。

## 第七步：修改需求后重新组卷

```powershell
python -m exam_assembly_agent.demo_changes --output-dir exam_assembly_agent/outputs/changes_demo_2
```

输出目录必须为空或不存在。查看 summary.json，passed 应为 true：

1. `01_initial`：10 题、20 分，STRUCTURAL_PASS。
2. `02_changed_valid`：15 题、30 分，五类知识点各 3 题，难度 5/7/3，STRUCTURAL_PASS。
3. `03_conflicting_request`：保留 15 题、每题 2 分，却改为总分 20，INVALID_REQUEST。
4. `04_candidate_shortage`：调整为 10 道困难题，候选只有 5 道困难题，NEEDS_QUESTIONS。

每阶段保存 request.json、report.json 和 revision.json；仅成功阶段输出学生卷及答案。
history.json 保存全部历史，revision 从 1 递增，base_revision 指向修改依据。
新要求提交后，旧卷仅作为历史，不在本次失败时回退使用；旧文件不会删除，需按最新 revision 判断。
RequestSession.submit 支持结构化 changes；修改知识点或难度字典时需完整提供该字段，不自动补配额。
旧 base_revision 会在执行前被拒绝，防止误用过期要求。非法业务要求仍保留为一次尝试，可基于该版本修正。
会话当前保存在内存，导出文件仅作追溯，不支持服务重启后自动恢复；尚未实现自然语言修改、界面或数据库会话。

完整测试：

```powershell
python -m unittest discover -s exam_assembly_agent -t . -p "test_*.py" -v
```

## 第八步：语义重复人工复核入口

```powershell
python -m exam_assembly_agent.semantic_review --input exam_assembly_agent/examples/semantic_pairs.json --output-dir exam_assembly_agent/outputs/semantic_demo
```

本例 3 道题，输出全部 3 个题目对，初始状态 NEEDS_REVIEW。
review_packet.json 包含题目、答案、判断准则及文字相似度排序；仅供教师复核。
decisions_template.json 供人工填写 verdict、reviewer 和 reason；保留 pair_id 及 content_hashes 不变。
verdict 可为 DUPLICATE、DISTINCT 或 UNRESOLVED。
examples/semantic_pairs_labels.md 是 AI 辅助的开发标签草案，不是已经完成的人工复核，也不作为自动判定输入。

完成真实人工复核后运行（输出使用新目录）：

```powershell
python -m exam_assembly_agent.semantic_review --input exam_assembly_agent/examples/semantic_pairs.json --decisions exam_assembly_agent/outputs/semantic_demo/decisions_template.json --output-dir exam_assembly_agent/outputs/semantic_reviewed
```

- DUPLICATES_FOUND：至少存在一对人工确认的语义重复，仍需查看是否有其他未复核题对。
- NEEDS_REVIEW：仍有未确认、无法判断、内容已变更或无效结论。
- SEMANTIC_REVIEW_PASS：全部题对均有有效的 DISTINCT 人工结论；不代表跨题提示检查或单题质量通过。

这只是人工复核工具，未接入模型、embedding 或语义冲突自动修复，也未改变 main.py 的 STRUCTURAL_PASS 含义。
全量题对为 O(n²)，当前面向小卷；文字相似度仅排序，不声称检测召回率或语义判断准确率。
未来先完成独立人工标签，再比较模型判断，并将确认冲突接入组卷修复。

## Git 提交范围

阶段功能和测试通过后即可提交到个人分支，不必等真实数据库对接。
提交源代码、示例输入、提示词、测试和文档；模块 .gitignore 已排除 outputs、Python 缓存及 .env。
运行产物只放 outputs；最终评测时再挑选、脱敏并明确保存必要的结果和轨迹。
先检查暂存区已有变更，只提交本模块，避免混入其他模块的删除或凭据。

```powershell
python -m unittest exam_assembly_agent.test_assembly exam_assembly_agent.test_checker_adapter exam_assembly_agent.test_repair exam_assembly_agent.test_missing_slots -v
```
