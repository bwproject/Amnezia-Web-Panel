# ProjectBW integration patches

This directory contains only the focused diffs against the current `main` branch. It must not contain full copies of upstream files.

| Patch | Purpose |
|---|---|
| `app.py.patch` | Register BW managers, HTTP proxy protocol/API, Telegram Exit Node settings and transport |
| `app_telegram_lifecycle.patch` | Pass Telegram Exit transport through upstream v1.8.15 settings-save and explicit toggle paths |
| `exit_link_service.py.patch` | Integrate standard WireGuard with Exit Node management |
| `protocol_names.py.patch` | Protocol display-name adjustment |
| `smartroute_service.py.patch` | Route standard WireGuard Smart Route operations through the BW manager |
| `telegram_bot.py.patch` | Inject the Telegram HTTP client factory |
| `templates__my_connections.html.patch` | Hide config actions when an external AWG peer has no stored private key |
| `templates__users.html.patch` | Show unavailable AWG configs when a peer's private key is not stored on the server |
| `templates__server.html.patch` | HTTP proxy controls and WireGuard Exit Node UI |
| `templates__settings.html.patch` | Telegram Exit Node selector |

The additive BW-only modules live beside the patch directory and under `managers/`. Telegram Exit Node SSH sessions use the panel's `_ssh_manager_for` factory so encrypted credentials, jump hosts and lifecycle fences remain active. The HTTP client factory is threaded through upstream v1.8.15's `_supervise_bot` retry loop, preserving startup retries and graceful stop. Settings saves retain upstream's explicit `telegram.enabled` lifecycle state and only add `exit_uid`. Telemt itself is taken directly from the official upstream release without BW-specific modifications. The workflow in `.github/workflows/sync-bw.yml` checks out `main`, copies those modules, applies every patch with `git apply --check`, validates Python syntax, then updates `BW` and builds the Docker image.

When upstream changes, update patches against the new official stable release and run the workflow from `imp`. Never copy a complete upstream file into this directory.
