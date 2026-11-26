#!/usr/bin/env python3
"""Check source tags and replay witnesses against the full, untagged consensus scheduler.

This oracle imports neither the source binder nor the comparison driver. TLC
independently exhausts each scheduler without a history monitor. It dumps full
state graphs, which are compared by typed state values, not TLC fingerprints.
"""

import argparse
from collections import namedtuple
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


APALACHE = "0.62.4"
MODEL_DIR = "examples/classic/distributed/ConsensusAlgorithm"
REVISIONS = {"old": "883cc2c579bd11954129d207899790e80fb8c91e",
             "new": "35df73a703259890303659e421f79016897993b3"}
PARAMETERS = {"N": 3, "F": 1, "ACTUAL_FAULTS": 1, "K": 1, "MAX_ROUNDS": 2}
HISTORIES = (("receive_round_1",), ("receive_round_1", "receive_round_2"))
EXPECTED = {"old": ([0], [0]), "new": ([0, 1, 2], [0])}
FIELDS = ("round", "stage", "crashed", "newlyCrashed", "correctProcsMessages",
          "crashedProcsMessages", "procState")
TAG = "reviewReceiveRound"
NativeState = namedtuple("NativeState", FIELDS)
TaggedState = namedtuple("TaggedState", ("native", "tag"))


@dataclass(frozen=True)
class Record:
    entries: tuple

    def __getitem__(self, key):
        return dict(self.entries)[key]


UNIT = Record((("tag", "UNIT"),))
RECEIVING = Record((("Receiving", UNIT),))
COMPUTING = Record((("Computing", UNIT),))


@dataclass
class Graph:
    initial: set
    outgoing: dict
    stats: dict


TOKEN = re.compile(r'\s*(<<|>>|\|->|[{}\[\],]|-?[0-9]+|[A-Za-z][A-Za-z0-9_]*|"UNIT")')
ASSIGNMENT = re.compile(r'^/\\ ([A-Za-z_][A-Za-z_0-9]*) = ', re.M)
QUOTED = r'"(?:\\.|[^"\\])*"'
NODE = re.compile(rf'(-?\d+) \[label=({QUOTED}),(style = filled|tooltip={QUOTED})\];?')
EDGE = re.compile(r'(-?\d+) -> (-?\d+) \[label="",color="black",fontcolor="black"\];')
RANK = re.compile(r'\{rank = same; (?:-?\d+;)+}')
STATS = re.compile(r"^(\d+) states generated, (\d+) distinct states found, (\d+) states left on queue\.$", re.M)
DEPTH = re.compile(r"^The depth of the complete state graph search is (\d+)\.$", re.M)


def read_value(text):
    """Read only the TLA+ value forms printed for this model by the pinned TLC."""
    tokens = []
    text = text.strip()
    pos = 0
    while pos < len(text):
        match = TOKEN.match(text, pos)
        if not match:
            raise ValueError(f"unsupported TLC value syntax: {text}")
        tokens.append(match[1])
        pos = match.end()
    stream = iter([*tokens, None])
    token = next(stream)

    def take(expected):
        nonlocal token
        if token != expected:
            raise ValueError(f"expected {expected} in TLC value: {text}")
        token = next(stream)

    def collection(end, item):
        if token == end:
            take(end)
            return []
        items = [item()]
        while token == ",":
            take(",")
            items.append(item())
        take(end)
        return items

    def field():
        key = token
        if key is None or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
            raise ValueError(f"invalid TLC record field: {text}")
        take(key)
        take("|->")
        return key, value()

    def value():
        if token == "{":
            take("{")
            items = collection("}", value)
            result = frozenset(items)
            if len(result) != len(items):
                raise ValueError(f"duplicate TLC set element: {text}")
            return result
        if token == "<<":
            take("<<")
            return tuple(collection(">>", value))
        if token == "[":
            take("[")
            items = collection("]", field)
            if not items or len(dict(items)) != len(items):
                raise ValueError(f"empty or duplicate TLC record fields: {text}")
            return Record(tuple(sorted(items)))
        if token == '"UNIT"':
            take('"UNIT"')
            return "UNIT"
        if token is not None and re.fullmatch(r"-?[0-9]+", token):
            number = int(token)
            take(token)
            return number
        raise ValueError(f"unexpected TLC value: {text}")

    parsed = value()
    if token is not None:
        raise ValueError(f"trailing syntax in TLC value: {text}")
    return parsed


def named_values(state, *, tagged, strict=True):
    if not isinstance(state, dict):
        raise ValueError("expected a TLC state object")
    expected = (*FIELDS, TAG) if tagged else FIELDS
    values = {}
    for name, value in state.items():
        fields = [field for field in expected if name == field or name.endswith("_" + field)]
        if not fields and not strict:
            continue  # the comparison report can also contain monitor fields
        if len(fields) != 1 or fields[0] in values:
            raise ValueError(f"unexpected or duplicate state variable: {name}")
        values[fields[0]] = value
    if values.keys() != set(expected):
        raise ValueError(f"incomplete TLC state (expected all seven native variables): {state}")
    return values


def parse_state(raw, tagged):
    label = json.loads(raw)
    assignments = list(ASSIGNMENT.finditer(label))
    if not assignments or assignments[0].start() != 0:
        raise ValueError("unexpected TLC state assignment format")
    fields = {}
    ends = [m.start() for m in assignments[1:]] + [len(label)]
    for match, end in zip(assignments, ends, strict=True):
        if match[1] in fields:
            raise ValueError(f"duplicate TLC state variable: {match[1]}")
        fields[match[1]] = read_value(label[match.end():end])
    fields = named_values(fields, tagged=tagged)
    tag = fields.pop(TAG, None)
    native = NativeState(**fields)
    if tagged and type(tag) is not int:
        raise ValueError("tag must be a round number")
    return TaggedState(native, tag) if tagged else native


def read_graph(dot, stats, *, tagged):
    header = ["strict digraph DiskGraph {", "node [shape=box,style=rounded]", "nodesep=0.35;",
              "subgraph cluster_graph {", 'color="white";']
    lines = dot.strip().splitlines()
    if lines[:5] != header or lines[-2:] != ["}", "}"]:
        raise ValueError("unexpected TLC DOT graph framing")
    nodes, initial, edges = {}, set(), []
    for line in lines[5:-2]:
        if match := NODE.fullmatch(line):
            key, label, style = match.groups()
            if key in nodes:
                raise ValueError("duplicate TLC DOT state ID")
            nodes[key] = parse_state(label, tagged)
            if style == "style = filled":
                initial.add(key)
        elif match := EDGE.fullmatch(line):
            edges.append(match.groups())
        elif not RANK.fullmatch(line):
            raise ValueError(f"unexpected TLC DOT graph row: {line}")
    if (not initial or len(nodes) != stats["distinct"] or len(set(nodes.values())) != len(nodes)
            or len(initial) + len(edges) != stats["generated"]
            or any(source not in nodes or target not in nodes for source, target in edges)):
        raise ValueError("TLC DOT graph does not account for the complete search")
    outgoing = {state: set() for state in nodes.values()}
    for source, target in edges:
        outgoing[nodes[source]].add(nodes[target])
    roots = {nodes[key] for key in initial}
    reached = set(roots)
    frontier = list(roots)
    while frontier:
        unseen = outgoing[frontier.pop()] - reached
        reached.update(unseen)
        frontier.extend(unseen)
    if reached != outgoing.keys():
        raise ValueError("TLC DOT graph contains unreachable states")
    return Graph(roots, outgoing, {**stats, "initial": len(roots), "edges": sum(map(len, outgoing.values()))})


def run(args, *, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=120)
    if result.returncode:
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        raise ValueError(f"{args[0]} exited with {result.returncode}:\n{output}")
    return result.stdout


def native_snapshot(repo, revision, directory):
    directory.mkdir()
    git = ["git", "--no-replace-objects", "--literal-pathspecs", "-C", str(repo)]
    for name in ("ConsensusAlg.qnt", "KSetAgreementConsensus.qnt"):
        path = f"{MODEL_DIR}/{name}"
        tree = run([*git, "ls-tree", "-z", "--full-tree", revision, "--", path]).decode("utf-8")
        blob = re.fullmatch(r"100(?:644|755) blob ([0-9a-f]+)\t" + re.escape(path) + "\0", tree)
        if not blob:
            raise ValueError(f"expected regular committed file: {revision}:{path}")
        (directory / name).write_bytes(run([*git, "cat-file", "blob", blob[1]]))
    entry = directory / "native_oracle.qnt"
    entry.write_bytes(Path(__file__).with_name(entry.name).read_bytes())
    return entry


def explore(entry, work, jar, *, tagged):
    work.mkdir()
    module = entry.stem
    tla = run([
        "quint", "compile", str(entry), "--main", module, "--target", "tlaplus",
        "--init", "reviewInit" if tagged else "init", "--step", "reviewStep" if tagged else "step",
        "--invariant", "true",
        "--verbosity", "0", "--apalache-version", APALACHE, "--server-endpoint",
        os.environ.get("CONSENSUS_PROJECTION_ENDPOINT", "localhost:19856"),
    ], cwd=work)
    (work / f"{module}.tla").write_bytes(tla)
    (work / f"{module}.cfg").write_text("INIT q_init\nNEXT q_step\n", encoding="utf-8")
    log = run([
        "java", "-Xmx512m", "-XX:+UseParallelGC", "-Duser.language=en", "-Duser.country=US", "-cp", str(jar),
        "tlc2.TLC", "-deadlock", "-workers", "1", "-fp", "0", "-noGenerateSpecTE", "-dump", "dot", "graph.dot",
        f"{module}.tla",
    ], cwd=work).decode("utf-8")
    rows, depth = STATS.findall(log), DEPTH.findall(log)
    if (len(rows) != 1 or rows[0][2] != "0" or len(depth) != 1
            or "Model checking completed. No error has been found." not in log):
        raise ValueError(f"TLC did not establish closure:\n{log}")
    stats = dict(zip(("generated", "distinct", "queued"), map(int, rows[0]), strict=True))
    return read_graph((work / "graph.dot").read_text(encoding="utf-8"),
                      {**stats, "depth": int(depth[0])}, tagged=tagged)


def receive_round(source, target):
    # This independent, model-specific oracle uses the stage sequence of the
    # untagged scheduler, not the action's transition predicate or compiled name.
    if source.stage != RECEIVING:
        return 0
    if source.round not in (1, 2) or source.round != target.round or target.stage != COMPUTING:
        raise ValueError("unexpected native stage/round at receive")
    return source.round


def check_projection(native, tagged):
    if ({state.native for state in tagged.initial} != native.initial
            or any(state.tag != 0 for state in tagged.initial)):
        raise ValueError("source tags changed native initialization")
    if {state.native for state in tagged.outgoing} != native.outgoing.keys():
        raise ValueError("tagged reachable states do not project to native reachable states")
    # Compare per tagged state, not the union across states with the same projection.
    for source, targets in tagged.outgoing.items():
        if {target.native for target in targets} != native.outgoing[source.native]:
            raise ValueError(f"tag erasure changed outgoing native transitions at {source}")
    for source, targets in tagged.outgoing.items():
        if any(target.tag != receive_round(source.native, target.native) for target in targets):
            raise ValueError(f"incorrect receive tag on outgoing native transition at {source}")


def omissions(state):
    return sum(frozenset() in state["S"] for state in state.procState)


def label(round_number):
    return f"receive_round_{round_number}" if round_number else None


def native_outcomes(native):
    outcomes = {history: set() for history in HISTORIES}
    frontier = [(state, ()) for state in native.initial]
    visited = set(frontier)
    while frontier:
        source, prefix = frontier.pop()
        for target in native.outgoing[source]:
            public = label(receive_round(source, target))
            history = (*prefix, public) if public else prefix
            if public:
                if history not in outcomes:
                    raise ValueError(f"unexpected history in the original scheduler: {history}")
                outcomes[history].add(omissions(target))
                if history == HISTORIES[-1]:
                    continue
            item = (target, history)
            if item not in visited:
                visited.add(item)
                frontier.append(item)
    return tuple(sorted(outcomes[history]) for history in HISTORIES)


def witness_value(value, *, sequence=False):
    # TLC's JSON uses lists for both sequences and sets. procState is the
    # total map on 1..2, emitted as a sequence; all other lists here are sets.
    if sequence and not isinstance(value, list):
        raise ValueError("witness procState must be in process order")
    if type(value) is int or value == "UNIT":
        return value
    if isinstance(value, dict):
        return Record(tuple(sorted((k, witness_value(v)) for k, v in value.items())))
    if isinstance(value, list):
        items = tuple(map(witness_value, value))
        if sequence:
            return items
        result = frozenset(items)
        if len(result) != len(items):
            raise ValueError("duplicate element in witness set")
        return result
    raise ValueError(f"unsupported TLC witness value: {value!r}")


def replay(native, row, history):
    trace = row["trace"]
    if not trace:
        raise ValueError("empty witness trace")
    seen = []
    prior = None
    for index, frame in enumerate(trace):
        state = frame["state"]
        fields = named_values(state, tagged=True, strict=False)
        tag = fields.pop(TAG)
        native_state = NativeState(**{k: witness_value(v, sequence=(k == "procState")) for k, v in fields.items()})
        if index == 0:
            if native_state not in native.initial:
                raise ValueError("witness does not replay through the original init")
            round_number, call = 0, "init"
        else:
            if native_state not in native.outgoing[prior]:
                raise ValueError(f"witness does not replay through the original scheduler at frame {index}")
            round_number = receive_round(prior, native_state)
            call = "receiveMessages" if round_number else "hidden"
        public = label(round_number)
        if type(tag) is not int or tag != round_number or frame["call"] != call or frame["public_label"] != public:
            raise ValueError(f"witness call labels or tag disagree with the native scheduler at frame {index}")
        if public:
            seen.append(public)
        phase = state["ReviewPhase"]
        if type(phase) is not int or phase != len(seen):
            raise ValueError(f"witness monitor phase disagrees with the native history at frame {index}")
        prior = native_state
    if (tuple(seen) != history or public != history[-1]
            or type(row["omissions"]) is not int or omissions(prior) != row["omissions"]):
        raise ValueError("witness does not realize the declared history and outcome")


def check_report(report, case, native):
    old, new = report["revisions"]["old"], report["revisions"]["new"]
    scope = report["scope"]
    if (report["status"] != "exhaustive" or old != REVISIONS["old"] or new not in REVISIONS.values()
            or REVISIONS[case] not in (old, new) or scope["max_original_transitions"] is not None
            or scope["parameters"] != PARAMETERS or scope["public_histories"] != list(map(list, HISTORIES))):
        raise ValueError("expected an exhaustive report for the designated consensus instance and revision")
    new_case = "old" if new == old else "new"
    count = 0
    for history, entry, old_set, new_set in zip(HISTORIES, report["histories"], EXPECTED["old"],
                                                EXPECTED[new_case], strict=True):
        if (entry["public_history"] != list(history) or entry["removed"] != sorted(set(old_set) - set(new_set))
                or entry["added"] != sorted(set(new_set) - set(old_set))):
            raise ValueError("report histories or deltas disagree with the native oracle")
        for side, revision, expected in (("old", old, old_set), ("new", new, new_set)):
            rows = entry["outcomes"][side]
            if [row["omissions"] for row in rows] != expected:
                raise ValueError("report outcomes disagree with the native oracle")
            if revision == REVISIONS[case]:
                for row in rows:
                    replay(native, row, history)
                    count += 1
    return count


def check_revision(repo, case, tagged_directory, report=None):
    if run(["quint", "--version"]).strip() != b"0.33.1":
        raise ValueError("run this oracle with Quint 0.33.1 from nix develop")
    jar = Path(os.environ["QUINT_HOME"]).resolve() / f"apalache-dist-{APALACHE}/apalache/lib/apalache.jar"
    revision = REVISIONS[case]
    with tempfile.TemporaryDirectory(prefix="quint-consensus-projection-") as tmp:
        root = Path(tmp)
        entry = native_snapshot(repo, revision, root / "original")
        native = explore(entry, root / "native-graph", jar, tagged=False)
        tagged = explore(tagged_directory.resolve() / "review.qnt", root / "tagged-graph", jar, tagged=True)
        check_projection(native, tagged)
        outcomes = native_outcomes(native)
        if outcomes != EXPECTED[case]:
            raise ValueError(f"unexpected outcomes in the original scheduler: {outcomes}")
        replayed = 0 if report is None else check_report(report, case, native)
    return {"revision": revision, "native": native.stats, "tagged": tagged.stats, "replayed_witnesses": replayed,
            "histories": [{"public_history": history, "omissions": values}
                          for history, values in zip(HISTORIES, outcomes, strict=True)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("case", choices=REVISIONS)
    parser.add_argument("tagged_directory", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = None if args.report is None else json.loads(args.report.read_text(encoding="utf-8"))
        if args.report is not None and not isinstance(report, dict):
            raise ValueError("expected a comparison report object")
        print(json.dumps(check_revision(args.checkout, args.case, args.tagged_directory, report), indent=2))
    except (OSError, KeyError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"consensus projection oracle failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
