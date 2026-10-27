# aipotluck-local-client GUI — research, framework choice, and upstream-sync plan

Date: 2026-10-07 · Status: proposal, nothing implemented

## Decisions (2026-10-07, Andrew)
- Signing: no Apple Developer ID yet; plan for it later. **Linux (Debian/Ubuntu) is the first tested platform.**
- Branching: short-lived branches merged **straight to `main`**; add `develop` later if needed.
- Toolchain: Rust installed locally; **local builds must work first**, GitHub Actions later.
- Dev host: Debian 13 (trixie) aarch64, glibc 2.41. Binaries built here are dev-only; release
  AppImage/.deb must be built on Ubuntu 22.04 / Debian 12 for glibc compatibility.

## 0. TL;DR

- **Don't re-implement the CLI. Embed it.** The GUI ships the upstream `aitpotluck-local-client`
  Python package unchanged (git submodule pinned to an exact commit) plus a bundled standalone
  Python. It calls the same `install.py` and `cli.py` code paths and talks to the same local service
  on `127.0.0.1:8069`. That gives the same llama.cpp and newt binaries, the same pins and checksums
  (`llama_version.json`, `llama_custom_builds.json`, `newt_version.json`), the same `runtime.json`,
  the same OS service registration and the same tunnel, with no second implementation.
- **Recommended shell: Tauri v2 + Svelte**, with the Python runtime as a bundled sidecar.
  The installer is about 30–45 MB (mostly Python), each OS gets a native installer, and the UI uses
  the same CSS tokens as aipotluck.org's Alpha design system. Runner-up: pywebview, which is pure
  Python but needs extra Linux system packages and has weaker packaging.
- **Zero-keypress pairing**: aipotluck.org's existing **Copy** button already puts the pairing JSON
  on the clipboard. The app watches for that JSON when its window gains focus and offers a single
  **Pair this device** button. A later `aipotluck://pair` deep link would remove even that step, but
  it needs a change to the web app.
- **Sync = the two-half harness the Android port already uses.**
  1. Hermetic CI tests hold the GUI to a committed snapshot of the upstream surface.
  2. A scheduled `tools/sync_upstream.sh` fetches upstream. It diffs the surface, then runs
     upstream's own tests and our contract and e2e tests against the candidate commit. It stays
     silent when everything is green and reports when something drifts.

---

## 1. What the upstream project actually is (as of `origin/main` 2ac2591, 2026-10-06)

Source: a fetched checkout of `aitpotluck-local-client` (local `main` was 20 commits behind origin; untouched).

- **Pure-stdlib Python ≥3.9, `dependencies = []`.** It has no build step and no pip install. Optional
  `pywin32` is needed only for the Windows `--system` service.
- **Installer** (`aipotluck/installer/install.py`):
  - detects OS, arch and GPU backend, plus glibc and CUDA SM (`platform_detect.py`);
  - picks a prebuilt llama.cpp asset, our own binary cache, or a source build (`build_strategy.py`,
    `build_cache.py`, `source_build.py`);
  - downloads, verifies sha256 and extracts (`fetch.py`);
  - pre-pulls and pre-sizes a default model, writes `runtime.json`, and registers an OS service
    (systemd user unit / launchd LaunchAgent / Scheduled Task, plus a `--system` variant of each);
  - writes the `aipotluck-local-client` PATH shim.
  - Every install finishes **logged out**.
- **Service** (`aipotluck/service/runner.py`): an HTTP server on `127.0.0.1:8069` that supervises
  `llama-server` (router mode, port 8080) and `newt` (Pangolin tunnel). It is gated on
  `runtime.json`'s `logged_in` flag.
  - `GET /healthz`, `/status`, `/capabilities`, `/models`, `/jobs`, `/jobs/<id>`
  - `POST /models`, `/models/benchmark` (async jobs, 202 + job id)
  - `DELETE /models?model=`
  - **New in the last 20 commits:** pull, list, benchmark and remove over HTTP, plus a jobs API and
    held-back models. This is the API a GUI wants.
- **CLI** (`aipotluck/installer/cli.py`): `login`, `logout`, `status`, `pull`, `list`, `remove`,
  `benchmark`.
  - **`login`/`logout` have no HTTP equivalent.** They download newt, edit `runtime.json` directly
    and restart the OS service.
  - A GUI therefore has to call this Python code, either in-process or as a subprocess. It cannot do
    login through the HTTP API alone.
- **Pins:**
  - llama.cpp `b10989` (sha256 computed by us);
  - newt `1.17.0`→`1.18.1` on main. Its macOS and Windows checksums are still the placeholder
    `UNVERIFIED_…`, which blocks a real Mac/Windows pairing until someone fills them in.
- **Public one-liner** (`install.sh` / `install.ps1`) clones into `~/.aipotluck/src` or
  `%LOCALAPPDATA%\aipotluck\src` and hands off to the installer.
- **Conventions** (`CLAUDE.md`):
  - conventional commits `type(scope): summary`;
  - a short-lived branch for non-trivial changes. In practice these are PRs named
    `andrewtergis/cur-NNNN-slug` → `main`;
  - never push without approval;
  - "Runtime parameters always observable";
  - Tests and gates rules 1–4: a check that can't go red isn't one; fail-open contracts are named;
    green units are never sufficient for OS and network paths; never assert on source text.
- **Verified hardware:** Linux x86_64 and Jetson only. **macOS and Windows backends have never run
  on real hardware.** That is the biggest risk for a cross-platform GUI, because the GUI will be the
  first heavy user of those paths.

Sibling precedent: the Android port (`aipotluck-local-client-android`) already solved two of the problems
this project faces:
- conformance against this same upstream: `tools/check_upstream.sh`,
  `tools/conformance/extract_surface.py`, `conformance/{desktop-surface,coverage}.json`;
- design-token sync from `alpha-ds`: `tools/design/sync-alpha.py`, `docs/DESIGN-SYSTEM.md`.

Reuse both.

Design guide: there is no `/designguide` route in the aipotluck.org web app. The equivalents are:
- the **`/designsystem`** route (`web/src/routes/designsystem`), which browses the Alpha DS;
- `web/src/lib/alpha-ds/` (tokens → `tokens/generated/tokens.css`, `tokens.json`);
- the rules in `web/src/lib/chat/design-system.md`: three backgrounds, three border opacities,
  three text strengths, accent at icon/badge scale only, sharp corners, Plus Jakarta Sans and
  DM Mono.

I've assumed that's what "/designguide" meant.

---

## 2. Requirements → evaluation criteria

| # | Requirement | How it's scored |
|---|---|---|
| R1 | Install friction is the #1 goal | One download, one native installer, no prerequisites (no Python, git or package manager), no terminal |
| R2 | Few clicks, fewer keypresses | Pairing must be possible with 0 keypresses |
| R3 | macOS + Linux + Windows | Native installer per OS; x64 + arm64 where llama.cpp has assets |
| R4 | Minimal dependencies, low graphics need | Small runtime, no GPU UI stack, no 100 MB browser engine if avoidable |
| R5 | Identical transport, API and binaries to the CLI | Must run upstream's own code and pins, not a port |
| R6 | Follow the Alpha design system | Can we consume `tokens.css` directly instead of hand-translating? |
| R7 | Periodic upstream compatibility tests | Testable headless on Linux CI; contract layer testable without a GUI |

---

## 3. Options evaluated

The size estimate for every option includes the ~22–34 MB bundled CPython that R5 requires. The
figures are python-build-standalone `cpython-3.12.15` `install_only_stripped` tarballs (release
20261003): mac-arm64 25.0 MB, win-x64 22.0 MB, linux-x64 34.3 MB, linux-arm64 29.2 MB.

### A. Tauri v2 (Rust core + system webview) + Svelte UI + bundled Python sidecar — **recommended**
- **Install:**
  - Windows: `.msi` or NSIS `.exe`. The webview is WebView2, which is preinstalled on all Windows 11
    and on serviced Windows 10. The NSIS bootstrapper can install it if it's missing.
  - macOS: `.dmg`, drag to Applications. The webview is WKWebView, part of the OS.
  - Linux: `.AppImage` (self-contained, ~70 MB+ with WebKitGTK bundled), `.deb` and `.rpm`.
    The deb and rpm declare `libwebkit2gtk-4.1` as a dependency, so `apt` pulls it in.
- **Size:** a 3–10 MB app plus Python ≈ **30–45 MB** on Windows and macOS, and ~100 MB as an
  AppImage.
- **R5:**
  - `bundle.resources` carries the upstream submodule (Python source plus the pin JSONs).
  - `externalBin` carries python-build-standalone.
  - Rust spawns `python -m aipotluck.installer.install …` and `… cli login --credentials-file …`
    exactly as the CLI user would, and talks HTTP to `:8069` for everything else.
- **R6:** the UI is Svelte, the same stack as aipotluck.org. It imports `alpha-ds`'s generated
  `tokens.css` verbatim. The OKLCH `light-dark()` colours work in current WebView2 and WebKit; check
  that the older WebKitGTK on Ubuntu 22.04 supports them, and fall back to the generated sRGB values
  if not.
- **Built-in pieces:** official plugins cover single-instance, tray, autostart, deep-link
  (`aipotluck://`), clipboard, updater (signed) and notifications. Code-signing and notarization are
  documented for both macOS and Windows.
- **Cons:**
  - The Rust toolchain is needed in CI.
  - The Linux AppImage must be built on the **oldest** target base (Ubuntu 22.04 or Debian 12) for
    glibc compatibility.
  - ARM AppImages can't be cross-built, so they need an arm64 runner.
  - The webview differs per OS, which means 3 rendering engines to test.

### B. pywebview (Python + system webview) + same Svelte/HTML UI
- **For:** one language with upstream, so the GUI could import `aipotluck.installer.cli` in-process.
- **Install:**
  - Windows needs pythonnet and WebView2.
  - macOS needs the pyobjc frameworks (~10 MB of wheels).
  - **Linux needs either system GTK/WebKit2 PyGObject packages (`apt install python3-gi
    gir1.2-webkit2-4.1`), which a standalone Python can't easily use, or PyQt6 / QtWebEngine
    (~100 MB+).**
  - Packaging goes through PyInstaller or Briefcase. Single-file PyInstaller exes are a frequent
    antivirus false positive on Windows, which is real install friction.
- **Missing pieces:** deep links, tray and auto-update are all DIY per OS.
- **Verdict:** a viable fallback, but worse on R1 for Linux and on updates.

### C. "Headless" GUI: a local web page served on `127.0.0.1`, opened in the default browser
- **For:** almost no new dependencies, and it works on a headless Linux box over SSH port-forward.
- **Against:**
  - It still needs an installer, so the friction is unchanged.
  - It isn't an app: no tray or dock icon, and closing the browser tab looks like quitting.
  - Doing `login` from a browser page needs a new local write endpoint, which is a localhost
    CSRF/DNS-rebinding exposure. Upstream deliberately has none.
- **Verdict:** worth keeping as a **secondary mode** of option A, by serving the same Svelte build
  for headless Linux. Not suitable as the primary.

### D. Tkinter (ships inside python-build-standalone)
- **For:** zero extra dependencies. It's already in the Python we must bundle anyway.
- **Against:** it fails R6. Tk can't render the Alpha DS (OKLCH tiers, typography, Remix icons)
  without a hand-built theme, and it looks dated. Its HiDPI behaviour on Windows and Linux is
  inconsistent.
- **Verdict:** only useful as an emergency installer fallback.

### E. Wails (Go + system webview)
- Similar to Tauri in size and webview model. Go matches newt's language, but that has no practical
  benefit here.
- v2 has no first-party updater or deep-link support, and v3 is still alpha.
- The community and plugins are smaller than Tauri's.
- **Verdict:** behind Tauri on every criterion that matters here.

### F. Electron
- 90–150 MB of bundled Chromium per install, plus Node. It fails R4. The only advantage is a single
  rendering engine. **Rejected.**

### G. Native toolkits (Qt/PySide6, Flutter, Slint, Fyne)
- They can't reuse the Alpha DS CSS, so the tokens would need a hand translation like Android's
  Compose port. Qt adds 60–150 MB and LGPL obligations. Flutter adds a second language and toolchain.
- **Verdict:** they carry Android-style translation cost for no install benefit.

### Scorecard (✓ good, ~ ok, ✗ poor)

| | R1 install | R2 clicks | R3 x-plat | R4 deps | R5 same code | R6 design | R7 testable |
|---|---|---|---|---|---|---|---|
| **A Tauri+Svelte** | ✓ | ✓ (deep link, clipboard, tray) | ✓ | ✓ | ✓ sidecar | ✓ tokens.css verbatim | ✓ |
| B pywebview | ~ (Linux) | ~ | ✓ | ~ | ✓ in-proc | ✓ | ✓ |
| C browser UI | ~ | ~ | ✓ | ✓ | ✓ | ✓ | ✓ |
| D Tkinter | ✓ | ~ | ✓ | ✓ | ✓ | ✗ | ~ |
| E Wails | ✓ | ~ | ✓ | ✓ | ✓ | ✓ | ✓ |
| F Electron | ~ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| G Qt/Flutter | ~ | ~ | ✓ | ✗ | ✓ | ✗ | ~ |

---

## 4. Proposed architecture (option A)

```
aipotluck-local-client-gui/
  upstream/aitpotluck-local-client/   git submodule, pinned commit (THE CLI, unmodified)
  runtime/python.lock.json            python-build-standalone tag + per-target sha256 (same pin style as llama_version.json)
  src-tauri/                          Rust: window, tray, single-instance, deep-link, sidecar spawn, update
  ui/                                 Svelte app; imports design/tokens.css
  design/                             tokens.css + fonts + Remix icons, generated by tools/design/sync-alpha
  conformance/                        upstream-surface.json (baseline) + coverage.json (manifest)
  tools/                              check.sh, sync_upstream.sh, design/sync-alpha.py, conformance/*
  tests/                              contract tests (vs a live upstream service), UI e2e
```

**Runtime model**:
1. First launch copies Python and the upstream source out of the app bundle into a **stable per-user
   path** under upstream's own layout root, versioned (for example
   `~/.local/share/aipotluck/gui-runtime/<upstream-sha>/`).
2. **Why the copy is required:** the OS service unit records the interpreter path. An AppImage
   mounts at a random `/tmp/.mount_*` path, macOS App Translocation moves apps out of quarantine
   into a random path, and both vanish when the app quits. Registering the service against the
   bundle path would break the service after the first reboot.
3. Install is `python -m aipotluck.installer.install --backend auto`, with progress streamed from
   its log. The service is then a normal upstream service. **The GUI can quit and inference keeps
   running**, which matches the CLI.
4. Pair is `python -m aipotluck.installer.cli login --credentials-file <0600 temp file>`. The file is
   deleted right after, and the secret never goes on argv, where `ps` would show it.
5. Status, models, pull, benchmark and remove go to `http://127.0.0.1:8069` (`/status`, `/models`,
   `/jobs/<id>`). The GUI polls; it computes nothing itself. Any computed value it shows comes from
   `/status`'s `runtime_params`, which follows upstream's "observable runtime params" rule.
6. Uninstall and unpair call the same upstream entry points.

**Click budget (target):**
- download (1) → run installer (1–2) → app opens, "Set up this computer" (1). Backend is
  auto-detected and the default model is pre-pulled, with progress shown.
- On aipotluck.org: Pair → Copy. Switch to the app, which detects the pairing JSON → **Pair (1)**.
- Total ≈ 4–5 clicks in the app and installer, **0 keypresses**.
- A later deep link (`aipotluck://pair?…`, which needs an aipotluck.org change; that repo is
  read-only for us, so this is a proposal) turns Copy+Pair into one click on the website.

**Paste fallback:** a large paste target, Ctrl/⌘-V only. Ctrl/⌘-V is the only keypress anywhere.

**Clipboard safety:** read the clipboard only on window focus while the pair screen is showing, and
match it strictly against `{tunnelId, tunnelSecret, tunnelEndpoint}`. Never log the clipboard
contents, and clear the clipboard after a successful pair (optional, needs a decision).

---

## 5. Staying in sync with upstream (the periodic integration test)

This follows `upstream-conformance-harness` and the Android repo's working version of it.

### 5.1 Pin
- `upstream/aitpotluck-local-client` is a git submodule. The commit pinned there is the
  **only** upstream the app ships, and it is bumped by a reviewable commit
  (`chore(upstream): bump to <sha> — <summary>`).
- llama.cpp and newt pins come from that submodule's JSON files, so the GUI is in lockstep with the
  CLI by construction. The Android repo's "newt lockstep" rule becomes automatic here.

### 5.2 Hermetic half (CI, every commit — `tools/check.sh`)
1. **Surface conformance**:
   - Port `extract_surface.py` from the Android repo; it uses `ast` over the same upstream.
   - It extracts: CLI subcommands and flags, installer flags, HTTP routes and their response JSON
     keys, `runtime.json` keys read, error `code`s, job states, and pin files.
   - Compare the extraction against the committed `conformance/upstream-surface.json`.
   - Every leaf must be classified in `coverage.json` as `implemented` / `partial` /
     `not_applicable` / `todo`, with a note.
   - Unclassified or stale leaves fail the build.
   - **GUI meaning of `implemented`: reachable from the UI**, not merely callable.
2. **Contract tests**:
   - Start the *real* upstream service from the pinned submodule against a temp layout
     (`--install-dir`), with a stub `llama-server`/`newt` (the same technique upstream's own tests
     use).
   - Drive it through the GUI's TS client.
   - Assert the response shapes our UI depends on, and that login/logout through the sidecar path
     leaves the same `runtime.json` the CLI would.
3. **UI e2e**: Playwright against the Svelte build with the Tauri IPC mocked, plus a `tauri-driver`
   (WebDriver) smoke test on Linux.
4. **Upstream's own `pytest`**, run with the bundled Python. This proves the interpreter we ship can
   run upstream unchanged.

### 5.3 Network half (scheduled — `tools/sync_upstream.sh`)
1. `git fetch` upstream `main` into a cache clone. Never write to the upstream checkouts. If
   `origin/main` == pinned, print nothing and exit 0.
2. Otherwise, in a scratch worktree, check out the candidate in the submodule and run:
   - surface diff (added / removed / changed) and coverage;
   - upstream pytest;
   - our contract and e2e suites.
3. Report:
   - the new commits (`git log --oneline pinned..candidate`);
   - surface drift with classification;
   - unclassified items, which are new upstream features the GUI doesn't expose yet;
   - test results;
   - pin changes (llama.cpp tag, newt tag, python requirement).
4. Exit codes:
   - `0` in sync;
   - `1` drift or failure;
   - `2` couldn't run (fetch or parse failure). This is reported as a tooling error, never as
     "upstream deleted everything".
5. If everything is green and only `implemented` leaves changed, prepare a local branch
   `chore/upstream-bump-<sha>` with the bumped submodule and refreshed baseline. **It is not pushed**
   (push requires your approval, as in upstream's CLAUDE.md).
6. **Schedule:** a scheduled script job runs daily. It is silent when there's nothing to
   say and delivers the report to the maintainer otherwise. It always exits 0 so the report itself is the
   signal. The same script is reusable later as a GitHub Actions `schedule:` workflow, since the
   org's CI control plane is GitHub Actions.
7. **Prove it can go red** before trusting it: inject a synthetic new subcommand, a changed flag
   default, a new route and a new response key into a scratch copy, and confirm each one is reported.

### 5.4 Design sync (same pattern, lower stakes)
- `tools/design/sync-alpha.py <aipotluck.org checkout>` copies `alpha-ds/tokens/generated/tokens.css`
  and `tokens.json`, the fonts (OFL) and the Remix icons into `design/`. It records the source SHA.
- A weekly check diffs the token output and the `design-system.md` rules hash, then reports.

---

## 6. Conventions to adopt (from upstream `CLAUDE.md`, plus the Android translation)

- `CLAUDE.md` + `AGENTS.md` symlink.
- Conventional commits `type(scope): summary`. Scopes: `ui`, `shell`, `sidecar`, `upstream`,
  `design`, `conformance`, `packaging`, `tests`, `docs`.
- One branch per change, `andrewtergis/cur-NNNN-slug` when there's a ticket, merged to `main` by PR,
  as upstream is doing now. **Open question:** upstream's CLAUDE.md text says "solo, commits to
  main", while the Android port and the web app use `main ← develop ← branch`. I'd mirror upstream's
  actual practice (PR → main) unless you want `develop`.
- Never push or create a remote without approval. Never write to `currentai/` checkouts.
- Tests and gates rules 1–4 verbatim. Add one rule: **"green CI is never sufficient for an
  installer change; it must be run on the real OS"**. That means a manual matrix per release
  (Win 11 x64, macOS arm64, Ubuntu 22.04/24.04 x64, arm64), recorded in the PR.
- The runtime-params observability rule carries over: the GUI shows `runtime_params` reasons and
  never computes its own.

---

## 7. Risks and open questions

1. **macOS and Windows paths in upstream are untested on real hardware, and the newt checksums for
   mac and win are placeholders.** The GUI will surface these first. Should the GUI project own
   fixing them upstream (via PRs to the CLI repo), or wait?
2. **Code signing.**
   - An unsigned app gets a Gatekeeper block on macOS. A signed but un-notarized one also fails on
     first run.
   - On Windows, unsigned means a SmartScreen warning. The cheapest option is Azure Trusted
     Signing, about $10/mo.
   - Without signing, "minimal friction" is not achievable. Who holds the Apple Developer ID and
     the Windows signing identity for Current AI?
3. **GPU backends on Windows and macOS.** Upstream picks CUDA, Vulkan or CPU, and Metal on macOS.
   The GUI only displays the choice; it must not add its own logic (R5).
4. **Deep link** needs an aipotluck.org change, filed as a proposal, never pushed by us.
5. **Repo location and name**: proposed as its own git repo named `aipotluck-local-client-gui`.
6. **Toolchain:** the dev host had no Rust or cargo. Building Tauri requires rustup and the
   webkit2gtk dev headers, which apt can't install without root. That made local builds there
   unlikely, so the plan was to build in GitHub Actions.
7. **Linux baseline:** build on Ubuntu 22.04 (glibc 2.35) to match the Jetson targets upstream
   supports.

## 8. Proposed next steps (once you approve)
1. `git init` the repo; adopt CLAUDE.md; add upstream as a submodule pinned to `2ac2591`.
2. Port the conformance extractor and coverage manifest, and prove they can go red.
3. Write `sync_upstream.sh` plus the scheduled watchdog. Test both the silent path and the report
   path.
4. Build the sidecar prototype with no UI yet: bundled python-build-standalone runs upstream's
   install, login and status against a temp layout on Linux.
5. Tauri shell and Svelte screens: Set up → Pair → Status/Models. Tokens synced from alpha-ds.
6. CI matrix on GitHub Actions: Windows, macOS and Ubuntu 22.04 builds, then a real-hardware smoke
   test per OS.

## References
- Upstream CLI: github.com/currentai-org/aitpotluck-local-client (`README.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `aipotluck/service/runner.py`, `aipotluck/installer/cli.py`)
- Android port precedent: `aipotluck-local-client-android` (`docs/CONFORMANCE.md`, `tools/check_upstream.sh`, `tools/conformance/`, `tools/design/sync-alpha.py`, `docs/guides/upstream-conventions.md`)
- Design system: aipotluck.org's `web/src/lib/alpha-ds/README.md`, web/src/lib/chat/design-system.md, route `/designsystem`
- Tauri sidecars: https://v2.tauri.app/develop/sidecar/
- Tauri AppImage (size, glibc baseline, no ARM cross-build): https://v2.tauri.app/distribute/appimage/
- Tauri deep linking: https://v2.tauri.app/plugin/deep-linking/
- Tauri signing: https://v2.tauri.app/distribute/sign/macos/ , https://v2.tauri.app/distribute/sign/windows/
- WebView2 distribution / Evergreen preinstalled on Win11: https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution , https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/evergreen-vs-fixed-version
- pywebview platform dependencies: https://pywebview.flowrl.com/guide/installation.html
- python-build-standalone: https://github.com/astral-sh/python-build-standalone , https://docs.astral.sh/python-build-standalone/
- BeeWare Briefcase: https://briefcase.beeware.org/
- Wails build/perf docs: https://v3.wails.io/concepts/build-system/
