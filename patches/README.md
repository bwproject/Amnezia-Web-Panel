# ProjectBW integration patches

This directory contains only the focused diffs against the current `main` branch. It must not contain full copies of upstream files.

| Patch | Purpose |
|---|---|
| `app.py.patch` | Register BW managers, HTTP proxy protocol/API, Telegram Exit Node settings and transport |
| `exit_link_service.py.patch` | Integrate standard WireGuard with Exit Node management |
| `protocol_names.py.patch` | Protocol display-name adjustment |
| `smartroute_service.py.patch` | Route standard WireGuard Smart Route operations through the BW manager |
| `telegram_bot.py.patch` | Inject the Telegram HTTP client factory |
| `templates__server.html.patch` | HTTP proxy controls, dedicated Telemt Exit Node marketplace entry, and Telemt/WireGuard Exit Node UI |
| `templates__settings.html.patch` | Telegram Exit Node selector |

The additive BW-only modules live beside the patch directory and under `managers/`; `protocol_telemt/` carries the Telemt image build context and default configuration used for each independent instance. The workflow in `.github/workflows/sync-bw.yml` checks out `main`, copies those modules, applies every patch with `git apply --check`, validates Python syntax, then updates `BW` and builds the Docker image.

When upstream changes, update patches against the new `main` and run the workflow manually from `imp`. Never copy a complete upstream file into this directory.
