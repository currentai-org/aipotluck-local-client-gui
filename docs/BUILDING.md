# Building locally (Linux: Debian / Ubuntu; macOS)

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

> **Container note (dev container):** in a container these packages are installed into
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

## macOS (Apple silicon; builds both macOS targets)

Proven on macOS 27.0, Apple M5 Pro. Nothing below needs Homebrew.

1. **Command Line Tools** (admin, once). Over SSH, `xcode-select --install` can't open its
   dialog, so use `softwareupdate`:
   ```bash
   softwareupdate -l | grep "Label: Command Line Tools"        # find the exact label
   sudo softwareupdate -i "Command Line Tools for Xcode 27.0-27.0"
   xcode-select -p                                             # -> /Library/Developer/CommandLineTools
   ```
   Until they're installed, `/usr/bin/python3` is only a placeholder that offers to install them,
   so nothing that needs Python works yet.
2. **Rust** (per user): the rustup command in section 2 with `--no-modify-path`, then
   `rustup target add x86_64-apple-darwin` so one Mac builds both `macos-arm64` and `macos-x64`.
   `cargo install tauri-cli --version '^2' --locked`.
3. **Node + pnpm** (per user, no installer): untar the LTS `node-vX-darwin-arm64.tar.gz` from
   nodejs.org into `~/.local` (symlink `~/.local/node`, put `~/.local/node/bin` on `PATH`), then
   `corepack install -g pnpm@10.34.4` (the version this repo's lockfile was made with).
4. Build: `tools/build.sh --release-target macos-arm64` (or `macos-x64`) → `dist/<target>/*.dmg`.

Notes:
- `tools/build.sh --release-target` sets `CI=true`. Without it, the DMG step runs a Finder
  AppleScript to lay out the window, which fails with error `-10810` when no one is logged in to
  the Mac's desktop (a build over SSH). GitHub's runners set `CI=true` themselves.
- Builds are **ad-hoc signed** (`signingIdentity: "-"` in `tauri.conf.json`), which Apple silicon
  requires for an app to run at all. There's no Developer ID yet, so a downloaded `.dmg` is
  blocked by Gatekeeper on first open; see `docs/RELEASING.md`. A Developer ID in
  `APPLE_SIGNING_IDENTITY` overrides the ad-hoc identity.
- `tools/check.sh` passes on macOS. It restages the runtime for the host every run, because a
  `--release-target macos-x64` build leaves the Intel interpreter staged ("Bad CPU type in
  executable" on Apple silicon).
- `tools/e2e-smoke.py` is Linux-only (tauri-driver has no macOS WebDriver). On macOS, test the
  app by hand.

## glibc / release builds

A binary links against the build host's glibc. A build made on the Debian 13 dev host
requires **GLIBC_2.39**, so it runs on Debian 13 and Ubuntu 24.04+ but **not** Ubuntu 22.04 /
Debian 12. Those dev builds are fine for testing. Release `.deb`/AppImage artifacts should be built
on the oldest supported base — Ubuntu 22.04 (glibc 2.35, matching upstream's Jetson/JetPack 6
targets) — e.g. in an `ubuntu:22.04` container or a GitHub Actions `ubuntu-22.04` runner.

Check what a build needs: `objdump -T src-tauri/target/release/aipotluck-local-client-gui | grep -o 'GLIBC_[0-9.]*' | sort -Vu | tail -1`

## Testing a build

```bash
tools/check.sh                                   # merge gate (unit + contract + conformance)
tools/e2e-smoke.py --app src-tauri/target/release/aipotluck-local-client-gui
```

`e2e-smoke.py` needs `cargo install tauri-driver --locked` and, from apt, `webkit2gtk-driver`
(its version must match the installed `libwebkit2gtk-4.1-0`) and `xvfb`. It starts its own Xvfb
display, so the window never appears on the desktop, even in a Wayland session; pass `--visible`
to watch it on `$DISPLAY` instead. It drives the real window on a throwaway HOME with no systemd
session:
- the install plan, then Customize (a bad model id refused, a small real model sized);
- set up, checking upstream pulled exactly that model;
- pair, with a fake, unreachable pairing; status; unpair.

It fails if any process the app started outlives it. `--default-model` skips Customize and
installs upstream's default model instead.
