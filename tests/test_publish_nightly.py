"""tools/publish-nightly.sh against a stub `gh` that keeps a fake release in a JSON file.

What's being held to account is the nightly contract, not the gh calls themselves:
- after a publish, the `nightly` release holds exactly this build's installers (under their
  labelled names AND stable `_nightly_` names) plus one SHA256SUMS -- nothing from an older build;
- the tag points at this commit, and the release is a prerelease that is never "latest";
- a dist dir with nothing to publish, or a mixed-up one, changes nothing.

The real `gh` and GitHub are never contacted.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# publish-nightly.sh runs only on CI's Ubuntu runner (build.yml's nightly job), and the stub `gh`
# below is a `#!/usr/bin/env python3` script, which Git Bash on Windows can't exec.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the nightly publish job runs on Linux only")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "publish-nightly.sh"
NAME = "aipotluck-local-client-gui"

# A stub `gh` covering exactly the subcommands publish-nightly.sh uses. State lives in $GH_STATE.
STUB = r'''#!/usr/bin/env python3
import json, os, sys, shutil
state_path = os.environ["GH_STATE"]
st = json.load(open(state_path)) if os.path.exists(state_path) else {"release": None, "refs": {}, "calls": []}
a = sys.argv[1:]
st["calls"].append(a)
def save(): json.dump(st, open(state_path, "w"), indent=1)
def strip_repo(args):
    out, i = [], 0
    while i < len(args):
        if args[i] == "--repo": i += 2; continue
        out.append(args[i]); i += 1
    return out
a = strip_repo(a)
if a[:2] == ["release", "view"]:
    if st["release"] is None: save(); sys.exit(1)
    if "--json" in a:
        for asset in st["release"]["assets"]: print(asset)
    save(); sys.exit(0)
if a[:2] == ["release", "create"]:
    st["release"] = {"tag": a[2], "assets": [], "prerelease": "--prerelease" in a,
                     "latest": "--latest=false" not in a, "title": a[a.index("--title")+1]}
    st["refs"]["tags/" + a[2]] = a[a.index("--target")+1]
    save(); sys.exit(0)
if a[:2] == ["release", "upload"]:
    files = [x for x in a[3:] if not x.startswith("--")]
    for f in files:
        n = os.path.basename(f)
        if n in st["release"]["assets"] and "--clobber" not in a: save(); sys.exit(1)
        if n not in st["release"]["assets"]: st["release"]["assets"].append(n)
        st.setdefault("bytes", {})[n] = open(f, "rb").read().hex()
    save(); sys.exit(0)
if a[:2] == ["release", "delete-asset"]:
    st["release"]["assets"].remove(a[3]); save(); sys.exit(0)
if a[:2] == ["release", "edit"]:
    st["release"]["prerelease"] = "--prerelease" in a
    st["release"]["latest"] = "--latest=false" not in a
    st["release"]["title"] = a[a.index("--title")+1]
    save(); sys.exit(0)
if a[0] == "api":
    method = a[a.index("-X")+1]; path = a[a.index("-X")+2]
    sha = [x.split("=",1)[1] for x in a if x.startswith("sha=")][0]
    if method == "PATCH":
        ref = path.split("/git/refs/")[1]
        if ref not in st["refs"]: save(); sys.exit(1)
        st["refs"][ref] = sha
    else:
        ref = [x.split("=",1)[1] for x in a if x.startswith("ref=")][0].removeprefix("refs/")
        st["refs"][ref] = sha
    save(); sys.exit(0)
print("stub gh: unhandled", a, file=sys.stderr); save(); sys.exit(2)
'''


@pytest.fixture
def env(tmp_path: Path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(STUB)
    gh.chmod(0o755)
    e = dict(os.environ)
    e.update(PATH=f"{bindir}:{e['PATH']}", GH_STATE=str(tmp_path / "gh.json"),
             GITHUB_REPOSITORY="currentai-org/aipotluck-local-client-gui")
    return e


def make_dist(d: Path, label: str, payload: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for target, ext in (("linux-x64", "deb"), ("linux-x64", "AppImage"), ("linux-arm64", "deb")):
        (d / f"{NAME}_{label}_{target}.{ext}").write_text(f"{payload}-{target}-{ext}")
    (d / "SHA256SUMS.linux-x64").write_text("per-target sums, superseded\n")
    return d


def publish(env, dist: Path, label: str, sha: str):
    return subprocess.run(["bash", str(SCRIPT), str(dist), label], env={**env, "GITHUB_SHA": sha},
                          capture_output=True, text=True)


def state(env) -> dict:
    return json.loads(Path(env["GH_STATE"]).read_text())


def test_first_nightly_creates_a_prerelease_with_labelled_and_stable_names_at_this_commit(env, tmp_path):
    label = "0.1.0-nightly.20261011.aaaaaaa"
    r = publish(env, make_dist(tmp_path / "d1", label, "one"), label, "a" * 40)
    assert r.returncode == 0, r.stderr
    s = state(env)
    assets = set(s["release"]["assets"])
    expected = {f"{NAME}_{label}_linux-x64.deb", f"{NAME}_{label}_linux-x64.AppImage", f"{NAME}_{label}_linux-arm64.deb",
                f"{NAME}_nightly_linux-x64.deb", f"{NAME}_nightly_linux-x64.AppImage", f"{NAME}_nightly_linux-arm64.deb",
                "SHA256SUMS"}
    assert assets == expected
    assert s["release"]["prerelease"] is True and s["release"]["latest"] is False
    assert s["refs"]["tags/nightly"] == "a" * 40


def test_the_stable_name_and_the_labelled_name_are_the_same_bytes_and_the_sums_cover_both(env, tmp_path):
    label = "0.1.0-nightly.20261011.aaaaaaa"
    publish(env, make_dist(tmp_path / "d1", label, "one"), label, "a" * 40)
    b = state(env)["bytes"]
    assert b[f"{NAME}_nightly_linux-x64.deb"] == b[f"{NAME}_{label}_linux-x64.deb"]
    sums = bytes.fromhex(b["SHA256SUMS"]).decode()
    for name, hexdata in b.items():
        if name == "SHA256SUMS":
            continue
        assert f"{hashlib.sha256(bytes.fromhex(hexdata)).hexdigest()}  {name}" in sums, name


def test_the_next_nightly_replaces_everything_from_the_previous_one_and_moves_the_tag(env, tmp_path):
    old, new = "0.1.0-nightly.20261011.aaaaaaa", "0.1.0-nightly.20261012.bbbbbbb"
    publish(env, make_dist(tmp_path / "d1", old, "one"), old, "a" * 40)
    r = publish(env, make_dist(tmp_path / "d2", new, "two"), new, "b" * 40)
    assert r.returncode == 0, r.stderr
    s = state(env)
    assert not [a for a in s["release"]["assets"] if old in a], "a previous nightly's installer survived"
    assert bytes.fromhex(s["bytes"][f"{NAME}_nightly_linux-x64.deb"]).decode() == "two-linux-x64-deb"
    assert s["refs"]["tags/nightly"] == "b" * 40
    assert s["release"]["title"] == f"Nightly build ({new})"


def test_a_nightly_that_lost_a_target_does_not_keep_serving_that_targets_stale_installer(env, tmp_path):
    """If a target is disabled (or dropped), its old `_nightly_` file must not linger as if current."""
    old, new = "0.1.0-nightly.20261011.aaaaaaa", "0.1.0-nightly.20261012.bbbbbbb"
    publish(env, make_dist(tmp_path / "d1", old, "one"), old, "a" * 40)
    d2 = make_dist(tmp_path / "d2", new, "two")
    (d2 / f"{NAME}_{new}_linux-arm64.deb").unlink()
    assert publish(env, d2, new, "b" * 40).returncode == 0
    assert f"{NAME}_nightly_linux-arm64.deb" not in state(env)["release"]["assets"]


def test_an_empty_dist_publishes_nothing_and_leaves_the_previous_nightly_alone(env, tmp_path):
    label = "0.1.0-nightly.20261011.aaaaaaa"
    publish(env, make_dist(tmp_path / "d1", label, "one"), label, "a" * 40)
    before = state(env)["release"]["assets"]
    (tmp_path / "empty").mkdir()
    r = publish(env, tmp_path / "empty", "0.1.0-nightly.20261012.bbbbbbb", "b" * 40)
    assert r.returncode != 0
    s = state(env)
    assert s["release"]["assets"] == before and s["refs"]["tags/nightly"] == "a" * 40


def test_installers_from_two_different_builds_in_one_dist_are_refused(env, tmp_path):
    d = make_dist(tmp_path / "d", "0.1.0-nightly.20261012.bbbbbbb", "two")
    (d / f"{NAME}_0.1.0-nightly.20261011.aaaaaaa_linux-x64.deb").write_text("stale")
    r = publish(env, d, "0.1.0-nightly.20261012.bbbbbbb", "b" * 40)
    assert r.returncode != 0 and "unexpected file" in r.stderr
    assert not Path(env["GH_STATE"]).exists() or state(env)["release"] is None
