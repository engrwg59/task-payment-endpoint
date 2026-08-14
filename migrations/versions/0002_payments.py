"""Payments and their event log.

The partial unique index is the point of this revision: it is what makes a second
live payment for a cart impossible, whatever the application code does.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PAYMENT_STATUSES = ("pending", "succeeded", "failed")
LIVE_PAYMENT_STATUSES = ("pending", "succeeded")
PAYMENT_EVENT_TYPES = ("initiated", "authorized", "declined", "provider_unreachable")


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("cart_id", sa.Uuid(), nullable=False),
        sa.Column("payment_method_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("provider_reference", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_payments_user_id"),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"], name="fk_payments_cart_id"),
        sa.ForeignKeyConstraint(
            ["payment_method_id"],
            ["user_payment_methods.id"],
            name="fk_payments_payment_method_id",
        ),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint(_value_in("status", PAYMENT_STATUSES), name="ck_payments_status"),
    )

    # One live payment per cart. `pending` counts as live because its outcome is
    # unknown — the card may already have been charged.
    op.create_index(
        "uq_payments_active_cart",
        "payments",
        ["cart_id"],
        unique=True,
        postgresql_where=sa.text(_value_in("status", LIVE_PAYMENT_STATUSES)),
    )

    # A retried request must return the original payment, never make a second one.
    op.create_index("uq_payments_idempotency_key", "payments", ["idempotency_key"], unique=True)
    op.create_index("idx_payments_user_id", "payments", ["user_id"])

    op.create_table(
        "payment_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_events"),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name="fk_payment_events_payment_id", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            _value_in("event_type", PAYMENT_EVENT_TYPES), name="ck_payment_events_event_type"
        ),
    )
    op.create_index("idx_payment_events_payment_id", "payment_events", ["payment_id"])


def downgrade() -> None:
    op.drop_table("payment_events")
    op.drop_table("payments")


def _value_in(column: str, values: tuple[str, ...]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))
