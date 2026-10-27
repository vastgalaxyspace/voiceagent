"""Full duplex relay with bounded, checkpoint-only provider resumption."""
import asyncio
import json
import logging
from collections import deque
from contextlib import AsyncExitStack
from time import monotonic

import anyio

from app.core.config import Settings
from app.integrations.gemini.retry import transient
from app.services.usage import Measurements
from app.services.live_tools import ARGUMENTS, ToolConnection, ToolSessionEnd

logger = logging.getLogger('voiceagent')


class SessionEnd(Exception):
    def __init__(self, reason: str):
        self.reason = reason


class Reconnect(Exception):
    def __init__(self, reason: str):
        self.reason = reason


class Outbox:
    def __init__(self, limit=64):
        self.items = deque()
        self.available = asyncio.Event()
        self.limit = limit

    def put(self, item):
        if len(self.items) >= self.limit:
            raise SessionEnd('slow_client')
        if isinstance(item, bytes) and sum(len(queued) for queued in self.items if isinstance(queued, bytes)) + len(item) > 480000:
            raise SessionEnd('slow_client')
        self.items.append(item)
        self.available.set()

    def interrupt(self):
        self.items = deque(item for item in self.items if not isinstance(item, bytes))
        if len(self.items) >= self.limit:
            raise SessionEnd('slow_client')
        self.items.appendleft({'type': 'interrupted'})
        self.available.set()

    def reset(self):
        self.items.clear()

    def transcript(self, item):
        # Coalesce replaceable text updates; captions must never exhaust audio's
        # bounded queue or terminate an otherwise healthy voice session.
        self.items = deque(queued for queued in self.items if not (
            isinstance(queued, dict) and queued.get('type') == item['type']
            and queued.get('message_id') == item.get('message_id')))
        if len(self.items) >= self.limit - 4:
            return  # The durable messages API recovers omitted UI updates.
        self.items.append(item)
        self.available.set()

    async def get(self):
        while not self.items:
            self.available.clear()
            await self.available.wait()
        return self.items.popleft()


class Relay:
    def __init__(self, channel, settings: Settings, provider, prompt: str,
                 measurements: Measurements, *, auth_stop=None, auth_seconds=None, on_state=None,
                 max_cost_usd: float | None = None, cost_margin_ratio: float = 0, tool_session=None,
                 output_audio_recorder=None, client_vad=False, transcripts=None):
        self.channel, self.settings, self.provider = channel, settings, provider
        self.prompt, self.measurements = prompt, measurements
        self.outbox = Outbox()
        self.inbox = asyncio.Queue(maxsize=8)
        self.ready = False
        self.has_ready = False
        self.last_activity = monotonic()
        self.playback_until = self.last_activity
        self.auth_stop, self.auth_seconds = auth_stop, auth_seconds
        self.on_state = on_state
        self._resume_handle = None  # Secret provider state: never logged/persisted/exposed.
        self.lease_deadline = None
        self.max_cost_usd = max_cost_usd
        self.cost_margin_ratio = cost_margin_ratio
        self.cost_usage_observed_at = None
        self.tool_session = tool_session
        self.output_audio_recorder = output_audio_recorder
        self.client_vad = client_vad
        self.client_speaking = False
        self.transcripts = transcripts

    async def state(self, value):
        if self.on_state is not None:
            await self.on_state(value)

    async def save_output_audio(self, *, partial=False):
        if self.output_audio_recorder is None:
            return
        try:
            await self.output_audio_recorder.complete_turn(partial=partial)
        except OSError:
            logger.warning('Could not save debug output audio for session %s', self.measurements.id)
            self.output_audio_recorder = None

    def flush_audio(self):
        self.ready = False
        self.client_speaking = False
        self.playback_until = monotonic()
        self.outbox.reset()
        while not self.inbox.empty():
            self.inbox.get_nowait()
            self.measurements.discarded_input_packets += 1

    async def receive_client(self):
        while True:
            message = await self.channel.receive()
            kind = message['type']
            if kind == 'session.stop':
                raise SessionEnd(self.channel.stop_reason)
            if kind == 'client.detached':
                self.flush_audio()
                continue
            if kind == 'client.attached':
                if self.channel.epoch > 1:
                    self.measurements.client_reconnects += 1
                continue
            audio = message.get('bytes')
            if audio is not None:
                if not audio or len(audio) % 2 or len(audio) > 3200:
                    raise SessionEnd('invalid_audio')
                if not self.ready:
                    if self.has_ready:
                        self.measurements.discarded_input_packets += 1
                        continue
                    raise SessionEnd('invalid_audio')
                try:
                    if self.client_vad and not self.client_speaking:
                        raise SessionEnd('audio_outside_activity')
                    self.inbox.put_nowait((audio, monotonic()))
                except asyncio.QueueFull:
                    raise SessionEnd('input_backpressure') from None
                samples = memoryview(audio).cast('h')
                if sum(sample * sample for sample in samples) / len(samples) > 327 ** 2:
                    self.last_activity = monotonic()
            else:
                text = message.get('text', '')
                if len(text) > 1024:
                    raise SessionEnd('invalid_message')
                try:
                    control = json.loads(text)
                except ValueError:
                    raise SessionEnd('invalid_message') from None
                if control == {'type': 'stop'}:
                    raise SessionEnd('user_stopped')
                if control == {'type': 'ping'}:
                    self.outbox.put({'type': 'pong'})
                    continue
                if self.client_vad and control in ({'type': 'speech_start'}, {'type': 'speech_end'}):
                    if not self.ready:
                        continue
                    starting = control['type'] == 'speech_start'
                    if starting == self.client_speaking:
                        raise SessionEnd('invalid_activity_sequence')
                    self.client_speaking = starting
                    self.last_activity = monotonic()
                    try:
                        self.inbox.put_nowait((control['type'], monotonic()))
                    except asyncio.QueueFull:
                        raise SessionEnd('input_backpressure') from None
                    continue
                if control != {'type': 'audio_end'} or self.client_vad:
                    raise SessionEnd('invalid_message')
                if not self.ready:
                    continue
                try:
                    self.inbox.put_nowait((None, monotonic()))
                except asyncio.QueueFull:
                    raise SessionEnd('input_backpressure') from None

    async def send_client(self):
        while True:
            item = await self.outbox.get()
            if isinstance(item, bytes):
                await self.channel.send_bytes(item)
            else:
                await self.channel.send_json(item)

    async def upload(self, connection):
        while True:
            audio, received = await self.inbox.get()
            async with asyncio.timeout(self.settings.io_timeout_seconds):
                self.measurements.mark_input_activity()
                if audio == 'speech_start':
                    if self.transcripts:
                        self.transcripts.input_started()
                    await connection.activity_start()
                elif audio == 'speech_end':
                    if self.transcripts:
                        self.transcripts.input_ended()
                    await connection.activity_end()
                elif audio is None:
                    if self.transcripts:
                        self.transcripts.input_ended()
                    await connection.end_audio()
                else:
                    if self.transcripts and not self.client_vad:
                        self.transcripts.input_started()
                    await connection.send_audio(audio)
                    self.measurements.input_bytes += len(audio)
                    self.measurements.relay_ms.append(round((monotonic() - received) * 1000, 3))

    async def download(self, connection, tools=None):
        async for message in connection.messages():
            if message.tool_call_cancellation is not None and tools is not None:
                tools.cancel(message.tool_call_cancellation.ids)
            if message.tool_call is not None:
                # A generated function call is provider output even if it is
                # cancelled or rejected before any function result is sent.
                self.measurements.mark_output_activity()
                if tools is None:
                    raise SessionEnd('tools_not_enabled')
                tools.submit(message.tool_call.function_calls)
            update = message.session_resumption_update
            if update is not None:
                # False explicitly invalidates the previous checkpoint: replaying
                # an older checkpoint could silently omit in-flight conversation.
                self._resume_handle = update.new_handle if update.resumable and update.new_handle else None
            content = message.server_content
            if content and self.transcripts:
                if content.model_turn and not content.interrupted:
                    self.transcripts.output_started()
                self.transcripts.receive(content)
            if content and (content.model_turn or content.interrupted):
                self.measurements.mark_output_activity()
            if content and content.turn_complete:
                self.measurements.mark_turn_complete()
            if message.usage_metadata:
                self.measurements.record_usage(
                    message.usage_metadata, final_for_turn=self.measurements.turn_finished,
                )
                self.cost_usage_observed_at = monotonic()
                if self.max_cost_usd is not None:
                    estimate = self.measurements.estimated_cost()
                    if estimate is None:
                        raise SessionEnd('cost_tracking_unavailable')
                    if estimate >= self.max_cost_usd * (1 - self.cost_margin_ratio):
                        raise SessionEnd('cost_limit')
            if content:
                if content.interrupted:
                    self.measurements.interruptions += 1
                    self.playback_until = monotonic()
                    self.outbox.interrupt()
                    await self.save_output_audio(partial=True)
                if content.model_turn and not content.interrupted:
                    for part in content.model_turn.parts or []:
                        blob = part.inline_data
                        if blob and blob.data and (blob.mime_type or '').startswith('audio/pcm'):
                            self.measurements.output_bytes += len(blob.data)
                            self.playback_until = max(self.playback_until, monotonic()) + len(blob.data) / 48000
                            if self.output_audio_recorder is not None:
                                self.output_audio_recorder.append(blob.data)
                            self.outbox.put(blob.data)
                if content.turn_complete:
                    self.measurements.turns += 1
                    await self.save_output_audio()
                    self.outbox.put({'type': 'turn_complete'})
            if message.go_away is not None:
                raise Reconnect('provider_go_away')
        raise ConnectionError('Provider receive stream ended')

    async def connect_once(self, handle):
        stack = AsyncExitStack()
        tasks = set()
        try:
            async def setup():
                async with asyncio.timeout(self.settings.provider_setup_seconds):
                    return await stack.enter_async_context(self.provider.connect(self.prompt, resume_handle=handle))

            opening = asyncio.create_task(setup())
            detached = asyncio.create_task(self.channel.disconnected.wait())
            tasks.update({opening, detached})
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if detached in done:
                raise Reconnect('client_disconnected')
            connection = opening.result()
            self.client_speaking = False
            self.measurements.connection_index += 1
            await self.state('active')
            first = not self.has_ready
            if first:
                self.measurements.ready_ms = round((monotonic() - self.measurements.started) * 1000, 3)
            else:
                self.measurements.provider_reconnects += 1
                # Resumed usage-counter semantics need their own live calibration.
                self.measurements.incomplete_breakdown = True
            self.ready = self.has_ready = True
            if self.cost_usage_observed_at is None:
                self.cost_usage_observed_at = monotonic()
            greeting_pending = first and callable(getattr(connection, 'greet', None))
            self.outbox.put({
                'greeting_pending': greeting_pending,
                'type': 'ready' if first else 'resumed', 'protocol_version': 3,
                'session_id': self.measurements.id, 'model': self.settings.gemini_model,
                'input': {'encoding': 'pcm_s16le', 'sample_rate': 16000, 'channels': 1},
                'speech_detection': 'client' if self.client_vad else 'server',
                'output': {'encoding': 'pcm_s16le', 'sample_rate': 24000, 'channels': 1},
                'max_seconds': self.settings.session_max_seconds,
                'remaining_seconds': max(0, self.settings.session_max_seconds - (monotonic() - self.measurements.started)),
                'reconnect_grace_seconds': self.settings.client_reconnect_grace_seconds,
                'heartbeat_interval_seconds': min(5, self.settings.client_transport_timeout_seconds / 3),
                'tools': list(ARGUMENTS) if self.tool_session else [],
            })
            if greeting_pending:
                # Count the prompt as provider input before awaiting transmission.
                # Never repeat it on checkpoint resumption or app reattachment.
                self.measurements.mark_input_activity()
                async with asyncio.timeout(self.settings.io_timeout_seconds):
                    await connection.greet()
            tools = ToolConnection(self.tool_session, connection, self.outbox) if self.tool_session else None
            if tools is not None:
                tasks.add(asyncio.create_task(tools.run()))
            tasks.update({asyncio.create_task(self.upload(connection)), asyncio.create_task(self.download(connection, tools))})
            done, _ = await asyncio.wait(tasks - {opening}, return_when=asyncio.FIRST_COMPLETED)
            if detached in done:
                raise Reconnect('client_disconnected')
            for task in done:
                task.result()
        finally:
            self.ready = False
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                try:
                    async with asyncio.timeout(self.settings.io_timeout_seconds):
                        await asyncio.gather(*tasks, return_exceptions=True)
                finally:
                    async with asyncio.timeout(self.settings.io_timeout_seconds * 2):
                        await stack.aclose()

    async def provider_loop(self):
        handle = None
        while True:
            try:
                if self.channel.stop_reason:
                    raise SessionEnd(self.channel.stop_reason)
                if self.auth_stop is not None and self.auth_stop.is_set():
                    raise SessionEnd('auth_revoked')
                if self.auth_seconds is not None and monotonic() - self.measurements.started >= self.auth_seconds:
                    raise SessionEnd('auth_expired')
                await self.connect_once(handle)
                raise SessionEnd('provider_disconnected')
            except SessionEnd:
                raise
            except ToolSessionEnd as exc:
                raise SessionEnd(exc.reason) from None
            except Exception as exc:
                # Keep diagnostics useful without logging provider messages, keys, or audio.
                logger.warning('Provider connection failed: exception=%s code=%s',
                               type(exc).__name__, getattr(exc, 'code', None))
                if not isinstance(exc, Reconnect) and not transient(exc):
                    raise SessionEnd('resume_rejected' if handle else 'provider_error') from None
                reason = exc.reason if isinstance(exc, Reconnect) else 'provider_disconnected'
                if not self.has_ready:
                    raise SessionEnd('io_or_setup_timeout' if isinstance(exc, TimeoutError) else 'resume_unavailable') from None
                if self.max_cost_usd is not None:
                    # Cross-connection usage counter semantics are not calibrated.
                    raise SessionEnd('cost_tracking_unavailable') from None
                self.flush_audio()
                if self.transcripts:
                    self.transcripts.connection_gap()
                await self.state('reconnecting')
                if not self._resume_handle:
                    raise SessionEnd('provider_go_away' if reason == 'provider_go_away' else 'resume_unavailable') from None
                self.outbox.put({'type': 'reconnecting', 'reason': reason})
                await self.channel.connected.wait()
                if self.measurements.resume_attempts >= self.settings.provider_resume_attempts:
                    raise SessionEnd('resume_attempts_exhausted') from None
                self.measurements.resume_attempts += 1
                self.measurements.incomplete_breakdown = True
                handle = self._resume_handle
                # No input is retained during the gap. Never replay uncertain audio.
                delay = min(2, self.settings.provider_resume_backoff_seconds * (2 ** (self.measurements.resume_attempts - 1)))
                await asyncio.sleep(delay)

    async def watch(self):
        while True:
            await asyncio.sleep(.05)
            now = monotonic()
            if (self.max_cost_usd is not None and self.cost_usage_observed_at is not None
                    and now - self.cost_usage_observed_at >= self.settings.cost_usage_timeout_seconds):
                raise SessionEnd('cost_tracking_unavailable')
            if self.channel.stop_reason:
                raise SessionEnd(self.channel.stop_reason)
            if self.lease_deadline is not None and now >= self.lease_deadline():
                raise SessionEnd('lease_lost')
            if self.auth_stop is not None and self.auth_stop.is_set():
                raise SessionEnd('auth_revoked')
            if self.auth_seconds is not None and now - self.measurements.started >= self.auth_seconds:
                raise SessionEnd('auth_expired')
            if now - self.measurements.started >= self.settings.session_max_seconds:
                raise SessionEnd('duration_limit')
            if self.channel.socket is None and now - self.channel.detached_at >= self.settings.client_reconnect_grace_seconds:
                raise SessionEnd('client_reconnect_timeout')
            if self.has_ready and self.channel.socket is not None and now - self.channel.last_received >= self.settings.client_transport_timeout_seconds:
                await self.channel.expire_transport()
            if now - max(self.last_activity, self.playback_until) >= self.settings.session_idle_seconds:
                raise SessionEnd('idle_timeout')

    async def run(self):
        tasks = set()
        reason = 'provider_error'
        try:
            tasks = {asyncio.create_task(coroutine) for coroutine in (
                self.receive_client(), self.send_client(), self.watch(), self.provider_loop(),
            )}
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except SessionEnd as exc:
            reason = exc.reason
        except TimeoutError:
            reason = 'io_or_setup_timeout'
        except asyncio.CancelledError:
            reason = 'server_shutdown'
        except Exception:
            reason = 'provider_error'
        finally:
            self._resume_handle = None
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                try:
                    async with asyncio.timeout(self.settings.io_timeout_seconds * 3):
                        await asyncio.gather(*tasks, return_exceptions=True)
                finally:
                    if self.tool_session is not None:
                        self.tool_session.clear()
                    if self.output_audio_recorder is not None:
                        await self.save_output_audio(partial=True)
                    if self.transcripts is not None:
                        await self.transcripts.close()
        if reason == 'cost_tracking_unavailable':
            self.measurements.incomplete_breakdown = True
        return self.measurements.summary(reason)
