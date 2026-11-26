"""Run the pinned wheel payload in the caller's working directory."""

import os
import platform
from pathlib import Path
import sys


def main():
    if sys.platform == "darwin" and tuple(map(int, platform.mac_ver()[0].split(".")[:2])) < (13, 5):
        print("git-quint-diff: this wheel requires macOS 13.5 or newer", file=sys.stderr)
        return 2
    payload = Path(__file__).resolve().parent / "payload"
    node = payload / "node"
    env = dict(os.environ, QUINT_HOME=str(payload / "quint-home"),
               QUINT_DIFF_QUINT_PACKAGE=str(payload / "quint"),
               QUINT_DIFF_JAVA=str(payload / "java" / "bin" / "java"))
    for key in ("NODE_OPTIONS", "NODE_PATH", "JDK_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS"):
        env.pop(key, None)
    try:
        os.execve(node, [str(node), str(payload / "git-quint-diff"), *sys.argv[1:]], env)
    except OSError as error:
        print(f"git-quint-diff: cannot run bundled Node.js: {error}", file=sys.stderr)
        return 2
