import random
import sys
import unittest
from unittest.mock import patch
from python_adapter import ROOT, RustParser, PythonRankBucket
from features import concept_insights

sys.path.insert(0, str(ROOT / 'skills/university-agent/tests'))
import test_concept_insights as legacy_tests


def concept_bucket(count):
    result = {}
    for index in range(count):
        result[f'개념 {index}'] = dict(importanceRaw=(index % 13) + 1, weakRaw=(index % 5) * .5,
            attempts=index % 4, explanation=f'근거 있는 설명 {index}',
            evidence={(f'r{index}', 'p.1'): {'location': 'p.1', 'quote': f'원문 {index}'}},
            sourceImportance={'course_material': dict(scores=[20, 50, 80], reasons=['본문 근거'], referenceIds=['ref1'])})
    return result


class ConceptParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = RustParser()

    def test_generated_scores_and_ties_match(self):
        rng = random.Random(20261106)
        for count in (0, 1, 10, 100, 1000):
            bucket = concept_bucket(count)
            for item in bucket.values():
                item.update(importanceRaw=rng.randint(0, 100), weakRaw=rng.randint(0, 8) * .5,
                            attempts=rng.randint(0, 8))
            for limit in (1, 20, 50):
                self.assertEqual(self.native.rank_concepts(bucket, limit), PythonRankBucket(bucket, limit))

    def test_evidence_order_and_unicode_sort_are_kept(self):
        bucket = concept_bucket(8)
        item = next(iter(bucket.values()))
        item['sourceImportance']['ai_evaluation'] = dict(scores=[2, 3], reasons=['근거'] * 5, referenceIds=list(range(20)))
        item['evidence'] = {(str(i), str(i)): {'location': str(i), 'quote': f'인용 {i}'} for i in range(12)}
        self.assertEqual(self.native.rank_concepts(bucket, 8), PythonRankBucket(bucket, 8))

    def test_invalid_unselected_score_preserves_original_exception(self):
        bucket = concept_bucket(10)
        bucket['개념 0']['importanceRaw'] = 0
        bucket['개념 0']['sourceImportance']['course_material']['scores'] = ['invalid']
        for run in (PythonRankBucket, self.native.rank_concepts):
            with self.assertRaises(TypeError):
                run(bucket, 1)

    def test_nonfinite_and_surrogate_inputs_use_python_recovery(self):
        bucket = concept_bucket(2)
        bucket['개념 0']['explanation'] = '\ud800'
        self.assertEqual(self.native.rank_concepts(bucket, 2), PythonRankBucket(bucket, 2))
        bucket['개념 0']['importanceRaw'] = float('nan')
        for run in (PythonRankBucket, self.native.rank_concepts):
            with self.assertRaises(ValueError):
                run(bucket, 2)

    def test_existing_permission_and_course_regressions_use_native_rank(self):
        suite = unittest.TestLoader().loadTestsFromTestCase(legacy_tests.ConceptInsightTests)
        result = unittest.TestResult()
        before = self.native.concept_calls
        with patch.object(concept_insights, '_rank_bucket', self.native.rank_concepts):
            suite.run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        self.assertGreater(self.native.concept_calls, before)


if __name__ == '__main__':
    unittest.main()
