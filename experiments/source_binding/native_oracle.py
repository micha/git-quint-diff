#!/usr/bin/env python3
"""Check a source-binding fixture's full native and tagged transition graphs.

Compile the original Git tree and the supplied tagged source independently
with pinned Quint. Compare TLC's complete graphs before any history filter.
This deliberately uses no binder or comparison implementation.
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile


APALACHE = "0.62.4"
MODULE = "workflow"
TAG = "reviewCall"
QUOTED = r'"(?:\\.|[^"\\])*"'
NODE = re.compile(rf'(-?\d+) \[label=({QUOTED}),(style = filled|tooltip={QUOTED})\];?')
EDGE = re.compile(r'-?\d+ -> -?\d+ \[label="",color="black",fontcolor="black"\];')
STATS = re.compile(r"^(\d+) states generated, (\d+) distinct states found, (\d+) states left on queue\.$", re.M)


@dataclass
class Graph:
    states: dict
    initial: set
    edges: set
    stats: dict


def run(args, *, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=120)
    if result.returncode != 0:
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        raise ValueError(f"{args[0]} exited with {result.returncode}:\n{output}")
    return result.stdout


def native_snapshot(repo, revision, directory):
    git = ["git", "--no-replace-objects", "-C", str(repo)]
    commit = run([*git, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}"]).decode().strip()
    entries = run([*git, "ls-tree", "-r", "-z", "--full-tree", commit]).decode("utf-8")
    for entry in filter(None, entries.split("\0")):
        metadata, name = entry.split("\t", 1)
        path = PurePosixPath(name)
        if path.suffix != ".qnt":
            continue
        mode, kind, blob = metadata.split()
        if mode not in {"100644", "100755"} or kind != "blob" or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"not a regular Quint fixture path: {name}")
        dest = directory / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(run([*git, "cat-file", "blob", blob]))
    return commit


def read_graph(dot, stats):
    # The pinned TLC DOT format describes concrete, unprojected states. The
    # fixture only uses an integer and, when tagged, a single ASCII string.
    states, initial, edges = {}, set(), set()
    if not dot.startswith("strict digraph DiskGraph {") or not dot.rstrip().endswith("}"):
        raise ValueError("unexpected TLC DOT graph format")
    for line in map(str.strip, dot.splitlines()):
        if match := NODE.fullmatch(line):
            key, quoted, style = match.groups()
            state = {}
            for assignment in json.loads(quoted).splitlines():
                field = re.fullmatch(r'(?:/\\ )?([A-Za-z_][A-Za-z_0-9]*) = (-?\d+|"[a-z]+")', assignment)
                if not field or field[1] in state:
                    raise ValueError(f"unexpected TLC state: {assignment}")
                state[field[1]] = json.loads(field[2])
            if key in states:
                raise ValueError("duplicate TLC DOT state ID")
            states[key] = state
            if style == "style = filled":
                initial.add(key)
        elif EDGE.fullmatch(line):
            source, _, target, *_ = line.split()
            edges.add((source, target))
        elif re.match(r"^-?\d", line):
            raise ValueError(f"unexpected TLC DOT node or edge: {line}")
    if (not initial or len(states) != stats["distinct"]
            or any(source not in states or target not in states for source, target in edges)):
        raise ValueError("TLC DOT graph does not account for the complete search")
    return Graph(states, initial, edges, {**stats, "initial": len(initial), "edges": len(edges)})


def explore(source, work, jar, init, step):
    work.mkdir()
    tla = run([
        "quint", "compile", str(source / f"{MODULE}.qnt"), "--main", MODULE,
        "--target", "tlaplus", "--init", init, "--step", step, "--invariant", "true", "--verbosity", "0",
        "--apalache-version", APALACHE, "--server-endpoint",
        os.environ.get("SOURCE_BINDING_ORACLE_ENDPOINT", "localhost:19855"),
    ], cwd=work)
    (work / f"{MODULE}.tla").write_bytes(tla)
    (work / f"{MODULE}.cfg").write_text("INIT q_init\nNEXT q_step\n", encoding="utf-8")
    log = run([
        "java", "-Xmx512m", "-XX:+UseParallelGC", "-Duser.language=en", "-Duser.country=US", "-cp", str(jar),
        "tlc2.TLC", "-deadlock", "-workers", "1", "-fp", "0", "-noGenerateSpecTE", "-dump", "dot", "graph.dot",
        f"{MODULE}.tla",
    ], cwd=work).decode("utf-8")
    rows = STATS.findall(log)
    if len(rows) != 1 or rows[0][2] != "0" or "Model checking completed. No error has been found." not in log:
        raise ValueError(f"TLC did not establish closure:\n{log}")
    stats = dict(zip(("generated", "distinct", "queued"), map(int, rows[0]), strict=True))
    return read_graph((work / "graph.dot").read_text(encoding="utf-8"), stats)


def check_projection(case, native, tagged):
    (field,) = native.states[min(native.initial)]
    if not (field == "x" or field.endswith("_x")):
        raise ValueError(f"expected one native variable x, got {field}")
    for graph, fields in ((native, {field}), (tagged, {field, TAG})):
        if any(state.keys() != fields or type(state[field]) is not int for state in graph.states.values()):
            raise ValueError("TLC trace not over the expected complete state variables")

    beta = 4 if case == "changed" else 3
    # Hand-written oracle for the fixture; these triples are not read from a
    # binding, generated source, or comparison report.
    expected = {(0, "hidden", 1), (0, "hidden", 2), (3, "hidden", 0)}
    expected |= {(x, label, target) for x in (1, 2) for label, target in (("alpha", 3), ("beta", beta))}
    if beta == 4:
        expected.add((4, "hidden", 0))
    native_x = {key: state[field] for key, state in native.states.items()}
    tagged_x = {key: state[field] for key, state in tagged.states.items()}
    if ({native_x[key] for key in native.initial} != {0}
            or {tagged_x[key] for key in tagged.initial} != {0}
            or {tagged.states[key][TAG] for key in tagged.initial} != {"init"}):
        raise ValueError("native or tagged initial states disagree with the fixture")
    original = {(native_x[source], native_x[target]) for source, target in native.edges}
    if original != {(x, y) for x, _, y in expected}:
        raise ValueError(f"unexpected native edges: {sorted(original)}")

    # Check each augmented state, not just the union after projecting all
    # edges: a monitor-state-dependent loss could be hidden by another copy.
    outgoing = defaultdict(set)
    for source, target in tagged.edges:
        outgoing[source].add((tagged.states[target][TAG], tagged_x[target]))
    if set(tagged_x.values()) != set(native_x.values()):
        raise ValueError("tagged reachable states do not project to the native reachable states")
    for key, x in tagged_x.items():
        projected = {y for _, y in outgoing[key]}
        if projected != {y for prior, y in original if prior == x}:
            raise ValueError(f"tag erasure changed outgoing native transitions at {tagged.states[key]}")
        if outgoing[key] != {(label, y) for prior, label, y in expected if prior == x}:
            raise ValueError(f"unexpected call tags or targets at {tagged.states[key]}")
    return sorted(expected)


def check_revision(repo, revision, case, tagged_source):
    if run(["quint", "--version"]).strip() != b"0.33.1":
        raise ValueError("run this oracle with Quint 0.33.1 from nix develop")
    jar = Path(os.environ["QUINT_HOME"]).resolve() / f"apalache-dist-{APALACHE}/apalache/lib/apalache.jar"
    step = {"old": "step", "refactor": "dispatch", "changed": "dispatch"}[case]
    with tempfile.TemporaryDirectory(prefix="quint-source-binding-oracle-") as tmp:
        directory = Path(tmp)
        commit = native_snapshot(repo, revision, directory / "original")
        native = explore(directory / "original", directory / "native", jar, "init", step)
        tagged = explore(tagged_source.resolve(), directory / "tagged", jar, "reviewInit", step)
        transitions = check_projection(case, native, tagged)
    return {"revision": commit, "case": case, "native": native.stats, "tagged": tagged.stats,
            "tagged_transitions": transitions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("revision")
    parser.add_argument("case", choices=("old", "refactor", "changed"))
    parser.add_argument("tagged_directory", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(check_revision(args.checkout, args.revision, args.case, args.tagged_directory), indent=2))
    except (OSError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"source binding oracle failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
