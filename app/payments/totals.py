"""How much a cart costs.

The brief says the shop already has a total calculation service; this is the smallest
thing that stands in for it, kept behind one function so it can be swapped for the
real one without touching the payment flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.errors import CartEmptyError, MixedCurrencyCartError
from app.models.shop import Cart

#: Money is stored to two decimal places, matching NUMERIC(12, 2).
AMOUNT_EXPONENT = Decimal("0.01")


@dataclass(frozen=True)
class CartTotal:
    amount: Decimal
    currency: str


def calculate_cart_total(cart: Cart) -> CartTotal:
    if not cart.items:
        raise CartEmptyError(f"Cart {cart.id} has no items to pay for.")

    currencies = {item.product.currency for item in cart.items}
    if len(currencies) > 1:
        raise MixedCurrencyCartError(
            f"Cart {cart.id} mixes {', '.join(sorted(currencies))} and cannot be paid at once."
        )

    amount = sum((item.subtotal for item in cart.items), start=Decimal(0))
    return CartTotal(amount=amount.quantize(AMOUNT_EXPONENT), currency=currencies.pop())
