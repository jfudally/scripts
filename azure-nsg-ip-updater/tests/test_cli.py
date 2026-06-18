"""Tests for CLI helpers that don't require touching Azure.

The heavy wiring in :func:`nsg_ip_updater.cli.main` is exercised end-to-end
in integration runs (``make run-dotenv``). Here we only pin down the pure
parsing helper that turns the ``AZURE_NSG_RULE_NAMES`` env var into a clean
list of rule names.
"""
from __future__ import annotations

import pytest

from nsg_ip_updater.cli import _parse_rule_names


def test_parse_single_rule_name() -> None:
    """A lone rule name yields a one-element list."""
    assert _parse_rule_names("dns") == ["dns"]


def test_parse_comma_separated_rule_names() -> None:
    """Comma-separated names are split into individual rules."""
    assert _parse_rule_names("dns,ssh,https") == ["dns", "ssh", "https"]


def test_parse_strips_whitespace_and_drops_blanks() -> None:
    """Whitespace and empty segments (e.g. trailing commas) are tolerated."""
    assert _parse_rule_names(" dns , ssh ,, https, ") == ["dns", "ssh", "https"]


def test_parse_deduplicates_preserving_order() -> None:
    """Repeated rule names collapse to one entry, first occurrence wins order."""
    assert _parse_rule_names("dns,ssh,dns") == ["dns", "ssh"]


def test_parse_empty_string_yields_no_rules() -> None:
    """An empty/whitespace-only value yields an empty list, not [''] ."""
    assert _parse_rule_names("   ") == []


@pytest.mark.parametrize("raw", ["dns", "dns,ssh"])
def test_parse_returns_list(raw: str) -> None:
    """Result is always a list regardless of how many names were given."""
    assert isinstance(_parse_rule_names(raw), list)
