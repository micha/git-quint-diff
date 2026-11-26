"""Verify source tags against the native scheduler and deliberately corrupt them."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from make_fixture import make_fixture
from native_oracle import check_revision


@unittest.skipUnless(os.environ.get("QUINT_HOME"), "run with pinned Quint/TLC in nix develop")
class NativeOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = tempfile.TemporaryDirectory(prefix="quint-source-binding-test-")
        cls.addClassCleanup(scratch.cleanup)
        cls.root = Path(scratch.name)
        cls.repo = cls.root / "repo"
        cls.revisions = make_fixture(cls.repo)
        # Both staging and the original oracle must ignore saved working-tree source.
        for name in ("workflow.qnt", "marks.qnt"):
            (cls.repo / name).write_text("not valid Quint\n", encoding="utf-8")
        cls.stages = {}
        for case in cls.revisions:
            directory = cls.root / case
            subprocess.run([
                sys.executable, "-B", str(Path(__file__).with_name("source_bindings.py")),
                "stage", str(cls.repo), case, str(directory),
            ], check=True, stdout=subprocess.DEVNULL, timeout=120)
            cls.stages[case] = directory

    def test_entire_original_scheduler_and_all_labeled_branches(self):
        for case, commit in self.revisions.items():
            with self.subTest(case=case):
                result = check_revision(self.repo, commit, case, self.stages[case])
                self.assertEqual(result["revision"], commit)
                original = (9, 5, 8) if case == "changed" else (8, 4, 5)
                for graph, expected in (("native", original), ("tagged", (11, 6, 10))):
                    stats = result[graph]
                    self.assertEqual((stats["generated"], stats["distinct"], stats["edges"]), expected)
                    self.assertEqual((stats["initial"], stats["queued"]), (1, 0))

    def test_projection_rejects_a_choice_lost_only_after_init(self):
        directory = self.root / "suppressed"
        shutil.copytree(self.stages["old"], directory)
        source = directory / "workflow.qnt"
        text = source.read_text(encoding="utf-8")
        old = "nondet v = Set(1, 2).oneOf()"
        self.assertEqual(text.count(old), 1)
        # The 0->2 edge still occurs after a hidden reset; comparing the
        # projected union of edges, or just public outcomes, would miss this.
        source.write_text(text.replace(old, 'nondet v = (if (reviewCall == "init") Set(1) else Set(1, 2)).oneOf()'),
                          encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "tag erasure changed outgoing native transitions"):
            check_revision(self.repo, self.revisions["old"], "old", directory)

    def test_native_relation_alone_cannot_detect_swapped_public_labels(self):
        directory = self.root / "swapped"
        shutil.copytree(self.stages["changed"], directory)
        source = directory / "workflow.qnt"
        text, replacements = re.subn(r'(reviewCall\' = ")(alpha|beta)(")',
                                     lambda m: m[1] + {"alpha": "beta", "beta": "alpha"}[m[2]] + m[3],
                                     source.read_text(encoding="utf-8"))
        self.assertEqual(replacements, 2)
        source.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unexpected call tags or targets"):
            check_revision(self.repo, self.revisions["changed"], "changed", directory)


if __name__ == "__main__":
    unittest.main()
