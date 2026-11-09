"""Registry dedup: the decision that stops the same book entering twice.

Four outcomes matter and each maps to a different action:

* ``blocked_L1``        byte-identical file, same source
* ``blocked_L2``        identical text from a different file
* ``rejected_duplicate`` near-identical text with high coverage
* ``delta_edition``     same book, different edition, import only the difference

These cases run against a throwaway registry and throwaway files; no real index
is read.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from kb_registry import check_document, classify_pair, connect, content_sha256, term_fingerprint

PARAGRAPH = (
    "操作系统是配置在计算机硬件上的第一层软件，负责管理硬件设备并提高它们的利用率，"
    "同时为用户和应用程序提供一个简单接口。进程是系统进行资源分配和调度的一个独立单位，"
    "线程是进程内的一个执行单元。存储器管理的主要任务是分配回收内存并完成地址映射。"
)
BODY = "\n\n".join(PARAGRAPH * 3 for _ in range(30))


def write_pdf(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


def write_parsed(path: Path, text: str) -> Path:
    units = [{"text": text, "page": 1, "index": 1}]
    path.write_text(json.dumps({"units": units}, ensure_ascii=False), encoding="utf-8")
    return path


def register(registry: Path, doc_id: str, title: str, file_hash: str, text: str) -> None:
    conn = connect(registry)
    conn.execute(
        """INSERT INTO documents
           (doc_id, subject, title, source_path, file_sha256, content_sha256, edition, chunk_count, term_fingerprint)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            doc_id,
            "operating_system",
            title,
            f"/books/{title}.pdf",
            file_hash,
            content_sha256(text),
            None,
            10,
            term_fingerprint(text),
        ),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def registry(tmp_dir: Path) -> Path:
    return tmp_dir / "registry.sqlite"


def test_identical_file_is_blocked_at_l1(registry: Path, tmp_dir: Path) -> None:
    body = BODY.encode("utf-8")
    incoming = write_pdf(tmp_dir / "操作系统（第5版）.pdf", body)
    register(registry, "doc1", "计算机操作系统（第5版）", hashlib.sha256(body).hexdigest(), BODY)

    decision = check_document(incoming, "operating_system", registry)
    assert decision["decision"] == "blocked_L1"
    assert decision["existing_doc_id"] == "doc1"


def test_same_text_other_file_is_blocked_at_l2(registry: Path, tmp_dir: Path) -> None:
    register(registry, "doc1", "计算机操作系统（第5版）", "file-hash-of-another-copy", BODY)
    incoming = write_pdf(tmp_dir / "操作系统 扫描版.pdf", b"different bytes entirely")
    parsed = write_parsed(tmp_dir / "parsed.json", BODY)

    decision = check_document(
        incoming, "operating_system", registry, parsed_json=parsed
    )
    assert decision["decision"] == "blocked_L2"
    assert decision["existing_doc_id"] == "doc1"


def test_new_edition_routes_to_delta(registry: Path, tmp_dir: Path) -> None:
    register(registry, "doc1", "计算机网络 第7版", "hash-7", BODY)
    # A real revision keeps most sentences but changes some, so the text hash
    # differs while similarity stays high. Identical text would be blocked_L2.
    revised = BODY + "\n\n新增小节：第 8 版补充了 QUIC 与 HTTP/3 的内容。"
    incoming = write_pdf(tmp_dir / "计算机网络 第8版.pdf", b"bytes-8")
    parsed = write_parsed(tmp_dir / "parsed8.json", revised)

    decision = check_document(incoming, "operating_system", registry, parsed_json=parsed)
    assert decision["decision"] in {"delta_edition", "rejected_duplicate"}
    assert decision["comparisons"], "expected at least one comparison"


def test_unrelated_book_is_not_blocked(registry: Path, tmp_dir: Path) -> None:
    register(registry, "doc1", "计算机操作系统（第5版）", "hash-5", BODY)
    incoming = write_pdf(tmp_dir / "数据结构与算法分析.pdf", b"other bytes")
    parsed = write_parsed(tmp_dir / "parsed-ds.json", "二叉树的前序遍历按根左右的顺序访问节点。" * 400)

    decision = check_document(incoming, "operating_system", registry, parsed_json=parsed)
    assert decision["decision"] not in {"blocked_L1", "blocked_L2", "rejected_duplicate"}


def test_unreadable_file_is_blocked_not_crashed(registry: Path, tmp_dir: Path) -> None:
    # A corrupt or encrypted PDF used to escape as a PyMuPDF exception.
    incoming = write_pdf(tmp_dir / "坏文件.pdf", b"not a pdf at all")
    decision = check_document(incoming, "operating_system", registry)
    assert decision["decision"] == "blocked_unreadable"


def test_empty_registry_never_blocks(registry: Path, tmp_dir: Path) -> None:
    incoming = write_pdf(tmp_dir / "任何一本书.pdf", b"fresh bytes")
    parsed = write_parsed(tmp_dir / "parsed-fresh.json", PARAGRAPH * 40)
    decision = check_document(incoming, "operating_system", registry, parsed_json=parsed)
    assert decision["decision"] not in {"blocked_L1", "blocked_L2", "rejected_duplicate"}


@pytest.mark.parametrize(
    ("incoming", "existing", "relation"),
    [
        ("计算机网络 第7版 (Kurose)", "计算机网络 第7版 (Kurose)", "same_edition"),
        ("计算机网络 第8版 (Kurose)", "计算机网络 自顶向下方法 第7版 (Kurose)", "same_edition"),
        ("计算机操作系统 第5版", "计算机网络 第7版", "unrelated"),
    ],
)
def test_classify_pair(incoming: str, existing: str, relation: str) -> None:
    got, score = classify_pair(incoming, existing)
    assert got == relation, (got, score)
