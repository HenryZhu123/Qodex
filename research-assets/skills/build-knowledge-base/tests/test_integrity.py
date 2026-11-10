"""Integrity gate: the sample must be large enough and the verdict must reflect
the damage.

The gate is what stops OCR garbage from becoming a knowledge base, so its
verdicts are exercised on real failure shapes rather than trusted.

Note on fixtures: a page needs realistic text density. One short line per page
trips the "low average text density" warning and is not the failure we want to
observe here.
"""

from __future__ import annotations

from integrity import check_integrity, sample_contiguous

SENTENCE = (
    "操作系统是配置在计算机硬件上的第一层软件，负责管理硬件设备、提高利用率，"
    "并为用户和应用程序提供简单接口。进程是系统进行资源分配和调度的一个独立单位。"
)


def page(index: int) -> str:
    return f"第{index}页　{SENTENCE * 3}"


CLEAN = "\n".join(page(i) for i in range(1, 21))
MOJIBAKE = "\n".join(
    "锟斤拷锟斤拷 系统 锟斤拷 硬件 锟斤拷锟斤拷 设备 锟斤拷 进程 " * 4 for _ in range(20)
)
GARBLED = "\n".join(("\ufffd\ufffd\ufffd 系统 " + "\ufffd\ufffd 硬件 " * 10) for _ in range(20))


def units_from(text: str) -> list[dict]:
    return [{"text": line, "page": index, "index": index} for index, line in enumerate(text.splitlines(), 1)]


def doc_for(text: str) -> dict:
    return {"doc_id": "d1", "text": text, "unit_type": "page", "title": "测试"}


def test_sample_respects_minimum_units() -> None:
    sample = sample_contiguous(units_from(CLEAN), "page", ratio=0.01, min_units=5)
    assert sample["sample_units"] >= 5


def test_sample_window_is_contiguous() -> None:
    sample = sample_contiguous(units_from(CLEAN), "page", ratio=0.25, min_units=2)
    for window in sample["windows"]:
        span = window["end_index"] - window["start_index"] + 1
        assert span == window["unit_count"]


def test_clean_text_passes() -> None:
    sample = sample_contiguous(units_from(CLEAN), "page", ratio=0.5, min_units=5)
    report = check_integrity(sample, doc_for(CLEAN))
    assert report["verdict"] == "pass", report["reasons"]
    assert report["metrics"]["replacement_ratio"] == 0
    assert report["metrics"]["page_density"] > 100


def test_replacement_characters_fail() -> None:
    sample = sample_contiguous(units_from(GARBLED), "page", ratio=0.5, min_units=5)
    report = check_integrity(sample, doc_for(GARBLED))
    assert report["verdict"] == "fail"
    assert report["metrics"]["replacement_chars"] > 0


def test_mojibake_is_flagged() -> None:
    sample = sample_contiguous(units_from(MOJIBAKE), "page", ratio=0.5, min_units=5)
    report = check_integrity(sample, doc_for(MOJIBAKE))
    assert report["metrics"]["mojibake_hits"] >= 5
    assert report["verdict"] == "fail"


def test_low_density_warns_without_failing() -> None:
    thin = "\n".join(f"第{i}页 短句。" for i in range(1, 21))
    sample = sample_contiguous(units_from(thin), "page", ratio=0.5, min_units=5)
    report = check_integrity(sample, doc_for(thin))
    assert report["verdict"] == "warn"
    assert any("density" in reason for reason in report["reasons"])


def test_empty_sample_fails() -> None:
    report = check_integrity({"text": "", "sample_units": 0, "windows": []}, doc_for(""))
    assert report["verdict"] == "fail"
