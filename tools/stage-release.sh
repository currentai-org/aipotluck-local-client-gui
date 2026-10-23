#!/usr/bin/env bash
# Prepare a directory of installers for a release: add the fixed ("latest") names, combine the
# checksums, and refuse if any name aipotluck.org links to would be missing.
#
#   tools/stage-release.sh <dist-dir> <version>
#
#   <dist-dir>   every target's output of tools/collect-bundles.sh, merged: installers named
#                aipotluck-local-client-gui_<version>_<target>.<ext> plus SHA256SUMS.<target>
#   <version>    e.g. 0.2.0 (must match the file names)
#
# In place, in this order:
#   1. copy each installer to its version-free name, aipotluck-local-client-gui_<target>.<ext>
#   2. replace the per-target SHA256SUMS.<target> files with one SHA256SUMS covering every file
#   3. check every name in .github/latest-download-names.txt is now present; if any isn't, exit 1
#      naming them, before build.yml creates the draft release
#
# Run by build.yml's `release` job; tests/test_latest_links.py runs it on a fake dist.
set -euo pipefail
DIST="${1:?usage: stage-release.sh <dist-dir> <version>}"
VERSION="${2:?usage: stage-release.sh <dist-dir> <version>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAMES="${LATEST_NAMES_FILE:-$ROOT/.github/latest-download-names.txt}"
NAME=aipotluck-local-client-gui

case "$VERSION" in *[!0-9A-Za-z.+-]*|"") echo "bad version: $VERSION" >&2; exit 2 ;; esac
shopt -s nullglob
versioned=("$DIST/${NAME}_${VERSION}_"*)
[ "${#versioned[@]}" -gt 0 ] || { echo "no installers named ${NAME}_${VERSION}_* in $DIST" >&2; exit 1; }

# 1. version-free copies (same bytes)
for f in "${versioned[@]}"; do
  cp "$f" "$DIST/${NAME}_$(basename "$f" | sed "s/^${NAME}_${VERSION}_//")"
done

# 2. one SHA256SUMS for everything
rm -f "$DIST"/SHA256SUMS.* "$DIST/SHA256SUMS"
sums="$(mktemp)"
(cd "$DIST" && if command -v sha256sum >/dev/null; then sha256sum -- "${NAME}"_*; else shasum -a 256 -- "${NAME}"_*; fi) > "$sums"
mv "$sums" "$DIST/SHA256SUMS"

# 3. every name aipotluck.org links to must be here
missing=()
while IFS= read -r n; do
  n="${n%%#*}"; n="$(echo "$n" | tr -d '[:space:]')"
  [ -n "$n" ] || continue
  [ -f "$DIST/$n" ] || missing+=("$n")
done < "$NAMES"
if [ "${#missing[@]}" -gt 0 ]; then
  echo "This release would break aipotluck.org's download links: missing ${missing[*]}" >&2
  echo "Every name in .github/latest-download-names.txt must be built. See \"Fixed latest download links\" in docs/RELEASING.md." >&2
  exit 1
fi
echo "staged ${#versioned[@]} installers for $VERSION with their fixed names, and one SHA256SUMS"
