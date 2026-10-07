# AI Potluck Local Client (desktop GUI)

A desktop app that turns this computer into a local inference server for
[aipotluck.org](https://aipotluck.org) in two clicks. It's a window on
[`aitpotluck-local-client`](https://github.com/currentai-org/aitpotluck-local-client): the app
bundles that CLI's own code and a Python to run it with, so the llama.cpp and newt binaries, their
pins and checksums, the background service, and the pairing are exactly the CLI's.

**Status: v0.1, Linux (Debian/Ubuntu) first.** macOS and Windows aren't built yet.

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
docs/                              BUILDING, CONFORMANCE, DESIGN-SYSTEM, research/
```

Read [CLAUDE.md](CLAUDE.md) (conventions), [ARCHITECTURE.md](ARCHITECTURE.md) (design), and
[docs/CONFORMANCE.md](docs/CONFORMANCE.md) (how this stays in step with the CLI).
