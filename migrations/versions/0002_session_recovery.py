"""Fenced runtime leases and connection recovery states."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = '0002_session_recovery'
down_revision = '0001_foundation'
branch_labels = None
depends_on = None
LIVE = "status IN ('connecting', 'active', 'reconnecting')"


def upgrade():
    op.drop_index('uq_conversations_active_user', table_name='conversations')
    with op.batch_alter_table('conversations') as batch:
        batch.drop_constraint(op.f('ck_conversations_status'), type_='check')
        batch.add_column(sa.Column('runtime_owner', sa.String(64)))
        batch.add_column(sa.Column('lease_expires_at', sa.DateTime(timezone=True)))
        batch.create_check_constraint('status', "status IN ('created', 'connecting', 'active', 'reconnecting', 'ended', 'failed')")
    # Stop the old application before migrating. Its in-memory provider state
    # cannot survive the upgrade and must never be silently reconstructed.
    table = sa.table('conversations', sa.column('status'), sa.column('end_reason'), sa.column('ended_at', sa.DateTime(timezone=True)))
    op.execute(table.update().where(table.c.status == 'active').values(
        status='failed', end_reason='migration_interrupted', ended_at=datetime.now(timezone.utc)))
    with op.batch_alter_table('conversations') as batch:
        batch.create_check_constraint('live_lease', "status NOT IN ('connecting', 'active', 'reconnecting') OR "
                                      "(runtime_owner IS NOT NULL AND lease_expires_at IS NOT NULL)")
    op.create_index('uq_conversations_active_user', 'conversations', ['user_id'], unique=True,
                    postgresql_where=sa.text(LIVE), sqlite_where=sa.text(LIVE))
    op.create_index('ix_conversations_live_lease', 'conversations', ['lease_expires_at'],
                    postgresql_where=sa.text(LIVE), sqlite_where=sa.text(LIVE))


def downgrade():
    op.drop_index('ix_conversations_live_lease', table_name='conversations')
    op.drop_index('uq_conversations_active_user', table_name='conversations')
    table = sa.table('conversations', sa.column('status'), sa.column('end_reason'), sa.column('ended_at', sa.DateTime(timezone=True)))
    op.execute(table.update().where(table.c.status.in_(['connecting', 'reconnecting'])).values(
        status='failed', end_reason='migration_interrupted', ended_at=datetime.now(timezone.utc)))
    with op.batch_alter_table('conversations') as batch:
        batch.drop_constraint(op.f('ck_conversations_live_lease'), type_='check')
        batch.drop_constraint(op.f('ck_conversations_status'), type_='check')
        batch.create_check_constraint('status', "status IN ('created', 'active', 'ended', 'failed')")
        batch.drop_column('lease_expires_at')
        batch.drop_column('runtime_owner')
    op.create_index('uq_conversations_active_user', 'conversations', ['user_id'], unique=True,
                    postgresql_where=sa.text("status = 'active'"), sqlite_where=sa.text("status = 'active'"))
