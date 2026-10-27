"""Private audio files and deterministic course/lecture selection, not transcription."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

from features.assignment_selection import normalize


def select_lectures(courses, lectures, *, course_query='', lecture_query='', lecture_ids=None, all_completed=False):
    matching = [course for course in courses if not course_query or normalize(course_query) in normalize(course['name'])]
    if not all_completed and not lecture_ids and len(matching) != 1:
        raise ValueError('음성을 가져올 과목을 골라 주세요: ' + ', '.join(course['name'] for course in matching))
    course_ids = {course['id'] for course in matching}
    selected = [lecture for lecture in lectures if lecture['courseId'] in course_ids and
                (not lecture_query or normalize(lecture_query) in normalize(lecture['title'])) and
                (not all_completed or lecture.get('completed') is True)]
    if lecture_ids:
        if not set(lecture_ids) <= {item['id'] for item in selected}:
            raise ValueError('선택한 과목에서 강의를 찾지 못했어요.')
        selected = [item for item in selected if item['id'] in lecture_ids]
    if not selected:
        raise ValueError('조건에 맞는 강의가 없어요. 학교 목록을 새로 확인해 주세요.')
    return selected


def ffmpeg_path():
    executable = shutil.which('ffmpeg')
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        raise RuntimeError('음성을 나눌 도구가 아직 없어요. 이 실행 환경에 requirements-audio.txt를 설치하면 이어갈 수 있어요.') from None


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1_048_576), b''):
            digest.update(block)
    return digest.hexdigest()


def cached_audio(record, root, source_key=None):
    if not record or (source_key is not None and record.get('sourceKey') != source_key):
        return None
    try:
        path = Path(record['localPath']).resolve(strict=True)
        path.relative_to(root.resolve())
        if path.is_file() and path.stat().st_size and _digest(path) == record['contentHash']:
            return record
    except (OSError, ValueError, KeyError):
        pass
    return None


def _source_fingerprint(plan):
    """Ignore session-bound URLs; the current permission check still runs before this cache hit."""
    shape = {'format': plan.get('format'),
             'chunkCount': len(plan.get('chunks', [])),
             'segmentTimes': plan.get('segmentTimes', []),
             'durationSeconds': plan.get('durationSeconds')}
    return 'v3-' + hashlib.sha256(json.dumps(shape, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def extract_audio(provider, user, lecture, plan, root, cached=None, progress=None):
    if lecture.get('completed') is not True:
        raise ValueError('끝까지 본 강의만 음성을 가져올 수 있어요.')
    if plan.get('format') not in ('mpegts', 'mov'):
        raise ValueError('학교 영상 형식을 확인하지 못해 음성을 가져오지 않았어요.')
    root = root.resolve()
    source_key = 'v3-' + hashlib.sha256((_source_fingerprint(plan) + lecture['courseId'] + lecture['title']).encode()).hexdigest()
    hit = cached_audio(cached, root, source_key)
    if not hit and cached and not str(cached.get('sourceKey', '')).startswith('v3-'):
        # Older records used expiring signed URLs as their key. The live permission and format
        # checks above have already passed, so preserve that valid local copy and migrate its key.
        hit = cached_audio(cached, root)
        if hit:
            hit = {**hit, 'sourceKey': source_key}
    if hit:
        return {**hit, 'reused': True}
    executable = ffmpeg_path()
    if not all(re.fullmatch(r'[A-Za-z0-9_-]+', lecture[key]) for key in ('id', 'courseId')):
        raise ValueError('강의 저장 위치를 확인하지 못했어요.')
    target = root / hashlib.sha256(user.encode()).hexdigest()[:16] / lecture['courseId'] / lecture['id'] / source_key / 'lecture.m4a'
    if not target.resolve().is_relative_to(root):
        raise ValueError('허용된 음성 폴더 밖에는 저장하지 않아요.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.audio-', dir=root) as folder:
        source, output = Path(folder) / 'media.bin', Path(folder) / 'audio.m4a'
        provider.save_lecture_media(plan, source, progress)
        if progress:
            progress('다 받아왔어요. 화면은 빼고 교수님 음성만 보관할게요…')
        command = [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                   '-protocol_whitelist', 'file', '-f', plan['format'], '-i', str(source),
                   '-map', '0:a:0', '-vn', '-sn', '-dn', '-map_metadata', '-1', '-map_chapters', '-1',
                   '-c:a', 'aac', '-b:a', '96k', '-f', 'ipod', str(output)]
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           text=True, encoding='utf-8', errors='replace', timeout=600,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            raise RuntimeError('영상 변환 시간이 제한을 넘어 중단했어요. 학교 원본과 기존 저장본은 건드리지 않았어요.') from None
        except subprocess.CalledProcessError as error:
            detail = error.stderr or ''
            if re.search(r'no streams|Stream map.*matches no streams|does not contain any stream', detail, re.I):
                raise RuntimeError('이 영상에는 추출할 음성 트랙이 없어요. 화면 영상만 있는지 확인해 주세요.') from None
            raise RuntimeError('이 영상 형식을 음성 파일로 바꾸지 못했어요. 기존 저장본은 그대로 뒀어요.') from None
        except OSError:
            raise RuntimeError('이 컴퓨터에서 영상 변환 도구를 실행하지 못했어요. FFmpeg 설치 상태를 확인해 주세요.') from None
        try:
            with output.open('r+b') as stream:
                if stream.read(12)[4:8] != b'ftyp' or output.stat().st_size < 100:
                    raise ValueError('완성된 음성 파일을 확인하지 못해 보관하지 않았어요.')
                os.fsync(stream.fileno())
        except FileNotFoundError:
            raise RuntimeError('영상 변환은 끝났지만 음성 파일이 만들어지지 않았어요. 기존 저장본은 그대로 뒀어요.') from None
        content_hash = _digest(output)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not target.resolve().is_relative_to(root):
            raise ValueError('허용된 음성 폴더 밖에는 저장하지 않아요.')
        os.replace(output, target)
    return {'lectureId': lecture['id'], 'sourceKey': source_key, 'localPath': str(target),
            'contentHash': content_hash, 'savedAt': datetime.now(timezone.utc).isoformat(), 'reused': False}
