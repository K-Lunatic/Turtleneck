import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import companion


class CompanionTests(unittest.TestCase):
    def test_tray_icon_is_a_small_monochrome_line_mark(self):
        class FakeImage:
            mode = 'RGBA'
            size = (64, 64)
            def __init__(self):
                self.operations = []

        class FakeImageModule:
            @staticmethod
            def new(mode, size, color):
                return FakeImage()

        class FakeDraw:
            def __init__(self, image):
                self.image = image
            def ellipse(self, *args, **kwargs): self.image.operations.append('ellipse')
            def line(self, *args, **kwargs): self.image.operations.append('line')
            def arc(self, *args, **kwargs): self.image.operations.append('arc')

        class FakeDrawModule:
            Draw = FakeDraw

        icon = companion._build_tray_icon(FakeImageModule, FakeDrawModule)
        self.assertEqual((icon.mode, icon.size), ('RGBA', (64, 64)))
        self.assertGreaterEqual(len(icon.operations), 5)

    def test_setup_menu_starts_connection_flow_instead_of_status_only(self):
        with patch.object(companion.subprocess, 'Popen') as launch:
            companion._open_setup()
        command = launch.call_args.args[0]
        self.assertEqual(command[-2:], ['--only', 'tls'])
        self.assertNotIn('--status', command)
        self.assertEqual(launch.call_args.kwargs['stdout'], companion.subprocess.DEVNULL)

    def test_present_routes_login_and_exam_to_the_embedded_window(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder) / 'companion-runtime.json'
            received = []
            dashboard = companion.DashboardServer(
                presenter=lambda url, kind: received.append((url, kind)),
            )
            with patch.object(companion, 'RUNTIME_PATH', runtime):
                dashboard_url = dashboard.start()
                try:
                    parts = urlsplit(dashboard_url)
                    base = f'http://{parts.hostname}:{parts.port}'
                    token = json.loads(runtime.read_text(encoding='utf-8'))['token']
                    for kind in ('login', 'exam'):
                        request = Request(
                            base + '/present',
                            data=json.dumps({
                                'url': f'http://127.0.0.1:4321/?kind={kind}',
                                'kind': kind,
                            }).encode('utf-8'),
                            method='POST',
                            headers={
                                'Authorization': 'Bearer ' + token,
                                'Content-Type': 'application/json',
                            },
                        )
                        with urlopen(request, timeout=2) as response:
                            self.assertEqual(response.status, 200)
                finally:
                    dashboard.stop()
            self.assertEqual([kind for _url, kind in received], ['login', 'exam'])

    def test_frozen_exam_uses_adjacent_main_bundle_when_available(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app_dir = root / 'Turtleneck Companion.app' / 'Contents' / 'MacOS'
            app_dir.mkdir(parents=True)
            (root / 'turtleneck' / 'turtleneck').parent.mkdir()
            (root / 'turtleneck' / 'turtleneck').write_bytes(b'')
            with patch.object(sys, 'frozen', True, create=True), \
                 patch.object(sys, 'executable', str(app_dir / 'turtleneck-companion')):
                command = companion._exam_command()
            self.assertEqual(command[0], str((root / 'turtleneck' / 'turtleneck').resolve()))
            self.assertTrue(command[1].endswith('scripts/exam_web.py'))

    def test_frozen_setup_uses_adjacent_main_bundle_when_available(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app_dir = root / 'Turtleneck Companion.app' / 'Contents' / 'MacOS'
            app_dir.mkdir(parents=True)
            (root / 'turtleneck' / 'turtleneck').parent.mkdir()
            (root / 'turtleneck' / 'turtleneck').write_bytes(b'')
            with patch.object(sys, 'frozen', True, create=True), \
                 patch.object(sys, 'executable', str(app_dir / 'turtleneck-companion')):
                command = companion._setup_command()
            self.assertEqual(command[0], str((root / 'turtleneck' / 'turtleneck').resolve()))
            self.assertTrue(command[1].endswith('scripts/setup_turtleneck.py'))

    def test_frozen_commands_find_sibling_main_bundle_in_release_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            dist = Path(folder) / 'dist'
            companion_dir = dist / 'companion'
            companion_dir.mkdir(parents=True)
            main = dist / 'turtleneck' / 'turtleneck'
            main.parent.mkdir()
            main.write_bytes(b'')
            executable = companion_dir / 'turtleneck-companion'
            with patch.object(sys, 'frozen', True, create=True), \
                 patch.object(sys, 'executable', str(executable)):
                exam = companion._exam_command()
                setup = companion._setup_command()
            self.assertEqual(exam[0], str(main.resolve()))
            self.assertEqual(setup[0], str(main.resolve()))

    def test_skill_status_is_local_and_does_not_require_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'SKILL.md').write_text('name: turtleneck\n', encoding='utf-8')
            self.assertEqual(companion.skill_status(root), {'installed': True, 'path': str(root.resolve())})

    def test_snapshot_exposes_profile_markers_but_not_secret_fields(self):
        profile = {
            'site': 'tls.example.edu', 'alias': 'main', 'username': 'student', 'active': True,
            'dbPath': '/tmp/not-used.db', 'password': 'must-not-leak', 'cookie': 'must-not-leak'
        }
        with patch.object(companion, 'list_profiles', return_value=[profile]), patch.object(companion, 'skill_status', return_value={'installed': True, 'path': '/skill'}):
            data = companion.snapshot()
        encoded = json.dumps(data, ensure_ascii=False)
        self.assertIn('student', encoded)
        self.assertNotIn('must-not-leak', encoded)
        self.assertNotIn('dbPath', encoded)
        self.assertEqual(data['profiles'][0]['site'], 'tls.example.edu')

    def test_dashboard_reads_exam_summary_without_questions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / 'university.db'
            study_path = root / 'study-sessions.db'
            with closing(sqlite3.connect(study_path)) as db, db:
                db.execute('CREATE TABLE study_exams (user TEXT, exam_id TEXT, conversation TEXT, created_at TEXT, title TEXT, question_count INTEGER, phase TEXT, score REAL, state TEXT)')
                db.execute('INSERT INTO study_exams VALUES (?,?,?,?,?,?,?,?,?)',
                           ('student', 'exam-1', 'conversation', '2026-11-16T01:00:00+00:00', '자료구조 복습', 10, 'finished', 80.0, '{}'))
            profile = {'site': 'tls.example.edu', 'alias': 'main', 'username': 'student', 'active': True, 'dbPath': str(db_path)}
            with patch.object(companion, 'snapshot', return_value={'skill': {'installed': True}, 'profiles': [profile], 'checkedAt': 1}):
                data = companion.dashboard_snapshot()
            self.assertEqual(data['exams'][0]['title'], '자료구조 복습')
            self.assertEqual(data['scoreSummary']['average'], 80.0)
            self.assertNotIn('state', data['exams'][0])


if __name__ == '__main__':
    unittest.main()
