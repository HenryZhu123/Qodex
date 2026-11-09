"""Load rule evidence from reviewed, content-pinned knowledge-base chunks."""

from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from .generation import SCHEMA_VERSION, failure_result

SUBJECT_DIRS = {
    "operating_systems": "operating_system",
    "data_structures": "data_structure",
    "computer_organization": "computer_organization",
    "computer_networks": "computer_network",
}
TEXT_FIELDS = (
    "subject", "topic", "database", "doc_id", "chunk_id", "source", "edition", "source_sha256", "content_sha256",
    "summary",
)
REQUIRED_ENTRY_FIELDS = {*TEXT_FIELDS, "rules"}


class KnowledgeUnavailable(Exception):
    pass


class KnowledgeEvidence:
    def __init__(self, root: Path, catalog: Path):
        self.root = root.resolve()
        try:
            value = json.loads(catalog.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("Cannot read the question-generation knowledge catalog") from error
        if (
            not isinstance(value, dict)
            or value.keys() != {"schema_version", "entries"}
            or value["schema_version"] != SCHEMA_VERSION
            or not isinstance(value["entries"], list)
        ):
            raise ValueError("Invalid question-generation knowledge catalog")
        self.entries = {}
        seen = set()
        for entry in value["entries"]:
            if (
                not isinstance(entry, dict)
                or not REQUIRED_ENTRY_FIELDS <= entry.keys()
                or entry.keys() - REQUIRED_ENTRY_FIELDS - {"section"}
                or not all(isinstance(entry[key], str) and entry[key].strip() for key in TEXT_FIELDS)
            ):
                raise ValueError("Invalid knowledge catalog entry")
            if "section" in entry and (not isinstance(entry["section"], str) or not entry["section"].strip()):
                raise ValueError("Knowledge catalog section must be nonempty text")
            if entry["subject"] not in SUBJECT_DIRS or not re.fullmatch(r"kb(?:_[^/\\]+)?\.sqlite", entry["database"]):
                raise ValueError("Invalid subject or database in knowledge catalog")
            if not all(re.fullmatch(r"[0-9a-f]{64}", entry[field]) for field in ("source_sha256", "content_sha256")):
                raise ValueError("Knowledge catalog hashes must be lowercase SHA-256")
            rules = entry["rules"]
            if not isinstance(rules, list) or not rules or not all(
                isinstance(rule, str) and rule.strip() for rule in rules
            ):
                raise ValueError("Invalid rules in knowledge catalog")
            topic = (entry["subject"], entry["topic"])
            identity = (*topic, entry["database"], entry["chunk_id"])
            if identity in seen:
                raise ValueError("Duplicate chunk in knowledge catalog")
            seen.add(identity)
            self.entries.setdefault(topic, []).append(entry)

    def find(self, subject: str, topic: str) -> list[dict]:
        entries = self.entries.get((subject, topic))
        if not entries:
            return []
        subject_dir = self.root / SUBJECT_DIRS[subject]
        conflicts = self._conflicting_chunks(subject_dir / "relations.json")
        evidence = []
        unavailable = False
        for entry in entries:
            if entry["chunk_id"] in conflicts:
                continue
            path = subject_dir / entry["database"]
            try:
                item = self._read(path, entry)
            except (OSError, sqlite3.Error):
                unavailable = True
                continue
            if item is not None:
                evidence.append(item)
        if unavailable and not evidence:
            raise KnowledgeUnavailable()
        return evidence

    @staticmethod
    def _conflicting_chunks(path: Path) -> set[str]:
        # Some editions only list conflict membership in the sidecar. The
        # groups identify both sides even when per-chunk metadata does not.
        try:
            groups = json.loads(path.read_text(encoding="utf-8"))["conflicts"]
            if not isinstance(groups, dict):
                raise ValueError("Invalid knowledge conflict groups")
            chunks = set()
            for members in groups.values():
                if not isinstance(members, list) or not members:
                    raise ValueError("Invalid knowledge conflict group")
                for member in members:
                    chunk_id = member["chunk_id"]
                    if not isinstance(chunk_id, str) or not chunk_id.strip():
                        raise ValueError("Invalid conflicting chunk ID")
                    chunks.add(chunk_id)
            return chunks
        except FileNotFoundError:
            return set()
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise KnowledgeUnavailable() from error

    @staticmethod
    def _read(path: Path, entry: dict) -> dict | None:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            row = db.execute(
                """
                SELECT c.content, c.heading_path, c.page_start, c.page_end, c.metadata_json, d.source_hash
                FROM chunks c JOIN documents d ON d.doc_id = c.doc_id
                WHERE c.chunk_id = ? AND c.doc_id = ?
                """,
                (entry["chunk_id"], entry["doc_id"]),
            ).fetchone()
        if row is None:
            return None
        content, heading, page_start, page_end, metadata_json, source_hash = row
        if not isinstance(content, str) or not content.strip():
            return None
        content_hash = sha256(content.encode("utf-8")).hexdigest()
        if source_hash != entry["source_sha256"] or content_hash != entry["content_sha256"]:
            return None
        try:
            metadata = json.loads(metadata_json) if metadata_json else {}
        except (TypeError, ValueError):
            return None
        if not isinstance(metadata, dict) or metadata.get("conflict_group_id"):
            return None
        location = []
        heading = entry.get("section", heading)
        if isinstance(heading, str) and heading.strip():
            location.append(heading.strip())
        if type(page_start) is int and page_start > 0:
            page_range = f"{page_start}–{page_end}" if type(page_end) is int and page_end > page_start else str(page_start)
            location.append(f"p. {page_range}")
        if not location:
            return None
        location.append(f"chunk {entry['chunk_id']}")
        identity = json.dumps([entry["database"], entry["doc_id"], entry["chunk_id"]]).encode()
        return {
            "id": "kb:" + sha256(identity).hexdigest(),
            "source": entry["source"],
            "version": f"{entry['edition']} · source sha256:{source_hash} · chunk sha256:{content_hash}",
            "anchor": " · ".join(location),
            "summary": entry["summary"],
            "rules": entry["rules"],
        }


def with_knowledge(generate, payload, find_evidence) -> dict:
    result = generate(payload)
    # Validation runs before lookup. Explicit evidence, including an empty
    # list, always keeps its original contract.
    if result["status"] != "NEEDS_MATERIAL" or "evidence" in payload:
        return result
    try:
        evidence = find_evidence(payload["subject"], payload["topic"])
    except KnowledgeUnavailable:
        return failure_result(
            "KNOWLEDGE_BASE_UNAVAILABLE", "已配置的知识库索引暂不可读。", result["request_id"],
        )
    return generate({**payload, "evidence": evidence}) if evidence else result
