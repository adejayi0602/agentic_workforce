"""Which files may be uploaded (ADR-0012). Deterministic: no I/O.

The media type is decided here from the extension. The client's own claim is never trusted.
"""

import base64
import binascii
import re
from dataclasses import dataclass

from workforce_api.errors import ApiError
from workforce_contracts import ErrorCode

MAX_BYTES = 15 * 1024 * 1024

ALLOWED: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
}

LEGACY: dict[str, str] = {
    ".doc": ".docx",
    ".ppt": ".pptx",
    ".xls": ".xlsx",
    ".docm": ".docx",
    ".pptm": ".pptx",
    ".xlsm": ".xlsx",
}

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\]")


@dataclass(frozen=True)
class AcceptedFile:
    filename: str
    extension: str
    media_type: str
    size_bytes: int
    sha256_hex: str

    @property
    def sha256_b64(self) -> str:
        return base64.b64encode(binascii.unhexlify(self.sha256_hex)).decode()


def accept(filename: str, size_bytes: int, sha256_hex: str) -> AcceptedFile:
    """Validate an upload request, or raise an ApiError a person can act on."""
    # No path separators or control characters, and no leading dots (hidden files, "..").
    name = _UNSAFE.sub("_", filename.strip()).lstrip(".")[:255]
    if not name:
        raise _invalid("filename", "The file needs a name.")
    extension = ("." + name.rsplit(".", 1)[1].lower()) if "." in name else ""

    if extension in LEGACY:
        modern = LEGACY[extension]
        raise ApiError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            f"{extension} files aren't accepted. Please save the file as {modern} and upload "
            "that instead.",
            status_code=422,
            details={"field": "filename", "extension": extension, "use_instead": modern},
        )
    if extension not in ALLOWED:
        raise ApiError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            "Only Word (.docx), PowerPoint (.pptx), Excel (.xlsx), PDF, Markdown and text "
            "files can be uploaded.",
            status_code=422,
            details={"field": "filename", "extension": extension, "allowed": sorted(ALLOWED)},
        )
    if size_bytes <= 0:
        raise _invalid("size_bytes", "The file is empty.")
    if size_bytes > MAX_BYTES:
        raise ApiError(
            ErrorCode.FILE_TOO_LARGE,
            "Files can be up to 15 MB.",
            status_code=422,
            details={"field": "size_bytes", "max_bytes": MAX_BYTES},
        )
    digest = sha256_hex.strip().lower()
    if not _SHA256_HEX.match(digest):
        raise _invalid("sha256", "sha256 must be the file's SHA-256 as 64 hex characters.")

    return AcceptedFile(
        filename=name,
        extension=extension,
        media_type=ALLOWED[extension],
        size_bytes=size_bytes,
        sha256_hex=digest,
    )


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_FAILED, message, status_code=422, details={"field": field})
