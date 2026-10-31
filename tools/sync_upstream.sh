#!/usr/bin/env bash
# "Has aipotluck-local-client moved ahead of the commit this GUI ships, and does it matter?"
#
#   tools/sync_upstream.sh                 fetch upstream, test the GUI against its newest main, report
#   tools/sync_upstream.sh --ref <ref>     test against a specific branch/tag/sha instead of origin/main
#   tools/sync_upstream.sh --offline       skip the fetch (use what's already fetched)
#   tools/sync_upstream.sh --prepare-bump  if everything is green, commit a local
#                                          chore/upstream-bump-<sha> branch (never pushed)
#   tools/sync_upstream.sh --quiet         print nothing when in sync (for the scheduled watchdog)
#
# Exit codes: 0 in sync (or a candidate that passes everything), 1 drift/undecided/test failure,
# 2 could not run (fetch failed, upstream unreadable). Only exit 2 is a tooling problem.
#
# Writes only: the submodule's .git (fetch), a scratch git worktree under build/sync/, and -- with
# --prepare-bump -- a local branch in this repo. Never pushes, never touches the working tree.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUB="$ROOT/upstream/aipotluck-local-client"
WORK="$ROOT/build/sync"
REF="origin/main"
OFFLINE=0 PREPARE=0 QUIET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF="${2:?}"; shift 2 ;;
    --offline) OFFLINE=1; shift ;;
    --prepare-bump) PREPARE=1; shift ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

REPORT="$(mktemp)"; trap 'rm -f "$REPORT"' EXIT
say() { echo "$@" >> "$REPORT"; }
finish() { # $1 = exit code
  if [ "$1" -ne 0 ] || [ "$QUIET" -eq 0 ]; then cat "$REPORT"; fi
  exit "$1"
}

[ -d "$SUB/.git" ] || [ -f "$SUB/.git" ] || { echo "upstream submodule not initialised: git submodule update --init" >&2; exit 2; }

if [ "$OFFLINE" -eq 0 ]; then
  git -C "$SUB" fetch --quiet origin 2>"$WORK.fetch.err" || {
    mkdir -p "$WORK"; echo "could not fetch upstream: $(cat "$WORK.fetch.err" 2>/dev/null)" >&2; exit 2; }
fi
PINNED="$(git -C "$ROOT" ls-tree HEAD upstream/aipotluck-local-client | awk '{print $3}')"
[ -n "$PINNED" ] || PINNED="$(git -C "$SUB" rev-parse HEAD)"
CANDIDATE="$(git -C "$SUB" rev-parse --verify --quiet "$REF^{commit}")" || { echo "unknown upstream ref: $REF" >&2; exit 2; }

say "aipotluck-local-client: pinned ${PINNED:0:9}, candidate $REF = ${CANDIDATE:0:9}"
if [ "$PINNED" = "$CANDIDATE" ]; then
  say "In sync -- nothing new upstream."
  finish 0
fi

say ""
say "New upstream commits ($(git -C "$SUB" rev-list --count "$PINNED..$CANDIDATE")):"
git -C "$SUB" log --oneline --no-decorate "$PINNED..$CANDIDATE" | sed 's/^/  /' >> "$REPORT"

# ------------------------------------------------------------- scratch checkout of the candidate
mkdir -p "$WORK"
CAND_DIR="$WORK/upstream-$CANDIDATE"
if [ ! -d "$CAND_DIR" ]; then
  git -C "$SUB" worktree prune
  git -C "$SUB" worktree add --quiet --detach "$CAND_DIR" "$CANDIDATE" || { echo "worktree failed" >&2; exit 2; }
fi

FAIL=0
# 1. interface surface: drift + every item classified
python3 "$ROOT/tools/conformance/extract_surface.py" "$CAND_DIR" --out "$WORK/candidate-surface.json" 2>/dev/null
say ""
say "== Interface surface =="
( cd "$ROOT" && python3 tools/conformance/check_coverage.py --surface "$WORK/candidate-surface.json" --quiet ) >> "$REPORT" 2>&1
rc=$?
[ $rc -eq 2 ] && { cat "$REPORT"; exit 2; }
[ $rc -ne 0 ] && FAIL=1

# 2. upstream's own test suite, on the interpreter the GUI ships, + 3. our contract tests against
#    the candidate's real service.
PY="$("$ROOT/tools/bundled-python.sh")" || { say "could not prepare the bundled python"; finish 2; }
say ""
say "== Upstream's own tests on the bundled Python ($("$PY" -V 2>&1)) =="
if "$PY" -c 'import pytest' 2>/dev/null; then
  OUT="$(cd "$CAND_DIR" && "$PY" -m pytest -q -p no:cacheprovider 2>&1)" || FAIL=1
  echo "$OUT" | tail -3 | sed 's/^/  /' >> "$REPORT"
else
  say "  (skipped: pytest not available to the bundled python -- run tools/bundled-python.sh --with-pytest)"
fi
say ""
say "== GUI contract tests against the candidate =="
OUT="$(cd "$ROOT" && AIPOTLUCK_UPSTREAM_DIR="$CAND_DIR" "$PY" -m pytest -q -p no:cacheprovider tests 2>&1)" || FAIL=1
echo "$OUT" | tail -3 | sed 's/^/  /' >> "$REPORT"

say ""
if [ "$FAIL" -ne 0 ]; then
  say "RESULT: upstream ${CANDIDATE:0:9} is NOT yet compatible with this GUI -- see above."
  say "Next: classify new items in conformance/coverage.json (implement or excuse each), fix any"
  say "failing contract test, then: tools/sync_upstream.sh --ref ${CANDIDATE:0:9} --prepare-bump"
  finish 1
fi

say "RESULT: upstream ${CANDIDATE:0:9} passes every check."
if [ "$PREPARE" -eq 1 ]; then
  BR="chore/upstream-bump-${CANDIDATE:0:9}"
  if git -C "$ROOT" rev-parse --verify --quiet "refs/heads/$BR" >/dev/null; then
    say "Branch $BR already exists; leaving it."
  else
    BUMP="$WORK/bump-wt"
    rm -rf "$BUMP"; git -C "$ROOT" worktree prune
    git -C "$ROOT" worktree add --quiet -b "$BR" "$BUMP" HEAD
    git -C "$BUMP/upstream/aipotluck-local-client" checkout --quiet "$CANDIDATE" 2>/dev/null \
      || { git -C "$BUMP" submodule update --init --quiet upstream/aipotluck-local-client && \
           git -C "$BUMP/upstream/aipotluck-local-client" checkout --quiet "$CANDIDATE"; }
    cp "$WORK/candidate-surface.json" "$BUMP/conformance/upstream-surface.json"
    git -C "$BUMP" add upstream/aipotluck-local-client conformance/upstream-surface.json
    git -C "$BUMP" commit --quiet -m "chore(upstream): bump aipotluck-local-client to ${CANDIDATE:0:9}" \
      -m "Prepared by tools/sync_upstream.sh: surface classified, upstream tests and GUI contract tests green against ${CANDIDATE:0:9}. Not yet verified on a real install -- run the manual smoke test before merging." \
      -m "$(git -C "$SUB" log --oneline --no-decorate "$PINNED..$CANDIDATE")"
    git -C "$ROOT" worktree remove --force "$BUMP"
    say "Prepared local branch $BR (not pushed). Review, smoke-test, then merge to main."
  fi
else
  say "Next: tools/sync_upstream.sh --ref ${CANDIDATE:0:9} --prepare-bump"
fi
finish 0
