"""Shared fixtures.

Tests run against a real PostgreSQL database because the behaviour under test is
PostgreSQL's: row locks, a partial unique index, and what happens when two connections
race. SQLite would pass while proving nothing.

The payment flow is allowed to commit for real rather than being wrapped in a
transaction that is rolled back afterwards. Those commits are the design, so a fixture
that neutralised them would test something the application never does. Isolation comes
from emptying the tables between tests instead.
"""

from __future__ import annotations

import pytest
from flask import Flask
from flask_migrate import upgrade
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.gateway import EXTENSION_KEY, MockPaymentGateway

#: Emptied between tests, children before parents.
TABLES_IN_DELETE_ORDER = (
    "payment_events",
    "payments",
    "cart_items",
    "carts",
    "user_payment_methods",
    "products",
    "users",
)


@pytest.fixture(scope="session")
def app() -> Flask:
    """One application, with the schema built from the migrations exactly once."""
    application = create_app(TestConfig)

    with application.app_context():
        db.session.execute(text("DROP SCHEMA public CASCADE"))
        db.session.execute(text("CREATE SCHEMA public"))
        db.session.commit()
        upgrade()

    return application


@pytest.fixture
def session(app: Flask) -> Session:
    """A database session, with everything it leaves behind cleaned up afterwards."""
    with app.app_context():
        yield db.session

        db.session.rollback()
        for table in TABLES_IN_DELETE_ORDER:
            db.session.execute(text(f"DELETE FROM {table}"))
        db.session.commit()
        db.session.remove()


@pytest.fixture
def gateway(app: Flask) -> MockPaymentGateway:
    """The gateway the endpoint will use, fresh for every test."""
    payment_gateway = MockPaymentGateway()
    app.extensions[EXTENSION_KEY] = payment_gateway
    return payment_gateway


@pytest.fixture
def client(app: Flask, session: Session, gateway: MockPaymentGateway):
    return app.test_client()
