import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.benchmarks.traffic_curve import render_svg


class TrafficCurveTests(unittest.TestCase):
    def test_curve_keeps_both_series_and_scenario(self):
        result = render_svg([
            {"scenario": "academic_sync", "comparison": {"bodyBytesLowerBound": {"skill": 10, "user": 20}}},
            {"scenario": "academic_sync", "comparison": {"bodyBytesLowerBound": {"skill": 5, "user": 20}}},
        ])
        self.assertIn("academic_sync", result)
        self.assertIn("터틀넥", result)
        self.assertIn("사용자 브라우저", result)
        self.assertEqual(result.count("<polyline"), 2)

    def test_curve_rejects_mixed_scenarios(self):
        with self.assertRaises(ValueError):
            render_svg([
                {"scenario": "a", "comparison": {"requests": {"skill": 1, "user": 2}}},
                {"scenario": "b", "comparison": {"requests": {"skill": 1, "user": 2}}},
            ], "requests")


if __name__ == "__main__":
    unittest.main()
