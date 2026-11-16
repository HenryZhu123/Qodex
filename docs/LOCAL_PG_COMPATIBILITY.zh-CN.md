# 本机 PostgreSQL 与团队格式对齐

## 约定

以本地基线 `origin/main 9e64c8b` 中的数据库模型、Alembic迁移与题库接口为准。使用既有 `question_bank`、`question_snapshots`、`question_reviews`、`assembled_exams`、`assembled_exam_items`，不新建私有题库结构。

- 来源身份：`task_id + question_id + version`。
- `question_bank.record_id` 是银行记录身份；学生试卷的 `question_id` 使用该record_id，原来源身份放在 `selected_sources`。
- 题库快照字段：`question_json.task_id/question_id/version/review_status/question/metadata`。
- 学科沿用题库中文名称；题型为 `single_choice` 或结构化 `comprehensive`；分值读取原题 `points`。
- 当前PASS、版本和题目内容必须一致；不从JSON样例复制PASS进入正式题库。
- 综合题的 `student_stem/parts/grading` 是本轮已实现的增量契约，整合时需一同合并审校导入适配器和组卷服务；仅有旧版表结构并不意味着旧综合题自动具备评分数据。
- 组卷通过 `GET /v1/question-bank/search` 与任务state接口读题，不直接写题库；历史通过现有组卷历史表保存。
- 将来换成团队实例只切服务地址和数据库连接配置；数据格式不另做分支。

## 本机已完成（2026-11-16）

1. 原数据库 `qodex` 先导出完整备份，在独立副本 `qodex_assembly_compat_20261116` 恢复并演练。
2. 应用团队20261115迁移及本轮 `20261116_01_legacy_snapshot_payloads.py`。后者只转换历史JSON身份键，不增加表或业务列，也不改变题面、答案、分值、审校结论。
3. 逐题核对原内容、元数据和来源审校ID，副本还核对了全部历史版本和审校结果。
4. 演练通过后再次备份，并升级原本机 `qodex`；保留全部5道题。
5. 按团队SQL顺序应用 `001_pending_questions.sql`、`002_generation_tasks.sql`，补齐命题任务表、待审任务身份与关联约束；本地启动脚本已同步相同顺序。
6. 通过真实PostgreSQL和正常FastAPI路由完成三题组卷、答案与HTML读取、数据库历史保存、六题缺题与禁止残缺卷下载。组卷前后题库指纹一致，付费模型调用为0。

初次对齐时保留5道数据结构2分单选。随后经用户单独授权的小批量真题测试，新增2道计算机网络2分单选：实际解析、审校PASS、正式入库与双题组卷均通过。该轮使用22次模型请求，未超过授权的30次上限；未测试扫描件OCR。

后续综合题整理测试新增1道数据结构综合题（10分，四小问2/2/2/4），当前共8条正式题库记录：7道单选、1道综合。该题是用户明确批准的措辞规范化测试副本；原稿及未通过的审校记录保留。参考答案和分值未改变，评分仅保留整小问分值，不宣称为官方细分评分标准。真实审校PASS并入库后，已完成2单选＋1综合、总分14分的真实PostgreSQL混合组卷与历史保存。尚无操作系统或计算机组成原理题。

结构化文档的QuestionNode现可保存parts/grading，normalizer与QuestionService保留该数据并将全部小问题面送审，教师答案仍独立保存。此轮人工整理入库不代表原始扫描PDF的综合题自动解析已完整验证。

## 验证材料与备份

全部位于被Git忽略的 `.local/pg-compat-20261116/`，不随代码推送：

- `qodex-before-task-migration-*.dump`：首次完整备份，已实际恢复到演练库。
- `qodex-immediate-backup-*.dump`：升级原实例前的再次备份。
- `original-upgrade.json`：备份路径、SHA256、升级版本与题数。
- `verification.json`：副本接口联调与历史内容保留核对。
- `current-db-verification.json`：原本机数据库接口联调结果及试卷路径。
- `team-bootstrap.json`：团队命题表和任务关联检查。

补充迁移包含拒绝冲突来源身份的检查；发生冲突时事务回滚，不静默改成另一个任务。真实PostgreSQL回归在演练库的事务临时表中验证内容保留、幂等与三类冲突拒绝，不污染正式题库。

## 网页测试

在本项目根目录启动：

```powershell
& .\scripts\start-local.ps1
```

访问终端给出的本机网页（默认端口3000）。进入组卷历史，可查看名称以“本机真实题库组卷联调”开头的3题成功记录及缺题记录；也可重新配置少量单选试卷。

不要运行旧目录 `postgres-integration` 中的旧版审校服务连接这个已升级的数据库。旧版本接口不同；如确有需要，使用备份恢复到另一个实例。

接入团队题库时，核对双方提交版本、迁移版本、题库查询样本以及至少一条当前state响应；尤其确认综合题的完整小问和评分契约已合并。代码与迁移上传到个人分支后由队友整合，数据备份、密钥及本机配置不提交。
