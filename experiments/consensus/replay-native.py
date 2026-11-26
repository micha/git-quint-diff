"""Called by native-oracle.sh to check complete original-state traces using TLC.

The independently compiled native q_init and q_step remain unchanged. Replay
adds a cursor and restricts the original variables to the supplied states in
order. A counterexample at the last index covers the whole path.
"""

import json
import os
from pathlib import Path
import subprocess
import sys


REPORT_PREFIX = "review_KSetAgreementConsensus_"
NATIVE_PREFIX = "native_oracle_KSetAgreementConsensus_"
FIELDS = ("round", "stage", "crashed", "newlyCrashed", "correctProcsMessages",
          "crashedProcsMessages", "procState")
CALL = {"Starting": "crash", "Sending": "sendMessages",
        "Receiving": "receiveMessages", "Computing": "computeAction"}


def literal(value, *, sequence=False):
    if type(value) is int:
        return str(value)
    if isinstance(value, str) and value == "UNIT":
        return '"UNIT"'
    if isinstance(value, dict):
        if not value or any(not key.isascii() or not key.isalpha() for key in value):
            raise ValueError("unexpected TLC record key")
        return "[" + ", ".join(f"{key} |-> {literal(item)}" for key, item in value.items()) + "]"
    if isinstance(value, list):
        start, end = ("<<", ">>") if sequence else ("{", "}")
        return start + ", ".join(map(literal, value)) + end
    raise ValueError("unexpected TLC state value")


def frame_predicates(row, history):
    states = [{field: frame["state"][REPORT_PREFIX + field] for field in FIELDS}
              for frame in row["trace"]]
    labels = []
    for i, frame in enumerate(row["trace"]):
        call, label = "init", None
        if i:
            prior = states[i - 1]
            call = CALL[next(iter(prior["stage"]))]
            if call == "receiveMessages":
                label = f"receive_round_{prior['round']}"
                labels.append(label)
        if frame["call"] != call or frame["public_label"] != label:
            raise ValueError("call labels disagree with the native scheduler")
    if (not states or labels != history or label != history[-1]
            or sum([] in process["S"] for process in states[-1]["procState"]) != row["omissions"]):
        raise ValueError("trace did not realize the declared history/outcome")
    predicates = []
    for i, state in enumerate(states):
        prime = "'" if i else ""
        predicates.append(" /\\ ".join(
            f"{NATIVE_PREFIX}{field}{prime} = {literal(state[field], sequence=(field == 'procState'))}"
            for field in FIELDS
        ))
    return predicates


def execute(args, directory):
    return subprocess.run(args, cwd=directory, capture_output=True, text=True, timeout=120)


def replay(directory, jar, row, history):
    states = frame_predicates(row, history)
    cases = "\n    \\/ ".join(f"(cursor = {i} /\\ {predicate})" for i, predicate in enumerate(states[1:]))
    (directory / "replay.tla").write_text(rf'''---- MODULE replay ----
EXTENDS native_oracle
VARIABLE cursor
ReplayInit == q_init /\ cursor = 0 /\ {states[0]}
ReplayNext ==
  /\ cursor < {len(states) - 1}
  /\ cursor' = cursor + 1
  /\ q_step
  /\ \/ {cases}
NeverFinish == cursor < {len(states) - 1}
====
''', encoding="utf-8")
    result = execute([
        "java", "-Xmx512m", "-cp", str(jar), "tlc2.TLC", "-deadlock", "-workers", "1",
        "-noGenerateSpecTE", "replay.tla",
    ], directory)
    if result.returncode != 12 or "Error: Invariant NeverFinish is violated." not in result.stdout:
        raise ValueError(f"trace did not replay through the original scheduler:\n{result.stdout}{result.stderr}")


def main(scratch, report_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old, new = report["revisions"]["old"], report["revisions"]["new"]
    if (report["status"] != "exhaustive" or old != "883cc2c579bd11954129d207899790e80fb8c91e"
            or new not in {old, "35df73a703259890303659e421f79016897993b3"}):
        raise ValueError("expected an exhaustive report for the designated consensus revisions")
    expected = [
        (["receive_round_1"], [0], [0] if new == old else [0, 1, 2]),
        (["receive_round_1", "receive_round_2"], [0], [0]),
    ]
    for entry, (history, old_set, new_set) in zip(report["histories"], expected, strict=True):
        if (entry["public_history"] != history
                or [row["omissions"] for row in entry["outcomes"]["old"]] != old_set
                or [row["omissions"] for row in entry["outcomes"]["new"]] != new_set):
            raise ValueError("report disagrees with the native oracle's outcome sets")
        if (entry["removed"] != sorted(set(old_set) - set(new_set))
                or entry["added"] != sorted(set(new_set) - set(old_set))):
            raise ValueError("report deltas do not match the verified outcome sets")

    jar = Path(os.environ["QUINT_HOME"]).resolve() / "apalache-dist-0.62.4/apalache/lib/apalache.jar"
    for side in ("old", "new"):
        directory = scratch / ("old" if new == old else side)
        result = execute([
            "quint", "compile", "native_oracle.qnt", "--target", "tlaplus", "--invariant", "true",
            "--verbosity", "0", "--apalache-version", "0.62.4", "--server-endpoint",
            os.environ.get("CONSENSUS_ORACLE_ENDPOINT", "localhost:19854"),
        ], directory)
        if result.returncode or "MODULE native_oracle" not in result.stdout:
            raise ValueError(f"could not compile native scheduler:\n{result.stdout}{result.stderr}")
        (directory / "native_oracle.tla").write_text(result.stdout, encoding="utf-8")
        (directory / "replay.cfg").write_text("INIT ReplayInit\nNEXT ReplayNext\nINVARIANT NeverFinish\n",
                                              encoding="utf-8")
        for entry in report["histories"]:
            for row in entry["outcomes"][side]:
                replay(directory, jar, row, entry["public_history"])
                print(f"replayed {side} {' -> '.join(entry['public_history'])}: {row['omissions']}")


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.TimeoutExpired) as error:
        sys.exit(str(error))
