# Releasing

How installers get built, and how a release gets published. Everything here runs on GitHub-hosted
runners; nothing needs a machine of ours.

## What gets built

One installer set per **OS × CPU architecture**, declared in [`.github/build-targets.json`](../.github/build-targets.json):

| Target | Runner | Installers | Priority |
|---|---|---|---|
| linux-x64 | `ubuntu-22.04` | `.deb`, `.AppImage` | must |
| linux-arm64 | `ubuntu-22.04-arm` | `.deb`, `.AppImage` | nice |
| windows-x64 | `windows-2022` | `-setup.exe` (NSIS), `.msi` | must |
| macos-arm64 | `macos-15` | `.dmg`, `.app.zip` | must |
| macos-x64 | `macos-15` (cross-compiled) | `.dmg`, `.app.zip` | optional |

There are no CUDA or Metal builds of the GUI. The GUI contains no GPU code. The bundled CLI picks and
downloads the right llama.cpp build (CPU / CUDA / Vulkan / ROCm; Metal is built into the macOS asset)
on the user's machine. So one binary per OS × arch covers every GPU.

A target is only allowed in the matrix if the bundled Python *and* upstream's newt pin both have an
asset for it. `tests/test_build_targets.py` enforces that. It is why `windows-arm64` isn't there,
even though llama.cpp ships for it.

Linux builds run on Ubuntu **22.04** so the binary runs on 22.04 and newer. A Linux binary needs the
build host's glibc or newer. The build log's summary prints the glibc floor of each Linux build.

## Workflows

| Workflow | Runs on | Does |
|---|---|---|
| `check.yml` | every push to `main`, every PR | `tools/check.sh` (conformance, contract tests on the bundled Python, UI tests and type check, Rust tests) |
| `build.yml` | every PR; manual dispatch; tag `v*.*.*` | builds all five targets. On a PR or a dispatch: installers as workflow artifacts (14 days). On a tag: also a **draft** GitHub Release with every installer and a combined `SHA256SUMS` |

The release is a draft on purpose: nothing is downloadable until a person reviews it and clicks
Publish.

## Cutting a release

1. Bump the version in all three places. They must match, and `tools/release_version.py --check`
   fails otherwise:
   - `src-tauri/tauri.conf.json` → `"version"`
   - `src-tauri/Cargo.toml` → `[package] version` (then `cargo update -p aipotluck-local-client-gui` to refresh the lock)
   - `ui/package.json` → `"version"`
2. Commit (`chore(release): 0.2.0`), merge to `main`.
3. Tag the merge commit and push the tag:
   ```bash
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```
   The `plan` job refuses a tag that doesn't equal `v<version>` before any build starts.
4. Wait for `build` to go green, then open **Releases → the draft**. Install at least the Linux
   `.deb` on a real machine (CLAUDE.md, tests rule 3), edit the notes, and **Publish**.

To rebuild a release's assets (say, after fixing a flaky runner), re-run the failed jobs on the tag's
workflow run. The release job replaces the draft's assets instead of failing.

## Building one target by hand

**Actions → build → Run workflow**, set `only` to e.g. `windows-x64`. The installers appear as an
artifact on the run. Locally, `tools/build.sh` builds the host target, and
`tools/collect-bundles.sh <target>` names the output the same way CI does.

## Signing (not set up yet)

Builds are **unsigned** today:
- macOS shows "can't be opened because Apple cannot check it"; users must right-click → Open.
- Windows SmartScreen shows "Windows protected your PC" → More info → Run anyway.

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

Change the two `macos-*` entries' `runner` in `.github/build-targets.json` from `macos-15` to the
mini's self-hosted labels (e.g. `["self-hosted", "macOS", "ARM64"]`; the field accepts a JSON
array). The workflow itself doesn't change. Put `macos-15` back to fall back to hosted runners.
