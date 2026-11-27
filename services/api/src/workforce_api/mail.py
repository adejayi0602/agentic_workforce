"""Outgoing email, behind one small interface.

- ConsoleMailer (local and test): logs each message and keeps it in memory, so developers can
  copy the link and browser tests can read it through the dev-only mailbox endpoint.
- In AWS, an SES mailer will implement the same interface (deployment sprint).
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class Mailer(Protocol):
    async def send(self, message: Message) -> None: ...


class ConsoleMailer:
    MAX_KEPT = 200

    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, message: Message) -> None:
        self.sent.append(message)
        del self.sent[: -self.MAX_KEPT]
        logger.info("Email to %s: %s\n%s", message.to, message.subject, message.body)
