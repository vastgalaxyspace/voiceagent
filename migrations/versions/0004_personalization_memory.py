"""Opt-in user-managed memory and bounded personalization.

Revision ID: 0004_personalization_memory
Revises: 0003_usage_enforcement
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_personalization_memory'
down_revision = '0003_usage_enforcement'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_preferences') as batch:
        batch.add_column(sa.Column('display_name', sa.String(80), nullable=False, server_default=''))
        batch.add_column(sa.Column('custom_instructions', sa.String(1000), nullable=False, server_default=''))
        batch.add_column(sa.Column('conversation_mode', sa.String(32), nullable=False, server_default='general'))
        batch.add_column(sa.Column('memory_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('memory_revision', sa.Integer(), nullable=False, server_default='0'))
        batch.create_check_constraint('conversation_mode',
            "conversation_mode IN ('general', 'english_practice', 'interview_practice')")
        batch.create_check_constraint('memory_revision', 'memory_revision >= 0')
    op.create_table(
        'user_memories',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(64), nullable=False),
        sa.Column('content', sa.String(500), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_user_memories'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE', name='fk_user_memories_user_id_users'),
        sa.UniqueConstraint('user_id', 'key', name='uq_user_memories_owner_key'),
        sa.CheckConstraint('priority >= 0 AND priority <= 100', name='ck_user_memories_priority'),
        sa.CheckConstraint('version > 0', name='ck_user_memories_version'),
        sa.CheckConstraint('length(content) > 0 AND length(content) <= 500', name='ck_user_memories_content_length'),
    )
    op.create_index('ix_user_memories_owner_priority', 'user_memories', ['user_id', 'priority', 'id'])


def downgrade():
    op.drop_index('ix_user_memories_owner_priority', table_name='user_memories')
    op.drop_table('user_memories')
    with op.batch_alter_table('user_preferences') as batch:
        batch.drop_constraint('memory_revision', type_='check')
        batch.drop_constraint('conversation_mode', type_='check')
        for column in ['memory_revision', 'memory_enabled', 'conversation_mode', 'custom_instructions', 'display_name']:
            batch.drop_column(column)
