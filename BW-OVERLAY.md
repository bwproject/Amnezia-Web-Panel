# ProjectBW overlay (imp)

This branch is the source of truth for ProjectBW-specific changes. It is based on upstream `main` and contains only:

- New BW-owned Python modules (complete files are appropriate because they do not exist upstream).
- Focused unified-diff patches under `patches/` for modifications to upstream files.
- The workflow that assembles and validates the complete `BW` branch.

## Branch roles

- `main`: untouched upstream Amnezia-Web-Panel.
- `imp`: ProjectBW-only modules and minimal patches; no complete copies of upstream files such as `app.py`.
- `BW`: generated, complete, buildable source tree made from the current `main` plus this branch.

## Build flow

1. Check out `main`.
2. Copy the BW-only modules from this branch.
3. Apply every `patches/*.patch` file. The workflow first runs `git apply --check`; a patch conflict stops the build.
4. Compile the integrated Python modules and check whitespace errors.
5. Synchronize the assembled tree into `BW`.
6. Build and publish `ghcr.io/bwproject/amnezia-panel-bw:latest` and a short-SHA tag.

The workflow runs when relevant files change in `imp`, or manually via GitHub Actions. After updating upstream `main`, run it manually from `imp` to rebase the integration onto the new upstream version.

## Rules

- Do not edit upstream files directly in `imp`; express changes as patches.
- New BW-only files belong in the overlay as complete files.
- Do not make untracked manual changes directly in `BW`; it is generated from `main` + `imp`.
- Never merge `imp` or `BW` into `main`.
