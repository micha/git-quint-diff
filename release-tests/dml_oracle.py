"""Native TLC closure and an independent report/route oracle for the DML derivative.

The native graph is compiled from the committed snapshot's unchanged init and
step, without the production binder, IR manipulation, or DOT reader. The
fixture's event tuple is a check on label identity, not a runtime selector.
"""

from collections import deque, namedtuple
import json
from pathlib import Path
import re
import socket
import subprocess

from consensus_oracle import ASSIGNMENT, EDGE, NODE, RANK, Graph, read_value


State = namedtuple("State", ("returning", "main", "staged", "receipt", "event"))
ENTRYPOINT = "recorded_return_fixture.qnt"
MODULE = "recorded_return_fixture"
NO_EVENT = (0, 0, 0, 0, 0)
SCENARIO = "dml_return"
STAGE = "stage_alternate"
PUBLISH = {3: "publish_alternate_expected_3", -2: "publish_alternate_expected_minus_2"}
HIDDEN = {"startReturn", "clearEvent", "moveMain"}


def site(kind, version, label=None, factor=3, *, routed=False):
    """Manually checked, side-local coordinates; independent of discovery/binding."""
    line, column = {
        "startReturn": (60, 37), "clearEvent": (61, 32),
        "moveMain": (69 if version == "old" else 70, 7),
        "stage": ((64 if label else 63), 7),
        "publish": ((68 if version == "old" else 69) if label else 65, 7),
    }[kind]
    position = {"path": ENTRYPOINT, "line": line, "column": column}
    if routed and kind not in ("startReturn", "clearEvent"):
        position["line"] += 3
        position["via"] = [{k: hop[k] for k in ("path", "line", "column")} for hop in routing_hops(version)]
    if label is None:
        return position
    args = [12] if kind == "stage" else [12, 3, *([] if version == "old" else [factor]), False, 0]
    return position | {"callee": f"{MODULE}::{kind}", "args": args}


def declaration(kind):
    line = {"stage": 38, "publish": 48, "step": 60, "sourceStep": 64, "readyStep": 77}[kind]
    return {"path": ENTRYPOINT, "module": MODULE, "line": line, "column": 10, "action": kind}


def routing_hops(version):
    """Coordinates of route occurrences and declarations in the committed derivative."""
    calls = [("sourceStep", 62, 10)] if version == "old" else [("readyStep", 62, 10), ("sourceStep", 77, 22)]
    return [{"path": ENTRYPOINT, "line": line, "column": column,
             "callee": f"{MODULE}::{kind}", "declaration": declaration(kind)} for kind, line, column in calls]


def resolved_site(kind, version, label=None, factor=3, *, routed=False):
    expected = site(kind, version, label, factor, routed=routed)
    if label is not None:
        expected["declaration"] = declaration(kind)
    if "via" in expected:
        expected["via"] = routing_hops(version)
    return expected


def state_values(raw):
    if raw.keys() != set(State._fields) or raw["returning"] not in ("TRUE", "FALSE"):
        raise ValueError(f"unexpected native DML variables or types: {raw}")
    main, staged, receipt, event = map(read_value, (raw["main"], raw["staged"], raw["receipt"], raw["event"]))
    if (any(type(v) is not int for v in (main, staged, receipt)) or type(event) is not tuple
            or len(event) != 5 or any(type(v) is not int for v in event)):
        raise ValueError(f"unexpected native DML values or types: {raw}")
    return State(raw["returning"] == "TRUE", main, staged, receipt, event)


def read_native_dot(path, generated, distinct):
    lines = path.read_text(encoding="utf8").strip().splitlines()
    if lines[:5] != ["strict digraph DiskGraph {", "node [shape=box,style=rounded]", "nodesep=0.35;",
                     "subgraph cluster_graph {", 'color="white";'] or lines[-2:] != ["}", "}"]:
        raise ValueError("unexpected DML graph framing")
    states, initial, edges = {}, set(), set()
    for line in lines[5:-2]:
        if match := NODE.fullmatch(line):
            key, raw, style = match.groups()
            text = json.loads(raw)
            variables = list(ASSIGNMENT.finditer(text))
            if key in states or len(variables) != len(State._fields) or variables[0].start() != 0:
                raise ValueError("unexpected DML state node")
            ends = [m.start() for m in variables[1:]] + [len(text)]
            states[key] = state_values({m[1]: text[m.end():end].strip() for m, end in zip(variables, ends, strict=True)})
            if style == "style = filled":
                initial.add(key)
        elif match := EDGE.fullmatch(line):
            edges.add(match.groups())
        elif not RANK.fullmatch(line):
            raise ValueError(f"unexpected DML graph row: {line}")
    if len(states) != distinct or len(set(states.values())) != distinct or len(initial) + len(edges) != generated:
        raise ValueError("DML graph does not agree with native closure counts")
    graph = Graph({states[key] for key in initial}, {state: set() for state in states.values()})
    for source, target in edges:
        graph.outgoing[states[source]].add(states[target])
    if graph.initial != {State(False, 3, 0, 0, NO_EVENT)}:
        raise ValueError("unexpected DML initialization")
    seen, pending = set(graph.initial), list(graph.initial)
    while pending:
        unseen = graph.outgoing[pending.pop()] - seen
        seen.update(unseen)
        pending.extend(unseen)
    if seen != graph.outgoing.keys():
        raise ValueError("DML graph contains states beyond native reachability")
    return graph


def native_graph(repo, revision, work, env):
    work.mkdir()
    (work / ENTRYPOINT).write_bytes(subprocess.check_output(
        ["git", "cat-file", "blob", f"{revision}:{ENTRYPOINT}"], cwd=repo, env=env))

    def run(*args):
        result = subprocess.run(args, cwd=work, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(f"Independent {args[0]} failed:\n{result.stdout}{result.stderr}")
        return result.stdout

    if run("quint", "--version").strip() != "0.33.1":
        raise AssertionError("DML native oracle requires Quint 0.33.1 from nix develop")
    run("quint", "typecheck", ENTRYPOINT)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    tla = run("quint", "compile", ENTRYPOINT, "--target", "tlaplus", "--verbosity", "0",
              "--apalache-version", "0.62.4", "--server-endpoint", f"127.0.0.1:{port}")
    (work / f"{MODULE}.tla").write_text(tla, encoding="utf8")
    (work / f"{MODULE}.cfg").write_text("INIT q_init\nNEXT q_step\n", encoding="utf8")
    jar = Path(env["QUINT_HOME"]) / "apalache-dist-0.62.4/apalache/lib/apalache.jar"
    log = run("java", "-Xmx512m", "-XX:+UseParallelGC", "-Duser.language=en", "-Duser.country=US",
              f"-Djava.io.tmpdir={work}", "-cp", str(jar), "tlc2.TLC", "-deadlock", "-workers", "1", "-fp", "0",
              "-noGenerateSpecTE", "-dump", "dot", "graph.dot", f"{MODULE}.tla")
    stats = re.findall(r"^(\d+) states generated, (\d+) distinct states found, (\d+) states left on queue\.$", log, re.M)
    if (len(stats) != 1 or stats[0][2] != "0" or "Model checking completed. No error has been found." not in log):
        raise AssertionError(f"Independent TLC did not establish DML closure:\n{log}")
    return read_native_dot(work / "graph.dot", *map(int, stats[0][:2]))


def edge_call(source, target, version, factor):
    if not source.returning:
        if target != source._replace(returning=True):
            raise ValueError("unexpected handoff edge")
        return "startReturn", None
    if source.event != NO_EVENT:
        if target != source._replace(event=NO_EVENT, receipt=0):
            raise ValueError("unexpected report reset edge")
        return "clearEvent", None
    cmd, wanted, expected_main, expected_factor, mode = target.event
    if cmd == 0 and target == source._replace(main=target.main) and target.main in {0, 3, 4}:
        return "moveMain", None
    if cmd == 1 and wanted in {11, 12} and (expected_main, expected_factor, mode) == (0, 0, 0):
        return "stage", STAGE if wanted == 12 else None
    if (cmd == 2 and wanted in {11, 12} and expected_main in {0, 3, 11} and mode in {0, 1, 2, 3}
            and expected_factor in ({0} if version == "old" else {3, -2})):
        matches = (wanted, expected_main, expected_factor, mode) == (12, 3, 0 if version == "old" else factor, 0)
        return "publish", PUBLISH[factor] if matches else None
    raise ValueError("native edge has no valid report or scheduler route")


def shortest(graph, history, version, factor):
    """Search the full native graph at exact endpoints, allowing only the three hidden routes."""
    pending = deque((state, 0, 0) for state in graph.initial)
    seen = {(state, 0) for state in graph.initial}
    lengths = {}
    while pending:
        source, prefix, depth = pending.popleft()
        if prefix == len(history):
            lengths.setdefault(source.receipt, depth)
            continue
        for target in graph.outgoing[source]:
            kind, label = edge_call(source, target, version, factor)
            if kind not in HIDDEN and label != history[prefix]:
                continue
            item = (target, prefix + (label is not None))
            if item not in seen:
                seen.add(item)
                pending.append((*item, depth + 1))
    return lengths


def check_site(actual, kind, version, label, factor, *, routed):
    expected = resolved_site(kind, version, label, factor, routed=routed)
    if actual.get("via") != expected.get("via"):
        raise ValueError(f"wrong routing provenance for {label or kind}")
    if any(actual.get(k) != v for k, v in expected.items()):
        raise ValueError(f"wrong source site for {label or kind}")


def replay_witness(graph, witness, revision, history, outcome, version, factor, *, routed=False):
    metadata = {"revision": revision, "scenario": SCENARIO, "history": history, "outcome": outcome}
    if any(witness.get(k) != v for k, v in metadata.items()):
        raise ValueError("DML witness has wrong scope or outcome")
    state = state_values(witness["initial"])
    if state not in graph.initial:
        raise ValueError("DML witness does not implement native init")
    seen = []
    for i, step in enumerate(witness["steps"], 1):
        if len(seen) == len(history):
            raise ValueError("DML witness steps past its exact endpoint")
        target = state_values(step["state"])
        if target not in graph.outgoing[state]:
            raise ValueError(f"DML witness has no native edge at frame {i}")
        kind, label = edge_call(state, target, version, factor)
        if (label is None and kind not in HIDDEN) or step["label"] != label:
            raise ValueError(f"DML witness has wrong label at frame {i}")
        check_site(step["site"], kind, version, label, factor, routed=routed)
        if label is not None:
            seen.append(label)
        state = target
    if seen != history or state.receipt != outcome:
        raise ValueError("DML witness does not produce its reported exact history and receipt")


def verify_tagged(native, tracked, version, factor, *, routed=False):
    states = {key: (state_values({k: v for k, v in row.items() if k != "qdSite"}), row["qdSite"])
              for key, row in tracked["states"].items()}
    if ({states[k] for k in tracked["initial"]} != {(s, "0") for s in native.initial}
            or {state for state, _ in states.values()} != native.outgoing.keys()):
        raise ValueError("initial or reachable DML states differ under erasure")
    for key, (source, tag) in states.items():
        successors = [states[k] for k in tracked["outgoing"].get(key, [])]
        if {target for target, _ in successors} != native.outgoing[source]:
            raise ValueError(f"DML successors differ under erasure at state {source} with tag {tag}")
        for target, target_tag in successors:
            kind, label = edge_call(source, target, version, factor)
            classified = tracked["sites"][target_tag]
            expected = {"label": label} if label is not None or kind in HIDDEN else {}
            if {k: v for k, v in classified.items() if k == "label"} != expected:
                raise ValueError(f"wrong label for DML edge {kind} at tag {target_tag}")
            check_site(classified["site"], kind, version, label, factor, routed=routed)
