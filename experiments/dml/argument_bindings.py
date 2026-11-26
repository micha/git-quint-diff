#!/usr/bin/env python3
"""Bind DML review requests to their original scheduler sites and argument values."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import tempfile

from direct_actions import (
    APALACHE_VERSION, INVARIANT, MAX_OUTCOMES, MODEL, QUINT_VERSION, REVISIONS, ROUND_TIMEOUT,
    Incomplete, add_definitions, backend_jar, close_outcomes, compile_tla, require_success, run,
)
from scheduler_actions import FACTORS, HISTORIES, REQUEST

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source_binding"))
from source_bindings import parse  # noqa: E402

MODULE = Path(MODEL).stem
TAG = "reviewCall"
PHASE = "reviewPhase"
TAGGED_INIT = "reviewInit"
SIBLINGS = {"workerStep": "reviewWorkerStep", "sourceStep": "reviewSourceStep", "step": "reviewStep"}
NATIVE_FIELDS = {"returning", "worker", "source", "event"}
HIDDEN, STAGE, FACTOR_3, FACTOR_MINUS_2, OTHER, LEGACY = range(6)
TAGS = {HIDDEN: "hidden", STAGE: HISTORIES[2][0], FACTOR_3: HISTORIES[2][1],
        FACTOR_MINUS_2: HISTORIES[3][1], OTHER: "other operation", LEGACY: "legacy publish (either factor label)"}
PUBLISH = "publish with expected factor"
SITE_ROLES = {HIDDEN: TAGS[HIDDEN], OTHER: TAGS[OTHER], STAGE: "stage by selected argument",
              LEGACY: TAGS[LEGACY], PUBLISH: PUBLISH, None: "routing"}
# Explicit per-revision source review: line, column, resolved callee and role.
# Even unselected operations are mapped so they cannot become silent by default.
SITES = {
    "old": {
        "workerStep": [(144, 5, "selectScale", OTHER), (145, 5, "exportScale", OTHER),
                       (147, 5, "moveWorkerPin", HIDDEN), (148, 5, "updateWorker", HIDDEN),
                       (149, 5, "startReturn", HIDDEN)],
        "sourceStep": [(154, 5, "stage", STAGE), (159, 5, "publish", LEGACY),
                       (161, 5, "updateSource", HIDDEN), (166, 7, "updateSource", HIDDEN),
                       (169, 5, "updateSource", HIDDEN), (170, 5, "updateSource", OTHER)],
        "step": [(176, 25, "workerStep", None), (177, 35, "updateSource", HIDDEN),
                 (178, 10, "sourceStep", None)],
    },
    "new": {
        "workerStep": [(150, 5, "selectScale", OTHER), (151, 5, "exportScale", OTHER),
                       (153, 5, "moveWorkerPin", HIDDEN), (154, 5, "updateWorker", HIDDEN),
                       (155, 5, "startReturn", HIDDEN)],
        "sourceStep": [(160, 5, "stage", STAGE), (166, 5, "publish", PUBLISH),
                       (168, 5, "updateSource", HIDDEN), (173, 7, "updateSource", HIDDEN),
                       (176, 5, "updateSource", HIDDEN), (177, 5, "updateSource", OTHER)],
        "step": [(183, 25, "workerStep", None), (184, 35, "updateSource", HIDDEN),
                 (185, 10, "sourceStep", None)],
    },
}


def snapshot(repo, revision, path):
    git = ["git", "--no-replace-objects", "--literal-pathspecs", "-C", str(repo)]
    entry = require_success(run([*git, "ls-tree", "-z", "--full-tree", revision, "--", MODEL]), "locate DML model")
    match = re.fullmatch(rb"100(?:644|755) blob ([0-9a-f]{40})\t" + re.escape(MODEL.encode()) + rb"\x00", entry)
    if not match:
        raise Incomplete(f"not a regular file in {revision}: {MODEL}")
    oid = match[1].decode("ascii")
    path.write_bytes(require_success(run([*git, "cat-file", "blob", oid]), "read DML model blob"))
    return oid


def unique(items, description):
    if len(items) != 1:
        raise Incomplete(f"expected one {description}, found {len(items)}")
    return items[0]


def app(node, opcode):
    return node["kind"] == "app" and node["opcode"] == opcode


def scheduler_leaves(node, resolve, locals_=()):
    """Traverse action positions only; leave every choice and guard in place."""
    def is_call(expr):
        return expr["kind"] in {"name", "app"} and resolve(expr).get("qualifier") == "action"

    def guard(expr):
        kind = expr["kind"]
        if kind in {"str", "int", "bool"}:
            return True
        if kind == "name":
            target = resolve(expr)
            return (target.get("id") in locals_ or target.get("kind") == "var"
                    or target.get("qualifier") == "pureval")
        return (kind == "app" and expr["opcode"] in {"not", "neq", "eq", "field", "or", "contains"}
                and all(map(guard, expr["args"])))

    if app(node, "ite") and len(node["args"]) == 3 and guard(node["args"][0]):
        branches = node["args"][1:]
    elif app(node, "actionAny") and node["args"]:
        branches = node["args"]
    elif node["kind"] == "let" and node["opdef"]["qualifier"] == "nondet" and app(node["opdef"]["expr"], "oneOf"):
        yield from scheduler_leaves(node["expr"], resolve, (*locals_, node["opdef"]["id"]))
        return
    elif is_call(node):
        yield node, node, locals_
        return
    elif app(node, "actionAll"):
        calls = [child for child in node["args"] if is_call(child)]
        if len(calls) != 1 or not all(child is calls[0] or guard(child) for child in node["args"]):
            raise Incomplete("unsupported all: expected one direct action call and guards")
        yield node, calls[0], locals_
        return
    else:
        raise Incomplete("unsupported scheduler shape (expected if, any, oneOf binding or direct action)")
    for branch in branches:
        yield from scheduler_leaves(branch, resolve, locals_)


def matches_signature(callee, signature):
    expr = callee["expr"]
    return (expr["kind"] == "lambda" and
            [(p["name"], p["typeAnnotation"]["kind"]) for p in expr["params"]] == signature)


def tag_for(call, role, callee, locals_, resolve, source_text):
    if role in (HIDDEN, OTHER):
        return str(role)

    def simple(expr):
        if expr["kind"] in {"int", "bool"}:
            return True
        if expr["kind"] == "name":
            target = resolve(expr)
            return target.get("qualifier") == "nondet" and target.get("id") in locals_
        return (expr["kind"] == "app" and (expr["opcode"], len(expr["args"])) in {("eq", 2), ("ite", 3)}
                and all(map(simple, expr["args"])))

    args = call.get("args", [])
    signature = [("root", "int")] if role == STAGE else [("wanted", "int"), ("expectedMain", "int")]
    if role == PUBLISH:
        signature += [("expectedFactor", "int")]
    if role != STAGE:
        signature += [("aliasesMain", "bool"), ("failAt", "int")]
    if (len(args) != len(signature) or not matches_signature(callee, signature) or not all(map(simple, args))):
        raise Incomplete(f"unsupported signature or source argument at {callee['name']}")
    # Use the actual argument expressions with the original nondet bindings in
    # scope. Never simplify the alias/failure arguments to a test on `mode`.
    values = [f"({source_text(a)})" for a in args]
    if role == STAGE:
        return f"if ({values[0]} == {REQUEST['wanted']}) {STAGE} else {OTHER}"
    root, main, *rest = values
    alias, fail = rest[-2:]
    tag = str(LEGACY)
    if role == PUBLISH:
        factor = rest[0]
        tag = f"if ({factor} == {FACTORS[2]}) {FACTOR_3} else if ({factor} == {FACTORS[3]}) {FACTOR_MINUS_2} else {OTHER}"
    return (f"if ({root} == {REQUEST['wanted']} and {main} == {REQUEST['expectedMain']} and "
            f"{alias} == false and {fail} == {REQUEST['failAt']}) {tag} else {OTHER}")


def instrument(quint, path, selectors):
    """Append tagged siblings using the exact original scheduler source slices."""
    original = path.read_bytes().decode("ascii")
    if "\r" in original:
        raise Incomplete("source binding requires ASCII with LF line endings")
    reserved = "|".join((TAG, PHASE, TAGGED_INIT, *SIBLINGS.values()))
    if re.search(rf"\b(?:{reserved})\b", original):
        raise Incomplete("monitor names must be fresh")
    ir, source_map = parse(quint, path)
    files = {f: Path(p).resolve() for f, p in source_map["sourceIndex"].items()}
    if set(files.values()) != {path.resolve()}:
        raise Incomplete("unexpected source map files for the DML model")

    def locate(node):
        file, start, last = source_map["map"][str(node["id"])]
        a, b = start["index"], last["index"] + 1
        if files[str(file)] != path.resolve() or not 0 <= a < b <= len(original):
            raise Incomplete("source range outside the committed model")
        position = (start["line"] + 1, start["col"] + 1)
        if position != (original.count("\n", 0, a) + 1, a - original.rfind("\n", 0, a)):
            raise Incomplete("source map position and offset disagree")
        return position, a, b

    def source_text(node):
        _, a, b = locate(node)
        return original[a:b]

    mod = unique([m for m in ir["modules"] if m["name"] == MODULE], f"module {MODULE}")

    def action(name):
        return unique([d for d in mod["declarations"] if d.get("name") == name and d["kind"] == "def"
                       and d.get("qualifier") == "action"], f"action {name}")

    def resolve(node):
        return ir["table"].get(str(node["id"]), {})

    _, _, module_end = locate(mod)
    if original[module_end - 1] != "}":
        raise Incomplete("unexpected end of module")
    additions = f"\n  var {TAG}: int\n  action {TAGGED_INIT} = all {{ init, {TAG}' = {HIDDEN} }}\n"
    sites, routes = [], Counter()
    for scheduler, sibling in SIBLINGS.items():
        expr = action(scheduler)["expr"]
        _, start, end = locate(expr)
        pending = {(line, col): (name, role) for line, col, name, role in selectors[scheduler]}
        if len(pending) != len(selectors[scheduler]):
            raise Incomplete(f"duplicate source selector in {scheduler}")
        edits = []
        prior = start
        for leaf, call, locals_ in sorted(scheduler_leaves(expr, resolve), key=lambda leaf: locate(leaf[0])[1]):
            _, a, b = locate(leaf)
            pos, c, d = locate(call)
            if pos not in pending:
                raise Incomplete(f"stale or unclassified site {scheduler}:{pos[0]}:{pos[1]}")
            name, role = pending.pop(pos)
            callee = action(name)
            if not (prior <= a <= c < d <= b <= end < module_end and resolve(call).get("id") == callee["id"]):
                raise Incomplete(f"stale call selector for {name} in {scheduler}")
            if leaf is not call and (not re.match(r"all\s*\{", original[a:b]) or original[b - 1] != "}"):
                raise Incomplete("unexpected source range for guarded action")
            if role is None:
                if scheduler != "step" or leaf is not call or call["kind"] != "name" or original[c:d] != name:
                    raise Incomplete("unsupported routing call in step")
                routes[name] += 1
                edits.append((c - start, d - start, SIBLINGS[name]))
            else:
                tag = tag_for(call, role, callee, locals_, resolve, source_text)
                edits.extend([(a - start, a - start, "all { "), (b - start, b - start, f", {TAG}' = {tag} }}")])
            callee_line, callee_col = locate(callee)[0]
            sites.append({"file": MODEL, "module": MODULE, "scheduler": scheduler, "line": pos[0], "column": pos[1],
                          "call": original[c:d], "role": SITE_ROLES[role],
                          "callee": {"action": name, "line": callee_line, "column": callee_col}})
            prior = b
        if pending:
            raise Incomplete(f"unresolved source selectors in {scheduler}: {sorted(pending)}")
        body = original[start:end]
        for a, b, text in reversed(edits):
            body = body[:a] + text + body[b:]
        additions += f"  action {sibling} = {body}\n"
    if routes != {"workerStep": 1, "sourceStep": 1}:
        raise Incomplete("expected one route to each sub-scheduler")
    path.write_bytes((original[:module_end - 1] + additions + original[module_end - 1:]).encode("ascii"))
    return sites


def stage(quint, repo, side, directory):
    directory.mkdir()
    path = directory / Path(MODEL).name
    blob = snapshot(repo, REVISIONS[side], path)
    try:
        sites = instrument(quint, path, SITES[side])
    except (KeyError, TypeError, ValueError) as error:
        raise Incomplete(f"cannot bind Quint source locations: {error}") from error
    return path, {"blob": blob, "sites": sites}


def render_check(tla, seen):
    # Only the new tag determines progress; the receipt is just the projection.
    allowed = " \\/ ".join(f'({PHASE} = {p} /\\ event["receipt"] = {r})' for p, r in sorted(seen)) or "FALSE"
    return add_definitions(tla, rf'''
VARIABLE {PHASE}
ReviewStart == q_init /\ {PHASE} = 0
ReviewNext ==
    /\ {PHASE} \in {{0, 1}}
    /\ q_step
    /\ \/ /\ {TAG}' = {HIDDEN}
          /\ {PHASE}' = {PHASE}
       \/ /\ {PHASE} = 0
          /\ {TAG}' = {STAGE}
          /\ {PHASE}' = 1
       \/ /\ {PHASE} = 1
          /\ \/ /\ {TAG}' \in {{{FACTOR_3}, {LEGACY}}}
                /\ {PHASE}' = 2
             \/ /\ {TAG}' \in {{{FACTOR_MINUS_2}, {LEGACY}}}
                /\ {PHASE}' = 3
{INVARIANT} == {PHASE} \in {{2, 3}} => ({allowed})
''')


def read_witness(path, side):
    try:
        states = json.loads(path.read_text(encoding="utf-8"))["counterexample"]["state"]
        trace, previous = [], None
        for i, (n, state) in enumerate(states, start=1):
            phase, tag = state[PHASE], state[TAG]
            if (set(state) != NATIVE_FIELDS | {PHASE, TAG} or type(n) is not int or n != i
                    or type(phase) is not int or type(tag) is not int):
                raise ValueError("unexpected state number, phase, source tag, or original fields")
            if i == 1 and tag == HIDDEN and phase == 0:
                name = "init"
            elif previous in (0, 1) and tag == HIDDEN and phase == previous:
                name = "hidden"
            elif previous == 0 and tag == STAGE and phase == 1:
                name = TAGS[STAGE]
            elif (i == len(states) and previous == 1 and phase in HISTORIES
                  and tag == (LEGACY if side == "old" else phase)):
                name = HISTORIES[phase][1]
            else:
                raise ValueError("unexpected source tag for the selected history")
            trace.append({"action": name, "state": state})
            previous = phase
        if previous not in HISTORIES:
            raise ValueError("trace did not finish a selected public history")
        receipt = state["event"]["receipt"]
        if type(receipt) is not int:
            raise ValueError("noninteger receipt")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise Incomplete(f"cannot read TLC's witness: {error}") from error
    return (phase, receipt), trace


def compare(quint, repo, sides, report):
    jar = backend_jar(quint)
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="git-quint-diff-dml-source-") as temp:
        for name, side in sides.items():
            try:
                path, report["bindings"][name] = stage(quint, repo, side, Path(temp) / name)
                tla = compile_tla(quint, path, MODULE, init=TAGGED_INIT, step=SIBLINGS["step"], invariant="true")
                outcomes[name], report["closure"][name] = close_outcomes(
                    jar, path.with_suffix(".tla"), lambda seen: render_check(tla, seen),
                    lambda trace: read_witness(trace, side), HISTORIES, init="ReviewStart", step="ReviewNext",
                )
            except (Incomplete, OSError, UnicodeError) as error:
                raise Incomplete(f"{name.upper()}: {error}") from error
    for phase, history in HISTORIES.items():
        frontier = {side: {r: trace for (p, r), trace in items.items() if phase == p}
                    for side, items in outcomes.items()}
        old, new = frontier["old"], frontier["new"]
        report["histories"].append({
            "public_history": history,
            "outcomes": {side: [{"receipt": r, "trace": items[r]} for r in sorted(items)]
                         for side, items in frontier.items()},
            "removed": sorted(old.keys() - new.keys()), "added": sorted(new.keys() - old.keys()),
        })
    report["status"] = "exhaustive"


def terminal(report):
    scope = report["scope"]
    print(f"OLD {report['revisions']['old']} → NEW {report['revisions']['new']}\n"
          f"Model: {MODEL} ({scope['scenario']})\n"
          f"Scope: two selected histories; {scope['internal']}; no transition bound\n"
          f"Observation: {scope['observation']} (0=absent, 12=alternate)\n"
          f"Backend: Quint {QUINT_VERSION} / Apalache {APALACHE_VERSION} / TLC\n"
          f"Status: {report['status']} ({len(report['histories'])} histories checked)")
    print("Bindings: stage alternate (12); publish alternate, expected main previousMain (3),\n"
          "          aliasesMain=false, failAt=0; factor 3 or −2 (legacy publish mapped to both labels)")
    for history in scope["public_histories"]:
        print("Selected: " + " → ".join(history))
    for side, binding in report["bindings"].items():
        for site in binding["sites"]:
            callee = site["callee"]["action"]
            if callee in {"stage", "publish"}:
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
                delta = history["removed" if side == "old" else "added"]
                mark = ("− " if side == "old" else "+ ") if row["receipt"] in delta else "  "
                print(f"{mark}{side.upper()} receipt={row['receipt']}")
                for frame in row["trace"]:
                    state = frame["state"]
                    print(f"    {frame['action']}: returning={str(state['returning']).lower()}, "
                          f"main={state['source']['main']}, returned={state['source']['returned']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    stage_parser = sub.add_parser("stage", help="export the tagged, unfiltered scheduler for independent checking")
    comparison = sub.add_parser("compare", help="compare two fixed public histories")
    for p in (stage_parser, comparison):
        p.add_argument("repo", type=Path, help="DML checkout with the two original commits")
        p.add_argument("quint", type=Path, help="absolute path to Quint 0.34.0 executable")
    stage_parser.add_argument("side", choices=REVISIONS)
    stage_parser.add_argument("directory", type=Path)
    comparison.add_argument("--self", action="store_true", help="compare OLD with itself")
    comparison.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo, quint = args.repo.resolve(), args.quint.absolute()
    if args.command == "stage":
        try:
            backend_jar(quint)
            _, meta = stage(quint, repo, args.side, args.directory.resolve())
            print(json.dumps(meta, indent=2))
        except (Incomplete, OSError, UnicodeError) as error:
            print(f"incomplete: {error}", file=sys.stderr)
            return 1
        return 0
    sides = {"old": "old", "new": "old" if args.self else "new"}
    report = {
        "schema_version": 1, "status": "incomplete", "model": MODEL,
        "revisions": {name: REVISIONS[side] for name, side in sides.items()},
        "scope": {"scenario": "initial_source (original init)", "public_histories": list(HISTORIES.values()),
                  "internal": "only explicitly mapped hidden sites allowed; stop at selected publish",
                  "observation": "event.receipt", "max_original_transitions": None,
                  "arguments": {"stage": {"wanted": 12}, "publish": REQUEST, "expected_factors": FACTORS},
                  "legacy_publish_matches_both_factors": REVISIONS["old"], "tags": TAGS},
        "backend": {"quint": QUINT_VERSION, "apalache": APALACHE_VERSION, "checker": "TLC"},
        "limits": {"outcomes_per_side": MAX_OUTCOMES, "seconds_per_tool_invocation": ROUND_TIMEOUT},
        "bindings": {}, "histories": [], "closure": {},
    }
    try:
        compare(quint, repo, sides, report)
    except (Incomplete, OSError) as error:
        report["error"] = str(error)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        terminal(report)
    return 0 if report["status"] == "exhaustive" else 1


if __name__ == "__main__":
    raise SystemExit(main())
