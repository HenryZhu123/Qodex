#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a KB-aware variant of the reviewer prompts.

The stock prompts constrain `reference` to read-only context that must never be
used to judge correctness. For the knowledge-base ablation we need the opposite:
`reference` carries retrieved textbook evidence that the reviewer SHOULD use as
the factual anchor for judging `detection_content`.

Approach: keep every stock instruction, but prepend a knowledge-base directive
to each task prompt. The directive overrides the read-only reading of
`reference` and states exactly how to use the evidence.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SRC = Path(
    r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\prompts\reviewer-prompt\qwen38_27b"
)
DST = Path(r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\prompts\kb_aware")

PREAMBLE = """# 教材证据库 (Knowledge Base Evidence)

`input_payload.reference` 字段存放从该学科权威教材检索到的**证据片段**，每条带有学科、章节路径与页码。

使用方式：
1. 先阅读 `reference` 中的教材片段，理解该题涉及的学科概念在教材中的定义、条件、公式与性质。
2. 用这些片段作为**事实依据**，判断 `detection_content` 的表述是否与教材一致。
3. 若 `detection_content` 的表述与教材片段明显冲突（方向相反、数值不符、条件缺失、概念混用），应按本任务规定的错误类型报告。
4. 若 `reference` 为空，或片段与本题无关，则按你自身的学科知识判断。
5. 仍需遵守：**不要报告 `reference` 本身的任何问题**——它只是判断依据，不是检测对象。

本指令优先于下文关于 `reference` 的其它描述。

---

"""


def main() -> int:
    if DST.exists():
        shutil.rmtree(DST)
    count = 0
    for path in sorted(SRC.rglob("*.txt")):
        rel = path.relative_to(SRC)
        target = DST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text(encoding="utf-8")
        if rel.parent.name == "tasks":
            text = PREAMBLE + text
            count += 1
        target.write_text(text, encoding="utf-8")
    print(f"prompts written: {DST}")
    print(f"task prompts prefixed: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
