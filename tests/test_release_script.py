"""tools/release.sh against throwaway git repos: a bare "origin" for the GUI, a clone of this repo's
version files as the GUI checkout, and a bare repo standing in for the CLI. GitHub is never
contacted and nothing is pushed anywhere real.

The contract held to account:
- `prepare` sets one version in every file that carries it, on a release/vX branch, in one commit;
- `tag` creates and pushes v<version> only when main is clean and current, the files agree, the
  tag is new, and the pinned CLI commit is on the CLI's main -- and creates nothing otherwise.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="release.sh is run from a POSIX shell")

ROOT = Path(__file__).resolve().parents[1]
FILES = ["src-tauri/tauri.conf.json", "src-tauri/Cargo.toml", "src-tauri/Cargo.lock", "ui/package.json"]
SUB = "upstream/aitpotluck-local-client"


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    r = subprocess.run(["git", "-c", "protocol.file.allow=always", *args], cwd=cwd, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r.stdout.strip()


@pytest.fixture
def repos(tmp_path):
    """GUI checkout on main == origin/main, version 0.1.0, CLI pinned at a commit on the CLI's main."""
    cli_work = tmp_path / "cli-work"
    cli_work.mkdir()
    git(cli_work, "init", "-q", "-b", "main")
    (cli_work / "README").write_text("cli\n")
    git(cli_work, "add", ".")
    git(cli_work, "commit", "-q", "-m", "cli on main")
    cli_main_commit = git(cli_work, "rev-parse", "HEAD")
    git(cli_work, "checkout", "-q", "-b", "feature")
    (cli_work / "README").write_text("cli feature\n")
    git(cli_work, "commit", "-q", "-am", "feature only")
    cli_feature_commit = git(cli_work, "rev-parse", "HEAD")
    cli_bare = tmp_path / "cli.git"
    git(tmp_path, "clone", "-q", "--bare", str(cli_work), str(cli_bare))

    origin = tmp_path / "gui.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    gui = tmp_path / "gui"
    gui.mkdir()
    git(gui, "init", "-q", "-b", "main")
    for f in FILES + ["tools/release.sh", "tools/release_version.py"]:
        (gui / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, gui / f)
    git(gui, "submodule", "add", "-q", str(cli_bare), SUB)
    git(gui / SUB, "checkout", "-q", cli_main_commit)
    git(gui, "add", ".")
    git(gui, "commit", "-q", "-m", "initial")
    git(gui, "remote", "add", "origin", str(origin))
    git(gui, "push", "-q", "-u", "origin", "main")
    return {"gui": gui, "origin": origin, "cli": cli_bare, "cli_feature": cli_feature_commit, "tmp": tmp_path}


def release(r, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "AIPOTLUCK_CLI_REMOTE": str(r["cli"]), "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_ALLOW_PROTOCOL": "file"}
    return subprocess.run(["bash", "tools/release.sh", *args], cwd=r["gui"], env=env,
                          capture_output=True, text=True, timeout=60)


def version_of(r) -> str:
    return subprocess.run([sys.executable, "tools/release_version.py", "--check"], cwd=r["gui"],
                          capture_output=True, text=True).stdout.strip()


def merge_release_branch(r, version: str):
    """What merging the release PR does: main gets the version commit."""
    gui = r["gui"]
    git(gui, "checkout", "-q", "main")
    git(gui, "merge", "-q", "--no-ff", f"release/v{version}", "-m", "Merge release PR")
    git(gui, "push", "-q", "origin", "main")


def remote_tags(r) -> list[str]:
    return git(r["origin"], "tag", "-l").split()


def test_prepare_sets_every_version_file_in_one_commit_on_a_release_branch(repos):
    r = release(repos, "prepare", "0.2.0")
    assert r.returncode == 0, r.stderr
    gui = repos["gui"]
    assert git(gui, "branch", "--show-current") == "release/v0.2.0"
    assert version_of(repos) == "0.2.0"
    assert git(gui, "log", "-1", "--format=%s") == "chore(release): 0.2.0"
    changed = set(git(gui, "show", "--name-only", "--format=", "HEAD").split())
    assert changed == set(FILES)
    assert "name = \"aipotluck-local-client-gui\"\nversion = \"0.2.0\"" in (gui / "src-tauri/Cargo.lock").read_text()
    assert remote_tags(repos) == []  # prepare never tags


def test_prepare_then_tag_pushes_an_annotated_tag_on_mains_tip(repos):
    assert release(repos, "prepare", "0.2.0").returncode == 0
    merge_release_branch(repos, "0.2.0")
    r = release(repos, "tag", "0.2.0", "--yes")
    assert r.returncode == 0, r.stderr
    assert remote_tags(repos) == ["v0.2.0"]
    assert git(repos["origin"], "cat-file", "-t", "v0.2.0") == "tag"  # annotated
    assert git(repos["origin"], "rev-parse", "v0.2.0^{commit}") == git(repos["origin"], "rev-parse", "main")


def test_tag_refuses_when_the_version_files_say_something_else(repos):
    r = release(repos, "tag", "0.2.0", "--yes")
    assert r.returncode != 0 and "don't all say 0.2.0" in r.stderr
    assert remote_tags(repos) == []


def test_tag_refuses_a_cli_pin_that_is_only_on_a_feature_branch(repos):
    gui = repos["gui"]
    git(gui / SUB, "fetch", "-q", str(repos["cli"]), "feature")
    git(gui / SUB, "checkout", "-q", repos["cli_feature"])
    git(gui, "commit", "-q", "-am", "pin a feature-branch CLI")
    git(gui, "push", "-q", "origin", "main")
    assert release(repos, "prepare", "0.2.0").returncode == 0
    merge_release_branch(repos, "0.2.0")
    r = release(repos, "tag", "0.2.0", "--yes")
    assert r.returncode != 0 and "isn't on the CLI's main" in r.stderr
    assert remote_tags(repos) == [] and git(gui, "tag", "-l") == ""


def test_tag_refuses_when_main_is_behind_origin(repos):
    assert release(repos, "prepare", "0.2.0").returncode == 0
    merge_release_branch(repos, "0.2.0")
    other = repos["tmp"] / "other"
    git(repos["tmp"], "clone", "-q", str(repos["origin"]), str(other))
    (other / "x").write_text("x")
    git(other, "add", "x")
    git(other, "commit", "-q", "-m", "someone else's change")
    git(other, "push", "-q", "origin", "main")
    r = release(repos, "tag", "0.2.0", "--yes")
    assert r.returncode != 0 and "isn't origin/main" in r.stderr
    assert remote_tags(repos) == []


def test_tag_refuses_uncommitted_changes(repos):
    assert release(repos, "prepare", "0.2.0").returncode == 0
    merge_release_branch(repos, "0.2.0")
    (repos["gui"] / "ui/package.json").write_text("{}")
    r = release(repos, "tag", "0.2.0", "--yes")
    assert r.returncode != 0 and "uncommitted" in r.stderr
    assert remote_tags(repos) == []


def test_tag_refuses_a_tag_that_already_exists(repos):
    assert release(repos, "prepare", "0.2.0").returncode == 0
    merge_release_branch(repos, "0.2.0")
    assert release(repos, "tag", "0.2.0", "--yes").returncode == 0
    git(repos["gui"], "tag", "-d", "v0.2.0")  # only origin has it now (release.sh fetches it back)
    before = git(repos["origin"], "rev-parse", "v0.2.0")
    r = release(repos, "tag", "0.2.0", "--yes")
    assert r.returncode != 0 and "v0.2.0 already exists" in r.stderr
    assert git(repos["origin"], "rev-parse", "v0.2.0") == before  # never moved or re-created


def test_tag_asks_first_and_a_no_creates_nothing(repos):
    assert release(repos, "prepare", "0.2.0").returncode == 0
    merge_release_branch(repos, "0.2.0")
    env = {**os.environ, "AIPOTLUCK_CLI_REMOTE": str(repos["cli"]), "GIT_ALLOW_PROTOCOL": "file"}
    r = subprocess.run(["bash", "tools/release.sh", "tag", "0.2.0"], cwd=repos["gui"], env=env,
                       input="n\n", capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "Nothing created" in r.stdout
    assert remote_tags(repos) == [] and git(repos["gui"], "tag", "-l") == ""


@pytest.mark.parametrize("bad", ["0.2", "v0.2.0.1", "latest", "0.2.0 --force"])
def test_refuses_anything_but_a_semver(repos, bad):
    r = release(repos, "prepare", bad)
    assert r.returncode != 0
    assert git(repos["gui"], "branch", "--show-current") == "main"
