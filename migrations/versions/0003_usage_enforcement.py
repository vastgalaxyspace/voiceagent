"""Add daily allowance reservations, settlement and admission rate windows.

Revision ID: 0003_usage_enforcement
Revises: 0002_session_recovery
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_usage_enforcement'
down_revision = '0002_session_recovery'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        'daily_usage',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('usage_date', sa.Date(), nullable=False),
        sa.Column('connected_seconds', sa.Numeric(12, 3), nullable=False, server_default='0'),
        sa.Column('reserved_seconds', sa.Numeric(12, 3), nullable=False, server_default='0'),
        sa.Column('estimated_cost_usd', sa.Numeric(14, 8), nullable=False, server_default='0'),
        sa.Column('reserved_cost_usd', sa.Numeric(14, 8), nullable=False, server_default='0'),
        sa.Column('sessions_started', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('sessions_settled', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('incomplete_cost_sessions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('connected_seconds >= 0 AND reserved_seconds >= 0',
                           name='ck_daily_usage_usage_seconds_nonnegative'),
        sa.CheckConstraint('estimated_cost_usd >= 0 AND reserved_cost_usd >= 0',
                           name='ck_daily_usage_usage_cost_nonnegative'),
        sa.CheckConstraint('sessions_started >= 0 AND sessions_settled >= 0 AND incomplete_cost_sessions >= 0',
                           name='ck_daily_usage_usage_counts_nonnegative'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE',
                                name='fk_daily_usage_user_id_users'),
        sa.PrimaryKeyConstraint('user_id', 'usage_date', name='pk_daily_usage'),
    )
    op.create_index('ix_daily_usage_date_cost', 'daily_usage', ['usage_date', 'estimated_cost_usd'])
    op.create_table(
        'usage_reservations',
        sa.Column('conversation_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('usage_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('reserved_seconds', sa.Numeric(12, 3), nullable=False),
        sa.Column('reserved_cost_usd', sa.Numeric(14, 8), nullable=False, server_default='0'),
        sa.Column('settled_seconds', sa.Numeric(12, 3), nullable=True),
        sa.Column('settled_cost_usd', sa.Numeric(14, 8), nullable=True),
        sa.Column('cost_complete', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('reserved', 'settled')",
                           name='ck_usage_reservations_reservation_status'),
        sa.CheckConstraint('reserved_seconds > 0 AND reserved_cost_usd >= 0',
                           name='ck_usage_reservations_reservation_amounts'),
        sa.CheckConstraint('(settled_seconds IS NULL OR settled_seconds >= 0) AND '
                           '(settled_cost_usd IS NULL OR settled_cost_usd >= 0)',
                           name='ck_usage_reservations_settled_amounts'),
        sa.CheckConstraint("(status = 'reserved' AND settled_seconds IS NULL AND settled_cost_usd IS NULL) OR "
                           "(status = 'settled' AND settled_seconds IS NOT NULL AND settled_cost_usd IS NOT NULL)",
                           name='ck_usage_reservations_reservation_settlement'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE',
                                name='fk_usage_reservations_conversation_id_conversations'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE',
                                name='fk_usage_reservations_user_id_users'),
        sa.PrimaryKeyConstraint('conversation_id', name='pk_usage_reservations'),
    )
    op.create_index('ix_usage_reservations_user_date_status', 'usage_reservations',
                    ['user_id', 'usage_date', 'status'])
    op.create_table(
        'conversation_rate_windows',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
        sa.CheckConstraint('count >= 0', name='ck_conversation_rate_windows_rate_count_nonnegative'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE',
                                name='fk_conversation_rate_windows_user_id_users'),
        sa.PrimaryKeyConstraint('user_id', 'window_start', name='pk_conversation_rate_windows'),
    )


def downgrade():
    op.drop_table('conversation_rate_windows')
    op.drop_index('ix_usage_reservations_user_date_status', table_name='usage_reservations')
    op.drop_table('usage_reservations')
    op.drop_index('ix_daily_usage_date_cost', table_name='daily_usage')
    op.drop_table('daily_usage')
    op.drop_column('users', 'is_admin')
