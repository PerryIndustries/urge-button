import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from updater import Updater  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def make_repos(tmp_path):
    origin, clone, other = tmp_path / "origin.git", tmp_path / "clone", tmp_path / "other"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    for repo in (clone, other):
        subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "t")
        git(repo, "checkout", "-q", "-B", "main")
    (other / "app.py").write_text("v1")
    git(other, "add", ".")
    git(other, "commit", "-qm", "first")
    git(other, "push", "-q", "origin", "main")
    git(clone, "pull", "-q", "origin", "main")
    return clone, other


def publish(other, text, msg):
    (other / "app.py").write_text(text)
    git(other, "commit", "-qam", msg)
    git(other, "push", "-q", "origin", "main")


def test_pulls_a_new_version(tmp_path):
    clone, other = make_repos(tmp_path)
    u = Updater(clone)
    assert u.check() is None and u.status == "Up to date"
    publish(other, "v2", "Breathing guide")
    assert u.check().endswith("Breathing guide")
    assert (clone / "app.py").read_text() == "v2"


def test_never_overwrites_local_edits(tmp_path):
    clone, other = make_repos(tmp_path)
    publish(other, "v2", "update")
    (clone / "app.py").write_text("my own change")
    u = Updater(clone)
    assert u.check() is None and "local edits" in u.status
    assert (clone / "app.py").read_text() == "my own change"


def test_skips_other_branches(tmp_path):
    clone, other = make_repos(tmp_path)
    git(clone, "checkout", "-q", "-b", "experiment")
    publish(other, "v2", "update")
    u = Updater(clone)
    assert u.check() is None and "experiment" in u.status
