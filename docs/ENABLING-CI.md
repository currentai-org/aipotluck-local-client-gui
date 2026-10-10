# Turning on build automation on github.com

The step-by-step plan for enabling `.github/workflows/build.yml` and `check.yml` in
`currentai-org/aipotluck-local-client-gui`. Everything here needs a person with admin rights on the
repo (and, for step 2, on the org). None of it has been done yet. The workflows exist only on the
local branch `build/release-workflow`.

Expected time: about 1 hour of clicking, plus one ~30-minute first build to watch.

## 0. Before you start (5 min)

- [ ] Confirm the repo's visibility is **private**. Nothing here needs self-hosted runners, so
      public would also be safe. Revisit only if a Mac mini runner is added later.
- [ ] Check the org's Actions billing (Settings → Billing → Actions):
  - the build matrix uses only **standard** runners, which need no plan upgrade;
  - a full five-target build costs about **$1.74**, about 85% of that from the two macOS jobs;
  - with no spending limit/payment method, private-repo minutes stop at the free quota. That quota
    is already being exceeded by aipotluck.org's CI (CUR-1534 billing notes), so confirm a payment
    method is on file, or set an Actions budget for this repo.

## 1. Push the branch and open a PR (5 min)

- [ ] `git push -u origin build/release-workflow` from your checkout. Or approve me to push it;
      by repo rule, I won't push without an explicit yes.
- [ ] Open a PR into `main`. Opening it is what first runs the workflows: `check` and `build` both
      trigger on `pull_request`.

## 2. Repository / org Actions settings (10 min)

At **github.com/currentai-org/aipotluck-local-client-gui → Settings → Actions → General**:

- [ ] **Actions permissions**: allow actions, and either:
  - "Allow all actions", or
  - "Allow currentai-org and select non-currentai-org actions", with this allow-list:
    ```
    actions/checkout@*, actions/setup-node@*, actions/upload-artifact@*, actions/download-artifact@*,
    pnpm/action-setup@*, Swatinem/rust-cache@*
    ```
  If the org policy is stricter (Org → Settings → Actions), an org owner adds the same list there.
- [ ] **Workflow permissions**: leave the default "Read repository contents". The release job asks
      for `contents: write` itself, scoped to that one job.
- [ ] **Fork pull request workflows**: leave "Require approval for first-time contributors" (or
      stricter).
- [ ] **Artifact and log retention**: the default (90 days) is fine. Installers set their own
      14-day retention.

## 3. Watch the first run on the PR (30–40 min, mostly waiting)

On the PR's **Checks** tab:

- [ ] `check / tools/check.sh`: green. This is the same gate as running `tools/check.sh` locally.
- [ ] `build / Plan`: prints the five-target matrix and `0.1.0`.
- [ ] `build / Build <target>` ×5. Expected first-run surprises, in order of likelihood:
  - **windows-x64**: it is the first Windows build this code has ever had. The Rust compiles
    (`#[cfg(windows)]` paths were type-checked from Linux), but the bundler, NSIS/WiX and the
    Git-Bash staging script have not run on Windows before. If it fails, re-run with
    `workflow_dispatch` + `only: windows-x64` while iterating.
  - **macos-x64**: cross-compiles from the arm64 runner. If it fails, drop it from
    `.github/build-targets.json` (it's "optional") rather than block the rest.
  - **linux-arm64**: runs on the standard `ubuntu-22.04-arm` runner, available to private repos
    since 2026-01-29 and billed as standard minutes. If it sits queued anyway, remove the target
    for now (it's "nice", not "must").
- [ ] On each Linux job, the run summary shows **requires GLIBC_2.35 or lower**. Higher means
      something pulled in a newer dependency.
- [ ] Download `installers-linux-x64` from the run's **Artifacts**. Install the `.deb` on your x86
      laptop: `sudo apt install ./aipotluck-local-client-gui_0.1.0_linux-x64.deb`, then Set up →
      Pair. This is the real-machine check CLAUDE.md requires before merging anything with a
      visible effect.

## 4. Make the gates required (5 min)

**Settings → Branches → Add branch ruleset** (or a classic protection rule) for `main`:

- [ ] Require a pull request before merging.
- [ ] Require status checks to pass, and add:
  - `tools/check.sh`
  - `Build linux-x64`, `Build windows-x64`, `Build macos-arm64` (the three "must" targets)

  Leave `linux-arm64` and `macos-x64` as non-required until they've been green for a while.
- [ ] Block force pushes and deletion. This matches the repo rule "never force-push a shared
      branch".
- [ ] Merge the PR (CLAUDE.md asks for `--no-ff`; in the UI choose "Create a merge commit").

## 5. Cut the first release (15 min)

- [ ] On `main`: `git tag -a v0.1.0 -m "v0.1.0" && git push origin v0.1.0`. The version is already
      `0.1.0` in all three files.
- [ ] **Actions → build** runs on the tag; the `plan` job checks the tag equals `v0.1.0`.
- [ ] When green: **Releases** shows a **draft** "aipotluck-local-client-gui 0.1.0". It holds about
      11 installers plus `SHA256SUMS`.
- [ ] Download one installer per must-ship OS you can reach and run it. At minimum the Linux one.
- [ ] Edit the notes. **Say plainly that the macOS and Windows builds are unsigned** and how to get
      past Gatekeeper and SmartScreen. Then **Publish**.

## 6. Housekeeping (5 min)

- [ ] **Settings → Code security**: enable Dependabot version updates. `.github/dependabot.yml`
      already asks for monthly grouped bumps of the SHA-pinned actions.
- [ ] Optional: **Settings → Notifications** or a watch on the repo's Actions, so a red nightly or
      release reaches you.

## Later (not needed for unsigned builds)

| When | What | Where |
|---|---|---|
| Apple Developer ID exists | add the six `APPLE_*` secrets (Settings → Secrets and variables → Actions). The workflow already passes them through and signs and notarizes when they're present | docs/RELEASING.md § Signing |
| Windows certificate exists | add `bundle.windows.signCommand` + its secrets | docs/RELEASING.md § Signing |
| Mac mini online | register it as a runner on this repo only, then point the two `macos-*` targets' `runner` at its labels in `.github/build-targets.json` | docs/RELEASING.md § Mac mini |
| You want nightly builds | add `schedule: - cron: '0 10 * * *'` to `build.yml`'s `on:`, about $52/month | `.github/workflows/build.yml` |

## If something goes wrong

- **A tag build fails partway:** fix it, then re-run the failed jobs on the same tag's run. The
  release job replaces the draft's assets rather than failing on "already exists".
- **The wrong thing got tagged:** delete the draft release and the tag
  (`git push origin :refs/tags/v0.1.0`). Nothing was public, because releases start as drafts.
- **Everything on one OS is red after a runner image update:** pin that target's `runner` to the
  previous image label in `.github/build-targets.json` while investigating.
