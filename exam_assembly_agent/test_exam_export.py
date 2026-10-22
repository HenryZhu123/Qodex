import copy
import json
from pathlib import Path
import tempfile
import unittest
from .main import assemble_exam, inspect_candidates
from .question_bank import load_questions
from .exam_export import export_exam


class ExportTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / 'examples'
        self.request = json.loads((root / 'request.json').read_text(encoding='utf-8'))
        self.bank = load_questions(root / 'question_bank.json')
        self.result = assemble_exam(self.request, self.bank)

    def test_complete_bank_and_missing_answer_exclusion(self):
        self.assertEqual(len(self.bank), 20)
        self.assertTrue(all(q['answer'] in q['options'] and q['explanation'] for q in self.bank))
        broken = copy.deepcopy(self.bank[0])
        broken['answer'] = ''
        self.assertEqual(inspect_candidates(self.request, [broken])['eligible_candidate_count'], 0)

    def test_separate_documents_and_same_numbering(self):
        self.result['answer_key'][0]['explanation'] = 'TEACHER_ONLY_SENTINEL'
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_exam(self.request, self.result, tmp)
            student = Path(paths['student_exam_html']).read_text(encoding='utf-8')
            teacher = Path(paths['answer_key_html']).read_text(encoding='utf-8')
            self.assertNotIn('TEACHER_ONLY_SENTINEL', student)
            self.assertIn('TEACHER_ONLY_SENTINEL', teacher)
            self.assertEqual(student.count('class="question"'), 10)
            self.assertEqual(teacher.count('class="question"'), 10)
            for i, q in enumerate(self.result['student_exam'], 1):
                self.assertIn(f'{i}.（2 分）', student)
                self.assertIn(f'第 {i} 题：', teacher)
                self.assertIn(q['question_id'], teacher)

    def test_escapes_html_and_rejects_mismatched_key(self):
        self.result['student_exam'][0]['stem'] = '<script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_exam(self.request, self.result, tmp)
            student = Path(paths['student_exam_html']).read_text(encoding='utf-8')
            self.assertNotIn('<script>', student)
            self.assertIn('&lt;script&gt;', student)
            self.result['answer_key'].pop()
            with self.assertRaises(ValueError):
                export_exam(self.request, self.result, tmp)


if __name__ == '__main__':
    unittest.main()
