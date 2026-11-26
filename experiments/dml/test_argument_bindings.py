"""Verify DML source binding; live checks need DML_CHECKOUT and DML_QUINT (0.34.0)."""

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import argument_bindings as checker


class WitnessTests(unittest.TestCase):
    def read(self, frames, side="old"):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "trace.json"
            path.write_text(json.dumps({"counterexample": {"state": list(enumerate(frames, 1))}}))
            return checker.read_witness(path, side)

    def test_phase_reads_tags_and_not_event_reports(self):
        def state(tag, phase):
            # No usable event command or request fields; only the observation.
            return {"returning": False, "worker": {}, "source": {}, "event": {"receipt": 0},
                    "reviewCall": tag, "reviewPhase": phase}

        frames = [state(0, 0), state(1, 1), state(0, 1), state(5, 2)]
        self.assertEqual(self.read(frames)[0], (2, 0))
        frames[-1]["reviewPhase"] = 3
        self.assertEqual(self.read(frames)[0], (3, 0))
        with self.assertRaises(checker.Incomplete):
            self.read(frames, "new")
        frames[-1]["reviewCall"] = 3
        self.assertEqual(self.read(frames, "new")[0], (3, 0))
        frames[2]["reviewCall"] = 4  # Cannot be silently skipped.
        with self.assertRaises(checker.Incomplete):
            self.read(frames, "new")
        frames[2]["reviewCall"] = 0
        del frames[2]["worker"]
        with self.assertRaisesRegex(checker.Incomplete, "original fields"):
            self.read(frames, "new")


@unittest.skipUnless(os.environ.get("DML_CHECKOUT") and os.environ.get("DML_QUINT"),
                     "set DML_CHECKOUT and DML_QUINT to replay experiment 7")
class SourceActionsTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(os.environ["DML_CHECKOUT"]).resolve()
        self.quint = Path(os.environ["DML_QUINT"]).absolute()

    def cli(self, *flags, repo=None, code=0):
        proc = subprocess.run([sys.executable, "-B", checker.__file__, "compare", str(repo or self.repo),
                               str(self.quint), "--json", *flags], capture_output=True, timeout=240)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_self_then_change_and_dirty_checkout(self):
        same = self.cli("--self")
        diff = self.cli()
        for report, expected in ((same, [[[0, 12], [0, 12]]] * 2),
                                 (diff, [[[0, 12], [0]], [[0, 12], [0, 12]]])):
            self.assertEqual(report["status"], "exhaustive")
            self.assertIsNone(report["scope"]["max_original_transitions"])
            for side, stats in report["closure"].items():
                count = sum(len(h["outcomes"][side]) for h in report["histories"])
                self.assertEqual(stats, dict(generated=572, distinct=182, queued=0, rounds=count + 1))
            for history, frontiers in zip(report["histories"], expected):
                self.assertEqual([[row["receipt"] for row in history["outcomes"][s]] for s in ("old", "new")], frontiers)
                old, new = map(set, frontiers)
                self.assertEqual(history["removed"], sorted(old - new))
                self.assertEqual(history["added"], sorted(new - old))
                for side, rows in history["outcomes"].items():
                    for row in rows:
                        trace = row["trace"]
                        public_frames = [f for f in trace if f["action"] not in {"init", "hidden"}]
                        self.assertEqual([f["action"] for f in public_frames], history["public_history"])
                        self.assertEqual(public_frames[0]["state"]["reviewCall"], 1)
                        last = trace[-1]["state"]
                        legacy = report["revisions"][side] == checker.REVISIONS["old"]
                        self.assertEqual(last["reviewCall"], 5 if legacy else last["reviewPhase"])
                        self.assertEqual(last["event"]["receipt"], row["receipt"])

        with tempfile.TemporaryDirectory() as scratch:
            clone = Path(scratch) / "dml"
            subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(self.repo), str(clone)],
                           check=True, timeout=30)
            dirty = clone / checker.MODEL
            dirty.parent.mkdir()
            dirty.write_bytes(b"not valid Quint\n")
            self.assertEqual(self.cli(repo=clone), diff)  # Includes witness order.
            self.assertEqual(dirty.read_bytes(), b"not valid Quint\n")

    def test_sibling_erasure_preserves_guards_nondet_and_calls(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            for side, revision in checker.REVISIONS.items():
                tagged, meta = checker.stage(self.quint, self.repo, side, scratch / side)
                original = subprocess.check_output(["git", "--no-replace-objects", "-C", str(self.repo),
                                                    "show", f"{revision}:{checker.MODEL}"]).decode("ascii")
                self.assertEqual(len(meta["sites"]), 14)
                unchanged, addons = tagged.read_bytes().decode("ascii").split("\n  var reviewCall: int\n", 1)
                self.assertEqual(unchanged + "}\n", original)
                addons = addons.split("\n  action reviewWorkerStep = ", 1)[1].removesuffix("\n}\n")
                # Remove only outer wrappers and restore the two routing names.
                erased = []
                for line in addons.splitlines():
                    if ", reviewCall' = " in line:
                        line = re.sub(r", reviewCall' = .* \}(,?)$", r"\1", line)
                        line = line.replace("all { ", "", 1)
                    elif "all { all {" in line:
                        line = line.replace("all { ", "", 1)
                    erased.append(line)
                restored = "\n".join(erased).replace("if (not(returning)) reviewWorkerStep", "if (not(returning)) workerStep")
                restored = restored.replace("else reviewSourceStep", "else sourceStep")
                restored = restored.replace("\n  action reviewSourceStep =", "\n\n  action sourceStep =")
                restored = restored.replace("\n  action reviewStep = ", "\n\n  action step =\n    ")
                schedulers = original.split("  action workerStep = ", 1)[1].split("\n\n  // Fixture-level oracle", 1)[0]
                schedulers = re.sub(r"\n\n  // Check each operation report.*?\n  action step", "\n\n  action step",
                                    schedulers, flags=re.S)
                self.assertEqual(restored, schedulers)

    def test_stale_duplicate_and_unsupported_bindings_fail_closed(self):
        def try_stage(needle, replacement, diagnostic):
            with tempfile.TemporaryDirectory() as scratch:
                path = Path(scratch) / Path(checker.MODEL).name
                checker.snapshot(self.repo, checker.REVISIONS["new"], path)
                original = path.read_text()
                self.assertIn(needle, original)
                modified = original.replace(needle, replacement, 1)
                path.write_text(modified)
                with self.assertRaisesRegex(checker.Incomplete, diagnostic):
                    checker.instrument(self.quint, path, checker.SITES["new"])
                self.assertEqual(path.read_text(), modified)

        try_stage("    stage(root),", "     stage(root),", "stale or unclassified")
        try_stage("nondet mode = Set(0, 1, 2, 3).oneOf()", "val mode = 0", "unsupported scheduler shape")
        try_stage("publish(root, expectedMain, expectedFactor,", "publish(alternate, expectedMain, expectedFactor,",
                  "unsupported signature or source argument")
        selectors = copy.deepcopy(checker.SITES["new"])
        selectors["sourceStep"].append(selectors["sourceStep"][0])
        with tempfile.TemporaryDirectory() as scratch, patch.dict(checker.SITES, {"new": selectors}):
            with self.assertRaisesRegex(checker.Incomplete, "duplicate source selector"):
                checker.stage(self.quint, self.repo, "new", Path(scratch) / "tagged")

        with tempfile.TemporaryDirectory() as scratch:
            report = self.cli(repo=Path(scratch), code=1)
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["histories"], [])
            self.assertEqual(report["closure"], {})


if __name__ == "__main__":
    unittest.main()
