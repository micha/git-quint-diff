#!/usr/bin/env python3
"""Create the controlled three-revision review in a new Git repository."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess


FIXTURES = Path(__file__).with_name("fixtures")
REVISIONS = ("old", "refactor", "changed")


def make_fixture(repo):
    repo.mkdir()
    # Make the commit IDs reproducible across machines and invocation times.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="Quint Diff Fixture", GIT_COMMITTER_NAME="Quint Diff Fixture",
               GIT_AUTHOR_EMAIL="quint-fixture@example.invalid",
               GIT_COMMITTER_EMAIL="quint-fixture@example.invalid", TZ="UTC")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, env=env, text=True).strip()

    git("init", "--quiet", "--template=", "--object-format=sha1", "--initial-branch=review-fixture")
    commits = {}
    for index, revision in enumerate(REVISIONS, start=1):
        stamp = f"2000-01-0{index}T00:00:00+0000"
        env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        for name in ("marks.qnt", "workflow.qnt"):
            shutil.copyfile(FIXTURES / revision / name, repo / name)
        git("add", "--", "marks.qnt", "workflow.qnt")
        git("commit", "--quiet", "--message", revision)
        git("tag", revision)
        commits[revision] = git("rev-parse", "HEAD")
    return commits


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="new directory for the fixture repository")
    args = parser.parse_args()
    for revision, commit in make_fixture(args.directory).items():
        print(f"{revision} {commit}")
