#!/usr/bin/env python3
"""Replay the finite comparison examples against the Git subcommand."""

import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
MODEL = "models/review.qnt"
TICKET = "obtain_ticket"
TRAINING = "obtain_training"
REQUEST = "request_review"


def blocked(reason, step):
    return {"reason": reason, "step": step}


class ReplayTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="git-quint-diff-replay-")
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            PATH=f"{ROOT}{os.pathsep}{self.env.get('PATH', os.defpath)}",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
        )
        self.git("init", "--quiet", "--template=", "--initial-branch=replay")
        self.git("config", "user.name", "Replay Test")
        self.git("config", "user.email", "replay@example.invalid")

    def git(self, *args, expect=0):
        process = subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        )
        self.assertEqual(
            process.returncode, expect,
            f"git {' '.join(args)}\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}",
        )
        return process.stdout

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD").strip()

    def run_diff(self, old, new, scenario, actions, depth, *, as_json=True, expect=0):
        args = ["quint-diff", "--model", MODEL, "--scenario", scenario, "--max-depth", str(depth)]
        if as_json:
            args.append("--json")
        for action in actions:
            args.extend(["--action", action])
        stdout = self.git(*args, old, new, expect=expect)
        if not as_json:
            return stdout
        try:
            report = json.loads(stdout)
        except json.JSONDecodeError as error:
            self.fail(f"Invalid JSON: {error}\n{stdout}")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["old_revision"], old)
        self.assertEqual(report["new_revision"], new)
        self.assertEqual(report["model"], MODEL)
        self.assertEqual(report["observation"], "review::observe")
        self.assertEqual(report["scenario"], scenario)
        self.assertEqual(report["actions"], sorted(actions))
        self.assertEqual(report["max_depth"], depth)
        return report

    def bounded_histories(self, report):
        self.assertEqual(report["status"], "bounded")
        actual = [tuple(entry["history"]) for entry in report["histories"]]
        expected = [
            history
            for depth in range(report["max_depth"] + 1)
            for history in itertools.product(report["actions"], repeat=depth)
        ]
        self.assertEqual(actual, expected)
        return dict(zip(actual, report["histories"]))

    def check_entry(self, entry, *, old=(), new=(), old_stop=None, new_stop=None,
                    added=(), removed=(), witnesses=()):
        self.assertEqual(entry["old"]["outcomes"], sorted(old))
        self.assertEqual(entry["new"]["outcomes"], sorted(new))
        self.assertEqual(entry["old"]["stop"], old_stop)
        self.assertEqual(entry["new"]["stop"], new_stop)
        self.assertEqual(entry["added"], sorted(added))
        self.assertEqual(entry["removed"], sorted(removed))
        # Compare concrete producing traces against the fixture, not just +/− labels.
        self.assertCountEqual(
            [(w["side"], w["outcome"], w["states"]) for w in entry["witnesses"]],
            witnesses,
        )

    def no_delta(self, entry):
        self.assertEqual(entry["added"], [])
        self.assertEqual(entry["removed"], [])
        self.assertEqual(entry["witnesses"], [])

    def test_approval_from_isolated_transitive_imports(self):
        fixture = FIXTURES / "approval"
        shutil.copytree(fixture / "models", self.repo / "models")
        rule = "shared/rule.qnt"
        self.write(rule, (fixture / "rules/old.qnt").read_text(encoding="utf-8"))
        old = self.commit("Ticket-only approval")
        self.write(rule, (fixture / "rules/new.qnt").read_text(encoding="utf-8"))
        new = self.commit("Approval requires training too")
        self.assertEqual(self.git("diff", "--name-only", old, new).splitlines(), [rule])

        # Neither snapshot may use this third rule, which approves even at depth zero.
        trap = (fixture / "rules/working_tree.qnt").read_text(encoding="utf-8")
        self.write(rule, trap)
        git_status = self.git("status", "--porcelain=v1")
        self.assertEqual(git_status, f" M {rule}\n")

        actions = (TRAINING, TICKET)  # Input order is deliberately not sorted.
        depth_one = self.bounded_histories(self.run_diff(old, new, "new_user", actions, 1))
        report = self.run_diff(old, new, "new_user", actions, 2)
        entries = self.bounded_histories(report)
        self.assertEqual({h: entries[h] for h in depth_one}, depth_one)
        repeat = self.run_diff(old, new, "new_user", actions, 2)
        self.assertEqual(report["histories"], repeat["histories"])
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), new)
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD").strip(), "replay")
        self.assertEqual(self.git("status", "--porcelain=v1"), git_status)
        self.assertEqual((self.repo / rule).read_text(encoding="utf-8"), trap)

        denied, approved = ("denied",), ("approved",)
        start = {"ticket": False, "trained": False}
        ticket = {"ticket": True, "trained": False}
        trained = {"ticket": False, "trained": True}
        finished = {"ticket": True, "trained": True}
        self.check_entry(entries[()], old=denied, new=denied)
        self.check_entry(
            entries[(TICKET,)], old=approved, new=denied, added=denied, removed=approved,
            witnesses=[("new", "denied", [start, ticket]), ("old", "approved", [start, ticket])],
        )
        self.check_entry(
            entries[(TRAINING,)], old_stop=blocked("missing_action", 1), new=denied,
            added=denied, witnesses=[("new", "denied", [start, trained])],
        )
        disabled = blocked("disabled_action", 2)
        self.check_entry(entries[(TICKET, TICKET)], old_stop=disabled, new_stop=disabled)
        self.check_entry(
            entries[(TRAINING, TRAINING)], old_stop=blocked("missing_action", 1), new_stop=disabled,
        )
        for first, second, intermediate, step in ((TICKET, TRAINING, ticket, 2), (TRAINING, TICKET, trained, 1)):
            with self.subTest(history=(first, second)):
                self.check_entry(
                    entries[(first, second)], old_stop=blocked("missing_action", step), new=approved,
                    added=approved, witnesses=[("new", "approved", [start, intermediate, finished])],
                )

        terminal = self.run_diff(old, new, "new_user", actions, 1, as_json=False)
        self.assertNotIn("Findings", terminal)
        self.assertIn("bounded", terminal.lower())
        self.assertRegex(terminal, r'\+\s*"?denied\b')
        self.assertRegex(terminal, r'[−-]\s*"?approved\b')

    def test_nondeterministic_self_comparison_and_removal(self):
        source = (FIXTURES / "nondeterministic/review.qnt").read_text(encoding="utf-8")
        self.write(MODEL, source)
        old = self.commit("Review has two possible outcomes")
        marker = "pure val approvalsPossible = true"
        self.assertEqual(source.count(marker), 1)
        self.write(MODEL, source.replace(marker, "pure val approvalsPossible = false"))
        new = self.commit("Review cannot approve")

        for after, expected_outcomes in ((old, ("approved", "denied")), (new, ("denied",))):
            with self.subTest(self_comparison=after == old):
                entries = self.bounded_histories(self.run_diff(old, after, "pending_review", (REQUEST,), 2))
                self.check_entry(entries[()], old=("pending",), new=("pending",))
                disabled = blocked("disabled_action", 2)
                self.check_entry(entries[(REQUEST, REQUEST)], old_stop=disabled, new_stop=disabled)
                request = entries[(REQUEST,)]
                if after == old:
                    self.check_entry(request, old=("approved", "denied"), new=expected_outcomes)
                    # Negative control: two individually valid picks falsely imply a delta.
                    picked_old = {request["old"]["outcomes"][0]}
                    picked_new = {request["new"]["outcomes"][-1]}
                    self.assertEqual(picked_new - picked_old, {"denied"})
                    self.assertEqual(picked_old - picked_new, {"approved"})
                else:
                    self.check_entry(
                        request, old=("approved", "denied"), new=expected_outcomes,
                        removed=("approved",), witnesses=[("old", "approved", ["pending", "approved"])],
                    )

    def test_both_equally_observed_states_are_retained(self):
        source = (FIXTURES / "branching/review.qnt").read_text(encoding="utf-8")
        self.write(MODEL, source)
        old = self.commit("Either branch can finish via its own label")
        marker = "pure val finishesAvailable = true"
        self.assertEqual(source.count(marker), 1)
        self.write(MODEL, source.replace(marker, "pure val finishesAvailable = false"))
        new = self.commit("Both finish labels are disabled")

        actions = ("branch", "finish_left", "finish_right")
        entries = self.bounded_histories(self.run_diff(old, new, "start", actions, 2))
        self.check_entry(entries[("branch",)], old=("pending",), new=("pending",))
        changed = set()
        for direction in ("left", "right"):
            history = ("branch", f"finish_{direction}")
            changed.add(history)
            outcome = f"{direction}_done"
            self.check_entry(
                entries[history], old=(outcome,), new_stop=blocked("disabled_action", 2),
                removed=(outcome,), witnesses=[("old", outcome, ["initial", f"{direction}_path", outcome])],
            )
        # Collapsing the two paths to one state would lose at least one of the two removals.
        for history, entry in entries.items():
            if history not in changed:
                with self.subTest(history=history):
                    self.no_delta(entry)

    def test_missing_snapshot_import_does_not_fall_back_to_working_tree(self):
        fixture = FIXTURES / "approval"
        shutil.copytree(fixture / "models", self.repo / "models")
        old = self.commit("Transitive rule is missing")
        self.write("shared/rule.qnt", (fixture / "rules/new.qnt").read_text(encoding="utf-8"))
        new = self.commit("Transitive rule is present")

        report = self.run_diff(old, new, "new_user", (TICKET,), 1, expect=1)
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["error"])
        self.assertEqual(report["histories"], [])

    def test_malformed_transitive_import_reports_parse_error_as_json(self):
        fixture = FIXTURES / "approval"
        shutil.copytree(fixture / "models", self.repo / "models")
        rule = "shared/rule.qnt"
        source = (fixture / "rules/new.qnt").read_text(encoding="utf-8")
        self.write(rule, source)
        old = self.commit("Well-formed transitive import")
        self.write(rule, source + "@\n")  # Keep valid declarations despite the lexer error.
        new = self.commit("Malformed transitive import")

        report = self.run_diff(old, new, "new_user", (TICKET,), 1, expect=1)
        self.assertEqual(report["status"], "incomplete")
        self.assertRegex(report["error"], r"shared/rule\.qnt:\d+:\d+:")
        self.assertIn("token recognition error", report["error"])
        self.assertEqual(report["histories"], [])

    def test_observation_failure_is_incomplete_not_an_empty_set(self):
        source = (FIXTURES / "nondeterministic/review.qnt").read_text(encoding="utf-8")
        self.write(MODEL, source)
        old = self.commit("Review observations always evaluate")
        marker = "pure def observe(state: str): str = state"
        self.assertEqual(source.count(marker), 1)
        self.write(MODEL, source.replace(
            marker,
            'pure def observe(state: str): str = if (state == "approved") List("only").nth(1) else state',
        ))
        new = self.commit("A reachable observation fails to evaluate")

        report = self.run_diff(old, new, "pending_review", (REQUEST,), 2, expect=1)
        self.assertEqual(report["status"], "incomplete")
        self.assertRegex(report["error"], r"QNT510|[Oo]ut of bounds")
        self.assertEqual([entry["history"] for entry in report["histories"]], [[]])
        self.check_entry(report["histories"][0], old=("pending",), new=("pending",))


if __name__ == "__main__":
    unittest.main()
