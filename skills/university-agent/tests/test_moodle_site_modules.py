import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.moodle_site import module_for


class MoodleSiteModuleTests(unittest.TestCase):
    def test_kku_uses_only_observed_kku_extensions(self):
        module = module_for("https://tls.kku.ac.kr")
        self.assertEqual(module.key, "kku_tls")
        self.assertEqual(module.course_paths[0], "/local/ubion/user/")
        self.assertEqual(module.autonomous_course_path, "/local/ubeclass/my.php")
        self.assertTrue(module.is_kku_resource_view("/mod/ubfile/view.php"))
        self.assertTrue(module.is_custom_document("/local/ubdoc/"))

    def test_unknown_moodle_never_receives_kku_paths(self):
        module = module_for("https://lms.example.edu")
        self.assertEqual(module.key, "standard_moodle")
        self.assertEqual(module.course_paths, ("/my/", "/course/index.php"))
        self.assertIsNone(module.autonomous_course_path)
        self.assertFalse(module.is_kku_resource_view("/mod/ubfile/view.php"))
        self.assertTrue(module.is_standard_resource_view("/mod/resource/view.php"))

    def test_similar_hostname_is_not_treated_as_kku(self):
        module = module_for("https://tls.kku.ac.kr.example.edu")
        self.assertEqual(module.key, "standard_moodle")
        self.assertIsNone(module.autonomous_course_path)


if __name__ == "__main__":
    unittest.main()
