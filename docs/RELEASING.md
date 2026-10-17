# Releasing

How installers get built and published. Everything here runs on GitHub-hosted runners; nothing
needs a machine of ours.

## Channels

| Channel | When | Where | Who can download |
|---|---|---|---|
| **PR builds** | every pull request | the run's **Artifacts** (kept 14 days) | repo members |
| **Nightly** | every push to `main` that changes code | the rolling **`nightly` prerelease** | anyone who can see the repo |
| **Release** | a `v<version>` tag | a **draft** release, published by a person | after Publish |

### Nightly

Every push to `main` builds all **enabled** targets. If *every* one builds, the workflow replaces the
assets of the single `nightly` prerelease and moves its `nightly` tag to that commit
(`tools/publish-nightly.sh`). If any target fails, the previous nightly stays as it was. A
half-built nightly would be worse.

Each installer appears under two names:
- **Labelled**, e.g. `aipotluck-local-client-gui_0.1.0-nightly.20261012.2cbd67a_linux-x64.deb`:
  says exactly which build it is.
- **Stable**, e.g. `aipotluck-local-client-gui_nightly_linux-x64.deb`: always the newest, so a
  link like
  `https://github.com/currentai-org/aipotluck-local-client-gui/releases/download/nightly/aipotluck-local-client-gui_nightly_linux-x64.deb`
  keeps working.

A single `SHA256SUMS` covers both. The nightly is a prerelease and never marked "latest", so it
doesn't appear as the repo's current release. Docs-only pushes (`docs/**`, `*.md`) don't trigger a
nightly.

Notes:
- While the repo is private, nightly downloads need a GitHub login with access to the repo.
- Nightlies are unsigned on macOS and Windows, like releases (see Signing).
- The version inside a nightly's app is the base version (`0.1.0`). The date and commit are in the
  file name and release title.

## What gets built

One installer set per **OS × CPU architecture**, declared in
[`.github/build-targets.json`](../.github/build-targets.json):

| Target | Enabled in CI | Runner | Installers | Priority |
|---|---|---|---|---|
| linux-x64 | ✅ | `ubuntu-22.04` | `.deb`, `.AppImage` | must |
| linux-arm64 | ✅ | `ubuntu-22.04-arm` | `.deb`, `.AppImage` | nice |
| windows-x64 | ⏸ until proven locally | `windows-2022` | `-setup.exe` (NSIS), `.msi` | must |
| macos-arm64 | ⏸ until proven locally | `macos-15` | `.dmg`, `.app.zip` | must |
| macos-x64 | ⏸ until proven locally | `macos-15` (cross-compiled) | `.dmg`, `.app.zip` | optional |

There are no CUDA or Metal builds of the GUI. The GUI contains no GPU code. The bundled CLI
downloads the right llama.cpp build (CPU, CUDA, Vulkan or ROCm; Metal is built into the macOS
asset) on the user's machine, so one binary per OS × arch covers every GPU.

A target is only allowed in the file if the bundled Python *and* upstream's newt pin both have an
asset for it (`tests/test_build_targets.py`). That's why `windows-arm64` isn't there. Linux builds
run on Ubuntu **22.04** so the binary runs on 22.04 and newer. The run summary prints each Linux
build's glibc floor.

## Turning on Windows and macOS (local first)

A disabled target costs nothing: it is never built on PRs, nightlies or tags. Prove it locally,
then flip it on.

1. **Build it on a real machine of that OS**, the same way CI will:
   ```bash
   tools/build.sh --release-target windows-x64     # from Git Bash on Windows
   tools/build.sh --release-target macos-arm64     # on the Mac
   tools/build.sh --release-target macos-x64       # on the same Mac (cross-compiles)
   ```
   This runs CI's exact steps (stage the target's runtime → `tauri build --target --bundles` →
   collect into `dist/<target>/` with checksums). Toolchain per OS: [BUILDING.md](BUILDING.md).
2. **Install the result and run it**: set up, pair, check the status screen.
3. **Optionally, try it once in CI without enabling it**: Actions → build → Run workflow, with
   `only: windows-x64`. A dispatch builds a disabled target on request, artifacts only. Nothing
   is published.
4. **Enable it**: set `"enabled": true` in `.github/build-targets.json`, and update
   `test_only_linux_is_enabled_until_windows_and_macos_are_proven_locally` in the same commit (it
   exists to make that change deliberate). The next nightly includes it.
5. Once it has been green for a while, add `Build <target>` to `main`'s required checks.

## Workflows

| Workflow | Runs on | Does |
|---|---|---|
| `check.yml` | every push to `main`, every PR | `tools/check.sh` (conformance, contract tests on the bundled Python, UI tests and type check, Rust tests) |
| `build.yml` | PRs; pushes to `main`; `v*.*.*` tags; manual dispatch | builds the enabled targets (or `only`). Then PR: artifacts; `main`: nightly prerelease; tag: draft release |

## Cutting a release

1. Bump the version in all three places. They must match, and `tools/release_version.py --check`
   fails otherwise:
   - `src-tauri/tauri.conf.json` → `"version"`
   - `src-tauri/Cargo.toml` → `[package] version` (then `cargo update -p aipotluck-local-client-gui` to refresh the lock)
   - `ui/package.json` → `"version"`
2. Commit (`chore(release): 0.2.0`), merge to `main`. That also produces a nightly.
3. Tag the merge commit and push the tag:
   ```bash
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```
   The `plan` job refuses a tag that doesn't equal `v<version>` before any build starts.
4. Wait for `build` to go green, then open **Releases → the draft**. Install at least the Linux
   `.deb` on a real machine (CLAUDE.md, tests rule 3), edit the notes, and **Publish**.

To rebuild a release's assets, re-run the failed jobs on the tag's workflow run. The release job
replaces the draft's assets instead of failing.

## Signing (not set up yet)

Builds are **unsigned** today:
- macOS: the app is ad-hoc signed (so it runs on Apple silicon) but not with a Developer ID or
  notarized. On first open from a downloaded `.dmg`, macOS says it "can't be opened because
  Apple cannot check it". Since macOS 15, right-click → Open no longer bypasses this. Use
  **System Settings → Privacy & Security → Open Anyway** (shown after the first attempt), or
  `xattr -dr com.apple.quarantine /Applications/aipotluck-local-client-gui.app`.
- Windows SmartScreen: "Windows protected your PC" → More info → Run anyway.

`build.yml` already passes these secrets to the bundler when they exist, and stays unsigned when
they don't:

| Secret | What |
|---|---|
| `APPLE_CERTIFICATE` | base64 of the Developer ID Application `.p12` |
| `APPLE_CERTIFICATE_PASSWORD` | its password |
| `APPLE_SIGNING_IDENTITY` | e.g. `Developer ID Application: Current AI (TEAMID)` |
| `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` | notarization: Apple ID, an app-specific password, team id |

Windows signing (Azure Trusted Signing or an OV/EV certificate) is configured through
`bundle.windows.signCommand` in `tauri.conf.json` plus its own secrets. Not wired yet.

## Moving the macOS jobs to the Mac mini

Set the two `macos-*` entries' `runner` in `.github/build-targets.json` to the mini's self-hosted
labels, e.g. `["self-hosted", "macOS", "ARM64"]`. The workflow itself doesn't change. Put
`macos-15` back to fall back to hosted runners.
