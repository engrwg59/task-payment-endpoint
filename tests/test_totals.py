"""What a cart adds up to."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.errors import CartEmptyError, MixedCurrencyCartError
from app.payments.totals import calculate_cart_total
from tests.factories import add_cart_item, create_cart, create_product, create_user


def test_the_total_is_the_sum_of_the_line_items(session):
    cart = create_cart(session, user=create_user(session))
    add_cart_item(session, cart=cart, product=create_product(session, price="45.00"), quantity=1)
    add_cart_item(session, cart=cart, product=create_product(session, price="12.50"), quantity=2)

    total = calculate_cart_total(cart)

    assert total.amount == Decimal("70.00")
    assert total.currency == "USD"


def test_the_total_keeps_two_decimal_places(session):
    cart = create_cart(session, user=create_user(session))
    add_cart_item(session, cart=cart, product=create_product(session, price="0.10"), quantity=3)

    total = calculate_cart_total(cart)

    assert total.amount == Decimal("0.30")
    assert str(total.amount) == "0.30"


def test_the_line_item_price_is_used_rather_than_the_current_product_price(session):
    """Repricing a product must not change what a waiting cart costs."""
    product = create_product(session, price="45.00")
    cart = create_cart(session, user=create_user(session))
    add_cart_item(session, cart=cart, product=product, quantity=1)

    product.price = Decimal("99.00")
    session.commit()
    session.refresh(cart)

    assert calculate_cart_total(cart).amount == Decimal("45.00")


def test_an_empty_cart_has_no_total(session):
    cart = create_cart(session, user=create_user(session))

    with pytest.raises(CartEmptyError):
        calculate_cart_total(cart)


def test_a_cart_cannot_mix_currencies(session):
    cart = create_cart(session, user=create_user(session))
    add_cart_item(session, cart=cart, product=create_product(session, currency="USD"))
    add_cart_item(session, cart=cart, product=create_product(session, currency="EUR"))

    with pytest.raises(MixedCurrencyCartError):
        calculate_cart_total(cart)
