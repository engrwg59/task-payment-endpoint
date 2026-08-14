"""Application configuration, read from the environment."""

import os
from typing import Any, ClassVar

DEFAULT_DATABASE_URL = "postgresql+psycopg://payments:payments@localhost:5432/payments"
DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://payments:payments@localhost:5432/payments_test"


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    # Connections idle in the pool may have been closed by the database; check first.
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict[str, Any]] = {"pool_pre_ping": True}
    TESTING = False


class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    TESTING = True
