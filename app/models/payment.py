"""The payment side of the schema: what was charged, and what the provider said.

`Payment` holds the money and the current state. `PaymentEvent` is an append-only
log of everything the provider told us, which is what a dispute is answered from.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.errors import PaymentAlreadySettledError
from app.extensions import db
from app.models.columns import CreatedAtMixin, TimestampMixin, enum_column, uuid_primary_key


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Succeeded and failed are final; a payment never leaves them."""
        return self is not PaymentStatus.PENDING


#: A cart may have only one payment in these states at a time. `pending` is included
#: because its outcome is unknown, not because it failed.
LIVE_PAYMENT_STATUSES = (PaymentStatus.PENDING, PaymentStatus.SUCCEEDED)

#: Name of the partial unique index that enforces the rule above.
ACTIVE_CART_PAYMENT_INDEX = "uq_payments_active_cart"

#: Name of the unique index behind idempotent replays.
IDEMPOTENCY_KEY_INDEX = "uq_payments_idempotency_key"


class PaymentEventType(StrEnum):
    INITIATED = "initiated"
    AUTHORIZED = "authorized"
    DECLINED = "declined"
    PROVIDER_UNREACHABLE = "provider_unreachable"


class Payment(TimestampMixin, db.Model):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        Index(
            ACTIVE_CART_PAYMENT_INDEX,
            "cart_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'succeeded')"),
        ),
        Index(IDEMPOTENCY_KEY_INDEX, "idempotency_key", unique=True),
        Index("idx_payments_user_id", "user_id"),
    )

    id: Mapped[UUID] = uuid_primary_key()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    cart_id: Mapped[UUID] = mapped_column(ForeignKey("carts.id"), nullable=False)
    payment_method_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_payment_methods.id"), nullable=False
    )
    # Snapshotted at checkout: repricing a product must never move a settled payment.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[PaymentStatus] = enum_column(PaymentStatus, default=PaymentStatus.PENDING)
    provider_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)

    events: Mapped[list[PaymentEvent]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", order_by="PaymentEvent.created_at"
    )

    def mark_succeeded(self, provider_reference: str) -> None:
        self._reject_if_settled()
        self.status = PaymentStatus.SUCCEEDED
        self.provider_reference = provider_reference

    def mark_failed(self, failure_code: str) -> None:
        self._reject_if_settled()
        self.status = PaymentStatus.FAILED
        self.failure_code = failure_code

    def _reject_if_settled(self) -> None:
        if self.status.is_terminal:
            raise PaymentAlreadySettledError(
                f"Payment {self.id} is already {self.status.value} and cannot change."
            )


class PaymentEvent(CreatedAtMixin, db.Model):
    """One thing that happened to a payment. Written once, never updated or deleted."""

    __tablename__ = "payment_events"
    __table_args__ = (Index("idx_payment_events_payment_id", "payment_id"),)

    id: Mapped[UUID] = uuid_primary_key()
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[PaymentEventType] = enum_column(PaymentEventType)
    # The provider's own words, with card details already left out by the gateway.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    payment: Mapped[Payment] = relationship(back_populates="events")
