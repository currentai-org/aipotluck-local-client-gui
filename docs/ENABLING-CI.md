# Turning on build automation on github.com

The step-by-step plan for enabling `.github/workflows/build.yml` and `check.yml` in
`currentai-org/aipotluck-local-client-gui`. Every step needs a person with admin rights on the repo
(and, for step 0, on the org). None of it has been done. The workflows exist only on the branch
`build/release-workflow`.

**Phase 1 (this plan): Linux only.** linux-x64 and linux-arm64 build on every PR. Every push to
`main` publishes a **nightly** prerelease. A `v*` tag makes a draft release. (macOS has since been enabled, see Cost below.) Windows and macOS were
declared but disabled, so they cost nothing until you've proven them locally (phase 2, at the end).

Expected time: about 1 hour of clicking, plus watching one ~20-minute first build.

## Cost, Linux-only phase

Computed from GitHub's standard per-minute rates (Linux x64 $0.006, arm64 $0.005), assuming ~12 min
per target build plus ~2 min of plan and publish:

| | Linux only (phase 1) | All five targets (for comparison) |
|---|---|---|
| One push to `main` (build + nightly publish) | **$0.14** | $1.75 |
| 60 pushes to `main` / month | **$8.64** | $105.12 |
| 150 pushes / month | **$21.60** | $262.80 |
| One merged change incl. ~3 PR builds | $0.58 | $7.01 |

The jump to "all five" is almost entirely the two macOS jobs ($0.062/min).

**macOS is now enabled** (macos-arm64 and macos-x64 on GitHub's `macos-15` runners, both proven on
the Mac mini first). With Linux + macOS, each PR build and each push to `main` costs about
**$1.63** (Linux $0.14 + two macOS jobs at ~12 min × $0.062 = $1.49): about $98/month at 60
pushes, $244 at 150, and roughly $6.50 per merged change including ~3 PR builds. Raise the Actions
budget from step 0 accordingly.

**Windows is now enabled too** (windows-x64 on `windows-2022`, NSIS installer only; proven on a
Windows 10 PC first). At the same assumptions as above, ~12 min at Windows' $0.010/min, it adds
about **$0.12** per build, so each PR build and push to `main` costs about **$1.75**: roughly $105
a month at 60 pushes and $263 at 150. Check the per-minute rate against GitHub's current pricing;
a cold Windows Rust build may also run longer than 12 minutes until the cache is warm. A nightly on *every* push was the expensive part; nightlies now build once a day (04:00 UTC),
and only when `main` has moved (docs/RELEASING.md).

## 0. Before you start (5 min)

- [ ] Confirm the repo's visibility. Private is fine. Nothing here uses self-hosted runners.
- [ ] Org → Settings → Billing → **Budgets and alerts**: create an Actions budget scoped to this
      repo (e.g. $25/month with an alert at 80%) so a runaway loop can't surprise anyone.
- [ ] Confirm a payment method is on the org. aipotluck.org's CI already uses up the free minutes,
      so without one this repo's jobs will queue and then fail on quota.

## 1. Push the branch and open a PR (5 min)

- [ ] `git push -u origin build/release-workflow`. Push it yourself, or give me an explicit yes;
      by repo rule I won't push otherwise.
- [ ] Open a PR into `main`. That first runs `check` and `build` (Linux only, artifacts only:
      PRs never publish).

## 2. Repository Actions settings (10 min)

**Repo → Settings → Actions → General**:

- [ ] **Actions permissions**: allow actions, either all of them or "currentai-org + selected" with
      this allow-list:
      ```
      actions/checkout@*, actions/setup-node@*, actions/upload-artifact@*,
      actions/download-artifact@*, pnpm/action-setup@*, Swatinem/rust-cache@*,
      aws-actions/configure-aws-credentials@*
      ```
      If the org restricts actions (Org → Settings → Actions), an org owner adds the same list there.
- [ ] **Workflow permissions**: keep **"Read repository contents and packages permissions"**. The
      `nightly` and `release` jobs request `contents: write` for themselves, which works under the
      read default; nothing else gets write.
- [ ] **Fork pull request workflows**: keep "Require approval for first-time contributors".

## 3. Watch the first PR run (~20 min)

- [ ] `check / tools/check.sh`: green (the same gate as running `tools/check.sh` locally).
- [ ] `build / Plan`: prints a two-target matrix (`linux-x64`, `linux-arm64`), version `0.1.0`,
      channel `none`.
- [ ] `build / Build linux-x64` and `Build linux-arm64`: green. Each run summary shows
      **requires GLIBC_2.35** (or lower).
- [ ] **No** `Publish nightly` job runs. That's correct for a PR.
- [ ] Download `installers-linux-x64` from the run's Artifacts and install it on your x86 laptop:
      `sudo apt install ./aipotluck-local-client-gui_0.1.0-nightly.*_linux-x64.deb`. Then Set up →
      Pair → check the status screen. This is CLAUDE.md's real-machine check for anything visible.

## 4. Protect `main` (5 min)

**Settings → Rules → Rulesets → New branch ruleset**, target `main`:

- [ ] Require a pull request before merging.
- [ ] Require status checks: `tools/check.sh`, `Build linux-x64`. Leave `Build linux-arm64`
      optional for a week.
- [ ] Block force pushes. The `nightly` *tag* is moved by the workflow, but branch rules don't
      cover tags, so nothing here blocks it. Don't add a tag ruleset that covers `nightly`.
- [ ] Merge the PR with **"Create a merge commit"** (CLAUDE.md asks for `--no-ff`).

## 5. Watch the first nightly (the next 04:00 UTC run, or start one by hand)

Nightlies are scheduled (04:00 UTC). To see one now: Actions → build → Run workflow on `main`
with **nightly** ticked. Either way `build` runs with channel `nightly`:

- [ ] `Publish nightly` runs after both Linux builds pass.
- [ ] **Releases** now shows **"Nightly build (0.1.0-nightly.YYYYMMDD.<sha>)"**, marked
      **Pre-release**, *not* "Latest". It contains:
  - `aipotluck-local-client-gui_0.1.0-nightly.<date>.<sha>_linux-x64.deb` / `.AppImage`, and the
    same for `linux-arm64`;
  - `aipotluck-local-client-gui_nightly_linux-x64.deb` / `.AppImage`, and the same for
    `linux-arm64`: the stable "latest nightly" names;
  - `SHA256SUMS`.
- [ ] The **`nightly` tag** points at the merge commit (Code → Tags).
- [ ] Download via the stable link while signed in to GitHub:
      `https://github.com/currentai-org/aipotluck-local-client-gui/releases/download/nightly/aipotluck-local-client-gui_nightly_linux-x64.deb`.
      Check `sha256sum` against `SHA256SUMS`.
- [ ] Push a trivial code change to `main` (through a PR). After it builds, the release title and
      assets show the *new* commit, and nothing from the previous nightly remains.

## 6. First tagged release (optional now, 15 min)

- [ ] `git tag -a v0.1.0 -m v0.1.0 && git push origin v0.1.0`.
- [ ] A **draft** "aipotluck-local-client-gui 0.1.0" appears with the Linux installers and
      `SHA256SUMS`. Install, write notes, **Publish**. This becomes the repo's "Latest" release;
      the nightly never does.

## 7. Housekeeping (5 min)

- [ ] **Settings → Code security**: enable **Dependabot version updates**.
      `.github/dependabot.yml` asks for monthly grouped bumps of the SHA-pinned actions.
- [ ] Watch the repo's Actions (or set a notification rule) so a red nightly reaches you. A red
      nightly leaves the previous nightly in place, so failures are quiet otherwise.

---

## Phase 2: turning on Windows and macOS

Do this per OS when you have the machine in front of you. Full detail is in
[RELEASING.md § Turning on Windows and macOS](RELEASING.md).

1. On the Windows PC (Git Bash) or the Mac:
   - one-time toolchain setup from `docs/BUILDING.md` (Rust, Node and pnpm; on Windows the VS Build
     Tools C++ workload; on macOS the Xcode Command Line Tools);
   - then `tools/build.sh --release-target windows-x64`, `macos-arm64` or `macos-x64`.
2. Install the installer from `dist/<target>/`, then Set up → Pair on that machine.
3. Optional: one CI trial with Actions → build → **Run workflow** → `only: windows-x64`. This is
   artifacts only, never published. About $0.12 for Windows, $0.74 per macOS target.
4. Set `"enabled": true` for that target in `.github/build-targets.json`, and update the
   `only_linux_is_enabled…` test in the same commit. From the next push, nightlies include it.
5. **Before enabling macOS, decide the nightly cadence.** Per-push nightlies with macOS on cost
   about $1.75 per push, against $0.14 Linux-only. Either:
   - point the macOS targets' `runner` at the Mac mini's self-hosted labels; or
   - change the nightly trigger to a daily `schedule:`.

   I can make either change when you're ready.

## Later

| When | What |
|---|---|
| Apple Developer ID exists | add the six `APPLE_*` repo secrets. The workflow already passes them through and signs and notarizes when present ([RELEASING.md § Signing](RELEASING.md)) |
| Windows certificate exists | add `bundle.windows.signCommand` + its secrets |
| The repo goes public | nightly links work without a login, and self-hosted runners (the Mac mini) must then be restricted to `main`/tags only, never PRs |

## If something goes wrong

- **A nightly failed part-way:** the previous nightly is untouched. Fix it, and the next push to
  `main` publishes. Or re-run the failed jobs on the same run.
- **A tag build failed:** fix it, then re-run the failed jobs on the tag's run. The release job
  replaces the draft's assets.
- **The wrong thing got tagged:** delete the draft release and the tag
  (`git push origin :refs/tags/v0.1.0`). Nothing was public.
- **To pause nightlies without touching code:** Actions → build → ⋯ → **Disable workflow**. This
  also stops PR builds. Re-enable when done.
