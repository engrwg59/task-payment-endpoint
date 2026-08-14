"""One place that knows how the endpoint is called."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from flask.testing import FlaskClient

from app.models.shop import Cart, User

DEFAULT_IDEMPOTENCY_KEY = "key-1"


def post_payment(
    client: FlaskClient,
    *,
    cart: Cart,
    user: User,
    idempotency_key: str = DEFAULT_IDEMPOTENCY_KEY,
    payment_method_id: UUID | None = None,
):
    body: dict[str, Any] = {}
    if payment_method_id is not None:
        body["payment_method_id"] = str(payment_method_id)

    return client.post(
        payment_url(cart.id),
        headers={"X-User-Id": str(user.id), "Idempotency-Key": idempotency_key},
        json=body,
    )


def payment_url(cart_id: UUID) -> str:
    return f"/api/v1/carts/{cart_id}/payments"
