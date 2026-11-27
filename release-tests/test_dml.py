"""Black-box and unfiltered projection checks for the finite DML derivative."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_cli as base
from dml_oracle import (
    ENTRYPOINT, MODULE, PUBLISH, SCENARIO, STAGE, declaration, native_graph, replay_witness, shortest, site, verify_tagged,
)


FIXTURE = base.ROOT / "release-tests/fixtures/dml"
COMMITS = {
    "old": "d3525cc2f98964fa0a04949fb6736b3da03610f5",
    "new": "fab07489fc91c6b447b6bd7d2b5bbd5541cae5b3",
}
BLOBS = {
    "old": "5760ebf8c5845cf4cde50d41bbb5203200823443",
    "new": "22861dd5426d24552a7ba807ae762113b72f04a2",
}


def side(version, factor):
    return {
        "entrypoint": ENTRYPOINT, "module": MODULE, "init": "init", "step": "step", "observe": "receipt",
        "bindings": {STAGE: site("stage", version, STAGE),
                     PUBLISH[factor]: site("publish", version, PUBLISH[factor], factor)},
        "hidden": [site(kind, version) for kind in ("startReturn", "clearEvent", "moveMain")],
    }


def review(old, new, factor):
    return {"scenario": SCENARIO, "histories": [[STAGE, PUBLISH[factor]], [STAGE]],
            "old": side(old, factor), "new": side(new, factor)}


def materialize(repo, env):
    def git(*args, **kwargs):
        return subprocess.check_output(["git", *args], cwd=repo, env=env | kwargs, text=True).strip()

    repo.mkdir()
    git("init", "--quiet", "--initial-branch=fixture", "--object-format=sha1")
    (repo / ENTRYPOINT).write_bytes((FIXTURE / ENTRYPOINT).read_bytes())
    for version, minute_second, message in (("old", "00:00", "Model DML return and factorless publication"),
                                            ("new", "00:01", "Check the requested publication factor")):
        if version == "new":
            git("apply", str(FIXTURE / "check-requested-factor.diff"))
        git("add", "--", ENTRYPOINT)
        date = f"2025-01-01T00:{minute_second}Z"
        git("commit", "--quiet", "-m", message, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        actual = git("rev-parse", "HEAD", f"HEAD:{ENTRYPOINT}").splitlines()
        if actual != [COMMITS[version], BLOBS[version]]:
            raise AssertionError(f"unexpected DML fixture commit or blob for {version}: {actual}")


class DmlTest(unittest.TestCase):
    invoke = base.CliTest.invoke
    installed_invocation = base.CliTest.installed_invocation
    machine_report = base.CliTest.machine_report
    assert_rows = base.CliTest.assert_rows

    @classmethod
    def setUpClass(cls):
        cls.env = base.git_env() | {"GIT_NO_LAZY_FETCH": "1"}
        cls.tmp = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.repo = cls.tmp / "fixture"
        materialize(cls.repo, cls.env)
        cls.native = {version: native_graph(cls.repo, revision, cls.tmp / version, cls.env)
                      for version, revision in COMMITS.items()}

    def setUp(self):
        self.settings = self.tmp / "review.json"

    def complete(self, old, new, factor):
        config = review(old, new, factor)
        report = self.machine_report(self.invoke(COMMITS[old], COMMITS[new], config), "exhaustive", config)
        self.assertEqual(report["diagnostics"], [])
        versions = {"old": old, "new": new}
        for name, version in versions.items():
            resolved = report[name]
            self.assertEqual(resolved["revision"], COMMITS[version])
            self.assertEqual(resolved["blobs"], {ENTRYPOINT: BLOBS[version]})
            self.assertEqual(resolved["scheduler"], declaration("step"))
            self.assertEqual(resolved["closure"]["queued"], 0)
            self.assertEqual(resolved["hidden"], config[name]["hidden"])
            self.assertEqual(resolved["bindings"], {
                label: selector | {"declaration": declaration("stage" if label == STAGE else "publish")}
                for label, selector in config[name]["bindings"].items()
            })
        for row in report["histories"]:
            history = row["history"]
            for name, version in versions.items():
                self.assertEqual(row[name]["outcomes"], sorted(shortest(self.native[version], history, version, factor)))
            for delta in row["deltas"]:
                version = old if delta["change"] == "-" else new
                outcome, witness = delta["outcome"], delta["witness"]
                replay_witness(self.native[version], witness, COMMITS[version], history, outcome, version, factor)
                self.assertEqual(len(witness["steps"]), shortest(self.native[version], history, version, factor)[outcome])
        return report

    def test_factor_guard_changes_only_the_wrong_factor_review(self):
        stage = ([STAGE], [12], [12], [])
        mismatch = [STAGE, PUBLISH[3]]
        match = [STAGE, PUBLISH[-2]]
        self.assertEqual(shortest(self.native["old"], mismatch, "old", 3), {0: 5, 12: 4})
        self.assertEqual(shortest(self.native["new"], mismatch, "new", 3), {0: 4})
        self.assertEqual(shortest(self.native["new"], match, "new", -2), {0: 5, 12: 4})
        self.assert_rows(self.complete("old", "old", 3), [stage, (mismatch, [0, 12], [0, 12], [])])
        forward = self.complete("old", "new", 3)
        self.assert_rows(forward, [stage, (mismatch, [0, 12], [0], [("-", 12)])])
        self.assert_rows(self.complete("new", "old", 3), [stage, (mismatch, [0], [0, 12], [("+", 12)])])
        self.assert_rows(self.complete("old", "new", -2), [stage, (match, [0, 12], [0, 12], [])])

        terminal = self.invoke(COMMITS["old"], COMMITS["new"], review("old", "new", 3), machine=False)
        self.assertEqual(terminal.returncode, 0, terminal.stdout + terminal.stderr)
        for text in ("with args [12,3,false,0]", "with args [12,3,3,false,0]"):
            self.assertIn(text, terminal.stdout)
        self.assertRegex(terminal.stdout, rf"(?m)^[-−] 12 \({COMMITS['old']}\)$")

        witness = copy.deepcopy(forward["histories"][1]["deltas"][0]["witness"])
        witness["steps"][2]["state"]["main"] = "4"  # Reachable, but not via the report reset in this frame.
        with self.assertRaisesRegex(ValueError, "no native edge at frame 3"):
            replay_witness(self.native["old"], witness, COMMITS["old"], mismatch, 12, "old", 3)

    @base.development_only
    def test_projection_preserves_each_tracked_states_successors_and_labels(self):
        for version, revision in COMMITS.items():
            with self.subTest(side=version):
                result = subprocess.run(
                    ["node", str(base.ROOT / "release-tests/consensus_projection.cjs"), revision,
                     json.dumps(side(version, 3))], cwd=self.repo, env=self.env,
                    capture_output=True, text=True, timeout=120,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                tracked = json.loads(result.stdout)
                graph = self.native[version]
                verify_tagged(graph, tracked, version, 3)
                self.check_mutations(graph, tracked, version)

    def check_mutations(self, graph, tracked, version):
        def projected(key):
            return tuple(sorted((k, v) for k, v in tracked["states"][key].items() if k != "qdSite"))

        def edges(tracked):
            return {(projected(key), projected(target))
                    for key, outgoing in tracked["outgoing"].items() for target in outgoing}

        # Delete a native successor from one of two differently tagged states
        # for the same native state. Global edge union and state sets still pass.
        missing = copy.deepcopy(tracked)
        source, shadow = next((left, right) for left in tracked["outgoing"] for right in tracked["outgoing"]
                              if left != right and projected(left) == projected(right))
        target = tracked["outgoing"][shadow][0]
        missing["outgoing"][source] = [k for k in missing["outgoing"][source] if projected(k) != projected(target)]
        self.assertEqual(edges(missing), edges(tracked))
        with self.assertRaisesRegex(ValueError, "successors differ under erasure"):
            verify_tagged(graph, missing, version, 3)

        mislabeled = copy.deepcopy(tracked)
        public, = (item for item in mislabeled["sites"].values() if item.get("label") == PUBLISH[3])
        public["label"] = STAGE
        self.assertEqual(edges(mislabeled), edges(tracked))
        with self.assertRaisesRegex(ValueError, "wrong label.*publish"):
            verify_tagged(graph, mislabeled, version, 3)

        wrong_site = copy.deepcopy(tracked)
        public, = (item for item in wrong_site["sites"].values() if item.get("label") == PUBLISH[3])
        public["site"]["line"] -= 1
        self.assertEqual(edges(wrong_site), edges(tracked))
        with self.assertRaisesRegex(ValueError, "wrong source site.*publish"):
            verify_tagged(graph, wrong_site, version, 3)
