# Roadmap

## Phase 0 — Spike (done before this repo existed)
Validate that an Azure Service Principal with Network Contributor can rewrite a
single security rule's `source_address_prefix` without disrupting other rules.
Throwaway `az network nsg rule update` invocation against a test NSG.

## Phase 1 — MVP (current)
**Goal:** end-to-end, cron-driven sync of one NSG rule against this host's
public IP.

- [x] Public-IP fetcher with provider fallback.
- [x] NSG rule wrapper (read + update, with field preservation).
- [x] Updater that no-ops when the rule is already correct.
- [x] CLI entrypoint authenticated via Service Principal env vars.
- [x] Sync multiple rules on one NSG in a single run (`AZURE_NSG_RULE_NAMES`,
      comma-separated; IP fetched once and applied to each).
- [x] Makefile + README + cron snippet.
- [x] Unit tests with mocked SDK / mocked HTTP.

Out of scope for Phase 1: IPv6, multiple NSGs, retries, notifications.

## Phase 2 — Hardening
- Retry/backoff on transient `azure.core.exceptions.HttpResponseError`s.
- Optional `--dry-run` flag.
- Optional state file (`/var/lib/nsg-ip-updater/last-ip`) to skip the Azure
  read entirely when the IP has not changed since the previous run — saves
  API calls on hosts running cron every minute.
- Push a heartbeat to a Healthchecks.io URL on success/failure so a missed
  run alerts loudly.
- Structured (JSON) logging mode for ingestion.

## Phase 3 — Scale / Polish
- IPv6 support (`source_address_prefixes` carrying both v4 and v6 entries).
- Sync rules across multiple NSGs / resource groups (config file driven);
  single-NSG multi-rule already shipped in Phase 1.
- Managed Identity auth path for when this runs on an Azure VM.
- Container image + GitHub Actions release workflow.
- Optional Storage Account / Key Vault / SQL Server firewall back-ends (the
  updater is already abstracted enough that the SDK wrapper is the only
  thing that has to change).
