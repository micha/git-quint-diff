#!/usr/bin/env python3
"""Compare two fixed public histories on exact DML Git snapshots using Quint/TLC."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from direct_actions_driver import DRIVER_FILE, DRIVER_MODULE, HISTORIES, render_driver


MODEL = "tests/recorded_return_design.qnt"
REVISIONS = {
    "old": "819ac9d9c496bf652ea85af12b3369844df2b1e4",
    "new": "c540078318bf52313a33d856c7825d6b09566b17",
}
QUINT_VERSION = "0.34.0"
APALACHE_VERSION = "0.62.4"
ROUND_TIMEOUT = 120  # seconds per tool invocation
MAX_OUTCOMES = 32  # per side; hitting this without closure is incomplete
PHASE = "reviewPhase"
PROJECTION = ("dml_event.receipt", "dml_source.main", "dml_source.returned")
INVARIANT = "ReviewNoUnseenOutcome"
TRANSITIONS = (
    "init", "startReturn", "stage(alternate)", "step (clear event)", "publish(alternate)",
)
STATS = re.compile(
    r"^(\d+) states generated, (\d+) distinct states found, (\d+) states left on queue\.$", re.M,
)


class Incomplete(Exception):
    """A tooling failure or unsupported case, never evidence of absence."""


def run(args, directory=None):
    try:
        return subprocess.run(
            args, cwd=directory, capture_output=True, timeout=ROUND_TIMEOUT,
            env={**os.environ, "LC_ALL": "C", "NO_COLOR": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Incomplete(f"{Path(args[0]).name}: {error}") from error


def log_text(proc):
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def require_success(proc, operation):
    if proc.returncode:
        raise Incomplete(f"{operation} (exit {proc.returncode}):\n{log_text(proc).strip()}")
    return proc.stdout


def compile_snapshot(dml, quint, side, directory):
    # These exact revisions of this fixed entrypoint have no transitive imports.
    # Copy bytes from the commit only, not from the checkout or from a syntax shim.
    blob = require_success(run([
        "git", "--no-replace-objects", "-C", str(dml), "cat-file", "blob",
        f"{REVISIONS[side]}:{MODEL}",
    ]), "read committed model")
    (directory / Path(MODEL).name).write_bytes(blob)
    (directory / DRIVER_FILE).write_text(render_driver(side), encoding="utf-8")
    tla = require_success(run([
        str(quint), "compile", DRIVER_FILE, "--target", "tlaplus", "--init", "init",
        "--step", "step", "--verbosity", "0", "--apalache-version", APALACHE_VERSION,
        "--server-endpoint", os.environ.get("DML_TLC_ENDPOINT", "localhost:18822"),
    ], directory), "compile selected Quint actions").decode("utf-8")
    if not re.search(r"^----+ MODULE " + DRIVER_MODULE + r" ----+$", tla, re.M):
        raise Incomplete("Quint did not emit the expected TLA+ module")
    return tla


def int_literal(value):
    return str(value) if value >= 0 else f"({value})"


def invariant(tla, seen):
    # Check that every end state projects to an already witnessed pair of
    # (history, outcome). With no witnesses, all end states violate the check.
    body, separator, terminator = tla.rstrip().rpartition("\n")
    if not separator or not re.fullmatch(r"=+", terminator):
        raise Incomplete("TLA+ module has no terminator")
    end = " \\/ ".join(f"{PHASE} = {phase}" for phase in HISTORIES)
    known = []
    for phase, outcome in sorted(seen):
        comparison = [f"{PHASE} = {phase}"] + [
            f"{field} = {int_literal(value)}" for field, value in zip(PROJECTION, outcome)
        ]
        known.append("(" + " /\\ ".join(comparison) + ")")
    allowed = " \\/ ".join(known) or "FALSE"
    return f"{body}\n\n{INVARIANT} == ({end}) => ({allowed})\n====\n"


def read_witness(path):
    try:
        states = json.loads(path.read_text(encoding="utf-8"))["counterexample"]["state"]
        if len(states) != len(TRANSITIONS):
            raise ValueError("unexpected trace length")
        rows = []
        sources = []
        phases = []
        for index, (number, state) in enumerate(states):
            phase = state[PHASE]
            event = state["dml_event"]
            source = state["dml_source"]
            observation = (event["receipt"], source["main"], source["returned"])
            returning = state["dml_returning"]
            if (number != index + 1 or type(phase) is not int or type(returning) is not bool
                    or any(type(n) is not int for n in observation)):
                raise ValueError("unexpected state number, phase or projection")
            rows.append({"action": TRANSITIONS[index], "phase": phase, "command": event["command"],
                         "returning": returning, "observation": observation})
            phases.append(phase)
            sources.append(source)
        if (phases[:-1] != [0, 1, 2, 3] or phases[-1] not in HISTORIES
                or [row["command"] for row in rows] != ["", "", "stage", "", "publish"]
                or [row["returning"] for row in rows] != [False, True, True, True, True]):
            raise ValueError("trace did not follow the selected scheduler path")
        publish = {field: event[field] for field in ("wanted", "expectedMain", "aliasesMain", "failAt")}
        if "expectedFactor" in event:
            publish["expectedFactor"] = event["expectedFactor"]
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise Incomplete(f"cannot read TLC's witness: {error}") from error
    return (phases[-1], rows[-1]["observation"]), {
        "states": rows, "publish_arguments": publish,
        "source_unchanged_after_publish": sources[-1] == sources[-2],
    }


def enumerate_outcomes(jar, directory, tla):
    """Keep covering new projections until an exhaustive TLC run proves closure."""
    source = directory / f"{DRIVER_MODULE}.tla"
    source.with_suffix(".cfg").write_text(
        f"INIT q_init\nNEXT q_step\nINVARIANT {INVARIANT}\n", encoding="utf-8",
    )
    trace = directory / "witness.json"
    seen = {}
    for round_number in range(1, MAX_OUTCOMES + 2):
        trace.unlink(missing_ok=True)
        source.write_text(invariant(tla, seen), encoding="utf-8")
        proc = run([
            "java", "-Xmx512m", "-XX:+UseParallelGC", "-cp", str(jar), "tlc2.TLC",
            "-deadlock", "-workers", "1", "-fp", "0", "-noGenerateSpecTE",
            "-dumpTrace", "json", trace.name, source.name,
        ], directory)
        log = log_text(proc)
        if proc.returncode == 0:
            stats = STATS.findall(log)
            # TLC can report a zero queue even when it stopped at a witness.
            # Require explicit successful model checking, not just the statistic.
            if ("Model checking completed. No error has been found." not in log
                    or len(stats) != 1 or int(stats[0][2]) != 0 or trace.exists()):
                raise Incomplete(f"TLC did not confirm exhaustion:\n{log.strip()}")
            missing = set(HISTORIES) - {phase for phase, _ in seen}
            if missing:
                labels = "; ".join(" → ".join(HISTORIES[phase]) for phase in sorted(missing))
                raise Incomplete(f"expected fixture path did not finish: {labels}")
            return seen, dict(zip(("generated", "distinct", "queued"), map(int, stats[0])), rounds=round_number)
        if (proc.returncode != 12
                or f"Error: Invariant {INVARIANT} is violated." not in log):
            raise Incomplete(f"TLC failed (exit {proc.returncode}):\n{log.strip()}")
        key, witness = read_witness(trace)
        if key in seen:
            raise Incomplete(f"TLC returned an already excluded outcome: {key}")
        if len(seen) == MAX_OUTCOMES:
            raise Incomplete(f"more than {MAX_OUTCOMES} distinct history/outcome pairs on this side")
        seen[key] = witness


def compare(dml, quint, report):
    if require_success(run([str(quint), "--version"]), "check Quint version").strip() != QUINT_VERSION.encode():
        raise Incomplete(f"expected Quint {QUINT_VERSION}; the default prototype shell pins 0.33.1")
    home = os.environ.get("QUINT_HOME")
    if not home:
        raise Incomplete("QUINT_HOME is not set; use the project's nix develop shell")
    jar = Path(home).resolve() / f"apalache-dist-{APALACHE_VERSION}/apalache/lib/apalache.jar"
    if not jar.is_file():
        raise Incomplete(f"missing TLC jar: {jar}")
    with tempfile.TemporaryDirectory(prefix="git-quint-diff-direct-") as scratch:
        outcomes = {}
        for side in REVISIONS:
            directory = Path(scratch) / side
            directory.mkdir()
            try:
                tla = compile_snapshot(dml, quint, side, directory)
                outcomes[side], report["exhaustion"][side] = enumerate_outcomes(jar, directory, tla)
            except (Incomplete, OSError, UnicodeError) as error:
                raise Incomplete(f"{side.upper()}: {error}") from error
    for phase, history in HISTORIES.items():
        frontier = {
            side: {outcome: witness for (end, outcome), witness in reached.items() if end == phase}
            for side, reached in outcomes.items()
        }
        old, new = (frontier[side] for side in REVISIONS)
        report["histories"].append({
            "public_history": history,
            "outcomes": {
                side: [{"observation": obs, "witness": reached[obs]} for obs in sorted(reached)]
                for side, reached in frontier.items()
            },
            "removed": sorted(old.keys() - new.keys()),
            "added": sorted(new.keys() - old.keys()),
        })
    report["status"] = "bounded"


def terminal(report):
    print(f"OLD {REVISIONS['old']} → NEW {REVISIONS['new']}\nModel: {MODEL}")
    print("Scenario: initial_source; two selected length-2 public histories, four transitions each\n"
          "Observation: (event.receipt, source.main, source.returned)\n"
          f"Backend: Quint {QUINT_VERSION} / Apalache {APALACHE_VERSION} / TLC")
    print(f"Status: {report['status']} ({len(report['histories'])} histories checked)")
    for side, stats in report["exhaustion"].items():
        print(f"{side.upper()} closure: {stats['generated']} generated, {stats['distinct']} distinct, "
              f"{stats['queued']} queued in the final of {stats['rounds']} TLC runs")
    if "error" in report:
        for history in report["selected_histories"]:
            print("Selected: " + " → ".join(history))
        print(report["error"])
        return
    for history in report["histories"]:
        print("\n" + " → ".join(history["public_history"]))
        for side, outcome_rows in history["outcomes"].items():
            for row in outcome_rows:
                outcome, witness = row["observation"], row["witness"]
                changed = outcome in history["removed" if side == "old" else "added"]
                mark = ("− " if side == "old" else "+ ") if changed else "  "
                path = " → ".join(f"{state['action']}: {state['observation']}" for state in witness["states"])
                unchanged = "yes" if witness["source_unchanged_after_publish"] else "no"
                print(f"{mark}{side.upper()} {outcome}; source unchanged by publish: {unchanged}\n    {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dml", type=Path, help="DML checkout containing both original commits")
    parser.add_argument("quint", type=Path, help="path to Quint 0.34.0 executable")
    parser.add_argument("--json", action="store_true", help="print experimental structured evidence")
    args = parser.parse_args()
    report = {
        "schema_version": 1, "status": "incomplete", "model": MODEL, "revisions": REVISIONS,
        "scenario": "initial_source", "observation": ["event.receipt", "source.main", "source.returned"],
        "selected_histories": list(HISTORIES.values()), "max_public_depth": 2, "max_transitions": 4,
        "backend": {"quint": QUINT_VERSION, "apalache": APALACHE_VERSION, "checker": "TLC"},
        "limits": {"outcomes_per_side": MAX_OUTCOMES, "seconds_per_tool_invocation": ROUND_TIMEOUT},
        "histories": [], "exhaustion": {},
    }
    try:
        compare(args.dml.resolve(), args.quint.absolute(), report)
    except (Incomplete, OSError) as error:
        report["error"] = str(error)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        terminal(report)
    return 0 if report["status"] == "bounded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
