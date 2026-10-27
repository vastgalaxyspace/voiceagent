"""Collect provider transcript deltas without putting database I/O on the audio path."""
import asyncio
import logging
from collections import deque
from uuid import uuid4

from app.db.base import utcnow
from app.repositories import transcripts as repository

logger = logging.getLogger('voiceagent')


class TranscriptCollector:
    MAX_MESSAGES = 512
    MAX_TEXT = 32000

    def __init__(self, database, conversation_id, owner, emit, *, client_vad=False):
        self.database, self.conversation_id, self.owner = database, conversation_id, owner
        self.emit = emit
        self.sequence = 0
        self.users = deque()
        self.assistant = None
        self.pending = {}
        self.changed = asyncio.Event()
        self.closing = False
        self.incomplete = False
        self.task = None
        self.input_open = False
        self.client_vad = client_vad

    def start(self):
        self.task = asyncio.create_task(self.writer())

    def new(self, role):
        if self.sequence >= self.MAX_MESSAGES:
            self.incomplete = True
            return None
        self.sequence += 1
        now = utcnow()
        return dict(id=uuid4(), conversation_id=self.conversation_id, sequence=self.sequence,
                    role=role, text='', state='partial', revision=0,
                    created_at=now, updated_at=now, completed_at=None)

    def input_started(self):
        if not self.input_open:
            # Empty VAD activities are never persisted as messages. Delayed text
            # can populate the current speech slot; audio-only events are not text.
            while self.users:
                row = self.users.pop()
                if row['text']:
                    self.finish(row)
            row = self.new('user')
            if row is not None:
                self.users.append(row)
            self.input_open = True

    def input_ended(self):
        self.input_open = False

    def output_started(self):
        if not self.client_vad:
            # For server VAD, provider output supplies an input boundary.
            self.input_ended()
        if self.assistant is None:
            self.assistant = self.new('assistant')

    def publish(self, row):
        if not row or not row['text'].strip():
            return
        row['revision'] += 1
        row['updated_at'] = utcnow()
        snapshot = dict(row)
        self.pending[row['id']] = snapshot
        self.changed.set()
        wire = {key: value.isoformat() if hasattr(value, 'isoformat') else str(value)
                if key in ('id', 'conversation_id') else value for key, value in snapshot.items()}
        self.emit(dict(wire, type='transcript', message_id=wire['id']))

    def finish(self, row, state='complete'):
        if row and row['state'] == 'partial':
            row['state'] = state
            row['completed_at'] = utcnow() if state != 'partial' else None
            self.publish(row)

    def append(self, row, text):
        if row is None or not text:
            return
        # Gemini's transcription text is streamed as deltas. Never deduplicate by
        # text: repeated spoken words can be intentional.
        remaining = self.MAX_TEXT - len(row['text'])
        if len(text) > remaining:
            self.incomplete = True
        row['text'] += text[:remaining].replace('\x00', '')
        self.publish(row)

    def receive(self, content):
        incoming = getattr(content, 'input_transcription', None)
        if incoming is not None:
            if not self.users and incoming.text:
                row = self.new('user')
                if row is not None:
                    self.users.append(row)
            if self.users:
                row = self.users[0]
                self.append(row, incoming.text or '')
                if getattr(incoming, 'finished', False):
                    self.finish(row)
                    self.users.popleft()
        outgoing = getattr(content, 'output_transcription', None)
        if outgoing is not None:
            self.output_started()
            self.append(self.assistant, outgoing.text or '')
        if getattr(content, 'interrupted', False):
            self.finish(self.assistant, 'interrupted')
        if getattr(content, 'turn_complete', False):
            self.finish(self.assistant)
            self.assistant = None
            # Do not assign delayed input to the model turn. Only finalize input
            # already transcribed after the corresponding microphone activity ends.
            if not self.input_open:
                for row in self.users:
                    if row['text']:
                        self.finish(row)
                # Keep the stable user slot for late fragments/finished markers.
                # A new microphone activity or explicit input finished replaces it.

    def connection_gap(self):
        self.input_open = False
        if self.assistant and self.assistant['text'] and self.assistant['state'] == 'partial':
            self.incomplete = True
            self.publish(self.assistant)
        # Keep stable message IDs across provider resumption.

    async def writer(self):
        while True:
            await self.changed.wait()
            self.changed.clear()
            if not self.closing:
                await asyncio.sleep(.35)
            batch = list(self.pending.values())
            if batch:
                try:
                    async with asyncio.timeout(3):
                        saved = await repository.save(self.database, self.conversation_id, self.owner, batch)
                    if not saved:
                        self.incomplete = True
                        return
                    for row in batch:
                        current = self.pending.get(row['id'])
                        if current and current['revision'] == row['revision']:
                            self.pending.pop(row['id'], None)
                        self.emit({'type': 'transcript_saved', 'conversation_id': str(self.conversation_id),
                                   'message_id': str(row['id']), 'revision': row['revision']})
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Do not log transcript content or database parameters.
                    logger.warning('Transcript checkpoint failed for conversation %s', self.conversation_id)
                    self.changed.set()
                    await asyncio.sleep(.5)
            if self.closing and not self.pending:
                return
            if self.pending:
                self.changed.set()

    async def close(self):
        for row in list(self.users) + ([self.assistant] if self.assistant else []):
            if row['text'] and row['state'] == 'partial':
                self.publish(row)
        self.closing = True
        self.changed.set()
        if self.task is not None:
            try:
                await asyncio.wait_for(self.task, timeout=12)
            except Exception:
                self.incomplete = True
        if self.pending:
            self.incomplete = True
