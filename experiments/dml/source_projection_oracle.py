#!/usr/bin/env python3
"""Check tag erasure and replay witnesses on DML's full original scheduler.

No source-binder or history-monitor code is used here. The original event is
an independent oracle for the call tags in these two fixtures only.
"""

import argparse
from array import array
from collections import deque, namedtuple
from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


MODEL = "tests/recorded_return_design.qnt"
REVISIONS = {"old": "819ac9d9c496bf652ea85af12b3369844df2b1e4",
             "new": "c540078318bf52313a33d856c7825d6b09566b17"}
LABELS = {1: "stage_alternate", 2: "publish_alternate_expected_3", 3: "publish_alternate_expected_minus_2"}
EXPECTED = {"old": {2: [0, 12], 3: [0, 12]}, "new": {2: [0], 3: [0, 12]}}
ARGUMENTS = {"stage": {"wanted": 12}, "publish": {"wanted": 12, "expectedMain": 3, "aliasesMain": False, "failAt": 0},
             "expected_factors": {"2": 3, "3": -2}}
TAG = "reviewCall"
FIELDS = ("returning", "worker", "source", "event")
Native = namedtuple("Native", FIELDS)
Tagged = namedtuple("Tagged", ("native", "tag"))
Worker = namedtuple("Worker", "pin objects selected bundle")
Source = namedtuple("Source", "main returned producerPin objects")
Event = namedtuple("Event", "command wanted receipt oldBundle before expectedMain expectedFactor aliasesMain failAt")
RECORD_FIELDS = {kind: frozenset(kind._fields) for kind in (Worker, Source, Event)}
OLD_EVENT_FIELDS = RECORD_FIELDS[Event] - {"expectedFactor"}
ATOM_TYPES = {"command": str, "aliasesMain": bool}

APALACHE = "0.62.4"
TOOL_TIMEOUT = 300  # full DOT export; not a model transition bound
HEADER = ("strict digraph DiskGraph {", "node [shape=box,style=rounded]", "nodesep=0.35;",
          "subgraph cluster_graph {", 'color="white";')
EDGE = '[label="",color="black",fontcolor="black"];'
DOT_ROWS = re.compile(r"(-?\d+)(?: -> (-?\d+))? \[")
RANK = re.compile(r"\{rank = same; (?:-?\d+;)+\}")
TOKEN = re.compile(r'\|->|[{}\[\],]|-?\d+|[A-Za-z][A-Za-z0-9_]*|"[a-z]*"|\S')
FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
STATS = re.compile(r"^(\d+) states generated, (\d+) distinct states found, (\d+) states left on queue\.$", re.M)
DEPTH = re.compile(r"^The depth of the complete state graph search is (\d+)\.$", re.M)


@dataclass
class Graph:
    states: list
    index: dict
    initial: set
    outgoing: list
    stats: dict


def read_value(text):
    """Read the record, int-set, string, integer and boolean subset of TLC."""
    tokens = iter(TOKEN.findall(text))
    token = next(tokens, None)

    def take():
        nonlocal token
        last, token = token, next(tokens, None)
        return last

    def need(expected):
        if token != expected:
            raise ValueError(f"expected {expected!r} in TLC value: {text}")
        take()

    def value():
        if token == "[":
            take()
            record = {}
            while True:
                key = take()
                if not isinstance(key, str) or not FIELD.fullmatch(key) or key in record:
                    raise ValueError(f"missing or duplicate TLC record field: {text}")
                need("|->")
                record[key] = value()
                if token != ",":
                    break
                take()
            need("]")
            return record
        if token == "{":
            take()
            items = []
            if token != "}":
                items.append(value())
                while token == ",":
                    take()
                    items.append(value())
            need("}")
            return items
        atom = take()
        if atom == "TRUE" or atom == "FALSE":
            return atom == "TRUE"
        if atom is not None:
            if atom[0] in "-0123456789":
                return int(atom)
            if atom[0] == '"' and len(atom) > 1:
                return atom[1:-1]
        raise ValueError(f"unsupported TLC value: {text}")

    result = value()
    if token is not None:
        raise ValueError(f"trailing TLC syntax: {text}")
    return result


def require_kind(value, kind):
    if type(value) is not kind:
        raise ValueError(f"expected {kind.__name__}, got {value!r}")
    return value


@lru_cache(maxsize=32768)
def intern_source(*fields):
    # A source record recurs in every report made against that source.
    return Source(*fields)


def record(value, kind, *, old=False):
    require_kind(value, dict)
    fields = kind._fields
    expected = OLD_EVENT_FIELDS if old else RECORD_FIELDS[kind]
    if value.keys() != expected:
        raise ValueError(f"unexpected {kind.__name__} fields: {value}")
    items = []
    for key in fields:
        if key == "expectedFactor" and old:
            item = None
        elif key == "objects":
            values = require_kind(value[key], list)
            item = frozenset(require_kind(n, int) for n in values)
            if len(item) != len(values):
                raise ValueError(f"duplicate set members: {values}")
        elif key == "before":
            item = record(value[key], Source)
        else:
            item = require_kind(value[key], ATOM_TYPES.get(key, int))
        items.append(item)
    return intern_source(*items) if kind is Source else kind(*items)


def field_value(name, value, old):
    if name == "event":
        return record(value, Event, old=old)
    if name == "source":
        return record(value, Source)
    if name == "worker":
        return record(value, Worker)
    return require_kind(value, bool if name == "returning" else int)


@lru_cache(maxsize=32768)
def dot_field(name, value, old):
    return field_value(name, read_value(value), old)


def dot_state(raw, *, tagged, old):
    label = json.loads(raw)
    if not label.startswith("/\\ "):
        raise ValueError("unexpected TLC state assignment format")
    fields = {}
    for item in label[3:].split("\n/\\ "):
        name, sep, value = item.partition(" = ")
        if not sep or name in fields or name not in (*FIELDS, TAG):
            raise ValueError(f"unexpected or duplicate TLC variable: {name}")
        fields[name] = dot_field(name, value, old)
    if fields.keys() != set((*FIELDS, TAG) if tagged else FIELDS):
        raise ValueError(f"incomplete TLC state: {label}")
    tag = fields.pop(TAG, None)
    native = Native(**fields)
    return Tagged(native, tag) if tagged else native


def read_graph(path, stats, *, tagged, old):
    # Stream labels; the duplicated DOT tooltip text would otherwise take GiB.
    # Fingerprints resolve references within a dump, never across the two dumps.
    states, index, ids, initial = [], {}, {}, set()
    sources, targets = array("q"), array("q")
    with path.open(encoding="utf-8") as dot:
        if tuple(dot.readline().rstrip("\n") for _ in HEADER) != HEADER:
            raise ValueError("unexpected TLC DOT header")
        for line in dot:
            line = line.rstrip("\n")
            if line == "}":
                if dot.read(3) not in ("}", "}\n"):
                    raise ValueError("unexpected TLC DOT trailer")
                break
            row = DOT_ROWS.match(line)
            if row is None:
                if RANK.fullmatch(line):
                    continue
                raise ValueError(f"unexpected TLC DOT row: {line[:120]}")
            node_id = int(row[1])
            if row[2] is not None:
                if not line.endswith(EDGE) or row.end() - 1 + len(EDGE) != len(line):
                    raise ValueError("unexpected TLC DOT edge")
                sources.append(node_id)
                targets.append(int(row[2]))
                continue
            if not line.startswith("label=", row.end()) or node_id in ids:
                raise ValueError("unexpected or duplicate TLC DOT node")
            label = line[row.end() + len("label="):]
            if label.endswith(",style = filled]"):
                raw = label.removesuffix(",style = filled]")
                initial.add(len(states))
            else:
                raw, sep, tooltip = label.partition(",tooltip=")
                if not sep or tooltip != raw + "];":
                    raise ValueError("unexpected TLC DOT node label or tooltip")
            state = dot_state(raw, tagged=tagged, old=old)
            if state in index:
                raise ValueError("duplicate typed TLC state")
            index[state] = ids[node_id] = len(states)
            states.append(state)
        else:
            raise ValueError("missing TLC DOT trailer")
    if not initial or len(states) != stats["distinct"] or len(initial) + len(sources) != stats["generated"]:
        raise ValueError("TLC DOT graph does not account for the complete search")
    outgoing = [None] * len(states)
    for source, target in zip(sources, targets, strict=True):
        s, t = ids.get(source), ids.get(target)
        if s is None or t is None:
            raise ValueError("TLC DOT edge references an unknown node")
        if outgoing[s] is None:
            outgoing[s] = [t]
        else:
            outgoing[s].append(t)
    for i, items in enumerate(outgoing):
        outgoing[i] = tuple(sorted(set(items))) if items else ()
    reached = bytearray(len(states))
    agenda = list(initial)
    for root in initial:
        reached[root] = 1
    for source in agenda:
        for target in outgoing[source]:
            if not reached[target]:
                reached[target] = 1
                agenda.append(target)
    if len(agenda) != len(states):
        raise ValueError("TLC DOT graph contains unreachable states")
    return Graph(states, index, initial, outgoing, {**stats, "initial": len(initial),
                                                   "edges": sum(map(len, outgoing)), "dot_bytes": path.stat().st_size})


def run(args, *, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=TOOL_TIMEOUT,
                            env={**os.environ, "LC_ALL": "C", "NO_COLOR": "1"})
    if result.returncode:
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        raise ValueError(f"{args[0]} exited with {result.returncode}:\n{output}")
    return result.stdout


def native_snapshot(repo, revision, directory):
    directory.mkdir()
    git = ["git", "--no-replace-objects", "--literal-pathspecs", "-C", str(repo)]
    tree = run([*git, "ls-tree", "-z", "--full-tree", revision, "--", MODEL]).decode("utf-8")
    blob = re.fullmatch(r"100(?:644|755) blob ([0-9a-f]+)\t" + re.escape(MODEL) + "\0", tree)
    if not blob:
        raise ValueError(f"expected regular committed file: {revision}:{MODEL}")
    entry = directory / Path(MODEL).name
    entry.write_bytes(run([*git, "cat-file", "blob", blob[1]]))
    return entry


def explore(quint, jar, entry, work, *, tagged, old):
    work.mkdir()
    module = entry.stem
    tla = run([
        str(quint), "compile", str(entry), "--main", module, "--target", "tlaplus",
        "--init", "reviewInit" if tagged else "init", "--step", "reviewStep" if tagged else "step",
        "--verbosity", "0", "--apalache-version", APALACHE, "--server-endpoint",
        os.environ.get("DML_PROJECTION_ENDPOINT", "localhost:19888"),
    ], cwd=work)
    (work / f"{module}.tla").write_bytes(tla)
    (work / f"{module}.cfg").write_text("INIT q_init\nNEXT q_step\n", encoding="utf-8")
    log = run([
        "java", "-Xmx2G", "-XX:+UseParallelGC", "-Duser.language=en", "-Duser.country=US", "-cp", str(jar),
        "tlc2.TLC", "-deadlock", "-workers", "1", "-fp", "0", "-noGenerateSpecTE", "-dump", "dot", "graph.dot",
        f"{module}.tla",
    ], cwd=work).decode("utf-8")
    rows, depth = STATS.findall(log), DEPTH.findall(log)
    if (len(rows) != 1 or rows[0][2] != "0" or len(depth) != 1
            or "Model checking completed. No error has been found." not in log):
        raise ValueError(f"TLC did not establish closure:\n{log}")
    stats = dict(zip(("generated", "distinct", "queued"), map(int, rows[0]), strict=True), depth=int(depth[0]))
    path = work / "graph.dot"
    graph = read_graph(path, stats, tagged=tagged, old=old)
    path.unlink()
    return graph


def expected_tag(event):
    # For these exact blobs the successor report is written by the operation
    # that made the transition; this oracle does not classify by its receipt.
    if event.command == "":
        return 0
    if event.command == "stage" and event.wanted == 12:
        return 1
    if (event.command == "publish" and event.wanted == 12 and event.expectedMain == 3
            and not event.aliasesMain and event.failAt == 0):
        return {3: 2, -2: 3, None: 5}[event.expectedFactor]
    if event.command not in ("select", "export", "stage", "publish", "collect"):
        raise ValueError(f"unexpected native report: {event.command}")
    return 4


def check_projection(native, tagged):
    projection = [native.index.get(state.native) for state in tagged.states]
    reached = set(projection)
    if None in reached or len(reached) != len(native.states):
        raise ValueError("tagged reachable states do not project to native reachable states")
    if ({projection[i] for i in tagged.initial} != native.initial
            or any(tagged.states[i].tag != 0 for i in tagged.initial)):
        raise ValueError("source tags changed native initialization")
    for s, targets in enumerate(tagged.outgoing):
        if tuple(sorted({projection[t] for t in targets})) != native.outgoing[projection[s]]:
            raise ValueError(f"tag erasure changed outgoing native transitions at {tagged.states[s]}")
    for s, targets in enumerate(tagged.outgoing):
        for t in targets:
            target = tagged.states[t]
            if target.tag != expected_tag(target.native.event):
                raise ValueError(f"incorrect call tag: {target!r} on transition from {tagged.states[s]!r}")


def native_outcomes(native):
    # BFS in the full native graph, filtered using only its original reports.
    # The selected publish finishes the history immediately.
    outcomes = {2: {}, 3: {}}
    frontier = deque((state, 0, 0) for state in sorted(native.initial))
    seen = {(state, 0) for state in native.initial}
    while frontier:
        source, phase, length = frontier.popleft()
        for target in native.outgoing[source]:
            event = native.states[target].event
            tag = expected_tag(event)
            if phase == 1 and tag in (2, 3, 5):
                for publish in (2, 3) if tag == 5 else (tag,):
                    outcomes[publish].setdefault(event.receipt, length + 1)
                continue
            if tag == 0 or (tag == 1 and phase == 0):
                item = (target, 1 if tag == 1 else phase)
                if item not in seen:
                    seen.add(item)
                    frontier.append((*item, length + 1))
    return outcomes


def replay(native, row, publish, shortest, *, old):
    trace = row["trace"]
    if not isinstance(trace, list) or not trace:
        raise ValueError("empty or invalid witness trace")
    prior, phase = None, 0
    for i, frame in enumerate(trace):
        state = require_kind(frame["state"], dict)
        if state.keys() != set((*FIELDS, TAG, "reviewPhase")):
            raise ValueError("witness does not contain the four original variables, phase and tag")
        current = Native(**{key: field_value(key, state[key], old) for key in FIELDS})
        index = native.index.get(current)
        if i == 0:
            if index not in native.initial:
                raise ValueError("witness does not replay through the original init")
            tag, action = 0, "init"
        else:
            if index not in native.outgoing[prior]:
                raise ValueError(f"witness does not replay through the original scheduler at frame {i}")
            tag = expected_tag(current.event)
            if tag == 0:
                action = "hidden"
            elif tag == 1 and phase == 0:
                phase, action = 1, LABELS[1]
            elif tag in (publish, 5) and phase == 1 and i == len(trace) - 1:
                phase, action = publish, LABELS[publish]
            else:
                raise ValueError(f"witness does not realize the selected history at frame {i}")
        if (require_kind(state[TAG], int) != tag or require_kind(state["reviewPhase"], int) != phase
                or frame["action"] != action):
            raise ValueError(f"witness tag, action or phase disagrees with the original scheduler at frame {i}")
        prior = index
    if phase != publish or current.event.receipt != require_kind(row["receipt"], int):
        raise ValueError("witness does not realize the declared history and receipt")
    if len(trace) - 1 != shortest:
        raise ValueError("witness is not a shortest original execution for its history and receipt")


def check_report(report, case, native, outcomes):
    old, new = report["revisions"]["old"], report["revisions"]["new"]
    scope = report["scope"]
    if (report["schema_version"] != 1 or report["model"] != MODEL or report["status"] != "exhaustive"
            or old != REVISIONS["old"] or new not in REVISIONS.values() or REVISIONS[case] not in (old, new)
            or scope["scenario"] != "initial_source (original init)" or scope["observation"] != "event.receipt"
            or scope["max_original_transitions"] is not None or scope["arguments"] != ARGUMENTS
            or scope["legacy_publish_matches_both_factors"] != REVISIONS["old"]
            or scope["public_histories"] != [[LABELS[1], LABELS[p]] for p in (2, 3)]):
        raise ValueError("expected an exhaustive report for the designated DML histories and revision")
    new_case = "old" if new == old else "new"
    count = 0
    for publish, entry in zip((2, 3), report["histories"], strict=True):
        old_set, new_set = EXPECTED["old"][publish], EXPECTED[new_case][publish]
        if (entry["public_history"] != [LABELS[1], LABELS[publish]]
                or entry["removed"] != sorted(set(old_set) - set(new_set))
                or entry["added"] != sorted(set(new_set) - set(old_set))):
            raise ValueError("report histories or deltas disagree with the native oracle")
        for side, revision, expected in (("old", old, old_set), ("new", new, new_set)):
            rows = entry["outcomes"][side]
            if [require_kind(row["receipt"], int) for row in rows] != expected:
                raise ValueError("report outcomes disagree with the native oracle")
            if revision == REVISIONS[case]:
                for row in rows:
                    replay(native, row, publish, outcomes[publish][row["receipt"]], old=(case == "old"))
                    count += 1
    return count


def check_revision(repo, quint, case, tagged_directory, reports=()):
    if run([str(quint), "--version"]).strip() != b"0.34.0":
        raise ValueError("expected Quint 0.34.0 (the default nix shell Quint is 0.33.1)")
    jar = Path(os.environ["QUINT_HOME"]).resolve() / f"apalache-dist-{APALACHE}/apalache/lib/apalache.jar"
    if not jar.is_file():
        raise ValueError(f"missing TLC jar: {jar}")
    revision = REVISIONS[case]
    with tempfile.TemporaryDirectory(prefix="quint-dml-source-projection-") as tmp:
        root = Path(tmp)
        entry = native_snapshot(repo, revision, root / "original")
        native = explore(quint, jar, entry, root / "native-graph", tagged=False, old=(case == "old"))
        tagged_entry = tagged_directory.resolve() / entry.name
        tagged = explore(quint, jar, tagged_entry, root / "tagged-graph", tagged=True, old=(case == "old"))
        check_projection(native, tagged)
    outcomes = native_outcomes(native)
    if {p: sorted(items) for p, items in outcomes.items()} != EXPECTED[case]:
        raise ValueError(f"unexpected outcomes in the original scheduler: {outcomes}")
    replayed = sum(check_report(report, case, native, outcomes) for report in reports)
    return {"revision": revision, "native": native.stats, "tagged": tagged.stats, "replayed_witnesses": replayed,
            "seconds_per_tool_invocation": TOOL_TIMEOUT,
            "histories": [{"public_history": [LABELS[1], LABELS[p]],
                           "receipts": sorted(items), "shortest_original_transitions": dict(sorted(items.items()))}
                          for p, items in outcomes.items()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("quint", type=Path, help="path to the Quint 0.34.0 executable")
    parser.add_argument("case", choices=REVISIONS)
    parser.add_argument("tagged_directory", type=Path)
    parser.add_argument("--report", type=Path, action="append", default=[], help="an exhaustive comparison JSON report")
    args = parser.parse_args()
    try:
        reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.report]
        print(json.dumps(check_revision(args.checkout.resolve(), args.quint.absolute(), args.case,
                                        args.tagged_directory, reports), indent=2))
    except (OSError, KeyError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"DML source projection oracle failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
