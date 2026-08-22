from functools import cached_property
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Protocol, cast

import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]

from liyan_server.settings import Settings


class ObjectStorage(Protocol):
    def put(self, key: str, stream: BinaryIO, *, content_type: str) -> None: ...

    def open(self, key: str) -> BinaryIO: ...

    def delete(self, key: str) -> None: ...


class R2ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.r2_bucket
        self._settings = settings

    @cached_property
    def _client(self) -> BaseClient:
        return boto3.client(
            "s3",
            endpoint_url=self._settings.r2_endpoint_url or None,
            aws_access_key_id=self._settings.r2_access_key_id or None,
            aws_secret_access_key=self._settings.r2_secret_access_key or None,
            region_name="auto",
        )

    def _configured_bucket(self) -> str:
        if not self._bucket:
            raise RuntimeError("R2 object storage is not configured.")
        return self._bucket

    def put(self, key: str, stream: BinaryIO, *, content_type: str) -> None:
        self._client.upload_fileobj(
            stream,
            self._configured_bucket(),
            key,
            ExtraArgs={"ContentType": content_type},
        )

    def open(self, key: str) -> BinaryIO:
        temporary = SpooledTemporaryFile(  # noqa: SIM115 - ownership passes to the caller
            max_size=8 * 1024 * 1024,
            mode="w+b",
        )
        self._client.download_fileobj(self._configured_bucket(), key, temporary)
        temporary.seek(0)
        return cast(BinaryIO, temporary)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._configured_bucket(), Key=key)
