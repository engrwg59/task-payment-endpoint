"""WSGI entry point: `gunicorn wsgi:app` and `flask --app wsgi:app` both use this."""

from app import create_app

app = create_app()
