# Windows 团队 Pi 启动记录

已验证环境（2026-10-21）：Node.js 24.20.0、npm 11.19.0、团队 Pi 0.85.1。
Node.js 使用官方 LTS 安装包，通过 Windows 包管理器安装。

团队源码当前位于相邻目录 hku-agent-exam-checker；本模块仍在 hku-agent。
已在团队源码目录运行 `npm.cmd ci --ignore-scripts --no-audit --no-fund`。
首次运行缺少模型目录数据，已按源码脚本运行：

```powershell
node packages/ai/scripts/generate-models.ts --strict --data-only
```

该步骤仅下载模型目录，不是调用公司模型，不需要密钥。
没有运行完整构建，没有全局安装另一份 Pi。

在 hku-agent 根目录验证团队 Pi：

```powershell
& ./exam_assembly_agent/run-team-pi.ps1 -PiArguments '--version'
```

应显示 `0.85.1`。不传参数可启动交互界面：

```powershell
& ./exam_assembly_agent/run-team-pi.ps1
```

脚本会检测相邻仓库及调整后的 pi-coding-agent 子目录，也可用 -PiRoot 指定仓库。
调用官方 Node 路径，退出后还原当前进程 PATH；不会保存或打印凭据。
本次仅验证版本命令；未验证模型连接，也未注册组卷工具。

新开 PowerShell 后应能运行 `node --version` 和 `npm.cmd --version`。
已通过 setup-talkweb.ps1 添加用户级模型配置，只保存环境变量引用，不保存密钥。

## 网关模型变更（2026-10-21）

按用户提供的网关实测结果，使用 gpu-deepseek-flash。
原指南的 DeepSeek-V4.1-Flash 在本账号测试时无可用通道；不要继续用旧名称测试。
已下线的 gpu-deepseek-v4-flash 也不使用。
更新已有配置可运行 update-talkweb-model.ps1；只更新 DeepSeek 条目，保留其他供应商和 Qwen。

在已设置 TALKWEB_API_KEY 的同一个 PowerShell 窗口运行：

```powershell
& ./exam_assembly_agent/run-team-pi.ps1 -PiArguments @('--provider','talkweb','--model','gpu-deepseek-flash','--no-session','--no-context-files','-p','只回复：CONNECTED')
```

该命令会发送真实模型请求。新模型的连通性需在用户终端验证；不能把旧的版本检查当作模型连接成功。

## 最小组卷扩展

本模块的 pi-extension.ts 通过 -e 显式加载，不改团队内置扩展，不复制审校功能。
工具名 exam_assembly，调用 pi_bridge.py，先使用固定开发题库。
桥接文件使用标准库，无额外 Python 依赖。真实审校数据库尚未接入。

在 hku-agent 根目录、已设置 TALKWEB_API_KEY 的同一窗口执行：

```powershell
& ./exam_assembly_agent/test-assembly-model.ps1
```

该命令发送一次真实模型任务，要求只调用 exam_assembly，并保存 JSON 事件轨迹。
outputs/pi_model_checks 下的新目录含 summary.json 和 trace.jsonl。
summary.passed 仅在观察到一次工具执行完成、无工具错误并返回 STRUCTURAL_PASS 时为 true。
单纯模型声称“组卷成功”不能通过检查。模型调用次数及费用由网关计费，未在此估算。
实际试卷、答案和结构检查报告保存在 outputs/pi_runs 下的唯一目录，工具返回其绝对路径。
没有注册自动补题、语义判断或会话恢复能力；模型必须如实转述缺题和未完成状态。

启动带组卷扩展的交互 Pi：

```powershell
& ./exam_assembly_agent/run-assembly-pi.ps1 -PiArguments @('--provider','talkweb','--model','gpu-deepseek-flash')
```

可通过 -Python 指定实际 Python 可执行文件，默认使用当前终端 python。
模块须在自己的开发分支提交后再与团队目录布局整合。

### Windows PowerShell 参数修复

旧测试将中文 JSON 作为原生命令行参数传递，Windows PowerShell 5 下会丢失引号、截断及产生乱码。
run-team-pi.ps1 现在先写入 UTF-8 参数文件，由 pi-launcher.mjs 读取并以 shell=false 启动 Pi，随后清理临时参数文件。
test-assembly-model.ps1 显式按 UTF-8 读取要求，显示启动、模型响应和工具执行阶段，并设置 180 秒整次测试超时。
启动等待不再等同于无限等待；查看新运行目录的 trace.jsonl 和 summary.json 判断实际结果。
使用假 Pi 的 test-launcher.mjs 已验证 Windows PowerShell 5 下中文、JSON 引号、换行和空格保持完整，不使用模型密钥。
