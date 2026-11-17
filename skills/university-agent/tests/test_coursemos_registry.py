import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.coursemos_registry import find_candidates, load_registry


class CoursemosRegistryTests(unittest.TestCase):
    def test_public_registry_keeps_source_and_separate_app_note(self):
        registry = load_registry()
        self.assertEqual(registry["source"]["listedAsOf"], "2024-01")
        self.assertIn("건국대학교", registry["listedInstitutions"])
        self.assertIn("연세대학교 LearnUs", registry["separateAppInstitutions"])

    def test_find_candidates_is_local_and_bounded(self):
        self.assertEqual(find_candidates("건국"), ["건국대학교"])
        self.assertLessEqual(len(find_candidates("대학교", limit=3)), 3)


if __name__ == "__main__":
    unittest.main()
