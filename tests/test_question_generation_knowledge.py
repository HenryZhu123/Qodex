from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from question_generation.batch import generate_batch
from question_generation.generation import generate_question
from question_generation.knowledge import KnowledgeEvidence, with_knowledge

EXAMPLES = Path(__file__).resolve().parents[1] / "question_generation" / "examples"


class KnowledgeTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        subject = self.root / "operating_system"
        subject.mkdir()
        self.index = subject / "kb.sqlite"
        self.text = "Synthetic fixture for validating the index contract."
        self.source_hash = sha256(b"synthetic source").hexdigest()
        with sqlite3.connect(self.index) as connection:
            connection.executescript("""
                CREATE TABLE documents (doc_id TEXT PRIMARY KEY, source_hash TEXT);
                CREATE TABLE chunks (
                    chunk_id TEXT PRIMARY KEY, doc_id TEXT, content TEXT, heading_path TEXT,
                    page_start INTEGER, page_end INTEGER, metadata_json TEXT
                );
            """)
            connection.execute("INSERT INTO documents VALUES (?, ?)", ("os-demo", self.source_hash))
            connection.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                               ("section-1", "os-demo", self.text, "Paging", 3, 4, "{}"))
        self.entry = {
            "subject": "operating_systems", "topic": "single_level_paging",
            "database": "kb.sqlite", "doc_id": "os-demo", "chunk_id": "section-1",
            "source": "https://example.invalid/synthetic-paging",
            "edition": "synthetic edition",
            "source_sha256": self.source_hash,
            "content_sha256": sha256(self.text.encode()).hexdigest(),
            "summary": "Synthetic fixture only.",
            "rules": ["split_address", "map_virtual_page", "preserve_offset"],
        }
        self.catalog = self.root / "catalog.json"
        self.request = json.loads((EXAMPLES / "paging.json").read_text(encoding="utf-8"))
        self.request.pop("evidence")

    def provider(self, **changes):
        entry = {**self.entry, **changes}
        self.catalog.write_text(json.dumps({"schema_version": "0.1", "entries": [entry]}), encoding="utf-8")
        return KnowledgeEvidence(self.root, self.catalog)

    def test_uses_pinned_source_and_chunk_with_real_topic_routing(self):
        provider = self.provider()
        result = with_knowledge(generate_question, self.request, provider.find)
        self.assertEqual(result["status"], "GENERATED")
        ref, = result["questions"][0]["evidence_refs"]
        self.assertEqual(ref["source"], self.entry["source"])
        self.assertEqual(ref["version"], f"synthetic edition · source sha256:{self.source_hash}"
                                         f" · chunk sha256:{self.entry['content_sha256']}")
        self.assertEqual(ref["anchor"], "Paging · p. 3–4 · chunk section-1")
        self.assertEqual(provider.find("computer_networks", "single_level_paging"), [])

    def test_partial_rule_coverage_returns_exact_missing_rules(self):
        provider = self.provider(rules=["split_address", "map_virtual_page"])
        result = with_knowledge(generate_question, self.request, provider.find)
        self.assertEqual(result["status"], "NEEDS_MATERIAL")
        self.assertEqual(result["missing_rules"], ["preserve_offset"])
        self.assertEqual(result["questions"], [])

    def test_source_or_chunk_changes_do_not_carry_forward_tags(self):
        for changes in ({"source_sha256": "0" * 64}, {"content_sha256": "0" * 64},
                        {"doc_id": "different-doc"}, {"chunk_id": "missing"}):
            provider = self.provider(**changes)
            with self.subTest(changes=changes):
                result = with_knowledge(generate_question, self.request, provider.find)
                self.assertEqual(result["status"], "NEEDS_MATERIAL")
                self.assertEqual(result["questions"], [])

    def test_conflicting_chunk_does_not_count_as_material(self):
        provider = self.provider()
        with sqlite3.connect(self.index) as connection:
            connection.execute("UPDATE chunks SET metadata_json = ?", (json.dumps({"conflict_group_id": "g1"}),))
        result = with_knowledge(generate_question, self.request, provider.find)
        self.assertEqual(result["status"], "NEEDS_MATERIAL")

    def test_bad_index_reports_unavailability_without_creating_files(self):
        provider = self.provider(database="kb_missing.sqlite")
        result = with_knowledge(generate_question, self.request, provider.find)
        self.assertEqual(result["status"], "KNOWLEDGE_BASE_UNAVAILABLE")
        self.assertFalse((self.index.parent / "kb_missing.sqlite").exists())

    def test_explicit_evidence_and_invalid_input_do_not_trigger_lookup(self):
        lookup = Mock()
        for payload, status in (
            ({**self.request, "evidence": []}, "NEEDS_MATERIAL"),
            ({**self.request, "seed": True}, "INVALID_REQUEST"),
            ({**self.request, "topic": "unknown"}, "UNSUPPORTED_REQUEST"),
        ):
            result = with_knowledge(generate_question, payload, lookup)
            self.assertEqual(result["status"], status)
        lookup.assert_not_called()

    def test_batch_only_fetches_material_for_omitted_slots(self):
        provider = self.provider()
        batch = json.loads((EXAMPLES / "batch.json").read_text(encoding="utf-8"))
        batch["slots"][0].pop("evidence")
        batch["slots"][1]["evidence"] = []
        result = generate_batch(batch, single_generator=lambda item: with_knowledge(generate_question, item, provider.find))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["generated_count"], 4)
        self.assertEqual(result["deficits"][0]["slot_id"], "stack")
        paging = [question for question in result["questions"] if question["slot_id"] == "paging"]
        self.assertEqual(len(paging), 2)
        self.assertTrue(all(question["evidence_refs"][0]["source"] == self.entry["source"] for question in paging))

    def test_catalog_cannot_escape_the_subject_index_folder(self):
        with self.assertRaises(ValueError):
            self.provider(database="../kb.sqlite")
