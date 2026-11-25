"""Authentication (ADR-0008): OIDC bearer tokens in, a validated Principal out."""

from workforce_api.auth.principal import AuthenticationError, Principal

__all__ = ["AuthenticationError", "Principal"]
