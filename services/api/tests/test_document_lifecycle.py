"""The document version lifecycle (ADR-0012), pinned."""

from itertools import pairwise

import pytest

from workforce_api.modules.documents.lifecycle import (
    PARSEABLE,
    TERMINAL,
    TRANSITIONS,
    InvalidTransitionError,
    VersionStatus,
    can_transition,
    transition,
)
from workforce_api.modules.documents.models import STATUSES

S = VersionStatus


def test_every_status_has_a_rule_and_matches_the_database_check() -> None:
    assert set(TRANSITIONS) == set(VersionStatus)
    assert {s.value for s in VersionStatus} == set(STATUSES)


def test_terminal_states() -> None:
    assert {S.READY, S.NEEDS_OCR, S.QUARANTINED, S.EXPIRED} == TERMINAL


def test_happy_path() -> None:
    path = [S.AWAITING_UPLOAD, S.UPLOADED, S.SCANNING, S.CLEAN, S.PROCESSING, S.READY]
    for current, target in pairwise(path):
        assert transition(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.UPLOADED, S.PROCESSING),  # skipping the scan
        (S.SCANNING, S.PROCESSING),  # processing before the verdict
        (S.QUARANTINED, S.CLEAN),  # un-quarantining
        (S.QUARANTINED, S.PROCESSING),
        (S.READY, S.PROCESSING),  # rewriting a finished version
        (S.EXPIRED, S.UPLOADED),
        (S.AWAITING_UPLOAD, S.SCANNING),
    ],
)
def test_forbidden_transitions(current: VersionStatus, target: VersionStatus) -> None:
    assert not can_transition(current, target)
    with pytest.raises(InvalidTransitionError):
        transition(current, target)


def test_only_scanned_clean_versions_are_parseable() -> None:
    assert {S.CLEAN, S.PROCESSING, S.PROCESSING_FAILED} == PARSEABLE
    # The only way into the parseable states is through CLEAN, i.e. a passed scan.
    entries = {source for source, targets in TRANSITIONS.items() if targets & PARSEABLE}
    assert entries - PARSEABLE == {S.SCANNING}
    assert TRANSITIONS[S.SCANNING] & PARSEABLE == {S.CLEAN}


def test_failed_steps_can_be_retried() -> None:
    assert can_transition(S.SCAN_FAILED, S.SCANNING)
    assert can_transition(S.PROCESSING_FAILED, S.PROCESSING)
