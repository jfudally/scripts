"""Load and validate the YAML file that declares which NSG rules to sync.

The file groups rules by resource group and NSG, so a single run can keep
rules current across several NSGs in several resource groups::

    resource_groups:
      - name: my-rg
        nsgs:
          - name: my-nsg
            rules:
              - allow-home-ssh
              - allow-home-https
      - name: other-rg
        nsgs:
          - name: other-nsg
            rules: [allow-home-rdp]

The nested shape is flattened into an ordered, de-duplicated list of
:class:`RuleTarget` triples. Credentials are deliberately *not* part of this
file — they stay in environment variables (``.env``) so the config can be
committed or shared without leaking secrets.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """The config file is missing, unparseable, or has the wrong shape."""


@dataclass(frozen=True)
class RuleTarget:
    """One security rule to keep pointed at this host's public IP.

    Attributes:
        resource_group: Azure resource group that owns the NSG.
        nsg_name: Name of the network security group.
        rule_name: Name of the security rule on that NSG.
    """

    resource_group: str
    nsg_name: str
    rule_name: str

    @property
    def label(self) -> str:
        """Path-like ``rg/nsg/rule`` identifier, unique across the whole config."""
        return f"{self.resource_group}/{self.nsg_name}/{self.rule_name}"


def load_config(path: str | Path) -> list[RuleTarget]:
    """Read the YAML config at *path* and return the rules it declares.

    Args:
        path: Filesystem path to the YAML config file.

    Returns:
        Ordered, de-duplicated list of :class:`RuleTarget`.

    Raises:
        ConfigError: The file does not exist, is not valid YAML, or does not
            match the expected schema (see :func:`parse_config`).
    """
    path = Path(path)
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    return parse_config(raw)


def parse_config(raw: Any) -> list[RuleTarget]:
    """Validate an already-parsed config document and flatten it into targets.

    Validation is strict: any missing/blank name, empty list, or wrong type
    raises rather than being skipped, because a silently ignored typo would
    leave a rule pointing at a stale IP with no signal.

    Duplicate ``(resource_group, nsg, rule)`` triples collapse to one entry
    (first occurrence keeps its position) so a rule is never written twice in
    one run.

    Args:
        raw: The object produced by ``yaml.safe_load`` on the config file.

    Returns:
        Ordered, de-duplicated list of :class:`RuleTarget`.

    Raises:
        ConfigError: The document does not match the schema. The message
            names the offending path, e.g. ``resource_groups[1].nsgs[0].rules``.
    """
    if not isinstance(raw, dict):
        raise ConfigError("config top level must be a mapping with a 'resource_groups' key")

    groups = _require_non_empty_list(raw.get("resource_groups"), "resource_groups")

    # dict preserves insertion order, giving us an ordered set for de-duplication.
    targets: dict[RuleTarget, None] = {}
    for g_idx, group in enumerate(groups):
        g_path = f"resource_groups[{g_idx}]"
        group = _require_mapping(group, g_path)
        rg_name = _require_name(group.get("name"), f"{g_path}.name")
        nsgs = _require_non_empty_list(group.get("nsgs"), f"{g_path}.nsgs")

        for n_idx, nsg in enumerate(nsgs):
            n_path = f"{g_path}.nsgs[{n_idx}]"
            nsg = _require_mapping(nsg, n_path)
            nsg_name = _require_name(nsg.get("name"), f"{n_path}.name")
            rules = _require_non_empty_list(nsg.get("rules"), f"{n_path}.rules")

            for r_idx, rule in enumerate(rules):
                rule_name = _require_name(rule, f"{n_path}.rules[{r_idx}]")
                targets.setdefault(RuleTarget(rg_name, nsg_name, rule_name), None)

    return list(targets)


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    """Return *value* if it is a mapping, else raise naming *path*."""
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a mapping")
    return value


def _require_non_empty_list(value: Any, path: str) -> list[Any]:
    """Return *value* if it is a non-empty list, else raise naming *path*."""
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{path} must be a non-empty list")
    return value


def _require_name(value: Any, path: str) -> str:
    """Return *value* stripped if it is a non-blank string, else raise naming *path*."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} must be a non-empty string")
    return value.strip()
