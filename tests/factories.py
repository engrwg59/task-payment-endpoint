"""Builders for the rows a payment needs, so tests read as what they are testing.

Every builder commits. The endpoint under test serves its request on its own
connection and can only see committed rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import count

from sqlalchemy.orm import Session

from app.models.shop import Cart, CartItem, CartStatus, Product, User, UserPaymentMethod

_sequence = count(1)

DEFAULT_TOKEN = "tok_test_visa"


def create_user(session: Session, *, name: str = "Alice") -> User:
    user = User(email=f"user-{next(_sequence)}@example.com", name=name)
    return _persist(session, user)


def create_product(session: Session, *, price: str = "45.00", currency: str = "USD") -> Product:
    product = Product(name=f"Product {next(_sequence)}", price=Decimal(price), currency=currency)
    return _persist(session, product)


def create_payment_method(
    session: Session, *, user: User, token: str = DEFAULT_TOKEN, is_default: bool = True
) -> UserPaymentMethod:
    payment_method = UserPaymentMethod(
        user_id=user.id, provider_token=token, last_four="4242", is_default=is_default
    )
    return _persist(session, payment_method)


def create_cart(session: Session, *, user: User, status: CartStatus = CartStatus.ACTIVE) -> Cart:
    return _persist(session, Cart(user_id=user.id, status=status))


def add_cart_item(session: Session, *, cart: Cart, product: Product, quantity: int = 1) -> CartItem:
    item = CartItem(
        cart_id=cart.id, product_id=product.id, quantity=quantity, unit_price=product.price
    )
    return _persist(session, item)


@dataclass(frozen=True)
class PayableCart:
    """A user with a saved card and a cart worth paying for."""

    user: User
    cart: Cart
    payment_method: UserPaymentMethod


def create_payable_cart(
    session: Session,
    *,
    token: str = DEFAULT_TOKEN,
    price: str = "45.00",
    quantity: int = 2,
    status: CartStatus = CartStatus.ACTIVE,
) -> PayableCart:
    """The usual arrangement: one user, one card, one cart holding one product."""
    user = create_user(session)
    payment_method = create_payment_method(session, user=user, token=token)
    cart = create_cart(session, user=user, status=status)
    add_cart_item(
        session, cart=cart, product=create_product(session, price=price), quantity=quantity
    )
    return PayableCart(user=user, cart=cart, payment_method=payment_method)


def _persist[T](session: Session, instance: T) -> T:
    session.add(instance)
    session.commit()
    return instance
