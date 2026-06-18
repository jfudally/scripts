"""Fetch the host's current public IPv4 from external echo services.

A dynamic-IP residential connection means we cannot trust any single
provider — they go down, rate-limit, or briefly return HTML error pages.
:func:`get_public_ip` walks a list of providers and returns the first
syntactically valid IPv4 it sees. If every provider fails it raises
:class:`PublicIPError` rather than silently returning ``None``, so the
caller (cron) can surface the failure instead of erasing an NSG rule.
"""
from __future__ import annotations

import ipaddress
import logging
from collections.abc import Sequence

import requests

logger = logging.getLogger(__name__)

#: Ordered list of plain-text IP echo services. Each must respond with a bare
#: IPv4 address (optionally with surrounding whitespace) and HTTP 200.
DEFAULT_PROVIDERS: tuple[str, ...] = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://checkip.amazonaws.com",
    "https://ipv4.icanhazip.com",
)


class PublicIPError(RuntimeError):
    """Raised when no provider returned a usable IPv4 address."""


def _looks_like_ipv4(candidate: str) -> bool:
    """Return True if *candidate* parses as a real IPv4 address."""
    try:
        ipaddress.IPv4Address(candidate)
    except (ipaddress.AddressValueError, ValueError):
        return False
    return True


def get_public_ip(
    providers: Sequence[str] = DEFAULT_PROVIDERS,
    timeout: float = 10.0,
) -> str:
    """Return the host's current public IPv4 as a string.

    Args:
        providers: Ordered list of HTTP endpoints that return a bare IPv4
            address as plain text. The first one to return a valid address
            wins. Defaults to :data:`DEFAULT_PROVIDERS`.
        timeout: Per-request timeout in seconds.

    Returns:
        A dotted-quad IPv4 string, e.g. ``"203.0.113.42"``.

    Raises:
        PublicIPError: Every provider was unreachable, returned a non-2xx
            response, or returned data that was not a valid IPv4 address.
    """
    last_error: str | None = None
    for url in providers:
        try:
            response = requests.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_error = f"{url}: network error: {exc}"
            logger.warning("public-ip provider %s failed: %s", url, exc)
            continue
        if response.status_code != 200:
            last_error = f"{url}: HTTP {response.status_code}"
            logger.warning("public-ip provider %s returned HTTP %s", url, response.status_code)
            continue
        candidate = response.text.strip()
        if not _looks_like_ipv4(candidate):
            last_error = f"{url}: non-IP response {candidate!r}"
            logger.warning("public-ip provider %s returned non-IP: %r", url, candidate)
            continue
        logger.info("public-ip provider %s returned %s", url, candidate)
        return candidate

    raise PublicIPError(
        f"all public-IP providers failed (last error: {last_error or 'no providers tried'})"
    )
