"""The endpoint the container healthcheck depends on."""

from __future__ import annotations


def test_health_reports_ok_when_the_database_is_reachable(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
