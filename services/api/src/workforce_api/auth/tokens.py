"""Bearer token validation.

Only RS256 is accepted, so `alg: none` and HMAC key-confusion attacks are rejected outright.
Issuer, expiry, issued-at and subject are required. The audience may arrive as `aud` (OIDC ID
tokens, our dev tokens) or as `client_id` (Cognito access tokens); either must match.
"""

from collections.abc import Callable
from typing import Any

import jwt
from anyio import to_thread

from workforce_api.auth.principal import AuthenticationError, Principal

ALGORITHMS = ["RS256"]
REQUIRED_CLAIMS = ["exp", "iat", "iss", "sub"]

KeyResolver = Callable[[str], Any]
"""Given the raw token, return the public key that should have signed it."""


class TokenValidator:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        key_resolver: KeyResolver,
        clock_skew_seconds: int = 30,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._resolve_key = key_resolver
        self._leeway = clock_skew_seconds

    def validate(self, token: str) -> Principal:
        try:
            key = self._resolve_key(token)
        except AuthenticationError:
            raise
        except (jwt.PyJWKClientError, jwt.DecodeError) as exc:
            raise AuthenticationError("unknown_key") from exc

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS, "verify_aud": False},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("expired") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthenticationError("wrong_issuer") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise AuthenticationError("missing_claim") from exc
        except jwt.InvalidSignatureError as exc:
            raise AuthenticationError("bad_signature") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("malformed") from exc

        if not self._audience_matches(claims):
            raise AuthenticationError("wrong_audience")
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("missing_claim")

        return Principal(
            issuer=self._issuer,
            subject=subject,
            email=_optional_str(claims.get("email")),
            name=_optional_str(claims.get("name")),
        )

    async def validate_async(self, token: str) -> Principal:
        """Key resolution may fetch JWKS over HTTP, so run it off the event loop."""
        return await to_thread.run_sync(self.validate, token)

    def _audience_matches(self, claims: dict[str, Any]) -> bool:
        aud = claims.get("aud")
        audiences = [aud] if isinstance(aud, str) else list(aud or [])
        return self._audience in audiences or claims.get("client_id") == self._audience


def jwks_key_resolver(jwks_url: str) -> KeyResolver:
    """Resolve signing keys from an issuer's JWKS endpoint, cached in memory."""
    client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)

    def resolve(token: str) -> Any:
        return client.get_signing_key_from_jwt(token).key

    return resolve


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
