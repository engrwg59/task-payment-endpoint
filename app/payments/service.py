"""Starting a payment for a cart.

The work is split across two database transactions with the provider call in the gap
between them. A single transaction wrapping the charge would hold a row lock and a
connection open for the whole network round trip, and a crash mid-call would roll back
the only record that the card may already have been charged.

    Transaction 1  lock the cart, validate it, write the payment as `pending`, commit
    (no transaction) charge the card
    Transaction 2  record the outcome, check the cart out, commit

If the process dies in the gap, the payment stays `pending` — unknown, but never lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.errors import (
    CartNotFoundError,
    CartNotPayableError,
    ConcurrentPaymentAttemptError,
    InvalidRequestError,
    PaymentMethodNotFoundError,
)
from app.extensions import db
from app.gateway import ChargeRequest, ChargeResult, PaymentGateway, PaymentGatewayError
from app.models.payment import (
    ACTIVE_CART_PAYMENT_INDEX,
    IDEMPOTENCY_KEY_INDEX,
    LIVE_PAYMENT_STATUSES,
    Payment,
    PaymentEvent,
    PaymentEventType,
    PaymentStatus,
)
from app.models.shop import Cart, CartItem, CartStatus, UserPaymentMethod
from app.payments.totals import calculate_cart_total


class PaymentOutcomeKind(StrEnum):
    #: A payment was created and the card was charged.
    CREATED = "created"
    #: This exact request was already handled; the original payment is returned unchanged.
    REPLAYED = "replayed"
    #: Another live payment already exists for this cart, so nothing was charged.
    CONFLICT = "conflict"


@dataclass(frozen=True)
class PaymentOutcome:
    """What happened, and the payment to show for it.

    A conflict is a state rather than an error: the caller still gets a payment back,
    just not one this request created.
    """

    kind: PaymentOutcomeKind
    payment: Payment


def start_payment(
    *,
    cart_id: UUID,
    user_id: UUID,
    idempotency_key: str,
    payment_method_id: UUID | None,
    gateway: PaymentGateway,
) -> PaymentOutcome:
    # --- Transaction 1: claim the cart and record what we are about to do -----------
    # Settled first, before anything is looked up or reported: everything below this
    # line discloses something about the cart or the payments made against it.
    cart = _lock_user_cart(user_id=user_id, cart_id=cart_id)

    # A retry is answered whatever state the cart has reached in the meantime, checked
    # out included. Re-validating it here would report failure for money already taken.
    replay = _find_replay(idempotency_key, user_id=user_id, cart_id=cart_id)
    if replay is not None:
        return PaymentOutcome(PaymentOutcomeKind.REPLAYED, replay)

    if not cart.is_payable:
        return _refuse_unpayable_cart(cart)

    total = calculate_cart_total(cart)
    payment_method = _resolve_payment_method(user_id=user_id, payment_method_id=payment_method_id)

    payment = Payment(
        user_id=user_id,
        cart_id=cart.id,
        payment_method_id=payment_method.id,
        amount=total.amount,
        currency=total.currency,
        status=PaymentStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    db.session.add(payment)
    _record_event(
        payment,
        PaymentEventType.INITIATED,
        {"amount": str(total.amount), "currency": total.currency},
    )

    try:
        db.session.flush()
    except IntegrityError as error:
        db.session.rollback()
        return _resolve_conflict(
            error, user_id=user_id, cart_id=cart_id, idempotency_key=idempotency_key
        )

    # Captured while the row is still loaded. After the commit the object is expired,
    # and reading it would open the very transaction this design keeps closed.
    charge = ChargeRequest(
        payment_id=payment.id,
        provider_token=payment_method.provider_token,
        amount=total.amount,
        currency=total.currency,
    )
    db.session.commit()

    # --- No transaction open: charge the card ---------------------------------------
    try:
        result = gateway.charge(charge)
    except PaymentGatewayError as error:
        payment = _record_unknown_outcome(charge.payment_id, cart_id=cart_id, error=error)
        return PaymentOutcome(PaymentOutcomeKind.CREATED, payment)

    # --- Transaction 2: record what the provider said -------------------------------
    payment = _settle(charge.payment_id, cart_id=cart_id, result=result)
    return PaymentOutcome(PaymentOutcomeKind.CREATED, payment)


def _lock_cart(cart_id: UUID) -> Cart:
    """Take the cart row lock.

    Every transaction in this module takes this lock first and touches the payment
    second. Transaction 1 holds the cart while it inserts into the payments index;
    a transaction that locked the payment first and then reached for the cart would
    close a cycle with it, and PostgreSQL would break the tie by killing one of them.
    """
    return db.session.execute(select(Cart).where(Cart.id == cart_id).with_for_update()).scalar_one()


def _lock_user_cart(*, user_id: UUID, cart_id: UUID) -> Cart:
    """Load this user's cart with a row lock, so two requests cannot both claim it.

    Whether the cart can be paid for is the caller's question, not this one's: deciding
    it here would mean answering the whole request from inside a loader.
    """
    cart = db.session.execute(
        select(Cart)
        .where(Cart.id == cart_id, Cart.user_id == user_id)
        .with_for_update()
        .options(selectinload(Cart.items).joinedload(CartItem.product))
    ).scalar_one_or_none()

    if cart is None:
        # Someone else's cart is reported the same way as a missing one, so the
        # endpoint cannot be used to discover which cart ids exist.
        raise CartNotFoundError(f"No cart {cart_id} belongs to this user.")
    return cart


def _refuse_unpayable_cart(cart: Cart) -> PaymentOutcome:
    """Refuse a closed cart, showing the payment responsible for closing it if there is one.

    A cart is normally closed because a payment closed it, and handing that payment back
    is more use to the caller than an error: it is the receipt they are missing. It is also
    the same answer a cart held by a still-pending payment gets, because it is the same
    situation — one payment already owns this cart.
    """
    live = _find_live_payment(cart.id)
    if live is not None:
        return PaymentOutcome(PaymentOutcomeKind.CONFLICT, live)

    # Nothing to point at: the cart was abandoned, or closed by something other than a
    # payment. There is no receipt to return, so this is a plain refusal.
    raise CartNotPayableError(f"Cart {cart.id} is {cart.status.value}, so it cannot be paid for.")


def _resolve_payment_method(*, user_id: UUID, payment_method_id: UUID | None) -> UserPaymentMethod:
    """The card named by the request, or the user's default one."""
    query = select(UserPaymentMethod).where(UserPaymentMethod.user_id == user_id)
    if payment_method_id is None:
        query = query.where(UserPaymentMethod.is_default.is_(True))
    else:
        query = query.where(UserPaymentMethod.id == payment_method_id)

    payment_method = db.session.execute(query).scalar_one_or_none()
    if payment_method is not None:
        return payment_method

    raise PaymentMethodNotFoundError(
        f"No payment method {payment_method_id} belongs to this user."
        if payment_method_id is not None
        else "This user has no default payment method."
    )


def _find_replay(idempotency_key: str, *, user_id: UUID, cart_id: UUID) -> Payment | None:
    """The payment this key already produced, if the caller is retrying.

    Matched on the caller as well as the key. A key is not a bearer token: the payment
    it names carries an amount, a card and a provider reference, and belongs to whoever
    made it rather than to whoever can name it.
    """
    payment = db.session.execute(
        select(Payment).where(
            Payment.idempotency_key == idempotency_key,
            Payment.user_id == user_id,
        )
    ).scalar_one_or_none()

    if payment is None:
        return None
    if payment.cart_id != cart_id:
        raise InvalidRequestError(
            f"Idempotency-Key '{idempotency_key}' was already used for a different cart."
        )
    return payment


def _resolve_conflict(
    error: IntegrityError, *, user_id: UUID, cart_id: UUID, idempotency_key: str
) -> PaymentOutcome:
    """Turn a unique violation into the outcome it actually represents.

    Reached only when a concurrent request won the race between the lookups above and
    this insert; the database, not those lookups, is what makes a double charge impossible.
    """
    constraint = _violated_constraint(error)

    if constraint == IDEMPOTENCY_KEY_INDEX:
        replay = _find_replay(idempotency_key, user_id=user_id, cart_id=cart_id)
        if replay is not None:
            return PaymentOutcome(PaymentOutcomeKind.REPLAYED, replay)
        # The key is taken, but not by anything this caller made. Saying no more than
        # that keeps one caller's keys from being probed by another.
        raise InvalidRequestError(f"Idempotency-Key '{idempotency_key}' is already in use.")

    if constraint == ACTIVE_CART_PAYMENT_INDEX:
        live = _find_live_payment(cart_id)
        if live is not None:
            return PaymentOutcome(PaymentOutcomeKind.CONFLICT, live)
        # The row that blocked us has already gone: the competing attempt settled
        # between our insert and this lookup, so the cart is payable again.
        raise ConcurrentPaymentAttemptError(
            f"Another payment for cart {cart_id} was in progress. Please retry."
        )

    raise error


def _find_live_payment(cart_id: UUID) -> Payment | None:
    return db.session.execute(
        select(Payment).where(Payment.cart_id == cart_id, Payment.status.in_(LIVE_PAYMENT_STATUSES))
    ).scalar_one_or_none()


def _settle(payment_id: UUID, *, cart_id: UUID, result: ChargeResult) -> Payment:
    """Transaction 2 — write down the outcome of a charge that already happened."""
    cart = _lock_cart(cart_id)
    payment = db.session.get(Payment, payment_id, with_for_update=True)

    if result.is_authorized:
        payment.mark_succeeded(result.reference)
        cart.status = CartStatus.CHECKED_OUT
        event_type = PaymentEventType.AUTHORIZED
    else:
        payment.mark_failed(result.failure_code)
        event_type = PaymentEventType.DECLINED

    _record_event(payment, event_type, result.details)
    db.session.commit()
    return payment


def _record_unknown_outcome(
    payment_id: UUID, *, cart_id: UUID, error: PaymentGatewayError
) -> Payment:
    """Transaction 2 — the provider never answered, so the payment stays pending.

    The cart deliberately stays active: it is not paid for until we know it was.
    It is still locked first, so that every transaction here takes its locks in the
    same order.
    """
    _lock_cart(cart_id)
    payment = db.session.get(Payment, payment_id, with_for_update=True)
    _record_event(payment, PaymentEventType.PROVIDER_UNREACHABLE, {"message": str(error)})
    db.session.commit()
    return payment


def _record_event(payment: Payment, event_type: PaymentEventType, payload: dict[str, Any]) -> None:
    db.session.add(PaymentEvent(payment=payment, event_type=event_type, payload=payload))


def _violated_constraint(error: IntegrityError) -> str | None:
    """Which constraint psycopg says was violated, if it said."""
    diagnostics = getattr(error.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None)
