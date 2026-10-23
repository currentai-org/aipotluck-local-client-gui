"""tools/publish-nightly.sh against a stub `gh` that keeps a fake release in a JSON file.

What's being held to account is the nightly contract, not the gh calls themselves:
- every nightly gets its own prerelease, nightly-<date>.<sha>, titled "GUI v<label>", holding its
  labelled installers and their SHA256SUMS; earlier ones are kept (the history);
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
import json, os, sys
state_path = os.environ["GH_STATE"]
st = json.load(open(state_path)) if os.path.exists(state_path) else {"releases": {}, "refs": {}, "bytes": {}, "calls": []}
a = sys.argv[1:]
st["calls"].append(a)
def save(): json.dump(st, open(state_path, "w"), indent=1)
def strip_repo(args):
    out, i = [], 0
    while i < len(args):
        if args[i] == "--repo": i += 2; continue
        out.append(args[i]); i += 1
    return out
VALUED = {"--target", "--title", "--notes"}
def positional(args):
    out, i = [], 0
    while i < len(args):
        if args[i] in VALUED: i += 2; continue
        if args[i].startswith("--"): i += 1; continue
        out.append(args[i]); i += 1
    return out
def add_files(tag, files, clobber):
    rel = st["releases"][tag]
    for f in files:
        n = os.path.basename(f)
        if n in rel["assets"] and not clobber: save(); sys.exit(1)
        if n not in rel["assets"]: rel["assets"].append(n)
        st["bytes"].setdefault(tag, {})[n] = open(f, "rb").read().hex()
a = strip_repo(a)
if a[:2] == ["release", "view"]:
    rel = st["releases"].get(a[2])
    if rel is None: save(); sys.exit(1)
    if "--json" in a:
        for asset in rel["assets"]: print(asset)
    save(); sys.exit(0)
if a[:2] == ["release", "create"]:
    tag = a[2]
    if tag in st["releases"]: save(); sys.exit(1)
    st["releases"][tag] = {"assets": [], "prerelease": "--prerelease" in a,
                           "latest": "--latest=false" not in a, "title": a[a.index("--title")+1]}
    st["refs"]["tags/" + tag] = a[a.index("--target")+1]
    add_files(tag, positional(a[3:]), clobber=False)
    save(); sys.exit(0)
if a[:2] == ["release", "upload"]:
    if a[2] not in st["releases"]: save(); sys.exit(1)
    add_files(a[2], positional(a[3:]), clobber="--clobber" in a)
    save(); sys.exit(0)
if a[:2] == ["release", "delete-asset"]:
    st["releases"][a[2]]["assets"].remove(a[3]); st["bytes"].get(a[2], {}).pop(a[3], None); save(); sys.exit(0)
if a[:2] == ["release", "edit"]:
    rel = st["releases"][a[2]]
    rel["prerelease"] = "--prerelease" in a
    rel["latest"] = "--latest=false" not in a
    rel["title"] = a[a.index("--title")+1]
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
    assets = set(s["releases"]["nightly"]["assets"])
    expected = {f"{NAME}_{label}_linux-x64.deb", f"{NAME}_{label}_linux-x64.AppImage", f"{NAME}_{label}_linux-arm64.deb",
                f"{NAME}_nightly_linux-x64.deb", f"{NAME}_nightly_linux-x64.AppImage", f"{NAME}_nightly_linux-arm64.deb",
                "SHA256SUMS"}
    assert assets == expected
    assert s["releases"]["nightly"]["prerelease"] is True and s["releases"]["nightly"]["latest"] is False
    assert s["refs"]["tags/nightly"] == "a" * 40


def test_the_stable_name_and_the_labelled_name_are_the_same_bytes_and_the_sums_cover_both(env, tmp_path):
    label = "0.1.0-nightly.20261011.aaaaaaa"
    publish(env, make_dist(tmp_path / "d1", label, "one"), label, "a" * 40)
    b = state(env)["bytes"]["nightly"]
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
    assert not [a for a in s["releases"]["nightly"]["assets"] if old in a], "a previous nightly's installer survived"
    assert bytes.fromhex(s["bytes"]["nightly"][f"{NAME}_nightly_linux-x64.deb"]).decode() == "two-linux-x64-deb"
    assert s["refs"]["tags/nightly"] == "b" * 40
    assert s["releases"]["nightly"]["title"] == f"GUI latest nightly (v{new})"


def test_a_nightly_that_lost_a_target_does_not_keep_serving_that_targets_stale_installer(env, tmp_path):
    """If a target is disabled (or dropped), its old `_nightly_` file must not linger as if current."""
    old, new = "0.1.0-nightly.20261011.aaaaaaa", "0.1.0-nightly.20261012.bbbbbbb"
    publish(env, make_dist(tmp_path / "d1", old, "one"), old, "a" * 40)
    d2 = make_dist(tmp_path / "d2", new, "two")
    (d2 / f"{NAME}_{new}_linux-arm64.deb").unlink()
    assert publish(env, d2, new, "b" * 40).returncode == 0
    assert f"{NAME}_nightly_linux-arm64.deb" not in state(env)["releases"]["nightly"]["assets"]


def test_an_empty_dist_publishes_nothing_and_leaves_the_previous_nightly_alone(env, tmp_path):
    label = "0.1.0-nightly.20261011.aaaaaaa"
    publish(env, make_dist(tmp_path / "d1", label, "one"), label, "a" * 40)
    before = state(env)["releases"]["nightly"]["assets"]
    (tmp_path / "empty").mkdir()
    r = publish(env, tmp_path / "empty", "0.1.0-nightly.20261012.bbbbbbb", "b" * 40)
    assert r.returncode != 0
    s = state(env)
    assert s["releases"]["nightly"]["assets"] == before and s["refs"]["tags/nightly"] == "a" * 40


def test_installers_from_two_different_builds_in_one_dist_are_refused(env, tmp_path):
    d = make_dist(tmp_path / "d", "0.1.0-nightly.20261012.bbbbbbb", "two")
    (d / f"{NAME}_0.1.0-nightly.20261011.aaaaaaa_linux-x64.deb").write_text("stale")
    r = publish(env, d, "0.1.0-nightly.20261012.bbbbbbb", "b" * 40)
    assert r.returncode != 0 and "unexpected file" in r.stderr
    assert not Path(env["GH_STATE"]).exists() or state(env)["releases"] == {}


# Per-nightly history: one prerelease per build, kept.

def test_each_nightly_gets_its_own_prerelease_titled_gui_v_label_with_its_installers_and_sums(env, tmp_path):
    label = "0.2.0-nightly.20261023.aaaaaaa"
    assert publish(env, make_dist(tmp_path / "d1", label, "one"), label, "a" * 40).returncode == 0
    s = state(env)
    rel = s["releases"]["nightly-20261023.aaaaaaa"]
    assert rel["title"] == f"GUI v{label}"
    # The official version the nightly is built on leads the title.
    assert rel["title"].startswith("GUI v0.2.0-nightly.")
    assert rel["prerelease"] is True and rel["latest"] is False
    assert s["refs"]["tags/nightly-20261023.aaaaaaa"] == "a" * 40
    assert set(rel["assets"]) == {f"{NAME}_{label}_linux-x64.deb", f"{NAME}_{label}_linux-x64.AppImage",
                                  f"{NAME}_{label}_linux-arm64.deb", "SHA256SUMS"}
    b = s["bytes"]["nightly-20261023.aaaaaaa"]
    sums = bytes.fromhex(b["SHA256SUMS"]).decode()
    for name, hexdata in b.items():
        if name != "SHA256SUMS":
            assert f"{hashlib.sha256(bytes.fromhex(hexdata)).hexdigest()}  {name}" in sums, name
    assert "_nightly_" not in sums, "the dated release's sums name files it doesn't have"


def test_earlier_nightlies_are_kept_as_history_while_the_rolling_one_moves_on(env, tmp_path):
    old, new = "0.2.0-nightly.20261023.aaaaaaa", "0.2.0-nightly.20261024.bbbbbbb"
    publish(env, make_dist(tmp_path / "d1", old, "one"), old, "a" * 40)
    assert publish(env, make_dist(tmp_path / "d2", new, "two"), new, "b" * 40).returncode == 0
    s = state(env)
    assert {"nightly-20261023.aaaaaaa", "nightly-20261024.bbbbbbb", "nightly"} <= set(s["releases"])
    assert bytes.fromhex(s["bytes"]["nightly-20261023.aaaaaaa"][f"{NAME}_{old}_linux-x64.deb"]).decode() == "one-linux-x64-deb"
    assert s["refs"]["tags/nightly-20261023.aaaaaaa"] == "a" * 40
    assert s["refs"]["tags/nightly"] == "b" * 40


def test_rerunning_the_same_nightly_replaces_its_files_instead_of_failing(env, tmp_path):
    label = "0.2.0-nightly.20261023.aaaaaaa"
    publish(env, make_dist(tmp_path / "d1", label, "first"), label, "a" * 40)
    r = publish(env, make_dist(tmp_path / "d2", label, "second"), label, "a" * 40)
    assert r.returncode == 0, r.stderr
    s = state(env)
    assert [t for t in s["releases"] if t.startswith("nightly-")] == ["nightly-20261023.aaaaaaa"]
    assert bytes.fromhex(s["bytes"]["nightly-20261023.aaaaaaa"][f"{NAME}_{label}_linux-x64.deb"]).decode() == "second-linux-x64-deb"


def test_a_label_that_is_not_a_nightly_label_is_refused_before_anything_is_published(env, tmp_path):
    r = publish(env, make_dist(tmp_path / "d", "0.2.0", "x"), "0.2.0", "a" * 40)
    assert r.returncode != 0 and "not a nightly label" in r.stderr
    assert not Path(env["GH_STATE"]).exists() or state(env)["releases"] == {}
