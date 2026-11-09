from hashlib import sha256
import json
import sqlite3
from unittest.mock import Mock
from unittest import TestCase

import test_question_generation_knowledge as fixtures
from question_generation.knowledge import with_knowledge
from question_generation.generation import generate_question


class DiscoveryTests(TestCase):
    provider = fixtures.KnowledgeTests.provider

    def setUp(self):
        fixtures.KnowledgeTests.setUp(self)
        self.payload = {**self.request, 'topic':'semaphore_diagnosis',
                        'constraints':{'authoring':{'objective':'diagnose','syllabus_areas':['os.process'],
                                                    'material_query':'信号量 互斥'}}}
        with sqlite3.connect(self.index) as db:
            db.execute('ALTER TABLE chunks ADD COLUMN content_hash TEXT')
            for i, text in enumerate([
                '信号量用于互斥访问和同步，wait操作必须原子执行，资源不可用时进程阻塞，signal操作可以唤醒等待者。'*2,
                '文件系统用于管理文件目录、磁盘空间及其持久化元数据，目录项可以指向文件的索引节点。'*2,
            ]):
                db.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?)',
                           (f'discovery-{i}','os-demo',text,'进程同步' if i==0 else '文件管理',5+i,5+i,'{}',sha256(text.encode()).hexdigest()))

    def test_discovery_finds_new_topic_without_changing_rule_catalog(self):
        provider = self.provider()
        result = provider.discover(self.payload)
        self.assertEqual(len(result), 1)
        self.assertIn('discovery-0', result[0]['anchor'])
        self.assertEqual(result[0]['rules'], [])
        self.assertIn('not chunk-curated', result[0]['version'])
        self.assertEqual(provider.find('operating_systems','semaphore_diagnosis'), [])
        self.assertNotIn('Verified chapter', result[0]['anchor'])

    def test_discovery_rejects_source_and_content_changes(self):
        provider = self.provider(source_sha256='0'*64)
        self.assertEqual(provider.discover(self.payload), [])
        provider = self.provider()
        with sqlite3.connect(self.index) as db:
            db.execute("UPDATE chunks SET content_hash='changed' WHERE chunk_id='discovery-0'")
        self.assertEqual(provider.discover(self.payload), [])

    def test_discovery_excludes_conflicts_and_does_not_reuse_section_override(self):
        provider = self.provider(section='Verified chapter')
        self.assertIn('进程同步', provider.discover(self.payload)[0]['anchor'])
        (self.index.parent/'relations.json').write_text(json.dumps({'conflicts':{'g1':[{'chunk_id':'discovery-0'}]}}))
        self.assertEqual(provider.discover(self.payload), [])

    def test_discovery_is_explicit_and_never_overrides_empty_material(self):
        lookup, discovery = Mock(return_value=[]), Mock(return_value=[])
        result = with_knowledge(generate_question, self.payload, lookup, discover_evidence=discovery)
        self.assertEqual(result['status'], 'NEEDS_MATERIAL')
        lookup.assert_not_called()
        discovery.assert_called_once_with(self.payload)
        discovery.reset_mock()
        with_knowledge(generate_question, {**self.payload,'evidence':[]}, lookup, discover_evidence=discovery)
        discovery.assert_not_called()

    def test_discovery_does_not_import_unpinned_documents(self):
        with sqlite3.connect(self.index) as db:
            db.execute("UPDATE chunks SET doc_id='untrusted' WHERE chunk_id='discovery-0'")
            db.execute('INSERT INTO documents VALUES (?,?)',('untrusted',self.source_hash))
        self.assertEqual(self.provider().discover(self.payload), [])
