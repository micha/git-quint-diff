"""Internal regression for the evaluator's shared compiled branch predicates."""

import json
import subprocess

from test_cli import FixtureCase, COMMITS, ROOT


class ProjectionTest(FixtureCase):
    def test_erasure_preserves_each_reachable_states_native_edges(self):
        for name, commit in COMMITS.items():
            with self.subTest(revision=name):
                result = subprocess.run(
                    ["node", str(ROOT / "release-tests/projection.cjs"), name, commit, json.dumps(self.side(name))],
                    cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=180,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
