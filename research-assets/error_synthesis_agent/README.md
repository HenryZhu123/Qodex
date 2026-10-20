# 造错 Agent

轻量级 CLI，用 OpenAI 兼容接口对试题生成指定类型的错误样本。支持 Excel / 单道题输入、并发、Markdown 提示词库和专项要求注入。

## 输入

支持两种输入方式：

1. Excel：至少具有题型列（`title`、`题型` 等）和题目列（`content`、`题目`、`题干` 等）。可用 `--title-column`、`--content-column` 明确指定列名。
2. 单道题：命令行传入 `--title` 和 `--content`。

Excel 可包含可选的 `reference`、`generation_instruction` 列；后者会覆盖命令行的全局专项要求。

## 运行

```powershell
cd D:\hyt-agent\error_synthesis_agent

$env:OPENAI_API_KEY = "你的密钥"
python .\synthesize.py `
  --excel "D:\data\questions.xlsx" `
  --output .\out\typo.jsonl `
  --error-type "错别字" `
  --base-url "http://服务器地址:端口/v1" `
  --model "deepseek-v4-pro" `
  --concurrency 8 `
  --generation-instruction "仅使用中文形近字或同音字；不得造英文缩写错误。"
```

单道题示例：

```powershell
python .\synthesize.py `
  --title "单项选择题" `
  --content "下列关于细胞膜的叙述，正确的是（ ）。\nA. 细胞膜具有选择透过性\nB. 细胞膜完全由蛋白质构成" `
  --error-type "错别字" `
  --generation-instruction "仅造一个专业术语形近字错误" `
  --output .\out\one.jsonl `
  --base-url "http://服务器地址:端口/v1" `
  --model "deepseek-v4-pro"
```

`--base-url` 也可传完整的 `/chat/completions` 地址。默认请求：`{base-url}/chat/completions`。

## 输出字段

每一行输出为：

```json
{
  "error_type": "答案泄露",
  "error_detailed_type": "真实二级错误类型",
  "design_rationale": "一句话说明错误类型、错误数量和修改位置，不得出现构造过程痕迹。",
  "correction": "原文：A -> 错误：B",
  "error_content": "注入错误后的完整题目文本",
  "error_cnt": 1
}
```

失败记录会被写到输出 JSONL，并附带 `_status: "failed"` 与 `_error`，便于重跑筛选。

## 支持的错误类型

`错别字`、`语义不清`、`选项结构错误`、`标点符号错误`、`题目与题型不一致`、`信息缺失`、`题目无解`、`答案泄露`。

每个错误类型对应 `prompts/` 内一个 Markdown 文件。需要调整某类规则时，只修改对应 `.md` 文件；新增类型时，同时在 `prompt_library.py` 的 `PROMPT_FILES` 添加映射即可。
