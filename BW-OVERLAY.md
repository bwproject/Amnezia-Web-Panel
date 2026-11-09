# ProjectBW portable overlay

This branch is intentionally based on the upstream `main` branch and contains only additive ProjectBW modules plus this integration manifest.

## Purpose

Keep ProjectBW-specific functionality separate from upstream application files so future upstream updates can be ported by applying a small, reviewable set of integration changes.

## Included modules

- `bw_exit_manager.py` — ProjectBW Exit Node management helpers.
- `bw_wg_awg_transport.py` — transport and routing helpers for standard WireGuard through the server's AmneziaWG transport.
- `managers/wireguard_exit_manager.py` — WireGuard-specific Exit Node adapter.
- `telegram_exit_transport.py` — Telegram Bot API HTTP transport through a selected Exit Node.

## Deliberately not included

This branch does not replace upstream `app.py`, `exit_link_service.py`, `smartroute_service.py`, `telegram_bot.py`, or HTML templates with older full-file copies. Those files change frequently upstream and must be integrated through small, reviewed patches.

## Integration points to maintain

1. Register `BWExitManager` as the Exit Node manager factory.
2. Inject `WireGuardExitManager` into the Exit Link service for `wireguard` protocol instances.
3. Extend the Exit Link service's allowed protocol set to include standard WireGuard while preserving upstream AmneziaWG behavior, validation, cleanup and failover.
4. Route standard WireGuard Smart Route operations through `WireGuardExitManager`; retain upstream Smart Route behavior for AmneziaWG.
5. Inject `TelegramExitHTTPClient` as the Telegram Bot API HTTP client factory and expose a validated Exit Node selector in settings.
6. Expose Exit Node controls for standard WireGuard in the server UI.
7. Keep any UI/settings changes as focused patches against the current upstream templates; never copy the complete old templates over upstream.

## Porting workflow

1. Update this branch's base to the desired upstream commit.
2. Review the additive modules against the upstream manager and transport APIs.
3. Apply the integration points above as small commits, one concern per commit.
4. Run Python compilation, unit/integration tests, and a real VPN routing test before merging.
5. Build and publish the BW image only from a validated integration branch.

## Safety

This is a portability workspace, not a deployable release. It intentionally has no image-build workflow and does not modify `main` or the production `BW` branch.
