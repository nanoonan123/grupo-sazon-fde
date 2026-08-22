"""API health endpoint tests."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint() -> None:
    """The health endpoint reports a successful process status."""

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
