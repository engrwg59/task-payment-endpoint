"""Expected, client-visible failures and the JSON responses they produce.

Domain code raises these by name and never mentions HTTP; the status code each one
carries is the single place where the domain meets the transport.
"""

from http import HTTPStatus

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException


class DomainError(Exception):
    """A failure the caller caused and can act on."""

    code = "error"
    status = HTTPStatus.BAD_REQUEST


class InvalidRequestError(DomainError):
    code = "invalid_request"
    status = HTTPStatus.BAD_REQUEST


class CartNotFoundError(DomainError):
    code = "cart_not_found"
    status = HTTPStatus.NOT_FOUND


class CartNotPayableError(DomainError):
    code = "cart_not_payable"
    status = HTTPStatus.UNPROCESSABLE_ENTITY


class CartEmptyError(DomainError):
    code = "cart_empty"
    status = HTTPStatus.UNPROCESSABLE_ENTITY


class MixedCurrencyCartError(DomainError):
    code = "mixed_currency_cart"
    status = HTTPStatus.UNPROCESSABLE_ENTITY


class PaymentMethodNotFoundError(DomainError):
    code = "payment_method_not_found"
    status = HTTPStatus.UNPROCESSABLE_ENTITY


class PaymentAlreadySettledError(DomainError):
    code = "payment_already_settled"
    status = HTTPStatus.CONFLICT


class ConcurrentPaymentAttemptError(DomainError):
    """A competing attempt claimed the cart and then settled, freeing it again."""

    code = "concurrent_payment_attempt"
    status = HTTPStatus.CONFLICT


def register_error_handlers(app: Flask) -> None:
    """Make every failure leave the application as the same JSON envelope."""

    @app.errorhandler(DomainError)
    def handle_domain_error(error: DomainError):
        return _error_response(error.code, str(error), error.status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        status = HTTPStatus(error.code)
        return _error_response(status.name.lower(), error.description, status)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception("Unhandled error while serving %s %s", request.method, request.path)
        return _error_response(
            "internal_error",
            "The request could not be completed.",
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def _error_response(code: str, message: str, status: HTTPStatus):
    return jsonify({"error": {"code": code, "message": message}}), status
