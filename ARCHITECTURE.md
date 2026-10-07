# Architecture

## Shape

```
┌──────────────────── AI Potluck Local Client (Tauri v2) ────────────────────┐
│  ui/ (Svelte 5, Alpha DS tokens)                                            │
│     │  invoke(): app_state · install_plan · model_size · setup_device ·     │
│     │            clipboard_pairing · pair · unpair · service_call ·         │
│     │            open_settings_page                                         │
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

`tools/stage-runtime.sh` stages four things into `src-tauri/resources/runtime/`, and Tauri ships
them as app resources:
- `python-<tag>-<target>.tar.gz`: python-build-standalone 3.12, pinned with sha256 in
  `runtime/python_version.json`, the same pin style as upstream's `llama_version.json`;
- `upstream-<sha12>.tar.gz`: `git archive` of the pinned submodule commit;
- `gui_probe.py`: our read-only state probe;
- `gui_plan.py`: our read-only install plan (what Set up would install, and its sizes).

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
  `model_preflight` and upstream's per-model measuring budget (`PROBE_BUDGET_SECONDS`, held to the
  conformance baseline by a UI test). Upstream runs one job at a time, so the controls wait too.
  There is no byte-level download progress: upstream's job reports steps, not bytes, and
  guessing from the cache directory would re-implement llama.cpp's cache resolution. Byte progress
  in the job is an upstream proposal.
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
- Removing a model goes through the running router, so it fails (`delete_failed`, shown to the
  user) while llama-server is down.
- Source-build hosts (no prebuilt llama.cpp for the machine) may need apt packages. Upstream only
  installs them with consent through an interactive prompt the GUI can't answer, so the log shows
  upstream's instructions instead.
- macOS and Windows aren't built or tested yet. Upstream's newt checksums for those platforms are
  still placeholders, so pairing there fails until upstream fills them in. Signing comes later.
- Release `.deb`/AppImage builds must be made on Ubuntu 22.04 for glibc compatibility
  (docs/BUILDING.md).
