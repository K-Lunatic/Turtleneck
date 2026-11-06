"""Read-only live resource-detail comparison; never download original file bodies."""
from copy import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'tests')]
from benchmark_tls_resources import load_stage05
from providers.credentials import load
from providers.moodle_provider import MoodleTLSProvider
from providers.moodle_session import MoodleSession
from providers.request_metrics import RequestMetrics


def main():
    username, password = load()
    auth_metrics = RequestMetrics()
    auth = MoodleSession(metrics=auth_metrics)
    auth.login(username, password)
    del password
    source = Path(os.environ.get('UNIVERSITY_AGENT_DB', Path.home() / '.university-agent/university.db'))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None

    def session(metrics):
        child = MoodleSession(metrics=metrics)
        for cookie in auth.cookies:
            child.cookies.set_cookie(copy(cookie))
        child.logged_in = True
        return child

    setup_metrics = RequestMetrics()
    setup = MoodleTLSProvider(session(setup_metrics))
    preflight = setup.preflight(username)
    courses = setup.get_courses(username)
    def count(course):
        return len(set(re.findall(r'/mod/(?:resource|ubfile)/view\.php\?id=(\d+)', setup._course_page(course))))
    course = max(courses, key=count)
    if not count(course):
        raise RuntimeError('No resource activities are available for comparison.')
    notices = setup.for_courses(username, {course['id']}).get_notices(username)
    report = {'measurement': 'live TLS resource-detail resolution only; metadata mode',
              'resources_in_selected_course': count(course), 'courses_in_preflight': len(preflight['courseIds']),
              'authentication_setup': auth_metrics.snapshot(), 'preflight_and_notices_setup': setup_metrics.snapshot()}
    with tempfile.TemporaryDirectory(prefix='tls-resource-measure-') as directory:
        old_class = load_stage05(directory).MoodleTLSProvider
        baseline_rows = None
        for label, provider_class in (('before', old_class), ('after', MoodleTLSProvider)):
            metrics = RequestMetrics()
            provider = provider_class(session(metrics))
            provider._courses = [course]
            provider._course_pages = setup._course_pages.copy()
            kwargs = {'notices': notices, 'download_new_files': False}
            if label == 'after':
                eligible = [row for row in baseline_rows if row['downloadStatus'] != 'PROHIBITED']
                selected = (eligible or baseline_rows)[0]['id']
                kwargs.update(resource_ids={selected}, detail_course_ids=set())
            rows = provider.get_resources(username, **kwargs)
            report[label] = metrics.snapshot()
            if label == 'before':
                baseline_rows = rows
                report['resource_records_before'] = len(rows)
            else:
                report['target_results_equal'] = rows == [row for row in baseline_rows if row['id'] == selected]
                report['selected_count'] = len(rows)
    report['source_db_bytes_unchanged'] = source_hash is None or hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    for field in ('requests', 'response_body_bytes', 'elapsed_seconds'):
        report[field + '_reduction_percent'] = round((1 - report['after'][field] / report['before'][field]) * 100, 2) if report['before'][field] else None
    report['notes'] = ['Before: every resource detail in the course. After: one selected resource detail.',
                       'Common authentication, all-course preflight and selected-course notice reads excluded from comparison.',
                       'Same cached course page, notices and authenticated account; sequential single samples.',
                       'No CLI end-to-end timing, no actual file-body transfer, and no writes to user DB.',
                       'Only aggregate metrics/equality flags are saved; no course or resource IDs, URLs, cookies or bodies.']
    target = REPO / 'tls-optimization-stage6-results/live.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert report['target_results_equal'] and report['source_db_bytes_unchanged']
    assert report['before']['requests_by_kind'].get('file', 0) == report['after']['requests_by_kind'].get('file', 0) == 0
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
