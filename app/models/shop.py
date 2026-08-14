"""The parts of the shop that already existed: users, products and carts.

These mirror the supplied base schema; the payment side is in `app.models.payment`.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.columns import CreatedAtMixin, TimestampMixin, enum_column, uuid_primary_key


class CartStatus(StrEnum):
    ACTIVE = "active"
    CHECKED_OUT = "checked_out"
    ABANDONED = "abandoned"


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[UUID] = uuid_primary_key()
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Product(TimestampMixin, db.Model):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
        CheckConstraint("stock_quantity >= 0", name="ck_products_stock_quantity_non_negative"),
    )

    id: Mapped[UUID] = uuid_primary_key()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class Cart(TimestampMixin, db.Model):
    __tablename__ = "carts"
    __table_args__ = (Index("idx_carts_user_id", "user_id"),)

    id: Mapped[UUID] = uuid_primary_key()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[CartStatus] = enum_column(CartStatus, default=CartStatus.ACTIVE)

    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )

    @property
    def is_payable(self) -> bool:
        return self.status is CartStatus.ACTIVE


class CartItem(CreatedAtMixin, db.Model):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_cart_items_quantity_positive"),
        Index("idx_cart_items_cart_id", "cart_id"),
    )

    id: Mapped[UUID] = uuid_primary_key()
    cart_id: Mapped[UUID] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Copied from the product when the item is added, so the price the user saw
    # cannot move underneath them before they pay.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity


class UserPaymentMethod(CreatedAtMixin, db.Model):
    __tablename__ = "user_payment_methods"
    __table_args__ = (Index("idx_user_payment_methods_user_id", "user_id"),)

    id: Mapped[UUID] = uuid_primary_key()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # The card itself lives with the provider; this token is all the shop ever holds.
    provider_token: Mapped[str] = mapped_column(Text, nullable=False)
    last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
