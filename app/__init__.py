"""Application factory.

Nothing is created at import time, so tests build their own app against their own
database instead of inheriting a global one.
"""

from flask import Flask

from app import models  # noqa: F401  -- registers every mapping before migrations run
from app.cli import register_cli
from app.config import Config
from app.errors import register_error_handlers
from app.extensions import db, migrate
from app.gateway import EXTENSION_KEY, MockPaymentGateway
from app.health import health_blueprint
from app.payments import payments_blueprint


def create_app(config: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)

    db.init_app(app)
    migrate.init_app(app, db)

    app.extensions[EXTENSION_KEY] = MockPaymentGateway()

    app.register_blueprint(health_blueprint)
    app.register_blueprint(payments_blueprint)
    register_error_handlers(app)
    register_cli(app)

    return app
