"""The fixed ("latest") download names aipotluck.org links to, end to end.

What's held to account:
- .github/latest-download-names.txt is exactly what the enabled targets in build-targets.json
  produce, so a target added, dropped or given a new format can't leave the list (and the site)
  out of step unnoticed;
- tools/stage-release.sh gives a release every fixed name (same bytes as the versioned file) and one
  SHA256SUMS, and refuses a dist that would leave a fixed name missing;
- tools/check-latest-links.sh passes only when every name, requested at releases/latest/download,
  reaches that file in the release that should be Latest. It runs against a local HTTP server that
  answers the way GitHub does (a 302 naming the Latest tag even for a missing file, then 404).
GitHub is never contacted.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="release tooling runs on CI's Linux runner")

ROOT = Path(__file__).resolve().parents[1]
NAMES_FILE = ROOT / ".github" / "latest-download-names.txt"
STAGE = ROOT / "tools" / "stage-release.sh"
CHECK = ROOT / "tools" / "check-latest-links.sh"
NAME = "aipotluck-local-client-gui"
# `tauri build --bundles` value -> the extension tools/collect-bundles.sh gives that installer.
BUNDLE_EXT = {"deb": "deb", "appimage": "AppImage", "nsis": "setup.exe", "msi": "msi", "app": "app.zip", "dmg": "dmg"}


def listed_names() -> list[str]:
    out = []
    for line in NAMES_FILE.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def test_the_fixed_names_are_exactly_what_the_enabled_targets_build():
    targets = json.loads((ROOT / ".github" / "build-targets.json").read_text())["targets"]
    built = {f"{NAME}_{t['target']}.{BUNDLE_EXT[b]}" for t in targets if t["enabled"] for b in t["bundles"].split(",")}
    names = listed_names()
    assert len(names) == len(set(names)), "a name is listed twice"
    assert set(names) == built, (
        "latest-download-names.txt and the enabled targets disagree. Update the list AND "
        "aipotluck.org's settings page together (docs/RELEASING.md, 'Fixed latest download links'): "
        f"only listed {sorted(set(names) - built)}, only built {sorted(built - set(names))}"
    )


# --- stage-release.sh -----------------------------------------------------------------------------

def make_dist(d: Path, version: str, skip: set[str] = frozenset()) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for n in listed_names():
        if n in skip:
            continue
        suffix = n.removeprefix(f"{NAME}_")
        (d / f"{NAME}_{version}_{suffix}").write_text(f"bytes of {suffix}")
    (d / "SHA256SUMS.linux-x64").write_text("per-target sums, superseded\n")
    return d


def stage(dist: Path, version: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(STAGE), str(dist), version], capture_output=True, text=True)


def test_staging_adds_every_fixed_name_with_the_same_bytes_and_one_sums_file(tmp_path):
    dist = make_dist(tmp_path / "dist", "0.3.0")
    r = stage(dist, "0.3.0")
    assert r.returncode == 0, r.stderr
    for n in listed_names():
        versioned = dist / n.replace(f"{NAME}_", f"{NAME}_0.3.0_", 1)
        assert (dist / n).read_bytes() == versioned.read_bytes(), n
    assert not list(dist.glob("SHA256SUMS.*")), "per-target sums should be replaced"
    sums = (dist / "SHA256SUMS").read_text()
    for f in dist.glob(f"{NAME}_*"):
        assert f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" in sums, f.name


def test_staging_refuses_a_release_that_would_leave_a_site_link_missing(tmp_path):
    gone = f"{NAME}_macos-x64.dmg"
    dist = make_dist(tmp_path / "dist", "0.3.0", skip={gone})
    r = stage(dist, "0.3.0")
    assert r.returncode == 1
    assert gone in r.stderr and "aipotluck.org" in r.stderr and "docs/RELEASING.md" in r.stderr


def test_staging_refuses_a_dist_with_no_installers_for_that_version(tmp_path):
    dist = make_dist(tmp_path / "dist", "0.3.0")
    r = stage(dist, "0.4.0")
    assert r.returncode == 1 and "no installers" in r.stderr


# --- check-latest-links.sh ------------------------------------------------------------------------

class FakeGitHub:
    """Answers like github.com: /latest/download/<n> -> 302 to /releases/download/<latest>/<n>
    whether or not the file exists; the file URL -> 206 if that release has it, else 404."""

    def __init__(self, latest: str, files: dict[str, set[str]]):
        self.latest, self.files = latest, files
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parts = self.path.strip("/").split("/")
                if parts[:2] == ["latest", "download"]:
                    self.send_response(302)
                    self.send_header("Location", f"{outer.url}/releases/download/{outer.latest}/{parts[2]}")
                    self.end_headers()
                elif parts[:2] == ["releases", "download"] and parts[3] in outer.files.get(parts[2], set()):
                    self.send_response(206)
                    self.send_header("Content-Length", "1")
                    self.end_headers()
                    self.wfile.write(b"x")
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()


def check(gh: FakeGitHub, tag: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "LATEST_BASE": f"{gh.url}/latest/download", "LATEST_ATTEMPTS": "1", "LATEST_RETRY_SECONDS": "0"}
    return subprocess.run(["bash", str(CHECK), tag], env=env, capture_output=True, text=True, timeout=60)


def test_the_check_passes_when_every_fixed_name_reaches_the_published_release():
    with FakeGitHub("v0.3.0", {"v0.3.0": set(listed_names())}) as gh:
        r = check(gh, "v0.3.0")
    assert r.returncode == 0, r.stderr
    assert f"all {len(listed_names())} fixed download links lead to v0.3.0" in r.stdout


def test_the_check_fails_naming_each_file_the_release_lacks():
    gone = f"{NAME}_windows-x64.setup.exe"
    with FakeGitHub("v0.3.0", {"v0.3.0": set(listed_names()) - {gone}}) as gh:
        r = check(gh, "v0.3.0")
    assert r.returncode == 1
    assert f"{gone}: v0.3.0 has no such file (HTTP 404)" in r.stderr
    assert "upload the missing fixed-name copies" in r.stderr


def test_the_check_fails_when_a_different_release_is_marked_latest():
    # Everything downloads fine, but from the old release: the site would serve stale installers.
    with FakeGitHub("v0.2.0", {"v0.2.0": set(listed_names()), "v0.3.0": set(listed_names())}) as gh:
        r = check(gh, "v0.3.0")
    assert r.returncode == 1
    assert "Latest is not v0.3.0" in r.stderr and "Set as the latest release" in r.stderr
