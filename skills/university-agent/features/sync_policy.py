"""Local sync ownership, successful-check ages and persistent failure cooldowns."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time


CATALOG_TTL = 5 * 60
AUTONOMOUS_TTL = 6 * 60 * 60
ACADEMIC_TTL = 15 * 60
NOTICE_TTL = 6 * 60 * 60
RESOURCE_TTL = 24 * 60 * 60


def now():
    return datetime.now(timezone.utc)


def scope_key(base_url, username):
    return hashlib.sha256(json.dumps([base_url.rstrip('/'), username]).encode()).hexdigest()


def fresh(value, seconds, *, since=None):
    try:
        checked = datetime.fromisoformat(value)
        age = (now() - checked).total_seconds()
        return 0 <= age < seconds and (since is None or checked >= since)
    except (TypeError, ValueError):
        return False


def checks(state, kind):
    try:
        result = json.loads(state.get(kind + '_course_checks', '{}'))
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def due_courses(state, kind, course_ids, seconds, *, since=None):
    previous = checks(state, kind)
    return {identifier for identifier in course_ids if not fresh(previous.get(identifier), seconds, since=since)}


class SyncBusy(RuntimeError):
    pass


class SyncLock:
    """OS-owned lock: a crashed process releases it without deleting a live lock file."""
    def __init__(self, db_path, *, timeout=120):
        self.path = Path(str(Path(db_path).resolve()) + '.sync.lock')
        self.timeout = timeout
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        self.file = os.fdopen(descriptor, 'r+b', buffering=0)
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    self.file.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if os.fstat(descriptor).st_size == 0:
                        self.file.write(b' ')
                    return self
                except OSError:
                    if time.monotonic() >= deadline:
                        raise SyncBusy('다른 학교 확인이 진행 중이에요. 완료 후 다시 확인해 주세요.') from None
                    time.sleep(0.1)
        except BaseException:
            self.file.close()
            raise

    def __exit__(self, *_):
        self.file.close()

    def state(self, scope):
        self.file.seek(1)
        try:
            data = json.loads(self.file.read(4096))
            return data if isinstance(data, dict) and data.get('scope') == scope else {}
        except (ValueError, UnicodeError):
            return {}

    def remaining(self, scope):
        value = self.state(scope).get('retry_at', 0)
        return max(0, value - now().timestamp()) if isinstance(value, (int, float)) and math.isfinite(value) else 0

    def record(self, scope, *, failed=False, delay=0):
        self.file.seek(1)
        self.file.truncate()
        self.file.write(json.dumps({'scope': scope, 'failed': failed,
                                   'retry_at': now().timestamp() + delay if delay else 0}).encode())
        self.file.flush()
