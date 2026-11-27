"""Object storage (S3 in AWS, SeaweedFS locally). Deliberately small: only what intake needs.

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
    def __init__(self, *, endpoint_url: str | None, region: str) -> None:
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "ObjectStore":
        return cls(endpoint_url=settings.s3_endpoint_url, region=settings.s3_region)

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

    async def get_bytes(self, *, bucket: str, key: str, max_bytes: int) -> bytes:
        """Read a whole object, refusing anything larger than max_bytes."""
        return await to_thread.run_sync(self._get_bytes, bucket, key, max_bytes)

    def _get_bytes(self, bucket: str, key: str, max_bytes: int) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        try:
            data = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(data) > max_bytes:
            raise ValueError(f"Object {key} is larger than {max_bytes} bytes.")
        return bytes(data)

    async def put_bytes(self, *, bucket: str, key: str, data: bytes, content_type: str) -> None:
        await to_thread.run_sync(
            lambda: self._client.put_object(
                Bucket=bucket, Key=key, Body=data, ContentType=content_type
            )
        )

    @property
    def client(self) -> Any:
        """The raw boto3 client, for scanners that read object tags."""
        return self._client

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
