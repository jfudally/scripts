"""Command-line entrypoint for the cron job.

Wires together :mod:`nsg_ip_updater.public_ip`,
:mod:`nsg_ip_updater.nsg_client`, and :mod:`nsg_ip_updater.updater` using
real Azure credentials sourced from environment variables.

Required env vars (Service Principal auth):
  * ``AZURE_TENANT_ID``
  * ``AZURE_CLIENT_ID``
  * ``AZURE_CLIENT_SECRET``
  * ``AZURE_SUBSCRIPTION_ID``
  * ``AZURE_RESOURCE_GROUP``     -- resource group containing the NSG
  * ``AZURE_NSG_NAME``           -- name of the network security group
  * ``AZURE_NSG_RULE_NAMES``     -- comma-separated security rule name(s) on
                                    that NSG to keep pointed at this host

Exit codes:
  * ``0`` -- every rule is already current OR was successfully updated
  * ``1`` -- configuration error (missing env var / no rule names)
  * ``2`` -- runtime error: couldn't fetch the public IP at all, or one or
             more individual rules failed to reconcile (the rules that could
             be updated still were)
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable

from azure.identity import EnvironmentCredential
from azure.mgmt.network import NetworkManagementClient

from nsg_ip_updater.nsg_client import NSGRuleClient
from nsg_ip_updater.public_ip import get_public_ip
from nsg_ip_updater.updater import sync_nsg_rules_with_current_ip

_REQUIRED_ENV_VARS = (
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "AZURE_NSG_NAME",
    "AZURE_NSG_RULE_NAMES",
)


def _missing_env(required: Iterable[str]) -> list[str]:
    """Return the subset of *required* env var names that are unset or blank."""
    return [name for name in required if not os.environ.get(name)]


def _parse_rule_names(raw: str) -> list[str]:
    """Parse the comma-separated ``AZURE_NSG_RULE_NAMES`` value into a list.

    Whitespace around each name is stripped, blank segments (e.g. a trailing
    comma) are dropped, and duplicates are collapsed while preserving the
    first occurrence's order. A value with no usable names yields ``[]``.

    Args:
        raw: Raw env var value, e.g. ``"dns, ssh, https"``.

    Returns:
        Ordered, de-duplicated list of non-empty rule names.
    """
    seen: dict[str, None] = {}
    for segment in raw.split(","):
        name = segment.strip()
        if name:
            seen.setdefault(name, None)
    return list(seen)


def _configure_logging() -> None:
    """Stream INFO+ logs to stderr with a cron-friendly timestamped format."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


def main() -> int:
    """Run one reconciliation pass over every configured rule and return an exit code."""
    _configure_logging()
    log = logging.getLogger("nsg_ip_updater")

    missing = _missing_env(_REQUIRED_ENV_VARS)
    if missing:
        log.error("missing required environment variables: %s", ", ".join(missing))
        return 1

    subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
    resource_group = os.environ["AZURE_RESOURCE_GROUP"]
    nsg_name = os.environ["AZURE_NSG_NAME"]
    rule_names = _parse_rule_names(os.environ["AZURE_NSG_RULE_NAMES"])

    if not rule_names:
        log.error("AZURE_NSG_RULE_NAMES did not contain any rule names")
        return 1

    try:
        credential = EnvironmentCredential()
        network_client = NetworkManagementClient(credential, subscription_id)
        nsg_clients = [
            NSGRuleClient(
                network_client=network_client,
                resource_group=resource_group,
                nsg_name=nsg_name,
                rule_name=rule_name,
            )
            for rule_name in rule_names
        ]
        results = sync_nsg_rules_with_current_ip(nsg_clients, get_public_ip)
    except Exception:  # noqa: BLE001 -- top-level cron boundary
        log.exception("reconciliation failed")
        return 2

    for result in results:
        if result.error is not None:
            log.error("NSG rule %s failed: %s", result.rule_name, result.error)
        elif result.changed:
            log.info(
                "updated NSG rule %s: %s -> %s",
                result.rule_name,
                result.old_prefix,
                result.new_prefix,
            )
        else:
            log.info(
                "NSG rule %s already current at %s",
                result.rule_name,
                result.new_prefix,
            )

    failed = [r.rule_name for r in results if r.error is not None]
    if failed:
        log.error("%d of %d rule(s) failed: %s", len(failed), len(results), ", ".join(failed))
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
