"""Tests for the NSG client wrapper around azure-mgmt-network.

The wrapper hides the SDK-specific call shapes so the rest of the app
deals with plain strings. We mock NetworkManagementClient because we do
not want these tests reaching Azure.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nsg_ip_updater.nsg_client import NSGRuleClient, NSGRuleNotFoundError


def _fake_rule(prefix: str | None = "1.2.3.4/32", prefixes: list[str] | None = None):
    """Build a SimpleNamespace that quacks like a SecurityRule from the SDK."""
    return SimpleNamespace(
        name="allow-home",
        source_address_prefix=prefix,
        source_address_prefixes=prefixes or [],
        priority=100,
        direction="Inbound",
        access="Allow",
        protocol="Tcp",
        source_port_range="*",
        destination_port_range="22",
        destination_address_prefix="*",
        destination_address_prefixes=[],
    )


def test_rule_name_is_exposed() -> None:
    """The configured rule name is readable so callers can label results/logs."""
    client = NSGRuleClient(
        network_client=MagicMock(),
        resource_group="rg",
        nsg_name="nsg",
        rule_name="allow-home",
    )
    assert client.rule_name == "allow-home"


def test_get_current_source_prefix_returns_single_prefix() -> None:
    """If the rule uses source_address_prefix, that string is returned verbatim."""
    sdk = MagicMock()
    sdk.security_rules.get.return_value = _fake_rule(prefix="1.2.3.4/32")
    client = NSGRuleClient(
        network_client=sdk,
        resource_group="rg",
        nsg_name="nsg",
        rule_name="allow-home",
    )
    assert client.get_current_source_prefix() == "1.2.3.4/32"


def test_get_current_source_prefix_uses_first_of_prefixes_list() -> None:
    """Rules can use source_address_prefixes (plural). We surface the first entry."""
    sdk = MagicMock()
    sdk.security_rules.get.return_value = _fake_rule(prefix=None, prefixes=["5.6.7.8/32"])
    client = NSGRuleClient(
        network_client=sdk,
        resource_group="rg",
        nsg_name="nsg",
        rule_name="allow-home",
    )
    assert client.get_current_source_prefix() == "5.6.7.8/32"


def test_get_raises_typed_error_when_rule_missing() -> None:
    """Azure 404 is translated into a domain-specific exception."""
    from azure.core.exceptions import ResourceNotFoundError

    sdk = MagicMock()
    sdk.security_rules.get.side_effect = ResourceNotFoundError("nope")
    client = NSGRuleClient(
        network_client=sdk,
        resource_group="rg",
        nsg_name="nsg",
        rule_name="missing",
    )
    with pytest.raises(NSGRuleNotFoundError):
        client.get_current_source_prefix()


def test_update_source_prefix_calls_begin_create_or_update_with_new_value() -> None:
    """Updating must preserve the existing rule's other fields and only swap the prefix."""
    sdk = MagicMock()
    existing = _fake_rule(prefix="1.1.1.1/32")
    sdk.security_rules.get.return_value = existing
    poller = MagicMock()
    poller.result.return_value = _fake_rule(prefix="9.9.9.9/32")
    sdk.security_rules.begin_create_or_update.return_value = poller

    client = NSGRuleClient(
        network_client=sdk,
        resource_group="rg",
        nsg_name="nsg",
        rule_name="allow-home",
    )
    client.update_source_prefix("9.9.9.9/32")

    sdk.security_rules.begin_create_or_update.assert_called_once()
    kwargs = sdk.security_rules.begin_create_or_update.call_args.kwargs
    assert kwargs["resource_group_name"] == "rg"
    assert kwargs["network_security_group_name"] == "nsg"
    assert kwargs["security_rule_name"] == "allow-home"
    sent = kwargs["security_rule_parameters"]
    assert sent["source_address_prefix"] == "9.9.9.9/32"
    # Other fields are preserved from the existing rule.
    assert sent["priority"] == existing.priority
    assert sent["destination_port_range"] == existing.destination_port_range
    # Plural list is cleared so the singular field is authoritative.
    assert sent.get("source_address_prefixes", []) == []
    poller.result.assert_called_once()
