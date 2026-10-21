"""Read-only live tools and private/published lexical knowledge.

Revision ID: 0005_knowledge_tools
Revises: 0004_personalization_memory
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_knowledge_tools'
down_revision = '0004_personalization_memory'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_preferences') as batch:
        batch.add_column(sa.Column('knowledge_revision', sa.Integer(), nullable=False, server_default='0'))
        batch.create_check_constraint('knowledge_revision', 'knowledge_revision >= 0')
    op.create_table(
        'knowledge_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_state'),
        sa.CheckConstraint('id = 1 AND revision >= 0', name='ck_knowledge_state_singleton_revision'),
    )
    op.execute(sa.text('INSERT INTO knowledge_state (id, revision) VALUES (1, 0)'))
    op.create_table(
        'knowledge_entries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('content', sa.String(6000), nullable=False),
        sa.Column('source_url', sa.String(1000), nullable=False),
        sa.Column('published', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_entries'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE', name='fk_knowledge_entries_owner_id_users'),
        sa.CheckConstraint('owner_id IS NULL OR published = false', name='ck_knowledge_entries_private_unpublished'),
        sa.CheckConstraint('version > 0', name='ck_knowledge_entries_version'),
        sa.CheckConstraint('length(title) BETWEEN 1 AND 120 AND length(content) BETWEEN 1 AND 6000',
                           name='ck_knowledge_entries_lengths'),
    )
    op.create_index('ix_knowledge_entries_owner_updated', 'knowledge_entries', ['owner_id', 'updated_at', 'id'])
    op.create_index('ix_knowledge_entries_published', 'knowledge_entries', ['published', 'id'])
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("CREATE INDEX ix_knowledge_entries_search ON knowledge_entries USING gin "
                   "(to_tsvector('simple'::regconfig, title || ' ' || content))")


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.drop_index('ix_knowledge_entries_search', table_name='knowledge_entries')
    op.drop_index('ix_knowledge_entries_published', table_name='knowledge_entries')
    op.drop_index('ix_knowledge_entries_owner_updated', table_name='knowledge_entries')
    op.drop_table('knowledge_entries')
    op.drop_table('knowledge_state')
    with op.batch_alter_table('user_preferences') as batch:
        batch.drop_constraint('knowledge_revision', type_='check')
        batch.drop_column('knowledge_revision')
