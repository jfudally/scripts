"""Thin wrapper around ``azure-mgmt-network`` for a single NSG security rule.

The Azure SDK exposes security rules as full ``SecurityRule`` objects with
two parallel fields — ``source_address_prefix`` (singular) and
``source_address_prefixes`` (plural). Callers do not want to care which
shape the rule was created in; this module normalises that.

Only the operations this project needs are wrapped:

* read the current source prefix,
* swap it for a new value while preserving every other field on the rule.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from azure.core.exceptions import ResourceNotFoundError

logger = logging.getLogger(__name__)


class NSGRuleError(RuntimeError):
    """Base class for NSG client errors raised by this module."""


class NSGRuleNotFoundError(NSGRuleError):
    """The configured rule does not exist on the NSG."""


class _SecurityRulesOperations(Protocol):
    """Subset of the SDK ``security_rules`` operations object we rely on."""

    def get(
        self,
        resource_group_name: str,
        network_security_group_name: str,
        security_rule_name: str,
    ) -> Any: ...

    def begin_create_or_update(
        self,
        *,
        resource_group_name: str,
        network_security_group_name: str,
        security_rule_name: str,
        security_rule_parameters: dict[str, Any],
    ) -> Any: ...


class _NetworkClient(Protocol):
    """Subset of ``NetworkManagementClient`` we rely on."""

    security_rules: _SecurityRulesOperations


class NSGRuleClient:
    """Read and update a single security rule on an Azure NSG.

    The wrapper is constructed with an already-authenticated
    :class:`azure.mgmt.network.NetworkManagementClient` so unit tests can
    pass in a mock and the production CLI can wire up
    :class:`azure.identity.EnvironmentCredential`.
    """

    def __init__(
        self,
        *,
        network_client: _NetworkClient,
        resource_group: str,
        nsg_name: str,
        rule_name: str,
    ) -> None:
        """Bind the wrapper to a specific resource group / NSG / rule triple.

        Args:
            network_client: Authenticated ``NetworkManagementClient`` (or a
                test double exposing the same ``.security_rules`` operations).
            resource_group: Azure resource group that owns the NSG.
            nsg_name: Name of the network security group.
            rule_name: Name of the security rule whose source prefix we will
                read and overwrite.
        """
        self._client = network_client
        self._resource_group = resource_group
        self._nsg_name = nsg_name
        self._rule_name = rule_name

    @property
    def rule_name(self) -> str:
        """Name of the security rule this client reads and overwrites.

        Exposed so orchestration/logging can label results when several
        clients (one per rule) are reconciled in a single run.
        """
        return self._rule_name

    def _get_rule(self) -> Any:
        try:
            return self._client.security_rules.get(
                self._resource_group, self._nsg_name, self._rule_name
            )
        except ResourceNotFoundError as exc:
            raise NSGRuleNotFoundError(
                f"security rule {self._rule_name!r} not found on NSG {self._nsg_name!r}"
                f" in resource group {self._resource_group!r}"
            ) from exc

    def get_current_source_prefix(self) -> str | None:
        """Return the rule's current source IP prefix as a string, or ``None``.

        Azure stores the source either in ``source_address_prefix`` (singular)
        or in ``source_address_prefixes`` (plural). We prefer the singular
        field when set; otherwise we surface the first entry of the plural
        list. When neither is populated we return ``None``, which the
        updater treats as "needs to be populated".

        Raises:
            NSGRuleNotFoundError: The configured rule does not exist.
        """
        rule = self._get_rule()
        if getattr(rule, "source_address_prefix", None):
            return rule.source_address_prefix
        prefixes = getattr(rule, "source_address_prefixes", None) or []
        return prefixes[0] if prefixes else None

    def update_source_prefix(self, new_prefix: str) -> None:
        """Overwrite the rule's source prefix with *new_prefix*.

        Every other field on the rule (priority, ports, direction, etc.) is
        round-tripped unchanged. We explicitly clear ``source_address_prefixes``
        (plural) so the singular field is unambiguously authoritative after
        the write; otherwise Azure rejects the request as a conflict.

        Args:
            new_prefix: New source IP prefix in CIDR form, e.g.
                ``"203.0.113.42/32"``.
        """
        existing = self._get_rule()
        payload = _rule_to_payload(existing)
        payload["source_address_prefix"] = new_prefix
        payload["source_address_prefixes"] = []

        logger.info(
            "updating NSG rule %s/%s/%s source to %s",
            self._resource_group,
            self._nsg_name,
            self._rule_name,
            new_prefix,
        )
        poller = self._client.security_rules.begin_create_or_update(
            resource_group_name=self._resource_group,
            network_security_group_name=self._nsg_name,
            security_rule_name=self._rule_name,
            security_rule_parameters=payload,
        )
        # Block until Azure applies the change so the cron exit code reflects reality.
        poller.result()


# Fields we copy verbatim from the existing SecurityRule when we write back.
# Listed explicitly (not via ``vars()``) so SDK-private attributes don't leak
# into the request body.
_PRESERVED_FIELDS = (
    "protocol",
    "source_port_range",
    "source_port_ranges",
    "destination_port_range",
    "destination_port_ranges",
    "destination_address_prefix",
    "destination_address_prefixes",
    "access",
    "priority",
    "direction",
    "description",
)


def _rule_to_payload(rule: Any) -> dict[str, Any]:
    """Convert an SDK ``SecurityRule`` (or duck-typed equivalent) into a dict.

    The SDK's ``begin_create_or_update`` accepts either a model instance or a
    plain dict; dicts are simpler to construct from arbitrary inputs and play
    nicely with the test doubles.
    """
    payload: dict[str, Any] = {}
    for field in _PRESERVED_FIELDS:
        value = getattr(rule, field, None)
        if value is None:
            continue
        if isinstance(value, list) and not value:
            continue
        payload[field] = value
    return payload
