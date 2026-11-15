# 接口真样本（改字段前先看这里）

这些文件是**真实捕获**的请求/响应，不是手写示意。四个模块的字段只要对不上，先在本目录里比对，
而不是猜。每个文件都标注了捕获时间与复现命令。

| 文件 | 环节 | 谁产出 → 谁消费 |
| --- | --- | --- |
| `01-generate-success.json` | 命题成功（`author`） | 命题服务 8093 → Pi / 审校 |
| `02-review-success.json` | 审校 PASS + 自动入库 | 审校服务 8091 → Pi / 题库 |
| `03-bank-record.json` | 题库检索返回的**一条记录** | 审校 8091 → 组卷 8092 |
| `04-assemble-request.json` | 组卷请求 | Pi / 网页 → 组卷 8092 |
| `05-assemble-success.json` | 组卷成功（`STRUCTURAL_PASS`） | 组卷 8092 → Pi / 网页 |
| `06-assemble-needs-questions.json` | 组卷缺口（`NEEDS_QUESTIONS`） | 组卷 8092 → Pi（补题依据） |
| `07-generate-fail-invalid.json` | 命题请求不合法（`INVALID_REQUEST`） | 命题 8093 → 调用方 |
| `08-generate-fail-model.json` | 命题失败（`MODEL_UNAVAILABLE`，输出被截断） | 命题 8093 → 调用方 |
| `09-review-needs-revision.json` | 审校打回（`NEEDS_REVISION`，附逐条错误） | 审校 8091 → Pi（修订依据） |
| `10-student-exam-artifact.json` | 试卷产物 `student_exam.json` | 组卷 8092 → 教师（打印/分发） |

## 五条最容易踩的口径

1. **失败也是 HTTP 200。** 看 `status`，不要看状态码。`07` 就是 200 + `INVALID_REQUEST`。
2. **命题有两种题形状。** `author` 返回 `student_view` / `instructor_view`（`01`）；
   `single` / `batch` 返回 `question` / `metadata`。入库后统一成 `question_json.question`（`03`）。
   谁按其中一种去读另一种，都会拿到 `undefined`。
3. **组卷只认题库里的形状**（`03`），它不读命题响应。要求：`subject` 中文、
   `options` 四个、`answer_text` 是选项原文或单个 A–D、`reference` 必须为空、`points` 是数字且与请求分值一致。
4. **组卷成功响应不含题目内容**（`05`）：`student_exam` / `answer_key` 被有意移出响应，
   只给 `artifacts` 路径（`student_exam.json` 见 `10`）。想在响应里直接拿题面会拿到 `undefined`。
   另外 `10` 里的 `question_id` 实际是题库 `record_id`；要回溯来源看 `selected_sources`。
5. **卷子做不长，先看 `rejected_records`**（`06`）：那里写着每道候选为什么被剔除
  （版本过期、分值不一致、带参考材料等）。`deficits` 只说缺什么，不说为什么补不上。
   若 `pool_complete=false`，说明某次检索撞到 100 条上限，此时**不能**断言"全库缺题"。

## 审校的口径（别把 PASS 当质检报告）

- `02`：`review.summary.errors` 为空 + `ingestion.status=STORED` 才算"入库成功"。
- `09`：`NEEDS_REVISION` 带逐条 `errors`（`error_type` / `position` / `correction` / `severity`），
  修订要用这些条目，不要自己另编问题。
- 审校**看不到答案与评分**（服务只收到题面与选项），所以 `PASS` 不等于答案正确。

## 复现（本机服务在跑时）

```bash
# 01 / 08：命题（付费；08 依赖模型偶发截断，难以稳定复现）
curl -sS -X POST http://127.0.0.1:8093/v1/question-generation/author \
  -H 'content-type: application/json' \
  -d '{"schema_version":"0.1","request_id":"doc-sample","brief":"想练单链表的头插尾插，出一道单选题"}'

# 02 / 09：审校（需 task_id + question_id + version）
curl -sS -X POST http://127.0.0.1:8091/v1/exam-checker/tasks/<task_id>/questions/<question_id>/review \
  -H 'content-type: application/json' \
  -d '{"version":1,"idempotency_key":"doc-sample"}'

# 03：题库记录
curl -sS -G http://127.0.0.1:8091/v1/question-bank/search \
  --data-urlencode 'subject=数据结构' --data-urlencode 'limit=1'

# 04 → 05 / 06：组卷（免费；把 difficulty_counts 改成 medium / easy 即可得到成功 / 缺口两种结果）
curl -sS -X POST http://127.0.0.1:8092/v1/exam-assembly/assemble \
  -H 'content-type: application/json' -d @docs/samples/04-assemble-request.json
```

## 来源与时间

- `01` `02`：2026-11-15 合并后真实链路 run7（`deepseek-flash`），题：单链表头插/尾插。
- `03`：2026-11-15 本地题库检索实拍（该题即 `01` 入库后的记录）。
- `04`–`06` `10`：2026-11-15 17:0x 本机组卷实拍；`06` 故意把难度设成 `easy` 以触发缺口。
- `07`：2026-11-15 现场构造的非法请求（`requirements` 传成对象而非字符串数组）——这是最常撞的 422。
- `08`：2026-11-15 run3，作者阶段两次输出截断（`content_decode`），重试无效。
- `09`：2026-11-15 run1，选项缺 A–D 标识被打回；该缺陷后来在命题侧修复。

脱敏：样例中的绝对路径已替换为 `<repo>`；不含任何密钥。id 保留原值，便于与 `.local/` 下的证据对照。
