import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from features.profile_context import select_profile
from providers import credentials


class ProfileAccountTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "macOS Keychain migration case")
    def test_default_profile_reads_original_username_key_during_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "tls-account.json"
            keychain = {("university-agent/tls", "lunatic"): "old-password"}

            def read_secret(service, alias):
                value = keychain.get((service, alias), "")
                if not value:
                    raise ValueError("empty")
                return value

            config.write_text(json.dumps({"activeAlias": "default", "profiles": {
                "default": {"username": "lunatic"}}}), encoding="utf-8")
            with patch.object(credentials, "CONFIG_PATH", config), \
                 patch.object(credentials, "_read_keychain_secret", side_effect=read_secret):
                self.assertEqual(credentials.load("default", "tls.kku.ac.kr"),
                                 ("lunatic", "old-password"))

    @unittest.skipIf(os.name == "nt", "macOS Keychain storage case")
    def test_sites_and_aliases_have_separate_markers_and_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "tls-account.json"
            keychain = {}

            def security(args, **_kwargs):
                service = args[args.index("-s") + 1]
                alias = args[args.index("-a") + 1]
                if args[1] == "add-generic-password":
                    self.assertEqual(args[-1], "-w")
                    self.assertNotIn(_kwargs["input"].rstrip("\n"), args)
                    keychain[(service, alias)] = _kwargs["input"].rstrip("\n")
                return type("Result", (), {"stdout": keychain[(service, alias)] + "\n"})()

            with patch.object(credentials, "CONFIG_PATH", config), \
                 patch.object(credentials, "_save_keychain_secret", side_effect=lambda service, alias, secret: keychain.__setitem__((service, alias), secret)), \
                 patch.object(credentials.subprocess, "run", side_effect=security), \
                 patch.dict(os.environ, {"TURTLENECK_ALLOW_KEYCHAIN_MIGRATION": "1"}):
                credentials.save("kku-user", "kku-password", "본계정", "tls.kku.ac.kr")
                credentials.save("mokwon-user", "mokwon-password", "본계정", "lms.mokwon.ac.kr")
                credentials.save("kku-helper", "helper-password", "조교", "tls.kku.ac.kr")
                self.assertEqual(credentials.load("본계정", "tls.kku.ac.kr"), ("kku-user", "kku-password"))
                self.assertEqual(credentials.load("본계정", "lms.mokwon.ac.kr"), ("mokwon-user", "mokwon-password"))
                self.assertEqual(credentials.load("조교", "tls.kku.ac.kr"), ("kku-helper", "helper-password"))
                markers = list(Path(folder).glob("tls-account*.json"))
                self.assertTrue(markers)
                marker_text = "".join(path.read_text(encoding="utf-8") for path in markers)
                self.assertNotIn("kku-password", marker_text)
                self.assertNotIn("mokwon-password", marker_text)
                self.assertNotIn("helper-password", marker_text)
                self.assertEqual({item["site"] for item in credentials.list_profiles()}, {"tls.kku.ac.kr", "lms.mokwon.ac.kr"})

    @unittest.skipIf(os.name == "nt", "macOS Keychain session case")
    def test_session_markers_keep_other_aliases(self):
        with tempfile.TemporaryDirectory() as folder:
            session_path = Path(folder) / "tls-session.json"
            values = {}

            def security(args, **_kwargs):
                service = args[args.index("-s") + 1]
                alias = args[args.index("-a") + 1]
                if args[1] == "add-generic-password":
                    self.assertEqual(args[-1], "-w")
                    self.assertNotIn(_kwargs["input"].rstrip("\n"), args)
                    values[(service, alias)] = _kwargs["input"].rstrip("\n")
                return type("Result", (), {"stdout": values[(service, alias)] + "\n"})()

            def jar(value):
                result = CookieJar()
                result.set_cookie(Cookie(version=0, name="MoodleSession", value=value, port=None,
                                         port_specified=False, domain="tls.example", domain_specified=True,
                                         domain_initial_dot=False, path="/", path_specified=True, secure=True,
                                         expires=None, discard=True, comment=None, comment_url=None, rest={}, rfc2109=False))
                return result

            with patch.object(credentials, "SESSION_PATH", session_path), \
                 patch.object(credentials, "_save_keychain_secret", side_effect=lambda service, alias, secret: values.__setitem__((service, alias), secret)), \
                 patch.object(credentials.subprocess, "run", side_effect=security), \
                 patch.dict(os.environ, {"TURTLENECK_ALLOW_KEYCHAIN_MIGRATION": "1"}):
                credentials.save_session("one", jar("cookie-one"), "one", "tls.kku.ac.kr")
                credentials.save_session("two", jar("cookie-two"), "two", "tls.kku.ac.kr")
                state = json.loads(session_path.read_text(encoding="utf-8"))
                self.assertEqual(set(state["profiles"]), {"one", "two"})
                self.assertNotIn("cookie-one", session_path.read_text(encoding="utf-8"))
                self.assertEqual(next(iter(credentials.load_session("one", "one", "tls.kku.ac.kr"))).value, "cookie-one")

    @unittest.skipIf(os.name == "nt", "macOS Keychain linking case")
    def test_explicit_cross_site_link_reuses_only_the_source_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "tls-account.json"
            keychain = {}

            def read_secret(service, alias):
                value = keychain.get((service, alias))
                if value is None:
                    raise ValueError("missing fixture secret")
                return value

            def security(args, **_kwargs):
                service = args[args.index("-s") + 1]
                alias = args[args.index("-a") + 1]
                if args[1] == "add-generic-password":
                    keychain[(service, alias)] = _kwargs["input"].rstrip("\n")
                return type("Result", (), {"stdout": keychain[(service, alias)] + "\n"})()

            with patch.object(credentials, "CONFIG_PATH", config), \
                 patch.object(credentials, "_save_keychain_secret", side_effect=lambda service, alias, secret: keychain.__setitem__((service, alias), secret)), \
                 patch.object(credentials, "_read_keychain_secret", side_effect=read_secret), \
                 patch.object(credentials.subprocess, "run", side_effect=security):
                credentials.save("kku-user", "shared-password", "본계정", "tls.kku.ac.kr")
                credentials.link_account("im.kku.ac.kr", "본계정", "tls.kku.ac.kr", "본계정")
                self.assertEqual(credentials.load("본계정", "im.kku.ac.kr"), ("kku-user", "shared-password"))
                marker = Path(folder) / "tls-account-im-kku-ac-kr.json"
                saved = json.loads(marker.read_text(encoding="utf-8"))
                self.assertEqual(saved["profiles"]["본계정"]["credentialRef"],
                                 {"site": "tls.kku.ac.kr", "alias": "본계정"})
                credentials.save("kku-user", "shared-password", "본계정", "im.kku.ac.kr")
                self.assertNotIn(("university-agent/tls/im.kku.ac.kr", "본계정"), keychain)

    def test_course_context_selects_one_profile_and_stops_on_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "tls-account.json"
            with patch.object(credentials, "CONFIG_PATH", config), \
                 patch.object(credentials, "_save_keychain_secret"), patch.object(credentials.subprocess, "run"):
                credentials.save("kku", "secret", "본계정", "tls.kku.ac.kr")
                credentials.save("mokwon", "secret", "본계정", "lms.mokwon.ac.kr")
                for item, course in zip(credentials.list_profiles(), ("자료구조", "운영체제")):
                    db = Path(item["dbPath"])
                    db.parent.mkdir(parents=True, exist_ok=True)
                    with closing(sqlite3.connect(db)) as connection, connection:
                        connection.execute("CREATE TABLE courses(name TEXT)")
                        connection.execute("INSERT INTO courses VALUES (?)", (course,))
                selected = select_profile("자료구조 과제 확인해줘")
                self.assertEqual((selected["status"], selected["profile"]["site"]), ("selected", "tls.kku.ac.kr"))
                credentials.save("kku-2", "secret", "부계정", "tls.kku.ac.kr")
                db = Path(next(item for item in credentials.list_profiles() if item["alias"] == "부계정")["dbPath"])
                db.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(db)) as connection, connection:
                    connection.execute("CREATE TABLE courses(name TEXT)")
                    connection.execute("INSERT INTO courses VALUES ('자료구조')")
                self.assertEqual(select_profile("자료구조 과제 확인해줘")["status"], "ambiguous")


if __name__ == "__main__":
    unittest.main()
