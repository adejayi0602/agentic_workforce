from typing import Any

import pytest

from workforce_intake.scanning import (
    EICAR,
    GUARDDUTY_TAG,
    EicarScanner,
    GuardDutyScanner,
    Verdict,
)


def test_eicar_scanner_flags_the_test_file_anywhere_in_content() -> None:
    result = EicarScanner().scan(bucket="b", key="k", content=b"prefix " + EICAR + b" suffix")
    assert result.verdict == Verdict.INFECTED
    assert result.details == {"signature": "EICAR-Test-File"}


def test_eicar_scanner_passes_ordinary_content() -> None:
    assert EicarScanner().scan(bucket="b", key="k", content=b"# SRS").verdict == Verdict.CLEAN


class FakeS3:
    def __init__(self, tags: list[dict[str, str]]) -> None:
        self.tags = tags
        self.calls: list[tuple[str, str]] = []

    def get_object_tagging(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.calls.append((Bucket, Key))
        return {"TagSet": self.tags}


@pytest.mark.parametrize(
    ("status", "verdict"),
    [
        ("NO_THREATS_FOUND", Verdict.CLEAN),
        ("THREATS_FOUND", Verdict.INFECTED),
        ("UNSUPPORTED", Verdict.FAILED),
        ("ACCESS_DENIED", Verdict.FAILED),
        ("FAILED", Verdict.FAILED),
        ("SOMETHING_NEW", Verdict.FAILED),  # unknown statuses never count as clean
    ],
)
def test_guardduty_tag_maps_to_verdict(status: str, verdict: Verdict) -> None:
    s3 = FakeS3([{"Key": "other", "Value": "x"}, {"Key": GUARDDUTY_TAG, "Value": status}])
    result = GuardDutyScanner(s3).scan(bucket="uploads", key="org/1/f", content=b"")
    assert result.verdict == verdict
    assert result.details == {"guardduty_status": status}
    assert s3.calls == [("uploads", "org/1/f")]


def test_guardduty_without_a_tag_yet_is_pending() -> None:
    assert GuardDutyScanner(FakeS3([])).scan(bucket="b", key="k", content=b"").verdict == (
        Verdict.PENDING
    )
