"""In-process stand-in for the card provider.

The outcome is decided by the stored card token, so every run — test or manual — is
reproducible. Nothing here is random: a suite that fails once in a hundred runs
teaches you nothing.
"""

from __future__ import annotations

from app.gateway.base import ChargeRequest, ChargeResult, ChargeStatus, PaymentGatewayError

#: A card token ending in this is always declined.
DECLINED_TOKEN_SUFFIX = "_declined"

#: A card token ending in this always times out, leaving the outcome unknown.
UNREACHABLE_TOKEN_SUFFIX = "_unreachable"


class MockPaymentGateway:
    """Charges nothing and always answers the same way for the same token."""

    def charge(self, request: ChargeRequest) -> ChargeResult:
        if request.provider_token.endswith(UNREACHABLE_TOKEN_SUFFIX):
            raise PaymentGatewayError(
                f"No response from the provider for payment {request.payment_id}."
            )

        if request.provider_token.endswith(DECLINED_TOKEN_SUFFIX):
            return ChargeResult(
                status=ChargeStatus.DECLINED,
                failure_code="card_declined",
                details={"decline_reason": "insufficient_funds"},
            )

        return ChargeResult(
            status=ChargeStatus.AUTHORIZED,
            reference=f"ch_{request.payment_id.hex}",
            # The card token is never echoed back into anything we store.
            details={"amount": str(request.amount), "currency": request.currency},
        )
