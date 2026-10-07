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
```

## 3. Node + pnpm

Node ≥ 20 and pnpm. (`npm i -g pnpm` with a user npm prefix if `/usr/local` isn't writable.)

## glibc / release builds

A binary links against the build host's glibc. Builds made on a newer distro (e.g. Debian 13, glibc
2.41) are **dev-only**. Release `.deb`/AppImage artifacts must be built on the oldest supported base
— Ubuntu 22.04 (glibc 2.35), matching upstream's Jetson/JetPack 6 targets.
