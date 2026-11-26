"""Black-box tests for the first source-bound milestone.

The only archived program used here is the Git fixture maker. Outcome sets,
source sites and the fixture's native transitions are checked independently.
"""

import copy
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "git-quint-diff"
ARCHIVE = "064f97d4258c57a4dd83f8e27c65bb995dc38aa9"
FIXTURE = "experiments/source_binding"
COMMITS = {
    "old": "0a5db49fffb644269f455207705dd59f71eb9933",
    "refactor": "75325f79c4a62330c971d8dfab971cbc447f99b3",
    "changed": "d627ef22313d7733711712168d82df02e60163f9",
}
# Call sites are selected independently in each committed source, including
# the two same-argument call sites in the first two revisions.
SITES = {
    "old": {"alpha": (12, 28), "beta": (14, 28)},
    "refactor": {"alpha": (18, 28), "beta": (15, 7)},
    "changed": {"alpha": (18, 28), "beta": (15, 7)},
}


def git_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="Release Test", GIT_COMMITTER_NAME="Release Test",
               GIT_AUTHOR_EMAIL="test@example.invalid", GIT_COMMITTER_EMAIL="test@example.invalid")
    return env


class FixtureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.env = git_env()
        archive = subprocess.check_output(
            ["git", "archive", ARCHIVE, f"{FIXTURE}/make_fixture.py", f"{FIXTURE}/fixtures"],
            cwd=ROOT, env=cls.env,
        )
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    dest = cls.scratch / member.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(tar.extractfile(member).read())
        cls.fixture_repo = cls.scratch / "fixture"
        result = subprocess.check_output(
            ["python3", "-B", str(cls.scratch / FIXTURE / "make_fixture.py"), str(cls.fixture_repo)],
            env=cls.env, text=True,
        )
        commits = dict(line.split() for line in result.splitlines())
        if commits != COMMITS:
            raise AssertionError(f"Unexpected archive fixture commits: {commits!r}")
        for ref, commit in COMMITS.items():
            actual = subprocess.check_output(
                ["git", "rev-parse", f"{ref}^{{commit}}"], cwd=cls.fixture_repo, env=cls.env, text=True,
            ).strip()
            if actual != commit:
                raise AssertionError(f"Unexpected fixture commit for {ref}: {actual}")

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.tmp / "model"
        self.settings = self.tmp / "review.json"
        self.git("clone", "--quiet", str(self.fixture_repo), str(self.repo), cwd=self.tmp)

    def git(self, *args, cwd=None, text=True):
        return subprocess.check_output(["git", *args], cwd=cwd or self.repo, env=self.env, text=text)

    def commit(self, subject):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", subject)
        return self.git("rev-parse", "HEAD").strip()

    def checkout(self, revision):
        self.git("checkout", "--quiet", "--detach", revision)

    def file(self, name, text):
        (self.repo / name).write_text(text, encoding="utf8")

    def replace(self, name, before, after):
        original = (self.repo / name).read_text(encoding="utf8")
        self.assertEqual(original.count(before), 1, (name, before))
        self.file(name, original.replace(before, after))

    def coordinates(self, revision, fragment):
        """Compute coordinates of an unambiguous fragment in derivative source."""
        source = self.git("show", f"{revision}:workflow.qnt")
        self.assertEqual(source.count(fragment), 1, (revision, fragment))
        offset = source.index(fragment)
        return source.count("\n", 0, offset) + 1, offset - source.rfind("\n", 0, offset)

    def side(self, revision, template=None, *, observe="x", bindings=None, hide_prep=True):
        template = template or revision
        callee = "marks::mark" if template == "old" else "marks::record"
        bindings = bindings if bindings is not None else SITES[template]
        prep = self.coordinates(revision, "all {\n      x == 0,")
        reset = self.coordinates(revision, "all { x.in(Set(3, 4)), x' = 0 }")
        return {
            "entrypoint": "workflow.qnt",
            "module": "workflow",
            "init": "init",
            "step": "step" if template == "old" else "dispatch",
            "observe": observe,
            "bindings": {
                label: None if point is None else {"line": point[0], "column": point[1], "callee": callee}
                for label, point in bindings.items()
            },
            "hidden": [{"line": ln, "column": col} for ln, col in ([prep, reset] if hide_prep else [reset])],
        }


class CliTest(FixtureCase):
    def invoke(self, old, new, review, *, machine=True, env=None):
        self.settings.write_text(json.dumps(review), encoding="utf8")
        args = [str(CLI), "--review", str(self.settings)]
        if machine:
            args.append("--json")
        return subprocess.run(
            [*args, old, new], cwd=self.repo, env=env or self.env,
            text=True, capture_output=True, timeout=130,
        )

    def review(self, old, new, *, histories=None, old_side=None, new_side=None):
        return {
            "scenario": "from_zero",
            "histories": [["alpha"], ["beta"]] if histories is None else histories,
            "old": old_side or self.side(old),
            "new": new_side or self.side(new),
        }

    def machine_report(self, result, status, review):
        self.assertEqual(result.returncode, 0 if status == "exhaustive" else 1,
                         f"stdout: {result.stdout}\nstderr: {result.stderr}")
        report = json.loads(result.stdout)
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["status"], status)
        self.assertEqual(report["scenario"], review["scenario"])
        scope = report["scope"]
        self.assertEqual(scope["histories"], sorted(review["histories"], key=lambda h: (len(h), h)))
        self.assertEqual(scope["hidden"], "explicit-only")
        self.assertEqual(scope["observationPoint"], "end-of-exact-history")
        self.assertIsNone(scope["nativeTransitionBound"])
        self.assertGreater(scope["backendTimeoutMs"], 0)
        return report

    def complete(self, old, new, review):
        report = self.machine_report(self.invoke(old, new, review), "exhaustive", review)
        self.assertEqual(report["diagnostics"], [])
        for name, rev in (("old", old), ("new", new)):
            resolved = report[name]
            self.assertEqual(resolved["revision"], COMMITS.get(rev, rev))
            for field in ("entrypoint", "module", "init", "step", "observe"):
                self.assertEqual(resolved[field], review[name][field], (name, field))
        return report

    def incomplete(self, old, new, review, side, error, *, env=None):
        result = self.invoke(old, new, review, env=env)
        report = self.machine_report(result, "incomplete", review)
        messages = "\n".join(
            f"{issue['phase']}: {issue['message']}" for issue in report["diagnostics"] if issue["side"] == side
        )
        self.assertRegex(messages, re.compile(error, re.IGNORECASE))
        for row in report["histories"]:
            self.assertFalse(row.get("deltas"), row)
            for name in ("old", "new"):
                self.assertNotEqual((row.get(name) or {}).get("outcomes"), [], row)
        return report

    def assert_rows(self, report, expected):
        actual = [
            (row["history"], row["old"]["outcomes"], row["new"]["outcomes"],
             [(delta["change"], delta["outcome"]) for delta in row["deltas"]])
            for row in report["histories"]
        ]
        # Compare serialized scalars so `True` does not pass as integer `1`.
        self.assertEqual(json.dumps(actual), json.dumps(expected), actual)

    def assert_site(self, site, selector):
        self.assertEqual(site["path"], "workflow.qnt")
        self.assertEqual((site["line"], site["column"]), (selector["line"], selector["column"]))
        if "callee" in selector:
            self.assertEqual(site["callee"], selector["callee"])
            module, action = selector["callee"].split("::")
            declaration = site["declaration"]
            self.assertEqual({key: declaration[key] for key in ("path", "module", "action", "line", "column")},
                             {"path": "marks.qnt", "module": module, "action": action, "line": 3, "column": 10})

    def assert_bindings(self, report, review):
        for side in ("old", "new"):
            for label, selector in review[side]["bindings"].items():
                if selector is None:
                    self.assertIsNone(report[side]["bindings"][label])
                else:
                    self.assert_site(report[side]["bindings"][label], selector)
            self.assertEqual(len(report[side]["hidden"]), len(review[side]["hidden"]))
            for site, selector in zip(report[side]["hidden"], review[side]["hidden"]):
                self.assert_site(site, selector)

    def replay_fixture_witness(self, witness, *, review, side, revision, history, outcome, observe=lambda x: x):
        """Replay in the hand-checked original graph, independent of the CLI's evaluator."""
        self.assertEqual(witness["revision"], COMMITS.get(revision, revision))
        self.assertEqual(witness["scenario"], review["scenario"])
        self.assertEqual(witness["history"], history)
        self.assertEqual(witness["outcome"], outcome)

        def scalar(state):
            self.assertEqual(list(state), ["x"], state)
            literal = state["x"]
            self.assertRegex(literal, r"^-?\d+$")
            return int(literal)

        state = scalar(witness["initial"])
        self.assertEqual(state, 0)
        observed_history = []
        selected = review[side]
        for step in witness["steps"]:
            self.assertLess(len(observed_history), len(history), witness)
            target = scalar(step["state"])
            label = step["label"]
            if label is None:
                # Original hidden preparation chooses 1 or 2; reset returns to 0.
                if state == 0:
                    self.assertIn(target, (1, 2))
                    self.assert_site(step["site"], selected["hidden"][0])
                else:
                    self.assertIn(state, (3, 4))
                    self.assertEqual(target, 0)
                    self.assert_site(step["site"], selected["hidden"][-1])
            else:
                self.assertEqual(label, history[len(observed_history)])
                self.assertIn(state, (1, 2))
                destination = 4 if revision == "changed" and label == "beta" else 3
                self.assertEqual(target, destination)
                self.assert_site(step["site"], selected["bindings"][label])
                observed_history.append(label)
            state = target
        self.assertEqual(observed_history, history)
        self.assertEqual(observe(state), outcome)

    def test_source_sites_self_refactor_then_change(self):
        for new in ("old", "refactor", "changed"):
            with self.subTest(new=new):
                # Choose both equal-effect sites independently. Do not infer their
                # correspondence from their effect, or from scheduler branch order.
                review = self.review("old", new, histories=[["beta"], ["alpha"]])
                report = self.complete("old", new, review)
                self.assert_bindings(report, review)
                changed = new == "changed"
                self.assert_rows(report, [
                    (["alpha"], [3], [3], []),
                    (["beta"], [3], [4] if changed else [3], [("-", 3), ("+", 4)] if changed else []),
                ])
                for delta in report["histories"][1]["deltas"]:
                    name = "old" if delta["change"] == "-" else "new"
                    self.replay_fixture_witness(delta["witness"], review=review, side=name,
                                                revision="old" if name == "old" else new,
                                                history=["beta"], outcome=delta["outcome"])
                if changed:
                    self.assertEqual(self.complete("old", new, review), report)
                    # Keep the claimed label/outcome but break the hidden preparation.
                    malformed = copy.deepcopy(report["histories"][1]["deltas"][0]["witness"])
                    malformed["steps"][0]["state"] = {key: "0" for key in malformed["initial"]}
                    with self.assertRaises(AssertionError):
                        self.replay_fixture_witness(malformed, review=review, side="old", revision="old",
                                                    history=["beta"], outcome=3)
                    terminal = self.invoke("old", new, review, machine=False)
                    self.assertEqual(terminal.returncode, 0, (terminal.stdout, terminal.stderr))
                    self.assert_terminal(terminal.stdout, review)

    def test_invalid_binding_is_neither_absent_nor_disabled(self):
        good = self.review("old", "refactor")
        for edits, pattern in (
            ({"alpha": {"callee": "marks::record"}}, r"alpha.*(?:2|ambiguous|multiple)"),
            ({"alpha": good["old"]["bindings"]["alpha"] | {"callee": "marks::record"}}, r"alpha.*(?:0|no|missing)"),
            ({"alpha": good["new"]["bindings"]["alpha"] | {"callee": "marks::mark"}}, r"alpha.*(?:0|no|missing)"),
            ({"beta": good["new"]["bindings"]["alpha"]}, r"(?:duplicate|same|conflict|already)"),
        ):
            with self.subTest(edits=edits):
                review = copy.deepcopy(good)
                review["new"]["bindings"].update(edits)
                self.incomplete("old", "refactor", review, "new", pattern)

    def test_only_exact_histories_and_only_explicitly_hidden_progress(self):
        selected = self.review("changed", "changed", histories=[["beta", "alpha"], ["alpha"], []])
        self.assert_rows(self.complete("changed", "changed", selected), [
            ([], [0], [0], []),
            (["alpha"], [3], [3], []),
            (["beta", "alpha"], [3], [3], []),
        ])
        side = self.side("changed", hide_prep=False)
        selected = self.review("changed", "changed", histories=[["alpha"]], old_side=side, new_side=side)
        report = self.complete("changed", "changed", selected)
        self.assert_rows(report, [(["alpha"], [], [], [])])
        for name in ("old", "new"):
            self.assertEqual(report["histories"][0][name]["reason"], "disabled")
            self.assertEqual(report["histories"][0][name]["label"], "alpha")
        # A bound label after an unreachable prefix must not be reported as blocked.
        selected["histories"] = [["alpha", "beta"]]
        report = self.complete("changed", "changed", selected)
        self.assert_rows(report, [(["alpha", "beta"], [], [], [])])
        for name in ("old", "new"):
            self.assertEqual(report["histories"][0][name]["reason"], "disabled")
            self.assertEqual(report["histories"][0][name]["label"], "alpha")

    def test_observe_only_at_endpoints_and_do_not_skip_a_public_step(self):
        self.replace("workflow.qnt", "all { x.in(Set(1, 2)), record(3)", "all { x == 4, record(3)")
        child = self.commit("Require a visible recovery step before intake")
        bindings = {"alpha": self.coordinates(child, "record(3)"), "beta": self.coordinates(child, "record(4)")}
        # Prepared states are native and reachable, but observing either is an error.
        # Reset is also possible after beta; it must not pollute beta's outcome set.
        observe = "if (x == 1 or x == 2) List(0).nth(9) else x"
        side = self.side(child, "changed", observe=observe, bindings=bindings)
        review = self.review(child, child, histories=[["beta", "alpha"], ["beta"], ["alpha"], []],
                             old_side=side, new_side=side)
        self.assert_rows(self.complete(child, child, review), [
            ([], [0], [0], []),
            (["alpha"], [], [], []),
            (["beta"], [4], [4], []),
            (["beta", "alpha"], [3], [3], []),
        ])

    def test_distinct_hidden_states_must_not_merge_by_observation(self):
        self.replace("workflow.qnt", "all { x.in(Set(1, 2)), record(3)", "all { x == 1, record(3)")
        self.replace("workflow.qnt", "x.in(Set(1, 2)),\n      record(4)", "x == 2,\n      record(4)")
        child = self.commit("Distinguish the two prepared states")
        bindings = {"alpha": self.coordinates(child, "record(3)"), "beta": self.coordinates(child, "record(4)")}
        side = self.side(child, "changed", observe="if (x <= 2) 0 else x", bindings=bindings)
        review = self.review(child, child, old_side=side, new_side=side)
        self.assert_rows(self.complete(child, child, review), [(["alpha"], [3], [3], []), (["beta"], [4], [4], [])])

    def test_executed_denial_disabled_and_deliberate_absence(self):
        observe = 'if (x == 3) "denied" else "approved"'
        old = self.side("changed", observe=observe)
        for reason in ("disabled", "absent"):
            with self.subTest(reason=reason):
                self.checkout("changed")
                if reason == "disabled":
                    self.replace("workflow.qnt", "x.in(Set(1, 2)),\n      record(4)", "x == 20,\n      record(4)")
                else:
                    self.replace("workflow.qnt", "    all {\n      x.in(Set(1, 2)),\n      record(4),\n    },\n", "")
                child = self.commit(reason)
                calls = {
                    "alpha": self.coordinates(child, "record(3)"),
                    "beta": self.coordinates(child, "record(4)") if reason == "disabled" else None,
                }
                new = self.side(child, "changed", observe=observe, bindings=calls)
                review = self.review("changed", child, old_side=old, new_side=new)
                report = self.complete("changed", child, review)
                self.assert_bindings(report, review)
                self.assert_rows(report, [
                    (["alpha"], ["denied"], ["denied"], []),
                    (["beta"], ["approved"], [], [("-", "approved")]),
                ])
                beta = report["histories"][1]
                self.assertEqual(beta["new"]["reason"], reason)
                self.assertEqual(beta["new"]["label"], "beta")
                witness = beta["deltas"][0]["witness"]
                self.replay_fixture_witness(witness, review=review, side="old", revision="changed",
                                            history=["beta"], outcome="approved",
                                            observe=lambda x: "denied" if x == 3 else "approved")

    def test_nondeterministic_callee_compares_all_outcomes(self):
        self.replace("marks.qnt", "= x' = destination", "= all {\n    nondet v = Set(destination, destination + 1).oneOf()\n    x' = v,\n  }")
        child = self.commit("Retain the callee's native nondeterministic choice")
        side = self.side(child, "changed")
        for old, old_side, old_sets, deltas in (
            (child, side, ([3, 4], [4, 5]), ([], [])),
            ("changed", self.side("changed"), ([3], [4]), ([("+", 4)], [("+", 5)])),
        ):
            with self.subTest(old=old):
                review = self.review(old, child, old_side=old_side, new_side=side)
                self.assert_rows(self.complete(old, child, review), [
                    (["alpha"], old_sets[0], [3, 4], deltas[0]),
                    (["beta"], old_sets[1], [4, 5], deltas[1]),
                ])

    def test_negative_literal_and_boolean_observation(self):
        self.replace("workflow.qnt", "record(4)", "record(-1)")
        child = self.commit("Accept a negative literal in the recovery call")
        observe = "x < 0"
        review = self.review("changed", child, histories=[["beta"]], old_side=self.side("changed", observe=observe),
                             new_side=self.side(child, "changed", observe=observe))
        self.assert_rows(self.complete("changed", child, review), [
            (["beta"], [False], [True], [("-", False), ("+", True)]),
        ])

    def assert_terminal(self, stdout, review):
        # Check semantic content, not whitespace/column widths or the full layout.
        for expected in ("exhaustive", review["scenario"], "workflow.qnt", "init", "step", "dispatch",
                         "marks::mark", "marks::record", COMMITS["old"], COMMITS["changed"], "[alpha]", "[beta]",
                         "explicit hidden steps only", "no native-transition bound", "end of exact history", "Observe: x",
                         "workflow.qnt:14:28", "workflow.qnt:15:7", "marks.qnt:3:10", "Hidden: workflow.qnt:6:5"):
            self.assertIn(expected, stdout)
        self.assertRegex(stdout, r"(?m)^[ \t]*[-−] +3\b")
        self.assertRegex(stdout, r"(?m)^[ \t]*\+ +4\b")
        self.assertNotRegex(stdout, r"(?i)\bFindings\b")

    def test_transitive_import_ignores_worktree_index_head_and_replacement_refs(self):
        self.checkout("refactor")
        self.replace("workflow.qnt", 'import marks.* from "./marks"', 'import bridge.* from "./bridge"')
        self.file("bridge.qnt", 'module bridge {\n  import marks.* from "./marks"\n  export marks.*\n}\n')
        old = self.commit("Import the action through a forwarding module")
        self.replace("marks.qnt", "x' = destination", "x' = destination + 1")
        new = self.commit("Change only an action in the transitive import")
        for path in ("workflow.qnt", "bridge.qnt"):
            self.assertEqual(self.git("rev-parse", f"{old}:{path}"), self.git("rev-parse", f"{new}:{path}"))
        self.assertNotEqual(self.git("rev-parse", f"{old}:marks.qnt"), self.git("rev-parse", f"{new}:marks.qnt"))
        review = self.review(old, new, old_side=self.side(old, "refactor"), new_side=self.side(new, "refactor"))
        report = self.complete(old, new, review)
        self.assert_bindings(report, review)
        self.assert_rows(report, [([label], [3], [4], [("-", 3), ("+", 4)]) for label in ("alpha", "beta")])
        for name, rev in (("old", old), ("new", new)):
            self.assertEqual(report[name]["blobs"], {
                path: self.git("rev-parse", f"{rev}:{path}").strip() for path in ("workflow.qnt", "bridge.qnt", "marks.qnt")
            })

        # HEAD, the index and all saved model files now differ from both committed snapshots.
        self.checkout("changed")
        self.git("checkout", "--quiet", "-b", "unrelated-head")
        self.file("marks.qnt", "invalid staged marks")
        self.git("add", "--", "marks.qnt")
        paths = ("workflow.qnt", "bridge.qnt", "marks.qnt")
        for path in paths:
            self.file(path, f"invalid saved {path}")

        def repository_state():
            return (
                self.git("symbolic-ref", "HEAD"), self.git("rev-parse", "HEAD"), self.git("show-ref"),
                (self.repo / ".git/index").read_bytes(), [(self.repo / path).read_bytes() for path in paths],
            )

        for replace in (False, True):
            with self.subTest(replace=replace):
                if replace:
                    self.git("replace", old, new)
                before = repository_state()
                self.assertEqual(self.complete(old, new, review), report)
                self.assertEqual(repository_state(), before)

    def test_bad_committed_sources_never_fall_back_to_valid_saved_or_index_source(self):
        healthy = self.side("refactor")
        for path, broken in (("marks.qnt", None), ("workflow.qnt", None), ("marks.qnt", "\n@\n")):
            with self.subTest(path=path, broken=broken):
                self.checkout("refactor")
                good = (self.repo / path).read_text(encoding="utf8")
                if broken is None:
                    (self.repo / path).unlink()
                else:
                    self.file(path, good + broken)
                child = self.commit(f"Commit broken {path}")
                self.file(path, good)
                self.git("add", "--", path)
                review = self.review("refactor", child, new_side=healthy)
                self.incomplete("refactor", child, review, "new", re.escape(path))
                review = self.review(child, "refactor", old_side=healthy)
                self.incomplete(child, "refactor", review, "old", re.escape(path))
                self.git("reset", "--hard", "--quiet")

    def test_unknown_revision_is_incomplete(self):
        missing = "release-test-no-such-ref"
        healthy = self.side("refactor")
        self.incomplete("refactor", missing, self.review("refactor", missing, new_side=healthy), "new", missing)
        self.incomplete(missing, "refactor", self.review(missing, "refactor", old_side=healthy), "old", missing)

    def test_non_snapshot_and_non_regular_imports_are_rejected(self):
        self.checkout("refactor")
        marks = (self.repo / "marks.qnt").read_text(encoding="utf8")
        external = self.tmp / "marks.qnt"
        external.write_text(marks, encoding="utf8")
        for kind in ("absolute", "outside", "symlink", "gitlink"):
            with self.subTest(kind=kind):
                self.checkout("refactor")
                if kind in ("absolute", "outside"):
                    target = str(external.with_suffix("")) if kind == "absolute" else "../marks"
                    self.replace("workflow.qnt", '"./marks"', f'"{target}"')
                    child = self.commit(f"Import via {kind} path")
                elif kind == "symlink":
                    self.file("real-marks.qnt", marks)
                    (self.repo / "marks.qnt").unlink()
                    (self.repo / "marks.qnt").symlink_to("real-marks.qnt")
                    child = self.commit("Supply a symlink instead of regular source")
                else:
                    self.replace("workflow.qnt", '"./marks"', '"./vendor/marks"')
                    self.git("add", "workflow.qnt")
                    self.git("update-index", "--add", "--cacheinfo", f"160000,{COMMITS['refactor']},vendor")
                    self.git("commit", "--quiet", "-m", "Import through a gitlink")
                    child = self.git("rev-parse", "HEAD").strip()
                    self.git("clone", "--quiet", str(self.fixture_repo), "vendor")
                    self.git("checkout", "--quiet", "--detach", "refactor", cwd=self.repo / "vendor")
                diagnostic = "workflow.qnt|marks.qnt|vendor"
                review = self.review("refactor", child, new_side=self.side(child, "refactor"))
                self.incomplete("refactor", child, review, "new", diagnostic)

    def typecheck(self, entrypoint="workflow.qnt"):
        result = subprocess.run(["quint", "typecheck", entrypoint], cwd=self.repo, env=self.env,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shared_site_predicates_classify_before_the_step(self):
        self.file("workflow.qnt", """module workflow {
  const START: int
  var x: int
  action init = x' = START
  action bump = x' = x + 1
  action dispatch = if (x <= 2) {
    any {
      all { x > 0, bump },
      all { x == 1, x' = 3 },
    }
  } else all { x' = x }
}
""")
        rev = self.commit("Classify a nested scheduler site that changes the label variable")
        line, col = self.coordinates(rev, "bump },")
        hidden = [self.coordinates(rev, fragment) for fragment in ("all { x == 1", "all { x' = x }")]
        site = {"line": line, "column": col, "callee": "workflow::bump"}
        side = {"entrypoint": "workflow.qnt", "module": "workflow", "init": "init", "step": "dispatch",
                "constants": {"START": 1}, "observe": "x",
                "bindings": {"first": {**site, "when": "x == 1"}, "second": {**site, "when": "x == 2"}},
                "hidden": [{"line": ln, "column": c} for ln, c in hidden]}
        review = self.review(rev, rev, histories=[["first", "second"], ["first"], ["second"], []],
                             old_side=side, new_side=side)
        self.assert_rows(self.complete(rev, rev, review), [
            ([], [1], [1], []),
            (["first"], [2], [2], []),
            (["second"], [], [], []),
            (["first", "second"], [3], [3], []),
        ])
        # A call from an unmatched pre-state is not a hidden transition.
        unlabeled = side | {"bindings": {"second": side["bindings"]["second"]}}
        review = self.review(rev, rev, histories=[["second"]], old_side=unlabeled, new_side=unlabeled)
        self.assert_rows(self.complete(rev, rev, review), [(["second"], [], [], [])])
        # The site predicate alone is not enough: retain the outer if guard.
        guarded = side | {"constants": {"START": 3}, "bindings": {"third": {**site, "when": "x == 3"}}}
        review = self.review(rev, rev, histories=[["third"]], old_side=guarded, new_side=guarded)
        self.assert_rows(self.complete(rev, rev, review), [(["third"], [], [], [])])
        for when, diagnostic in (("x == 1", "conflicting selector"), ("x > 1", "pre-state scalar variable")):
            conflict = side | {"bindings": side["bindings"] | {"second": {**site, "when": when}}}
            review = self.review(rev, rev, histories=[["first", "second"]], old_side=side, new_side=conflict)
            self.incomplete(rev, rev, review, "new", f"binding:.*{diagnostic}")

    def test_constants_are_exact_or_fail_closed(self):
        self.file("workflow.qnt", """module workflow {
  const INITIAL: str
  var x: str
  action init = x' = INITIAL
  action dispatch = x' = x
}
""")
        rev = self.commit("Initialize from an exact string constant")
        side = {"entrypoint": "workflow.qnt", "module": "workflow", "init": "init", "step": "dispatch",
                "constants": {"INITIAL": "ready"}, "observe": "x", "bindings": {}, "hidden": []}
        changed = side | {"constants": {"INITIAL": "waiting"}}
        review = self.review(rev, rev, histories=[[]], old_side=side, new_side=changed)
        self.assert_rows(self.complete(rev, rev, review), [([], ["ready"], ["waiting"], [('-', 'ready'), ('+', 'waiting')])])
        # Pinned PrettyWriter would encode this as a newline instead of the
        # specified backslash plus n. It must not create spurious deltas.
        unrepresentable = side | {"constants": {"INITIAL": r"ready\n"}}
        review = self.review(rev, rev, histories=[[]], old_side=side, new_side=unrepresentable)
        self.incomplete(rev, rev, review, "new", r"compile:.*string literal cannot be translated losslessly")

    def test_local_nondeterministic_public_call_arguments_fail_closed(self):
        self.replace("workflow.qnt", "record(4),", "nondet destination = Set(3, 4).oneOf()\n      record(destination),")
        self.typecheck()
        child = self.commit("Nondeterministically pick the recovery argument in the scheduler")
        calls = {"alpha": self.coordinates(child, "record(3)"), "beta": self.coordinates(child, "record(destination)")}
        review = self.review("changed", child, new_side=self.side(child, "changed", bindings=calls))
        self.incomplete("changed", child, review, "new", r"binding:.*beta.*unsupported")

    def test_reachable_observation_error_does_not_imply_removal(self):
        selected = [["beta"]]
        self.assert_rows(self.complete("old", "changed", self.review("old", "changed", histories=selected)), [
            (["beta"], [3], [4], [("-", 3), ("+", 4)]),
        ])
        observe = "if (x == 4) List(3).nth(x) else x"
        # Independent typecheck on the native model, without the review evaluator.
        self.replace("workflow.qnt", "  }\n}\n", f"  }}\n  val observed = {observe}\n}}\n")
        self.typecheck()
        old, new = self.side("old", observe=observe), self.side("changed", observe=observe)
        review = self.review("old", "changed", histories=selected, old_side=old, new_side=new)
        self.incomplete("old", "changed", review, "new", r"observation: .*did not complete")
        result = self.invoke("old", "changed", review, machine=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("incomplete", result.stdout)
        self.assertRegex(result.stdout, r"(?is)\bnew\b.*observ")
        self.assertNotRegex(result.stdout, r"(?mi)^\s*[-−+]\s+\d|no (?:behavioral )?changes")

    def test_unavailable_backend_does_not_report_a_completed_comparison(self):
        env = self.env | {"QUINT_HOME": str(self.tmp / "unavailable")}
        self.incomplete("old", "changed", self.review("old", "changed"), None, r"backend", env=env)

    def test_new_candidate_does_not_prove_closure_or_replace_required_evidence(self):
        real_java = shutil.which("java", path=self.env["PATH"])
        self.assertIsNotNone(real_java, "run this suite in nix develop")
        tools = self.tmp / "tools"
        tools.mkdir()
        shim = tools / "java"
        shutil.copyfile(ROOT / "release-tests/fault-java.py", shim)
        shim.chmod(0o700)
        marker = self.tmp / "fault"
        env = self.env | {
            "PATH": str(tools) + os.pathsep + self.env["PATH"],
            "RELEASE_TEST_REAL_JAVA": real_java,
            "RELEASE_TEST_FAULT_MARKER": str(marker),
        }
        review = self.review("old", "changed", histories=[["beta"]])
        for mode, diagnostic in (("interrupt", r"exploration: .*did not complete"),
                                 ("missing-witness-edge", r"evidence: .*state graph")):
            with self.subTest(mode=mode):
                report = self.incomplete("old", "changed", review, "new", diagnostic,
                                         env=env | {"RELEASE_TEST_JAVA_FAULT": mode})
                self.assertEqual(marker.read_text(encoding="utf8"), mode)
                self.assertEqual(report["old"]["closure"]["queued"], 0)
                self.assertNotIn("closure", report["new"])
                marker.unlink()


if __name__ == "__main__":
    unittest.main()
