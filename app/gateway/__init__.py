"""Payment provider integration: the interface, and the mock that stands in for it."""

from flask import current_app

from app.gateway.base import (
    ChargeRequest,
    ChargeResult,
    ChargeStatus,
    PaymentGateway,
    PaymentGatewayError,
)
from app.gateway.mock import DECLINED_TOKEN_SUFFIX, UNREACHABLE_TOKEN_SUFFIX, MockPaymentGateway

#: Key under which the app factory stores the gateway on `app.extensions`.
EXTENSION_KEY = "payment_gateway"


def current_payment_gateway() -> PaymentGateway:
    """The gateway configured for the running application."""
    return current_app.extensions[EXTENSION_KEY]


__all__ = [
    "DECLINED_TOKEN_SUFFIX",
    "EXTENSION_KEY",
    "UNREACHABLE_TOKEN_SUFFIX",
    "ChargeRequest",
    "ChargeResult",
    "ChargeStatus",
    "MockPaymentGateway",
    "PaymentGateway",
    "PaymentGatewayError",
    "current_payment_gateway",
]
