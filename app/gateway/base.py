"""The boundary between the shop and whoever actually moves the money."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class ChargeStatus(StrEnum):
    AUTHORIZED = "authorized"
    DECLINED = "declined"


@dataclass(frozen=True)
class ChargeRequest:
    """Everything the provider needs, as plain values.

    A `Payment` is deliberately not passed here. The charge is made with no database
    transaction open, and reading an ORM object at that moment would open one.
    """

    payment_id: UUID
    provider_token: str
    amount: Decimal
    currency: str

    @property
    def idempotency_key(self) -> str:
        """Our payment id, so a retried charge is recognised by the provider too."""
        return str(self.payment_id)


@dataclass(frozen=True)
class ChargeResult:
    status: ChargeStatus
    reference: str | None = None
    failure_code: str | None = None
    #: Stored verbatim on the payment event, so it must be JSON-serialisable.
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_authorized(self) -> bool:
        return self.status is ChargeStatus.AUTHORIZED


class PaymentGatewayError(RuntimeError):
    """The provider could not be reached, so the outcome of the charge is unknown.

    This is not a decline. The card may well have been charged, which is why the
    payment stays pending instead of being marked failed.
    """


class PaymentGateway(Protocol):
    def charge(self, request: ChargeRequest) -> ChargeResult: ...
