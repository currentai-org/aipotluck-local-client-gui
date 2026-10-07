# Repository guide for coding agents

Guidance for coding agents and contributors working in this repository. `AGENTS.md` is a symlink to
this file, so Claude Code and Codex read the same text and cannot drift apart. Edit here, never
there.

Conventions are adopted from the upstream CLI (`currentai-org/aitpotluck-local-client`, its
`CLAUDE.md`) and its sibling port `aipotluck-local-client-android`. Where they differ, the CLI wins:
this app *is* the CLI with a window on it.

## Project overview

A cross-platform desktop GUI for `aitpotluck-local-client`. Two goals, in priority order:
1. **Minimal user friction.** Download, install, one click to set up, one click to pair. No
   terminal, no prerequisites, no keypresses beyond an optional paste.
2. **Behave identically to the CLI.** A device set up from this app and one set up from the CLI
   must be indistinguishable on disk, to the OS, and to aipotluck.org.

Linux (Debian/Ubuntu) is the first tested platform; macOS and Windows follow.

Read `ARCHITECTURE.md` before structural changes, `docs/CONFORMANCE.md` before touching anything
that talks to upstream, and `docs/DESIGN-SYSTEM.md` before UI work. `docs/BUILDING.md` covers the
local toolchain.

## Hard rules

- **Never re-implement the CLI. Run it.** Every action on the machine is one of upstream's own
  entry points, run with the bundled interpreter from the pinned upstream source
  (`python -m aipotluck.installer.install`, `python -m aipotluck.installer.cli login|logout`), or an
  allow-listed request to upstream's own service on `127.0.0.1:8069`. Downloading llama.cpp or
  newt, verifying checksums, writing `runtime.json`, and registering the OS service are all
  upstream's job. If the GUI needs something upstream can't do, the fix goes upstream (as a
  proposal; see below), not here.
- **The upstream pin is the submodule commit**, `upstream/aitpotluck-local-client`. llama.cpp and
  newt versions come from *that* commit's `llama_version.json`/`newt_version.json`, so they move in
  lockstep with the CLI by construction. Bump the pin only through `tools/sync_upstream.sh
  --prepare-bump` (or by hand with the same checks), never as a side effect of another change.
- **Never read, log, display, or put on argv the tunnel secret.** Pairing JSON goes to upstream via
  a 0600 file that is deleted when `login` exits. `pairing::recognise` returns the id and endpoint,
  never the secret. The clipboard is read only to recognise a pairing, and is cleared after a
  successful pair.
- **No inbound-network requirement, and no new localhost write API.** The webview reaches the
  service only through the Rust allow-list in `src-tauri/src/service.rs`.
- **Read-only upstreams.** `currentai-org/aitpotluck-local-client` and
  `currentai-org/aipotluck.org` are references. Never commit to, push to, or run a writing git
  command in their checkouts under `/opt/data/currentai/` or `/opt/data/aitpotluck-local-client`.
  The submodule here may be fetched and checked out, nothing more.
- **Do not commit third-party binaries.** The bundled Python and upstream archive are staged into
  `src-tauri/resources/runtime/` (gitignored) by `tools/stage-runtime.sh`. Fonts in
  `ui/src/design/fonts/` are the one exception (OFL).

## Branching, committing, pushing

Small project, so **short-lived branches merge straight into `main`** (a `develop` branch can come
later). Upstream's PR-to-main practice is the model.

- One branch per non-trivial change: `<type>/<short-slug>` (`feat/models-screen`,
  `fix/pair-clipboard`), or `andrewtergis/cur-NNNN-slug` when there's a ticket. A one-line doc fix
  can go straight to `main`.
- **Merge when it's demonstrated working, not merely tested.** That means:
  - `tools/check.sh` exits 0;
  - anything with a visible effect has been run in the real app, and the merge message says what
    was run and what it showed (a screenshot path, a `/status` field);
  - **a user can reach it from the UI.**
  Merge with `git merge --no-ff`.
- **Conventional commits**: `type(scope): summary`, lowercase, imperative, no trailing period.
  - Types: `feat`, `fix`, `docs`, `test`, `refactor`, `build`, `chore`.
  - Scopes: `ui`, `shell`, `runtime`, `sidecar`, `upstream`, `design`, `conformance`, `packaging`,
    `tools`, `tests`, `docs`.
  - The summary states the outcome a person would notice. The body says why, and what was verified.
- **Commit as each unit lands and its gate passes.** Don't batch unrelated changes.
- **Never push, create a remote, or open a PR without explicit approval**, scoped to that one push.
  Never force-push or delete a shared branch unless asked.

## Tests and gates: name the contract, not the behaviour

1. **A check that cannot go red is not a check.** Before trusting a new test, injure what it guards
   and watch it fail for that reason. The suite here was built that way. Each of these was injured
   once and watched to fail:
   - the probe's install check;
   - the tunnel-connected status row;
   - the sync script, which was pointed at an upstream with an injected route and subcommand.
2. **A test on a fail-open path states the contract in its name**
   (`unrelated_clipboard_text_is_never_offered_as_a_pairing`).
3. **Green tests are necessary, never sufficient, for anything they can't reach.** Two things need
   a real run on a real OS:
   - the OS service (systemd/launchd/Task Scheduler);
   - the real llama.cpp/newt download and a real pairing.
   Test those on a real machine before a release, and record what was run.
4. **Never assert on source text.** Assert on behaviour: the JSON the probe prints, the
   `runtime.json` upstream wrote, the HTTP status upstream's service returned.
5. **Tests run on the bundled interpreter** (`tools/bundled-python.sh`), never the dev machine's
   `python3`: the shipped interpreter is the one that has to work.

Gate: `tools/check.sh` runs:
- Rust unit tests;
- UI unit tests and type check;
- Python contract tests against the pinned upstream's real code;
- the conformance check (no drift, every upstream item classified).

## Runtime parameters are upstream's

Anything computed about the device (ctx size, parallel slots, KV-cache type) is upstream's
decision, surfaced via `/status` `runtime_params` with a reason string. The GUI displays those; it
never computes its own.

## Design system

The UI uses aipotluck.org's Alpha design system. `ui/src/design/tokens.css` is upstream's generated
token file **copied verbatim** by `tools/design/sync-alpha.py`. Never edit it, and never use a
literal colour, font size or radius in a component; reference a `--ds-*` token. The rules most often
broken (from `chat/design-system.md`):
- **Accent is icon or badge scale only, never a surface fill.**
- **Bordered controls rest one surface tier up from what's behind them**, never transparent.
- **Destructive looks exactly like secondary**; only its icon takes Accent 2.
- **Sharp corners by default; labels left-aligned**; DM Mono uppercase for labels and CTAs.

Re-sync with `tools/design/sync-alpha.py /opt/data/currentai/aipotluck.org`, and record the
upstream commit (written to `ui/src/design/SOURCE.json`) in the commit body.
