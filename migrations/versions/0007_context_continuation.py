"""Durable continuation links and summary checkpoints."""
from alembic import op
import sqlalchemy as sa

revision = '0007_context_continuation'
down_revision = '0006_conversation_history'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_preferences') as batch:
        batch.add_column(sa.Column('pronouns', sa.String(80), nullable=False, server_default=''))
    with op.batch_alter_table('conversations') as batch:
        batch.add_column(sa.Column('continued_from_id', sa.Uuid(), nullable=True))
        batch.add_column(sa.Column('summary', sa.Text(), nullable=False, server_default=''))
        batch.add_column(sa.Column('summary_through_sequence', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('summary_version', sa.Integer(), nullable=False, server_default='0'))
        batch.create_foreign_key('fk_conversation_continuation', 'conversations', ['continued_from_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_conversations_continued_from_id', ['continued_from_id'])


def downgrade():
    with op.batch_alter_table('user_preferences') as batch:
        batch.drop_column('pronouns')
    with op.batch_alter_table('conversations') as batch:
        batch.drop_index('ix_conversations_continued_from_id')
        batch.drop_constraint('fk_conversation_continuation', type_='foreignkey')
        for name in ('continued_from_id', 'summary', 'summary_through_sequence', 'summary_version'):
            batch.drop_column(name)
