# Pi 真实题库组卷验收记录

日期：2026-11-08。范围为本地开发集成验证，不是教学质量评估或生产部署验收。

## 已验证行为

1. 个人DeepSeek模型列表检查通过；本地PostgreSQL迁移、审校后端8091启动成功。
2. 从用户提供的试卷准备3道无图文字节选，按原文核对题干、选项和参考答案。首轮MinerU轮询300秒超时，没有进入审校或入库。
3. 显式启用纯文字PDF读取后发现选项对象被字符串化的问题；修复对象到文本转换，并限制选项必须有明确标签和文本。不凭位置补造缺失标签。明确单项选择题统一为single_choice；共享材料不混入卷头说明。
4. 修复后重新解析，恰好3题。题干、四选项、答案、每题2分、single_choice和数据结构学科均与来源核对一致。
5. 真实审校3题全部PASS，错误和unresolved_checks为空；服务自动入库3条STORED，并通过状态与记录接口回读确认。不直接写SQL、不伪造PASS、不自动修订题面。
6. 组卷后端从真实题库接口查询，核对当前审校、内容与来源版本，生成3题6分试卷。
7. 用户启动当前源码Pi，以个人DeepSeek调用内置exam_assembly，request_id为pi-real-bank-3q。返回POSTGRES_QUESTION_BANK_API、STRUCTURAL_PASS、uses_mock_reviews=false和validation.passed=true。
8. 文件内容核对：学生HTML题面和ABCD选项完整，无答案；独立答案HTML依次为A、C、B。答案解析未提供，没有补造解析。
9. 模型目录类型问题修复后，用户重新启动Pi再次测试，request_id为pi-post-typefix-3q。已回读新生成的report.json和两份HTML：STRUCTURAL_PASS、POSTGRES_QUESTION_BANK_API、uses_mock_reviews=false、validation.passed=true，仍为同一批真实入库题的当前版本；3题6分、知识点/难度配额正确，学生卷无答案，答案卷A、C、B对应正确。该次输出目录为70f0b667276547aba5a8074b8113c564，仅保存在本机outputs，不随Git提交。

本次配额：线性表顺序存储1题、二叉树遍历1题、森林与二叉树的转换1题；easy 1题、medium 2题、hard 0题。难度和知识点来自本轮模型标注，未经学生作答数据校准。

## 检查与限制

- 提交整理时重新运行：组卷核心、HTTP服务和解析/接口共95项Python测试通过；Pi组卷与审校扩展22项测试通过。Python测试另有1条现有Starlette/httpx弃用警告。相关测试不调用真实模型或真实数据库。
- 原113项packages/ai模型类型错误已清零。模型生成数据固定为同版本官方发布基线，应用源码已存在的Copilot/Fireworks兼容修复，显式保留实测deepseek-flash。npm run check通过，包含TypeScript与浏览器冒烟检查；依赖版本和锁文件不变，没有删除测试或使用any放宽约束。
- 恢复脚本6项测试通过；模型目录、兼容性及DeepSeek名称保留109项针对性测试通过。可重复初始化命令与限制见MODEL_CATALOG.zh-CN.md。上述通过不代表已运行全量测试或完成全部生产验收。
- 相似性仅进行字面筛查和显式人工题对决策；本卷3对均无字面标记，不认证完整语义唯一性或跨题提示检测。
- 目前正式输出只支持四选项单选题、整数单题分值、无共享材料的完整题面。复杂图片、共享材料、混合题型和大规模题库查询不在本次验收内。
- 当前结果验证本机实例。GitHub上传代码不会同步PostgreSQL数据，也不会自动启动服务。

## 提交范围

提交Pi内置扩展、组卷核心与HTTP服务、解析修复、启动脚本、针对性测试、开发示例和接口文档。开发JSON保留显式mock标记，与正式题库入口分开。

不提交密钥、.env、原始试卷PDF、真实试题转录文件、数据库卷或备份、node_modules、虚拟环境、运行HTML/JSON报告和本机测试依赖。验收产物保存在本机outputs目录，默认忽略。
