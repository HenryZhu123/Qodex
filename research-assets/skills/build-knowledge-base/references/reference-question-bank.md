# 参考题库（Reference Question Bank）

把 408 真题试卷与答案整理成结构化的参考题记录，供知识库在**生成**场景提供示例、在**审校**场景提供同题比对依据。

对应 Proposal §3.4：参考题与学科证据分离，参考题只作示例，不作学科事实依据。

## 数据来源

```text
research-assets/408exam/真题/
├── 01_重排版试卷_2009-2026/<year>.pdf      试卷（可选文字层）
├── 02_参考答案_2009-2026/<year>-answer.pdf  答案（部分为扫描件）
└── manual_answers.json                      人工核对的答案覆盖
```

## 构建

```bash
cd research-assets/skills/build-knowledge-base

# 1. 解析试卷与答案
python scripts/refq/parse_408.py \
  --exam-root ../../408exam/真题 \
  --out <output-dir>

# 2. 入库 SQLite + 导出 JSONL
python scripts/refq/ingest_refq.py \
  --records <output-dir>/reference_questions.jsonl \
  --db <output-dir>/refq.sqlite \
  --out <output-dir>
```

`parse_408.py` 会额外写出 `manual_answers.template.json`，列出自动解析失败、需要人工补录的题号。

## 手工答案覆盖

`manual_answers.json` 的优先级最高：命中即覆盖自动解析结果。

```json
{
  "2013": { "1": "D", "2": "C", "3": "D", "4": "B", "5": "A" }
}
```

已核对年份：2009、2013、2014、2015、2016、2017、2019、2021、2024、2025、2026（各 40 题，共 440 个答案）。

- 2009/2013/2014/2015/2016/2017：答案表格在 PDF 中有文字层但排布混乱，逐年读图逐题核对后写入。
- 2019/2021/2024/2025/2026：答案为纯扫描件，用 MinerU 识别后再人工核对。

## 扫描件 OCR（MinerU）

扫描年份使用 MinerU Agent API（免 token，按 IP 限流），脚本：

```bash
python scripts/refq/mineru_answers.py \
  --answer-pdf ../../408exam/真题/02_参考答案_2009-2026/2019-answer.pdf \
  --year 2019 \
  --out <output-dir>
```

批量执行：

```bash
python scripts/refq/run_mineru_batch.py
```

MinerU 会把答案表还原成 HTML `<table>`，脚本按 `题号 → 字母` 配对解析，比整页 OCR 稳定得多。

实测对比（2019 年）：

| 方案 | 识别数 |
|---|---:|
| Tesseract 5.4 + chi_sim | 29/40，字母噪声严重 |
| **MinerU Agent API** | **39/40**，仅 1 个单元格缺失 |

5 个扫描年份合计 196/200，剩余 4 个缺口（2019-Q12、2024-Q17、2024-Q37、2025-Q27）读图补齐。

## 答案版式

| 版式 | 年份 | 提取方式 |
|---|---|---|
| 表格 + 单字母/字母块 | 2009–2018（部分） | 坐标定位 + 行列聚类，缺口由手工答案覆盖 |
| 行内 `NN. X` | 2012、2020 | 正则 |
| 逐行单字母 | 2022 | 顺序读取 |
| `【参考答案】X` | 2023 | 正则 |
| 扫描件 | 2019、2021、2024、2025、2026 | MinerU + 手工核对 |

## 当前覆盖

| 项 | 数量 |
|---|---:|
| 题目总数 | 720（18 年 × 40 道选择题） |
| 有标准答案 | **720（100%）** |
| 四个选项完整 | 696 |
| 有解析 | 418 |

按学科：数据结构 180、计算机组成 90、操作系统 180、计算机网络 270（按 408 题号划分）。

> 解析（explanation）只覆盖有文字层的年份；扫描年份的解析在 MinerU Markdown 里存在，但尚未结构化入库。

## 记录结构

```json
{
  "record_id": "refq-408-2024-01",
  "source": "408_exam",
  "year": 2024,
  "exam_title": "2024年全国硕士研究生入学统一考试计算机学科专业基础综合",
  "question_no": 1,
  "subject": "data_structure",
  "question_type": "single_choice",
  "stem": "...",
  "stem_norm": "去除空白的题干，用于指纹匹配",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "options_complete": true,
  "standard_answer": "C",
  "answer_available": true,
  "explanation": "...",
  "answer_method": "grid",
  "trust_level": "A",
  "knowledge_points": [],
  "anchors": {
    "paper_file": "2024.pdf",
    "answer_file": "2024-answer.pdf",
    "question_no": 1
  }
}
```

## 数据库

```sql
reference_questions(
  record_id, source, year, exam_title, question_no, subject, question_type,
  stem, stem_norm, options_json, options_complete, standard_answer,
  answer_available, explanation, answer_method, trust_level,
  knowledge_points_json, anchors_json
)

reference_questions_fts(stem_tokens, explanation_tokens, record_id)
```

`stem_norm` 用于同题指纹；`reference_questions_fts` 用于示例检索。

## 使用边界

- **可以**：从参考题检索相似题目作为生成示例；用 `standard_answer` 做同题答案比对。
- **不可以**：把参考题当作学科事实依据去判断另一道题的对错（Proposal §3.4 明确禁止）。
- 参考题必须先经审校（`review_status = PASS`）才进入可用池；当前数据尚未附审校状态。

## 待办

1. ~~OCR 补齐 2019、2021、2024、2025、2026 五年的选择题答案~~（已完成，720/720）。
2. ~~补齐 2009/2013/2014/2015/2016/2017 中尚未覆盖的题号~~（已完成）。
3. 知识点标注：把 `knowledge_points` 与 408 大纲对齐。
4. 综合应用题（41–47）的结构化，当前只保留题干与分值。
5. 审校状态回填：`review_status`、`review_confidence`。
6. 扫描年份的解析（explanation）结构化：MinerU Markdown 里已有，尚未回填到记录。
7. 24 道题的选项不完整（多为含图选择题），需人工补录或保留 `options_complete=false`。
