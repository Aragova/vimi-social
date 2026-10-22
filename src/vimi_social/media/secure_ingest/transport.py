import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator, Mapping

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult

from vimi_social.media.secure_ingest.errors import TransportError
from vimi_social.media.secure_ingest.models import (
    FetchTimeouts,
    ResolvedTarget,
    ResponseStream,
)


class StaticPinnedResolver(AbstractResolver):
    def __init__(self, host: str, addresses: tuple[str, ...]) -> None:
        self._host = host
        self._addresses = addresses

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        if host != self._host:
            raise OSError(f"unexpected resolver host {host!r}")
        results: list[ResolveResult] = []
        for value in self._addresses:
            address = ipaddress.ip_address(value)
            address_family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
            if family not in {socket.AF_UNSPEC, address_family}:
                continue
            results.append(
                ResolveResult(
                    hostname=host,
                    host=address.compressed,
                    port=port,
                    family=address_family,
                    proto=0,
                    flags=0,
                )
            )
        if not results:
            raise OSError("no pinned address matches the requested address family")
        return results

    async def close(self) -> None:
        return None


class AiohttpResponseStream:
    def __init__(self, response: aiohttp.ClientResponse, session: aiohttp.ClientSession) -> None:
        self._response = response
        self._session = session

    @property
    def status(self) -> int:
        return self._response.status

    @property
    def headers(self) -> Mapping[str, str]:
        return self._response.headers

    async def iter_chunks(self, chunk_size: int) -> AsyncIterator[bytes]:
        async for chunk in self._response.content.iter_chunked(chunk_size):
            yield bytes(chunk)

    async def close(self) -> None:
        self._response.release()
        await self._session.close()


class PinnedAiohttpTransport:
    async def open(
        self,
        target: ResolvedTarget,
        *,
        timeouts: FetchTimeouts,
    ) -> ResponseStream:
        resolver = StaticPinnedResolver(target.host, target.addresses)
        connector = aiohttp.TCPConnector(
            resolver=resolver,
            use_dns_cache=False,
            force_close=True,
            limit=1,
        )
        timeout = aiohttp.ClientTimeout(
            total=timeouts.total_seconds,
            connect=timeouts.connect_seconds,
            sock_connect=timeouts.connect_seconds,
            sock_read=timeouts.read_seconds,
        )
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            auto_decompress=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
            headers={
                "Accept-Encoding": "identity",
                "User-Agent": "ViMi-Social-Media-Ingest/1.0",
            },
        )
        try:
            response = await session.get(target.url, allow_redirects=False)
        except asyncio.CancelledError:
            await session.close()
            raise
        except (TimeoutError, aiohttp.ClientError) as exc:
            await session.close()
            raise TransportError(f"HTTP request failed for {target.host}") from exc
        return AiohttpResponseStream(response, session)
