# 与源码版本配套的模型目录

## 原因与处理

Pi源码版本为0.85.1，模型JSON为忽略提交的生成数据。原来的hydrate:model-data从供应商最新目录生成数据；随着模型删除、改名或接口分组变化，旧测试引用的模型消失，产生113项类型错误。修改业务类型为any、删除测试或排除测试都不能解决版本不一致。

本集成分支提供hydrate:model-data:release，使用同版本官方npm包的模型目录作为可重复基线：

- 固定@earendil-works/pi-ai@0.85.1，并验证整个发布归档的SHA-512完整性、包名和版本。
- 按本源码的模型数据格式验证39个提供方和生成清单，验证完成后才切换目录；原本地目录保留在outputs/model-baseline/previous-*，不删除。
- 应用本源码中已存在的Copilot GPT Responses路由规则（上游#9209），以及Fireworks原生工具引用、无签名思考和有效努力级别修复（上游#9323）。保留现有回归断言，不把测试改成接受错误结果。
- 从本机原有目录保留显式补充的deepseek-flash定义，见scripts/release-model-additions.json。用户已通过官方API和Pi实测此ID；上下文、价格等元数据沿用原缓存，不代表重新核实当日计费价格。
- 不修改自动生成的models.generated.ts、不更改依赖版本或锁文件、不连接个人API、不读写密钥。

## 初始化与恢复

在仓库根目录（包含pi-coding-agent的目录）执行：

```powershell
npm.cmd --prefix .\pi-coding-agent ci --ignore-scripts
npm.cmd --prefix .\pi-coding-agent run hydrate:model-data:release
npm.cmd --prefix .\pi-coding-agent run check
```

需要Node.js 22.19及以上、npm和tar。首次运行从npm官方仓库下载公开发布包，随后复用已验证缓存。脚本不会安装或执行发布包内代码。下载或校验失败会停止，不能当作恢复成功。

已有离线归档时，在pi-coding-agent目录运行：

```powershell
node .\scripts\restore-release-model-data.mjs --archive "归档的实际路径"
```

默认实时hydrate:model-data命令保留原有含义，但它不是本分支的可重复验收入口。重新拉取实时目录后，若再次出现源码与模型ID不匹配，应恢复发布基线，或整体升级提供方实现、模型数据和测试；不要只关闭类型约束。

该基线服务于源码兼容和离线检查，不代表其中所有历史模型今天仍可调用。真实调用前仍应检查账号可用列表。升级Pi版本后脚本会拒绝继续使用旧基线，需要重新评审归档完整性与兼容补丁。

## 验证

恢复脚本的6项离线测试，以及模型类型、提供方配置、Fireworks工具/思考兼容等针对性测试通过；npm run check通过，包括完整TypeScript检查与浏览器打包冒烟检查。完整测试数字见VALIDATION.zh-CN.md。本次未运行全量测试套件或消耗付费API。
