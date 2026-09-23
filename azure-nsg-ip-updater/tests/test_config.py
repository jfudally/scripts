"""Tests for the YAML configuration loader.

The config file declares which rules to keep current, grouped by resource
group and NSG. The loader validates the shape and flattens it into an
ordered list of :class:`RuleTarget` triples the CLI turns into clients.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nsg_ip_updater.config import ConfigError, RuleTarget, load_config, parse_config


def test_parse_flattens_multiple_resource_groups_and_nsgs() -> None:
    """Every rule under every NSG under every resource group becomes a target, in order."""
    raw = {
        "resource_groups": [
            {
                "name": "rg-a",
                "nsgs": [
                    {"name": "nsg-1", "rules": ["ssh", "https"]},
                    {"name": "nsg-2", "rules": ["rdp"]},
                ],
            },
            {"name": "rg-b", "nsgs": [{"name": "nsg-3", "rules": ["ssh"]}]},
        ]
    }

    assert parse_config(raw) == [
        RuleTarget("rg-a", "nsg-1", "ssh"),
        RuleTarget("rg-a", "nsg-1", "https"),
        RuleTarget("rg-a", "nsg-2", "rdp"),
        RuleTarget("rg-b", "nsg-3", "ssh"),
    ]


def test_parse_deduplicates_identical_targets_preserving_order() -> None:
    """The same rg/nsg/rule listed twice is reconciled once; first occurrence wins order."""
    raw = {
        "resource_groups": [
            {"name": "rg", "nsgs": [{"name": "nsg", "rules": ["ssh", "https", "ssh"]}]},
            {"name": "rg", "nsgs": [{"name": "nsg", "rules": ["https"]}]},
        ]
    }

    assert parse_config(raw) == [
        RuleTarget("rg", "nsg", "ssh"),
        RuleTarget("rg", "nsg", "https"),
    ]


def test_parse_same_rule_name_on_different_nsgs_is_kept() -> None:
    """Rule names only need to be unique per NSG, so both entries survive."""
    raw = {
        "resource_groups": [
            {"name": "rg-a", "nsgs": [{"name": "nsg", "rules": ["ssh"]}]},
            {"name": "rg-b", "nsgs": [{"name": "nsg", "rules": ["ssh"]}]},
        ]
    }

    assert len(parse_config(raw)) == 2


def test_rule_target_label_is_path_like() -> None:
    """The label uniquely identifies a rule across resource groups in logs."""
    assert RuleTarget("rg", "nsg", "ssh").label == "rg/nsg/ssh"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (None, "top level"),
        ([], "top level"),
        ({}, "resource_groups"),
        ({"resource_groups": []}, "resource_groups"),
        ({"resource_groups": [{"nsgs": []}]}, "resource_groups[0].name"),
        ({"resource_groups": [{"name": "rg"}]}, "resource_groups[0].nsgs"),
        ({"resource_groups": [{"name": "rg", "nsgs": [{"rules": ["x"]}]}]}, "nsgs[0].name"),
        ({"resource_groups": [{"name": "rg", "nsgs": [{"name": "n"}]}]}, "nsgs[0].rules"),
        (
            {"resource_groups": [{"name": "rg", "nsgs": [{"name": "n", "rules": []}]}]},
            "nsgs[0].rules",
        ),
        (
            {"resource_groups": [{"name": "rg", "nsgs": [{"name": "n", "rules": ["ok", " "]}]}]},
            "rules[1]",
        ),
        (
            {"resource_groups": [{"name": "rg", "nsgs": [{"name": "n", "rules": "ssh"}]}]},
            "nsgs[0].rules",
        ),
    ],
)
def test_parse_rejects_malformed_config(raw: object, message: str) -> None:
    """Malformed configs fail loudly with the offending path in the message."""
    with pytest.raises(ConfigError, match=message.replace("[", r"\[").replace("]", r"\]")):
        parse_config(raw)


def test_load_config_reads_yaml_file(tmp_path: Path) -> None:
    """A YAML file on disk is parsed into targets."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "resource_groups:\n"
        "  - name: rg\n"
        "    nsgs:\n"
        "      - name: nsg\n"
        "        rules: [ssh, https]\n"
    )

    assert load_config(path) == [
        RuleTarget("rg", "nsg", "ssh"),
        RuleTarget("rg", "nsg", "https"),
    ]


def test_load_config_missing_file_raises_config_error(tmp_path: Path) -> None:
    """A missing file is a configuration error, not a raw FileNotFoundError."""
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_load_config_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    """Unparseable YAML is reported as a configuration error."""
    path = tmp_path / "config.yaml"
    path.write_text("resource_groups: [unclosed\n")

    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


def test_committed_example_config_is_valid() -> None:
    """config.example.yaml must stay loadable so users can copy it as-is."""
    example = Path(__file__).resolve().parents[1] / "config.example.yaml"

    targets = load_config(example)

    assert {t.resource_group for t in targets} == {"my-rg", "my-other-rg"}
