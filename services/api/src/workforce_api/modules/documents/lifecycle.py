"""Document version lifecycle (ADR-0012). Deterministic: no I/O, no LLM."""

from enum import StrEnum


class VersionStatus(StrEnum):
    AWAITING_UPLOAD = "awaiting_upload"
    UPLOADED = "uploaded"
    EXPIRED = "expired"
    SCANNING = "scanning"
    CLEAN = "clean"
    QUARANTINED = "quarantined"
    SCAN_FAILED = "scan_failed"
    PROCESSING = "processing"
    READY = "ready"
    NEEDS_OCR = "needs_ocr"
    PROCESSING_FAILED = "processing_failed"


S = VersionStatus

TRANSITIONS: dict[VersionStatus, frozenset[VersionStatus]] = {
    S.AWAITING_UPLOAD: frozenset({S.UPLOADED, S.EXPIRED}),
    S.UPLOADED: frozenset({S.SCANNING}),
    S.SCANNING: frozenset({S.CLEAN, S.QUARANTINED, S.SCAN_FAILED}),
    S.SCAN_FAILED: frozenset({S.SCANNING}),
    S.CLEAN: frozenset({S.PROCESSING}),
    S.PROCESSING: frozenset({S.READY, S.NEEDS_OCR, S.PROCESSING_FAILED}),
    S.PROCESSING_FAILED: frozenset({S.PROCESSING}),
    S.READY: frozenset(),
    S.NEEDS_OCR: frozenset(),
    S.QUARANTINED: frozenset(),
    S.EXPIRED: frozenset(),
}

TERMINAL = frozenset(s for s, targets in TRANSITIONS.items() if not targets)

# A parser may only ever read a version that has passed the malware scan.
PARSEABLE = frozenset({S.CLEAN, S.PROCESSING, S.PROCESSING_FAILED})


class InvalidTransitionError(ValueError):
    def __init__(self, current: VersionStatus, target: VersionStatus) -> None:
        super().__init__(f"Cannot move a document version from {current} to {target}.")
        self.current = current
        self.target = target


def can_transition(current: VersionStatus, target: VersionStatus) -> bool:
    return target in TRANSITIONS[current]


def transition(current: VersionStatus, target: VersionStatus) -> VersionStatus:
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
    return target
