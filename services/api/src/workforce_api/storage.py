"""Object storage (S3 in AWS, MinIO locally). Deliberately small: only what intake needs.

boto3 is synchronous, so calls run in a worker thread to keep the event loop free.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from anyio import to_thread
from botocore.config import Config
from botocore.exceptions import ClientError

from workforce_api.config import Settings

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class StoredObject:
    size: int
    sha256_hex: str


class ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def presign_put(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str,
        size: int,
        sha256_b64: str,
        ttl_seconds: int,
    ) -> PresignedUpload:
        """A PUT URL signed for this exact size, content type and SHA-256.

        S3 refuses an upload whose headers don't match the signature, or whose body doesn't
        match the checksum. The API still verifies the stored object itself on completion.
        """
        url = self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": size,
                "ChecksumSHA256": sha256_b64,
            },
            ExpiresIn=ttl_seconds,
        )
        return PresignedUpload(
            url=url,
            method="PUT",
            headers={"Content-Type": content_type, "x-amz-checksum-sha256": sha256_b64},
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )

    async def measure(self, *, bucket: str, key: str, max_bytes: int) -> StoredObject | None:
        """Stream the object and return its real size and SHA-256, or None if it isn't there.

        Stops reading past max_bytes, so an oversized object can't tie up the API.
        """
        return await to_thread.run_sync(self._measure, bucket, key, max_bytes)

    def _measure(self, bucket: str, key: str, max_bytes: int) -> StoredObject | None:
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return None
            raise
        digest = hashlib.sha256()
        size = 0
        body = response["Body"]
        try:
            while chunk := body.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    break
                digest.update(chunk)
        finally:
            body.close()
        return StoredObject(size=size, sha256_hex=digest.hexdigest())
