#!/usr/bin/env python3
"""Compare two selected source-level call sites on a controlled Git fixture."""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dml"))
from direct_actions import (  # noqa: E402
    APALACHE_VERSION, INVARIANT, MAX_OUTCOMES, ROUND_TIMEOUT, Incomplete, add_definitions,
    backend_jar, close_outcomes, compile_tla, require_success, run,
)

VERSION = "0.33.1"
ENTRY = "workflow.qnt"
MODULE = "workflow"
LABELS = ("alpha", "beta")
BINDINGS = Path(__file__).with_name("bindings.json")


def snapshot(repo, commit, directory):
    """Stage the two known regular blobs from the exact fixture commit."""
    git = ["git", "--no-replace-objects", "--literal-pathspecs", "-C", str(repo)]
    blobs = {}
    for name in (ENTRY, "marks.qnt"):
        entry = require_success(run([*git, "ls-tree", "-z", "--full-tree", commit, "--", name]), f"locate {name}")
        match = re.fullmatch(rb"100(?:644|755) blob ([0-9a-f]{40})\t" + re.escape(name.encode()) + rb"\x00", entry)
        if not match:
            raise Incomplete(f"not a regular file in {commit}: {name}")
        oid = match[1].decode("ascii")
        content = require_success(run([*git, "cat-file", "blob", oid]), f"read {name}")
        (directory / name).write_bytes(content)
        blobs[name] = oid
    return blobs


def parse(quint, source):
    with tempfile.TemporaryDirectory(prefix="quint-source-map-") as temp:
        ir, source_map = (Path(temp) / name for name in ("ir.json", "map.json"))
        require_success(run([str(quint), "parse", source.name, "--out", str(ir),
                             "--source-map", str(source_map)], source.parent), "parse committed Quint source")
        return tuple(json.loads(path.read_text(encoding="utf-8")) for path in (ir, source_map))


def instrument(quint, directory, binding):
    """Resolve source sites, then insert one fresh tag per scheduler branch."""
    source = directory / ENTRY
    original = source.read_bytes().decode("ascii")
    imported = (directory / "marks.qnt").read_bytes().decode("ascii")
    if "\r" in original + imported:
        raise Incomplete("fixture expects ASCII source with LF line endings")
    if re.search(r"\b(?:reviewCall|reviewInit|reviewObservation)\b", original + imported):
        raise Incomplete("monitor names must be fresh")
    ir, locations = parse(quint, source)

    def locate(node):
        file_id, start, end = locations["map"][str(node["id"])]
        file = Path(locations["sourceIndex"][str(file_id)]).resolve().relative_to(directory)
        return str(file), (start["line"] + 1, start["col"] + 1), (start["index"], end["index"] + 1)

    def unique(nodes, description):
        if len(nodes) != 1:
            raise Incomplete(f"expected one {description}, found {len(nodes)}")
        return nodes[0]

    def module(file, name):
        return unique([m for m in ir["modules"] if m["name"] == name and locate(m)[0] == file],
                      f"module {name} in {file}")

    def action(mod, name):
        return unique([d for d in mod["declarations"] if d.get("name") == name
                       and d.get("kind") == "def" and d.get("qualifier") == "action"], f"action {name}")

    file, mod_name, name = binding["callee"]
    resolved = action(module(file, mod_name), name)
    workflow = module(ENTRY, MODULE)
    scheduler = action(workflow, binding["scheduler"])["expr"]
    if scheduler.get("opcode") != "actionAny":
        raise Incomplete("unsupported scheduler: expected top-level any")
    branches = scheduler["args"]
    if not branches or any(branch.get("opcode") != "actionAll" for branch in branches):
        raise Incomplete("unsupported scheduler: expected all in each branch")
    sites = []
    for index, branch in enumerate(branches):
        for conjunct in branch["args"]:
            target = ir["table"].get(str(conjunct["id"]))
            if conjunct["kind"] == "app" and target and target["id"] == resolved["id"]:
                site = locate(conjunct)
                if site[0] != ENTRY:
                    raise Incomplete("selected call is not in the scheduler source")
                sites.append((index, *site[1:]))

    if set(binding["calls"]) != set(LABELS):
        raise Incomplete("expected an explicit selector for each public label")
    branch_tags, selected = {}, {}
    for label in LABELS:
        position = binding["calls"][label]
        index, (line, column), (start, end) = unique([
            site for site in sites if position is None or list(site[1]) == position
        ], f"source call site for {label}")
        if index in branch_tags or sum(site[0] == index for site in sites) != 1:
            raise Incomplete(f"ambiguous calls in the scheduler branch for {label}")
        branch_tags[index] = label
        selected[label] = {"file": ENTRY, "module": MODULE, "scheduler": binding["scheduler"],
                           "line": line, "column": column, "call": original[start:end],
                           "callee": {"file": file, "module": mod_name, "action": name,
                                      "line": locate(resolved)[1][0], "column": locate(resolved)[1][1]}}

    # A direct action in a conjunction is executed by that scheduler branch.
    # Wrap the entire branch, not the action definition or unrelated call sites.
    # Inserting only text means removing these additions restores every original byte.
    patches = []
    last_end = 0
    for index, branch in enumerate(branches):
        branch_file, _, (start, end) = locate(branch)
        if (branch_file != ENTRY or not last_end <= start < end <= len(original)
                or not original[start:end].startswith("all {") or original[end - 1] != "}"):
            raise Incomplete("unexpected scheduler branch source range")
        patches += [(start, "all { "), (end, f", reviewCall' = {json.dumps(branch_tags.get(index, 'hidden'))} }}")]
        last_end = end
    closing = len(original.rstrip()) - 1
    if original[closing:].strip() != "}" or closing < last_end:
        raise Incomplete("unexpected end of scheduler module")
    patches.append((closing, '''
  var reviewCall: str
  action reviewInit = all { init, reviewCall' = "init" }
  def reviewObservation = x
'''))
    rendered = original
    for index, text in reversed(patches):
        rendered = rendered[:index] + text + rendered[index:]
    source.write_bytes(rendered.encode("ascii"))
    return selected


def stage(quint, repo, binding, directory):
    directory.mkdir()
    blobs = snapshot(repo, binding["commit"], directory)
    try:
        return {"blobs": blobs, "sites": instrument(quint, directory, binding)}
    except (KeyError, TypeError, ValueError) as error:
        raise Incomplete(f"cannot bind Quint source locations: {error}") from error


def render_check(tla, seen):
    known = " \\/ ".join(
        f"(reviewCall = {json.dumps(LABELS[index])} /\\ reviewObservation = ({outcome}))"
        for index, outcome in sorted(seen)
    ) or "FALSE"
    # Stop on the first public call. This restriction is separate from tagging,
    # which the independent oracle checks on the full scheduler.
    return add_definitions(tla, rf'''
ReviewFirstCall == reviewCall \in {{"init", "hidden"}} /\ q_step
{INVARIANT} == reviewCall \in {{"alpha", "beta"}} => ({known})
''')


def read_witness(path):
    try:
        states = json.loads(path.read_text(encoding="utf-8"))["counterexample"]["state"]
        trace = []
        for i, (number, state) in enumerate(states, start=1):
            label = state["reviewCall"]
            # The fixture has exactly one original integer variable. No coupling
            # to the compiler's spelling of the imported variable in the trace.
            (x,) = [value for name, value in state.items() if name != "reviewCall"]
            if number != i or type(x) is not int:
                raise ValueError("unexpected state number or observation")
            trace.append({"call": label, "x": x})
        if (len(trace) < 2 or [row["call"] for row in trace[:-1]] != ["init"] + ["hidden"] * (len(trace) - 2)
                or trace[-1]["call"] not in LABELS):
            raise ValueError("trace did not end at the first public call")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise Incomplete(f"cannot read TLC's witness: {error}") from error
    return (LABELS.index(trace[-1]["call"]), trace[-1]["x"]), trace


def compare(quint, jar, repo, pair, report):
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="git-quint-diff-source-") as temp:
        for side, binding in pair.items():
            directory = Path(temp) / side
            try:
                report["bindings"][side] = stage(quint, repo, binding, directory)
            except (Incomplete, OSError, UnicodeError) as error:
                raise Incomplete(f"{side.upper()}: {error}") from error
        for side, binding in pair.items():
            source = Path(temp) / side / ENTRY
            try:
                tla = compile_tla(quint, source, MODULE, init="reviewInit", step=binding["scheduler"])
                outcomes[side], report["closure"][side] = close_outcomes(
                    jar, source.with_suffix(".tla"), lambda seen: render_check(tla, seen), read_witness,
                    {}, step="ReviewFirstCall",
                )
            except (Incomplete, OSError, UnicodeError) as error:
                raise Incomplete(f"{side.upper()}: {error}") from error
    for index, label in enumerate(LABELS):
        frontier = {side: {x: trace for (end, x), trace in reached.items() if end == index}
                    for side, reached in outcomes.items()}
        old, new = (frontier[side] for side in ("old", "new"))
        report["histories"].append({
            "public_history": [label],
            "outcomes": {side: [{"x": x, "trace": traces[x]} for x in sorted(traces)]
                         for side, traces in frontier.items()},
            "removed": sorted(old.keys() - new.keys()), "added": sorted(new.keys() - old.keys()),
        })
    report["status"] = "exhaustive"


def terminal(report):
    print(f"OLD {report['revisions']['old']} → NEW {report['revisions']['new']}")
    print("Scope: original init; hidden steps before first public call; histories alpha and beta; no transition bound")
    print(f"Observation: {report['scope']['observation']}\nStatus: {report['status']}")
    for side, binding in report["bindings"].items():
        for label, site in binding["sites"].items():
            print(f"{side.upper()} {label}: {site['file']}:{site['line']}:{site['column']} "
                  f"({site['scheduler']} → {site['callee']['module']}::{site['callee']['action']})")
    for side, stats in report["closure"].items():
        print(f"{side.upper()} closure: {stats['generated']} generated, {stats['distinct']} distinct, "
              f"{stats['queued']} queued in the final of {stats['rounds']} TLC runs")
    if "error" in report:
        print(report["error"])
    for history in report["histories"]:
        print("\n" + " → ".join(history["public_history"]))
        for side, rows in history["outcomes"].items():
            if not rows:
                print(f"  {side.upper()}: no matching execution within scope")
            for row in rows:
                delta = history["removed"] if side == "old" else history["added"]
                mark = ("− " if side == "old" else "+ ") if row["x"] in delta else "  "
                witness = " → ".join(f"{frame['call']}: x={frame['x']}" for frame in row["trace"])
                print(f"{mark}{side.upper()} x={row['x']} ({witness})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    compare_parser = sub.add_parser("compare", help="compare OLD with one fixture revision")
    compare_parser.add_argument("repo", type=Path)
    compare_parser.add_argument("revision", choices=("old", "refactor", "changed"))
    compare_parser.add_argument("--ambiguous", action="store_true", help="omit NEW's alpha position as a negative control")
    compare_parser.add_argument("--json", action="store_true")
    stage_parser = sub.add_parser("stage", help="export the tagged full scheduler for independent verification")
    stage_parser.add_argument("repo", type=Path)
    stage_parser.add_argument("revision", choices=("old", "refactor", "changed"))
    stage_parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    bindings = json.loads(BINDINGS.read_text(encoding="utf-8"))
    chosen = bindings[args.revision]
    quint = shutil.which("quint") or "quint"
    if args.command == "stage":
        try:
            backend_jar(quint, VERSION)
            print(json.dumps(stage(quint, args.repo.resolve(), chosen, args.directory.resolve()), indent=2))
        except (Incomplete, OSError, UnicodeError) as error:
            print(f"incomplete: {error}", file=sys.stderr)
            return 1
        return 0
    if args.ambiguous:
        chosen = {**chosen, "calls": {**chosen["calls"], "alpha": None}}
    pair = {"old": bindings["old"], "new": chosen}
    report = {
        "schema_version": 1, "status": "incomplete",
        "revisions": {side: spec["commit"] for side, spec in pair.items()},
        "scope": {"entrypoint": ENTRY, "init": "workflow::init", "observation": "x after the first public call",
                  "selected_histories": [[label] for label in LABELS], "max_original_transitions": None},
        "backend": {"quint": VERSION, "apalache": APALACHE_VERSION, "checker": "TLC"},
        "limits": {"outcomes_per_side": MAX_OUTCOMES, "seconds_per_tool_invocation": ROUND_TIMEOUT},
        "bindings": {}, "histories": [], "closure": {},
    }
    try:
        compare(quint, backend_jar(quint, VERSION), args.repo.resolve(), pair, report)
    except (Incomplete, OSError) as error:
        report["error"] = str(error)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        terminal(report)
    return 0 if report["status"] == "exhaustive" else 1


if __name__ == "__main__":
    raise SystemExit(main())
