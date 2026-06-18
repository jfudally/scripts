"""Tests for the public IP fetcher.

The fetcher hits a list of well-known IP-echo services in order and
returns the first valid IPv4 it sees. It must:
  - tolerate the first service being down (timeout or HTTP error),
  - reject obviously bogus responses (non-IP text),
  - raise PublicIPError when every service fails.
"""
from __future__ import annotations

import pytest
import responses

from nsg_ip_updater.public_ip import (
    DEFAULT_PROVIDERS,
    PublicIPError,
    get_public_ip,
)


@responses.activate
def test_returns_ip_from_first_provider() -> None:
    """First provider returns a clean IPv4 — that is the answer."""
    responses.add(responses.GET, DEFAULT_PROVIDERS[0], body="203.0.113.42", status=200)
    assert get_public_ip(providers=DEFAULT_PROVIDERS) == "203.0.113.42"


@responses.activate
def test_falls_back_when_first_provider_errors() -> None:
    """If the first provider 500s, the second one is tried."""
    responses.add(responses.GET, DEFAULT_PROVIDERS[0], status=500)
    responses.add(responses.GET, DEFAULT_PROVIDERS[1], body="198.51.100.7\n", status=200)
    assert get_public_ip(providers=DEFAULT_PROVIDERS) == "198.51.100.7"


@responses.activate
def test_rejects_non_ip_response_and_falls_back() -> None:
    """An HTML/garbage response from a provider counts as a failure."""
    responses.add(responses.GET, DEFAULT_PROVIDERS[0], body="<html>nope</html>", status=200)
    responses.add(responses.GET, DEFAULT_PROVIDERS[1], body="192.0.2.5", status=200)
    assert get_public_ip(providers=DEFAULT_PROVIDERS) == "192.0.2.5"


@responses.activate
def test_raises_when_all_providers_fail() -> None:
    """Every provider broken → caller gets a typed error, not None."""
    for url in DEFAULT_PROVIDERS:
        responses.add(responses.GET, url, status=503)
    with pytest.raises(PublicIPError):
        get_public_ip(providers=DEFAULT_PROVIDERS)
