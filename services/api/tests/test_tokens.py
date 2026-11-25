"""Token validation: the accepted path and the attacks it must refuse."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from workforce_api.auth.dev_issuer import DEV_KEY_ID, DevTokenIssuer
from workforce_api.auth.principal import AuthenticationError
from workforce_api.auth.tokens import TokenValidator

ISSUER = "https://issuer.test"
AUDIENCE = "workforce-api"


@pytest.fixture
def issuer() -> DevTokenIssuer:
    return DevTokenIssuer(issuer=ISSUER, audience=AUDIENCE)


@pytest.fixture
def validator(issuer: DevTokenIssuer) -> TokenValidator:
    return TokenValidator(issuer=ISSUER, audience=AUDIENCE, key_resolver=issuer.resolve_key)


def reason(validator: TokenValidator, token: str) -> str:
    with pytest.raises(AuthenticationError) as info:
        validator.validate(token)
    return info.value.reason


def test_valid_token_yields_principal(issuer: DevTokenIssuer, validator: TokenValidator) -> None:
    token = issuer.issue(subject="alice", email="alice@example.com", name="Alice")
    principal = validator.validate(token)
    assert principal.issuer == ISSUER
    assert principal.subject == "alice"
    assert principal.email == "alice@example.com"
    assert principal.name == "Alice"


def test_cognito_style_access_token_with_client_id_is_accepted(
    issuer: DevTokenIssuer, validator: TokenValidator
) -> None:
    token = issuer.issue(subject="bob", overrides={"aud": None, "client_id": AUDIENCE})
    assert validator.validate(token).subject == "bob"


def test_expired_token_is_rejected(issuer: DevTokenIssuer, validator: TokenValidator) -> None:
    past = int(time.time()) - 3600
    token = issuer.issue(subject="alice", overrides={"iat": past - 60, "exp": past})
    assert reason(validator, token) == "expired"


def test_small_clock_skew_is_tolerated(issuer: DevTokenIssuer, validator: TokenValidator) -> None:
    now = int(time.time())
    token = issuer.issue(subject="alice", overrides={"exp": now - 5})
    assert validator.validate(token).subject == "alice"


def test_wrong_issuer_is_rejected(issuer: DevTokenIssuer, validator: TokenValidator) -> None:
    token = issuer.issue(subject="alice", overrides={"iss": "https://evil.test"})
    assert reason(validator, token) == "wrong_issuer"


def test_wrong_audience_is_rejected(issuer: DevTokenIssuer, validator: TokenValidator) -> None:
    token = issuer.issue(subject="alice", overrides={"aud": "some-other-app"})
    assert reason(validator, token) == "wrong_audience"


def test_missing_subject_is_rejected(issuer: DevTokenIssuer, validator: TokenValidator) -> None:
    token = issuer.issue(subject="alice", overrides={"sub": None})
    assert reason(validator, token) in {"missing_claim", "malformed"}


def test_token_signed_by_another_key_is_rejected(validator: TokenValidator) -> None:
    impostor = DevTokenIssuer(issuer=ISSUER, audience=AUDIENCE)  # same kid, different key
    assert reason(validator, impostor.issue(subject="alice")) == "bad_signature"


def test_unsigned_alg_none_token_is_rejected(validator: TokenValidator) -> None:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "alice", "iat": now, "exp": now + 60}
    token = jwt.encode(claims, key=None, algorithm="none", headers={"kid": DEV_KEY_ID})
    assert reason(validator, token) == "malformed"


def test_hmac_key_confusion_is_rejected(validator: TokenValidator) -> None:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "alice", "iat": now, "exp": now + 60}
    token = jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": DEV_KEY_ID})
    assert reason(validator, token) == "malformed"


def test_unknown_key_id_is_rejected(validator: TokenValidator) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "alice", "iat": now, "exp": now + 60}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "someone-else"})
    assert reason(validator, token) == "unknown_key"


def test_garbage_is_rejected(validator: TokenValidator) -> None:
    assert reason(validator, "not.a.token") == "unknown_key"
