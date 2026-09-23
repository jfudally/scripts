"""nsg_ip_updater — keep Azure NSG security rules pointed at this host's public IP.

The package is intentionally small and split into layers:

* :mod:`config` — loads the YAML file listing which rules to sync, grouped by
  resource group and NSG, and flattens it into (rg, nsg, rule) targets.
* :mod:`public_ip` — fetches the host's current public IPv4 from a list of
  external echo services, tolerating individual outages.
* :mod:`nsg_client` — a thin wrapper over ``azure-mgmt-network`` so the rest
  of the app deals in plain strings instead of SDK objects.
* :mod:`updater` — the orchestrator that compares the observed IP with the
  rule and only writes when they differ. This is where the cron-safety lives.

A CLI entrypoint lives in :mod:`cli` and is exposed as ``python -m nsg_ip_updater``.
"""

__version__ = "0.1.0"
