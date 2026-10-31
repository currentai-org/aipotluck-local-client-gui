# Staying in step with aipotluck-local-client

This app runs the upstream CLI's own code, so "staying in sync" isn't porting changes. It means
noticing when upstream moves, proving the GUI still works against the new commit, then bumping the
pin. The failure that matters is upstream gaining something (a route, a flag, a pairing rule) and
nobody noticing.

## The pieces

| | Runs | Needs | Answers |
|---|---|---|---|
| `tools/check.sh` | every change (the merge gate) | this repo only | Does the GUI still match the upstream commit it pins? |
| `tools/sync_upstream.sh` | on demand, and daily by schedule | network (git fetch) | Has upstream moved, and is the GUI compatible with the new commit? |

The script can *prepare* a bump (`--prepare-bump` makes a local `chore/upstream-bump-<sha>`
branch). The gate *holds* the code to whatever is pinned. Nothing is ever pushed automatically.

## What `sync_upstream.sh` does against a candidate commit

1. **Interface surface.** `tools/conformance/extract_surface.py` reads upstream's source with
   `ast` and records these declarations:
   - every CLI subcommand and flag, and every installer flag;
   - the service's HTTP routes per method;
   - the JSON keys of its responses;
   - API error codes and job states;
   - `runtime.json` keys read;
   - newt's argv and health constants;
   - pinned binary versions, platform assets, and placeholder checksums;
   - the upstream internals the GUI calls (layout, service manager, log format).

   `check_coverage.py` then diffs the extraction against `conformance/upstream-surface.json` and
   requires every leaf to be classified in `conformance/coverage.json`.
2. **Upstream's own test suite**, run on the Python the app bundles. This proves the shipped
   interpreter runs that commit.
3. **GUI contract tests** (`tests/`) against the candidate's real code:
   - its real service payload, started with the argv the GUI uses;
   - its real `cli logout` / `login` parsing;
   - the probe reading its real layout.

Exit codes: `0` compatible or in sync, `1` drift / undecided / test failure, `2` couldn't run.
Exit 2 is a tooling problem and is reported as one, never as "upstream deleted everything".

## Coverage statuses

| Status | Meaning here |
|---|---|
| `implemented` | Reachable from the UI, **or** delegated to upstream's unchanged code (llama.cpp/newt handling, `runtime.json`), so it matches by construction. Any change still appears as drift. |
| `partial` | Exists but deliberately differs; the note says how. |
| `not_applicable` | An advanced CLI option the GUI deliberately doesn't expose, with the reason. |
| `todo` | Not reachable from the UI yet. The list is the GUI's backlog against the CLI. |

A group rule (`tunnel.*`) also covers anything new beneath it. `check_coverage.py` prints what each
wildcard absorbs, so check that list whenever you accept a baseline.

## Proven to go red

`sync_upstream.sh` was pointed at a scratch upstream with a new `GET /pair` route and a new
`update` subcommand injected. It reported 3 added and 3 undecided items and exited 1, while
upstream's 608 tests and the 7 contract tests stayed green. That shows each layer reports its own
failure and not the others'.

## Daily watchdog

A daily cron job runs `tools/upstream_watchdog.sh`:
- it prints nothing when in sync, so nothing is delivered;
- when upstream has moved, it delivers the report plus the next steps;
- it always exits 0, so a delivered warning is not also a failed job.

The same script works as a GitHub Actions `schedule:` job once CI exists.

## Bumping

```bash
tools/sync_upstream.sh                 # see what's new and whether it's compatible
# classify new items in conformance/coverage.json; implement or excuse each
tools/sync_upstream.sh --prepare-bump  # local branch with the submodule + baseline bumped
git checkout chore/upstream-bump-<sha>
tools/build.sh --debug                 # then smoke-test the real app on a real machine
git checkout main && git merge --no-ff chore/upstream-bump-<sha>
```
