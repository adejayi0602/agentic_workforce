"""Malware scanning (ADR-0012, threat T10).

A scanner gives one of four verdicts. Only CLEAN lets a file go on to a parser:

- CLEAN: scanned, nothing found.
- INFECTED: a threat was found. The version is quarantined for good.
- FAILED: the scanner couldn't judge the file. Retryable; never treated as clean.
- PENDING: no verdict yet (GuardDuty scans asynchronously). Ask again later.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Verdict(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    FAILED = "failed"
    PENDING = "pending"


@dataclass(frozen=True)
class ScanResult:
    verdict: Verdict
    engine: str
    # Facts for the audit trail: signature names, scanner status codes. Never file content.
    details: dict[str, str] = field(default_factory=dict)


class Scanner(Protocol):
    engine: str

    def scan(self, *, bucket: str, key: str, content: bytes) -> ScanResult: ...


# The industry-standard antivirus test string. Harmless; every scanner flags it.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class EicarScanner:
    """For local development and tests only: flags files containing the EICAR test string.

    It proves the quarantine path works end to end. It is not real malware protection, and
    the worker refuses to start with it outside the local and test environments.
    """

    engine = "eicar-test"

    def scan(self, *, bucket: str, key: str, content: bytes) -> ScanResult:
        if EICAR in content:
            return ScanResult(Verdict.INFECTED, self.engine, {"signature": "EICAR-Test-File"})
        return ScanResult(Verdict.CLEAN, self.engine)


# Tag GuardDuty Malware Protection for S3 writes on each scanned object.
GUARDDUTY_TAG = "GuardDutyMalwareScanStatus"

_GUARDDUTY_VERDICTS = {
    "NO_THREATS_FOUND": Verdict.CLEAN,
    "THREATS_FOUND": Verdict.INFECTED,
    "UNSUPPORTED": Verdict.FAILED,
    "ACCESS_DENIED": Verdict.FAILED,
    "FAILED": Verdict.FAILED,
}


class GuardDutyScanner:
    """Reads the verdict GuardDuty Malware Protection for S3 has tagged onto the object.

    GuardDuty scans on upload, asynchronously. Until the tag appears the verdict is PENDING,
    and the processing workflow asks again after a delay.
    """

    engine = "aws-guardduty"

    def __init__(self, s3_client: Any) -> None:
        self._s3 = s3_client

    def scan(self, *, bucket: str, key: str, content: bytes) -> ScanResult:
        tags = self._s3.get_object_tagging(Bucket=bucket, Key=key).get("TagSet", [])
        status = next((t["Value"] for t in tags if t.get("Key") == GUARDDUTY_TAG), None)
        if status is None:
            return ScanResult(Verdict.PENDING, self.engine)
        verdict = _GUARDDUTY_VERDICTS.get(status, Verdict.FAILED)
        return ScanResult(verdict, self.engine, {"guardduty_status": status})
