"""Cloudflare R2, and the two ways it can fail to be there.

An operator has to be able to tell "nobody configured this" from "the bucket is
having a bad minute": the first is permanent until somebody edits configuration,
the second usually resolves itself. Presenting them identically is what makes an
unconfigured bucket cost an afternoon, so the difference is modelled here rather
than guessed at the call site.
"""

from functools import cached_property
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Literal, Protocol, cast

import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from liyan_server.settings import Settings

type ObjectStorageState = Literal["ready", "unconfigured", "unreachable"]

#: Settings an operator must fill in before a file 来源 can be accepted, in the
#: order they appear in `.env.example`.
REQUIRED_SETTINGS: tuple[tuple[str, str], ...] = (
    ("r2_endpoint_url", "LIYAN_R2_ENDPOINT_URL"),
    ("r2_access_key_id", "LIYAN_R2_ACCESS_KEY_ID"),
    ("r2_secret_access_key", "LIYAN_R2_SECRET_ACCESS_KEY"),
    ("r2_bucket", "LIYAN_R2_BUCKET"),
)

UNCONFIGURED_MESSAGE = (
    "File storage is not configured on this server, so uploads cannot be accepted. "
    "Retrying will not help. Paste the text or submit a URL instead, or ask an "
    "operator to configure object storage."
)


class ObjectStorageUnconfigured(RuntimeError):
    """No credentials or bucket, so no upload can ever succeed as things stand."""


class ObjectStorage(Protocol):
    def put(self, key: str, stream: BinaryIO, *, content_type: str) -> None: ...

    def open(self, key: str) -> BinaryIO: ...

    def delete(self, key: str) -> None: ...

    def missing_settings(self) -> tuple[str, ...]:
        """Setting names an operator still has to fill in.

        Storage that exists by construction, such as an in-memory double, needs
        nothing and says so.
        """
        return ()

    def state(self) -> ObjectStorageState:
        """Whether storage can be used right now, without writing anything."""
        return "ready"


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

    @cached_property
    def _probe_client(self) -> BaseClient:
        """A client for readiness only, bounded so a probe cannot hang.

        Readiness is polled continuously by the platform, so this one refuses to
        retry and gives up quickly; the working client keeps its own defaults.
        """
        return boto3.client(
            "s3",
            endpoint_url=self._settings.r2_endpoint_url or None,
            aws_access_key_id=self._settings.r2_access_key_id or None,
            aws_secret_access_key=self._settings.r2_secret_access_key or None,
            region_name="auto",
            config=Config(
                connect_timeout=2,
                read_timeout=2,
                retries={"max_attempts": 1},
            ),
        )

    def missing_settings(self) -> tuple[str, ...]:
        return tuple(
            name
            for attribute, name in REQUIRED_SETTINGS
            if not str(getattr(self._settings, attribute, "")).strip()
        )

    def state(self) -> ObjectStorageState:
        if self.missing_settings():
            # Answered without a network call: nothing is configured to call.
            return "unconfigured"
        try:
            self._probe_client.head_bucket(Bucket=self._bucket)
        except Exception:
            return "unreachable"
        return "ready"

    def _configured_bucket(self) -> str:
        if missing := self.missing_settings():
            raise ObjectStorageUnconfigured(
                f"Object storage is not configured: {', '.join(missing)}."
            )
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
