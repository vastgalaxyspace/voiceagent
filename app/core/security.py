"""Local isolation and explicit production transport/admission boundaries."""
import asyncio
import json
import logging
from time import monotonic
from urllib.parse import urlsplit

from fastapi import WebSocket
from fastapi.responses import JSONResponse

LOCAL_CLIENTS = frozenset({'127.0.0.1', '::1', 'testclient'})
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]', 'testserver']
AUTH_PATHS = frozenset({'/api/v1/auth/login', '/api/v1/auth/register', '/ws/live'})


def allowed_hosts(settings):
    if settings.environment == 'local':
        return ALLOWED_HOSTS
    return [urlsplit(settings.public_origin).hostname, '127.0.0.1', 'localhost']


def websocket_allowed(ws: WebSocket) -> bool:
    settings = ws.app.state.settings
    if settings.environment == 'local':
        if ws.client and ws.client.host not in LOCAL_CLIENTS:
            return False
        scheme = 'https' if ws.url.scheme == 'wss' else 'http'
        expected = f'{scheme}://{ws.headers.get("host")}'
    else:
        if ws.url.scheme != 'wss':
            return False
        expected = settings.public_origin
    # Kotlin can omit Origin. Browser origins must match exactly.
    return ws.headers.get('origin') in (None, expected)


class Admission:
    """One-worker fixed windows. Bounded keys; no eviction bypass on saturation."""
    def __init__(self, settings):
        self.settings = settings
        self.buckets = {}
        self.started = monotonic()
        self.count = self.inflight = 0

    def enter(self, client):
        now = monotonic()
        if now - self.started >= 60:
            self.started, self.count = now, 0
            self.buckets.clear()
        count = self.buckets.get(client, 0)
        if (self.count >= self.settings.auth_global_requests_per_minute
                or count >= self.settings.auth_requests_per_minute
                or self.inflight >= self.settings.auth_max_inflight):
            return False
        self.count += 1
        self.buckets[client] = count + 1
        self.inflight += 1
        return True


class TransportMiddleware:
    def __init__(self, app, settings, operations):
        self.app, self.settings, self.operations = app, settings, operations
        self.admission = Admission(settings)
        self.logger = logging.getLogger('voiceagent.http')
        if settings.environment == 'production' and not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            self.logger.propagate = False

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        http = scope['type'] == 'http'
        production = self.settings.environment == 'production'
        started = monotonic()
        status = 500
        admitted = False
        if http:
            self.operations.inflight += 1

        async def transmit(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                headers = list(message.get('headers', []))
                headers.extend([(b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'),
                                (b'referrer-policy', b'no-referrer')])
                if production:
                    headers.append((b'strict-transport-security', b'max-age=31536000'))
                message = {**message, 'headers': headers}
            await send(message)

        async def reject(code, reason):
            self.operations.rejected += 1
            if http:
                headers = {'Retry-After': '60'} if code == 429 else None
                await JSONResponse({'error': reason}, status_code=code, headers=headers)(scope, receive, transmit)
            else:
                await send({'type': 'websocket.close', 'code': 1008})

        try:
            client = (scope.get('client') or ('', 0))[0]
            path = scope['path']
            if not production and client not in LOCAL_CLIENTS:
                return await reject(403, 'local_prototype_only')
            probe = http and path in ('/health', '/health/ready') and client in ('127.0.0.1', '::1')
            if production:
                if scope['scheme'] not in ('https', 'wss') and not probe:
                    return await reject(400, 'secure_transport_required')
                origin = dict(scope['headers']).get(b'origin')
                if origin is not None and origin.decode('latin-1') != self.settings.public_origin:
                    return await reject(403, 'origin_not_allowed')
                if path.rstrip('/') in AUTH_PATHS:
                    admitted = self.admission.enter(client)
                    if not admitted:
                        return await reject(429, 'authentication_rate_limited')
            if http and production:
                # Bound chunked and missing-length bodies before a handler or
                # password worker runs, without BaseHTTPMiddleware buffering.
                chunks = bytearray()
                try:
                    declared = dict(scope['headers']).get(b'content-length')
                    if declared is not None and int(declared) > self.settings.http_max_body_bytes:
                        return await reject(413, 'request_too_large')
                    async with asyncio.timeout(5):
                        while True:
                            message = await receive()
                            if message['type'] == 'http.disconnect':
                                return
                            chunk = message.get('body', b'')
                            if len(chunks) + len(chunk) > self.settings.http_max_body_bytes:
                                return await reject(413, 'request_too_large')
                            chunks.extend(chunk)
                            if not message.get('more_body'):
                                break
                except TimeoutError:
                    return await reject(408, 'request_body_timeout')
                except ValueError:
                    return await reject(400, 'invalid_content_length')
                delivered = False

                async def buffered_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {'type': 'http.request', 'body': bytes(chunks), 'more_body': False}
                    return await receive()
                await self.app(scope, buffered_receive, transmit)
            else:
                await self.app(scope, receive, transmit)
        finally:
            if admitted:
                self.admission.inflight -= 1
            if http:
                duration = monotonic() - started
                self.operations.inflight -= 1
                self.operations.requests += 1
                self.operations.errors += int(status >= 500)
                self.operations.latency_seconds += duration
                if production:
                    # No URL/query, IP, identity, headers or body in logs.
                    self.logger.info(json.dumps({'event': 'http_request', 'status': status,
                                                 'duration_ms': round(duration * 1000, 3)}))
