"""Read-only lexical discovery inside source-pinned KB documents.

Discovery is explicitly requested via material_query. It does not promote the
returned chunks to the manually reviewed rule catalog. Semantic support remains
an author/reader/auditor responsibility.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import math
import re
import sqlite3

from .curriculum import AREAS
from .knowledge import KnowledgeUnavailable, SUBJECT_DIRS
from .reference_material import reference_evidence


DISCOVERY_MARKER = " · discovery: source-pinned; not chunk-curated"


def restore_discovered(provider, reference, areas):
    """Read the exact recorded discovery chunk, without running a new search."""
    if not reference["version"].endswith(DISCOVERY_MARKER):
        return None
    pin = re.search(r" · source sha256:([a-f0-9]{64}) · chunk sha256:([a-f0-9]{64})$",
                    reference["version"][:-len(DISCOVERY_MARKER)])
    _, marker, chunk_id = reference["anchor"].rpartition(" · chunk ")
    if not pin or not marker or not chunk_id:
        return None
    for entries in provider.entries.values():
        for source in entries:
            if (source["source"] != reference["source"] or source["source_sha256"] != pin[1]
                    or not any(a in AREAS[source["subject"]] for a in areas)):
                continue
            directory = provider.root / SUBJECT_DIRS[source["subject"]]
            if chunk_id in provider._conflicting_chunks(directory / "relations.json"):
                continue
            entry = {**source, "chunk_id": chunk_id, "content_sha256": pin[2], "rules": []}
            entry.pop("section", None)
            try:
                item = provider._read(directory / source["database"], entry)
            except (OSError, sqlite3.Error) as error:
                raise KnowledgeUnavailable() from error
            if item and item["id"] == reference["id"] and "excerpt" in item:
                item["summary"] = item["excerpt"][:1000]
                item["version"] += DISCOVERY_MARKER
                return item
    return None


def discover(provider, payload, *, limit=6, exact_anchor=False, related_notes=False):
    settings = payload["constraints"]["authoring"]
    query = settings.get("material_query")
    if not query:
        return []
    # Keep independently sourced notes for known gaps alongside the textbook.
    areas = settings["syllabus_areas"]
    references = list(reference_evidence(areas, query, related=related_notes))
    # Chinese word segmentation needs no new dependency or writable FTS index.
    words = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", query.lower()))
    tokens = set()
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word) and len(word) > 2:
            tokens.update(word[i:i+2] for i in range(len(word)-1))
        elif len(word) >= 2:
            tokens.add(word)
    if not tokens or provider is None:
        return references[:limit]
    subjects = {s for s, group in AREAS.items() if any(a in group for a in areas)}
    sources = {}
    for entries in provider.entries.values():
        for entry in entries:
            if entry["subject"] in subjects:
                key = (entry["subject"], entry["database"], entry["doc_id"])
                # Conflicting source pins cannot be silently resolved by order.
                if key in sources and sources[key]["source_sha256"] != entry["source_sha256"]:
                    raise KnowledgeUnavailable()
                sources[key] = entry
    ranked, unavailable = [], False
    frequencies = dict.fromkeys(tokens, 0)
    document_count = 0
    for (subject, database, doc_id), source in sources.items():
        directory = provider.root / SUBJECT_DIRS[subject]
        conflicts = provider._conflicting_chunks(directory / "relations.json")
        path = directory / database
        try:
            with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=2)) as db:
                rows = db.execute("""SELECT c.chunk_id, c.content, c.heading_path, c.content_hash
                    FROM chunks c JOIN documents d ON c.doc_id=d.doc_id
                    WHERE c.doc_id=? AND d.source_hash=? ORDER BY c.chunk_id LIMIT 10000""",
                                  (doc_id, source["source_sha256"]))
                for chunk_id, content, heading, stored_hash in rows:
                    if chunk_id in conflicts or not isinstance(content, str) or not 60 <= len(content) <= 12000:
                        continue
                    digest = sha256(content.encode()).hexdigest()
                    if stored_hash != digest:
                        continue
                    lower = content.lower()
                    matched = {t for t in tokens if t in lower}
                    document_count += 1
                    for token in matched:
                        frequencies[token] += 1
                    if len(matched) < min(2, len(tokens)) or (exact_anchor and not any(w in lower for w in words)):
                        continue
                    # Extracted ancestor headings sometimes contain whole OCR
                    # paragraphs. They must not dominate every descendant chunk.
                    heading = " ".join(h for h in heading.lower().split(" > ")[-2:] if len(h) <= 60) if isinstance(heading, str) else ""
                    entry = {**source, "chunk_id": chunk_id, "content_sha256": digest,
                             "summary": content[:1000], "rules": []}
                    # A section override was reviewed for the old chunk, not this one.
                    entry.pop("section", None)
                    ranked.append((lower, heading, matched, chunk_id, path, entry))
        except (OSError, sqlite3.Error):
            unavailable = True
    results = references[:limit]
    used, characters = set(), sum(len(item["summary"]) for item in results)
    def relevance(item):
        lower, heading, matched = item[:3]
        return sum(math.log(1 + (document_count+1)/(frequencies[t]+1)) *
                   (1 + min(lower.count(t), 4)/4 + (0.5 if t in heading else 0)) for t in matched) + 4*sum(
                       len(w) > 2 and w in lower for w in words)
    for _, _, _, _, path, entry in sorted(ranked, key=lambda item: (-relevance(item), str(item[4]), item[3])):
        if len(results) == limit:
            break
        if entry["content_sha256"] in used:
            continue
        try:
            item = provider._read(path, entry)
        except (OSError, sqlite3.Error):
            unavailable = True
            continue
        if item is None:
            continue
        size = len(item.get("excerpt", "")) + len(item["summary"])
        if characters + size > 18000:
            continue
        item["version"] += DISCOVERY_MARKER
        results.append(item)
        characters += size
        used.add(entry["content_sha256"])
    if unavailable and not results:
        raise KnowledgeUnavailable()
    return results
