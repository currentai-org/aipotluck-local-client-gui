#!/usr/bin/env bash
# Scheduled watchdog for upstream drift. Silent (no stdout) when the pinned upstream is current;
# otherwise prints tools/sync_upstream.sh's full report plus what to do next. Always exits 0, so a
# delivered warning is never also a failed job (a cron runner treats empty stdout as "nothing to
# deliver").
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$("$ROOT/tools/sync_upstream.sh" --quiet 2>&1)"
RC=$?
if [ -n "$OUT" ]; then
  case $RC in
    0) echo "aipotluck-local-client-gui: upstream CLI has new commits and they PASS every GUI check." ;;
    1) echo "aipotluck-local-client-gui: upstream CLI has moved and the GUI needs attention." ;;
    *) echo "aipotluck-local-client-gui: the upstream sync check could not run (tooling problem, not drift)." ;;
  esac
  echo
  echo "$OUT"
  echo
  echo "Repo: $ROOT  (see docs/CONFORMANCE.md \"Bumping\")"
fi
exit 0
