"""Replay experiment 2 with live Quint/TLC; requires DML_CHECKOUT and DML_QUINT."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import direct_actions as checker


SCRIPT = Path(checker.__file__).resolve()


@unittest.skipUnless(os.environ.get("DML_CHECKOUT") and os.environ.get("DML_QUINT"),
                     "set DML_CHECKOUT and DML_QUINT (0.34.0) to replay experiment 2")
class DirectActionsTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(os.environ["DML_CHECKOUT"]).resolve()
        self.quint = Path(os.environ["DML_QUINT"]).absolute()

    def cli(self, repo):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), str(repo), str(self.quint), "--json"],
                              capture_output=True, timeout=240)

    def test_exact_review_and_snapshot_isolation(self):
        proc = self.cli(self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["status"], "bounded")
        self.assertEqual(report["revisions"], checker.REVISIONS)
        self.assertEqual(report["max_public_depth"], 2)
        self.assertEqual(report["max_transitions"], 4)
        self.assertEqual(report["exhaustion"], {
            side: dict(generated=6, distinct=6, queued=0, rounds=3) for side in ("old", "new")
        })
        mismatch, matching = report["histories"]
        self.assertEqual(mismatch["public_history"], ["stage_alternate", "publish_alternate_expected_3"])
        self.assertEqual(matching["public_history"], ["stage_alternate", "publish_alternate_expected_minus_2"])
        self.assertEqual((mismatch["removed"], mismatch["added"]), ([[12, 12, 0]], [[0, 3, 12]]))
        self.assertEqual((matching["removed"], matching["added"]), ([], []))
        for phase, history in [(4, mismatch), (5, matching)]:
            for side, rows in history["outcomes"].items():
                row, = rows
                rejected = phase == 4 and side == "new"
                outcome = [0, 3, 12] if rejected else [12, 12, 0]
                self.assertEqual(row["observation"], outcome)
                witness = row["witness"]
                args = dict(wanted=12, expectedMain=3, aliasesMain=False, failAt=0)
                if side == "new":
                    args["expectedFactor"] = 3 if phase == 4 else -2
                self.assertEqual(witness["publish_arguments"], args)
                self.assertIs(witness["source_unchanged_after_publish"], rejected)
                self.assertEqual([state["phase"] for state in witness["states"]], [0, 1, 2, 3, phase])
                self.assertEqual([state["observation"] for state in witness["states"]],
                                 [[0, 3, 0], [0, 3, 0], [12, 3, 12], [0, 3, 12], outcome])
        with tempfile.TemporaryDirectory() as scratch:
            clone = Path(scratch) / "dml"
            subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(self.repo), str(clone)],
                           check=True, timeout=30)
            model = clone / checker.MODEL
            model.parent.mkdir()
            dirty = b"not valid Quint in the working tree\n"
            model.write_bytes(dirty)
            repeat = self.cli(clone)
            self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
            self.assertEqual(repeat.stdout, proc.stdout)
            self.assertEqual(model.read_bytes(), dirty)

    def test_enumerates_two_observations_for_one_history(self):
        # Temporary selector-only probe, not the DML review: let NEW phase 4
        # also take the matching branch. Presence of both outcomes must keep
        # OLD's common result out of the delta, regardless of witness order.
        render_driver = checker.render_driver

        def with_choice(side):
            driver = render_driver(side)
            if side == "new":
                branch, = (line for line in driver.splitlines() if "reviewPhase' = 5" in line)
                driver = driver.replace(branch, branch + "\n" + branch.replace("' = 5", "' = 4"))
            return driver

        report = {"histories": [], "exhaustion": {}}
        with patch.object(checker, "render_driver", with_choice):
            checker.compare(self.repo, self.quint, report)
        probe, _ = report["histories"]
        self.assertEqual([row["observation"] for row in probe["outcomes"]["new"]],
                         [(0, 3, 12), (12, 12, 0)])
        self.assertEqual((probe["removed"], probe["added"]), ([], [(0, 3, 12)]))
        self.assertEqual(report["exhaustion"]["new"], dict(generated=7, distinct=7, queued=0, rounds=4))

    def test_missing_fixture_path_cannot_create_a_false_delta(self):
        render_driver = checker.render_driver

        def without_matching(side):
            driver = render_driver(side)
            if side == "new":
                driver = "\n".join(line for line in driver.splitlines() if "reviewPhase' = 5" not in line)
            return driver

        report = {"status": "incomplete", "histories": [], "exhaustion": {}}
        with patch.object(checker, "render_driver", without_matching):
            with self.assertRaisesRegex(checker.Incomplete, "NEW: expected fixture path did not finish"):
                checker.compare(self.repo, self.quint, report)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["histories"], [])
        self.assertEqual(list(report["exhaustion"]), ["old"])

    def test_evaluation_failure_after_witness_cannot_create_a_false_delta(self):
        compile_snapshot = checker.compile_snapshot

        def with_fault(dml, quint, side, directory):
            tla = compile_snapshot(dml, quint, side, directory)
            if side == "new":
                self.assertIn("q_step == step", tla)
                # The first phase-4 witness still exists. Advancing the search
                # past it to prove absence fails when TLC evaluates its Next.
                tla = tla.replace("q_step == step", "q_step == IF reviewPhase # 4 THEN step ELSE Head(<<>>) = 0")
            return tla

        report = {"status": "incomplete", "histories": [], "exhaustion": {}}
        with patch.object(checker, "compile_snapshot", with_fault), \
                patch.object(checker, "read_witness", wraps=checker.read_witness) as read_witness:
            with self.assertRaisesRegex(checker.Incomplete, "NEW: TLC failed"):
                checker.compare(self.repo, self.quint, report)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["histories"], [])
        self.assertEqual(list(report["exhaustion"]), ["old"])
        self.assertIn("new", [args[0].parent.name for args, _ in read_witness.call_args_list])


if __name__ == "__main__":
    unittest.main()
