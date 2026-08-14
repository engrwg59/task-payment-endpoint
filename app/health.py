"""Liveness endpoint, used by the container healthcheck declared in compose.yml.

The database is checked too: an API that cannot reach PostgreSQL cannot take a
payment, so reporting it healthy would be a lie that hides an outage.
"""

from http import HTTPStatus

from flask import Blueprint, jsonify
from sqlalchemy import text

from app.extensions import db

health_blueprint = Blueprint("health", __name__)


@health_blueprint.get("/health")
def health():
    db.session.execute(text("SELECT 1"))
    return jsonify({"status": "ok"}), HTTPStatus.OK
