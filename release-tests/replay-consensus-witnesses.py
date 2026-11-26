"""Replay the additions from the documented upstream consensus review."""

import argparse
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from consensus_fixture import COMMITS
from consensus_oracle import native_graph, replay_witness


SCENARIO = "consensus_two_rounds"
HISTORY = ["receive_round_1"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="Git repository containing both upstream commits")
    parser.add_argument("report", type=Path, help="JSON report from OLD → NEW")
    args = parser.parse_args()

    try:
        report = json.loads(args.report.read_text(encoding="utf8"))
        if (report["version"] != 1 or report["status"] != "exhaustive" or report["scenario"] != SCENARIO
                or any(report[side]["revision"] != commit for side, commit in COMMITS.items())):
            raise ValueError("expected the exhaustive JSON v1 report for the documented OLD → NEW review")
        rows = [row for row in report["histories"] if row["history"] == HISTORY]
        deltas = rows[0]["deltas"] if len(rows) == 1 else []
        if (any(type(d["outcome"]) is not int for d in deltas)
                or [(d["change"], d["outcome"]) for d in deltas] != [("+", 1), ("+", 2)]):
            raise ValueError("expected round-one additions +1 and +2")
        revision = COMMITS["new"]
        with TemporaryDirectory() as scratch:
            graph = native_graph(args.repo.resolve(), revision, Path(scratch) / "native",
                                 os.environ | {"GIT_NO_LAZY_FETCH": "1"})
            for delta in deltas:
                replay_witness(graph, delta["witness"], revision=revision, scenario=SCENARIO,
                               history=HISTORY, outcome=delta["outcome"])
    except (AssertionError, AttributeError, KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Replay failed: {error}\n")

    for delta in deltas:
        print(f"Replayed +{delta['outcome']} at {revision} through original init and "
              f"{len(delta['witness']['steps'])} original step transitions")


if __name__ == "__main__":
    main()
