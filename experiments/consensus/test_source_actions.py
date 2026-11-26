"""Check source binding, erasure, and the fixed upstream consensus comparison."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import source_actions as checker


class WitnessTests(unittest.TestCase):
    def test_incomplete_frame_is_not_a_replayable_witness(self):
        init = {f"compiled_{name}": None for name in checker.NATIVE_FIELDS}
        init.update(compiled_round=1, compiled_reviewReceiveRound=0, ReviewPhase=0)
        public = {**init, "compiled_reviewReceiveRound": 1, "ReviewPhase": 1,
                  "compiled_procState": [{"S": [[]]}, {"S": []}]}
        data = {"counterexample": {"state": [[1, init], [2, public]]}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trace.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(checker.read_witness(path)[0], (1, 1))
            del init["compiled_newlyCrashed"]
            init["unexpectedField"] = []
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(checker.Incomplete, "expected one newlyCrashed"):
                checker.read_witness(path)


@unittest.skipUnless(os.environ.get("CONSENSUS_CHECKOUT") and os.environ.get("QUINT_HOME"),
                     "set CONSENSUS_CHECKOUT and use the pinned nix develop shell")
class SourceActionTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(os.environ["CONSENSUS_CHECKOUT"]).resolve()
        self.quint = shutil.which("quint")

    def cli(self, *args, code=0):
        proc = subprocess.run([sys.executable, "-B", str(Path(checker.__file__).resolve()), *map(str, args)],
                              capture_output=True, timeout=240)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return proc

    def read_blob(self, revision, name):
        return subprocess.check_output(["git", "--no-replace-objects", "-C", self.repo, "show",
                                        f"{revision}:{checker.MODEL_DIR}/{name}"], timeout=30)

    def test_stage_leaves_original_sources_and_guards_intact(self):
        for side, revision in checker.REVISIONS.items():
            with self.subTest(side=side), tempfile.TemporaryDirectory() as temp:
                staged = Path(temp) / side
                info = json.loads(self.cli("stage", self.repo, side, staged).stdout)
                self.assertEqual((info["site"]["line"], info["site"]["column"]), (248, 30))
                self.assertEqual(info["site"]["call"], "receiveMessages")
                self.assertEqual(info["site"]["callee"]["action"], "receiveMessages")
                self.assertEqual(info["site"]["tagged_leaves"], 5)
                self.assertEqual((staged / checker.FILES[0]).read_bytes(), self.read_blob(revision, checker.FILES[0]))
                tagged = (staged / checker.MODEL_FILE).read_bytes()
                original = self.read_blob(revision, checker.MODEL_FILE)
                chunk = re.search(rb"\n  var reviewReceiveRound: int\n  action reviewInit = [^\n]*\n"
                                  rb"  action reviewStep = (.*?)(?=\n\})\n", tagged, re.S)
                self.assertIsNotNone(chunk)
                self.assertEqual(tagged[:chunk.start()] + tagged[chunk.end():], original)
                native = re.search(rb"\n  action step =\s*(.*?)(?=\n\})", original, re.S)[1]
                monitored = chunk[1]
                # Unwrap the simple leaves independently and recover the
                # same original scheduler, including spacing and updates.
                erased, count = re.subn(rb"all \{ (.*?), reviewReceiveRound' = (?:round|0) \}", rb"\1", monitored)
                self.assertEqual(count, 5)
                self.assertEqual(erased, native)

    def test_stale_ambiguous_missing_or_nested_source_binding_fails_closed(self):
        revision = checker.REVISIONS["old"]
        original = self.read_blob(revision, checker.MODEL_FILE)
        for name, actual, position, message in (
            ("stale", original, (248, 31), "stale source selector"),
            ("duplicate", original.replace(b"all { sendMessages, stage'", b"all { receiveMessages, stage'"),
             (248, 30), "expected one direct scheduler call .* found 2"),
            ("indirect", original.replace(b"all { receiveMessages, stage'", b"all { lookalike, stage'")
             .replace(b"  action step =", b"  action lookalike = receiveMessages\n\n  action step ="),
             (250, 30), "expected one direct scheduler call .* found 0"),
            ("unsupported", original.replace(b"all { receiveMessages, stage'",
                                             b"all { any { receiveMessages, receiveMessages }, stage'"),
             (248, 30), "unsupported scheduler shape"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                driver, _ = checker.snapshot(self.repo, revision, directory)
                path = directory / checker.MODEL_FILE
                path.write_bytes(actual)
                with self.assertRaisesRegex(checker.Incomplete, message):
                    checker.instrument(self.quint, driver, position)
                self.assertEqual(path.read_bytes(), actual)

    def test_binding_failure_result_has_scope_but_no_deltas(self):
        stdout = io.StringIO()
        with (patch.object(checker, "scheduler_leaves", side_effect=checker.Incomplete("unsupported scheduler shape")),
              patch.object(sys, "argv", ["source_actions.py", "compare", str(self.repo), "--json"]),
              redirect_stdout(stdout)):
            self.assertEqual(checker.main(), 1)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["histories"], [])
        self.assertEqual(report["closure"], {})
        self.assertEqual(report["scope"]["public_histories"], [list(history) for history in checker.HISTORIES.values()])
        self.assertIn("OLD: unsupported scheduler shape", report["error"])

    def test_self_then_change_and_dirty_checkout(self):
        def check(repo, *flags):
            result = json.loads(self.cli("compare", repo, "--json", *flags).stdout)
            self.assertEqual(result["status"], "exhaustive")
            self.assertIsNone(result["scope"]["max_original_transitions"])
            for side, stats in result["closure"].items():
                count = sum(len(h["outcomes"][side]) for h in result["histories"])
                self.assertEqual(stats["rounds"], count + 1)
                self.assertEqual(stats["queued"], 0)
            return result

        def projections(report):
            return [[tuple(row["omissions"] for row in h["outcomes"][side]) for side in ("old", "new")]
                    for h in report["histories"]]

        same = check(self.repo, "--self")
        self.assertEqual(projections(same), [[(0,), (0,)]] * 2)
        self.assertTrue(all(not h["added"] and not h["removed"] for h in same["histories"]))
        diff = check(self.repo)
        self.assertEqual(diff["revisions"], checker.REVISIONS)
        self.assertEqual(projections(diff), [[(0,), (0, 1, 2)], [(0,), (0,)]])
        self.assertEqual([(h["removed"], h["added"]) for h in diff["histories"]], [([], [1, 2]), ([], [])])
        for h in diff["histories"]:
            for rows in h["outcomes"].values():
                for row in rows:
                    trace = row["trace"]
                    self.assertEqual([f["public_label"] for f in trace if f["public_label"]], h["public_history"])
                    self.assertEqual(len(trace) - 1, 3 if len(h["public_history"]) == 1 else 7)
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp) / "upstream"
            subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", self.repo, checkout],
                           check=True, timeout=30)
            directory = checkout / checker.MODEL_DIR
            directory.mkdir(parents=True)
            for filename in checker.FILES:
                (directory / filename).write_bytes(b"dirty invalid Quint\n")
            self.assertEqual(check(checkout), diff)  # Includes witness and outcome order.
            self.assertTrue(all((directory / name).read_bytes() == b"dirty invalid Quint\n" for name in checker.FILES))


if __name__ == "__main__":
    unittest.main()
