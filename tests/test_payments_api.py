"""The endpoint's contract: what it charges, what it answers, and what it refuses."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.gateway import DECLINED_TOKEN_SUFFIX, UNREACHABLE_TOKEN_SUFFIX
from app.models.payment import Payment, PaymentEventType, PaymentStatus
from app.models.shop import CartStatus
from tests.api import payment_url, post_payment
from tests.factories import (
    add_cart_item,
    create_cart,
    create_payable_cart,
    create_payment_method,
    create_product,
    create_user,
)


def test_authorized_card_creates_a_succeeded_payment(client, session):
    payable = create_payable_cart(session, price="45.00", quantity=2)

    response = post_payment(client, cart=payable.cart, user=payable.user)

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == PaymentStatus.SUCCEEDED.value
    assert body["amount"] == "90.00"
    assert body["currency"] == "USD"
    assert body["cart_id"] == str(payable.cart.id)
    assert body["payment_method_id"] == str(payable.payment_method.id)
    assert body["provider_reference"] is not None
    assert body["failure_code"] is None


def test_successful_payment_checks_the_cart_out(client, session):
    payable = create_payable_cart(session)

    post_payment(client, cart=payable.cart, user=payable.user)

    session.refresh(payable.cart)
    assert payable.cart.status is CartStatus.CHECKED_OUT


def test_declined_card_records_a_failed_payment_and_leaves_the_cart_alone(client, session):
    payable = create_payable_cart(session, token=f"tok_test{DECLINED_TOKEN_SUFFIX}")

    response = post_payment(client, cart=payable.cart, user=payable.user)

    assert response.status_code == 402
    body = response.get_json()
    assert body["status"] == PaymentStatus.FAILED.value
    assert body["failure_code"] == "card_declined"
    assert body["provider_reference"] is None

    session.refresh(payable.cart)
    assert payable.cart.status is CartStatus.ACTIVE


def test_unreachable_provider_leaves_the_payment_pending(client, session):
    """The card may well have been charged, so the outcome must not be guessed."""
    payable = create_payable_cart(session, token=f"tok_test{UNREACHABLE_TOKEN_SUFFIX}")

    response = post_payment(client, cart=payable.cart, user=payable.user)

    assert response.status_code == 202
    assert response.get_json()["status"] == PaymentStatus.PENDING.value

    session.refresh(payable.cart)
    assert payable.cart.status is CartStatus.ACTIVE


def test_every_attempt_leaves_an_audit_trail(client, session):
    payable = create_payable_cart(session)

    post_payment(client, cart=payable.cart, user=payable.user)

    payment = session.execute(select(Payment)).scalar_one()
    assert [event.event_type for event in payment.events] == [
        PaymentEventType.INITIATED,
        PaymentEventType.AUTHORIZED,
    ]


def test_a_named_payment_method_is_charged_instead_of_the_default(client, session):
    payable = create_payable_cart(session)
    other_card = create_payment_method(
        session, user=payable.user, token="tok_test_amex", is_default=False
    )

    response = post_payment(
        client, cart=payable.cart, user=payable.user, payment_method_id=other_card.id
    )

    assert response.status_code == 201
    assert response.get_json()["payment_method_id"] == str(other_card.id)


def test_unknown_cart_is_not_found(client, session):
    payable = create_payable_cart(session)

    response = client.post(
        payment_url(uuid4()),
        headers={"X-User-Id": str(payable.user.id), "Idempotency-Key": "key-1"},
        json={},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "cart_not_found"


def test_another_users_cart_is_reported_as_missing(client, session):
    """Answering "forbidden" here would confirm that the cart exists."""
    payable = create_payable_cart(session)
    intruder = create_user(session, name="Bob")

    response = post_payment(client, cart=payable.cart, user=intruder)

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "cart_not_found"


def test_a_closed_cart_with_no_payment_behind_it_is_refused(client, session):
    """No payment owns this cart, so there is no receipt to hand back — only a refusal."""
    payable = create_payable_cart(session, status=CartStatus.CHECKED_OUT)

    response = post_payment(client, cart=payable.cart, user=payable.user)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "cart_not_payable"


def test_an_abandoned_cart_is_refused(client, session):
    payable = create_payable_cart(session, status=CartStatus.ABANDONED)

    response = post_payment(client, cart=payable.cart, user=payable.user)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "cart_not_payable"


def test_an_empty_cart_cannot_be_paid_for(client, session):
    user = create_user(session)
    create_payment_method(session, user=user)
    cart = create_cart(session, user=user)

    response = post_payment(client, cart=cart, user=user)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "cart_empty"


def test_a_cart_mixing_currencies_cannot_be_paid_for(client, session):
    user = create_user(session)
    create_payment_method(session, user=user)
    cart = create_cart(session, user=user)
    add_cart_item(session, cart=cart, product=create_product(session, currency="USD"))
    add_cart_item(session, cart=cart, product=create_product(session, currency="EUR"))

    response = post_payment(client, cart=cart, user=user)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "mixed_currency_cart"


def test_a_user_without_a_card_cannot_pay(client, session):
    user = create_user(session)
    cart = create_cart(session, user=user)
    add_cart_item(session, cart=cart, product=create_product(session))

    response = post_payment(client, cart=cart, user=user)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "payment_method_not_found"


def test_another_users_card_cannot_be_charged(client, session):
    payable = create_payable_cart(session)
    stranger = create_user(session, name="Bob")
    stranger_card = create_payment_method(session, user=stranger)

    response = post_payment(
        client, cart=payable.cart, user=payable.user, payment_method_id=stranger_card.id
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "payment_method_not_found"


def test_the_user_header_is_required(client, session):
    payable = create_payable_cart(session)

    response = client.post(
        payment_url(payable.cart.id), headers={"Idempotency-Key": "key-1"}, json={}
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_the_idempotency_key_header_is_required(client, session):
    payable = create_payable_cart(session)

    response = client.post(
        payment_url(payable.cart.id), headers={"X-User-Id": str(payable.user.id)}, json={}
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_nothing_is_charged_when_the_request_is_rejected(client, session):
    payable = create_payable_cart(session, status=CartStatus.CHECKED_OUT)

    post_payment(client, cart=payable.cart, user=payable.user)

    assert session.execute(select(Payment)).all() == []
