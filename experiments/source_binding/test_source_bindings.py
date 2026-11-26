import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from make_fixture import FIXTURES, make_fixture
from source_bindings import BINDINGS, Incomplete, stage


SCRIPT = Path(__file__).with_name("source_bindings.py")


@unittest.skipUnless(os.environ.get("QUINT_HOME"), "run in nix develop")
class SourceBindingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.repo = self.directory / "repo"
        self.commits = make_fixture(self.repo)
        self.bindings = json.loads(BINDINGS.read_text(encoding="utf-8"))

    def invoke(self, revision, *args, env=None, code=0):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "compare", str(self.repo),
                                 revision, "--json", *args], env=env, capture_output=True,
                                timeout=120, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_comparisons_and_deterministic_committed_snapshot(self):
        self.assertEqual(self.commits, {case: spec["commit"] for case, spec in self.bindings.items()})
        for revision in ("old", "refactor", "changed"):
            with self.subTest(revision=revision):
                result = self.invoke(revision)
                self.assertEqual(result["revisions"], {"old": self.commits["old"], "new": self.commits[revision]})
                self.assertEqual(result["status"], "exhaustive")
                self.assertEqual(result["scope"]["selected_histories"], [["alpha"], ["beta"]])
                self.assertIsNone(result["scope"]["max_original_transitions"])
                self.assertEqual(result["closure"], {side: {"generated": 7, "distinct": 5, "queued": 0, "rounds": 3}
                                                    for side in ("old", "new")})
                for row, label in zip(result["histories"], ("alpha", "beta"), strict=True):
                    changed = revision == "changed" and label == "beta"
                    self.assertEqual(row["public_history"], [label])
                    self.assertEqual((row["removed"], row["added"]), ([3], [4]) if changed else ([], []))
                    for side, observations in row["outcomes"].items():
                        x = 4 if changed and side == "new" else 3
                        self.assertEqual([o["x"] for o in observations], [x])
                        trace = observations[0]["trace"]
                        self.assertEqual([frame["call"] for frame in trace], ["init", "hidden", label])
                        self.assertEqual((trace[0]["x"], trace[2]["x"]), (0, x))
                        self.assertIn(trace[1]["x"], {1, 2})
        for name in ("workflow.qnt", "marks.qnt"):
            (self.repo / name).write_bytes(b"intentionally invalid saved source\n")
        self.assertEqual(result, self.invoke("changed"))
        for name in ("workflow.qnt", "marks.qnt"):
            self.assertEqual((self.repo / name).read_bytes(), b"intentionally invalid saved source\n")

    def test_source_provenance_and_byte_erasure(self):
        for case, spec in self.bindings.items():
            with self.subTest(case=case):
                directory = self.directory / case
                result = stage("quint", self.repo, spec, directory)
                self.assertEqual((directory / "marks.qnt").read_bytes(), (FIXTURES / case / "marks.qnt").read_bytes())
                original = (FIXTURES / case / "workflow.qnt").read_text(encoding="ascii")
                for label, label_title in (("alpha", "intake"), ("beta", "recovery")):
                    site = result["sites"][label]
                    prefix = "// Public " + label_title
                    start = next(n for n, line in enumerate(original.splitlines(), 1) if prefix in line)
                    # Independently read the source near each semantic branch marker.
                    lines = original.splitlines()[start:]
                    callee = "mark" if case == "old" else "record"
                    relative, line = next((i, line) for i, line in enumerate(lines) if f"{callee}(" in line)
                    self.assertEqual((site["line"], site["column"]), (start + 1 + relative, line.index(callee) + 1))
                    self.assertEqual(site["callee"]["file"], "marks.qnt")
                    self.assertEqual(site["callee"]["action"], callee)
                    self.assertEqual(site["call"], f"{callee}({4 if label == 'beta' and case == 'changed' else 3})")

                tagged = (directory / "workflow.qnt").read_text(encoding="ascii")
                # The added wrapper and monitor declarations are erasable without
                # changing comments, whitespace, guards or dependency source.
                erased, declarations = re.subn(
                    r'\n  var reviewCall: str\n  action reviewInit = all \{ init, reviewCall\' = "init" \}\n'
                    r'  def reviewObservation = x\n', '', tagged,
                )
                erased, wrapped = re.subn(r"\ball \{ (?=all \{)", "", erased)
                erased, assigned = re.subn(r', reviewCall\' = "(?:alpha|beta|hidden)" \}', '', erased)
                self.assertEqual((declarations, wrapped, assigned), (1, 4, 4))
                self.assertEqual(erased.encode("ascii"), (FIXTURES / case / "workflow.qnt").read_bytes())

    def test_ambiguous_and_missing_bindings_fail_closed(self):
        result = self.invoke("refactor", "--ambiguous", code=1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["closure"], {})
        self.assertEqual(result["histories"], [])
        self.assertIn("source call site for alpha, found 2", result["error"])
        stale = copy.deepcopy(self.bindings["refactor"])
        stale["calls"]["alpha"] = self.bindings["old"]["calls"]["alpha"]
        with self.assertRaisesRegex(Incomplete, "source call site for alpha, found 0"):
            stage("quint", self.repo, stale, self.directory / "stale")
        stale["calls"]["alpha"] = stale["calls"]["beta"]
        with self.assertRaisesRegex(Incomplete, "ambiguous calls.*beta"):
            stage("quint", self.repo, stale, self.directory / "duplicate")

    def test_missing_tool_evidence_is_not_an_empty_outcome_set(self):
        result = self.invoke("changed", code=1, env={**os.environ, "QUINT_HOME": str(self.directory)})
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["histories"], [])
        self.assertIn("missing TLC jar", result["error"])


if __name__ == "__main__":
    unittest.main()
