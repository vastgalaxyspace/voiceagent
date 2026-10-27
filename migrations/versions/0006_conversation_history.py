"""Persist voice transcripts and user-facing history metadata."""
from alembic import op
import sqlalchemy as sa

revision = '0006_conversation_history'
down_revision = '0005_knowledge_tools'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('conversations') as batch:
        batch.add_column(sa.Column('title', sa.String(120), nullable=False, server_default=''))
        batch.add_column(sa.Column('preview', sa.String(240), nullable=False, server_default=''))
        batch.add_column(sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('last_message_at', sa.DateTime(timezone=True)))
        batch.add_column(sa.Column('has_user_message', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('transcript_status', sa.String(16), nullable=False, server_default='unavailable'))
        batch.create_check_constraint('transcript_status', "transcript_status IN ('unavailable', 'available', 'partial')")
        batch.create_check_constraint('message_count', 'message_count >= 0')
    op.create_table(
        'conversation_messages',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('conversation_id', sa.Uuid(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('conversation_id', 'sequence', name='uq_conversation_messages_sequence'),
        sa.CheckConstraint("role IN ('user', 'assistant')", name='role'),
        sa.CheckConstraint("state IN ('partial', 'complete', 'interrupted')", name='state'),
        sa.CheckConstraint('sequence > 0 AND revision > 0', name='ordering'),
        sa.CheckConstraint('length(trim(text)) > 0', name='nonempty'),
    )
    op.create_index('ix_conversations_history', 'conversations', ['user_id', 'has_user_message', 'created_at', 'id'])


def downgrade():
    op.drop_index('ix_conversations_history', table_name='conversations')
    op.drop_table('conversation_messages')
    with op.batch_alter_table('conversations') as batch:
        batch.drop_constraint('transcript_status', type_='check')
        batch.drop_constraint('message_count', type_='check')
        for name in ('transcript_status', 'has_user_message', 'last_message_at', 'message_count', 'preview', 'title'):
            batch.drop_column(name)
