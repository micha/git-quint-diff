"""Run the installed CLI on the offline upstream consensus fixture."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from consensus_fixture import COMMITS, materialize


def demo(executable):
    # Don't let Git settings from the caller redirect our disposable repository.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_ALLOW_PROTOCOL="")
    review = Path(__file__).resolve().parents[1] / "docs/consensus-review.json"
    try:
        with TemporaryDirectory(prefix="git-quint-diff-demo-") as scratch:
            repo = Path(scratch) / "model"
            materialize(repo, env)
            return subprocess.run(
                [executable, "--review", str(review), COMMITS["old"], COMMITS["new"]],
                cwd=repo, env=env,
            ).returncode
    except (AssertionError, OSError, subprocess.SubprocessError) as error:
        print(f"Consensus demo failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(demo(sys.argv[1]))
