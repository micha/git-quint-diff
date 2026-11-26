#!/usr/bin/env python3
"""Bind a public label to a scheduler call site in two upstream Quint revisions."""

import argparse
import json
from pathlib import Path
import re
import sys
import tempfile

# Reuse only the experimental Quint/TLC invocation and closure loop.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dml"))
from direct_actions import (  # noqa: E402
    APALACHE_VERSION, INVARIANT, MAX_OUTCOMES, QUINT_VERSION, ROUND_TIMEOUT,
    Incomplete, add_definitions, backend_jar, close_outcomes, compile_tla, require_success, run,
)

MODEL_DIR = "examples/classic/distributed/ConsensusAlgorithm"
FILES = ("KSetAgreementConsensus.qnt", "ConsensusAlg.qnt")
REVISIONS = {"old": "883cc2c579bd11954129d207899790e80fb8c91e",
             "new": "35df73a703259890303659e421f79016897993b3"}
PARAMETERS = {"N": 3, "F": 1, "ACTUAL_FAULTS": 1, "K": 1, "MAX_ROUNDS": 2}
HISTORIES = {1: ("receive_round_1",), 2: ("receive_round_1", "receive_round_2")}
PREFIX = "review_KSetAgreementConsensus_"
PUBLIC = "receiveMessages"
CALLS = ("stuttering", "crash", "sendMessages", PUBLIC, "computeAction")
DRIVER = ("module review {\n  import KSetAgreementConsensus("
          + ", ".join(f"{name} = {value}" for name, value in PARAMETERS.items())
          + ').* from "./KSetAgreementConsensus"\n}\n')


def snapshot(repo, revision, directory):
    """Materialize only the two known regular blobs; no checkout or syntax shim."""
    git = ["git", "--no-replace-objects", "--literal-pathspecs", "-C", str(repo)]
    blobs = {}
    for name in FILES:
        path = f"{MODEL_DIR}/{name}"
        entry = require_success(run([*git, "ls-tree", "-z", "--full-tree", revision, "--", path]),
                                f"locate {path}").decode("utf-8")
        match = re.fullmatch(r"100(?:644|755) blob ([0-9a-f]+)\t" + re.escape(path) + "\0", entry)
        if not match:
            raise Incomplete(f"not a regular file in the snapshot: {path}")
        oid = match[1]
        (directory / name).write_bytes(require_success(run([*git, "cat-file", "blob", oid]), f"read {path}"))
        blobs[path] = oid
    driver = directory / "review.qnt"
    driver.write_text(DRIVER, encoding="utf-8")
    return driver, blobs


def monitor(tla, bound):
    # Narrow binding for this compiler and model: copy exactly the original
    # scheduler body and annotate its five named call sites, not action
    # definitions or updates. Erasing the annotations gives back the supplied
    # relation, including the original round/stage tests and nondeterminism.
    operator = PREFIX + "step"
    original = re.findall(rf"^{operator} ==\n((?:[ ].*\n)+)", tla, re.M)
    if len(original) != 1 or re.findall(r"^q_step == (.*)$", tla, re.M) != [operator]:
        raise Incomplete("unexpected compiled scheduler binding")
    scheduler = original[0]
    for action in CALLS:
        call = PREFIX + action
        pattern = rf"^( +(?:THEN )?){call}$"
        scheduler, n = re.subn(pattern, lambda m: f'{m[1]}({call} /\\ reviewAction\' = "{action}")',
                               scheduler, flags=re.M)
        if n != 1:
            raise Incomplete(f"expected one scheduler call site for {action}, found {n}")
    counter_var = "\nVARIABLE reviewTransitions" if bound is not None else ""
    counter_init = " /\\ reviewTransitions = 0" if bound is not None else ""
    counter_step = (f"    /\\ reviewTransitions < {bound}\n"
                    "    /\\ reviewTransitions' = reviewTransitions + 1\n") if bound is not None else ""
    return add_definitions(tla, rf'''
VARIABLE reviewPhase, reviewAction{counter_var}
ReviewNativeStep ==
{scheduler}
ReviewStart == q_init /\ reviewPhase = 0 /\ reviewAction = "init"{counter_init}
ReviewNext ==
    /\ reviewPhase < 2
{counter_step}    /\ ReviewNativeStep
    /\ IF reviewAction' = "{PUBLIC}"
       THEN /\ {PREFIX}round = reviewPhase + 1
            /\ reviewPhase' = reviewPhase + 1
       ELSE reviewPhase' = reviewPhase
ReviewAtOutcome == reviewAction = "{PUBLIC}" /\ reviewPhase \in {{1, 2}}
ReviewOmissions == Cardinality({{ p \in DOMAIN {PREFIX}procState : {{}} \in {PREFIX}procState[p]["S"] }})
''')


def unseen(tla, seen):
    allowed = " \\/ ".join(f"(reviewPhase = {p} /\\ ReviewOmissions = {n})" for p, n in sorted(seen)) or "FALSE"
    return add_definitions(tla, f"{INVARIANT} == ReviewAtOutcome => ({allowed})")


def read_witness(path, bound):
    try:
        states = json.loads(path.read_text(encoding="utf-8"))["counterexample"]["state"]
        if len(states) < 2 or (bound is not None and len(states) - 1 > bound):
            raise ValueError("trace outside the requested bound")
        trace, labels = [], []
        for i, (number, state) in enumerate(states):
            phase, action = state["reviewPhase"], state["reviewAction"]
            if (number != i + 1 or type(phase) is not int
                    or (bound is not None and state["reviewTransitions"] != i)):
                raise ValueError("unexpected state number, phase, or transition count")
            label = None
            if i == 0 and action == "init":
                pass
            elif i > 0 and action in CALLS:
                if action == PUBLIC:
                    if trace[-1]["state"][PREFIX + "round"] != len(labels) + 1:
                        raise ValueError("unexpected round at public call")
                    label = f"receive_round_{len(labels) + 1}"
                    labels.append(label)
            else:
                raise ValueError("unexpected scheduler call")
            if phase != len(labels):
                raise ValueError("phase does not match recorded calls")
            trace.append({"call": action, "public_label": label, "state": state})
        if label is None or phase not in HISTORIES or tuple(labels) != HISTORIES[phase]:
            raise ValueError("trace did not end on a selected public call")
        # TLC exports the function on 1..2 as a JSON array in process order.
        processes = state[PREFIX + "procState"]
        if (not isinstance(processes, list) or len(processes) != PARAMETERS["N"] - 1
                or any(not isinstance(process["S"], list) for process in processes)):
            raise ValueError("invalid observation in TLC witness")
        omissions = sum([] in process["S"] for process in processes)
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise Incomplete(f"cannot read TLC's witness: {error}") from error
    return (phase, omissions), trace


def compare(repo, quint, report):
    jar = backend_jar(quint)
    bound = report["scope"]["max_original_transitions"]
    with tempfile.TemporaryDirectory(prefix="git-quint-diff-consensus-") as scratch:
        outcomes = {}
        for side, revision in report["revisions"].items():
            directory = Path(scratch) / side
            directory.mkdir()
            try:
                driver, report["blobs"][side] = snapshot(repo, revision, directory)
                # Select only the transition system, not the old model's
                # unrelated validity formula (getOnlyElement is not TLA+-translatable).
                tla = monitor(compile_tla(quint, driver, "review", invariant="true"), bound)
                outcomes[side], report["closure"][side] = close_outcomes(
                    jar, driver.with_suffix(".tla"), lambda seen: unseen(tla, seen),
                    lambda trace: read_witness(trace, bound), {}, init="ReviewStart", step="ReviewNext",
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
    report["status"] = "exhaustive" if bound is None else "bounded"


def terminal(report):
    scope = report["scope"]
    bound = scope["max_original_transitions"]
    print(f"OLD {report['revisions']['old']} → NEW {report['revisions']['new']}\n"
          f"Model: {report['model']} (original init and step)\n"
          f"Scenario parameters: {scope['parameters']}\n"
          f"Binding: {scope['binding']}\nInternal: {scope['internal']}\n"
          f"Original transition bound: {'none' if bound is None else bound}\n"
          f"Observation: {scope['observation']}\n"
          f"Backend: Quint {QUINT_VERSION} / Apalache {APALACHE_VERSION} / TLC\n"
          f"Status: {report['status']} ({len(report['histories'])} histories checked)")
    for labels in scope["public_histories"]:
        print("Selected: " + " → ".join(labels))
    for side, stats in report["closure"].items():
        print(f"{side.upper()} closure: {stats['generated']} generated, {stats['distinct']} distinct, "
              f"{stats['queued']} queued, {stats['rounds']} TLC runs")
    if "error" in report:
        print(report["error"])
    for history in report["histories"]:
        print("\n" + " → ".join(history["public_history"]))
        for side, rows in history["outcomes"].items():
            if not rows:
                print(f"  {side.upper()}: no matching execution within scope")
            for row in rows:
                n = row["omissions"]
                delta = history["removed" if side == "old" else "added"]
                mark = ("− " if side == "old" else "+ ") if n in delta else "  "
                calls = " → ".join(frame["public_label"] or frame["call"] for frame in row["trace"])
                final = row["trace"][-1]["state"]
                omitted = [p for p, state in enumerate(final[PREFIX + "procState"], 1) if [] in state["S"]]
                print(f"{mark}{side.upper()} omissions={n} (processes {omitted})\n    {calls}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path, help="upstream Quint Git repository containing both commits")
    parser.add_argument("quint", type=Path, help="path to Quint 0.34.0 executable")
    parser.add_argument("--self", action="store_true", help="compare OLD with itself")
    parser.add_argument("--max-transitions", type=int, help="optional bound on original steps (not init)")
    parser.add_argument("--json", action="store_true", help="print experimental structured evidence")
    args = parser.parse_args()
    if args.max_transitions is not None and args.max_transitions < 0:
        parser.error("--max-transitions must be nonnegative")
    report = {
        "schema_version": 1, "status": "incomplete", "model": f"{MODEL_DIR}/{FILES[0]}",
        "revisions": {**REVISIONS, "new": REVISIONS["old"]} if args.self else REVISIONS,
        "scope": {"parameters": PARAMETERS, "init": "ConsensusAlg.init", "scheduler": "ConsensusAlg.step",
                  "binding": "ConsensusAlg.step → receiveMessages, with current round 1 or 2",
                  "public_histories": list(HISTORIES.values()),
                  "internal": "other original scheduler calls; observe at each receive and stop after round 2 receive",
                  "observation": "count processes whose S contains the empty set immediately after receive",
                  "max_original_transitions": args.max_transitions},
        "backend": {"quint": QUINT_VERSION, "apalache": APALACHE_VERSION, "checker": "TLC"},
        "limits": {"outcomes_per_side": MAX_OUTCOMES, "seconds_per_tool_invocation": ROUND_TIMEOUT},
        "histories": [], "closure": {}, "blobs": {},
    }
    try:
        compare(args.upstream.resolve(), args.quint.absolute(), report)
    except (Incomplete, OSError) as error:
        report["error"] = str(error)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        terminal(report)
    return 0 if report["status"] != "incomplete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
