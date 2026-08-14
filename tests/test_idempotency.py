"""Retrying a payment request must never charge the card a second time."""

from __future__ import annotations

from sqlalchemy import select

from app.gateway import (
    DECLINED_TOKEN_SUFFIX,
    EXTENSION_KEY,
    UNREACHABLE_TOKEN_SUFFIX,
    ChargeRequest,
    ChargeResult,
    MockPaymentGateway,
)
from app.models.payment import Payment
from app.models.shop import CartStatus
from app.payments.routes import REPLAY_HEADER
from tests.api import post_payment
from tests.factories import (
    add_cart_item,
    create_cart,
    create_payable_cart,
    create_payment_method,
    create_product,
    create_user,
)


class CountingGateway:
    """Wraps the mock so a test can tell how often the card was actually charged."""

    def __init__(self) -> None:
        self._gateway = MockPaymentGateway()
        self.charges = 0

    def charge(self, request: ChargeRequest) -> ChargeResult:
        self.charges += 1
        return self._gateway.charge(request)


def test_replaying_a_request_returns_the_original_payment(client, session):
    payable = create_payable_cart(session)

    first = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")
    second = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")

    assert first.status_code == 201
    # 200 rather than 201: the replay repeated an answer, it did not create anything.
    assert second.status_code == 200
    assert second.get_json() == first.get_json()
    assert second.headers[REPLAY_HEADER] == "true"
    assert REPLAY_HEADER not in first.headers


def test_replaying_a_declined_payment_is_still_reported_as_declined(client, session):
    """A retry must be handled by the same branch as the call it repeats.

    Answering 200 here would let a caller that only reads the status code treat a
    refused card as a completed payment.
    """
    payable = create_payable_cart(session, token=f"tok_test{DECLINED_TOKEN_SUFFIX}")

    first = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")
    second = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")

    assert first.status_code == 402
    assert second.status_code == 402
    assert second.headers[REPLAY_HEADER] == "true"
    assert second.get_json() == first.get_json()


def test_replaying_an_unresolved_payment_is_still_reported_as_pending(client, session):
    payable = create_payable_cart(session, token=f"tok_test{UNREACHABLE_TOKEN_SUFFIX}")

    first = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")
    second = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.headers[REPLAY_HEADER] == "true"


def test_a_replay_is_answered_even_though_the_cart_is_no_longer_payable(client, session):
    """The cart is checked out by the first attempt, and the replay still succeeds.

    This is the point of the key. Re-validating the cart would answer 422 to a client
    retrying after a dropped connection — reporting failure for money already taken.
    """
    payable = create_payable_cart(session)

    first = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")
    session.refresh(payable.cart)
    assert payable.cart.status is CartStatus.CHECKED_OUT

    replay = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")

    assert replay.status_code == 200
    assert replay.headers[REPLAY_HEADER] == "true"
    assert replay.get_json()["id"] == first.get_json()["id"]


def test_replaying_a_request_does_not_charge_the_card_again(app, client, session):
    counting_gateway = CountingGateway()
    app.extensions[EXTENSION_KEY] = counting_gateway
    payable = create_payable_cart(session)

    post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")
    post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")

    assert counting_gateway.charges == 1
    assert len(session.execute(select(Payment)).all()) == 1


def test_a_new_key_for_a_cart_that_is_already_paid_for_conflicts(client, session):
    """A new key is a new intent, so it is not replayed — and the cart is already paid.

    The answer carries the payment that paid for it rather than a bare error: it is the
    receipt the caller is missing, and the same answer a cart held by a pending payment
    gets, because it is the same situation.
    """
    payable = create_payable_cart(session)

    first = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")
    second = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-2")

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.get_json()["id"] == first.get_json()["id"]
    assert second.get_json()["status"] == "succeeded"
    assert REPLAY_HEADER not in second.headers
    assert len(session.execute(select(Payment)).all()) == 1


def test_a_new_key_while_a_payment_is_still_pending_conflicts(client, session):
    """An unresolved payment holds the cart: it may already have been charged.

    The cart is still active here, so nothing stops the second attempt except the
    partial unique index — which is exactly what it is for.
    """
    payable = create_payable_cart(session, token=f"tok_test{UNREACHABLE_TOKEN_SUFFIX}")

    first = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")
    second = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-2")

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.get_json()["id"] == first.get_json()["id"]
    assert len(session.execute(select(Payment)).all()) == 1


def test_a_key_does_not_unlock_another_users_payment(client, session):
    """An Idempotency-Key is not a bearer token.

    Anyone naming a cart id and the key used against it would otherwise be handed that
    payment's amount, card and provider reference.
    """
    payable = create_payable_cart(session)
    stranger = create_user(session, name="Mallory")

    first = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")
    assert first.status_code == 201

    stolen = post_payment(client, cart=payable.cart, user=stranger, idempotency_key="key-1")

    assert stolen.status_code == 404
    assert stolen.get_json()["error"]["code"] == "cart_not_found"


def test_another_user_cannot_take_a_key_that_is_already_in_use(client, session):
    first_cart = create_payable_cart(session)
    second_cart = create_payable_cart(session)

    post_payment(client, cart=first_cart.cart, user=first_cart.user, idempotency_key="key-1")
    response = post_payment(
        client, cart=second_cart.cart, user=second_cart.user, idempotency_key="key-1"
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"
    # The refusal says the key is taken, never who by or what it paid for.
    assert "key-1" in response.get_json()["error"]["message"]
    assert str(first_cart.cart.id) not in response.get_json()["error"]["message"]


def test_reusing_your_own_key_for_a_different_cart_is_rejected(client, session):
    """Same caller, second cart, same key: the request has changed, so it is not a retry."""
    owner = create_user(session)
    create_payment_method(session, user=owner)
    first = create_cart(session, user=owner)
    add_cart_item(session, cart=first, product=create_product(session))
    second = create_cart(session, user=owner)
    add_cart_item(session, cart=second, product=create_product(session))

    post_payment(client, cart=first, user=owner, idempotency_key="key-1")
    response = post_payment(client, cart=second, user=owner, idempotency_key="key-1")

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_a_failed_payment_can_be_retried_with_a_new_key(client, session):
    """A declined card leaves the cart payable, so the user can try another one."""
    payable = create_payable_cart(session, token="tok_test_declined")

    declined = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-1")
    retried = post_payment(client, cart=payable.cart, user=payable.user, idempotency_key="key-2")

    assert declined.status_code == 402
    assert retried.status_code == 402
    assert retried.get_json()["id"] != declined.get_json()["id"]
