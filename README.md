# AI Potluck Local Client (desktop GUI)

A desktop app that turns this computer into a local inference server for
[aipotluck.org](https://aipotluck.org) in two clicks. It's a window on
[`aitpotluck-local-client`](https://github.com/currentai-org/aitpotluck-local-client): the app
bundles that CLI's own code and a Python to run it with, so the llama.cpp and newt binaries, their
pins and checksums, the background service, and the pairing are exactly the CLI's.

**Status: v0.1, Linux (Debian/Ubuntu), Windows 10/11 x64 and macOS (Apple silicon and Intel). macOS
and Windows builds are unsigned.**

## Using it

1. Install the `.deb` (or run the `.AppImage`) and open **AI Potluck**.
2. **Set up.** Installs llama.cpp for this hardware and a small starter model.
3. On aipotluck.org go to **Settings → Local Inference → Add a managed server → Pair → Copy**, then
   switch back to the app and click **Pair this computer**.

The server keeps running in the background (a systemd user service) after the window closes,
exactly like a CLI install. The `aipotluck-local-client` command is installed too, for anyone who
wants it.

## Building

See [docs/BUILDING.md](docs/BUILDING.md) for the one-time toolchain setup. Then:

```bash
git clone --recurse-submodules <this repo>
tools/build.sh --dev      # run it
tools/build.sh            # .deb + .AppImage in src-tauri/target/release/bundle/
tools/check.sh            # the merge gate
```

Installers are built by GitHub Actions (`.github/workflows/build.yml`). Linux x64 and arm64 and
Windows x64 and macOS arm64 and x64 build today. Every push to `main`
updates the **nightly** prerelease, and a `v*.*.*` tag makes a draft release. See
[docs/RELEASING.md](docs/RELEASING.md). To build any target the way CI does:
`tools/build.sh --release-target <target>`.

## Layout

```
upstream/aitpotluck-local-client/  git submodule: the CLI, pinned (the only upstream the app ships)
runtime/python_version.json        pinned python-build-standalone + sha256s
sidecar/gui_probe.py               read-only state probe, runs on upstream's own layout code
src-tauri/                         Rust shell: runtime unpack, upstream runner, service proxy, pairing
ui/                                Svelte UI; ui/src/design/ = Alpha DS synced from aipotluck.org
conformance/                       upstream interface baseline + coverage manifest
tests/                             contract tests vs upstream's real code (run on the bundled Python)
tools/                             build, check, stage-runtime, sync_upstream, watchdog, design sync
docs/                              BUILDING, RELEASING, CONFORMANCE, DESIGN-SYSTEM, research/
.github/                           CI: check.yml (the gate), build.yml (installers + draft release), build-targets.json
```

Read [CLAUDE.md](CLAUDE.md) (conventions), [ARCHITECTURE.md](ARCHITECTURE.md) (design), and
[docs/CONFORMANCE.md](docs/CONFORMANCE.md) (how this stays in step with the CLI).
