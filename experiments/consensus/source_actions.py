#!/usr/bin/env python3
"""Compare the consensus receive histories by binding a Quint source call site."""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

from action_identity import FILES, HISTORIES, MODEL_DIR, PARAMETERS, PUBLIC, REVISIONS, snapshot
from direct_actions import (
    APALACHE_VERSION, INVARIANT, MAX_OUTCOMES, ROUND_TIMEOUT, Incomplete, add_definitions,
    backend_jar, close_outcomes, compile_tla,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source_binding"))
from source_bindings import parse  # noqa: E402

VERSION = "0.33.1"
MODEL = "ConsensusAlg"
MODEL_FILE = f"{MODEL}.qnt"
SCHEDULER = "step"
TAG = "reviewReceiveRound"
TAG_VALUE = "reviewLastReceive"
OBSERVATION = "reviewOmissions"
TAGGED_INIT = "reviewInit"
TAGGED_STEP = "reviewStep"
PHASE = "ReviewPhase"
POSITIONS = {revision: (248, 30) for revision in REVISIONS.values()}
MONITOR_NAMES = (TAG, TAG_VALUE, OBSERVATION, TAGGED_INIT, TAGGED_STEP)
NATIVE_FIELDS = ("round", "correctProcsMessages", "crashedProcsMessages", "procState", "crashed", "newlyCrashed", "stage")


def unique(items, what):
    if len(items) != 1:
        raise Incomplete(f"expected one {what}, found {len(items)}")
    return items[0]


def app(node, opcode):
    return node.get("kind") == "app" and node.get("opcode") == opcode


def scheduler_leaves(expr, resolve):
    """Recognize branching positions only, not calls anywhere in an AST subtree."""
    def scalar(node):
        return node["kind"] in {"bool", "int", "str"} or (
            node["kind"] == "name" and (
                resolve(node).get("kind") in {"var", "const"}
                or resolve(node).get("qualifier") in {"val", "pureval"}
            )
        )

    def action_name(node):
        return node["kind"] == "name" and resolve(node).get("qualifier") == "action"

    def simple_update(node):
        if not app(node, "assign") or len(node["args"]) != 2:
            return False
        lhs, rhs = node["args"]
        return lhs["kind"] == "name" and resolve(lhs).get("kind") == "var" and scalar(rhs)

    if app(expr, "ite") and len(expr["args"]) == 3:
        condition, yes, no = expr["args"]
        # Only the guard form needed here; do not traverse it as an action.
        if scalar(condition) or (app(condition, "igt") and len(condition["args"]) == 2
                                 and all(map(scalar, condition["args"]))):
            yield from scheduler_leaves(yes, resolve)
            yield from scheduler_leaves(no, resolve)
            return
    elif app(expr, "matchVariant"):
        scrutinee, *cases = expr["args"]
        if scalar(scrutinee) and cases and len(cases) % 2 == 0:
            arms = list(zip(cases[::2], cases[1::2]))
            # Only payload-free arms are needed; don't introduce a read of
            # `round` under a payload binding that could shadow the state var.
            if all(tag["kind"] == "str" and arm["kind"] == "lambda"
                   and [param["name"] for param in arm["params"]] == ["_"] for tag, arm in arms):
                for _, arm in arms:
                    yield from scheduler_leaves(arm["expr"], resolve)
                return
    elif action_name(expr):
        yield expr, expr
        return
    elif app(expr, "actionAll"):
        calls = [arg for arg in expr["args"] if action_name(arg)]
        if len(calls) == 1 and all(arg is calls[0] or simple_update(arg) for arg in expr["args"]):
            yield expr, calls[0]
            return
    raise Incomplete("unsupported scheduler shape: expected if/match, a bare action, or one action with simple updates")


def instrument(quint, driver, position):
    """Append a tagged sibling of step; leave the original declarations intact."""
    directory = driver.parent.resolve()
    sources = {name: (directory / name).read_bytes().decode("ascii") for name in (driver.name, *FILES)}
    if any("\r" in source for source in sources.values()):
        raise Incomplete("source binding requires ASCII with LF line endings")
    fresh = re.compile(r"\b(?:" + "|".join(MONITOR_NAMES) + r")\b")
    if any(fresh.search(source) for source in sources.values()):
        raise Incomplete("monitor names must be fresh across the staged sources")
    ir, locations = parse(quint, driver)
    files = {key: Path(value).resolve() for key, value in locations["sourceIndex"].items()}
    if set(files.values()) != {directory / name for name in sources}:
        raise Incomplete("unexpected source map files for the staged import chain")

    def locate(node):
        file_id, start, last = locations["map"][str(node["id"])]
        name = files[str(file_id)].name
        text = sources[name]
        first, end = start["index"], last["index"] + 1
        if not 0 <= first < end <= len(text):
            raise Incomplete("source map range falls outside its staged source")
        line, col = text.count("\n", 0, first) + 1, first - text.rfind("\n", 0, first)
        if (line, col) != (start["line"] + 1, start["col"] + 1):
            raise Incomplete("source map position and offset disagree")
        return name, (line, col), first, end

    mod = unique([m for m in ir["modules"] if m["name"] == MODEL and locate(m)[0] == MODEL_FILE],
                 f"module {MODEL} in {MODEL_FILE}")

    def action(name):
        return unique([d for d in mod["declarations"] if d.get("name") == name and d.get("kind") == "def"
                       and d.get("qualifier") == "action"], f"action {name} in {MODEL}")

    callee = action(PUBLIC)
    expr = action(SCHEDULER)["expr"]
    resolve = lambda node: ir["table"].get(str(node["id"]), {})
    leaves = list(scheduler_leaves(expr, resolve))
    # A moved or ambiguous site is not silently rebound by name. This narrow
    # experiment also refuses multiple direct calls to the selected callee.
    selected_leaf, selected_call = unique(
        [(leaf, call) for leaf, call in leaves if resolve(call).get("id") == callee["id"]],
        f"direct scheduler call to {PUBLIC}",
    )
    original = sources[MODEL_FILE]
    name, found, call_start, call_end = locate(selected_call)
    if name != MODEL_FILE or found != position or original[call_start:call_end] != PUBLIC:
        raise Incomplete(f"stale source selector for {PUBLIC}: expected {position}, found {found}")

    expr_file, _, start, end = locate(expr)
    _, _, _, module_end = locate(mod)
    if expr_file != MODEL_FILE or end >= module_end or original[module_end - 1] != "}":
        raise Incomplete("scheduler range is not inside the expected source module")
    edits = []
    previous = start
    for leaf, call in sorted(leaves, key=lambda item: locate(item[0])[2]):
        file, _, a, b = locate(leaf)
        call_file, _, c, d = locate(call)
        if (file != MODEL_FILE or call_file != file or not previous <= a <= c < d <= b <= end
                or original[c:d] != call["name"]
                or (leaf is not call and (not re.match(r"all\s*\{", original[a:b]) or original[b - 1] != "}"))):
            raise Incomplete("unexpected source range for a scheduler leaf")
        value = "round" if leaf is selected_leaf else "0"
        edits.extend([(a - start, "all { "), (b - start, f", {TAG}' = {value} }}")])
        previous = b
    body = original[start:end]
    for offset, text in reversed(edits):
        body = body[:offset] + text + body[offset:]
    additions = f"\n  var {TAG}: int\n  action {TAGGED_INIT} = all {{ init, {TAG}' = 0 }}\n  action {TAGGED_STEP} = {body}\n"
    # Define stable root names for the checker predicates. There is no need to
    # find the compiled scheduler, calls, or imported variable names in TLA+.
    root = sources[driver.name]
    if not root.endswith("}\n"):
        raise Incomplete("unexpected end of scenario driver")
    tagged = original[:module_end - 1] + additions + original[module_end - 1:]
    (directory / MODEL_FILE).write_bytes(tagged.encode("ascii"))
    driver.write_bytes((root[:-2] + f"  def {TAG_VALUE} = {TAG}\n"
                        f"  def {OBSERVATION} = procState.keys().filter(p => procState.get(p).S.contains(Set())).size()\n"
                        "}\n").encode("ascii"))
    return {"file": f"{MODEL_DIR}/{MODEL_FILE}", "module": MODEL, "scheduler": SCHEDULER,
            "line": found[0], "column": found[1], "call": original[call_start:call_end],
            "callee": {"file": f"{MODEL_DIR}/{MODEL_FILE}", "module": MODEL, "action": PUBLIC,
                       "line": locate(callee)[1][0], "column": locate(callee)[1][1]},
            "tagged_leaves": len(leaves)}


def stage(quint, repo, revision, directory):
    directory.mkdir()
    driver, blobs = snapshot(repo, revision, directory)
    try:
        site = instrument(quint, driver, POSITIONS[revision])
    except (KeyError, TypeError, ValueError) as error:
        raise Incomplete(f"cannot bind Quint source locations: {error}") from error
    return driver, {"blobs": blobs, "site": site}


def render_check(tla, seen):
    allowed = " \\/ ".join(f"({PHASE} = {p} /\\ {OBSERVATION} = {n})" for p, n in sorted(seen)) or "FALSE"
    # Tracking the chosen histories is separate from tagging the full scheduler.
    return add_definitions(tla, rf'''
VARIABLE {PHASE}
ReviewStart == q_init /\ {PHASE} = 0
ReviewNext ==
    /\ {PHASE} < 2
    /\ q_step
    /\ IF {TAG_VALUE}' = 0
       THEN {PHASE}' = {PHASE}
       ELSE /\ {TAG_VALUE}' = {PHASE} + 1
            /\ {PHASE}' = {TAG_VALUE}'
{INVARIANT} == {TAG_VALUE} # 0 => ({allowed})
''')


def trace_value(state, suffix):
    # Only for TLC's trace encoding; the binding and history check do not
    # depend on flattened spellings of imported calls or variables.
    values = [value for name, value in state.items() if name == suffix or name.endswith("_" + suffix)]
    if len(values) != 1:
        raise ValueError(f"expected one {suffix} in the TLC frame, found {len(values)}")
    return values[0]


def read_witness(path):
    try:
        states = json.loads(path.read_text(encoding="utf-8"))["counterexample"]["state"]
        trace, labels = [], []
        for i, (number, state) in enumerate(states):
            phase, tag = state[PHASE], trace_value(state, TAG)
            if (type(number) is not int or number != i + 1 or type(phase) is not int or type(tag) is not int
                    or len(state) != len(NATIVE_FIELDS) + 2):
                raise ValueError("unexpected state number, phase, receive tag, or fields")
            for field in NATIVE_FIELDS:
                trace_value(state, field)
            label = None
            if i == 0:
                if tag != 0:
                    raise ValueError("unexpected initial tag")
                call = "init"
            elif tag == 0:
                call = "hidden"
            else:
                if tag != len(labels) + 1 or trace_value(trace[-1]["state"], "round") != tag:
                    raise ValueError("unexpected round at selected source call")
                call = PUBLIC
                label = f"receive_round_{tag}"
                labels.append(label)
            if phase != len(labels):
                raise ValueError("phase disagrees with public history")
            trace.append({"call": call, "public_label": label, "state": state})
        if not trace or not label or tuple(labels) != HISTORIES.get(phase):
            raise ValueError("trace did not end on a selected history")
        processes = trace_value(state, "procState")
        if (not isinstance(processes, list) or len(processes) != PARAMETERS["N"] - 1
                or any(not isinstance(process["S"], list) for process in processes)):
            raise ValueError("invalid process slots in TLC witness")
        omissions = sum([] in process["S"] for process in processes)
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise Incomplete(f"cannot read TLC's witness: {error}") from error
    return (phase, omissions), trace


def compare(quint, repo, report):
    jar = backend_jar(quint, VERSION)
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="git-quint-diff-consensus-source-") as temp:
        staged = {}
        for side, revision in report["revisions"].items():
            try:
                staged[side], report["bindings"][side] = stage(quint, repo, revision, Path(temp) / side)
            except (Incomplete, OSError, UnicodeError) as error:
                raise Incomplete(f"{side.upper()}: {error}") from error
        for side, driver in staged.items():
            try:
                # Keep these root accessors in the compiled transition system,
                # but not the historical, unrelated validity formula.
                tla = compile_tla(quint, driver, "review", init=TAGGED_INIT, step=TAGGED_STEP,
                                  invariant=f"{TAG_VALUE} >= 0 and {OBSERVATION} >= 0")
                outcomes[side], report["closure"][side] = close_outcomes(
                    jar, driver.with_suffix(".tla"), lambda seen: render_check(tla, seen), read_witness,
                    HISTORIES, init="ReviewStart", step="ReviewNext",
                )
            except (Incomplete, OSError, UnicodeError) as error:
                raise Incomplete(f"{side.upper()}: {error}") from error
    for phase, history in HISTORIES.items():
        frontier = {side: {n: trace for (p, n), trace in items.items() if p == phase}
                    for side, items in outcomes.items()}
        old, new = frontier["old"], frontier["new"]
        report["histories"].append({
            "public_history": history,
            "outcomes": {side: [{"omissions": n, "trace": items[n]} for n in sorted(items)]
                         for side, items in frontier.items()},
            "removed": sorted(old.keys() - new.keys()), "added": sorted(new.keys() - old.keys()),
        })
    report["status"] = "exhaustive"


def terminal(report):
    scope = report["scope"]
    print(f"OLD {report['revisions']['old']} → NEW {report['revisions']['new']}\n"
          f"Scenario: {report['model']} {scope['parameters']}\n"
          f"Scope: {scope['internal']}; no transition bound\nObservation: {scope['observation']}\n"
          f"Backend: Quint {VERSION} / Apalache {APALACHE_VERSION} / TLC\n"
          f"Status: {report['status']} ({len(report['histories'])} histories checked)")
    for history in scope["public_histories"]:
        print("Selected: " + " → ".join(history))
    for side, binding in report["bindings"].items():
        site = binding["site"]
        print(f"{side.upper()} binding: {site['file']}:{site['line']}:{site['column']} "
              f"({site['scheduler']} → {site['call']})")
    for side, stats in report["closure"].items():
        print(f"{side.upper()} closure: {stats['generated']} generated, {stats['distinct']} distinct, "
              f"{stats['queued']} queued in the final of {stats['rounds']} TLC runs")
    if "error" in report:
        print(report["error"])
    for history in report["histories"]:
        print("\n" + " → ".join(history["public_history"]))
        for side, rows in history["outcomes"].items():
            for row in rows:
                n = row["omissions"]
                delta = history["removed" if side == "old" else "added"]
                mark = ("− " if side == "old" else "+ ") if n in delta else "  "
                calls = " → ".join(frame["public_label"] or frame["call"] for frame in row["trace"])
                processes = trace_value(row["trace"][-1]["state"], "procState")
                slots = [i for i, process in enumerate(processes, 1) if [] in process["S"]]
                print(f"{mark}{side.upper()} omissions={n} (process slots {slots})\n    {calls}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    stage_parser = sub.add_parser("stage", help="stage the tagged, unfiltered scheduler for independent checking")
    stage_parser.add_argument("upstream", type=Path)
    stage_parser.add_argument("revision", choices=REVISIONS)
    stage_parser.add_argument("directory", type=Path)
    comparison = sub.add_parser("compare", help="compare the fixed consensus histories")
    comparison.add_argument("upstream", type=Path)
    comparison.add_argument("--self", action="store_true", help="compare OLD with itself")
    comparison.add_argument("--json", action="store_true")
    args = parser.parse_args()
    quint = shutil.which("quint") or "quint"
    if args.command == "stage":
        try:
            backend_jar(quint, VERSION)
            _, info = stage(quint, args.upstream.resolve(), REVISIONS[args.revision], args.directory.resolve())
            print(json.dumps(info, indent=2))
        except (Incomplete, OSError, UnicodeError) as error:
            print(f"incomplete: {error}", file=sys.stderr)
            return 1
        return 0
    report = {
        "schema_version": 1, "status": "incomplete", "model": f"{MODEL_DIR}/{FILES[0]}",
        "revisions": {**REVISIONS, "new": REVISIONS["old"]} if args.self else REVISIONS,
        "scope": {"parameters": PARAMETERS, "init": "ConsensusAlg.init", "scheduler": "ConsensusAlg.step",
                  "binding": "source call to receiveMessages; label by pre-state round",
                  "public_histories": list(HISTORIES.values()), "max_original_transitions": None,
                  "internal": "hidden native calls allowed; stop at the second selected receive",
                  "observation": "count all process slots whose S contains the empty set just after receiving"},
        "backend": {"quint": VERSION, "apalache": APALACHE_VERSION, "checker": "TLC"},
        "limits": {"outcomes_per_side": MAX_OUTCOMES, "seconds_per_tool_invocation": ROUND_TIMEOUT},
        "histories": [], "closure": {}, "bindings": {},
    }
    try:
        compare(quint, args.upstream.resolve(), report)
    except (Incomplete, OSError) as error:
        report["error"] = str(error)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        terminal(report)
    return 0 if report["status"] == "exhaustive" else 1


if __name__ == "__main__":
    raise SystemExit(main())
