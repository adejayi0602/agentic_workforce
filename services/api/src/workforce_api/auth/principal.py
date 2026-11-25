from dataclasses import dataclass
from typing import Literal

FailureReason = Literal[
    "missing_token",
    "malformed",
    "expired",
    "bad_signature",
    "wrong_issuer",
    "wrong_audience",
    "missing_claim",
    "unknown_key",
]


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, as asserted by a validated token. Not yet a platform user."""

    issuer: str
    subject: str
    email: str | None = None
    name: str | None = None


class AuthenticationError(Exception):
    def __init__(self, reason: FailureReason) -> None:
        super().__init__(reason)
        self.reason: FailureReason = reason
