"""The HTTP surface of the payment feature: parse, delegate, choose a status code."""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from flask import Blueprint, jsonify, request

from app.gateway import current_payment_gateway
from app.models.payment import PaymentStatus
from app.payments.schemas import (
    parse_idempotency_key,
    parse_payment_method_id,
    parse_user_id,
    serialize_payment,
)
from app.payments.service import PaymentOutcome, PaymentOutcomeKind, start_payment

payments_blueprint = Blueprint("payments", __name__, url_prefix="/api/v1")

#: Set on a response that repeats an earlier request rather than doing new work, so a
#: caller never has to infer it from the status code.
REPLAY_HEADER = "Idempotent-Replay"

#: A declined card is a successful request that recorded a failed payment, so the
#: status code describes the payment rather than the call.
_STATUS_BY_PAYMENT_STATUS = {
    PaymentStatus.SUCCEEDED: HTTPStatus.CREATED,
    PaymentStatus.FAILED: HTTPStatus.PAYMENT_REQUIRED,
    PaymentStatus.PENDING: HTTPStatus.ACCEPTED,
}

#: A replay reports what the first attempt reported, so a caller can handle a retry
#: with the branch it already has. The one change is 201 becoming 200: this request
#: created nothing, it only repeated the answer.
_REPLAY_STATUS_BY_PAYMENT_STATUS = {
    **_STATUS_BY_PAYMENT_STATUS,
    PaymentStatus.SUCCEEDED: HTTPStatus.OK,
}


@payments_blueprint.post("/carts/<uuid:cart_id>/payments")
def create_payment(cart_id: UUID):
    outcome = start_payment(
        cart_id=cart_id,
        user_id=parse_user_id(request.headers),
        idempotency_key=parse_idempotency_key(request.headers),
        payment_method_id=parse_payment_method_id(request.get_json(silent=True)),
        gateway=current_payment_gateway(),
    )

    response = jsonify(serialize_payment(outcome.payment))
    if outcome.kind is PaymentOutcomeKind.REPLAYED:
        response.headers[REPLAY_HEADER] = "true"
    return response, _status_for(outcome)


def _status_for(outcome: PaymentOutcome) -> HTTPStatus:
    if outcome.kind is PaymentOutcomeKind.CONFLICT:
        return HTTPStatus.CONFLICT
    if outcome.kind is PaymentOutcomeKind.REPLAYED:
        return _REPLAY_STATUS_BY_PAYMENT_STATUS[outcome.payment.status]
    return _STATUS_BY_PAYMENT_STATUS[outcome.payment.status]
