import asyncio
import hashlib
import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from vimi_social.media.secure_ingest.addressing import DestinationPolicy
from vimi_social.media.secure_ingest.errors import (
    ContentValidationError,
    DownloadLimitError,
    RedirectPolicyError,
    TransportError,
)
from vimi_social.media.secure_ingest.models import (
    FetchLimits,
    FetchResult,
    OneHopTransport,
    ResponseStream,
)
from vimi_social.media.secure_ingest.sniff import (
    sniff_media_format,
    validate_declared_content_type,
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_PREFIX_BYTES = 64
_FILE_HASH_CHUNK_BYTES = 1024 * 1024


class SecureMediaFetcher:
    def __init__(
        self,
        destination_policy: DestinationPolicy,
        transport: OneHopTransport,
        *,
        limits: FetchLimits | None = None,
    ) -> None:
        self._destination_policy = destination_policy
        self._transport = transport
        self._limits = limits or FetchLimits()

    async def fetch(self, raw_url: str, destination_dir: Path) -> FetchResult:
        current_url = raw_url
        visited: set[str] = set()
        for redirect_count in range(self._limits.max_redirects + 1):
            target = await self._destination_policy.resolve_url(
                current_url,
                timeout_seconds=self._limits.timeouts.connect_seconds,
            )
            if target.url in visited:
                raise RedirectPolicyError("redirect cycle detected")
            visited.add(target.url)
            response = await self._transport.open(target, timeouts=self._limits.timeouts)
            try:
                if response.status in _REDIRECT_STATUSES:
                    if redirect_count >= self._limits.max_redirects:
                        raise RedirectPolicyError("redirect limit exceeded")
                    location = _header_value(response, "Location")
                    if location is None or not location.strip():
                        raise RedirectPolicyError("redirect response is missing Location")
                    next_url = urljoin(target.url, location.strip())
                    next_scheme = urlsplit(next_url).scheme.lower()
                    if target.scheme == "https" and next_scheme == "http":
                        raise RedirectPolicyError(
                            "HTTPS-to-HTTP redirect downgrade is not accepted"
                        )
                    current_url = next_url
                    continue
                if not 200 <= response.status < 300:
                    raise TransportError(f"unexpected HTTP status {response.status}")
                return await self._consume_response(
                    response,
                    destination_dir=destination_dir,
                    final_url=target.url,
                    redirect_count=redirect_count,
                )
            finally:
                await response.close()
        raise RedirectPolicyError("redirect state exhausted unexpectedly")

    async def _consume_response(
        self,
        response: ResponseStream,
        *,
        destination_dir: Path,
        final_url: str,
        redirect_count: int,
    ) -> FetchResult:
        expected_length = _parse_content_length(_header_value(response, "Content-Length"))
        if expected_length is not None and expected_length > self._limits.max_bytes:
            raise DownloadLimitError("declared response size exceeds configured byte limit")
        content_encoding = _header_value(response, "Content-Encoding")
        if content_encoding is not None and content_encoding.strip().lower() not in {
            "",
            "identity",
        }:
            raise ContentValidationError("non-identity Content-Encoding is not accepted")

        await asyncio.to_thread(destination_dir.mkdir, parents=True, exist_ok=True)
        file_descriptor, temp_name = tempfile.mkstemp(
            prefix=".vimi-ingest-",
            suffix=".part",
            dir=destination_dir,
        )
        open_descriptor: int | None = file_descriptor
        temp_path: Path | None = Path(temp_name)
        digest = hashlib.sha256()
        total = 0
        prefix = bytearray()
        try:
            async for chunk in response.iter_chunks(self._limits.chunk_size):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self._limits.max_bytes:
                    raise DownloadLimitError("streamed response exceeded configured byte limit")
                digest.update(chunk)
                if len(prefix) < _PREFIX_BYTES:
                    prefix.extend(chunk[: _PREFIX_BYTES - len(prefix)])
                await _write_all_cancellation_safe(file_descriptor, chunk)

            await _fsync_cancellation_safe(file_descriptor)
            os.close(file_descriptor)
            open_descriptor = None
            if expected_length is not None and total != expected_length:
                raise ContentValidationError(
                    "received body length does not match Content-Length"
                )
            if total == 0:
                raise ContentValidationError("empty response is not accepted as media")
            media = sniff_media_format(bytes(prefix))
            content_type = validate_declared_content_type(
                _header_value(response, "Content-Type"),
                media,
            )
            sha256 = digest.hexdigest()
            final_path = destination_dir / f"{sha256}.{media.extension}"
            assert temp_path is not None
            await _promote_cancellation_safe(
                temp_path,
                final_path,
                expected_digest=sha256,
                expected_size=total,
            )
            temp_path = None
            return FetchResult(
                path=final_path,
                sha256=sha256,
                size_bytes=total,
                media_format=media.name,
                content_type=content_type,
                final_url=final_url,
                redirect_count=redirect_count,
            )
        finally:
            if open_descriptor is not None:
                os.close(open_descriptor)
            if temp_path is not None:
                await asyncio.to_thread(_unlink_if_exists, temp_path)


async def promote_validated_fetch(
    fetched: FetchResult,
    destination_dir: Path,
) -> FetchResult:
    """Move a validated staged artifact into durable content-addressed storage."""
    await asyncio.to_thread(destination_dir.mkdir, parents=True, exist_ok=True)
    suffix = fetched.path.suffix
    if not suffix:
        raise ContentValidationError("staged media artifact has no file extension")
    final_path = destination_dir / f"{fetched.sha256}{suffix}"
    await _promote_cancellation_safe(
        fetched.path,
        final_path,
        expected_digest=fetched.sha256,
        expected_size=fetched.size_bytes,
    )
    return FetchResult(
        path=final_path,
        sha256=fetched.sha256,
        size_bytes=fetched.size_bytes,
        media_format=fetched.media_format,
        content_type=fetched.content_type,
        final_url=fetched.final_url,
        redirect_count=fetched.redirect_count,
    )


async def _write_all_cancellation_safe(file_descriptor: int, data: bytes) -> None:
    task = asyncio.create_task(asyncio.to_thread(_write_all, file_descriptor, data))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


async def _fsync_cancellation_safe(file_descriptor: int) -> None:
    task = asyncio.create_task(asyncio.to_thread(os.fsync, file_descriptor))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


async def _promote_cancellation_safe(
    temp_path: Path,
    final_path: Path,
    *,
    expected_digest: str,
    expected_size: int,
) -> None:
    task = asyncio.create_task(
        asyncio.to_thread(
            _promote_artifact,
            temp_path,
            final_path,
            expected_digest,
            expected_size,
        )
    )
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


def _promote_artifact(
    temp_path: Path,
    final_path: Path,
    expected_digest: str,
    expected_size: int,
) -> None:
    try:
        os.link(temp_path, final_path, follow_symlinks=False)
    except FileExistsError:
        _validate_existing_artifact(final_path, expected_digest, expected_size)
        _unlink_if_exists(temp_path)
        return
    _unlink_if_exists(temp_path)


def _validate_existing_artifact(
    final_path: Path,
    expected_digest: str,
    expected_size: int,
) -> None:
    existing_stat = os.stat(final_path, follow_symlinks=False)
    if not stat.S_ISREG(existing_stat.st_mode) or existing_stat.st_size != expected_size:
        raise ContentValidationError(
            "existing digest-named artifact does not match downloaded media"
        )
    digest = hashlib.sha256()
    with final_path.open("rb") as existing_file:
        while chunk := existing_file.read(_FILE_HASH_CHUNK_BYTES):
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise ContentValidationError(
            "existing digest-named artifact does not match downloaded media"
        )


def _write_all(file_descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(file_descriptor, remaining)
        if written <= 0:
            raise OSError("temporary media write made no progress")
        remaining = remaining[written:]


def _unlink_if_exists(path: Path) -> None:
    with suppress(FileNotFoundError):
        path.unlink()


def _header_value(response: ResponseStream, name: str) -> str | None:
    direct = response.headers.get(name)
    if direct is not None:
        return direct
    lowered = name.lower()
    for key, value in response.headers.items():
        if key.lower() == lowered:
            return value
    return None


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or not stripped.isdecimal():
        raise ContentValidationError("Content-Length is invalid")
    return int(stripped)
