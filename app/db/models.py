from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, Uuid, func, literal_column
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow


class User(Base):
    __tablename__ = 'users'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class UserPreferences(Base):
    __tablename__ = 'user_preferences'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    language: Mapped[str] = mapped_column(String(32), default='English and Hindi')
    response_detail: Mapped[str] = mapped_column(String(16), default='brief')
    goal: Mapped[str] = mapped_column(String(500), default='')
    display_name: Mapped[str] = mapped_column(String(80), default='')
    custom_instructions: Mapped[str] = mapped_column(String(1000), default='')
    conversation_mode: Mapped[str] = mapped_column(String(32), default='general')
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_revision: Mapped[int] = mapped_column(Integer, default=0)
    knowledge_revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (
        CheckConstraint("language IN ('English', 'Hindi', 'English and Hindi')", name='language'),
        CheckConstraint("response_detail IN ('brief', 'detailed')", name='response_detail'),
        CheckConstraint("conversation_mode IN ('general', 'english_practice', 'interview_practice')", name='conversation_mode'),
        CheckConstraint('memory_revision >= 0', name='memory_revision'),
        CheckConstraint('knowledge_revision >= 0', name='knowledge_revision'),
    )


class UserMemory(Base):
    __tablename__ = 'user_memories'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    key: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(String(500))
    priority: Mapped[int] = mapped_column(Integer, default=50)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (
        UniqueConstraint('user_id', 'key', name='uq_user_memories_owner_key'),
        CheckConstraint('priority >= 0 AND priority <= 100', name='priority'),
        CheckConstraint('version > 0', name='version'),
        CheckConstraint('length(content) > 0 AND length(content) <= 500', name='content_length'),
        Index('ix_user_memories_owner_priority', 'user_id', 'priority', 'id'),
    )


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class PromptVersion(Base):
    __tablename__ = 'prompt_versions'
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    instructions: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = 'conversations'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    prompt_version: Mapped[str] = mapped_column(ForeignKey('prompt_versions.version'), index=True)
    status: Mapped[str] = mapped_column(String(16), default='created')
    preferences_snapshot: Mapped[dict] = mapped_column(JSON)
    configuration_snapshot: Mapped[dict] = mapped_column(JSON)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    end_reason: Mapped[str | None] = mapped_column(String(64))
    report: Mapped[dict | None] = mapped_column(JSON)
    runtime_owner: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (
        CheckConstraint("status IN ('created', 'connecting', 'active', 'reconnecting', 'ended', 'failed')", name='status'),
        CheckConstraint("status NOT IN ('connecting', 'active', 'reconnecting') OR "
                        "(runtime_owner IS NOT NULL AND lease_expires_at IS NOT NULL)", name='live_lease'),
        Index('ix_conversations_owner_created', 'user_id', 'created_at', 'id'),
    )


Index(
    'uq_conversations_active_user', Conversation.user_id, unique=True,
    postgresql_where=Conversation.status.in_(['connecting', 'active', 'reconnecting']),
    sqlite_where=Conversation.status.in_(['connecting', 'active', 'reconnecting']),
)

Index('ix_conversations_live_lease', Conversation.lease_expires_at,
      postgresql_where=Conversation.status.in_(['connecting', 'active', 'reconnecting']),
      sqlite_where=Conversation.status.in_(['connecting', 'active', 'reconnecting']))


class DailyUsage(Base):
    __tablename__ = 'daily_usage'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    connected_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    reserved_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=0)
    reserved_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=0)
    sessions_started: Mapped[int] = mapped_column(Integer, default=0)
    sessions_settled: Mapped[int] = mapped_column(Integer, default=0)
    incomplete_cost_sessions: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (
        CheckConstraint('connected_seconds >= 0 AND reserved_seconds >= 0', name='usage_seconds_nonnegative'),
        CheckConstraint('estimated_cost_usd >= 0 AND reserved_cost_usd >= 0', name='usage_cost_nonnegative'),
        CheckConstraint('sessions_started >= 0 AND sessions_settled >= 0 AND incomplete_cost_sessions >= 0',
                        name='usage_counts_nonnegative'),
        Index('ix_daily_usage_date_cost', 'usage_date', 'estimated_cost_usd'),
    )


class UsageReservation(Base):
    __tablename__ = 'usage_reservations'
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    usage_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default='reserved')
    reserved_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    reserved_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=0)
    settled_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    settled_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    cost_complete: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (
        CheckConstraint("status IN ('reserved', 'settled')", name='reservation_status'),
        CheckConstraint('reserved_seconds > 0 AND reserved_cost_usd >= 0', name='reservation_amounts'),
        CheckConstraint('(settled_seconds IS NULL OR settled_seconds >= 0) AND '
                        '(settled_cost_usd IS NULL OR settled_cost_usd >= 0)', name='settled_amounts'),
        CheckConstraint("(status = 'reserved' AND settled_seconds IS NULL AND settled_cost_usd IS NULL) OR "
                        "(status = 'settled' AND settled_seconds IS NOT NULL AND settled_cost_usd IS NOT NULL)",
                        name='reservation_settlement'),
        Index('ix_usage_reservations_user_date_status', 'user_id', 'usage_date', 'status'),
    )


class ConversationRateWindow(Base):
    __tablename__ = 'conversation_rate_windows'
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint('count >= 0', name='rate_count_nonnegative'),)


class KnowledgeEntry(Base):
    __tablename__ = 'knowledge_entries'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(String(6000))
    source_url: Mapped[str] = mapped_column(String(1000), default='')
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (
        CheckConstraint('owner_id IS NULL OR published = false', name='private_unpublished'),
        CheckConstraint('version > 0', name='version'),
        CheckConstraint('length(title) BETWEEN 1 AND 120 AND length(content) BETWEEN 1 AND 6000', name='lengths'),
        Index('ix_knowledge_entries_owner_updated', 'owner_id', 'updated_at', 'id'),
        Index('ix_knowledge_entries_published', 'published', 'id'),
    )


def knowledge_vector():
    # Fixed SQL in PostgreSQL's reflected form keeps Alembic expression-index
    # comparison stable. Only the search terms are supplied at runtime.
    return func.to_tsvector(literal_column("'simple'::regconfig"),
                           literal_column("(title::text || ' '::text) || content::text"))


KnowledgeEntry.__table__.append_constraint(
    Index('ix_knowledge_entries_search', knowledge_vector(), postgresql_using='gin').ddl_if(dialect='postgresql'))


class KnowledgeState(Base):
    __tablename__ = 'knowledge_state'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint('id = 1 AND revision >= 0', name='singleton_revision'),)
