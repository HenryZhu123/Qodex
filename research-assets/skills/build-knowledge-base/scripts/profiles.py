"""Language profiles: the typography assumptions that must not be hardcoded.

Chinese and English textbooks differ in ways that silently change behaviour:

* Chinese sentences end with 。；！？, English ones with . ; ! ?
* A Chinese heading is readable at 48 characters; an English one often needs 90
* English chapters use Chapter / Part / Section, Chinese ones 第N章 / 一、/（一）

Getting the first one wrong is the dangerous case: `is_stub` treats a chunk under
120 characters without sentence punctuation as a fragment and leaves it out of the
index, so an English book would lose most of its short paragraphs without a word
of warning.

Only typography lives here. Domain packs (chemistry formulas, Latin binomials)
belong elsewhere and must not change how text is split or indexed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Punctuation that marks a real sentence. Chinese profiles include the ASCII marks
# too: Chinese textbooks quote English definitions, and those are content.
ZH_SENTENCE = re.compile(r"[。；！？;!?]")
# A full stop only ends a sentence after a word, not inside "Figure 3.2" or "1.2".
EN_SENTENCE = re.compile(r"[;!?]|(?<=[A-Za-z0-9)])\.(?=\s|$)")

# A heading must not read like a sentence.
ZH_BODY_PUNCT = re.compile(r"[。；！？，：]")
EN_BODY_PUNCT = re.compile(r"[;!?]")

ROMAN = r"[IVXLC]+"
NUMBERED = r"[0-9]+(?:\.[0-9]+)*"

ZH_HEADING = re.compile(
    r"^(?:"
    r"第\s*[0-9一二三四五六七八九十百千]+\s*[章节篇]"
    r"|#{1,6}\s+\S"
    r"|" + NUMBERED + r"\s+\S"
    r"|[一二三四五六七八九十]+\s*[、.．]"
    r"|（[一二三四五六七八九十]+）"
    r")",
    re.IGNORECASE,
)

EN_HEADING = re.compile(
    r"^(?:"
    r"Chapter\s+[0-9]+"
    r"|Part\s+(?:[0-9]+|" + ROMAN + r")\b"
    r"|Section\s+" + NUMBERED + r"\b"
    r"|Appendix\s+[A-Z0-9]"
    r"|#{1,6}\s+\S"
    r"|" + NUMBERED + r"\s+\S"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Profile:
    code: str
    sentence_punct: re.Pattern[str]
    body_punct: re.Pattern[str]
    heading: re.Pattern[str]
    title_max_chars: int
    overlap_chars: int
    extra_heading: re.Pattern[str] | None = field(default=None)

    def is_heading(self, line: str) -> bool:
        return bool(self.heading.match(line) or (self.extra_heading and self.extra_heading.match(line)))

    def ends_like_sentence(self, line: str) -> bool:
        """True when a line closes a sentence rather than naming a section."""
        s = line.rstrip()
        if self.body_punct.search(s):
            return True
        # "Introduction." is prose; "1.2 Introduction" is a heading.
        if self.code in {"en", "mixed"} and re.search(r"[A-Za-z0-9)][.]$", s):
            return True
        return False

    def title_shape_ok(self, text: str) -> bool:
        s = text.strip()
        if not s or len(s) > self.title_max_chars:
            return False
        if self.body_punct.search(s):
            return False
        if self.code in {"en", "mixed"} and re.search(r"[A-Za-z][.]$", s):
            return False
        return True


ZH = Profile(
    code="zh",
    sentence_punct=ZH_SENTENCE,
    body_punct=ZH_BODY_PUNCT,
    heading=ZH_HEADING,
    title_max_chars=48,
    overlap_chars=100,
)

EN = Profile(
    code="en",
    sentence_punct=EN_SENTENCE,
    body_punct=EN_BODY_PUNCT,
    heading=EN_HEADING,
    # English titles need roughly twice the characters for the same information.
    title_max_chars=90,
    overlap_chars=150,
)

# Mixed documents are Chinese books that quote English: Chinese typography plus the
# ASCII sentence marks, which ZH_SENTENCE already covers.
MIXED = Profile(
    code="mixed",
    sentence_punct=ZH_SENTENCE,
    body_punct=ZH_BODY_PUNCT,
    heading=ZH_HEADING,
    title_max_chars=72,
    overlap_chars=120,
    extra_heading=EN_HEADING,
)

PROFILES = {"zh": ZH, "en": EN, "mixed": MIXED}


def get_profile(language: str | None) -> Profile:
    return PROFILES.get((language or "zh").lower(), ZH)
