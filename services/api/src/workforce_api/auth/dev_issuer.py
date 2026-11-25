"""A token issuer for local development and tests only.

It mints RS256 tokens shaped like real OIDC tokens, so the validation path is identical to
production. The key pair lives only in process memory, so tokens die with the process.
Settings refuse auth_mode 'dev' outside the local and test environments.
"""

import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

DEV_KEY_ID = "workforce-dev-1"


class DevTokenIssuer:
    def __init__(self, *, issuer: str, audience: str) -> None:
        self.issuer = issuer
        self.audience = audience
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @property
    def public_key(self) -> RSAPublicKey:
        return self._private_key.public_key()

    def resolve_key(self, token: str) -> Any:
        """Key resolver for TokenValidator: only tokens signed with our key id are accepted."""
        header = jwt.get_unverified_header(token)
        if header.get("kid") != DEV_KEY_ID:
            raise jwt.PyJWKClientError("unknown key id")
        return self.public_key

    def issue(
        self,
        *,
        subject: str,
        email: str | None = None,
        name: str | None = None,
        ttl_seconds: int = 3600,
        overrides: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": subject,
            "iat": now,
            "exp": now + ttl_seconds,
        }
        if email:
            claims["email"] = email
        if name:
            claims["name"] = name
        claims.update(overrides or {})
        return jwt.encode(claims, self._private_key, algorithm="RS256", headers={"kid": DEV_KEY_ID})
