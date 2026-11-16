# ProjectBW overlay (imp)

This branch is the source of truth for ProjectBW-specific changes. It contains BW-only modules, focused patches for upstream files, and the workflow used to assemble the complete product.

## Branch responsibilities

- `main`: mirrors the original `PRVTPRO/Amnezia-Web-Panel` main branch. A scheduled workflow checks upstream every 6 hours and merges new upstream commits into this branch.
- `imp`: contains only ProjectBW modules and patches. When it changes, CI applies the overlay to the current `main` and updates `BW`.
- `BW`: generated complete source tree (`main + imp`). A workflow in this branch builds and publishes the standalone ProjectBW panel container package.

## Automated flow

1. `main` checks `https://github.com/PRVTPRO/Amnezia-Web-Panel` every 6 hours.
2. When upstream has new commits, `main` merges them and dispatches the `imp` assembly workflow.
3. The `imp` workflow copies BW-only modules, applies all `patches/*.patch`, validates Python syntax, and synchronizes the result to `BW`.
4. The `imp` workflow dispatches the package workflow on `BW`.
5. The `BW` workflow builds and publishes `ghcr.io/bwproject/amnezia-panel-bw:latest` for `linux/amd64` and `linux/arm64`.

The workflows are also available for manual runs from GitHub Actions.

## Rules

- Keep application source in `main` aligned with upstream; the only ProjectBW-owned files there are CI workflow definitions.
- Do not put complete copies of upstream application files in `imp`; express changes as patches.
- New BW-only files belong in the overlay as complete files.
- Do not make manual application-source changes directly in `BW`; it is generated from `main + imp`.
- Never merge `imp` or `BW` into `main`.
