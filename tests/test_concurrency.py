"""Two requests for one cart, arriving at the same moment.

This test cannot share the transaction-per-test approach used elsewhere: the two
attempts run on separate connections and have to see each other's committed rows.
"""

from __future__ import annotations

from threading import Barrier, Thread
from uuid import UUID

from flask import Flask
from sqlalchemy import select

from app.errors import CartNotPayableError
from app.extensions import db
from app.gateway import MockPaymentGateway
from app.models.payment import Payment
from app.payments.service import PaymentOutcomeKind, start_payment
from tests.factories import create_payable_cart

ATTEMPTS = 2


def test_two_simultaneous_attempts_produce_one_payment(app, session):
    payable = create_payable_cart(session)
    results: list[object] = []
    barrier = Barrier(ATTEMPTS)

    threads = [
        Thread(
            target=_attempt,
            args=(app, payable.cart.id, payable.user.id, f"key-{number}", barrier, results),
        )
        for number in range(ATTEMPTS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(results) == ATTEMPTS, results

    winners = [result for result in results if result is PaymentOutcomeKind.CREATED]
    losers = [result for result in results if result is not PaymentOutcomeKind.CREATED]
    assert len(winners) == 1, results

    # The loser is refused in one of two ways, depending on how far the winner got
    # before the loser took the cart lock. Both are correct, and both mean the card
    # was charged once:
    #   • the winner had only reserved the cart  -> the unique index refuses the insert
    #   • the winner had already settled and checked the cart out -> the cart is closed
    assert isinstance(losers[0], PaymentOutcomeKind | CartNotPayableError), results
    if isinstance(losers[0], PaymentOutcomeKind):
        assert losers[0] is PaymentOutcomeKind.CONFLICT, results

    session.rollback()  # start a fresh snapshot before reading what the threads wrote
    payments = (
        session.execute(select(Payment).where(Payment.cart_id == payable.cart.id)).scalars().all()
    )
    assert len(payments) == 1


def _attempt(
    app: Flask,
    cart_id: UUID,
    user_id: UUID,
    idempotency_key: str,
    barrier: Barrier,
    results: list[object],
) -> None:
    """One request's worth of work, on this thread's own connection."""
    with app.app_context():
        try:
            # Line the threads up so they contend for the cart row lock. The assertions
            # above hold even if the operating system runs them one after the other:
            # the second attempt is refused by the index either way.
            barrier.wait(timeout=10)
            outcome = start_payment(
                cart_id=cart_id,
                user_id=user_id,
                idempotency_key=idempotency_key,
                payment_method_id=None,
                gateway=MockPaymentGateway(),
            )
            results.append(outcome.kind)
        except Exception as error:
            results.append(error)
        finally:
            db.session.remove()
