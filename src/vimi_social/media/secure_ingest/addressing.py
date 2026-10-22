import asyncio
import ipaddress
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

from vimi_social.media.secure_ingest.errors import InvalidUrlError, UnsafeAddressError
from vimi_social.media.secure_ingest.models import ResolvedTarget


class HostResolver(Protocol):
    async def resolve(self, host: str, port: int) -> Sequence[str]: ...


class SystemHostResolver:
    async def resolve(self, host: str, port: int) -> Sequence[str]:
        def _lookup() -> list[str]:
            records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses: list[str] = []
            for _family, _socktype, _proto, _canonname, sockaddr in records:
                address = str(sockaddr[0])
                if address not in addresses:
                    addresses.append(address)
            return addresses

        try:
            return await asyncio.to_thread(_lookup)
        except socket.gaierror as exc:
            raise UnsafeAddressError(f"hostname resolution failed for {host}") from exc


@dataclass(frozen=True, slots=True)
class DestinationPolicy:
    resolver: HostResolver

    async def resolve_url(
        self,
        raw_url: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ResolvedTarget:
        parsed = self._parse_and_normalize(raw_url)
        scheme = parsed.scheme
        host = parsed.hostname
        if host is None:
            raise InvalidUrlError("URL must include a hostname")
        port = 443 if scheme == "https" else 80

        literal = _parse_ip_literal(host)
        if literal is not None:
            addresses = (_validated_public_ip(literal),)
        else:
            resolved = await _resolve_with_timeout(
                self.resolver,
                host,
                port,
                timeout_seconds=timeout_seconds,
            )
            if not resolved:
                raise UnsafeAddressError(f"hostname {host} resolved to no addresses")
            addresses = tuple(_validated_public_ip(value) for value in resolved)

        return ResolvedTarget(
            url=urlunsplit(parsed),
            scheme=scheme,
            host=host,
            port=port,
            addresses=tuple(dict.fromkeys(addresses)),
        )

    @staticmethod
    def _parse_and_normalize(raw_url: str) -> SplitResult:
        if not raw_url or raw_url.strip() != raw_url:
            raise InvalidUrlError("URL must be non-empty and must not contain outer whitespace")
        try:
            parsed = urlsplit(raw_url)
        except ValueError as exc:
            raise InvalidUrlError("URL could not be parsed") from exc
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise InvalidUrlError("only http and https URLs are accepted")
        if parsed.username is not None or parsed.password is not None:
            raise InvalidUrlError("URL credentials are not accepted")
        if parsed.hostname is None:
            raise InvalidUrlError("URL must include a hostname")
        if "%" in parsed.hostname:
            raise InvalidUrlError("scoped or percent-encoded hostnames are not accepted")
        try:
            explicit_port = parsed.port
        except ValueError as exc:
            raise InvalidUrlError("URL port is invalid") from exc
        expected_port = 443 if scheme == "https" else 80
        if explicit_port is not None and explicit_port != expected_port:
            raise InvalidUrlError("only the default port for the URL scheme is accepted")

        canonical_host = _canonicalize_host(parsed.hostname)
        literal = _parse_ip_literal(canonical_host)
        netloc = f"[{canonical_host}]" if isinstance(literal, ipaddress.IPv6Address) else canonical_host
        return SplitResult(
            scheme=scheme,
            netloc=netloc,
            path=parsed.path or "/",
            query=parsed.query,
            fragment="",
        )


async def _resolve_with_timeout(
    resolver: HostResolver,
    host: str,
    port: int,
    *,
    timeout_seconds: float | None,
) -> Sequence[str]:
    if timeout_seconds is None:
        return await resolver.resolve(host, port)
    if timeout_seconds <= 0:
        raise ValueError("resolution timeout must be positive")
    try:
        return await asyncio.wait_for(resolver.resolve(host, port), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise UnsafeAddressError(f"hostname resolution timed out for {host}") from exc


def _canonicalize_host(host: str) -> str:
    value = host.rstrip(".").lower()
    if not value:
        raise InvalidUrlError("hostname is empty")
    literal = _parse_ip_literal(value)
    if literal is not None:
        return literal.compressed
    try:
        ascii_host = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidUrlError("hostname IDNA normalization failed") from exc
    if len(ascii_host) > 253 or any(not label or len(label) > 63 for label in ascii_host.split(".")):
        raise InvalidUrlError("hostname is invalid")
    return ascii_host


def _parse_ip_literal(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _validated_public_ip(value: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    try:
        address = ipaddress.ip_address(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise UnsafeAddressError(f"resolver returned invalid address {value!r}") from exc
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address.is_multicast or not address.is_global:
        raise UnsafeAddressError(
            f"destination address {address.compressed} is not an allowed public unicast address"
        )
    return address.compressed
