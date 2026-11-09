# 组卷默认扩展与 PostgreSQL 题库接入

## 分支核对（2026-11-08）

- `main`：`4b1aabe`，包含知识库同学最新参考题提取和答案补齐。
- `exam-checker`：`db50295`，与旧审校基线一致。
- `Knowledge-base`：`3a993a2`，另有知识库与审校集成、规则检查等工作；未将整条分支强行合并。
- `exam-assembly`：`0ff9590`，此前已上传的模拟组卷与 HTML/PDF 导出。

本工作目录以最新 main 为基础，保留原组卷模块并新增生产入口。没有修改或提交原 github-upload 工作目录。

## 两个库必须区分

`research-assets/skills/build-knowledge-base` 的参考题使用 SQLite `reference_questions`；主分支文档明确其尚未附审校状态，知识点标签也不在该同学当前范围。720 道参考题不等于 720 道已审校的 PostgreSQL 可组卷题。

生产数据链路：

```text
普通 Pi 的内置 exam_assembly
  -> POST http://127.0.0.1:8092/v1/exam-assembly/assemble
  -> GET http://127.0.0.1:8091/v1/question-bank/search
  -> PostgreSQL question_bank
  -> 逐题 GET /v1/exam-checker/documents/{id}/questions/{id}/state
  -> 核对版本、内容、当前 PASS 与 STORED
  -> 配额选题及相同题干检查
  -> 字面相似筛查，疑似题等待内容绑定的人工复核
  -> 分别导出学生卷、答案卷、报告
```

Pi 不接触数据库账号，不执行 SQL。正式入口没有 JSON/mock 回退。原 `pi-extension.ts`、`pi_bridge.py` 和演示 JSON 保留作显式离线开发工具，不用于正式服务。

## 启动步骤

首次安装Pi依赖后，在仓库根目录执行 `npm.cmd --prefix .\pi-coding-agent run hydrate:model-data:release`，恢复与源码配套的模型目录并保留实测deepseek-flash；完整说明见 `MODEL_CATALOG.zh-CN.md`。不要把自动拉取的最新模型目录当作固定源码版本的验收基线。

1. Docker 中启动团队 PostgreSQL，按审校服务原说明配置数据库、完成迁移并启动审校后端 8091。

本地运行时把所选模型提供方的地址、模型 ID 和密钥写入被 Git 忽略的 `pi-coding-agent/.env`，然后依次运行 `pi-coding-agent/start-exam-checker-db.sh` 与 `pi-coding-agent/start-exam-checker.sh`。完整命令见根目录 `README.md`；API Key 不得写入源码或提交到仓库。

对已人工核对的纯文字PDF，可显式加 `-PreferEmbeddedPdfText`：每页至少200个非空白字符且没有栅格图片时优先读取文字层，再调用真实模型提取结构。默认仍调用MinerU；扫描件、混合图片页和文字稀疏页也仍走MinerU。此检查无法排除矢量图，不应对未核对的图文试卷启用。文字来源标记为 `embedded-pdf-text`，不会冒充MinerU任务，审校和入库要求不变。
2. 在仓库根目录启动组卷后端：

```bash
source .venv/bin/activate
./scripts/start-exam-assembly.sh
```

脚本默认使用 `python3`，可通过 `QODEX_PYTHON` 指定已安装 FastAPI/httpx/uvicorn 的 Python。脚本会设置仓库根目录和组卷服务源码的导入路径，不需要移动模块。

独立部署时安装两个 Python 包：

```powershell
python -m pip install -e . -e .\pi-coding-agent\services\exam-assembly
```

需要 PDF 时额外安装核心的 `exam_assembly_agent/requirements-pdf.txt`，再传 `export_pdf: true`。HTML 默认生成。

3. 在另一窗口验证两个后端。健康检查不代表银行已具备可用题目：

```powershell
Invoke-RestMethod http://127.0.0.1:8091/health
Invoke-RestMethod http://127.0.0.1:8092/health
Invoke-RestMethod 'http://127.0.0.1:8091/v1/question-bank/search?limit=5' | ConvertTo-Json -Depth 15
```

4. 使用本工作目录的 Pi 源码正常启动。已安装的全局旧 Pi 不会自动变成此版本：

```powershell
& .\exam_assembly_agent\run-team-pi.ps1
```

使用个人 DeepSeek 的新PowerShell窗口需要单独设置密钥；环境变量不会从另一个已打开的窗口自动同步：

```powershell
$env:DEEPSEEK_API_KEY = ([Net.NetworkCredential]::new('', (Read-Host 'DeepSeek API Key' -AsSecureString))).Password.Trim()
& .\exam_assembly_agent\run-team-pi.ps1 -PiArguments @('--provider','deepseek','--model','deepseek-flash')
```

模型ID必须以自己账号的实际可用列表为准。公司网关账号也可追加原来的 `-PiArguments @('--provider', 'talkweb', '--model', '实际可用模型ID')`；不同提供方的密钥不可混用。

**不使用 `run-assembly-pi.ps1` 或 `-e pi-extension.ts`**；它们是此前显式模拟演示入口。默认扩展列表现在会同时注册 `exam_checker`、`question_bank` 和生产版 `exam_assembly`。

## 请求语义

公开请求已统一为 schema_version=1.0，使用题型题数、题型分值与知识点题数；内部才转换为既有选题核心格式。目前仍只支持四选项单选题，未实现混合题型/计算题；不能因请求格式支持题型映射就声称已支持计算题。

```json
{
  "schema_version": "1.0",
  "request_id": "real_001",
  "subject": "数据结构",
  "question_count": 2,
  "total_score": 4,
  "question_type_counts": {"single_choice": 2},
  "question_type_scores": {"single_choice": 2},
  "knowledge_point_counts": {"栈": 1, "队列": 1},
  "difficulty_counts": {"easy": 1, "medium": 1, "hard": 0},
  "max_repair_rounds": 3,
  "export_pdf": false
}
```

- `subject`、知识点、题型标签精确匹配数据库；不猜测中英文映射。
- `knowledge_point_counts` 是知识点的互斥配额。一道题有多个知识点时可选其中一个配额位置，不能重复使用同一记录凑数。
- 题型题数、知识点题数、难度题数必须分别合计到总题数；总分必须等于各题型题数乘以对应单题分值的合计。
- `question_type_scores` 是每题的分值，不是该题型总分；其键与 `question_type_counts` 相同。easy、medium、hard 三个键必须提供，不需要的难度填 0。
- 公开 API 不再接受旧 `question_type`、`score_per_question`、`topic_counts`；旧离线演示命令和核心输入格式不变。
- 不接受 `allow_mock_reviews`、`bank` 等模拟参数。
- 原始题目分值必须匹配；答案只能为 A-D 或唯一匹配选项全文；不猜答案。
- 题库暂未定义解析字段。缺解析时答案仍导出，标注“未提供解析”，不让模型编造。
- 包含参考材料的题目前拒绝导出，避免缺少材料导致残缺题面；复杂图片与数学排版不属于本次实现。

## 完成与未完成

- `STRUCTURAL_PASS`：配额及相同题干检查通过，返回学生 HTML、答案 HTML、JSON、报告的服务主机绝对路径。
- `NEEDS_QUESTIONS`：当前有效题库不足，返回 `deficits` 联合补题建议、可保留的题目分配及独立 `replenishment_request.json`。不同维度不能相加；联合槽位是一种可行补齐方案，不表示每个槽位都是唯一必需的。
- `INVALID_REQUEST`：配额不一致或不支持的请求；不会自动修改。
- `UNRESOLVED`：搜索预算耗尽、源题在选题后变化，或候选查询达到 API 上限，不能断言全库无解。
- `TOOL_ERROR`：网络、响应、导出失败，保留 HTTP 状态和 detail。

现有题库搜索每个查询最多100条且无分页。本次按知识点×难度分别查，再去重。查询满100条且无法选足时返回 UNRESOLVED，不把截断结果误报为全库缺题。

联合补题规划在当前已验证候选池中寻找不超配额、题干不重复的保留方案，再配对剩余知识点和难度。它能发现“各维度单独都够、联合配额却无解”的情况。规划有搜索预算；只有 `minimum_count_proven=true` 才证明当前候选池的最少补题数量，未证明时会如实标注。UNRESOLVED 不给确定补题指令。补题仍须经过独立审校、入库，再重新选题和验证。

完整可交给团队的字段约定见 `ASSEMBLY_CONTRACT.zh-CN.md`，示例为 `pi-coding-agent/services/exam-assembly/examples/request.json`。

版本和审校在选题前与导出前分别读取；不是跨服务数据库事务快照，不能保证导出后题目永远不被修改。报告保存源记录和版本，供追溯。

已接入字面相似筛查、人工题对复核和确认重复后的配额重选，详见 `SIMILARITY_REVIEW.zh-CN.md`。疑似题返回UNRESOLVED，不自动判错。尚未实现完整语义去重、跨题答案泄露检测、自动出题/审校补题闭环、跨主机文件下载或生产身份认证。默认只监听本机。STRUCTURAL_PASS 不是这些项目的质量验收。

## 测试与实际数据情况

- 当前核心48项、服务20项、组卷与原审校扩展合计22项测试通过。测试还包含64种小规模候选池的联合补题数量核对；相似题案例仅验证规则与流程，不是实际准确率评测。
- 独立 PostgreSQL（5544）合成测试，调用真实审校服务路由与数据库仓储，验证成功、缺题、源 record_id 以及4张来源表全部内容未变。
- 合成 PASS 仅用于隔离测试，不代表真实审校；不向团队 `qodex` 数据库写入合成题。
- 最初本机 `question_bank` 为空。现已将用户提供试卷的3道纯文字节选交给真实模型提取结构，核对题干、ABCD选项、答案、分值和题型，再调用真实审校。3题全部PASS、无未完成检查，自动入库STORED，并逐条回读确认。
- 已在当前源码Pi中，用自然语言调用内置 `exam_assembly`，从本机真实PostgreSQL题库选出3题、每题2分、总分6分，知识点各1题、easy 1题和medium 2题，返回STRUCTURAL_PASS。学生HTML无答案，答案HTML对应A、C、B；无模拟回退。该3题小样本仅验证接入流程，不代表大型题库或语义检测准确率验收。
- 试卷PDF、数据库内容、API Key与运行产物不随Git提交。同学克隆代码后仍需自行配置本地数据库，并经审校流程建立可用题目。详见 `VALIDATION.zh-CN.md`。

测试脚本 `pi-coding-agent/services/exam-assembly/tests/postgres_smoke.py` 仅接受库名 `assembly_test` 的显式测试连接。运行前设置 `PYTHONPATH` 包含仓库根、组卷服务 src 和审校服务 src，以及 `EXAM_ASSEMBLY_TEST_DATABASE_URL`。

此前113项packages/ai类型错误已通过恢复同版本发布基线、应用源码兼容规则并保留deepseek-flash解决。`npm run check`已通过。恢复方式、归档校验及模型可用性边界见 `MODEL_CATALOG.zh-CN.md`；没有删除测试或放宽业务类型约束。
