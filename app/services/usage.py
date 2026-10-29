from collections import deque
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4
from app.core.pricing import RATES


class Measurements:
    def __init__(self, model: str, usage_mode: str, session_id: str | None = None):
        self.id = session_id or str(uuid4())
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.started = monotonic()
        self.model = model
        self.usage_mode = usage_mode
        self.input_bytes = 0
        self.output_bytes = 0
        self.interruptions = 0
        self.turns = 0
        self.ready_ms = None
        self.usage_events = 0
        self.usage_samples = deque(maxlen=100)
        self.tokens = {}
        self.incomplete_breakdown = False
        self.previous = {}
        self.prompt_bytes = 0
        self.relay_ms = deque(maxlen=2048)
        self.report = None
        self.provider_reconnects = 0
        self.client_reconnects = 0
        self.resume_attempts = 0
        self.discarded_input_packets = 0
        self.connection_index = 0
        self.usage_pending = False
        self.turn_finished = False
        self.input_sequence = 0
        self.response_input_sequence = None
        self.tool_call_count = 0
        self.tool_error_count = 0
        self.tool_cancelled_count = 0
        self.knowledge_result_count = 0

    def mark_provider_activity(self):
        # Mark before awaiting provider I/O: cancellation can occur after the
        # provider accepted data but before the local await returns.
        self.usage_pending = True
        self.turn_finished = False

    def mark_input_activity(self):
        self.input_sequence += 1
        self.mark_provider_activity()

    def mark_output_activity(self):
        if self.response_input_sequence is None:
            self.response_input_sequence = self.input_sequence
        self.mark_provider_activity()

    def mark_turn_complete(self):
        # A completed response cannot acknowledge new input streamed while it
        # was being generated. Keep overlapping/barge-in input uncertain.
        self.turn_finished = (self.response_input_sequence is None
                              or self.response_input_sequence == self.input_sequence)
        self.response_input_sequence = None

    def record_usage(self, metadata, *, final_for_turn=True):
        raw = metadata.model_dump(mode='json', exclude_none=True)
        self.usage_events += 1
        # Only token fields are retained: never content or provider handles.
        sample = {key: raw[key] for key in (
            'prompt_token_count', 'response_token_count', 'total_token_count',
            'thoughts_token_count', 'cached_content_token_count',
            'tool_use_prompt_token_count',
            'prompt_tokens_details', 'response_tokens_details',
        ) if key in raw}
        sample['connection_index'] = self.connection_index
        self.usage_samples.append(sample)
        if final_for_turn:
            self.usage_pending = False
        if 'prompt_token_count' not in sample or 'response_token_count' not in sample:
            self.incomplete_breakdown = True
        current = {}
        for direction, detail_key, total_key in (
            ('input', 'prompt_tokens_details', 'prompt_token_count'),
            ('output', 'response_tokens_details', 'response_token_count'),
        ):
            details = sample.get(detail_key, [])
            counted = 0
            for item in details:
                modality = str(item.get('modality', 'UNKNOWN'))
                count = int(item.get('token_count') or 0)
                if count < 0:
                    self.incomplete_breakdown = True
                    continue
                key = f'{direction}_{modality}'
                current[key] = current.get(key, 0) + count
                counted += count
            if counted != int(sample.get(total_key) or 0):
                self.incomplete_breakdown = True
        if (sample.get('thoughts_token_count') or sample.get('cached_content_token_count')
                or sample.get('tool_use_prompt_token_count')):
            self.incomplete_breakdown = True
        if ('total_token_count' in sample and sample['total_token_count'] !=
                int(sample.get('prompt_token_count') or 0) + int(sample.get('response_token_count') or 0)):
            self.incomplete_breakdown = True
        if self.usage_mode == 'unknown':
            return
        for key, count in current.items():
            if self.usage_mode == 'cumulative':
                previous = self.previous.get(key, 0)
                if count < previous:
                    self.incomplete_breakdown = True
                delta = max(0, count - previous)
            else:
                delta = count
            self.tokens[key] = self.tokens.get(key, 0) + delta
        self.previous.update(current)

    def estimated_cost(self):
        rates = RATES.get(self.model)
        if (self.usage_mode == 'unknown' or self.usage_events == 0
                or self.incomplete_breakdown or rates is None
                or any(key not in rates for key in self.tokens)):
            return None
        return sum(count * rates[key] / 1_000_000 for key, count in self.tokens.items())

    def summary(self, reason: str):
        if self.report is not None:
            return self.report
        estimate = self.estimated_cost()
        complete = estimate is not None and not self.usage_pending
        values = sorted(self.relay_ms)
        self.report = {
            'session_id': self.id, 'started_at': self.started_at,
            'model': self.model, 'end_reason': reason,
            'system_prompt_bytes': self.prompt_bytes,
            'duration_seconds': round(monotonic() - self.started, 3),
            'ready_ms': self.ready_ms,
            'input_audio_seconds': round(self.input_bytes / 32000, 3),
            'generated_audio_seconds': round(self.output_bytes / 48000, 3),
            'interruption_count': self.interruptions, 'turn_count': self.turns,
            'relay_p95_ms': values[min(len(values) - 1, int(len(values) * .95))] if values else None,
            'relay_sample_count': len(values), 'usage_mode': self.usage_mode,
            'usage_event_count': self.usage_events,
            'usage_samples': list(self.usage_samples),
            'usage_samples_truncated': self.usage_events > len(self.usage_samples),
            'aggregated_tokens': self.tokens if self.usage_mode != 'unknown' else None,
            'estimated_model_cost_usd': round(estimate, 8) if complete else None,
            'observed_model_cost_usd': round(estimate, 8) if estimate is not None else None,
            'usage_complete': complete,
            'unreported_provider_activity': self.usage_pending,
            'cost_status': 'estimate_not_invoice' if complete else 'unverified_or_incomplete_usage',
            'pricing_checked_on': '2026-10-18',
            'pricing_source': 'https://ai.google.dev/gemini-api/docs/pricing',
            'provider_reconnect_count': self.provider_reconnects,
            'client_reconnect_count': self.client_reconnects,
            'resume_attempt_count': self.resume_attempts,
            'discarded_input_packets': self.discarded_input_packets,
            'usage_counter_scope': 'resumption_unverified' if self.resume_attempts else 'single_connection',
            'tool_call_count': self.tool_call_count,
            'tool_error_count': self.tool_error_count,
            'tool_cancelled_count': self.tool_cancelled_count,
            'knowledge_result_count': self.knowledge_result_count,
        }
        return self.report
