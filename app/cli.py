"""Commands registered on the Flask app."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import click
from flask import Flask

from app.extensions import db
from app.models.shop import Cart, CartItem, Product, User, UserPaymentMethod

ALICE_ID = UUID("11111111-1111-1111-1111-111111111111")
BOB_ID = UUID("22222222-2222-2222-2222-222222222222")
KETTLE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
BLANKET_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
MUG_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
ALICE_CART_ID = UUID("c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1")
ALICE_CARD_ID = UUID("11111111-2222-3333-4444-555555555555")

# Bob is not in db.sql. He is here so the declined path can be tried with one request:
# the mock provider refuses any token ending in `_declined`.
BOB_CART_ID = UUID("c2c2c2c2-c2c2-c2c2-c2c2-c2c2c2c2c2c2")
BOB_CARD_ID = UUID("22222222-3333-4444-5555-666666666666")


@click.command("seed-demo")
def seed_demo() -> None:
    """Insert the demo rows from db.sql so the endpoint can be tried by hand."""
    if db.session.get(User, ALICE_ID) is not None:
        click.echo("Demo data is already present.")
        return

    # Written parents first, flushing between the levels. These rows reference each
    # other by raw foreign key value rather than through a relationship(), and a
    # relationship is the only thing that tells SQLAlchemy how to order a flush.
    db.session.add_all(
        [
            User(id=ALICE_ID, email="alice@example.com", name="Alice"),
            User(id=BOB_ID, email="bob@example.com", name="Bob"),
            Product(id=KETTLE_ID, name="Blue Kettle", price=Decimal("45.00"), stock_quantity=10),
            Product(id=BLANKET_ID, name="Wool Blanket", price=Decimal("89.99"), stock_quantity=5),
            Product(id=MUG_ID, name="Ceramic Mug", price=Decimal("12.50"), stock_quantity=100),
        ]
    )
    db.session.flush()

    db.session.add_all(
        [
            Cart(id=ALICE_CART_ID, user_id=ALICE_ID),
            Cart(id=BOB_CART_ID, user_id=BOB_ID),
            UserPaymentMethod(
                id=ALICE_CARD_ID,
                user_id=ALICE_ID,
                provider_token="tok_test_alice_visa",
                last_four="4242",
                is_default=True,
            ),
            UserPaymentMethod(
                id=BOB_CARD_ID,
                user_id=BOB_ID,
                provider_token="tok_test_bob_declined",
                last_four="0002",
                is_default=True,
            ),
        ]
    )
    db.session.flush()

    db.session.add_all(
        [
            CartItem(
                cart_id=ALICE_CART_ID, product_id=KETTLE_ID, quantity=1, unit_price=Decimal("45.00")
            ),
            CartItem(
                cart_id=ALICE_CART_ID, product_id=MUG_ID, quantity=2, unit_price=Decimal("12.50")
            ),
            CartItem(
                cart_id=BOB_CART_ID, product_id=BLANKET_ID, quantity=1, unit_price=Decimal("89.99")
            ),
        ]
    )
    db.session.commit()
    click.echo(f"Alice: cart {ALICE_CART_ID} — 70.00 USD, card authorises.")
    click.echo(f"Bob:   cart {BOB_CART_ID} — 89.99 USD, card declines.")


def register_cli(app: Flask) -> None:
    app.cli.add_command(seed_demo)
