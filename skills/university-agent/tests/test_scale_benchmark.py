import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("scale_benchmark", ROOT / "experiments/benchmarks/scale_benchmark.py")
scale_benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(scale_benchmark)


class ScaleBenchmarkTests(unittest.TestCase):
    def test_small_and_large_workloads_are_explicit(self):
        self.assertLess(scale_benchmark.SCENARIOS["small"]["courses"], scale_benchmark.SCENARIOS["large"]["courses"])
        self.assertLess(scale_benchmark.SCENARIOS["small"]["mediaChunks"], scale_benchmark.SCENARIOS["large"]["mediaChunks"])

    def test_median_ignores_structured_metrics(self):
        self.assertEqual(scale_benchmark._median([
            {"elapsedMs": 2, "requests": 4, "statuses": {}},
            {"elapsedMs": 4, "requests": 6, "statuses": {}},
        ]), {"elapsedMs": 3, "requests": 5})


if __name__ == "__main__":
    unittest.main()
