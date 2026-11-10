# 本版代码提交步骤

由用户在PowerShell逐步执行。本文不会自动提交或推送。运行中的8091、8092和Pi窗口可保持开启，另开一个普通PowerShell操作。

## 1. 确认目录和分支

```powershell
cd "C:\Users\4jzha\Desktop\7608llm\hku-agent\postgres-integration"
git branch --show-current
git status --short
```

分支应为 `codex/exam-assembly-postgres`。不要在旧的github-upload目录执行本次提交，也不要切换到main。如果显示其他分支，先停止并核对。

本分支以已核对的main为基础，暂时只在本地整理和测试。按用户选择，最终将它合入原exam-assembly分支，并只推送exam-assembly，不在GitHub新增集成分支。原有mock代码保留作开发演示，正式组卷入口位于Pi内置扩展。

## 2. 暂存这版明确涉及的路径

下面每行是一条完整命令，分别执行；不要改成git add .或git add -A。

```powershell
git add -- .gitignore package.json package-lock.json pyproject.toml scripts/demo.sh scripts/demo-setup.sh scripts/start-question-generation.sh scripts/start-exam-assembly.sh docs/ASSEMBLY_CONTRACT.zh-CN.md docs/POSTGRES_INTEGRATION.zh-CN.md docs/SIMILARITY_REVIEW.zh-CN.md docs/VALIDATION.zh-CN.md docs/MODEL_CATALOG.zh-CN.md docs/GITHUB_SUBMISSION.zh-CN.md
git add --sparse -- exam_assembly_agent/
git add -- pi-coding-agent/package.json pi-coding-agent/scripts/release-model-additions.json pi-coding-agent/scripts/restore-release-model-data.mjs pi-coding-agent/scripts/restore-release-model-data.test.mjs pi-coding-agent/packages/ai/test/release-deepseek-model.test.ts
git add -- pi-coding-agent/packages/coding-agent/src/extensions/index.ts pi-coding-agent/packages/coding-agent/src/extensions/exam-assembly/ pi-coding-agent/packages/coding-agent/test/exam-assembly-extension.test.ts
git add -- pi-coding-agent/services/exam-assembly/ pi-coding-agent/services/exam-checker/src/exam_checker/api/app.py pi-coding-agent/services/exam-checker/src/exam_checker/config.py pi-coding-agent/services/exam-checker/src/exam_checker/parsing/normalizer.py pi-coding-agent/services/exam-checker/src/exam_checker/parsing/structure_extractor.py pi-coding-agent/services/exam-checker/src/exam_checker/services/document_parse_service.py pi-coding-agent/services/exam-checker/tests/test_document_parse_service.py pi-coding-agent/services/exam-checker/tests/test_option_normalization.py
```

LF/CRLF转换提示不是提交失败。若出现fatal或error，停止后续操作并保留错误信息。

当前工作目录启用了sparse-checkout，检出规则只有pi-coding-agent。组卷核心位于规则以外，因此需要上述--sparse参数才能暂存。该参数不会关闭忽略规则，outputs、缓存和.env仍不提交。完整暂存范围预计为91个文件；若只有40个，说明组卷核心尚未进入暂存区。

## 3. 核对暂存内容

```powershell
git diff --cached --check
git --no-pager diff --cached --stat
git status --short
```

第一条命令无输出通常代表空白格式检查通过。应看到代码、测试、启动脚本和文档。不得包含.env、API Key、outputs、node_modules、虚拟环境、原始试卷PDF或数据库备份。不要上传运行报告给学生，报告可能含答案。

本轮已完成npm run check；Python相关95项、Pi扩展22项、模型目录/兼容性109项和恢复脚本6项离线测试通过。完整检查不等于全量测试或生产质量验收。

## 4. 创建本地提交

```powershell
git commit -m "feat(coding-agent): integrate PostgreSQL exam assembly and reproducible model data"
```

应显示本地提交编号和文件变更统计。若检查钩子拒绝提交，不使用--no-verify，先查看报错。

## 5. 合入原来的exam-assembly分支

上一步本地提交成功后，确认原工作目录没有其他未提交改动：

```powershell
git -C ..\github-upload status --short
git -C ..\github-upload branch --show-current
```

第一条应无输出，第二条应为exam-assembly。否则停止并核对，不丢弃其他改动。原分支与当前分支有各自的历史，因此先正常合并，不使用强制推送：

```powershell
git -C ..\github-upload merge --no-edit codex/exam-assembly-postgres
```

如果出现CONFLICT，停止，不继续push；把冲突信息提供给协作者逐项处理。不要使用-X theirs、--no-verify或强制推送跳过核对。合并成功后核对结果并推送原分支：

```powershell
git -C ..\github-upload status
git -C ..\github-upload push -u origin exam-assembly
```

如果提示登录GitHub，按Git凭据管理器的浏览器流程登录有仓库写权限的账号。不要向聊天发送GitHub密码或Token。认证失败就停下排查，不强制推送。

## 6. 确认本地与远程同步

```powershell
git -C ..\github-upload status
git -C ..\github-upload log -1 --oneline
```

预期working tree clean，且exam-assembly与origin/exam-assembly同步。然后在GitHub选择原exam-assembly分支，查看最新提交与Pi扩展目录。不要执行推送codex/exam-assembly-postgres的命令。

本次只保存开发分支，暂不合并main或点击Merge。PostgreSQL里的真实题目不会随Git自动上传；同学可按接入文档创建自己的实例并入库。
