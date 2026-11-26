#!/usr/bin/env python3
"""Compare two public histories through DML's original nondeterministic scheduler."""

import argparse
import json
from pathlib import Path
import tempfile

from direct_actions import (
    APALACHE_VERSION, INVARIANT, MAX_OUTCOMES, MODEL, QUINT_VERSION, REVISIONS, ROUND_TIMEOUT,
    Incomplete, add_definitions, backend_jar, close_outcomes, compile_tla, int_literal, load_model,
)

HISTORIES = {
    2: ("stage_alternate", "publish_alternate_expected_3"),
    3: ("stage_alternate", "publish_alternate_expected_minus_2"),
}
FACTORS = {2: 3, 3: -2}
INTERNAL = "allow original steps with an empty successor event.command; exclude other reports; stop at selected publish"
REQUEST = {"wanted": 12, "expectedMain": 3, "aliasesMain": False, "failAt": 0}


def monitor(tla, revision, max_transitions):
    # The original relation assigns every successor value. The monitor reads
    # those values afterwards; it cannot write original variables, filter on
    # receipts, or prescribe which silent branch of q_step is taken.
    factor = {phase: "" for phase in HISTORIES}
    if revision == REVISIONS["new"]:
        factor = {2: ' /\\ event\'["expectedFactor"] = plannedFactor',
                  3: ' /\\ event\'["expectedFactor"] = alternateFactor'}
    if max_transitions is not None:
        counter = rf"""
VARIABLE reviewTransitions
ReviewStart == q_init /\ reviewPhase = 0 /\ reviewTransitions = 0
ReviewNext == /\ reviewTransitions < {max_transitions}
              /\ ReviewAdvance
              /\ reviewTransitions' = reviewTransitions + 1
"""
    else:
        counter = r"""
ReviewStart == q_init /\ reviewPhase = 0
ReviewNext == ReviewAdvance
"""
    return add_definitions(tla, rf"""
VARIABLE reviewPhase
ReviewAdvance ==
    /\ reviewPhase \in {{0, 1}}
    /\ q_step
    /\ \/ /\ event'["command"] = ""
          /\ reviewPhase' = reviewPhase
       \/ /\ reviewPhase = 0
          /\ event'["command"] = "stage"
          /\ event'["wanted"] = alternate
          /\ reviewPhase' = 1
       \/ /\ reviewPhase = 1
          /\ event'["command"] = "publish"
          /\ event'["wanted"] = alternate
          /\ event'["expectedMain"] = previousMain
          /\ ~event'["aliasesMain"]
          /\ event'["failAt"] = 0
          /\ \/ reviewPhase' = 2{factor[2]}
             \/ reviewPhase' = 3{factor[3]}
{counter}""")


def unseen(tla, seen):
    allowed = " \\/ ".join(
        f'(reviewPhase = {phase} /\\ event["receipt"] = {int_literal(receipt)})'
        for phase, receipt in sorted(seen)
    ) or "FALSE"
    return add_definitions(tla, rf"{INVARIANT} == (reviewPhase \in {{2, 3}}) => ({allowed})")


def read_witness(path, revision, max_transitions):
    try:
        states = json.loads(path.read_text(encoding="utf-8"))["counterexample"]["state"]
        if len(states) < 3 or (max_transitions is not None and len(states) - 1 > max_transitions):
            raise ValueError("trace outside the requested bound")
        trace, labels = [], []
        previous = None
        for index, (number, state) in enumerate(states):
            event, phase = state["event"], state["reviewPhase"]
            if number != index + 1 or type(phase) is not int or type(event["receipt"]) is not int:
                raise ValueError("invalid state number, phase, or receipt")
            if max_transitions is not None and state["reviewTransitions"] != index:
                raise ValueError("invalid transition count")
            command = event["command"]
            if index == 0 and command == "" and phase == 0:
                action = "init"
            elif index > 0 and command == "" and phase == previous and phase in (0, 1):
                action = "internal (no report)"
            elif previous == 0 and phase == 1 and command == "stage" and event["wanted"] == REQUEST["wanted"]:
                action = HISTORIES[2][0]
                labels.append(action)
            elif (index == len(states) - 1 and previous == 1 and phase in HISTORIES
                  and command == "publish" and all(event[k] == v for k, v in REQUEST.items())
                  and (revision == REVISIONS["old"] or event["expectedFactor"] == FACTORS[phase])):
                action = HISTORIES[phase][1]
                labels.append(action)
            else:
                raise ValueError("unexpected transition for the selected history")
            trace.append({"action": action, "state": state})
            previous = phase
        if phase not in HISTORIES or tuple(labels) != HISTORIES[phase]:
            raise ValueError("trace did not finish a selected public history")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise Incomplete(f"cannot read TLC's witness: {error}") from error
    return (phase, event["receipt"]), trace


def compare(dml, quint, report):
    jar = backend_jar(quint)
    bound = report["scope"]["max_original_transitions"]
    with tempfile.TemporaryDirectory(prefix="git-quint-diff-scheduler-") as scratch:
        outcomes = {}
        for side, revision in report["revisions"].items():
            directory = Path(scratch) / side
            directory.mkdir()
            try:
                source = load_model(dml, revision, directory)
                tla = monitor(compile_tla(quint, source, source.stem), revision, bound)
                outcomes[side], report["closure"][side] = close_outcomes(
                    jar, source.with_suffix(".tla"), lambda seen: unseen(tla, seen),
                    lambda trace: read_witness(trace, revision, bound),
                    # A tight bound can genuinely make a history unreachable.
                    HISTORIES if bound is None else {}, init="ReviewStart", step="ReviewNext",
                )
            except (Incomplete, OSError, UnicodeError) as error:
                raise Incomplete(f"{side.upper()}: {error}") from error
    for phase, history in HISTORIES.items():
        frontier = {side: {r: trace for (p, r), trace in items.items() if p == phase}
                    for side, items in outcomes.items()}
        old, new = frontier["old"], frontier["new"]
        report["histories"].append({
            "public_history": history,
            "outcomes": {side: [{"receipt": r, "trace": items[r]} for r in sorted(items)]
                         for side, items in frontier.items()},
            "removed": sorted(old.keys() - new.keys()),
            "added": sorted(new.keys() - old.keys()),
        })
    report["status"] = "exhaustive" if bound is None else "bounded"


def terminal(report):
    scope = report["scope"]
    transitions = scope["max_original_transitions"]
    bound = "none" if transitions is None else str(transitions)
    print(f"OLD {report['revisions']['old']} → NEW {report['revisions']['new']}\n"
          f"Model: {report['model']} (original init and step)\n"
          f"Scope: {scope['scenario']}, two selected length-2 histories only\n"
          f"Internal: {scope['internal']}\n"
          f"Original transition bound: {bound}\n"
          "Bindings: stage alternate (12); publish alternate with expected main previousMain (3),\n"
          "          aliasesMain=false, failAt=0; factor 3 or −2 (legacy revision omits factor)\n"
          f"Observation: {scope['observation']} (0=absent, 12=alternate)\n"
          f"Backend: Quint {QUINT_VERSION} / Apalache {APALACHE_VERSION} / TLC\n"
          f"Status: {report['status']} ({len(report['histories'])} histories checked)")
    for side, stats in report["closure"].items():
        print(f"{side.upper()} closure: {stats['generated']} generated, {stats['distinct']} distinct, "
              f"{stats['queued']} queued in the final of {stats['rounds']} TLC runs")
    if "error" in report:
        for labels in scope["public_histories"]:
            print("Selected: " + " → ".join(labels))
        print(report["error"])
    for history in report["histories"]:
        print("\n" + " → ".join(history["public_history"]))
        for side, rows in history["outcomes"].items():
            if not rows:
                print(f"  {side.upper()}: no matching execution within scope")
            for row in rows:
                receipt = row["receipt"]
                delta = history["removed" if side == "old" else "added"]
                mark = ("− " if side == "old" else "+ ") if receipt in delta else "  "
                print(f"{mark}{side.upper()} receipt={receipt}")
                for frame in row["trace"]:
                    state = frame["state"]
                    source = state["source"]
                    print(f"    {frame['action']}: returning={str(state['returning']).lower()}, "
                          f"main={source['main']}, returned={source['returned']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dml", type=Path, help="DML checkout containing both original commits")
    parser.add_argument("quint", type=Path, help="path to Quint 0.34.0 executable")
    parser.add_argument("--self", action="store_true", help="compare OLD with itself")
    parser.add_argument("--max-transitions", type=int, help="impose an optional bound on original steps")
    parser.add_argument("--json", action="store_true", help="print experimental structured evidence")
    args = parser.parse_args()
    if args.max_transitions is not None and args.max_transitions < 0:
        parser.error("--max-transitions must be nonnegative")
    revisions = {**REVISIONS, "new": REVISIONS["old"]} if args.self else REVISIONS
    report = {
        "schema_version": 1, "status": "incomplete", "model": MODEL, "revisions": revisions,
        "scope": {"scenario": "initial_source (original init)", "public_histories": list(HISTORIES.values()),
                  "internal": INTERNAL, "observation": "event.receipt",
                  "bindings": {"stage": {"wanted": 12}, "publish": REQUEST,
                               "publish_expected_factor": {HISTORIES[p][1]: f for p, f in FACTORS.items()},
                               "revision_without_expected_factor": REVISIONS["old"]},
                  "max_original_transitions": args.max_transitions},
        "backend": {"quint": QUINT_VERSION, "apalache": APALACHE_VERSION, "checker": "TLC"},
        "limits": {"outcomes_per_side": MAX_OUTCOMES, "seconds_per_tool_invocation": ROUND_TIMEOUT},
        "histories": [], "closure": {},
    }
    try:
        compare(args.dml.resolve(), args.quint.absolute(), report)
    except (Incomplete, OSError) as error:
        report["error"] = str(error)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        terminal(report)
    return 0 if report["status"] != "incomplete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
