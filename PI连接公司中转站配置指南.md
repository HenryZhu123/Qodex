# Pi Agent 连接公司模型中转站配置指南

本文用于在本地安装 Pi Agent，并将其连接到公司 Talkweb 模型中转站。配置完成后，Pi 默认启动 DeepSeek，同时支持随时切换到 Qwen。

> 适用中转站：`https://llm.talkweb.com.cn/v1`  
> 默认模型：`DeepSeek-V4.1-Flash`  
> 备选模型：`qwen3.8-max`

## 1. 环境要求

- Node.js 22.19 或更高版本
- npm
- 能访问公司中转站的网络环境
- 由管理员分配的有效访问凭证

检查版本：

```bash
node --version
npm --version
```

如果尚未安装 Node.js，可从 [Node.js 官网](https://nodejs.org/) 安装当前 LTS 版本。

## 2. 安装 Pi Agent

在终端执行：

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
```

验证安装：

```bash
pi --version
```

能够输出版本号即表示安装成功。

## 3. 创建模型配置

Pi 的用户级配置目录如下：

- macOS / Linux：`~/.pi/agent/`
- Windows：`%USERPROFILE%\.pi\agent\`

先创建目录：

```bash
mkdir -p ~/.pi/agent
```

在该目录中新建 `models.json`，内容如下：

```json
{
  "providers": {
    "talkweb": {
      "baseUrl": "https://llm.talkweb.com.cn/v1",
      "api": "openai-completions",
      "apiKey": "$TALKWEB_API_KEY",
      "models": [
        {
          "id": "DeepSeek-V4.1-Flash",
          "name": "Talkweb DeepSeek V4.1 Flash"
        },
        {
          "id": "qwen3.8-max",
          "name": "Talkweb Qwen 3.8 Max"
        }
      ]
    }
  }
}
```

模型 ID 区分大小写，请勿修改。

## 4. 配置访问凭证

不要将访问凭证直接写入 `models.json`，也不要提交到 Git。以下方式只在当前终端会话中生效，适合首次验证。

### macOS / Linux（zsh 或 bash）

```bash
read -s TALKWEB_API_KEY
export TALKWEB_API_KEY
echo
```

终端不会回显输入内容。关闭该终端后，环境变量自动失效。

### Windows PowerShell

```powershell
$env:TALKWEB_API_KEY = Read-Host "请输入公司访问凭证" -AsSecureString |
  ConvertFrom-SecureString -AsPlainText
```

关闭该 PowerShell 窗口后，环境变量自动失效。

### macOS 推荐：保存到系统钥匙串

如需长期使用，建议存入 macOS 钥匙串：

```bash
read -s "TALKWEB_KEY?请输入公司访问凭证: "
echo
security add-generic-password -U -a "$USER" -s talkweb-llm -w "$TALKWEB_KEY"
unset TALKWEB_KEY
```

然后将 `models.json` 中的这一行：

```json
"apiKey": "$TALKWEB_API_KEY"
```

替换为：

```json
"apiKey": "!security find-generic-password -ws 'talkweb-llm'"
```

这样 Pi 会在发起请求时从系统钥匙串读取凭证，配置文件中不会保存凭证明文。

## 5. 设置默认模型

Pi 同一时刻只能使用一个模型。本配置将 DeepSeek 设为启动默认模型，同时将 DeepSeek 和 Qwen 都加入可选模型范围。

在 `~/.pi/agent/settings.json` 中加入以下配置。如果文件已有其他设置，请合并字段，不要直接覆盖原内容。

```json
{
  "defaultProvider": "talkweb",
  "defaultModel": "DeepSeek-V4.1-Flash",
  "enabledModels": [
    "talkweb/DeepSeek-V4.1-Flash",
    "talkweb/qwen3.8-max"
  ]
}
```

此后直接运行：

```bash
pi
```

Pi 将默认使用 `DeepSeek-V4.1-Flash`。

## 6. 查看和切换模型

查看 Talkweb 模型列表：

```bash
pi --list-models talkweb
```

在 Pi 交互界面中输入：

```text
/model
```

搜索 `talkweb`，然后选择以下任一模型：

- `talkweb/DeepSeek-V4.1-Flash`
- `talkweb/qwen3.8-max`

Talkweb 是自定义中转供应商，因此不需要在 `/login` 中选择 OpenAI、DeepSeek 或 Qwen。

也可以从终端直接指定模型：

```bash
pi --provider talkweb --model DeepSeek-V4.1-Flash
```

```bash
pi --provider talkweb --model qwen3.8-max
```

## 7. 验证连接

分别执行以下命令：

```bash
pi --provider talkweb \
  --model DeepSeek-V4.1-Flash \
  --no-session --no-context-files \
  -p "只回复：CONNECTED"
```

```bash
pi --provider talkweb \
  --model qwen3.8-max \
  --no-session --no-context-files \
  -p "只回复：CONNECTED"
```

两个命令均返回 `CONNECTED`，表示模型配置、身份认证和网络连接均正常。

## 8. 常见问题

### `/model` 中没有 Talkweb 模型

依次检查：

1. `models.json` 是否位于 `~/.pi/agent/models.json`。
2. JSON 格式是否有效，模型 ID 的大小写是否正确。
3. 当前终端是否存在 `TALKWEB_API_KEY` 环境变量，或 macOS 钥匙串中是否已保存凭证。
4. 在 Pi 中重新打开 `/model`；该操作会重新加载 `models.json`。
5. 退出 Pi 后重新执行 `pi`。

### 提示 401 或 Unauthorized

访问凭证无效、已过期或未被 Pi 正确读取。请重新配置凭证，并确认账号具有对应模型的访问权限。

### 提示模型不存在

模型 ID 必须与中转站完全一致：

- `DeepSeek-V4.1-Flash`
- `qwen3.8-max`

不要自行改变大小写、空格或连字符。

### 网络连接失败

检查是否能访问：

```text
https://llm.talkweb.com.cn/v1
```

如公司网络要求 VPN、代理或内网访问，请先完成相应网络配置。

## 9. 安全要求

- 不要把访问凭证写入项目源码、文档或聊天记录。
- 不要把包含凭证的配置文件提交到 Git。
- 每位同事应使用单独分配的凭证，避免多人共用。
- 凭证疑似泄露时，应立即联系管理员停用并重新签发。
