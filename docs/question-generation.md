# 自主命题模块

> 状态（2026-11-15）：本页描述**当前实现**的接口与契约。
> 当前任务与真实进度见工作区根目录 `TASK_STATE.md`；四模块接线与政策/护栏见 [Agent 工作流](agent-workflow.md)；
> 通用创作的设计与验证边界见 [通用命题主线](question-generalization.md) 和 [实测记录](question-generalization-evaluation.md)。
> 本页“历史”小节保留合并前的分支快照，仅供追溯，不代表当前状态。

自主命题面向 408 专项练习和模拟卷补题。模块依据题型、考点和可追溯的资料生成题目、参考答案和解析，完成自检后交由独立审校。收到审校反馈时修订题目并重新自检。

[材料驱动的模型创作](question-authoring.md)（旧五考点 v1.1，历史快照）通过 `constraints.authoring` 设计条件反推、错误诊断和方案选择题；[通用材料驱动创作](question-generalization.md)（当前主线）在此基础上支持 24 章节、单选与综合题、粗需求入口和一轮定向修订。旧请求保持确定性规则生成。三条路径并存，不要混用。

| 职责 | 边界 |
| --- | --- |
| 命题与自检 | 设计题目和考法，校验题面、答案及解析，提供可定位的依据 |
| 知识库 | 提供知识点和引用材料，命题以结构化输入接收 |
| 单题审校 | 独立给出审校结论，自检结果与审校结论分别记录 |
| 组卷 | 提供缺题槽位及分值约束，管理整卷蓝图和整卷验证 |
| Pi | 组织工具调用，传递材料和反馈，协调重试与交付 |

现有 [自主命题设计稿](../research-assets/docs/feature-designs/question-generation-agent.md) 提出了单选题、综合应用题及生成和修订接口。模块已覆盖四科五类单选、两类综合题、批量、补题和版本修订。命令行与浏览器验证台用于本地复验；Pi 通过命题服务把自检通过的版本写入待审表，再由审校按 `task_id + question_id + version` 取用。个人开发计划和调研过程放在 `.local/question-generation/`。

## 接手开发

先读仓库 [AGENTS.md](../AGENTS.md) 和本页。当前任务、真实进度与恢复方式见工作区根目录的 `TASK_STATE.md`；通用命题主线的设计、接续顺序与验证边界见 [通用命题主线](question-generalization.md)；四模块接线见 [Agent 工作流](agent-workflow.md)。`.local/question-generation/` 下的计划与交接记录属于个人开发笔记，可能停留在旧阶段。

| 需要修改 | 代码入口 |
| --- | --- |
| 单题请求、题型和自检 | [generation.py](../question_generation/generation.py)，题型实现在同目录 |
| 批量约束、题干去重和组卷补题 | [batch.py](../question_generation/batch.py)、[replenishment.py](../question_generation/replenishment.py) |
| 综合题、评分点和版本修订 | [comprehensive.py](../question_generation/comprehensive.py) |
| 通用创作、粗需求与审计 | [general_authoring.py](../question_generation/general_authoring.py)、[brief_authoring.py](../question_generation/brief_authoring.py) |
| 已核验知识库证据、HTTP 和待审表 | [knowledge.py](../question_generation/knowledge.py)、[service.py](../question_generation/service.py)、[待审表迁移](../question_generation/sql/001_pending_questions.sql) |
| 模型客户端、阶段预算与失败分类 | [model_client.py](../question_generation/model_client.py) |
| Pi 工具 | [内置命题扩展](../pi-coding-agent/packages/coding-agent/src/extensions/question-generation/index.ts) |

从仓库根目录运行 `python3 -m unittest discover -s tests` 验证生成模块。修改 Pi 时按 [Pi 开发纪律](../pi-coding-agent/AGENTS.md) 运行全仓检查和命题扩展测试。升级前先从新鲜的 `origin/main` 核对本地待合入提交，再用隔离 PostgreSQL 复验 Pi 各操作及待审题包回读。更新知识库快照时重新核对证据清单及指纹（见 `.local/question-generation/team-kb/MIGRATION-2026.11.1.md`）。

## 工作区与依赖分支

从仓库根目录运行 `git status --short --branch` 确认当前分支。本地命题代码在 `feat/question-generation` 开发，已合并 `origin/main`；四个业务模块现在同仓，不需要再从其他功能分支复制接口。开始新一轮开发前重新 `git fetch origin` 并核对接口。

### 历史：2026-11-08 分支快照（合并前）

下表是合并前核对的分支状态，**已过期，仅作追溯**；当前同仓代码以本页其余章节为准。

| 分支和版本 | 已有能力 | 对命题的影响 |
| --- | --- | --- |
| `origin/main` · `4b1aabe` | [PostgreSQL 和数据库迁移](../pi-coding-agent/services/exam-checker/DATABASE.zh-CN.md)、审校和正式题库接口，以及 SQLite 参考题资产 | 生成草稿可以接收本地材料。通过独立审校后，由审校服务写入正式题库 |
| `origin/exam-checker` · `db50295` | 该版本已包含在 `main` 的历史中。当前[单题审校入口](../pi-coding-agent/services/exam-checker/src/exam_checker/api/app.py#L302)需要已有文档 ID 和题目 ID | 结构化新题如何直接送审，是接通正式入库前需要核实的接口 |
| `origin/Knowledge-base` · `3a993a2` | 未合入 `main` 的[教材检索实现](https://github.com/HenryZhu123/hku_agent/blob/3a993a2/pi-coding-agent/services/exam-checker/src/exam_checker/integrations/knowledge_base.py#L156)，目前接在审校内部 | 命题先接收结构化的证据材料。接入真实检索时，核实如何按考点取材并保留出处 |
| `origin/exam-assembly` · `c891810` | 未合入 `main` 的[组卷补题契约](https://github.com/HenryZhu123/hku_agent/blob/c891810/ASSEMBLY_CONTRACT.zh-CN.md#L30)，组卷已能通过审校服务查正式题库，并返回结构化缺题请求 | 可以用缺题请求样例验证命题输入，正式补题仍需经过审校、入库和重新组卷 |

[SQLite 参考题](../research-assets/skills/build-knowledge-base/references/reference-question-bank.md)可作为考法示例，当前记录尚未附审校状态。PostgreSQL 的 `question_bank` 用于保存通过审校的题目及其来源版本。命题模块通过服务接口交接题目，自检和独立审校分别记录。

## 独立开发与联调

- 用本地证据样例走通单选题生成和自检。最小链路可以验证输入约束、题目与解答格式、材料出处，以及资料不足时的返回。运行这条链路无需启动 PostgreSQL。
- 需要验证其他分支时，先阅读实际接口和测试。需要运行对方代码时，在独立 Git 工作树检出固定提交，并为联调使用独立的测试库。日常命题工作继续留在 `feat/question-generation`。
- 正式联调先核对结构化新题能否送审、入库并回读，再接真实知识检索和组卷补题。现有接口和样例足够时可以独立推进。只有需要上游新增接口、统一共享字段或修改数据库结构时，才提交具体的最小协作事项。

### L3 送审契约

命题与审校已经统一使用 `task_id + question_id + version`：

1. Pi 发起命题时自动生成 UUID `task_id`；批量调用返回的所有题共享该 ID。
2. 命题服务创建 `generation_tasks`，并将每个自检通过版本写入 `pending_questions`。
3. `exam_checker.review_question` 使用同一个 `task_id`、题目 ID 和可选版本；未指定版本时读取部分唯一索引标记的当前版本。
4. 审校开始前把命题包转换为 `question_snapshots` 中的不可变快照，审校和题库都以物理复合外键绑定该版本。
5. 相同 `idempotency_key` 的审校重试返回原记录；同一题目版本重复入库返回原题库记录。新版本不会覆盖旧版本。

上传文档仍保留在 `exam_documents`，不会伪装成 AI 命题任务；解析出的题目以文档解析 ID 作为审校 `task_id`，并通过 `source_document_id` 物理外键保留来源。

### Pi 调用与待审表交接

Pi 内置工具 `question_generation` 统一注册在 [question-generation/index.ts](../pi-coding-agent/packages/coding-agent/src/extensions/question-generation/index.ts)。工具参数是 `operation` 和 JSON `request`，支持 `single`、`batch`、`replenishment`、`comprehensive`、`revise`、`author`。通过 `QUESTION_GENERATION_SERVICE_URL` 指定命题服务地址，默认 `http://127.0.0.1:8093`。工具侧超时按 operation 区分：`batch` 与 `replenishment` 默认 1200 秒，其余 600 秒；服务内部另有阶段与整条流水线时限（见「模型输出、超时与失败诊断」）。

从仓库根目录，用 Python 3.11 或更新版本安装服务依赖。数据库管理员按文件名顺序执行 `question_generation/sql/*.sql`，再授权已创建的服务账号和审校只读账号。下面以 `qg_writer` 和 `qg_reviewer` 为示例角色。

```bash
python3 -m pip install -r question_generation/service-requirements.txt
psql "$QODEX_SCHEMA_ADMIN_DSN" -v ON_ERROR_STOP=1 -f question_generation/sql/001_pending_questions.sql
psql "$QODEX_SCHEMA_ADMIN_DSN" -v ON_ERROR_STOP=1 -f question_generation/sql/002_generation_tasks.sql
```

```sql
GRANT USAGE ON SCHEMA question_generation TO qg_writer, qg_reviewer;
GRANT EXECUTE ON FUNCTION question_generation.enqueue_question(uuid, jsonb, text, jsonb) TO qg_writer;
GRANT SELECT ON question_generation.current_pending_questions TO qg_reviewer;
```

在服务环境配置 `QUESTION_GENERATION_DATABASE_URL` 为写入账号的 PostgreSQL 连接字符串，再启动服务。Pi 只需服务 URL。

```bash
python3 -m uvicorn question_generation.service:app --host 127.0.0.1 --port 8093
curl -fsS http://127.0.0.1:8093/v1/question-generation/single \
  -H 'Content-Type: application/json' --data-binary @question_generation/examples/paging.json
```

服务只入队自检通过的题目包。返回 `queue_receipts` 表示已确认写入，`QUEUED` 是首次入队，`ALREADY_QUEUED` 是相同版本的重试。批量部分成功时保存其中实际合格的题。版本冲突返回 `QUEUE_VERSION_CONFLICT`，数据库不可用返回 `QUEUE_UNAVAILABLE`。同一次调用的写入在一个事务内。修订须传入与待审表一致的原始包，可使用前次调用返回的题目。旧版仍可追溯，当前取题视图只显示最新版本。原有命令行和验证台可继续用于本地预览。

审校按 `task_id`、`question_id` 和 `version` 识别不可变对象，`question_json` 内含学生题面、教师答案、评分点和证据来源。

```sql
SELECT task_id, question_id, version, request_id, question_json, queued_at
FROM question_generation.current_pending_questions
ORDER BY queued_at, task_id, question_id
LIMIT 100;
```

### 按考点从知识库取材

可同时配置 `QUESTION_GENERATION_KB_ROOT` 和 `QUESTION_GENERATION_KB_CATALOG`。配置后，`single`、`comprehensive`、`batch` 和 `replenishment` 请求中省略 `evidence` 的题或槽位按 `subject` 和 `topic` 取材；显式材料数组照常校验，显式空数组返回缺材料。修订继续使用原题证据。命令行和本地验证台沿用原有显式材料契约。

知识库根目录沿用 `operating_system`、`data_structure`、`computer_organization`、`computer_network` 四个科目子目录，每科可引用 `kb.sqlite` 或 `kb_*.sqlite`。命题以只读方式读取 `documents` 和 `chunks`，取材范围由已核验清单指定。

清单是包含 `schema_version: "0.1"` 和 `entries` 数组的 JSON。每条记录包含下列字段。

| 字段 | 含义 |
| --- | --- |
| `subject`、`topic` | 命题契约使用的科目和考点 |
| `database`、`doc_id`、`chunk_id` | 科目目录下的文件名、文档和片段标识 |
| `source`、`edition` | 审校可以追溯的来源和教材版次 |
| `source_sha256`、`content_sha256` | 源文档 SHA-256 和 SQLite 片段正文 UTF-8 的 SHA-256，均为小写十六进制 |
| `summary`、`rules` | 预核验的摘要与该片段实际支撑的命题规则数组 |
| `section` | 可选。章节路径抽取混入正文或误标时填写核验后的章节名，保留索引页码和分块 ID |

清单由取材方核验来源、使用许可和规则覆盖。服务核对文档和片段指纹，跳过缺定位、指纹不匹配、片段元数据标记有冲突或列在同科目录 `relations.json` 冲突组里的片段。冲突文件存在但无法解析时，该科取材报 `KNOWLEDGE_BASE_UNAVAILABLE`。规则不足时返回 `NEEDS_MATERIAL` 和缺失规则。配置的索引无法读取且没有可用证据时，返回 `KNOWLEDGE_BASE_UNAVAILABLE`。批量在对应槽位记录缺口并保留其他合格题。

**当前教材包是 2026.11.1**（2538 chunk / 2391 进 FTS），安装在 `.local/question-generation/team-kb/`（`books/`、`MANIFEST.json`、`catalog.json`）；旧版归档在 `team-kb-2026.11-frozen/`。换版后 chunk 编号已全部错位，**清单和评测规格里的 chunk 编号必须按内容核对，禁止按序号猜**；`team-kb/build_catalog.py` 内置了“section 编号必须被该块自身正文/标题印证”的断言。细节与已知的预期中断见 `team-kb/MIGRATION-2026.11.1.md`。

### 组卷联合缺口到待审

在 Pi 中调用 `question_generation`，将 `operation` 设为 `replenishment`，在 `request` 中提供 `replenishment_request`（组卷原始计划）、整数 `seed` 和 `slot_profiles`。同一个 `request` 也可直接发给 `POST /v1/question-generation/replenishment`。适配器使用联合计划的 `deficits`，按原顺序分配 `assembly-1`、`assembly-2` 等槽位 ID，保留原科目、考点、题型、难度、分值和题量，并按槽位填充、过滤 `avoid_stems` 中的规范化题干。

`slot_profiles` 由调用方为每个可命题槽位指定命题模块的 `topic`，可提供原有 `constraints` 和 `evidence`。配置了知识库时，省略材料的槽位也可按考点取材。未配置映射、题型不支持或材料不足的槽位会在结果中保留缺口。结果中的 `assembly_request_id` 对应组卷请求；入队题包和剩余缺口的 `assembly_slot` 都可追溯到原槽位。若保留题干命中，`reserved-stem-1` 等编号对应 `avoid_stems` 的位置。原样重试复用待审记录。

请求示例（把组卷缺口计划与已有栈材料组合）：

```bash
python3 - /path/to/replenishment_request.json <<'PY' | \
  curl -fsS http://127.0.0.1:8093/v1/question-generation/replenishment \
    -H 'Content-Type: application/json' --data-binary @-
import json
from pathlib import Path
import sys

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
sample = json.loads(Path("question_generation/examples/stack.json").read_text(encoding="utf-8"))
print(json.dumps({
    "replenishment_request": plan,
    "seed": 42,
    "slot_profiles": {
        "assembly-1": {key: sample[key] for key in ("topic", "constraints", "evidence")}
    },
}, ensure_ascii=False))
PY
```

> **确定性规则生成路径（v0.1，仍在用）。** 以下契约是模块最早的五题型族规则生成，仍在 `single`/`batch`/`comprehensive`/`revise` 中可用且可复算。新增命题能力走通用材料驱动路径（见 [通用命题主线](question-generalization.md)），不要继续扩展这套按考点手写的生成器。

## 本地命题契约 v0.1

| 科目 | 单选题型 | 自检 |
| --- | --- | --- |
| 操作系统 | [单级页表地址转换](../question_generation/examples/paging.json) | 用位运算独立复算物理地址 |
| 数据结构 | [单栈出栈序列判定](../question_generation/examples/stack.json) | 逐项模拟入栈与出栈，检查可达性和答案唯一性 |
| 计算机组成原理 | [直接映射 Cache 地址拆分](../question_generation/examples/cache.json) | 用位切片独立复算标记、行号和块内偏移 |
| 计算机网络 | [IPv4 子网网络地址](../question_generation/examples/subnet.json) | 用 Python 标准库独立复算网络地址 |
| 计算机网络 | [TCP 字节流与消息边界](../question_generation/examples/tcp.json) | 检查预核验选项中只有一项符合证据规则 |

分页题按字节寻址，页大小为 2 的幂，题面所列映射均有效。生成器拆分虚页号和页内偏移，用页表查出物理页框号，保留页内偏移。[OSTEP 分页章节](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-paging.pdf)

出栈题设定初始空栈且容量足够，元素按 1 至 n 的顺序各入栈一次。生成器按相对次序分类。如果候选序列依次出现 a、b、c，且 b < c < a，先弹出 a 就已让 c 入栈，随后 c 会挡住 b。自检用另一种方法逐项模拟四个选项，并要求唯一可达的序列与答案 ID 一致。[Princeton 栈练习](https://algs4.cs.princeton.edu/13stacks/index.php) · [Python 栈操作说明](https://docs.python.org/3/tutorial/datastructures.html#using-lists-as-stacks)

Cache 题使用 16 位字节地址。题面给出数据容量及块大小，每行存一块。生成器先按块大小取商和余数，再将主存块号除以行数，得到标记和行号。自检从地址位字段独立提取这三个值。[MIT 6.004 缓存讲义](https://ocw.mit.edu/courses/6-004-computation-structures-spring-2017/pages/c14/c14s1/)

IPv4 子网题给出地址和 CIDR 前缀长度。生成器将地址向下对齐到所属地址块的起点，使用标准库 `IPv4Network` 独立检查答案。[RFC 4632 §3.1](https://www.rfc-editor.org/rfc/rfc4632.html#section-3.1) · [Python ipaddress](https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Network)

TCP 概念题考查按序字节流、应用读写边界和应用层分帧。选项和解析依据两个条款预先核验，模块检查答案的唯一性并保留证据定位。[RFC 9293 §2.2](https://www.rfc-editor.org/rfc/rfc9293.html#section-2.2) · [RFC 9293 §3.7](https://www.rfc-editor.org/rfc/rfc9293.html#section-3.7)

### 本地运行

从仓库根目录运行以下命令。需要 Python 3.9 或更新版本，依赖为 Python 标准库。

```bash
python3 -m question_generation question_generation/examples/paging.json
python3 -m question_generation question_generation/examples/stack.json
python3 -m question_generation question_generation/examples/cache.json
python3 -m question_generation question_generation/examples/subnet.json
python3 -m question_generation question_generation/examples/tcp.json
python3 -m unittest discover -s tests
```

样例均把 UTF-8 JSON 结果写到标准输出。成功退出码为 0，命题失败退出码为 1。重复使用同一个请求、生成器和 Python 版本可重放同一道题。修改示例中的 `seed` 可生成另一变体。Python 调用方也可以使用 `question_generation.generation.generate_question(payload)`。

### 浏览器验证台

在仓库根目录运行 `python3 -m question_generation.ui`，打开 [本地验证台](http://127.0.0.1:8765/)。验证台只在本机监听，可用 `--port` 更换端口，按 Ctrl+C 停止。

试题台与 Pi 共用命题流程，可直接输入需求、粘贴材料或留空让模块选题：先看学生题面，再展开教师答案、评分、材料和考查计划；未过检查的模型题面独立标为“候选”，不进入待审。预览不需要 PostgreSQL。常用参数：

| 参数 | 作用 |
| --- | --- |
| `--provider local\|deepseek` | 选择本机模型或 DeepSeek，默认 `local`；DeepSeek 需在页面逐次确认请求 |
| `--kb-root` / `--kb-catalog` | 启用教材取材，必须同时提供；目录约定见上一节 |
| `--history-example` | 只读展示一份历史题包，页面上标为历史实测 |
| `--public-origin` | 显式放行一个非本机来源（如临时隧道域名），不设时仅限本机访问 |
| `--log-file` | 把每次请求（含失败、阶段耗时与完整结果）追加写入 JSONL |

[规则题验证台](http://127.0.0.1:8765/rules) 保留原有参数和预设。下表的预设属于规则题路径：

| 预设 | 预期结果 |
| --- | --- |
| 标准样例 | 生成并自检一道题。教师答案、逐项解析和完整 JSON 可分别展开 |
| 分页 · 零偏移 | 仍有四个互异选项，和答案碰撞的干扰项被另一条错误规则替换 |
| 出栈序列 · 最少元素 | 以 4 个元素生成四个互异选项，只有一个序列可达 |
| Cache · 块边界 | 地址为 `0x1230`，块内偏移为 0，仍有四个互异选项 |
| IPv4 · 子网起点 | 地址 `10.23.45.64/26` 的主机位已经为零，网络地址仍为 `10.23.45.64` |
| TCP · 消息分帧 | 切换到应用层分帧场景，长度字段是唯一正确选项 |
| 缺少材料 | 返回 `NEEDS_MATERIAL`，显示缺失的规则，无题目 |
| 分页 · 非法页大小 | 以 300 B 发出请求，返回 `INVALID_REQUEST`，无题目 |
| 出栈序列 · 非法元素个数 | 以 3 个元素发出请求，返回 `INVALID_REQUEST`，无题目 |
| Cache · 非法块大小 | 以 24 B 发出请求，返回 `INVALID_REQUEST`，无题目 |
| IPv4 · 超出前缀范围 | 以 `/31` 发出请求，返回 `INVALID_REQUEST`，无题目 |
| TCP · 未知场景 | 返回 `INVALID_REQUEST`，无题目 |

从规则题下拉框切换样例，可调整种子、题型参数和材料规则覆盖。结果与本地命令行一致，题目保留待独立审校状态。通用创作入口、审校、入库和组卷已可用，接入方式见 [Agent 工作流](agent-workflow.md)。

### 请求

请求使用 UTF-8 JSON。

| 字段 | v0.1 约定 |
| --- | --- |
| `schema_version`、`request_id` | 版本为字符串 `0.1`，请求 ID 为非空字符串 |
| `subject`、`topic` | 分页使用 `operating_systems`、`single_level_paging`。出栈序列使用 `data_structures`、`stack_pop_sequence`。Cache 使用 `computer_organization`、`direct_mapped_cache`。IPv4 使用 `computer_networks`、`ipv4_subnet_network_address` |
| `question_type` | `single_choice`，每次生成一道题 |
| `seed` | 0 至 4294967295 的整数，用于复现生成与选项顺序 |
| `constraints` | 可省略。分页的 `page_size` 为 2 至 65536 字节之间的 2 的幂，默认 256。`offset` 可省略，显式给出时须为 0 至 `page_size - 1` 的整数。出栈序列的 `element_count` 为 4 至 6 的整数，默认 5 |
| `evidence` | 材料数组。每条含唯一 `id`、来源 `source`、`version`、定位 `anchor`、材料摘要 `summary` 和标记数组 `rules`。分页要求 `split_address`、`map_virtual_page`、`preserve_offset`。出栈序列要求 `stack_push_top`、`stack_pop_top` |

材料由调用方预先核验并标记。模块检查字段、出处元数据及规则覆盖，使用内置规则求解。材料摘要的语义和引用可访问性由提供方核验。省略材料或传入空数组会得到缺材料结果。

Cache 的 `cache_size` 与 `block_size` 均为 2 的幂。数据容量支持 16–4096 B（默认 256 B），块大小支持 4–256 B（默认 16 B），且至少有两行。可选 `address` 为 0–65535 的整数，省略时由种子决定。材料须覆盖 `cache_byte_offset`、`cache_line_index`、`cache_tag`。

IPv4 的 `prefix_length` 支持 16–30，默认 26。可选 `ipv4_address` 为标准点分十进制字符串，省略时从 `10.0.0.0/8` 以种子选取。材料须覆盖 `ipv4_cidr_prefix` 和 `ipv4_subnet_alignment`。[RFC 1918 §3](https://www.rfc-editor.org/rfc/rfc1918.html#section-3)

TCP 使用 `computer_networks` 和 `tcp_message_boundaries`。可选约束 `scenario` 为 `reads`（读写边界）或 `framing`（消息分帧），省略时由种子选择。材料须覆盖 `tcp_ordered_byte_stream` 和 `tcp_no_message_boundaries`。

读写边界场景还可通过 JSON 指定 `payloads`，提供 2 至 4 段 ASCII 大写字母串，每段 1 至 6 个字母。指定后使用 `reads` 场景，题目同时考查按序拼接后的实际字节流与读写边界的区别。

### 输出与验收

成功时返回 `GENERATED` 和一个含一道题的 `questions` 数组。面向学生的输出使用 `student_view`，含题干和带稳定 ID 的四个选项。教师视图提供答案 ID、解法和逐项说明。题目包还记录生成器版本、种子、实际题设、出处、自检结果和 `PENDING` 审校状态。选项显示字母可按顺序分配，答案按 ID 关联。

失败时返回 `INVALID_REQUEST`、`UNSUPPORTED_REQUEST`、`NEEDS_MATERIAL` 或 `SELF_CHECK_FAILED`，附原因及空题目列表。材料不足时列出缺失的规则。未知请求字段视为无效，避免忽略约束。

手算对照使用 256 B 页、虚拟地址 `0x02B4` 和映射 `VPN 2 → PFN 5`。虚页号为 2，偏移为 `0xB4`，物理地址为 `0x05B4`。同一映射下，虚拟地址 `0x0200` 的正确结果为 `0x0500`，此时“丢弃偏移”会与正确答案重合，必须换一个干扰项。

出栈序列样例以 1 至 5 入栈。先压入 1 至 4，再弹出 4，随后压入并弹出 5，依次弹出剩余元素，得到 `4、5、3、2、1`。例如 `4、1、2、3、5` 无法出现，因为弹出 4 后，1 仍在 2 的下方。

Cache 样例中 256 B 数据容量与 16 B 块大小给出 16 行。地址 `0x1234` 的主存块号为 `0x123`，块内偏移为 4。块号除以 16，商为 18，余数为 3，因此十进制答案为 `18、3、4`。

IPv4 样例 `10.23.45.77/26` 有 6 位主机位，最后一个八位组按 64 个地址为一块。77 落在 64–127，因此网络地址为 `10.23.45.64`。

## 本地批量命题契约 v0.1

从仓库根目录运行四科混合样例。Python 调用方可直接使用 `question_generation.batch.generate_batch(payload)`。

```bash
python3 -m question_generation --batch question_generation/examples/batch.json
```

请求使用原有的 `schema_version`、`request_id` 和 `seed`，另提供 `question_count`（1–100）、`total_score`（正整数）和非空 `slots` 数组。每个槽位包含批内唯一的 `slot_id`、正整数 `count` 和 `score_per_question`，以及单题契约的 `subject`、`topic`、`question_type`、可选 `constraints` 与 `evidence`。各槽位题数之和必须等于总题量，题数乘单题分值的合计必须等于总分。

批量调用逐题复用单题生成与自检，核对科目、考点、题型及分值，再在结果题目包上记录 `slot_id` 和 `metadata.score`。同一批中，按 Unicode NFKC 和空白折叠后的题干去重。相同题设只保留一次，换种子、题目 ID、选项内容或顺序、分值都不会形成新题。单题请求及其题目包沿用上节契约。

每个槽位最多尝试 `8 × count` 次。分配在本次候选池中尽量填满槽位，同一道题只能归一个槽位。遇到候选重叠时，可替换先前分配的题来填后续槽位。缺口只反映本次候选池及尝试预算。

| 状态 | 结果 | 命令行退出码 |
| --- | --- | --- |
| `GENERATED` | 所有槽位均已填满 | 0 |
| `PARTIAL` | 返回已生成的合格题，并列出每个未填满槽位的缺口 | 1 |
| `NO_QUESTIONS` | 没有合格题，仍返回槽位缺口 | 1 |
| `INVALID_REQUEST` | 批量请求结构无效或题数、总分与配额冲突 | 1 |

有效请求的结果包括请求和实际生成的题数与分值，以及 `deficits` 数组。每项缺口记录槽位、要求数量、实际数量、缺失数量、尝试次数、去重后的候选数和原因。缺材料时会列出缺失的规则。

混合样例预期生成 5 题、11 分。复验部分成功时，将样例中栈槽位的 `evidence` 清空，把固定地址的 Cache 槽位 `count` 改为 2，并将总题量、总分改为 6 和 14。预期得到 4 题、9 分，栈因缺材料少 1 题，Cache 因相同题设去重少 1 题。示例和入口见 [批量请求](../question_generation/examples/batch.json)。

### 参考题去重

批量请求可选填 `reference_questions` 数组。每条须提供批内唯一的 `reference_id`、`stem`、`source` 和 `license`，均为非空字符串。调用方核验题干来源与许可。把 [本地参考题样例](../tests/fixtures/question_generation/references.json) 加入混合请求，可复验 Cache 题命中而其余 4 题保留。

参考题与候选复用批内题干规范化规则，候选通过自检后、分配前过滤。提供参考题字段时，结果会在 `reference_matches` 按槽位记录拦截次数及命中的参考 ID、来源和许可，即使槽位最终填满也会记录。仍有缺口时，槽位原因使用 `REFERENCE_DUPLICATE` 并列出对应参考 ID。改写及只换数字的变体单独纳入近重复评测。

## 分页综合题与修订 v0.1

使用 [分页综合题样例](../question_generation/examples/paging-comprehensive.json) 运行首个 L2 闭环。请求沿用分页的种子、约束和材料，`question_type` 使用 `comprehensive_application`。单选、批量单选及综合题分别通过命令行模式调用。两类综合题共用 `question_generation.comprehensive.generate_comprehensive` 和 `revise_comprehensive`，也可直接调用对应题型模块。

| 小问 ID | 分值 | 评分内容 | 等价解法 |
| --- | --- | --- | --- |
| `split-address` | 2 | 虚页号、页内偏移各 1 分 | 除法取商和余数，或按页大小切分地址位 |
| `physical-address` | 3 | 页框号 1 分、物理地址 2 分 | 页框基址加偏移，或替换高位并保留低位 |
| `cross-page` | 5 | 页尾物理地址、下一虚页号与偏移、下一页框、页首物理地址、连续性及依据，各 1 分 | 比较两物理地址之差，或证明相邻页框判据 |

三问共用一张页表。学生视图包含公共题干、各问 ID、题面和分值。教师视图以同一小问 ID 关联解法、等价解法的接受条件，以及各评分点的稳定 ID、分值、判分要求和期望值。各点按题设独立判分，十进制及标明进制的等值表示均接受。生成器用算术求解，自检用位字段独立复算，跨页连续性额外用页框关系复核。三个小问和九个评分点合计 10 分。

### 复验生成与修订

```bash
qodex_demo=$(mktemp -d)
python3 -m question_generation --comprehensive question_generation/examples/paging-comprehensive.json > "$qodex_demo/v1.json"
python3 - "$qodex_demo" <<'PY'
import json
from pathlib import Path
import sys

directory = Path(sys.argv[1])
question, = json.loads((directory / "v1.json").read_text(encoding="utf-8"))["questions"]
request = {
    "schema_version": "0.1",
    "request_id": "paging-revision-demo",
    "current_question": question,
    "feedback": {
        "feedback_id": "demo-feedback-1",
        "question_id": question["question_id"],
        "target_version": question["version"],
        "part_id": "cross-page",
        "action": "replace_next_frame",
        "replacement_frame": 18,
        "comment": "将下一虚页映射到相邻页框，演示物理地址连续。",
    },
}
(directory / "revise.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
PY
python3 -m question_generation --revise "$qodex_demo/revise.json" > "$qodex_demo/v2.json"
```

样例的虚页 11 和 12 在 v1 分别映射到页框 17 和 63。第三问的物理地址为 `0x11FF` 和 `0x3F00`，不连续。反馈把虚页 12 改映射到页框 18。v2 的后一物理地址为 `0x1200`，结论变为连续。题目、小问及评分点 ID、前两问和总分保持稳定，`revision` 记录反馈 ID、目标小问、源版本及映射变化。新版本重算通过后回到 `PENDING`。

修订请求由调用方提供最新 `current_question` 快照和指向该题该版本的结构化反馈。当前动作只用于 `cross-page`，替换页框须为 0–63 的整数并与两个现有页框不同，每题最多两轮。把修订请求的 `current_question` 改为 v2，沿用目标版本 1 的反馈，得到 `STALE_FEEDBACK`。题目 ID 不匹配、动作不支持、达到上限或自检失败时，返回对应状态和空题目列表。命令行成功退出码为 0，失败为 1。快照的持久化和并发提交由后续接入层负责。

## 栈轨迹与最小容量综合题

使用 [栈综合题样例](../question_generation/examples/stack-comprehensive.json)。请求使用 `data_structures`、`stack_pop_sequence` 和 `comprehensive_application`，沿用栈单选的 4–6 个元素、种子和证据规则。

| 小问 ID | 分值 | 评分内容 | 等价解法 |
| --- | --- | --- | --- |
| `operation-trace` | 4 | 入栈顺序 2 分，合法出栈并产生完整目标序列 2 分 | 写明每次操作，或给出能还原每一步操作的栈状态表 |
| `minimum-capacity` | 4 | 容量 2 分、下界证明 1 分、合法轨迹给出的可达上界 1 分 | 容量下界可用任一达到峰值的出栈位置证明 |

生成器模拟栈顶操作求得轨迹和峰值，自检穷举合法操作，并用目标出栈前缀复核容量下界。第 `k` 次出栈前，若前 `k` 个目标元素中的最大编号为 `m`，则至少已入栈 `m` 个元素，只出栈了 `k - 1` 个，容量至少为 `m - k + 1`。[Princeton 栈练习](https://algs4.cs.princeton.edu/13stacks/index.php)

```bash
qodex_stack=$(mktemp -d)
python3 -m question_generation --comprehensive question_generation/examples/stack-comprehensive.json > "$qodex_stack/v1.json"
python3 - "$qodex_stack" <<'PY'
import json
from pathlib import Path
import sys

directory = Path(sys.argv[1])
question, = json.loads((directory / "v1.json").read_text(encoding="utf-8"))["questions"]
request = {
    "schema_version": "0.1",
    "request_id": "stack-revision-demo",
    "current_question": question,
    "feedback": {
        "feedback_id": "stack-feedback-1",
        "question_id": question["question_id"],
        "target_version": question["version"],
        "part_id": "minimum-capacity",
        "action": "replace_output_sequence",
        "replacement_output": [1, 2, 3, 4, 5],
        "comment": "增加最小容量为 1 的对照样例。",
    },
}
(directory / "revise.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
PY
python3 -m question_generation --revise "$qodex_stack/revise.json" > "$qodex_stack/v2.json"
```

v1 目标序列为 `4、5、3、2、1`，最小容量为 4。更换目标序列后，v2 的最小容量为 1。由于两问共用目标序列，`revision.affected_parts` 列出两问，评分点及参考轨迹都重新核对。题目、小问及评分点 ID 和总分保持稳定，审校状态回到 `PENDING`。不可达序列、重复元素、未改变题设的反馈和错版反馈均返回对应失败状态。

## 通用路径：模型输出、超时与失败诊断

通用创作（`author`、`constraints.authoring`）由模型完成需求细化、创作、盲解和审计四个阶段。下列默认值是**当前代码**的取值（`question_generation/model_client.py`），按阶段覆盖时用 `QUESTION_GENERATION_<STAGE>_*`。

| 阶段 | 默认输出额度 | 默认时限 | 默认推理档 |
| --- | --- | --- | --- |
| `plan`（需求细化） | 32,768 | 240 s | `low` |
| `author`（创作/修订） | 32,768 | 600 s | `high` |
| `reader`（学生视角盲解） | 32,768 | 600 s | `low` |
| `audit`（反例审计） | 32,768 | 600 s | `low` |

- 覆盖环境变量：`QUESTION_GENERATION_<STAGE>_MAX_OUTPUT_TOKENS`、`QUESTION_GENERATION_<STAGE>_TIMEOUT_SECONDS`、`QUESTION_GENERATION_<STAGE>_REASONING_EFFORT`；客户端级输出默认仍为 16,384（`QUESTION_GENERATION_MAX_OUTPUT_TOKENS`），整条流水线另有总时限 900 s（`QUESTION_GENERATION_PIPELINE_TIMEOUT_SECONDS`）。
- 推理档只允许 `off`、`low`、`high`、`max`（服务商没有 `medium` 档）；非法档位在配置阶段直接报错。计划与盲解降档只影响延迟与成本，不改变审计结论。
- 传输：官方 `api.deepseek.com` 默认非流式（`QUESTION_GENERATION_STREAM=0`），其他兼容网关默认流式。流式下单次读取空闲超时为 90 s；连续 90 s 无数据先回退一次非流式，仍失败则以 `response_timeout` + `response_issue=idle_timeout` 结束。总时限内持续出字不会被误杀。
- 重试：仅瞬态 `transport_error` 与 HTTP 502/503/504 自动重试，最多 1 次（默认退避 1.75 s，可配 `max_retries`）；正文为空或 `content_decode` 消耗同一次重试预算。`response_timeout`、`incomplete_output`、`response_size_limit` 与审计拒绝不自动重试。原始字节流上限 16,000,000，拼接后正文上限 1,000,000 字符。

**失败诊断。** 模型调用失败返回 `MODEL_UNAVAILABLE`，`authoring_report.model_failure.stage` 标明阶段（`plan`/`author`/`reader`/`audit`）；`response_issue` 区分 `envelope_decode`、`envelope_shape`、`content_type`、`content_decode`、`content_not_object`、`idle_timeout`、`raw_stream` 等固定类别。诊断只记录类别与位置，不落响应正文、推理或截断内容。

通用路径的失败另带 `failure.code`（追加字段，不改 `status/message`），每项配 `retry` 与 `needs`，供 Pi 的护栏按类处置（见 [workflow-target.md](workflow-target.md) §3）：

| 阶段 | `failure.code` | `retry` | `needs` |
| --- | --- | --- | --- |
| 创作响应结构 | `candidate_shape` | `same_request` | — |
| 材料不足 | `material_gap` | `new_request` | `material` |
| 设计与结构检查 | `design_invalid` | `same_request` | — |
| 独立解答与质量检查 | `quality_gate` | `new_request` | — |
| 条件扰动检查不完整 | `condition_test_incomplete` | `same_request` | — |
| 独立答案分歧 | `blind_disagreement` | `new_request` | `human` |
| 独立小问解答不完整 | `blind_incomplete` | `same_request` | — |
| 反例与解析审计 | `audit_rejected` | `new_request` | `human` |

**正文解码的有限修复。** `_parse_json_content()` 按固定顺序尝试：剥掉最外层 json 代码围栏；把字符串内非法的单反斜杠（如 `\alpha`）加倍成字面反斜杠；左花括号比右花括号多 1–2 个时在末尾补齐。未闭合字符串、值错误和尾随文本仍然失败；修复成功时用量回执记 `content_repair`（`fence`/`backslash`/`brace` 及组合）。修复只处理格式滑落，不降低结构、引文、分值与见证校验。注意 `\beta`、`\times` 的第二个字符本身是合法 JSON 转义，与真实控制字符存在不可消解的歧义，程序不做猜测。

**审计放行判据。** `answer_agreement`、`ambiguity`、`grounding`、`grading`、`witness_alignment` 是硬阻断，任一失败必须 `valid=false`；`reasoning_necessity`、`requirements`、`counterfactual`、`scope` 是软指标，未通过时照常交付 `PENDING`，检查名与原因写入 `self_check.review_warnings`。9 项全过但 `issues` 非空时，每条 issue 以 `advisory_note` 写入 `review_warnings`，供审校逐条查看；`valid=false` 却没有任何软指标失败解释，视为审计契约自相矛盾并拒绝。盲解质量门禁只要求 `answerability=2`、`clarity>=1`、`distractors>=1`、`depth>=1` 且 `issues` 为空；`depth=1` 追加 `reader_depth` 警告，`depth=0` 仍硬拒。综合题评分点允许 0.5 分步长，小问分值与整题总分为整数。

以上规则只保证**内部自洽与流程可用**，不证明题目“像真题”。质量层（超纲、计算量、题型配比、图题/题组）仍未开工，见 `TASK_STATE.md` 的问题 1。
