# Building locally (Linux: Debian / Ubuntu first)

Local builds are the primary path. CI (GitHub Actions) comes later and will run these same steps.

## 1. System packages (root, once per machine/image)

```bash
sudo apt-get update && sudo apt-get install -y \
  build-essential file libssl-dev pkg-config \
  libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev \
  libayatana-appindicator3-dev libxdo-dev \
  xvfb xauth webkit2gtk-driver
```

- Lines 1–3: compiler plus Tauri v2's Linux build dependencies (WebKitGTK 4.1, GTK3, tray, input).
- Line 4: headless display + WebDriver for running and e2e-testing the GUI without a monitor.

> **Container note (dev host):** on the Hermes dev container these packages are installed into
> the container image, **not** a persistent volume. If the container is rebuilt and Rust/Tauri
> builds start failing (e.g. `pkg-config` can't find `webkit2gtk-4.1`), re-run the command above
> as root. Rust itself (`~/.cargo`, `~/.rustup`) lives in the persistent home and should survive.
> Quick check: `pkg-config --modversion webkit2gtk-4.1 && cargo tauri --version`.

## 2. Rust + Tauri CLI (per user, no root)

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
. "$HOME/.cargo/env"
cargo install tauri-cli --version '^2' --locked
cargo install tauri-driver --locked     # only needed for tools/e2e-smoke.py
```

## 3. Node + pnpm

Node ≥ 20 and pnpm. (`npm i -g pnpm` with a user npm prefix if `/usr/local` isn't writable.)

## glibc / release builds

A binary links against the build host's glibc. Measured: a build made on the Debian 13 dev host
requires **GLIBC_2.39**, so it runs on Debian 13 and Ubuntu 24.04+ but **not** Ubuntu 22.04 /
Debian 12. Those dev builds are fine for testing. Release `.deb`/AppImage artifacts should be built
on the oldest supported base — Ubuntu 22.04 (glibc 2.35, matching upstream's Jetson/JetPack 6
targets) — e.g. in an `ubuntu:22.04` container or a GitHub Actions `ubuntu-22.04` runner.

Check what a build needs: `objdump -T src-tauri/target/release/aipotluck-local-client-gui | grep -o 'GLIBC_[0-9.]*' | sort -Vu | tail -1`

## Testing a build

```bash
tools/check.sh                                   # merge gate (unit + contract + conformance)
DISPLAY=:99 tools/e2e-smoke.py --app src-tauri/target/release/aipotluck-local-client-gui
```

`e2e-smoke.py` needs `cargo install tauri-driver --locked` and an X display (`Xvfb :99 &`). It
drives the real window through set up → pair (with a fake, unreachable pairing) → status →
unpair on a throwaway HOME, and fails if any process the app started outlives it.
