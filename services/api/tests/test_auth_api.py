"""Authentication at the HTTP boundary. No database needed: requests fail before it."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from workforce_api.config import Settings
from workforce_api.main import create_app


def test_dev_auth_is_refused_outside_local_and_test() -> None:
    for env in ("development", "staging", "production"):
        with pytest.raises(ValidationError, match="not allowed"):
            Settings(env=env, auth_mode="dev")


def test_oidc_mode_is_allowed_in_production() -> None:
    settings = Settings(env="production", auth_mode="oidc", auth_issuer="https://cognito.test/pool")
    assert settings.jwks_url == "https://cognito.test/pool/.well-known/jwks.json"


def test_request_without_token_gets_401_envelope() -> None:
    with TestClient(create_app(Settings(env="test"))) as client:
        response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")
    error = response.json()["error"]
    assert error["code"] == "UNAUTHENTICATED"
    assert error["details"] == {"reason": "missing_token"}


def test_request_with_invalid_token_gets_401() -> None:
    with TestClient(create_app(Settings(env="test"))) as client:
        response = client.get("/api/v1/me", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_dev_token_endpoint_exists_only_in_dev_mode() -> None:
    with TestClient(create_app(Settings(env="test"))) as client:
        ok = client.post("/api/v1/dev-auth/token", json={"subject": "alice"})
    assert ok.status_code == 200
    assert ok.json()["token_type"] == "Bearer"  # noqa: S105

    oidc = Settings(env="production", auth_mode="oidc", auth_issuer="https://cognito.test/pool")
    with TestClient(create_app(oidc)) as client:
        missing = client.post("/api/v1/dev-auth/token", json={"subject": "alice"})
    assert missing.status_code == 404
