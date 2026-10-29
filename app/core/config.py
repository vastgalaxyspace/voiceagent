from pathlib import Path
from decimal import Decimal
from typing import Literal
import os

from pydantic import Field, HttpUrl, SecretStr, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.core.paths import OUTPUT_AUDIO_ROOT, PROJECT_ROOT, REPORTS_ROOT
from app.core.pricing import RATES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / '.env', env_file_encoding='utf-8', extra='ignore',
        hide_input_in_errors=True,
        secrets_dir=os.environ.get('VOICEAGENT_SECRETS_DIR'),
    )

    environment: Literal['local', 'tunnel', 'production'] = 'local'
    public_origin: str = ''
    registration_enabled: bool = True
    enable_api_docs: bool = True
    enable_test_harness: bool = True
    http_max_body_bytes: int = Field(default=32768, ge=8192, le=65536)
    auth_requests_per_minute: int = Field(default=10, ge=1, le=100)
    auth_global_requests_per_minute: int = Field(default=60, ge=1, le=1000)
    auth_max_inflight: int = Field(default=4, ge=1, le=8)

    gemini_api_key: SecretStr = SecretStr('')
    gemini_model: str = 'gemini-3.8-live'
    gemini_api_version: str = 'v1beta'
    voice_start_sensitivity: Literal['low', 'high'] = 'low'
    voice_prefix_padding_ms: int = Field(default=200, ge=0, le=500)
    voice_silence_duration_ms: int = Field(default=600, ge=100, le=2000)
    # Some Live endpoints reject this optional setup field entirely.
    voice_proactive_audio: bool = False
    session_max_seconds: float = Field(default=300, gt=0, le=600)
    session_idle_seconds: float = Field(default=60, gt=0, le=600)
    provider_setup_seconds: float = Field(default=20, gt=0, le=60)
    io_timeout_seconds: float = Field(default=5, gt=0, le=10)
    context_compression: bool = False
    context_trigger_tokens: int = Field(default=16000, ge=2048, le=100000)
    context_target_tokens: int = Field(default=8000, ge=1024, le=50000)
    max_active_sessions: int = Field(default=1, ge=1, le=1000)
    max_global_sessions: int = Field(default=100, ge=1, le=10000)
    continuation_max_bytes: int = Field(default=12000, ge=1024, le=32000)
    summary_model: str = ''
    summary_min_messages: int = Field(default=12, ge=2, le=100)
    save_reports: bool = False
    reports_directory: Path = REPORTS_ROOT
    save_output_audio: bool = False
    output_audio_directory: Path = OUTPUT_AUDIO_ROOT
    usage_mode: Literal['unknown', 'per_response', 'cumulative'] = 'unknown'
    database_url: SecretStr = SecretStr('')
    migration_database_url: SecretStr = SecretStr('')
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    auth_session_hours: int = Field(default=24, ge=1, le=168)
    active_prompt_version: str = Field(default='phase2-v1', min_length=1, max_length=64)
    client_reconnect_grace_seconds: float = Field(default=10, gt=0, le=30)
    client_transport_timeout_seconds: float = Field(default=15, ge=.1, le=60)
    provider_resume_attempts: int = Field(default=3, ge=0, le=5)
    provider_resume_backoff_seconds: float = Field(default=.25, ge=0, le=2)
    lease_seconds: float = Field(default=30, ge=2, le=120)
    lease_heartbeat_seconds: float = Field(default=5, ge=.1, le=30)
    daily_connected_seconds: int = Field(default=900, ge=60, le=86400)
    minimum_session_seconds: float = Field(default=30, ge=.1, le=600)
    conversation_creations_per_hour: int = Field(default=10, ge=0, le=100)
    cost_guard_enabled: bool = False
    daily_estimated_cost_limit_usd: Decimal = Field(default=Decimal('0.60'), ge=Decimal('0.00000001'), le=1000,
                                                  decimal_places=8)
    session_estimated_cost_limit_usd: Decimal = Field(default=Decimal('0.20'), ge=Decimal('0.00000001'), le=100,
                                                    decimal_places=8)
    cost_guard_margin_ratio: Decimal = Field(default=Decimal('0.20'), ge=0, le=Decimal('0.50'))
    cost_usage_timeout_seconds: float = Field(default=30, ge=.1, le=120)
    memory_max_items: int = Field(default=20, ge=1, le=100)
    memory_prompt_max_items: int = Field(default=5, ge=1, le=10)
    memory_prompt_max_bytes: int = Field(default=1800, ge=128, le=4000)
    live_tools_enabled: bool = False
    tool_policy_version: Literal['read-v1'] = 'read-v1'
    tool_max_calls: int = Field(default=10, ge=1, le=50)
    tool_timeout_seconds: float = Field(default=2, ge=.1, le=10)
    tool_result_max_bytes: int = Field(default=4096, ge=1024, le=16000)
    knowledge_max_private_entries: int = Field(default=50, ge=1, le=500)
    knowledge_max_shared_entries: int = Field(default=200, ge=1, le=2000)

    @model_validator(mode='after')
    def validate_lease_timing(self):
        if self.environment == 'tunnel':
            if not self.public_origin:
                raise ValueError('Tunnel access requires PUBLIC_ORIGIN')
            if self.save_output_audio or self.save_reports:
                raise ValueError('Tunnel access requires local audio and report files disabled')
        if self.context_target_tokens >= self.context_trigger_tokens:
            raise ValueError('Context target must be smaller than compression trigger')
        if self.environment == 'production':
            if not self.public_origin:
                raise ValueError('Production requires PUBLIC_ORIGIN')
            if not self.database_url.get_secret_value().startswith('postgresql+asyncpg://'):
                raise ValueError('Production requires a PostgreSQL runtime connection')
            try:
                database = make_url(self.database_url.get_secret_value())
            except Exception:
                raise ValueError('Invalid production database connection') from None
            if (not database.host or '/' in database.host or not database.username or not database.database
                    or database.query.get('ssl') != 'verify-full'
                    or set(database.query) - {'ssl', 'prepared_statement_cache_size'}):
                raise ValueError('Production requires an explicit PostgreSQL host, user, database and ssl=verify-full')
            if not self.gemini_api_key.get_secret_value():
                raise ValueError('Production requires a Gemini credential')
            if self.migration_database_url.get_secret_value():
                raise ValueError('Owner credentials must not be loaded by the production runtime')
            if (self.registration_enabled or self.enable_api_docs or self.enable_test_harness
                    or self.save_reports or self.save_output_audio):
                raise ValueError('Production requires registration, API docs, test harness and local file output disabled')
        if self.lease_heartbeat_seconds * 3 > self.lease_seconds:
            raise ValueError('Lease duration must be at least three heartbeat intervals')
        if self.minimum_session_seconds > self.session_max_seconds:
            raise ValueError('Minimum session duration cannot exceed the session maximum')
        if self.session_estimated_cost_limit_usd > self.daily_estimated_cost_limit_usd:
            raise ValueError('Per-session cost limit cannot exceed the daily cost limit')
        if self.cost_guard_enabled and self.usage_mode == 'unknown':
            raise ValueError('Cost guard requires a verified per_response or cumulative usage mode')
        if self.cost_guard_enabled and self.gemini_model not in RATES:
            raise ValueError('Cost guard requires a configured price table for the selected model')
        if self.live_tools_enabled and self.gemini_model not in ('gemini-3.8-live', 'gemini-3.1-flash-live-preview'):
            raise ValueError('Live tools require a supported Live model')
        return self

    @field_validator('public_origin')
    @classmethod
    def validate_public_origin(cls, value):
        if not value:
            return ''
        url = TypeAdapter(HttpUrl).validate_python(value)
        if (url.scheme != 'https' or url.username or url.password or url.query or url.fragment
                or url.path not in ('', '/') or '*' in url.host):
            raise ValueError('PUBLIC_ORIGIN must be an HTTPS origin without credentials, path, query or fragment')
        return str(url).rstrip('/')

    @field_validator('database_url', 'migration_database_url')
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if url and not url.startswith(('postgresql+asyncpg://', 'sqlite+aiosqlite://')):
            raise ValueError('Use postgresql+asyncpg:// (or sqlite+aiosqlite:// for tests)')
        return value

    @field_validator('reports_directory', 'output_audio_directory')
    @classmethod
    def resolve_local_directory(cls, path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path
