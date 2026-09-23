"""Tests for the orchestrator.

The updater decides, per rule:
  - if our current public IP already matches the NSG rule → no-op,
  - otherwise → call update_source_prefix and report what changed.

Both the public-IP fetcher and the NSG clients are injected so this layer
is trivially testable. The multi-rule entry point fetches the public IP
exactly once and reconciles every rule against it.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from nsg_ip_updater.updater import (
    UpdateResult,
    reconcile_rule,
    sync_nsg_rules_with_current_ip,
)


def _client(label: str, current_prefix: str | None) -> MagicMock:
    """Build a mock NSG client that reports *current_prefix* for the rule at *label*."""
    client = MagicMock()
    client.label = label
    client.get_current_source_prefix.return_value = current_prefix
    return client


def test_reconcile_no_update_when_ip_unchanged() -> None:
    """If observed IP already matches the rule, the SDK is not called to update."""
    nsg = _client("dns", "1.2.3.4/32")

    result = reconcile_rule(nsg, "1.2.3.4")

    assert result == UpdateResult(
        target="dns",
        changed=False,
        old_prefix="1.2.3.4/32",
        new_prefix="1.2.3.4/32",
        public_ip="1.2.3.4",
    )
    nsg.update_source_prefix.assert_not_called()


def test_reconcile_updates_when_ip_changed() -> None:
    """A new IP must trigger an update with /32 appended."""
    nsg = _client("dns", "1.2.3.4/32")

    result = reconcile_rule(nsg, "9.8.7.6")

    nsg.update_source_prefix.assert_called_once_with("9.8.7.6/32")
    assert result.changed is True
    assert result.target == "dns"
    assert result.old_prefix == "1.2.3.4/32"
    assert result.new_prefix == "9.8.7.6/32"
    assert result.public_ip == "9.8.7.6"


def test_reconcile_updates_when_rule_currently_empty() -> None:
    """A missing/None current prefix counts as a change and gets populated."""
    nsg = _client("dns", None)

    result = reconcile_rule(nsg, "9.8.7.6")

    nsg.update_source_prefix.assert_called_once_with("9.8.7.6/32")
    assert result.changed is True
    assert result.old_prefix is None
    assert result.new_prefix == "9.8.7.6/32"


def test_sync_fetches_public_ip_exactly_once_for_many_rules() -> None:
    """The public IP is fetched a single time and shared across every rule."""
    clients = [
        _client("dns", "9.8.7.6/32"),
        _client("ssh", "0.0.0.0/32"),
        _client("https", None),
    ]
    fetch_ip = MagicMock(return_value="9.8.7.6")

    results = sync_nsg_rules_with_current_ip(clients, fetch_ip)

    fetch_ip.assert_called_once_with()
    assert [r.target for r in results] == ["dns", "ssh", "https"]
    # dns already current → no write; the other two change.
    assert [r.changed for r in results] == [False, True, True]
    assert all(r.error is None for r in results)
    clients[0].update_source_prefix.assert_not_called()
    clients[1].update_source_prefix.assert_called_once_with("9.8.7.6/32")
    clients[2].update_source_prefix.assert_called_once_with("9.8.7.6/32")


def test_sync_continues_when_a_rule_fails() -> None:
    """One failing rule must not stop the others; the failure is reported."""
    good_before = _client("dns", "1.1.1.1/32")
    broken = _client("ssh", None)
    broken.get_current_source_prefix.side_effect = RuntimeError("boom")
    good_after = _client("https", None)
    clients = [good_before, broken, good_after]
    fetch_ip = MagicMock(return_value="9.8.7.6")

    results = sync_nsg_rules_with_current_ip(clients, fetch_ip)

    fetch_ip.assert_called_once_with()
    assert [r.target for r in results] == ["dns", "ssh", "https"]
    # The healthy rules either side of the failure were still updated.
    good_before.update_source_prefix.assert_called_once_with("9.8.7.6/32")
    good_after.update_source_prefix.assert_called_once_with("9.8.7.6/32")

    dns, ssh, https = results
    assert dns.error is None and dns.changed is True
    assert https.error is None and https.changed is True
    # The broken rule is reported as an error, not silently skipped.
    assert ssh.changed is False
    assert ssh.error is not None
    assert "boom" in ssh.error


def test_sync_labels_results_by_full_rule_path() -> None:
    """Same rule name on different NSGs yields distinguishable results."""
    clients = [_client("rg-a/nsg/ssh", None), _client("rg-b/nsg/ssh", None)]

    results = sync_nsg_rules_with_current_ip(clients, MagicMock(return_value="9.8.7.6"))

    assert [r.target for r in results] == ["rg-a/nsg/ssh", "rg-b/nsg/ssh"]
