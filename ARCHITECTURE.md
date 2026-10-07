# Architecture

## Shape

```
┌──────────────────── AI Potluck Local Client (Tauri v2) ────────────────────┐
│  ui/ (Svelte 5, Alpha DS tokens)                                            │
│     │  invoke(): app_state · setup_device · clipboard_pairing · pair ·      │
│     │            unpair · service_call · open_settings_page                 │
│  src-tauri/ (Rust)                                                          │
│     ├─ runtime.rs   unpack bundled Python + upstream source; run upstream   │
│     ├─ service.rs   allow-listed proxy to 127.0.0.1:8069                    │
│     └─ pairing.rs   recognise the Copy-button JSON (never returns secret)   │
└──────┬─────────────────────────────────────────────┬────────────────────────┘
       │ python -m aipotluck.installer.install        │ HTTP (allow-list)
       │ python -m aipotluck.installer.cli login/out  │
       ▼                                              ▼
  upstream code (pinned submodule, unchanged)   upstream service :8069
  └ downloads llama.cpp + newt (its own pins,   └ supervises llama-server (router :8080)
    checksums), writes runtime.json, registers    and newt (Pangolin tunnel)
    systemd --user / launchd / Scheduled Task
```

**The GUI never does anything upstream's code doesn't already do.** It chooses *which* upstream
command to run, with which flags, and shows the result.

## The bundled runtime

`tools/stage-runtime.sh` stages three things into `src-tauri/resources/runtime/`, and Tauri ships
them as app resources:
- `python-<tag>-<target>.tar.gz`: python-build-standalone 3.12, pinned with sha256 in
  `runtime/python_version.json`, the same pin style as upstream's `llama_version.json`;
- `upstream-<sha12>.tar.gz`: `git archive` of the pinned submodule commit;
- `gui_probe.py`: our read-only state probe.

On first launch `runtime.rs` verifies each archive's sha256 and unpacks it, atomically, into
`<data_home>/aipotluck/gui-runtime/` (beside upstream's own `<data_home>/aipotluck/llama.cpp/`).

Why unpack into a stable directory instead of running from the bundle: upstream's installer writes
the interpreter path and its own source path into the OS service definition (`ExecStart=` in the
systemd unit). An AppImage's mount point (`/tmp/.mount_*`) and a translocated macOS app's path both
disappear when the app quits, so a service registered against them would break at the next reboot.

A new upstream pin unpacks to a new `upstream-<sha12>/` directory. Re-running setup then
re-registers the service against it.

Why Python is bundled: upstream is stdlib-only (`dependencies = []`, requires ≥3.9), but stock
Windows and some minimal Linux installs have no suitable `python3`. A pinned interpreter also means
the one we test (`tools/bundled-python.sh`) is the one users run.

## Flows

- **Set up** runs `install --backend auto`. That is upstream's default path:
  - detect the hardware;
  - fetch and verify a llama.cpp build, or use upstream's binary cache or source build;
  - pre-pull and size the default model;
  - write `runtime.json`;
  - register and start the OS service.

  Log lines stream to the UI as a progress caption plus an expandable log.
- **Pair** (zero keypresses):
  1. The UI polls `clipboard_pairing` on window focus and every 3 s while on the pair screen.
  2. When the clipboard holds `{tunnelId, tunnelSecret, tunnelEndpoint}`, it shows the endpoint and
     a **Pair this computer** button.
  3. Clicking writes the clipboard text to a 0600 file and runs
     `cli login --credentials-file <file>`, which downloads newt with upstream's pin, writes
     `runtime.json`'s `tunnel` section, and restarts the service.
  4. The file is deleted when login exits, and the clipboard is cleared if it still holds the
     pairing.

  A paste box is the fallback.
- **Status** shows `/healthz` plus `/status`. The tunnel row reads `tunnel_connected`, not
  `running`: upstream's README documents newt running for 20+ hours while never connected.
- **Unpair** runs `cli logout`.

### Hosts with no service manager

Some hosts have no usable systemd user session, such as containers and WSL without systemd.
Upstream's `start` would fail there, so the GUI handles it in three steps:
1. `gui_probe.py` detects it (`systemctl --user show-environment` fails).
2. Set up passes `--no-start`.
3. The GUI spawns upstream's service payload itself, with the exact argv the unit file would use,
   and stops it with SIGTERM when the window closes.

The UI says plainly that the server only runs while the window is open.

## Security

- **CSP:** `default-src 'self'`. No remote content, fonts are bundled, and `connect-src` is limited
  to Tauri IPC.
- **Proxy allow-list:** `service.rs` allows only routes upstream serves, per method. It rejects `..`,
  absolute URLs and other methods, and a test checks the allow-list against the upstream baseline.
- **Capabilities:** only `core:default`. There is no shell or filesystem plugin, so the webview can
  do exactly the seven commands above and nothing else.
- **Secret handling:** see CLAUDE.md "Hard rules".

## Known gaps (v0.1)

- Models screen (pull/list/remove/benchmark) and a diagnostics view are not built yet. They are
  `todo` in `conformance/coverage.json`.
- Source-build hosts (no prebuilt llama.cpp for the machine) may need apt packages. Upstream only
  installs them with consent through an interactive prompt the GUI can't answer, so the log shows
  upstream's instructions instead.
- macOS and Windows aren't built or tested yet. Upstream's newt checksums for those platforms are
  still placeholders, so pairing there fails until upstream fills them in. Signing comes later.
- Release `.deb`/AppImage builds must be made on Ubuntu 22.04 for glibc compatibility
  (docs/BUILDING.md).
