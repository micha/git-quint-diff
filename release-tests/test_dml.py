"""Black-box and unfiltered projection checks for the finite DML derivative."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_cli as base
from dml_oracle import (
    ENTRYPOINT, MODULE, PUBLISH, SCENARIO, STAGE, declaration, native_graph, replay_witness, resolved_site, routing_hops,
    shortest, site, verify_tagged,
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
ROUTED_COMMITS = {
    "old": "2e2a3ec087c0cf05e8d29129a1330909778e7223",
    "new": "125ee395267dd1c618aeb27487d9a98831de1026",
}
ROUTED_BLOBS = {
    "old": "762100a594848f945368fb3503e8e1815c8b9085",
    "new": "08eec339a37d48f63a75248eb7b9e855cc8d019a",
}
HIDDEN_KINDS = ("startReturn", "clearEvent", "moveMain")


def side(version, factor, *, routed=False):
    return {
        "entrypoint": ENTRYPOINT, "module": MODULE, "init": "init", "step": "step", "observe": "receipt",
        **({"routing": [hop["callee"] for hop in routing_hops(version)]} if routed else {}),
        "bindings": {STAGE: site("stage", version, STAGE, routed=routed),
                     PUBLISH[factor]: site("publish", version, PUBLISH[factor], factor, routed=routed)},
        "hidden": [site(kind, version, routed=routed) for kind in HIDDEN_KINDS],
    }


def review(old, new, factor, *, routed=False):
    return {"scenario": SCENARIO, "histories": [[STAGE, PUBLISH[factor]], [STAGE]],
            "old": side(old, factor, routed=routed), "new": side(new, factor, routed=routed)}


def materialize(repo, env, *, routed=False):
    def git(*args, **kwargs):
        return subprocess.check_output(["git", *args], cwd=repo, env=env | kwargs, text=True).strip()

    repo.mkdir()
    git("init", "--quiet", "--initial-branch=fixture", "--object-format=sha1")
    (repo / ENTRYPOINT).write_bytes((FIXTURE / ENTRYPOINT).read_bytes())
    old_message, new_message = ("Model DML return and factorless publication", "Check the requested publication factor")
    commits, blobs = COMMITS, BLOBS
    if routed:
        git("apply", str(FIXTURE / "route-scheduler.diff"))
        old_message, new_message = ("Route DML return and factorless publication",
                                    "Check the requested publication factor through another router")
        commits, blobs = ROUTED_COMMITS, ROUTED_BLOBS
    for version, minute_second, message in (("old", "00:00", old_message), ("new", "00:01", new_message)):
        if version == "new":
            git("apply", str(FIXTURE / "check-requested-factor.diff"))
            if routed:
                git("apply", str(FIXTURE / "add-ready-router.diff"))
        git("add", "--", ENTRYPOINT)
        date = f"2025-01-01T00:{minute_second}Z"
        git("commit", "--quiet", "-m", message, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        actual = git("rev-parse", "HEAD", f"HEAD:{ENTRYPOINT}").splitlines()
        if actual != [commits[version], blobs[version]]:
            raise AssertionError(f"unexpected DML fixture commit or blob for {version}: {actual}")


class DmlTest(unittest.TestCase):
    invoke = base.CliTest.invoke
    installed_invocation = base.CliTest.installed_invocation
    machine_report = base.CliTest.machine_report
    assert_rows = base.CliTest.assert_rows
    incomplete = base.CliTest.incomplete
    commits, blobs, routed = COMMITS, BLOBS, False

    @classmethod
    def setUpClass(cls):
        cls.env = base.git_env() | {"GIT_NO_LAZY_FETCH": "1"}
        cls.tmp = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.repo = cls.tmp / "fixture"
        materialize(cls.repo, cls.env, routed=cls.routed)
        cls.native = {version: native_graph(cls.repo, revision, cls.tmp / version, cls.env)
                      for version, revision in cls.commits.items()}

    def setUp(self):
        self.settings = self.tmp / "review.json"

    def selected(self, old, new, factor):
        return review(old, new, factor, routed=self.routed)

    def complete(self, old, new, factor, config=None):
        config = config or self.selected(old, new, factor)
        report = self.machine_report(self.invoke(self.commits[old], self.commits[new], config), "exhaustive", config)
        self.assertEqual(report["diagnostics"], [])
        versions = {"old": old, "new": new}
        for name, version in versions.items():
            resolved = report[name]
            self.assertEqual(resolved["revision"], self.commits[version])
            self.assertEqual(resolved["blobs"], {ENTRYPOINT: self.blobs[version]})
            self.assertEqual(resolved["scheduler"], declaration("step"))
            self.assertEqual(resolved["closure"]["queued"], 0)
            self.assertEqual(resolved["hidden"], [resolved_site(kind, version, routed=self.routed) for kind in HIDDEN_KINDS])
            self.assertEqual(resolved["bindings"], {
                STAGE: resolved_site("stage", version, STAGE, routed=self.routed),
                PUBLISH[factor]: resolved_site("publish", version, PUBLISH[factor], factor, routed=self.routed),
            })
        for row in report["histories"]:
            history = row["history"]
            for name, version in versions.items():
                self.assertEqual(row[name]["outcomes"], sorted(shortest(self.native[version], history, version, factor)))
            for delta in row["deltas"]:
                version = old if delta["change"] == "-" else new
                outcome, witness = delta["outcome"], delta["witness"]
                replay_witness(self.native[version], witness, self.commits[version], history, outcome, version, factor,
                               routed=self.routed)
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

        terminal = self.invoke(self.commits["old"], self.commits["new"], self.selected("old", "new", 3), machine=False)
        self.assertEqual(terminal.returncode, 0, terminal.stdout + terminal.stderr)
        for text in ("with args [12,3,false,0]", "with args [12,3,3,false,0]"):
            self.assertIn(text, terminal.stdout)
        self.assertRegex(terminal.stdout, rf"(?m)^[-−] 12 \({self.commits['old']}\)$")
        if self.routed:
            for text in (f"{MODULE}::readyStep", f"{MODULE}::sourceStep", f"{ENTRYPOINT}:62:10", f"{ENTRYPOINT}:77:22"):
                self.assertIn(text, terminal.stdout)

        witness = copy.deepcopy(forward["histories"][1]["deltas"][0]["witness"])
        if self.routed:
            wrong_route = copy.deepcopy(witness)
            wrong_route["steps"][-1]["site"]["via"][0]["column"] += 1
            with self.assertRaisesRegex(ValueError, "wrong routing provenance.*publish"):
                replay_witness(self.native["old"], wrong_route, self.commits["old"], mismatch, 12, "old", 3, routed=True)
        witness["steps"][2]["state"]["main"] = "4"  # Reachable, but not via the report reset in this frame.
        with self.assertRaisesRegex(ValueError, "no native edge at frame 3"):
            replay_witness(self.native["old"], witness, self.commits["old"], mismatch, 12, "old", 3, routed=self.routed)

    @base.development_only
    def test_projection_preserves_each_tracked_states_successors_and_labels(self):
        for version, revision in self.commits.items():
            with self.subTest(side=version):
                result = subprocess.run(
                    ["node", str(base.ROOT / "release-tests/consensus_projection.cjs"), revision,
                     json.dumps(side(version, 3, routed=self.routed))], cwd=self.repo, env=self.env,
                    capture_output=True, text=True, timeout=120,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                tracked = json.loads(result.stdout)
                graph = self.native[version]
                verify_tagged(graph, tracked, version, 3, routed=self.routed)
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
            verify_tagged(graph, missing, version, 3, routed=self.routed)

        mislabeled = copy.deepcopy(tracked)
        public, = (item for item in mislabeled["sites"].values() if item.get("label") == PUBLISH[3])
        public["label"] = STAGE
        self.assertEqual(edges(mislabeled), edges(tracked))
        with self.assertRaisesRegex(ValueError, "wrong label.*publish"):
            verify_tagged(graph, mislabeled, version, 3, routed=self.routed)

        wrong_site = copy.deepcopy(tracked)
        public, = (item for item in wrong_site["sites"].values() if item.get("label") == PUBLISH[3])
        public["site"]["line"] -= 1
        self.assertEqual(edges(wrong_site), edges(tracked))
        with self.assertRaisesRegex(ValueError, "wrong source site.*publish"):
            verify_tagged(graph, wrong_site, version, 3, routed=self.routed)

        if self.routed:
            wrong_route = copy.deepcopy(tracked)
            public, = (item for item in wrong_route["sites"].values() if item.get("label") == PUBLISH[3])
            public["site"]["via"][0]["line"] -= 1
            self.assertEqual(edges(wrong_route), edges(tracked))
            with self.assertRaisesRegex(ValueError, "wrong routing provenance.*publish"):
                verify_tagged(graph, wrong_route, version, 3, routed=True)


class RoutedDmlTest(DmlTest):
    commits, blobs, routed = ROUTED_COMMITS, ROUTED_BLOBS, True

    def discover(self, version, routes):
        command, env = self.installed_invocation() if base.INSTALLED else ([str(base.CLI)], self.env | {
            "QUINT_HOME": str(self.tmp / "missing-tlc"), "QUINT_DIFF_JAVA": str(self.tmp / "missing-java"),
        })
        args = ["--discover", "--json", "--entrypoint", ENTRYPOINT, "--module", MODULE, "--step", "step",
                *(part for route in routes for part in ("--route", route)), self.commits[version]]
        result = subprocess.run([*command, *args], cwd=self.repo, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_discover_routed_sites_and_copy_selectors(self):
        selected = self.selected("old", "new", 3)
        for version in self.commits:
            config = selected[version]
            routes = [hop["callee"] for hop in routing_hops(version)]
            discovered = self.discover(version, routes)
            for key, expected in {
                "mode": "discovery", "status": "complete", "revision": self.commits[version],
                "blobs": {ENTRYPOINT: self.blobs[version]}, "scheduler": declaration("step"),
                "routing": routes, "diagnostics": [],
            }.items():
                self.assertEqual(discovered[key], expected, key)
            leaves = discovered["leaves"]
            kinds = ("startReturn", "clearEvent", "stage", "publish", "moveMain")
            self.assertEqual([row["leaf"] for row in leaves], [site(kind, version, routed=True) for kind in kinds])
            for kind, leaf in zip(kinds, leaves, strict=True):
                expected = None if kind in ("startReturn", "clearEvent") else routing_hops(version)
                self.assertEqual(leaf.get("via"), expected, kind)
            for label, kind, leaf in ((STAGE, "stage", leaves[2]), (PUBLISH[3], "publish", leaves[3])):
                call = leaf["call"]
                self.assertEqual(call["declaration"], declaration(kind))
                self.assertEqual(call["selector"], {k: v for k, v in config["bindings"][label].items() if k != "args"})
                config["bindings"][label] = call["selector"] | {"args": config["bindings"][label]["args"]}
            self.assertIsNone(leaves[-1]["call"])
            hidden = [leaves[i]["leaf"] for i in (0, 1, 4)]
            self.assertEqual(hidden, config["hidden"])
            config["hidden"] = hidden
        self.assert_rows(self.complete("old", "new", 3, selected), [
            ([STAGE], [12], [12], []), ([STAGE, PUBLISH[3]], [0, 12], [0], [("-", 12)]),
        ])

    def test_unlisted_routes_remain_opaque_and_stale_hops_fail(self):
        outer, inner = (hop["callee"] for hop in routing_hops("new"))
        for routes, opaque in (([], outer), ([outer], inner)):
            with self.subTest(routes=routes):
                discovered = self.discover("new", routes)
                self.assertEqual([row["call"]["selector"]["callee"] for row in discovered["leaves"]],
                                 [f"{MODULE}::startReturn", f"{MODULE}::clearEvent", opaque])
                config = self.selected("old", "new", 3)
                config["new"]["routing"] = routes
                self.incomplete(self.commits["old"], self.commits["new"], config, "new", r"binding:.*no matching")

        config = self.selected("old", "new", 3)
        # Same outer position, but NEW has one additional required hop.
        config["new"]["bindings"][PUBLISH[3]]["via"].pop()
        self.incomplete(self.commits["old"], self.commits["new"], config, "new", r"binding:.*no matching.*publish")
