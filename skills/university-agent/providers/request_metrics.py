"""Opt-in HTTP counters; never retain URLs, headers, credentials or bodies."""
from collections import Counter, deque
from contextlib import contextmanager
from contextvars import ContextVar
import threading
import time
from urllib.request import BaseHandler


current_metrics = ContextVar('tls_request_metrics', default=None)


@contextmanager
def measure_requests(metrics):
    token = current_metrics.set(metrics)
    try:
        yield metrics
    finally:
        current_metrics.reset(token)


class RequestMetrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.local = threading.local()
        self.started = time.monotonic()
        self.requests = Counter()
        self.statuses = Counter()
        self.body_bytes = Counter()
        self.active = self.peak = self.peak_rps = 0
        self.arrivals = deque()

    def start(self, kind):
        with self.lock:
            now = time.monotonic()
            self.requests[kind] += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.arrivals.append(now)
            while self.arrivals and self.arrivals[0] <= now - 1:
                self.arrivals.popleft()
            self.peak_rps = max(self.peak_rps, len(self.arrivals))
            token = [False]
            self.local.pending = token
            return token

    def finish(self, token, status):
        with self.lock:
            if token is not None and not token[0]:
                token[0] = True
                self.active -= 1
                self.statuses[str(status)] += 1

    def failed(self):
        self.finish(getattr(self.local, 'pending', None), 'transport_error')

    def received(self, kind, size):
        with self.lock:
            self.body_bytes[kind] += size

    def snapshot(self):
        with self.lock:
            return {
                'requests': sum(self.requests.values()), 'requests_by_kind': dict(self.requests),
                'response_body_bytes': sum(self.body_bytes.values()),
                'response_body_bytes_by_kind': dict(self.body_bytes), 'statuses': dict(self.statuses),
                'peak_open_requests': self.peak, 'peak_requests_per_second': self.peak_rps,
                'elapsed_seconds': round(time.monotonic() - self.started, 4),
            }


class MetricsHandler(BaseHandler):
    # Observe redirects and HTTP errors before urllib handles them.
    handler_order = 490

    def __init__(self, metrics):
        self.metrics = metrics

    def http_request(self, request):
        request._metrics_token = self.metrics.start(getattr(request, 'metrics_kind', 'page'))
        return request

    https_request = http_request

    def http_response(self, request, response):
        self.metrics.finish(request._metrics_token, response.code)
        read = response.read
        kind = getattr(request, 'metrics_kind', 'page')

        def measured_read(*args, **kwargs):
            data = read(*args, **kwargs)
            self.metrics.received(kind, len(data))
            return data

        response.read = measured_read
        return response

    https_response = http_response
