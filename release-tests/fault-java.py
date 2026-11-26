#!/usr/bin/env python3
"""Backend fault shim. Used only by the black-box test via a temporary PATH."""

import os
from pathlib import Path
import re
import subprocess
import sys


real_java = [os.environ["RELEASE_TEST_REAL_JAVA"], *sys.argv[1:]]
if "tlc2.TLC" not in sys.argv or Path.cwd().name != "new":
    os.execv(real_java[0], real_java)

result = subprocess.run(real_java, capture_output=True)
sys.stderr.buffer.write(result.stderr)
if result.returncode:
    sys.stdout.buffer.write(result.stdout)
    sys.exit(result.returncode)

path = Path("graph.dot")
graph = path.read_text(encoding="utf8")
# NEW must have found the beta=4 candidate before this fault. The test checks
# the marker so a failure in the shim cannot masquerade as the intended fault.
node = re.search(r"(?m)^(-?\d+) \[label=.*qdValue = \{4\}", graph)
if not node:
    sys.exit("No NEW beta candidate in fault fixture")
mode = os.environ["RELEASE_TEST_JAVA_FAULT"]
if mode == "interrupt":
    # Simulate losing the backend before acknowledging closure, even though a
    # producing candidate and its trace are already available.
    byte_status = b"Model checking completed. No error has been found."
    if byte_status not in result.stdout:
        sys.exit("No native closure acknowledgement to suppress")
    sys.stdout.buffer.write(result.stdout.replace(byte_status, b"Backend was interrupted"))
    Path(os.environ["RELEASE_TEST_FAULT_MARKER"]).write_text(mode, encoding="utf8")
    sys.exit(143)

if mode == "missing-witness-edge":
    # Keep the final closure log and the candidate node, but disconnect it
    # from all preceding evidence. A state count alone would still look right.
    edge = rf"(?m)^-?\d+ -> {re.escape(node[1])} \[.*\];\n"
    damaged, removed = re.subn(edge, "", graph)
    if not removed:
        sys.exit("No witness edge to remove")
    path.write_text(damaged, encoding="utf8")
    sys.stdout.buffer.write(result.stdout)
    Path(os.environ["RELEASE_TEST_FAULT_MARKER"]).write_text(mode, encoding="utf8")
    sys.exit(0)

sys.exit(f"unknown test fault {mode}")
