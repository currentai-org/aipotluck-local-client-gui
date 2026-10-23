#!/usr/bin/env bash
# Check aipotluck.org's download links: every fixed name in .github/latest-download-names.txt,
# requested at releases/latest/download/<name>, must lead to that file in release <tag>.
#
#   tools/check-latest-links.sh <tag>        e.g. v0.2.0, the release that should be Latest
#
# For each name, two requests:
#   1. without following redirects: GitHub answers 302 to releases/download/<latest tag>/<name>.
#      That redirect names the release GitHub treats as Latest, and it's sent even for a file that
#      doesn't exist, so it must name <tag>. Anything else means a different release is Latest.
#   2. following redirects, for the first byte only: must be 200/206. A 404 means <tag> has no file
#      by that name.
# GitHub can take a moment to move Latest after a publish, so a mismatch is retried before it fails.
#
# Exit 0 when every link is good; 1 listing each bad link and what to do (docs/RELEASING.md,
# "Fixed latest download links"). Run by .github/workflows/latest-links.yml on Publish, or by hand.
# Env: GITHUB_REPOSITORY (default currentai-org/aipotluck-local-client-gui); LATEST_BASE overrides
# the releases/latest/download URL and LATEST_NAMES_FILE the list (tests use both);
# LATEST_ATTEMPTS / LATEST_RETRY_SECONDS tune the retry.
set -euo pipefail
TAG="${1:?usage: check-latest-links.sh <tag>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${GITHUB_REPOSITORY:-currentai-org/aipotluck-local-client-gui}"
BASE="${LATEST_BASE:-https://github.com/$REPO/releases/latest/download}"
NAMES="${LATEST_NAMES_FILE:-$ROOT/.github/latest-download-names.txt}"
ATTEMPTS="${LATEST_ATTEMPTS:-6}"
RETRY="${LATEST_RETRY_SECONDS:-20}"

names=()
while IFS= read -r n; do
  n="${n%%#*}"; n="$(echo "$n" | tr -d '[:space:]')"
  [ -n "$n" ] && names+=("$n")
done < "$NAMES"
[ "${#names[@]}" -gt 0 ] || { echo "no names in $NAMES" >&2; exit 2; }

check_all() {
  bad=()
  for n in "${names[@]}"; do
    hop="$(curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' "$BASE/$n" || echo "000 ")"
    code="${hop%% *}"; to="${hop#* }"
    if [ "$code" != 302 ] && [ "$code" != 301 ]; then
      bad+=("$n: expected a redirect from releases/latest, got HTTP $code"); continue
    fi
    case "$to" in
      */releases/download/"$TAG"/"$n") ;;
      *) bad+=("$n: Latest is not $TAG (redirects to $to)"); continue ;;
    esac
    got="$(curl -sS -L -r 0-0 -o /dev/null -w '%{http_code}' "$BASE/$n" || echo 000)"
    case "$got" in 200|206) echo "ok  $n -> $TAG" ;; *) bad+=("$n: $TAG has no such file (HTTP $got)") ;; esac
  done
}

for attempt in $(seq 1 "$ATTEMPTS"); do
  check_all
  [ "${#bad[@]}" -eq 0 ] && { echo "all ${#names[@]} fixed download links lead to $TAG"; exit 0; }
  [ "$attempt" -lt "$ATTEMPTS" ] && { echo "attempt $attempt: ${#bad[@]} bad, retrying in ${RETRY}s"; sleep "$RETRY"; }
done

{
  echo "aipotluck.org's download links are broken for ${#bad[@]} of ${#names[@]} files:"
  for b in "${bad[@]}"; do echo "  - $b"; done
  echo
  echo "What to do (docs/RELEASING.md, \"Fixed latest download links\"):"
  echo "  - 'Latest is not $TAG': on the Releases page, edit $TAG and tick 'Set as the latest release'"
  echo "    (or, if another release should be Latest, rerun this check for that tag)."
  echo "  - 'has no such file': upload the missing fixed-name copies to $TAG (tools/stage-release.sh"
  echo "    makes them), or publish a release that has them. The site links 404 until then."
} >&2
exit 1
