# 组卷历史：数据库迁移、接口与验收

本功能由提交 `3268bf6c` 合入 main，保存每次组卷的结果快照。它没有新建或替换 `question_bank`，不会修改正式题目和审校结果。

## 数据表

- `assembled_exams`：exam_id（每次执行独立UUID）、创建时间、request_id、学科、状态、完整需求JSON、教师用报告JSON、学生HTML和答案HTML快照。
- `assembled_exam_items`：exam_id、顺序号、来源记录和版本JSON、学生题面JSON、答案JSON。复合主键为exam_id和position。

历史保存题目内容与答案，不在查询时重新读取最新题库。来源JSON仅用于追溯，刻意不外键绑定question_bank，以免以后题库清理破坏历史。历史接口不提供更新或删除操作。

需求JSON保存请求题数和总分；验证报告保存实际题数/分值检查结果。失败尝试的请求题数不代表已生成相同数量的题目。request_id不是幂等键：重复组卷是不同历史记录，不能在超时后自动反复提交。

## 迁移与配置

统一使用exam-checker已有Alembic链，新版本为20261111_01，前一版本为20261017_01。迁移随代码提交，队友仍需要在自己的数据库执行，不会随Git自动同步真实历史数据。

```powershell
# 从仓库根目录，先激活安装了审校和组卷依赖的Python环境
python -m pip install -e . -e .\pi-coding-agent\services\exam-assembly
$env:EXAM_CHECKER_DATABASE_URL = 'postgresql+asyncpg://qodex:qodex-local@127.0.0.1:5433/qodex'
$env:PYTHONPATH = (Resolve-Path '.\pi-coding-agent\services\exam-checker\src').Path
Push-Location .\pi-coding-agent\services\exam-checker
python -m alembic upgrade head
Pop-Location

$env:EXAM_ASSEMBLY_DATABASE_URL = $env:EXAM_CHECKER_DATABASE_URL
$env:PYTHONPATH = (Get-Location).Path + ';' + (Resolve-Path '.\pi-coding-agent\services\exam-assembly\src').Path
python -m uvicorn exam_assembly_service.app:app --host 127.0.0.1 --port 8092
```

连接示例只适用于团队默认本机开发实例；自定义密码/地址应使用自己的环境配置，不提交真实凭据。正式题库后端8091也需要启动，才能进行新的组卷；查询已保存历史不依赖8091。

支持`EXAM_ASSEMBLY_DATABASE_URL`，缺省使用`EXAM_CHECKER_DATABASE_URL`，接受postgresql://和postgresql+asyncpg://。两者均未设置时保留原有文件组卷模式，但health明确返回history_enabled=false，成功组卷返回history.status=DISABLED，历史接口返回503。配置了数据库但迁移未应用时启动失败，不临时自动建表。

统一演示scripts/demo.sh已传递该数据库配置；原有demo:db会自动应用这条Alembic迁移。更新代码后需重启8092，已启动的旧进程不会自动获得新接口。

## 接口

| 方法与路径（前缀 /v1/exam-assembly） | 用途 |
| --- | --- |
| POST /assemble | 原组卷接口；启用历史后额外返回history.status、exam_id、created_at |
| GET /history?limit=20&offset=0 | 按创建时间和exam_id倒序分页；limit为1到100 |
| GET /history/{exam_id} | 需求、状态、验证/错误/缺口、当次学生题面与来源；不返回答案或原始教师报告 |
| GET /history/{exam_id}/answers | 独立返回教师答案JSON |
| GET /history/{exam_id}/student.html | 从数据库读取学生HTML，原输出目录被清理后仍可使用 |
| GET /history/{exam_id}/answer.html | 独立读取教师答案HTML |

不存在的UUID返回404，非法UUID返回422。缺题/无完整试卷记录下载HTML返回409。列表中的requested_question_count和requested_total_score是请求值，状态需一并查看。

每次正常返回的成功、缺题、待复核、业务配额错误以及上游/导出失败都尽可能追加历史。请求JSON不符合结构校验的HTTP422、未捕获异常或进程被强制结束不保证有记录。保存父记录与全部题目明细是一个事务；写入失败返回503/HISTORY_SAVE_FAILED，不将未保存报告为STORED，已生成的本地文件可能保留。

查询与下载不重新组卷、不调用大模型。当前仍是本机教师开发服务，无登录和身份鉴权；分离答案接口只是数据边界，不是权限系统。不要公开暴露端口或将教师接口当作学生入口。

## 前端对接

现有Pi组卷调用自动获得新增history字段。此版本增加后端接口，没有修改网页布局、没有新增Pi历史工具。前端可使用history列表与exam_id详情接口实现“组卷历史”；使用独立答案接口展示教师答案，不把原始报告发给学生。

## 本地验收

- 组卷核心和服务共77项测试通过（包含隔离PostgreSQL测试），覆盖历史保存、答案隔离、源题改变后快照不变、本地文件清理后下载、分页校验、未知ID、失败记录和存储失败。测试另有原有Starlette/httpx弃用警告，不影响本轮结果。
- 独立5545 PostgreSQL数据库中执行完整迁移，并核对Alembic metadata无差异；验证真实SQL写入、主子表事务回滚、历史查询下载，原question_bank仍为空。
- 本机5433 qodex已应用新增迁移，使用原有三道真实PASS/STORED题目生成一条三题六分历史，exam_id为f0f088e6-7b46-4dc2-a458-853f91d4f062。重启测试服务后可查询和下载；四张原文档/题目版本/审校/正式题库表逐项哈希与数量完全未变。
- 本次不调用付费模型。运行证据在本机.local/history-live，默认不提交。未完成网页按钮和多用户权限验收。
- 原功能分支验收时最新整合版 `npm run check` 通过；合入 main 后仍应按仓库根目录 `AGENTS.md` 运行对应检查。
