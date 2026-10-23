#!/usr/bin/env bash
# Publish a directory of installers as one nightly: its own dated prerelease (the history), and the
# rolling `nightly` prerelease (fixed "latest nightly" download links).
#
#   tools/publish-nightly.sh <dist-dir> <label>
#
#   <dist-dir>   output of tools/collect-bundles.sh for every target, merged: installer files named
#                aipotluck-local-client-gui_<label>_<target>.<ext> plus SHA256SUMS.<target>
#   <label>      e.g. 0.1.0-nightly.20261011.2cbd67a (must match the file names)
#
# What it does, in this order, so a failure part-way leaves the previous nightly downloadable:
#   0. publish this build's own prerelease, tagged nightly-<YYYYMMDD>.<sha> and titled "GUI v<label>",
#      with the labelled installers and their SHA256SUMS. One per nightly, kept, so there's a
#      history to go back to; rerunning for the same build replaces its files rather than failing
#   1. build the rolling release's upload set: every installer under its labelled name AND under a stable
#      `..._nightly_<target>.<ext>` name (a fixed URL for "the latest nightly" links), plus one
#      combined SHA256SUMS covering both
#   2. create the `nightly` release (prerelease) if it doesn't exist yet
#   3. upload the new assets (--clobber replaces same-named ones)
#   4. delete assets left over from older nightlies (other labels)
#   5. move the `nightly` tag to $GITHUB_SHA and refresh the title/notes
#
# Needs: gh (authenticated via GH_TOKEN), GITHUB_REPOSITORY, GITHUB_SHA. Run by build.yml's
# `nightly` job; testable locally against a stub `gh` (tests/test_publish_nightly.py).
set -euo pipefail
DIST="${1:?usage: publish-nightly.sh <dist-dir> <label>}"
LABEL="${2:?usage: publish-nightly.sh <dist-dir> <label>}"
: "${GITHUB_REPOSITORY:?}" "${GITHUB_SHA:?}"
TAG=nightly
NAME=aipotluck-local-client-gui
# The label is <version>-nightly.<YYYYMMDD>.<sha7>. Not "v..." on purpose: build.yml treats a pushed
# v*.*.* tag as a release.
DATED_TAG="nightly-${LABEL#*-nightly.}"
REPO=(--repo "$GITHUB_REPOSITORY")

case "$LABEL" in *[!0-9A-Za-z.+-]*|"") echo "bad label: $LABEL" >&2; exit 2 ;; esac
case "$LABEL" in *-nightly.[0-9]*.*) ;; *) echo "not a nightly label (<version>-nightly.<date>.<sha>): $LABEL" >&2; exit 2 ;; esac
shopt -s nullglob
real=()
for f in "$DIST/${NAME}_${LABEL}_"*; do real+=("$f"); done
[ "${#real[@]}" -gt 0 ] || { echo "no installers named ${NAME}_${LABEL}_* in $DIST" >&2; exit 1; }
# A file under some OTHER label in the dist dir means the artifacts are mixed up; refuse.
for f in "$DIST"/"${NAME}"_*; do
  case "$(basename "$f")" in "${NAME}_${LABEL}_"*) ;; *) echo "unexpected file in $DIST: $f" >&2; exit 1 ;; esac
done

sums() { (cd "$1" && if command -v sha256sum >/dev/null; then sha256sum -- *; else shasum -a 256 -- *; fi); }

# 0. this build's own dated prerelease: the labelled installers and one SHA256SUMS for them
DATED="$(mktemp -d)"; STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE" "$DATED"' EXIT
for f in "${real[@]}"; do cp "$f" "$DATED/$(basename "$f")"; done
DSUMS="$(mktemp)"; sums "$DATED" > "$DSUMS"; mv "$DSUMS" "$DATED/SHA256SUMS"
dated_notes="Nightly build of \`main\` at ${GITHUB_SHA}. **Not a release**: untested beyond CI, unsigned on macOS and Windows.

The newest nightly is always at the \`${TAG}\` prerelease too. Verify downloads against \`SHA256SUMS\`."
if gh release view "$DATED_TAG" "${REPO[@]}" >/dev/null 2>&1; then
  gh release upload "$DATED_TAG" "$DATED"/* --clobber "${REPO[@]}"
else
  gh release create "$DATED_TAG" "$DATED"/* "${REPO[@]}" --prerelease --latest=false \
    --target "$GITHUB_SHA" --title "GUI v${LABEL}" --notes "$dated_notes"
fi

# 1. the rolling release's upload set (per-target SHA256SUMS.<target> files give way to one file)
for f in "${real[@]}"; do
  b="$(basename "$f")"
  cp "$f" "$STAGE/$b"
  cp "$f" "$STAGE/${NAME}_nightly_${b#"${NAME}_${LABEL}_"}"
done
SUMS="$(mktemp)"; sums "$STAGE" > "$SUMS"; mv "$SUMS" "$STAGE/SHA256SUMS"
upload=("$STAGE"/*)

title="GUI latest nightly (v${LABEL})"
notes="Automatic build of \`main\` at ${GITHUB_SHA}. **Not a release**: untested beyond CI, unsigned on macOS and Windows.
This build is also kept as its own prerelease, \`${DATED_TAG}\`, with the earlier nightlies.

Stable links to the newest nightly use the \`_nightly_\` file names, e.g.
\`https://github.com/${GITHUB_REPOSITORY}/releases/download/${TAG}/${NAME}_nightly_linux-x64.deb\`.
Verify downloads against \`SHA256SUMS\`."

# 2. make sure the release exists (prerelease, never "latest")
if ! gh release view "$TAG" "${REPO[@]}" >/dev/null 2>&1; then
  gh release create "$TAG" "${REPO[@]}" --prerelease --latest=false \
    --target "$GITHUB_SHA" --title "$title" --notes "$notes"
fi

# 3. upload (replaces same-named assets)
gh release upload "$TAG" "${upload[@]}" --clobber "${REPO[@]}"

# 4. prune assets from older nightlies: anything not in this upload set
keep="$(for f in "${upload[@]}"; do basename "$f"; done)"
gh release view "$TAG" "${REPO[@]}" --json assets --jq '.assets[].name' | while IFS= read -r a; do
  [ -n "$a" ] || continue
  if ! grep -qxF -- "$a" <<<"$keep"; then
    echo "removing stale asset $a"
    gh release delete-asset "$TAG" "$a" --yes "${REPO[@]}"
  fi
done

# 5. move the tag to this commit (the release follows its tag), refresh title/notes
gh api -X PATCH "repos/${GITHUB_REPOSITORY}/git/refs/tags/${TAG}" -f sha="$GITHUB_SHA" -F force=true >/dev/null \
  || gh api -X POST "repos/${GITHUB_REPOSITORY}/git/refs" -f ref="refs/tags/${TAG}" -f sha="$GITHUB_SHA" >/dev/null
gh release edit "$TAG" "${REPO[@]}" --prerelease --latest=false --title "$title" --notes "$notes"

echo "published nightly $LABEL as $DATED_TAG and $TAG ($(echo "$keep" | wc -l | tr -d ' ') assets) at $GITHUB_SHA"
