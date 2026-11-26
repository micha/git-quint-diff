"""Replay experiment 3 with live Quint/TLC; requires DML_CHECKOUT and DML_QUINT."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import scheduler_actions as checker


@unittest.skipUnless(os.environ.get("DML_CHECKOUT") and os.environ.get("DML_QUINT"),
                     "set DML_CHECKOUT and DML_QUINT (0.34.0) to replay experiment 3")
class SchedulerActionsTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(os.environ["DML_CHECKOUT"]).resolve()
        self.quint = Path(os.environ["DML_QUINT"]).absolute()

    def cli(self, *flags, repo=None, quint=None, code=0):
        proc = subprocess.run([
            sys.executable, "-B", str(Path(checker.__file__).resolve()),
            str(repo or self.repo), str(quint or self.quint), "--json", *flags,
        ], capture_output=True, timeout=240)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def outcomes(self, report):
        return [tuple([row["receipt"] for row in h["outcomes"][s]] for s in ("old", "new"))
                for h in report["histories"]]

    def deltas(self, report):
        return [(h["removed"], h["added"]) for h in report["histories"]]

    def test_native_self_comparison_then_removal(self):
        same = self.cli("--self")
        self.assertEqual(same["revisions"], {s: checker.REVISIONS["old"] for s in ("old", "new")})
        self.assertEqual(self.outcomes(same), [([0, 12], [0, 12])] * 2)
        self.assertEqual(self.deltas(same), [([], [])] * 2)

        diff = self.cli()
        self.assertEqual(diff["revisions"], checker.REVISIONS)
        self.assertEqual(self.outcomes(diff), [([0, 12], [0]), ([0, 12], [0, 12])])
        self.assertEqual(self.deltas(diff), [([12], []), ([], [])])
        for report in (same, diff):
            self.assertEqual(report["status"], "exhaustive")
            self.assertIsNone(report["scope"]["max_original_transitions"])
            for side, stats in report["closure"].items():
                count = sum(len(h["outcomes"][side]) for h in report["histories"])
                self.assertEqual(stats, dict(generated=572, distinct=182, queued=0, rounds=count + 1))

        mismatch, matching = diff["histories"]
        for history, factor in [(mismatch, 3), (matching, -2)]:
            for side, rows in history["outcomes"].items():
                for row in rows:
                    trace, receipt = row["trace"], row["receipt"]
                    self.assertEqual([f["action"] for f in trace if f["state"]["event"]["command"]],
                                     history["public_history"])
                    event, after = (trace[-1]["state"][field] for field in ("event", "source"))
                    before = trace[-2]["state"]["source"]
                    self.assertEqual(event["receipt"], receipt)
                    self.assertEqual(event["before"], before)
                    self.assertEqual(event["expectedMain"], 3)
                    self.assertEqual(event["wanted"], 12)
                    self.assertFalse(event["aliasesMain"])
                    self.assertEqual(event["failAt"], 0)
                    if side == "old":
                        self.assertNotIn("expectedFactor", event)
                    else:
                        self.assertEqual(event["expectedFactor"], factor)
                    if receipt == 12:
                        self.assertEqual((before["main"], before["returned"]), (3, 12))
                        self.assertEqual(after, {**before, "main": 12, "returned": 0})
                    else:
                        self.assertEqual(after, before)
                        if side == "old" or factor == -2:
                            self.assertTrue(before["main"] != 3 or before["returned"] != 12)
                        else:
                            self.assertEqual((before["main"], before["returned"]), (3, 12))

        with tempfile.TemporaryDirectory() as scratch:
            clone = Path(scratch) / "dml"
            subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(self.repo), str(clone)],
                           check=True, timeout=30)
            source = clone / checker.MODEL
            source.parent.mkdir()
            source.write_text("not valid Quint\n", encoding="utf-8")
            self.assertEqual(self.cli(repo=clone), diff)  # Includes witness and outcome order.
            self.assertEqual(source.read_text(encoding="utf-8"), "not valid Quint\n")

    def test_internal_schedule_bound_changes_only_scoped_deltas(self):
        empty, short, race = [self.cli("--max-transitions", str(bound)) for bound in (3, 4, 5)]
        for report, bound in [(empty, 3), (short, 4), (race, 5)]:
            self.assertEqual(report["status"], "bounded")
            self.assertEqual(report["scope"]["max_original_transitions"], bound)
            self.assertTrue(all(stats["queued"] == 0 for stats in report["closure"].values()))
        self.assertEqual(self.outcomes(empty), [([], [])] * 2)
        self.assertEqual(self.deltas(empty), [([], [])] * 2)
        self.assertEqual(self.outcomes(short), [([12], [0]), ([12], [12])])
        self.assertEqual(self.deltas(short), [([12], [0]), ([], [])])
        self.assertEqual(self.outcomes(race), [([0, 12], [0]), ([0, 12], [0, 12])])
        self.assertEqual(self.deltas(race), [([12], []), ([], [])])

    def test_unavailable_backend_does_not_create_empty_frontiers(self):
        with tempfile.TemporaryDirectory() as scratch:
            report = self.cli(quint=Path(scratch) / "missing-quint", code=1)
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("missing-quint", report["error"])
        self.assertEqual(report["histories"], [])
        self.assertEqual(report["closure"], {})


if __name__ == "__main__":
    unittest.main()
