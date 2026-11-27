"""Which files may be uploaded (ADR-0012)."""

import pytest

from workforce_api.errors import ApiError
from workforce_api.modules.documents.file_policy import MAX_BYTES, accept
from workforce_contracts import ErrorCode

SHA = "ab" * 32


def error(filename: str, size: int = 100, sha: str = SHA) -> ApiError:
    with pytest.raises(ApiError) as info:
        accept(filename, size, sha)
    return info.value


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [
        (
            "Payments SRS.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "Kick-off deck.PPTX",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        ("estimates.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("brief.pdf", "application/pdf"),
        ("notes.md", "text/markdown"),
        ("readme.txt", "text/plain"),
    ],
)
def test_accepted_formats_get_a_server_chosen_media_type(filename: str, media_type: str) -> None:
    assert accept(filename, 100, SHA).media_type == media_type


@pytest.mark.parametrize(
    ("legacy", "modern"),
    [(".doc", ".docx"), (".ppt", ".pptx"), (".xls", ".xlsx"), (".docm", ".docx")],
)
def test_legacy_and_macro_formats_are_refused_with_advice(legacy: str, modern: str) -> None:
    err = error(f"old{legacy}")
    assert err.code == ErrorCode.UNSUPPORTED_FILE_TYPE
    assert modern in err.message
    assert err.details["use_instead"] == modern


@pytest.mark.parametrize(
    "filename", ["virus.exe", "page.html", "archive.zip", "noextension", "srs.docx.exe"]
)
def test_other_types_are_refused(filename: str) -> None:
    assert error(filename).code == ErrorCode.UNSUPPORTED_FILE_TYPE


def test_size_limits() -> None:
    assert accept("a.docx", MAX_BYTES, SHA).size_bytes == MAX_BYTES
    assert error("a.docx", size=MAX_BYTES + 1).code == ErrorCode.FILE_TOO_LARGE
    assert error("a.docx", size=0).code == ErrorCode.VALIDATION_FAILED


def test_checksum_must_be_sha256_hex() -> None:
    assert accept("a.docx", 1, SHA.upper()).sha256_hex == SHA
    assert error("a.docx", sha="xyz").details == {"field": "sha256"}


def test_filenames_are_sanitised() -> None:
    assert accept("../../etc/passwd.txt", 1, SHA).filename == "_.._etc_passwd.txt"
    assert accept("a\x00b.txt", 1, SHA).filename == "a_b.txt"
    assert accept("..srs.md", 1, SHA).filename == "srs.md"
    assert error("...").details == {"field": "filename"}
    assert error(".hidden").code == ErrorCode.UNSUPPORTED_FILE_TYPE  # no extension left


def test_base64_checksum_for_s3() -> None:
    import base64
    import hashlib

    digest = hashlib.sha256(b"hello").hexdigest()
    expected = base64.b64encode(hashlib.sha256(b"hello").digest()).decode()
    assert accept("a.txt", 5, digest).sha256_b64 == expected
