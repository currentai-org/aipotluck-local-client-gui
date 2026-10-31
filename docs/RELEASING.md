# Releasing

How installers get built and published. Everything here runs on GitHub-hosted runners; nothing
needs a machine of ours.

## Channels

| Channel | When | Where | Who can download |
|---|---|---|---|
| **PR builds** | every pull request | the run's **Artifacts** (kept 14 days, best effort: GitHub refuses them while the org's artifact storage is full) | repo members |
| **Nightly** | daily at 04:00 UTC, when `main` has moved | a **prerelease per nightly**, plus the rolling **`nightly` prerelease** | anyone who can see the repo |
| **Release** | a `v<version>` tag | a **draft** release, published by a person | after Publish |

### Nightly

Once a day at 04:00 UTC, `build.yml` builds `main`'s tip for all **enabled** targets. If `main`
hasn't moved since the last nightly, the run stops at `Plan` and builds nothing. Pushes to `main`
don't build: every PR already builds every enabled target before it merges. To publish a nightly
now, run **Actions → build → Run workflow** on `main` with **nightly** ticked (all targets; leave
`only` empty).

If *every* target builds, `tools/publish-nightly.sh`:
1. publishes this build as **its own prerelease**, tagged `nightly-<YYYYMMDD>.<sha>` and titled
   **"GUI v0.2.0-nightly.20261023.abc1234"** (the base version comes first, so you can see which
   official version a nightly is built on). These are kept, so the Releases page is the history;
2. updates the rolling **`nightly` prerelease** ("GUI latest nightly (v…)"): replaces its
   assets and moves its `nightly` tag to this commit.

If any target fails, nothing is published and the previous nightly stays as it was. A half-built
nightly would be worse.

Each installer appears under two names:
- **Labelled**, e.g. `aipotluck-local-client-gui_0.1.0-nightly.20261012.2cbd67a_linux-x64.deb`:
  says exactly which build it is.
- **Stable**, e.g. `aipotluck-local-client-gui_nightly_linux-x64.deb`: always the newest, so a
  link like
  `https://github.com/currentai-org/aipotluck-local-client-gui/releases/download/nightly/aipotluck-local-client-gui_nightly_linux-x64.deb`
  keeps working.

A single `SHA256SUMS` covers both. Each dated prerelease carries only its labelled names and its
own `SHA256SUMS`. Nightlies are prereleases and never marked "latest", so they don't appear as the
repo's current release. Nothing prunes old dated nightlies yet; delete them from Releases by hand if
the list gets long (`gh release delete nightly-<date>.<sha> --cleanup-tag`).

Notes:
- While the repo is private, nightly downloads need a GitHub login with access to the repo.
- Nightlies are unsigned on macOS and Windows, like releases (see Signing).
- The version inside a nightly's app is the base version (`0.2.0`). The date and commit are in the
  file name and release title.

## What gets built

One installer set per **OS × CPU architecture**, declared in
[`.github/build-targets.json`](../.github/build-targets.json):

| Target | Enabled in CI | Runner | Installers | Priority |
|---|---|---|---|---|
| linux-x64 | ✅ | `ubuntu-22.04` | `.deb`, `.AppImage` | must |
| linux-arm64 | ✅ | `ubuntu-22.04-arm` | `.deb`, `.AppImage` | nice |
| windows-x64 | ✅ | `windows-2022` | `-setup.exe` (NSIS) | must |
| macos-arm64 | ✅ | `macos-15` | `.dmg`, `.app.zip` | must |
| macos-x64 | ✅ | `macos-15` (cross-compiled) | `.dmg`, `.app.zip` | optional |

The two macOS builds are for different Macs: `macos-arm64` for Apple silicon (M1 and later),
`macos-x64` for Intel Macs only. The Intel build does run on Apple silicon, but under Rosetta, and
much slower; the app shows a banner saying so. CI checks each `.app` (`tools/check-macos-arch.sh`)
holds only its own architecture, and the release notes say which download to pick.

Windows ships the NSIS installer only. The MSI (`nsis,msi`) has never been built. Try it with one
`only: windows-x64` dispatch before adding it, since a failing MSI step would fail every nightly.

There are no CUDA or Metal builds of the GUI. The GUI contains no GPU code. The bundled CLI
downloads the right llama.cpp build (CPU, CUDA, Vulkan or ROCm; Metal is built into the macOS
asset) on the user's machine, so one binary per OS × arch covers every GPU.

A target is only allowed in the file if the bundled Python *and* upstream's newt pin both have an
asset for it (`tests/test_build_targets.py`). That's why `windows-arm64` isn't there: llama.cpp and
python-build-standalone both publish Windows ARM64 builds, but newt doesn't (x64 only, through
1.19.0), and without newt the app can't pair. Windows 11 on ARM can run the x64 installer under its
built-in x64 emulation, with llama.cpp emulated too (so slower). That path is untested. Revisit
when newt ships a `windows_arm64` binary. Linux builds
run on Ubuntu **22.04** so the binary runs on 22.04 and newer. The run summary prints each Linux
build's glibc floor.

## Turning on Windows and macOS (local first)

A disabled target is never built on PRs, nightlies or tags. Prove it locally,
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
   `test_only_targets_proven_on_a_real_machine_are_enabled` in the same commit (it exists to make
   that change deliberate). The next nightly includes it.
5. Once it has been green for a while, add `Build <target>` to `main`'s required checks.

## Workflows

| Workflow | Runs on | Does |
|---|---|---|
| `check.yml` | every push to `main`, every PR | `tools/check.sh` (conformance, contract tests on the bundled Python, UI tests and type check, Rust tests) |
| `build.yml` | PRs; daily at 04:00 UTC; `v*.*.*` tags; manual dispatch | builds the enabled targets (or `only`). Then PR: artifacts; schedule (or dispatch with `nightly`): nightly prereleases; tag: draft release titled "GUI vX.Y.Z" |
| `latest-links.yml` | a full release is published; manual dispatch with a tag | follows every aipotluck.org download link (`releases/latest/download/<fixed name>`) and fails unless each reaches that release |

## Cutting a release

`tools/release.sh` does it in two steps, because `main` only takes changes through a PR:

1. **Prepare**, on an up-to-date `main` with a clean tree:
   ```bash
   tools/release.sh prepare 0.2.0 --push
   ```
   This creates the branch `release/v0.2.0`. It sets the version in `src-tauri/tauri.conf.json`,
   `src-tauri/Cargo.toml` (and the app's entry in `Cargo.lock`) and `ui/package.json`, then commits
   `chore(release): 0.2.0`. `--push` pushes the branch; without it, push it yourself. Open a PR
   into `main` and merge it.
2. **Tag**, back on `main` after pulling the merge:
   ```bash
   git checkout main && git pull
   tools/release.sh tag 0.2.0
   ```
   It checks everything first and creates nothing if any check fails:
   - the tree is clean and `HEAD` is exactly `origin/main`;
   - all three files say `0.2.0`;
   - `v0.2.0` exists neither locally nor on origin;
   - the pinned CLI commit is on the CLI's `main`, so a release never ships a CLI that only exists
     on a feature branch.

   It then asks before creating and pushing the annotated tag (`--yes` skips the question).
3. **The tag builds the release.** `build.yml` builds every enabled target and creates a **draft**
   release with the installers (each under its versioned name *and* its fixed name, see below), one
   `SHA256SUMS`, and notes GitHub generates from the PRs merged since the last release. The `plan`
   job also refuses a tag that doesn't equal `v<version>`, and no draft is created if a fixed name
   would be missing.
4. **Review and publish.** When `build` is green, open **Releases → the draft**. Install at least
   one build on a real machine (CLAUDE.md, tests rule 3), edit the notes if needed, and click
   **Publish** with **"Set as the latest release"** ticked (the default for a full release).
   Publishing moves every GUI download link on aipotluck.org to this release.
5. **Check the `latest-links` run.** Publishing starts `latest-links.yml`, which follows each of
   aipotluck.org's download links. Green: the site now serves this release. Red: see "Fixed latest
   download links" below; the site's download buttons are broken until it's fixed.

A pre-release works the same way (`tools/release.sh prepare 0.2.0-rc.1`). Tick "Set as a
pre-release" on the draft before publishing.

To rebuild a release's assets, re-run the failed jobs on the tag's workflow run. The release job
replaces the draft's assets instead of failing.

## Fixed latest download links

aipotluck.org's **Settings → Local inference** page offers the app's installers without naming a
version. It links

```
https://github.com/currentai-org/aipotluck-local-client-gui/releases/latest/download/<fixed name>
```

GitHub redirects that to the file of the same name in whichever release is marked **Latest** (never
a draft or a prerelease, so never a nightly). Publishing a release therefore updates the site with
no change, commit or deploy on the aipotluck.org side.

For that to work, every release carries each installer twice: under its versioned name
(`aipotluck-local-client-gui_0.2.0_linux-x64.deb`) and under a **fixed name**
(`aipotluck-local-client-gui_linux-x64.deb`). The fixed names are the contract with the site, and
they live in one file: **[`.github/latest-download-names.txt`](../.github/latest-download-names.txt)**.

Three things hold that contract, each failing with a message that points here:

| When | What | Fails if |
|---|---|---|
| every PR (`tools/check.sh`) | `tests/test_latest_links.py` | the list isn't exactly what the enabled targets in `build-targets.json` build |
| building the draft (`build.yml`, `release` job) | `tools/stage-release.sh` adds the fixed-name copies | a listed name wasn't built, so no draft is created |
| on Publish (`latest-links.yml`) | `tools/check-latest-links.sh <tag>` follows every link | a link reaches another release, or 404s |

On the site's side the names are in `DOWNLOADS`, in
`web/src/routes/chat/settings/(nav)/local-inference/+page.svelte` in `currentai-org/aipotluck.org`
(its `docs/guides/local-client-downloads.md` points back here).

### If `latest-links` fails

The run's log lists every bad link and its cause. Until it's fixed, the site's download buttons
for those files 404 or serve an older release.

- **"Latest is not vX.Y.Z"**: another release is marked Latest, usually because "Set as the latest
  release" was unticked on Publish, or an older release was re-marked later. Fix:
  ```bash
  gh release edit vX.Y.Z --repo currentai-org/aipotluck-local-client-gui --latest
  ```
  If the other release *should* be Latest, nothing is broken: re-run the check for that tag instead.
- **"vX.Y.Z has no such file"**: the release lacks a fixed-name copy (published by hand, or files
  deleted). Fix: upload the copies. From the release's own assets:
  ```bash
  V=X.Y.Z; R=currentai-org/aipotluck-local-client-gui; mkdir -p /tmp/fix && cd /tmp/fix
  gh release download "v$V" --repo "$R" --pattern "aipotluck-local-client-gui_${V}_*"
  for f in aipotluck-local-client-gui_${V}_*; do mv "$f" "${f/_${V}_/_}"; done
  gh release upload "v$V" --repo "$R" aipotluck-local-client-gui_*
  ```
  (The release's `SHA256SUMS` then doesn't list the fixed names; that's cosmetic, the bytes are the
  same as the versioned files it does list.)

Then re-run the check: **Actions → latest-links → Run workflow**, with the tag. Green means the
site is serving that release.

### Changing the list

Add, remove or rename a fixed name only together with the site, and in an order that never leaves
a site link pointing at a file that doesn't exist:

- **Adding a download** (a new target or format):
  1. here: enable/add it in `build-targets.json` and add its fixed name to
     `latest-download-names.txt` in the same PR (`test_latest_links.py` enforces that they match);
  2. publish a release that contains it, and check `latest-links` is green;
  3. aipotluck.org: add it to `DOWNLOADS`.
- **Removing a download**:
  1. aipotluck.org: remove it from `DOWNLOADS` and deploy;
  2. here: remove it from `build-targets.json` and the list in one PR;
  3. the next release stops carrying it.
- **Renaming** is a remove plus an add, in that combined order: add the new name, release, switch
  the site, then drop the old name.

If aipotluck.org wants a change (say, to stop offering `.app.zip`), it starts with a PR here that
changes this list and the build together, so the contract changes in one reviewed place.

### First rollout (v0.2.0)

v0.2.0 was published before fixed names existed, so it has none, and the site's `latest` links
404 until it gets them. Before aipotluck.org switches to these links, either cut the next release
(it will carry them) or backfill v0.2.0 with the commands under "has no such file" above, then run
`latest-links` for `v0.2.0` and wait for green.

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
