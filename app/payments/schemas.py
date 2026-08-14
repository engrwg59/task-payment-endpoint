"""Turning an HTTP request into arguments, and a payment into a response body."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from werkzeug.datastructures import Headers

from app.errors import InvalidRequestError
from app.models.payment import Payment

#: There is no authentication layer in this task, so the caller names themselves.
USER_ID_HEADER = "X-User-Id"

#: Required: a payment endpoint should never accept a request it cannot recognise again.
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"

MAX_IDEMPOTENCY_KEY_LENGTH = 255


def parse_user_id(headers: Headers) -> UUID:
    value = headers.get(USER_ID_HEADER)
    if not value:
        raise InvalidRequestError(f"The {USER_ID_HEADER} header is required.")
    return _parse_uuid(value, field=USER_ID_HEADER)


def parse_idempotency_key(headers: Headers) -> str:
    value = headers.get(IDEMPOTENCY_KEY_HEADER)
    if not value:
        raise InvalidRequestError(f"The {IDEMPOTENCY_KEY_HEADER} header is required.")
    if len(value) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise InvalidRequestError(
            f"The {IDEMPOTENCY_KEY_HEADER} header may be at most "
            f"{MAX_IDEMPOTENCY_KEY_LENGTH} characters."
        )
    return value


def parse_payment_method_id(body: Any) -> UUID | None:
    """Optional: without it the user's default card is charged."""
    if body is None:
        return None
    if not isinstance(body, dict):
        raise InvalidRequestError("The request body must be a JSON object.")

    value = body.get("payment_method_id")
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidRequestError("'payment_method_id' must be a string.")
    return _parse_uuid(value, field="payment_method_id")


def serialize_payment(payment: Payment) -> dict[str, Any]:
    return {
        "id": str(payment.id),
        "user_id": str(payment.user_id),
        "cart_id": str(payment.cart_id),
        "payment_method_id": str(payment.payment_method_id),
        # A string, not a float: JSON numbers cannot carry a decimal amount safely.
        "amount": str(payment.amount),
        "currency": payment.currency,
        "status": payment.status.value,
        "provider_reference": payment.provider_reference,
        "failure_code": payment.failure_code,
        "created_at": payment.created_at.isoformat(),
        "updated_at": payment.updated_at.isoformat(),
    }


def _parse_uuid(value: str, *, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise InvalidRequestError(f"'{field}' must be a UUID.") from error
