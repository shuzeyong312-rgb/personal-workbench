"""Unify collection triggers and preserve add-submission input facts.

Revision ID: 20261015_15
Revises: 20261012_14
"""
from alembic import op
import sqlalchemy as sa

revision = '20261015_15'
down_revision = '20261012_14'
branch_labels = None
depends_on = None


def _foreign_keys(enabled):
    if op.get_bind().dialect.name == 'sqlite':
        with op.get_context().autocommit_block():
            op.get_bind().exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")
        if not enabled:
            op.get_bind().exec_driver_sql('BEGIN')


def upgrade():
    _foreign_keys(False)
    try:
        with op.batch_alter_table('collection_batches') as batch:
            batch.add_column(sa.Column('request_fingerprint', sa.String(64), nullable=True))
            batch.drop_constraint('ck_collection_batches_trigger_kind', type_='check')
            batch.create_check_constraint('ck_collection_batches_trigger_kind', "trigger_kind IN ('manual_selected', 'manual_all_active', 'scheduled', 'manual_single', 'add_links')")
            batch.create_check_constraint('ck_collection_batches_add_fingerprint', "trigger_kind != 'add_links' OR request_fingerprint IS NOT NULL")
        with op.batch_alter_table('collection_batch_items') as batch:
            batch.add_column(sa.Column('identity_state', sa.String(16), nullable=False, server_default='removed'))
            batch.drop_constraint('ck_collection_batch_items_final_result', type_='check')
            batch.create_check_constraint('ck_collection_batch_items_final_result', "final_result IS NULL OR final_result IN ('first_pass_success', 'verification_resume_success', 'retry_success', 'final_failed', 'verification_required', 'not_executed', 'business_rejected')")
            batch.create_check_constraint('ck_collection_batch_items_identity', "identity_state IN ('pending', 'linked', 'removed')")
            batch.create_check_constraint('ck_collection_batch_items_business_rejected', "final_result IS NULL OR final_result != 'business_rejected' OR (execution_status = 'completed' AND base_result IS NOT NULL AND base_result = 'not_attempted')")
        op.execute("UPDATE collection_batch_items SET identity_state = CASE WHEN competitor_id IS NULL THEN 'removed' ELSE 'linked' END")
        with op.batch_alter_table('collection_batch_items') as batch:
            batch.create_check_constraint('ck_collection_batch_items_identity_fk', "(identity_state = 'linked' AND competitor_id IS NOT NULL) OR (identity_state IN ('pending', 'removed') AND competitor_id IS NULL)")
    finally:
        _foreign_keys(True)
    op.create_table(
        'collection_add_inputs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('batch_id', sa.Integer(), sa.ForeignKey('collection_batches.id'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('source_line', sa.Integer(), nullable=False),
        sa.Column('input_text', sa.String(2048)),
        sa.Column('normalized_url', sa.String(2048)),
        sa.Column('offer_id', sa.String(128)),
        sa.Column('duplicate_of_input_id', sa.Integer(), sa.ForeignKey('collection_add_inputs.id')),
        sa.Column('batch_item_id', sa.Integer(), sa.ForeignKey('collection_batch_items.id')),
        sa.Column('related_competitor_id', sa.Integer(), sa.ForeignKey('competitors.id')),
        sa.Column('result_code', sa.String(32)),
        sa.Column('error_code', sa.String(64)),
        sa.Column('sanitized_reason', sa.String(512)),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('navigation_claimed_at', sa.DateTime(timezone=True)),
        sa.Column('navigation_confirmed_at', sa.DateTime(timezone=True)),
        sa.Column('navigation_terminal_reason', sa.String(64)),
        sa.Column('identity_removed', sa.Boolean(), nullable=False, server_default='0'),
        sa.UniqueConstraint('batch_id', 'position', name='uq_collection_add_inputs_position'),
        sa.UniqueConstraint('batch_item_id', name='uq_collection_add_inputs_item'),
        sa.CheckConstraint('position >= 0 AND source_line >= 1', name='ck_collection_add_inputs_position'),
        sa.CheckConstraint('input_text IS NULL OR length(input_text) <= 2048', name='ck_collection_add_inputs_length'),
        sa.CheckConstraint("result_code IS NULL OR result_code IN ('added', 'invalid_url', 'duplicate_input', 'already_exists', 'identity_rejected', 'technical_failed', 'verification_required', 'not_executed', 'interrupted')", name='ck_collection_add_inputs_result'),
        sa.CheckConstraint('finished_at IS NULL OR result_code IS NOT NULL', name='ck_collection_add_inputs_finished'),
        sa.CheckConstraint('navigation_confirmed_at IS NULL OR navigation_claimed_at IS NOT NULL', name='ck_collection_add_inputs_navigation'),
        sa.CheckConstraint('identity_removed = 0 OR (input_text IS NULL AND normalized_url IS NULL AND offer_id IS NULL AND related_competitor_id IS NULL AND sanitized_reason IS NULL AND duplicate_of_input_id IS NULL)', name='ck_collection_add_inputs_removed'),
    )
    op.create_index('ix_collection_add_inputs_batch_result', 'collection_add_inputs', ['batch_id', 'result_code'])
    op.create_index('ix_collection_add_inputs_offer', 'collection_add_inputs', ['offer_id'])


def downgrade():
    bind = op.get_bind()
    if (bind.execute(sa.text("SELECT count(*) FROM collection_batches WHERE trigger_kind IN ('add_links', 'manual_single')")).scalar()
        or bind.execute(sa.text('SELECT count(*) FROM collection_add_inputs')).scalar()
        or bind.execute(sa.text("SELECT count(*) FROM collection_batch_items WHERE identity_state = 'pending' OR final_result = 'business_rejected'")).scalar()):
        raise RuntimeError('V1.3 facts exist; refusing lossy downgrade')
    op.drop_index('ix_collection_add_inputs_offer', table_name='collection_add_inputs')
    op.drop_index('ix_collection_add_inputs_batch_result', table_name='collection_add_inputs')
    op.drop_table('collection_add_inputs')
    _foreign_keys(False)
    try:
        with op.batch_alter_table('collection_batch_items') as batch:
            for name in ('ck_collection_batch_items_identity_fk', 'ck_collection_batch_items_identity', 'ck_collection_batch_items_business_rejected', 'ck_collection_batch_items_final_result'):
                batch.drop_constraint(name, type_='check')
            batch.drop_column('identity_state')
            batch.create_check_constraint('ck_collection_batch_items_final_result', "final_result IS NULL OR final_result IN ('first_pass_success', 'verification_resume_success', 'retry_success', 'final_failed', 'verification_required', 'not_executed')")
        with op.batch_alter_table('collection_batches') as batch:
            batch.drop_constraint('ck_collection_batches_add_fingerprint', type_='check')
            batch.drop_constraint('ck_collection_batches_trigger_kind', type_='check')
            batch.drop_column('request_fingerprint')
            batch.create_check_constraint('ck_collection_batches_trigger_kind', "trigger_kind IN ('manual_selected', 'manual_all_active', 'scheduled')")
    finally:
        _foreign_keys(True)
