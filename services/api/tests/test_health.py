from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from workforce_api.correlation import CORRELATION_HEADER
from workforce_api.main import create_app
from workforce_api.routes.health import get_database_check


def _client(db_ok: bool) -> TestClient:
    app = create_app()

    async def fake_check() -> bool:
        return db_ok

    app.dependency_overrides[get_database_check] = lambda: fake_check
    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _client(db_ok=True) as c:
        yield c


def test_liveness(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_when_dependencies_up(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": True}}


def test_readiness_returns_spec_error_envelope_when_database_down() -> None:
    with _client(db_ok=False) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DEPENDENCY_UNAVAILABLE"
    assert error["details"] == {"checks": {"database": False}}
    assert error["correlation_id"] == response.headers[CORRELATION_HEADER]


def test_correlation_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    UUID(response.headers[CORRELATION_HEADER])  # raises if not a UUID


def test_valid_incoming_correlation_id_is_echoed(client: TestClient) -> None:
    incoming = "6b0c6f2e-2f5b-4b8e-9a51-0d6f4a1b2c3d"
    response = client.get("/api/v1/health", headers={CORRELATION_HEADER: incoming})
    assert response.headers[CORRELATION_HEADER] == incoming


def test_invalid_incoming_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={CORRELATION_HEADER: "not-a-uuid"})
    assert response.headers[CORRELATION_HEADER] != "not-a-uuid"
    UUID(response.headers[CORRELATION_HEADER])


def test_unknown_route_uses_spec_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["correlation_id"] == response.headers[CORRELATION_HEADER]
