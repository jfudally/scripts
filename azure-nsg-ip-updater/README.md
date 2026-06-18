# nsg-ip-updater

Keep one or more Azure Network Security Group (NSG) security rules pointed
at this host's *current* public IPv4. Designed to run from cron on a
residential connection where the public IP rotates every few hours / days.

## How it works

1. Fetch the host's current public IPv4 from a list of well-known echo
   services (`api.ipify.org`, `ifconfig.me`, `checkip.amazonaws.com`,
   `icanhazip.com`). The first valid response wins; the rest are fallbacks.
   The IP is fetched **once per run** and applied to every configured rule.
2. For each rule named in `AZURE_NSG_RULE_NAMES`, read it from Azure.
3. If the rule's `source_address_prefix` already equals `<current-ip>/32`,
   skip it without writing.
4. Otherwise rewrite the rule, preserving every other field (priority,
   ports, direction, etc.), and wait for Azure to confirm.

All listed rules must live on the single NSG named by `AZURE_NSG_NAME`
(syncing rules across multiple NSGs is on the roadmap, not yet supported).

Reconciliation is resilient: if one rule fails (e.g. a typo'd name that
404s), the remaining rules are still updated and the failure is logged. The
run then exits non-zero so the problem is visible without blocking the
healthy rules.

Cron-safe: no Azure writes happen on the (very common) case where the IP
has not changed, and any failure exits non-zero so the run is visible in
mail / `MAILTO=`.

## Architecture

```
cli.py            -- env vars in, one NSGRuleClient per rule, exit code out
 └── updater.py   -- fetch IP once, compare-and-reconcile each rule (pure, no I/O)
      ├── public_ip.py     -- HTTP fetch + IPv4 validation
      └── nsg_client.py    -- thin wrapper over azure-mgmt-network (per rule)
```

## Setup

### 1. Create a Service Principal scoped to the NSG

```bash
NSG_ID=$(az network nsg show -g my-rg -n my-nsg --query id -o tsv)
az ad sp create-for-rbac \
  --name nsg-ip-updater \
  --role "Network Contributor" \
  --scopes "$NSG_ID"
```

That command prints `appId`, `password`, and `tenant`. Those are
`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_TENANT_ID`
respectively.

> Why a custom scope? Granting Network Contributor at the subscription
> level would let this credential change anything on the network. Scoping
> to the single NSG limits the blast radius if `.env` ever leaks.

### 2. Configure environment

```bash
cp .env.example .env
# fill in the values from step 1 + the NSG/rule names
chmod 600 .env
```

### 3. Install dependencies

```bash
make install
```

This installs into the shared `../.venv` (a `uv`-managed venv at the
parent `scripts/` repo root).

### 4. Verify locally

```bash
make test          # unit tests, no network
make run-dotenv    # actually hits Azure — sources ./.env first
```

Expected log on first run (two rules configured):

```
INFO ... public-ip provider https://api.ipify.org returned 203.0.113.42
INFO ... NSG rule allow-home-ssh source changing: 198.51.100.5/32 -> 203.0.113.42/32
INFO ... updated NSG rule allow-home-ssh: 198.51.100.5/32 -> 203.0.113.42/32
INFO ... NSG rule allow-home-https source changing: 198.51.100.5/32 -> 203.0.113.42/32
INFO ... updated NSG rule allow-home-https: 198.51.100.5/32 -> 203.0.113.42/32
```

Re-running immediately should log "already current" for every rule and exit
0 without an Azure write.

## Cron

Edit `crontab -e` and add (adjust paths):

```cron
MAILTO=you@example.com

# Sync NSG rule with current public IP every 10 minutes.
*/10 * * * * cd /Users/justinfudally/PycharmProjects/scripts/azure-nsg-ip-updater && /usr/bin/make run-dotenv >> /var/log/nsg-ip-updater.log 2>&1
```

`make run-dotenv` reads `./.env`, then invokes
`python -m nsg_ip_updater`. The script exits 0 when every rule is a no-op or
was updated, 1 on config error, and 2 when it can't fetch the public IP or
when one or more individual rules fail (the healthy rules are still updated
first) — so cron's `MAILTO=` will surface any failures.

> On macOS, the modern equivalent is `launchd`. A `.plist` template will
> appear in Phase 2; for now `cron` works and is portable.

## Make targets

```
make help          Show all targets
make install       Install runtime + dev deps into the shared venv
make test          Run pytest
make lint          Byte-compile sources as a cheap syntax check
make run           Run one pass using the current shell env
make run-dotenv    Run one pass after sourcing ./.env (cron mode)
make clean         Remove caches
```

## Project status

See [ROADMAP.md](ROADMAP.md). Currently in **Phase 1 (MVP)**.
