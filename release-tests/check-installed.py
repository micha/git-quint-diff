#!/usr/bin/env python3
"""Exercise an installed package, using the development shell only for oracles."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import unittest


HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bin_dir", type=Path, help="profile bin directory containing the installed subcommand")
    parser.add_argument("--dml-repo", required=True, type=Path, help="local Git repository with both historical DML commits")
    parser.add_argument("--git", type=Path, help="caller Git for the installed process (defaults to Git on PATH)")
    args = parser.parse_args()
    launcher = args.bin_dir / "git-quint-diff"
    if not os.access(launcher, os.X_OK) or launcher.resolve().is_relative_to(HERE.parent):
        parser.error("bin_dir must contain an executable installed outside the source tree")
    if not args.dml_repo.is_dir():
        parser.error("--dml-repo must be a local Git repository")
    if not all(shutil.which(name) for name in ("git", "quint", "java")) or not os.getenv("QUINT_HOME"):
        parser.error("run the harness in nix develop for independent fixture/oracle tools")
    caller_git = (args.git or Path(shutil.which("git"))).absolute()
    print(f"Caller Git: {subprocess.check_output([str(caller_git), '--version'], text=True).strip()}", flush=True)
    os.environ.update(RELEASE_TEST_INSTALLED_BIN=str(args.bin_dir.resolve()),
                      RELEASE_TEST_DML_REPO=str(args.dml_repo.resolve()),
                      RELEASE_TEST_CALLER_GIT=str(caller_git))
    loader = unittest.TestLoader()
    tests = loader.discover(str(HERE), pattern="test_cli.py")
    tests.addTests(loader.discover(str(HERE), pattern="test_consensus.py"))
    tests.addTests(loader.discover(str(HERE), pattern="test_dml.py"))
    return 0 if unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
