"""Orchestrator: compare the current public IP against NSG rules and reconcile.

This module is deliberately framework-free: it accepts callables and client
objects so unit tests can run without touching the network. The CLI in
:mod:`cli` is responsible for wiring the real implementations in.

A single host has exactly one public IP, so when several NSG rules must all
point at this host the IP is fetched once and applied to every rule. See
:func:`sync_nsg_rules_with_current_ip`.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of reconciling one NSG rule.

    Attributes:
        rule_name: Name of the security rule this result describes. Lets the
            caller attribute outcomes when several rules are synced at once.
        changed: True when the NSG rule was rewritten this run. Always False
            when ``error`` is set.
        old_prefix: The rule's source prefix before reconciliation
            (``None`` if the rule had neither singular nor plural source set,
            or if reconciliation failed before the prefix could be read).
        new_prefix: The rule's source prefix after reconciliation. Equal to
            ``old_prefix`` when ``changed`` is False, and ``None`` when
            reconciliation failed.
        public_ip: The bare IPv4 address observed for this host.
        error: ``None`` on success; otherwise a short description of why this
            rule could not be reconciled. The other rules in the same run are
            still attempted — see :func:`sync_nsg_rules_with_current_ip`.
    """

    rule_name: str
    changed: bool
    old_prefix: str | None
    new_prefix: str | None
    public_ip: str
    error: str | None = None


def reconcile_rule(nsg_client, public_ip: str) -> UpdateResult:
    """Reconcile one NSG rule against a known *public_ip*.

    The expected NSG source prefix is the public IP plus a ``/32`` host mask
    (NSG rules want a CIDR, even for a single host). If the rule's existing
    source prefix already matches, no write is issued — this is what makes
    the script safe to run from cron every few minutes.

    Args:
        nsg_client: An object exposing ``rule_name``,
            ``get_current_source_prefix()`` and ``update_source_prefix(str)``.
            In production this is an
            :class:`nsg_ip_updater.nsg_client.NSGRuleClient`; tests pass a mock.
        public_ip: The host's current public IPv4 as a bare string, e.g.
            ``"203.0.113.42"``.

    Returns:
        An :class:`UpdateResult` describing what (if anything) changed.
    """
    desired_prefix = f"{public_ip}/32"
    current_prefix = nsg_client.get_current_source_prefix()
    rule_name = nsg_client.rule_name

    if current_prefix == desired_prefix:
        logger.info(
            "NSG rule %s already matches public IP %s; no update needed",
            rule_name,
            public_ip,
        )
        return UpdateResult(
            rule_name=rule_name,
            changed=False,
            old_prefix=current_prefix,
            new_prefix=current_prefix,
            public_ip=public_ip,
        )

    logger.info(
        "NSG rule %s source changing: %s -> %s",
        rule_name,
        current_prefix if current_prefix is not None else "<unset>",
        desired_prefix,
    )
    nsg_client.update_source_prefix(desired_prefix)
    return UpdateResult(
        rule_name=rule_name,
        changed=True,
        old_prefix=current_prefix,
        new_prefix=desired_prefix,
        public_ip=public_ip,
    )


def sync_nsg_rules_with_current_ip(
    nsg_clients: Sequence,
    fetch_public_ip: Callable[[], str],
) -> list[UpdateResult]:
    """Reconcile every NSG rule with the host's current public IP.

    The public IP is fetched exactly once and shared across all rules — a
    host only has one public address, and fetching per-rule would multiply
    the (rate-limited) calls to the IP echo providers.

    Rules are reconciled in the order given and reconciliation is resilient:
    if one rule fails (e.g. a typo'd name that 404s), the failure is captured
    on that rule's :class:`UpdateResult` (``error`` set) and the remaining
    rules are still attempted. The caller inspects ``error`` on each result
    to decide the process exit code, so a single bad rule never blocks the
    others from being kept current.

    A failure to fetch the public IP itself still propagates, since without an
    IP there is nothing to reconcile any rule against.

    Args:
        nsg_clients: Ordered NSG rule clients, one per rule to keep current.
            Each must expose the interface documented on :func:`reconcile_rule`.
            In production these are
            :class:`nsg_ip_updater.nsg_client.NSGRuleClient` instances; tests
            pass mocks.
        fetch_public_ip: Zero-arg callable returning the host's current public
            IPv4 as a string. In production this is
            :func:`nsg_ip_updater.public_ip.get_public_ip`.

    Returns:
        One :class:`UpdateResult` per client, in the same order. Failed rules
        have ``error`` set and ``changed`` False.
    """
    public_ip = fetch_public_ip()
    results: list[UpdateResult] = []
    for client in nsg_clients:
        try:
            results.append(reconcile_rule(client, public_ip))
        except Exception as exc:  # noqa: BLE001 -- isolate one rule's failure
            logger.exception(
                "reconciliation failed for NSG rule %s; continuing with others",
                client.rule_name,
            )
            results.append(
                UpdateResult(
                    rule_name=client.rule_name,
                    changed=False,
                    old_prefix=None,
                    new_prefix=None,
                    public_ip=public_ip,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return results
