"""Read only observed, clear school media; never run player tracking or fetch keys."""
import hashlib
import json
import re
import math
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit

from providers.moodle_session import DownloadRestricted, check_download_origin, check_download_url


_RETRYABLE_HTTP = {408, 425, 500, 502, 503, 504}
_CHUNK_ATTEMPTS = 3


def _attributes(line):
    return dict((key, quoted or plain) for key, quoted, plain in
                re.findall(r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', line.partition(':')[2]))


def media_plan(session, source, *, video=False):
    """All referenced addresses/keys are checked before any media bytes are fetched."""
    parts = urlsplit(source)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or
        not parts.netloc):
        raise DownloadRestricted('학교에서 제공하는 영상 주소를 확인하지 못했어요.')
    origin, current, seen = parts.netloc, source, set()
    playback_key = hashlib.sha256(source.encode()).hexdigest()
    for _ in range(4):
        check_download_origin(current, origin)
        check_download_url(current)
        extension = urlsplit(current).path.lower().rsplit('.', 1)[-1]
        if extension in ('mp4', 'm4a'):
            html, final, headers = session.get_page_info(current, allowed_origin=origin)
            if html or 'html' in headers.get('Content-Type', '').lower():
                raise ValueError('학교가 영상 대신 다른 화면을 보내 가져오기를 멈췄어요.')
            check_download_origin(final, origin)
            check_download_url(final)
            return {'chunks': [current], 'origin': origin, 'format': 'mov',
                    'sourceKey': hashlib.sha256(final.encode()).hexdigest(), 'playbackKey': playback_key}
        if extension != 'm3u8' or current in seen:
            raise ValueError('현재 영상 제공 형식은 아직 읽을 수 없어요.')
        seen.add(current)
        payload, response = session.get_bytes(current, allowed_origin=origin, max_bytes=512_000)
        if not payload:
            raise ValueError('학교의 영상 목록이 비어 있어 가져오기를 멈췄어요.')
        try:
            text = payload.decode('utf-8-sig')
        except UnicodeError:
            raise ValueError('학교의 영상 목록을 읽지 못했어요.') from None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or lines[0] != '#EXTM3U':
            raise ValueError('학교의 영상 목록을 읽지 못했어요.')
        for line in lines:
            if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')) and _attributes(line).get('METHOD') != 'NONE':
                raise DownloadRestricted('보호된 영상이라 음성을 가져오지 않았어요.')
        if any(line.startswith(('#EXT-X-BYTERANGE:', '#EXT-X-DISCONTINUITY', '#EXT-X-GAP')) for line in lines):
            raise ValueError('이 영상의 조각 형식은 아직 지원하지 않아요.')
        map_uri = None
        for line in lines:
            if line.startswith('#EXT-X-MAP:'):
                attributes = _attributes(line)
                map_uri = attributes.get('URI')
                if not map_uri or attributes.get('BYTERANGE'):
                    raise ValueError('영상 초기 조각 형식을 확인하지 못했어요.')
                break
        base = response.geturl()
        audio, variants = [], []
        for index, line in enumerate(lines):
            attrs = _attributes(line)
            if line.startswith('#EXT-X-MEDIA:') and attrs.get('TYPE') == 'AUDIO' and attrs.get('URI'):
                audio.append((attrs.get('DEFAULT') == 'YES', attrs.get('AUTOSELECT') == 'YES', attrs.get('URI')))
            if line.startswith('#EXT-X-STREAM-INF:'):
                if index + 1 >= len(lines) or lines[index + 1].startswith('#'):
                    raise ValueError('영상 목록 일부가 비어 있어 가져오기를 멈췄어요.')
                bandwidth = attrs.get('BANDWIDTH', '')
                if not bandwidth.isdigit():
                    raise ValueError('영상 품질 정보를 확인하지 못했어요.')
                variants.append((int(bandwidth), lines[index + 1]))
        if audio or variants:
            if video and not variants:
                raise ValueError('이 강의에서는 화면 영상을 제공하지 않아요.')
            if video:
                selected = max(variants)[1]
            elif audio:
                # Prefer the playlist explicitly marked as the default audio track.
                selected = sorted(audio, key=lambda item: (not item[0], not item[1], item[2]))[0][2]
            else:
                raise DownloadRestricted('음성 전용 스트림이 없어 학교 트래픽 보호를 위해 가져오지 않았어요.')
            current = urljoin(base, selected)
            continue
        if '#EXT-X-ENDLIST' not in lines:
            raise ValueError('진행 중인 영상은 가져오지 않아요.')
        media_chunks = [urljoin(base, line) for line in lines if not line.startswith('#')]
        chunks = ([urljoin(base, map_uri)] if map_uri else []) + media_chunks
        if not chunks or len(chunks) > 4000:
            raise ValueError('영상 길이를 확인하지 못해 가져오기를 멈췄어요.')
        for chunk in chunks:
            check_download_origin(chunk, origin)
            check_download_url(chunk)
            if not map_uri and not urlsplit(chunk).path.lower().endswith('.ts'):
                raise ValueError('이 영상의 조각 형식은 아직 지원하지 않아요.')
        durations = []
        for line in lines:
            if line.startswith('#EXTINF:'):
                try:
                    value = float(line.partition(':')[2].partition(',')[0])
                except ValueError:
                    raise ValueError('영상 조각의 시간을 확인하지 못했어요.') from None
                if not math.isfinite(value) or value <= 0:
                    raise ValueError('영상 조각의 시간이 올바르지 않아요.')
                durations.append(value)
        if len(durations) != len(media_chunks):
            raise ValueError('영상 조각과 시간 정보가 맞지 않아요.')
        times, elapsed = [], 0.0
        for duration in durations:
            times.append([elapsed, elapsed + duration])
            elapsed += duration
        return {'chunks': chunks, 'origin': origin, 'format': 'mp4' if map_uri else 'mpegts',
                'mediaChunkOffset': 1 if map_uri else 0, 'segmentTimes': times,
                'durationSeconds': elapsed, 'playbackKey': playback_key,
                'sourceKey': hashlib.sha256(json.dumps([chunks, times]).encode()).hexdigest()}
    raise ValueError('영상 목록의 연결이 너무 많아 가져오기를 멈췄어요.')


def media_window(plan, start, duration):
    if not all(type(value) in (int, float) and math.isfinite(value) for value in (start, duration)) or start < 0 or not 0 < duration <= 300:
        raise ValueError('강의 구간은 시작 0초 이상, 길이 1–300초로 골라 주세요.')
    if plan['format'] == 'mov':
        return {**plan, 'mediaStartSeconds': 0, 'startSeconds': start, 'endSeconds': start + duration}
    matches = [index for index, (left, right) in enumerate(plan['segmentTimes']) if right > start and left < start + duration]
    if not matches:
        raise ValueError('선택한 시각이 강의 범위를 벗어났어요.')
    first, last = max(0, matches[0] - 1), matches[-1] + 1
    offset = plan.get('mediaChunkOffset', 0)
    selected_chunks = plan['chunks'][offset + first:offset + last]
    if offset:
        selected_chunks = plan['chunks'][:offset] + selected_chunks
    return {**plan, 'chunks': selected_chunks,
            'mediaStartSeconds': plan['segmentTimes'][first][0], 'startSeconds': start,
            'endSeconds': min(start + duration, plan['durationSeconds'])}


def download_media(session, plan, target, progress=None):
    """Bounded batches preserve order and resume only verified chunk batches."""
    chunks = plan['chunks']
    total = 0
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f'.{target.name}.partial')
    manifest = partial.with_name(partial.name + '.json')
    source_key = str(plan.get('sourceKey') or '')
    identity = {'sourceKey': source_key, 'format': plan.get('format'), 'chunks': len(chunks)}

    def clear_partial():
        partial.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)

    completed = 0
    written = 0
    try:
        saved = json.loads(manifest.read_text(encoding='utf-8')) if source_key and manifest.is_file() else None
        if (not isinstance(saved, dict) or saved.get('identity') != identity or
                type(saved.get('completed')) is not int or type(saved.get('bytes')) is not int or
                not 0 <= saved['completed'] <= len(chunks) or saved['bytes'] < 0 or
                not partial.is_file() or partial.stat().st_size < saved['bytes']):
            clear_partial()
            saved = None
        if saved:
            completed, written = saved['completed'], saved['bytes']
            if plan['format'] == 'mov' and completed == 0:
                written = partial.stat().st_size
            else:
                with partial.open('r+b') as stream:
                    stream.truncate(written)
        else:
            clear_partial()
            partial.touch(mode=0o600)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        clear_partial()
        partial.touch(mode=0o600)

    # A direct MP4 has one large chunk. Keep that chunk beside the destination so
    # an interrupted transfer can use HTTP Range instead of restarting it.
    if plan['format'] == 'mov' and hasattr(session, 'stream_bytes_to_file'):
        try:
            existing_bytes = partial.stat().st_size
            manifest_tmp = manifest.with_name(f'.{manifest.name}.{os.getpid()}')
            manifest_tmp.write_text(json.dumps({'identity': identity, 'completed': 0,
                                                'bytes': existing_bytes}, ensure_ascii=False), encoding='utf-8')
            os.replace(manifest_tmp, manifest)
            result = session.stream_bytes_to_file(
                chunks[0], partial, allowed_origin=plan['origin'],
                max_bytes=256_000_000, resume_existing=True,
            )
            size = result['size'] if isinstance(result, dict) else result
            with partial.open('r+b') as stream:
                if size <= 0 or stream.read(8)[4:8] != b'ftyp':
                    raise ValueError('영상 대신 다른 응답이 와서 저장하지 않았어요.')
                stream.flush()
                os.fsync(stream.fileno())
            manifest_tmp.write_text(json.dumps({'identity': identity, 'completed': 1,
                                                'bytes': size}, ensure_ascii=False), encoding='utf-8')
            os.replace(manifest_tmp, manifest)
            os.replace(partial, target)
            manifest.unlink(missing_ok=True)
            if progress:
                progress('강의 영상을 이어받아 저장했어요 · 1/1 조각')
            return
        except HTTPError as error:
            if error.code not in _RETRYABLE_HTTP:
                clear_partial()
            raise
        except (DownloadRestricted, ValueError):
            clear_partial()
            raise

    with tempfile.TemporaryDirectory(prefix='.media-', dir=str(target.parent)) as staging:
        def fetch(item):
            index, url = item
            limit = 256_000_000 if plan['format'] == 'mov' else 32_000_000
            for attempt in range(1, _CHUNK_ATTEMPTS + 1):
                worker = session.fork()
                temporary_file = tempfile.NamedTemporaryFile(prefix='.chunk-', dir=staging, delete=False)
                temporary = Path(temporary_file.name)
                temporary_file.close()
                keep = False
                try:
                    if hasattr(worker, 'stream_bytes_to_file'):
                        result = worker.stream_bytes_to_file(url, temporary, allowed_origin=plan['origin'], max_bytes=limit)
                        size = result['size'] if isinstance(result, dict) else result
                    else:
                        data, _ = worker.get_bytes(url, allowed_origin=plan['origin'], max_bytes=limit)
                        temporary.write_bytes(data or b'')
                        size = len(data or b'')
                    with temporary.open('rb') as stream:
                        header = stream.read(8)
                    valid_header = (plan['format'] == 'mpegts' and header[:1] == b'G')
                    if plan['format'] == 'mp4':
                        valid_header = index == 0 and header[4:8] == b'ftyp' or index > 0
                    if not size or (plan['format'] in ('mpegts', 'mp4') and not valid_header) or (plan['format'] == 'mov' and header[4:8] != b'ftyp'):
                        raise ValueError('영상 대신 다른 응답이 와서 저장하지 않았어요.')
                    keep = True
                    return temporary, size
                except HTTPError as error:
                    retry = error.code in _RETRYABLE_HTTP
                    if getattr(error, 'fp', None) is not None:
                        error.close()
                    if not retry or attempt == _CHUNK_ATTEMPTS:
                        raise
                except (URLError, TimeoutError):
                    if attempt == _CHUNK_ATTEMPTS:
                        raise
                finally:
                    if not keep:
                        temporary.unlink(missing_ok=True)
                time.sleep(0.5 * attempt)

        try:
            with partial.open('r+b') as stream, ThreadPoolExecutor(max_workers=2) as pool:
                stream.seek(written)
                for start in range(completed, len(chunks), 4):
                    for temporary, size in pool.map(fetch, list(enumerate(chunks[start:start + 4], start))):
                        total += size
                        if written + total > 1_000_000_000:
                            raise ValueError('영상이 1GB를 넘어 가져오기를 멈췄어요.')
                        with temporary.open('rb') as source:
                            shutil.copyfileobj(source, stream, length=1024 * 1024)
                        temporary.unlink(missing_ok=True)
                    written += total
                    completed = min(start + 4, len(chunks))
                    stream.flush()
                    os.fsync(stream.fileno())
                    manifest_tmp = manifest.with_name(f'.{manifest.name}.{os.getpid()}')
                    manifest_tmp.write_text(json.dumps({'identity': identity, 'completed': completed,
                                                        'bytes': written}, ensure_ascii=False), encoding='utf-8')
                    os.replace(manifest_tmp, manifest)
                    total = 0
                    if progress and (start == 0 or (start + 4) % 40 == 0 or start + 4 >= len(chunks)):
                        message = '강의 음성을 이어받고 있어요' if start >= 4 or completed else '강의 음성을 가져오고 있어요'
                        progress(f'{message} · {completed}/{len(chunks)} 조각')
            os.replace(partial, target)
            manifest.unlink(missing_ok=True)
        except HTTPError as error:
            # Policy failures are not safe to resume; retryable server failures keep the checkpoint.
            if error.code not in _RETRYABLE_HTTP:
                clear_partial()
            raise
        except (DownloadRestricted, ValueError):
            clear_partial()
            raise
