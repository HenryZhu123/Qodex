"""从 prompts 目录加载指定错误类型的 Markdown 提示词。"""
from pathlib import Path

PROMPT_DIR = Path(__file__).with_name("prompts")
PROMPT_FILES = {
    "错别字": "错别字.md", "语义不清": "语义不清.md", "选项结构错误": "选项结构错误.md",
    "标点符号错误": "标点符号错误.md", "题目与题型不一致": "题目与题型不一致.md",
    "信息缺失": "信息缺失.md", "题目无解": "题目无解.md", "答案泄露": "答案泄露.md",
}

OUTPUT_SCHEMA = """
输出必须严格是下列字段的 JSON 对象，字段不得缺失：
{{
  "error_type": "{error_type}",
  "error_detailed_type": "真实二级错误类型",
  "design_rationale": "一句话说明错误类型、错误数量和修改位置，不得出现构造过程痕迹。",
  "correction": "原文：A -> 错误：B",
  "error_content": "注入错误后的完整题目文本",
  "error_cnt": 1
}}
error_type 必须严格等于 "{error_type}"；error_cnt 必须是正整数；correction 必须只描述实际改动。
""".strip()


def load_type_prompt(error_type: str, detailed_type: str = "") -> str:
    if detailed_type:
        specialized = PROMPT_DIR / error_type / f"{detailed_type}.md"
        if specialized.is_file():
            return specialized.read_text(encoding="utf-8").strip()
    try:
        path = PROMPT_DIR / PROMPT_FILES[error_type]
    except KeyError as exc:
        raise ValueError(f"不支持的错误类型：{error_type}；可用类型：{'、'.join(PROMPT_FILES)}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"未找到提示词文件：{path}")
    return path.read_text(encoding="utf-8").strip()


def build_prompt(error_type: str, title: str, content: str, generation_instruction: str = "", reference: str = "", detailed_type: str = "") -> str:
    special = generation_instruction.strip() or "无"
    reference_part = f"\n参考信息：\n{reference.strip()}" if reference and reference.strip() else ""
    return f"""{load_type_prompt(error_type, detailed_type)}

本次唯一目标错误类型：{error_type}
专项要求是硬约束，优先级高于本提示词其余规则：{special}
若专项要求指定了二级错误类型，只能生成该二级类型；不得改用其他语义错误类型。不能满足时只输出 {{"skip": true}}。

题型：{title.strip()}
正确试题原文：
{content.strip()}{reference_part}

{OUTPUT_SCHEMA.format(error_type=error_type)}"""
