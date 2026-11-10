"""Small contract checks for the offline benchmark metadata and aggregation."""
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('benchmark_parts', ROOT / 'experiments/benchmarks/benchmark_parts.py')
benchmark_parts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark_parts)


class BenchmarkPartsTests(unittest.TestCase):
    def test_median_keeps_numeric_metrics_and_ignores_structured_values(self):
        self.assertEqual(benchmark_parts._median([
            {'elapsedMs': 2, 'requests': 4, 'statuses': {}},
            {'elapsedMs': 4, 'requests': 6, 'statuses': {}},
        ]), {'elapsedMs': 3, 'requests': 5})

    def test_each_part_declares_a_role_and_source_files(self):
        self.assertTrue(benchmark_parts.PARTS)
        self.assertTrue(all(item['role'] and item['files'] for item in benchmark_parts.PARTS.values()))


if __name__ == '__main__':
    unittest.main()
