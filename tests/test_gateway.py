"""The mock provider's own contract: same input, same answer, every time."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.gateway import (
    DECLINED_TOKEN_SUFFIX,
    UNREACHABLE_TOKEN_SUFFIX,
    ChargeRequest,
    ChargeStatus,
    MockPaymentGateway,
    PaymentGatewayError,
)


def build_request(token: str) -> ChargeRequest:
    return ChargeRequest(
        payment_id=uuid4(), provider_token=token, amount=Decimal("90.00"), currency="USD"
    )


def test_an_ordinary_token_is_authorized():
    result = MockPaymentGateway().charge(build_request("tok_test_visa"))

    assert result.status is ChargeStatus.AUTHORIZED
    assert result.is_authorized
    assert result.reference is not None
    assert result.failure_code is None


def test_a_declining_token_is_declined():
    result = MockPaymentGateway().charge(build_request(f"tok_test{DECLINED_TOKEN_SUFFIX}"))

    assert result.status is ChargeStatus.DECLINED
    assert not result.is_authorized
    assert result.failure_code == "card_declined"
    assert result.reference is None


def test_an_unreachable_token_raises_rather_than_declining():
    """Not knowing is different from being told no, and must not be confused with it."""
    with pytest.raises(PaymentGatewayError):
        MockPaymentGateway().charge(build_request(f"tok_test{UNREACHABLE_TOKEN_SUFFIX}"))


def test_the_same_request_always_gets_the_same_answer():
    request = build_request("tok_test_visa")
    gateway = MockPaymentGateway()

    assert gateway.charge(request) == gateway.charge(request)


def test_the_card_token_is_never_echoed_into_stored_details():
    result = MockPaymentGateway().charge(build_request("tok_test_visa"))

    assert "tok_test_visa" not in str(result.details)


def test_the_payment_id_is_used_as_the_providers_idempotency_key():
    request = build_request("tok_test_visa")

    assert request.idempotency_key == str(request.payment_id)
