# Continuous integration

CI runs on GitHub Actions for `currentai-org/aipotluck-local-client-gui`. Three workflows are on
`main`, every release target is enabled, and both the nightly and tagged releases have published.
[RELEASING.md](RELEASING.md) is the reference for what each workflow does, how a release is cut and
how the download links are kept working; this page covers the settings CI depends on and what a
build costs.

## What runs, and when

| Workflow | Runs on | Does |
|---|---|---|
| `check.yml` | every push to `main`, every PR | `tools/check.sh`: conformance, contract tests on the bundled Python, UI tests and type check, Rust tests |
| `build.yml` | PRs; daily at 04:00 UTC; `v*.*.*` tags; manual dispatch | builds the five enabled targets. PR: artifacts only. Schedule: nightly prereleases, skipped when `main` hasn't moved. Tag: draft release |
| `latest-links.yml` | a full release is published; manual dispatch | follows every aipotluck.org download link and fails unless each reaches that release |

All five release targets are enabled: `linux-x64`, `linux-arm64`, `windows-x64`, `macos-arm64` and
`macos-x64`. Each was proven locally with `tools/build.sh --release-target <t>` before it was
switched on, which is the rule that keeps an unproven platform from costing anything or shipping
broken. `tests/test_build_targets.py` enforces that an enabled target has an asset from both the
bundled Python and upstream's newt pin.

A push to `main` does not build. PR builds already build every enabled target, so the merge is the
first place a change could be broken, and the nightly is what publishes.

## Cost

GitHub's standard per-minute rates, at roughly 12 minutes per target plus ~2 minutes of plan and
publish:

| Target | Rate | Per build |
|---|---|---|
| `linux-x64` | $0.006/min | $0.07 |
| `linux-arm64` | $0.005/min | $0.06 |
| `windows-x64` | $0.010/min | $0.12 |
| `macos-arm64` | $0.062/min | $0.74 |
| `macos-x64` | $0.062/min | $0.74 |

**One run that builds all five costs about $1.75**, of which the two macOS jobs are 85%. Linux
alone is $0.14.

So the nightly can reach about $52 a month if `main` moves every day, and a merged change costs
roughly $7 including ~3 PR builds. A cold Rust build on a new runner may run longer than 12
minutes, so treat these as a floor until the caches are warm. Rates change: check GitHub's current
pricing before relying on them.

Moving the two macOS jobs to the Mac mini's self-hosted runners would remove most of that cost.
[RELEASING.md](RELEASING.md) has the procedure.

## Repository settings CI depends on

**Settings → Actions → General:**

- **Actions permissions**: allow actions, either all of them or "currentai-org + selected" with:
  ```
  actions/checkout@*, actions/setup-node@*, actions/upload-artifact@*,
  actions/download-artifact@*, pnpm/action-setup@*, Swatinem/rust-cache@*,
  aws-actions/configure-aws-credentials@*
  ```
  An org-level restriction (Org → Settings → Actions) needs the same list.
- **Workflow permissions**: "Read repository contents and packages permissions". The `nightly` and
  `release` jobs request `contents: write` for themselves, which works under the read default.
- **Fork pull request workflows**: "Require approval for first-time contributors".

**Settings → Rules → Rulesets**, targeting `main`:

- require a pull request before merging;
- require the `check` and `Build <target>` checks;
- block force pushes. The rolling `nightly` tag is moved by the workflow; branch rules don't cover
  tags, so nothing here blocks it, and a tag ruleset must not cover `nightly`.

**Org → Settings → Billing → Budgets and alerts**: an Actions budget scoped to this repo, so a
runaway loop can't surprise anyone. A payment method is needed on the org: aipotluck.org's CI uses
up the free minutes.

Builds pass installers between jobs through Current AI's S3 bucket, not GitHub's artifact store,
because `currentai-org`'s artifact quota had been failing every upload. That uses an OIDC token and
a role scoped to this repo's prefixes, so there is no stored key.

## Not set up yet

- **Signing.** Builds are unsigned. macOS signing and notarization need six `APPLE_*` repo secrets;
  Windows needs `bundle.windows.signCommand` and its certificate. The workflow passes either
  through unchanged when the secrets are present. See
  [RELEASING.md § Signing](RELEASING.md#signing-not-set-up-yet).
- **Windows MSI.** Windows ships the NSIS installer only; the MSI has never been built.
- **Public repo.** aipotluck.org's nightly links work without a login today because the repo is
  private. If it goes public, self-hosted runners (the Mac mini) must be restricted to `main` and
  tags only, never PRs.

## Watching it

A red nightly leaves the previous nightly in place, so failures are otherwise quiet. Watch the
repo's Actions, or set a notification rule, so a red run reaches someone. A red `latest-links` is
more urgent than a red nightly: it means aipotluck.org's download buttons are broken right now.
Troubleshooting for each failure mode is in [RELEASING.md](RELEASING.md).
