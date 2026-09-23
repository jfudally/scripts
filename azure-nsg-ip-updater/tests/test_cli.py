"""Tests for the CLI entrypoint.

Azure SDK construction and the public-IP fetch are monkeypatched out, so these
tests pin down the wiring — config loading, env validation, one client per
configured rule, and exit codes — without touching the network.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nsg_ip_updater import cli

_CREDS = {
    "AZURE_TENANT_ID": "t",
    "AZURE_CLIENT_ID": "c",
    "AZURE_CLIENT_SECRET": "s",
    "AZURE_SUBSCRIPTION_ID": "sub",
}

_TWO_RG_CONFIG = """\
resource_groups:
  - name: rg-a
    nsgs:
      - name: nsg-1
        rules: [ssh, https]
  - name: rg-b
    nsgs:
      - name: nsg-2
        rules: [ssh]
"""


@pytest.fixture
def azure(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub out Azure auth/SDK and the IP fetch; return the fake network client.

    Every rule on the fake SDK reports ``1.1.1.1/32`` and the host's IP is
    ``9.9.9.9``, so every configured rule needs an update.
    """
    for key, value in _CREDS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("NSG_IP_UPDATER_CONFIG", raising=False)

    network_client = MagicMock()
    rule = MagicMock(source_address_prefix="1.1.1.1/32", source_address_prefixes=[])
    network_client.security_rules.get.return_value = rule
    monkeypatch.setattr(cli, "EnvironmentCredential", MagicMock())
    monkeypatch.setattr(cli, "NetworkManagementClient", MagicMock(return_value=network_client))
    monkeypatch.setattr(cli, "get_public_ip", lambda: "9.9.9.9")
    return network_client


def _write_config(tmp_path: Path, text: str = _TWO_RG_CONFIG) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return path


def _written_targets(network_client: MagicMock) -> list[tuple[str, str, str]]:
    """Return the (rg, nsg, rule) triples the CLI wrote to, in call order."""
    return [
        (
            call.kwargs["resource_group_name"],
            call.kwargs["network_security_group_name"],
            call.kwargs["security_rule_name"],
        )
        for call in network_client.security_rules.begin_create_or_update.call_args_list
    ]


def test_updates_rules_across_resource_groups(azure: MagicMock, tmp_path: Path) -> None:
    """Every rule in every configured resource group / NSG is reconciled."""
    config = _write_config(tmp_path)

    assert cli.main(["--config", str(config)]) == 0
    assert _written_targets(azure) == [
        ("rg-a", "nsg-1", "ssh"),
        ("rg-a", "nsg-1", "https"),
        ("rg-b", "nsg-2", "ssh"),
    ]


def test_config_path_can_come_from_env(
    azure: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NSG_IP_UPDATER_CONFIG is used when --config is not passed (cron-friendly)."""
    monkeypatch.setenv("NSG_IP_UPDATER_CONFIG", str(_write_config(tmp_path)))

    assert cli.main([]) == 0
    assert len(_written_targets(azure)) == 3


def test_missing_config_file_is_config_error(azure: MagicMock, tmp_path: Path) -> None:
    """A missing config file exits 1 before any Azure call."""
    assert cli.main(["--config", str(tmp_path / "missing.yaml")]) == 1
    azure.security_rules.get.assert_not_called()


def test_malformed_config_is_config_error(azure: MagicMock, tmp_path: Path) -> None:
    """A schema violation exits 1 before any Azure call."""
    config = _write_config(tmp_path, "resource_groups: []\n")

    assert cli.main(["--config", str(config)]) == 1
    azure.security_rules.get.assert_not_called()


def test_missing_credentials_is_config_error(
    azure: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Credentials still come from env; a missing one exits 1."""
    monkeypatch.delenv("AZURE_CLIENT_SECRET")

    assert cli.main(["--config", str(_write_config(tmp_path))]) == 1
    azure.security_rules.get.assert_not_called()


def test_one_failing_rule_exits_2_but_others_still_update(
    azure: MagicMock, tmp_path: Path
) -> None:
    """A bad rule in one resource group does not block rules in another."""
    from azure.core.exceptions import ResourceNotFoundError

    good = azure.security_rules.get.return_value

    def get(rg: str, nsg: str, rule: str):
        if rg == "rg-a" and rule == "https":
            raise ResourceNotFoundError("nope")
        return good

    azure.security_rules.get.side_effect = get

    assert cli.main(["--config", str(_write_config(tmp_path))]) == 2
    assert _written_targets(azure) == [("rg-a", "nsg-1", "ssh"), ("rg-b", "nsg-2", "ssh")]
