"""Allow ``python -m nsg_ip_updater`` to invoke the CLI."""
from __future__ import annotations

from nsg_ip_updater.cli import main

raise SystemExit(main())
