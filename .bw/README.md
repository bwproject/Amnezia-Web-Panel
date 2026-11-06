# ProjectBW edition

The `BW` branch is a thin customization layer over the upstream `main` branch.

## Build model

The `Build Panel BW` workflow always checks out the current `main` branch into a clean build directory, then overlays the files stored in `bw-overlay/` from this `BW` branch. Docker is built from that combined source and published as:

- `ghcr.io/bwproject/panel-bw:latest`
- `ghcr.io/bwproject/panel-bw:sha-<commit>`

Do not merge upstream application files wholesale into `BW`. Put only ProjectBW-specific additions or replacement files in `bw-overlay/`. This keeps upstream fixes from `main` automatically included in each BW image build.

## Planned customization

- Route the panel's Telegram bot traffic through the configured Exit Node.
- Keep this behavior isolated to the BW overlay; do not change upstream `main`.

No application customization is implemented yet. The overlay is intentionally empty.
