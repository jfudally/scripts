"""Command-line entrypoint for the cron job.

Wires together :mod:`nsg_ip_updater.config`, :mod:`nsg_ip_updater.public_ip`,
:mod:`nsg_ip_updater.nsg_client`, and :mod:`nsg_ip_updater.updater`.

*Which* rules to sync comes from a YAML config file (see
:mod:`nsg_ip_updater.config`), which may span several resource groups and
NSGs. The file is located via, in order of precedence:

  1. ``--config PATH``
  2. the ``NSG_IP_UPDATER_CONFIG`` env var
  3. ``config.yaml`` in the current working directory

*Credentials* stay in environment variables (Service Principal auth) so the
config file carries no secrets:
  * ``AZURE_TENANT_ID``
  * ``AZURE_CLIENT_ID``
  * ``AZURE_CLIENT_SECRET``
  * ``AZURE_SUBSCRIPTION_ID``    -- every configured resource group must live
                                    in this subscription

Exit codes:
  * ``0`` -- every rule is already current OR was successfully updated
  * ``1`` -- configuration error (missing env var, missing/invalid config file)
  * ``2`` -- runtime error: couldn't fetch the public IP at all, or one or
             more individual rules failed to reconcile (the rules that could
             be updated still were)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterable, Sequence

from azure.identity import EnvironmentCredential
from azure.mgmt.network import NetworkManagementClient

from nsg_ip_updater.config import ConfigError, load_config
from nsg_ip_updater.nsg_client import NSGRuleClient
from nsg_ip_updater.public_ip import get_public_ip
from nsg_ip_updater.updater import sync_nsg_rules_with_current_ip

_REQUIRED_ENV_VARS = (
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_SUBSCRIPTION_ID",
)

_CONFIG_ENV_VAR = "NSG_IP_UPDATER_CONFIG"
_DEFAULT_CONFIG_PATH = "config.yaml"


def _missing_env(required: Iterable[str]) -> list[str]:
    """Return the subset of *required* env var names that are unset or blank."""
    return [name for name in required if not os.environ.get(name)]


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse CLI flags; ``--config`` defaults to the env var, then ``config.yaml``."""
    parser = argparse.ArgumentParser(
        prog="nsg_ip_updater",
        description="Point Azure NSG rules at this host's current public IPv4.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get(_CONFIG_ENV_VAR) or _DEFAULT_CONFIG_PATH,
        help=f"YAML config path (default: ${_CONFIG_ENV_VAR} or {_DEFAULT_CONFIG_PATH})",
    )
    return parser.parse_args(argv)


def _configure_logging() -> None:
    """Stream INFO+ logs to stderr with a cron-friendly timestamped format.

    Side effect: pins the ``azure`` logger (and so every Azure SDK child
    logger) to WARNING.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    # azure-core's HttpLoggingPolicy logs every request/response, headers
    # included, at INFO. Run every 15 minutes from cron, that buried our own
    # one-line results and grew the log by tens of MB. SDK warnings and
    # errors still get through.
    logging.getLogger("azure").setLevel(logging.WARNING)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one reconciliation pass over every configured rule and return an exit code.

    Args:
        argv: Command-line arguments excluding the program name. ``None``
            means ``sys.argv[1:]``; tests pass an explicit list.

    Returns:
        Process exit code — see the module docstring.
    """
    args = _parse_args(argv)
    _configure_logging()
    log = logging.getLogger("nsg_ip_updater")

    missing = _missing_env(_REQUIRED_ENV_VARS)
    if missing:
        log.error("missing required environment variables: %s", ", ".join(missing))
        return 1

    # Load and validate config before touching Azure so a typo fails fast
    # with exit 1 instead of surfacing as a partial runtime failure.
    try:
        targets = load_config(args.config)
    except ConfigError as exc:
        log.error("invalid configuration: %s", exc)
        return 1
    log.info("loaded %d rule(s) from %s", len(targets), args.config)

    try:
        credential = EnvironmentCredential()
        # One SDK client is shared by every rule: they all live in the same
        # subscription and only resource group / NSG / rule names differ.
        network_client = NetworkManagementClient(credential, os.environ["AZURE_SUBSCRIPTION_ID"])
        nsg_clients = [
            NSGRuleClient(
                network_client=network_client,
                resource_group=target.resource_group,
                nsg_name=target.nsg_name,
                rule_name=target.rule_name,
            )
            for target in targets
        ]
        results = sync_nsg_rules_with_current_ip(nsg_clients, get_public_ip)
    except Exception:  # noqa: BLE001 -- top-level cron boundary
        log.exception("reconciliation failed")
        return 2

    for result in results:
        if result.error is not None:
            log.error("NSG rule %s failed: %s", result.target, result.error)
        elif result.changed:
            log.info(
                "updated NSG rule %s: %s -> %s",
                result.target,
                result.old_prefix,
                result.new_prefix,
            )
        else:
            log.info("NSG rule %s already current at %s", result.target, result.new_prefix)

    failed = [r.target for r in results if r.error is not None]
    if failed:
        log.error("%d of %d rule(s) failed: %s", len(failed), len(results), ", ".join(failed))
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
