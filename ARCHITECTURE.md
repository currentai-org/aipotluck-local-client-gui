# Architecture

## Shape

```
┌──────────────────── AI Potluck Local Client (Tauri v2) ────────────────────┐
│  ui/ (Svelte 5, Alpha DS tokens)                                            │
│     │  invoke(): app_state · install_plan · model_size · setup_device ·     │
│     │            pair_one_click · cancel_pairing · pairing_server ·         │
│     │            set_pairing_server · clipboard_pairing · pair · unpair ·   │
│     │            service_call · open_link · open_settings_page              │
│  src-tauri/ (Rust)                                                          │
│     ├─ runtime.rs   unpack bundled Python + upstream source; run upstream   │
│     ├─ service.rs   allow-listed proxy to 127.0.0.1:8069                    │
│     ├─ pairing.rs   recognise the Copy-button JSON (never returns secret)   │
│     └─ settings.rs  the GUI's own prefs: the pairing-server override only   │
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

## Why Tauri v2 + Svelte

Seven requirements decided this, and they still describe the shell:

- one download, one native installer per OS, nothing else to install;
- pairing with zero keypresses;
- Linux, macOS and Windows, x64 and arm64 where llama.cpp has assets;
- a small runtime with no bundled browser engine;
- upstream's own code and pins running unmodified, not a port;
- the Alpha design system consumed as CSS rather than hand-translated;
- a UI testable headless on Linux CI.

What was chosen against what:

- **Tauri v2 + Svelte.** A 3-10 MB Rust shell over the OS's own webview (WebView2, WKWebView,
  WebKitGTK), with python-build-standalone as a sidecar: about 30-45 MB per install, about 100 MB
  as a Linux AppImage. The UI is Svelte, the same stack as aipotluck.org, so it imports the
  generated `tokens.css` verbatim instead of re-deriving it. Deep links, tray, single-instance,
  autostart and a signed updater all have official plugins.
- **pywebview, the runner-up.** One language with upstream, and it could import its CLI in-process.
  It loses on install friction where it matters most: on Linux it needs system PyGObject packages a
  standalone Python cannot use, or about 100 MB of QtWebEngine, and a single-file PyInstaller build
  is a routine antivirus false positive on Windows. Deep links, tray and auto-update are also
  DIY per OS.
- **Rejected.** Electron, at 90-150 MB of Chromium per install. Wails, which has no first-party
  updater or deep links and a smaller ecosystem. Tkinter, which cannot render the design system.
  Qt/Flutter/Slint, which cannot reuse the Alpha DS CSS, so the tokens would need the same hand
  translation the Android port needed, at 60-150 MB and LGPL obligations. A localhost web page,
  which still needs an installer, has no app identity, and would need a local write endpoint for
  `login` that upstream deliberately does not have.

Three costs come with it, all still true: the Linux AppImage must be built on the oldest supported
base (Ubuntu 22.04) for glibc compatibility; arm64 AppImages cannot be cross-built, so that target
needs an arm64 runner; and there are three webview engines to test rather than one.

## The bundled runtime

`tools/stage-runtime.sh` stages four things into `src-tauri/resources/runtime/`, and Tauri ships
them as app resources:
- `python-<tag>-<target>.tar.gz`: python-build-standalone 3.12, pinned with sha256 in
  `runtime/python_version.json`, the same pin style as upstream's `llama_version.json`;
- `upstream-<sha12>.tar.gz`: `git archive` of the pinned submodule commit;
- `gui_probe.py`: our read-only state probe;
- `gui_plan.py`: our read-only install plan (what Set up would install, and its sizes);
- `gui_server.py`: which AI Potluck server one-click pairing would use, decided by upstream's own
  `pairing.resolve_server_url`.

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

- **Plan.** Before Set up, the screen lists what will be installed (client, llama.cpp, newt, model)
  with approximate sizes. `gui_plan.py` asks upstream's own code which llama.cpp build and newt
  binary this host gets and which model is the default, sizes the model with upstream's
  `model_preflight.remote_model_bytes`, and sizes the two binaries with a HEAD request to the
  release URL upstream downloads from. The client figure is the unpacked runtime on disk. A size
  that can't be read shows as unknown, never as zero.
- **Customize** opens a settings page. Its one setting so far is the model: any Hugging Face
  `owner/repo[:quant]`, checked in `model_id.rs` and passed as a single `--model-hf=<id>` token.
  Saving re-sizes the model row and the total.
- **Set up** runs `install --backend auto` (plus `--model-hf=<id>` if customized). That is
  upstream's default path:
  - detect the hardware;
  - fetch and verify a llama.cpp build, or use upstream's binary cache or source build;
  - pre-pull and size the default model;
  - write `runtime.json`;
  - register and start the OS service.

  Log lines stream to the UI as a progress caption plus an expandable log.
- **Pair, one click (the default).** **Pair in your browser** runs upstream's `cli login` with no
  credential flags:
  1. Upstream fetches and verifies newt first, so a server it provisions is never left stranded.
  2. It makes a random pairing id and opens aipotluck.org's pair page in the browser. It always
     prints that link; the screen shows it with **Open it again** and **Copy link**, so the person
     can approve on another device.
  3. It polls aipotluck.org until the signed-in person approves. The credentials go straight from
     aipotluck.org into upstream's `runtime.json`; they never pass through the GUI.
  4. **Cancel** sends SIGINT, which upstream handles as Ctrl-C: "Pairing cancelled; nothing was
     changed."

  The screen reads upstream's own words from the log (`ui/src/lib/oneclick.ts`): the link, whether a
  browser opened, and the reason a pairing stopped. A server without one-click pairing (HTTP 404)
  opens the paste fallback automatically.
- **Pair, manually (the fallback).** **Paste the code instead**, or a pairing found on the clipboard
  (`clipboard_pairing`, polled on focus and every 3 s), writes the Copy-button JSON to a 0600 file
  and runs `cli login --credentials-file <file>`. The file is deleted when login exits, and the
  clipboard is cleared if it still holds the pairing.
- **Pairing server override (hidden).** For testing against develop or a local dev server. A small
  gear in the footer, in the hairline colour, that only reads as a control on hover or focus. Once
  set, the footer says "pairing with <server>" in the accent colour, so it can't be left on by
  accident. The value must pass upstream's own `resolve_server_url` (https, or http only to
  localhost) before it's saved to `<data_home>/aipotluck/gui-settings.json`, and is passed as
  `--server-url=<url>`. Without it, upstream's default applies, including `$AIPOTLUCK_SERVER_URL`.
- **Status** shows `/healthz` plus `/status`. The tunnel row reads `tunnel_connected`, not
  `running`: upstream's README documents newt running for 20+ hours while never connected.
- **Models** (on the status screen, once paired) is upstream's HTTP model API, through the proxy:
  - the list is `GET /models`, the same `model_ops.list_models` the CLI's `list` prints. Each row
    carries its LocalScore, band, speed and the CLI's notes (held back, not sized, not measured,
    stale).
  - Add is `POST /models`. Upstream refuses an oversized model before downloading (`409
    too_large_for_device`); only then does the UI offer "Download anyway" (`allow_oversized`).
  - the delete icon is `DELETE /models`, confirmed on the row first, since it deletes the weights.
  - Benchmark is `POST /models/benchmark` for every model.

  Add and Benchmark are upstream jobs. The UI follows the newest unfinished one in `GET /jobs`,
  whoever started it (this window, the CLI, aipotluck.org), showing upstream's latest progress
  step in words, an elapsed clock and how long it may take: the download size from
  `model_preflight` and, for Benchmark, upstream's per-model measuring budget
  (`PROBE_BUDGET_SECONDS`, held to the conformance baseline by a UI test). While a pull downloads,
  the job's `download` byte count drives a real progress bar. A pull downloads and sizes only;
  measuring is Benchmark's. Upstream runs one job at a time, so the controls wait too.
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
  do exactly the nine commands above and nothing else.
- **Secret handling:** see CLAUDE.md "Hard rules".

## Known gaps (v0.1)

- A diagnostics view is not built yet (`todo` in `conformance/coverage.json`).
- Source-build hosts (no prebuilt llama.cpp for the machine) may need apt packages. Upstream only
  installs them with consent through an interactive prompt the GUI can't answer, so the log shows
  upstream's instructions instead.
- Every release target builds in CI (Linux x64/arm64, macOS arm64/x64, Windows x64), but the builds
  are unsigned: macOS gets an ad-hoc signature and Windows none. Signing and notarization need the
  secrets listed in docs/RELEASING.md.
- Release `.deb`/AppImage builds must be made on Ubuntu 22.04 for glibc compatibility
  (docs/BUILDING.md).
