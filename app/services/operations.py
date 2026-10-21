"""Bounded, process-local operational counters; never stores request content."""
from time import monotonic


class Operations:
    def __init__(self):
        self.started = monotonic()
        self.requests = self.errors = self.rejected = self.inflight = 0
        self.latency_seconds = 0

    def snapshot(self):
        return {'uptime_seconds': round(monotonic() - self.started, 3),
                'http_request_count': self.requests, 'http_error_count': self.errors,
                'transport_rejection_count': self.rejected, 'http_inflight': self.inflight,
                'mean_http_seconds': round(self.latency_seconds / self.requests, 6) if self.requests else None}
