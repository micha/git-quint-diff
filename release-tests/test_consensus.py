"""Black-box acceptance and independent replay for the imported scheduler."""

import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_cli as base
from consensus_fixture import COMMITS, ENTRYPOINT, SCHEDULER, git, materialize
from consensus_oracle import edge_call, native_graph, omissions, shortest, state_values


CONSTANTS = {"N": 3, "F": 1, "ACTUAL_FAULTS": 1, "K": 1, "MAX_ROUNDS": 2}
OBSERVE = "Procs.filter(p => procState.get(p).S.contains(Set())).size()"
FIRST = "receive_round_1"
SECOND = "receive_round_2"
HISTORIES = [[FIRST], [FIRST, SECOND]]
HIDDEN = {"stuttering": (243, 7), "crash": (246, 23), "sendMessages": (247, 22), "computeAction": (249, 24)}
RECEIVE = {"path": SCHEDULER, "line": 248, "column": 30, "callee": "ConsensusAlg::receiveMessages"}
DECLARATION = {"path": SCHEDULER, "module": "ConsensusAlg", "action": "receiveMessages", "line": 181, "column": 10}


def side():
    return {
        "entrypoint": ENTRYPOINT, "module": "KSetAgreementConsensus", "constants": CONSTANTS.copy(),
        "init": "init", "step": "step", "observe": OBSERVE,
        "bindings": {FIRST: RECEIVE | {"when": "round == 1"}, SECOND: RECEIVE | {"when": "round == 2"}},
        "hidden": [{"path": SCHEDULER, "line": line, "column": column} for line, column in HIDDEN.values()],
    }


def review(histories=None):
    return {"scenario": "consensus_two_rounds", "histories": [list(h) for h in (histories or HISTORIES)],
            "old": side(), "new": side()}


class ConsensusTest(unittest.TestCase):
    # Use the same executable and report assertions as for the source-binding slice.
    invoke = base.CliTest.invoke
    machine_report = base.CliTest.machine_report
    assert_rows = base.CliTest.assert_rows
    incomplete = base.CliTest.incomplete

    @classmethod
    def setUpClass(cls):
        cls.env = base.git_env() | {"GIT_NO_LAZY_FETCH": "1"}
        cls.scratch = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        repo = cls.scratch / "upstream"
        materialize(repo, cls.env)
        cls.native = {revision: native_graph(repo, revision, cls.scratch / name, cls.env)
                      for name, revision in COMMITS.items()}

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.tmp / "model"
        materialize(self.repo, self.env)
        self.settings = self.tmp / "review.json"

    def complete(self, old, new, selected):
        report = self.machine_report(self.invoke(old, new, selected), "exhaustive", selected)
        self.assertEqual(report["diagnostics"], [])
        for name, revision in (("old", old), ("new", new)):
            resolved = report[name]
            self.assertEqual(resolved["revision"], revision)
            for field in ("entrypoint", "module", "constants", "init", "step", "observe"):
                self.assertEqual(resolved[field], selected[name][field], (name, field))
            self.assertEqual(resolved["observationType"], "int")
            self.assertEqual(resolved["blobs"], {
                path: git(self.repo, self.env, "rev-parse", f"{revision}:{path}").decode().strip()
                for path in (ENTRYPOINT, SCHEDULER)
            })
            self.assertEqual(resolved["closure"]["queued"], 0)
            self.assert_fields(resolved["scheduler"], DECLARATION | {"action": "step", "line": 241})
            for label, selector in selected[name]["bindings"].items():
                self.assert_fields(resolved["bindings"][label], selector | {"declaration": DECLARATION})
            self.assertEqual(len(resolved["hidden"]), len(HIDDEN))
            for site, selector in zip(resolved["hidden"], selected[name]["hidden"], strict=True):
                self.assert_fields(site, selector)
        for row in report["histories"]:
            self.assertEqual(row["old"]["outcomes"], sorted(shortest(self.native[old], row["history"])))
            self.assertEqual(row["new"]["outcomes"], sorted(shortest(self.native[new], row["history"])))
            for delta in row["deltas"]:
                revision = old if delta["change"] == "-" else new
                self.replay(delta["witness"], revision, selected["scenario"], row["history"], delta["outcome"])
        return report

    def assert_fields(self, value, expected):
        self.assertEqual({key: value[key] for key in expected}, expected)

    def assert_call_site(self, site, call, label):
        if label:
            self.assertEqual(call, "receiveMessages")
            self.assert_fields(site, RECEIVE | {"declaration": DECLARATION, "when": f"round == {label[-1]}"})
        else:
            line, column = HIDDEN[call]
            self.assert_fields(site, {"path": SCHEDULER, "line": line, "column": column})

    def replay(self, witness, revision, scenario, history, outcome):
        self.assert_fields(witness, {"revision": revision, "scenario": scenario, "history": history, "outcome": outcome})
        graph = self.native[revision]
        state = state_values(witness["initial"])
        self.assertIn(state, graph.initial, "witness does not replay through original init")
        observed_history = []
        for index, step in enumerate(witness["steps"], 1):
            self.assertLess(len(observed_history), len(history), "witness goes beyond exact endpoint")
            target = state_values(step["state"])
            self.assertIn(target, graph.outgoing[state], f"witness does not replay through original step at frame {index}")
            call, label = edge_call(state, target)
            self.assertEqual(step["label"], label)
            self.assert_call_site(step["site"], call, label)
            if label is not None:
                observed_history.append(label)
            state = target
        self.assertEqual(observed_history, history)
        self.assertEqual(omissions(state), outcome)
        self.assertEqual(len(witness["steps"]), shortest(graph, history)[outcome])

    def test_consensus_self_then_changed_and_reversed(self):
        old, new = COMMITS["old"], COMMITS["new"]
        # Input order intentionally differs from the required reporting order.
        selected = review(HISTORIES[::-1])
        self.assert_rows(self.complete(old, old, selected), [([FIRST], [0], [0], []), (HISTORIES[1], [0], [0], [])])
        forward = self.complete(old, new, selected)
        self.assert_rows(forward, [([FIRST], [0], [0, 1, 2], [("+", 1), ("+", 2)]), (HISTORIES[1], [0], [0], [])])
        self.assertEqual(self.complete(old, new, selected), forward)
        self.assert_rows(self.complete(new, old, selected), [
            ([FIRST], [0, 1, 2], [0], [("-", 1), ("-", 2)]), (HISTORIES[1], [0], [0], []),
        ])

        malformed = copy.deepcopy(forward["histories"][0]["deltas"][0]["witness"])
        frame = malformed["steps"][1]["state"]
        field, = (k for k in frame if k == "procState" or k.endswith("_procState"))
        frame[field], replacements = re.subn(r"(\bx\s*\|->\s*)[123]\b", r"\g<1>9", frame[field], count=1)
        self.assertEqual(replacements, 1)
        with self.assertRaisesRegex(AssertionError, "original step at frame 2"):
            self.replay(malformed, new, selected["scenario"], [FIRST], 1)

        terminal = self.invoke(old, new, selected, machine=False)
        self.assertEqual(terminal.returncode, 0, terminal.stdout + terminal.stderr)
        for phrase in (old, new, ENTRYPOINT, "KSetAgreementConsensus", "init init, step step", OBSERVE,
                       "ConsensusAlg::step", f"{SCHEDULER}:241:10", "ConsensusAlg::receiveMessages",
                       f"{SCHEDULER}:248:30", f"{SCHEDULER}:181:10", f"{SCHEDULER}:246:23",
                       selected["scenario"], "exhaustive", "explicit hidden steps only", "no native-transition bound",
                       "end of exact history", "0 queued", f"[{FIRST}]", f"[{FIRST} → {SECOND}]",
                       "when round == 1 (pre-state)", "when round == 2 (pre-state)"):
            self.assertIn(phrase, terminal.stdout)
        self.assertRegex(terminal.stdout, r"OLD:\s*\[\s*0\s*\]")
        self.assertRegex(terminal.stdout, r"NEW:\s*\[\s*0,\s*1,\s*2\s*\]")
        self.assertRegex(terminal.stdout, r"NEW:\s*\[\s*0\s*\]")
        for name, value in CONSTANTS.items():
            self.assertRegex(terminal.stdout, rf'"{name}"\s*:\s*{value}\b')
        self.assertEqual(re.findall(r"(?m)^\s*([+−-])\s+(\d+)\b", terminal.stdout), [("+", "1"), ("+", "2")])
        self.assertNotRegex(terminal.stdout, r"(?i)\bFindings\b")

        # Use a different invalid index, then dirty both saved model files.
        (self.repo / SCHEDULER).write_bytes(b"invalid staged scheduler\n")
        git(self.repo, self.env, "add", "--", SCHEDULER)
        for path in (ENTRYPOINT, SCHEDULER):
            (self.repo / path).write_bytes(f"invalid saved source: {path}\n".encode())

        def repository_state():
            return (git(self.repo, self.env, "symbolic-ref", "HEAD"), git(self.repo, self.env, "show-ref"),
                    (self.repo / ".git/index").read_bytes(), [(self.repo / path).read_bytes() for path in (ENTRYPOINT, SCHEDULER)])
        before = repository_state()
        self.assertEqual(self.complete(old, new, selected), forward)
        self.assertEqual(repository_state(), before)

    def test_round_two_cannot_hide_an_out_of_order_or_unclassified_receive(self):
        new = COMMITS["new"]
        selected = review([[SECOND]])
        for classify_first in (True, False):
            with self.subTest(classify_first=classify_first):
                if not classify_first:
                    for name in ("old", "new"):
                        del selected[name]["bindings"][FIRST]
                report = self.complete(new, new, selected)
                self.assert_rows(report, [([SECOND], [], [], [])])
                for name in ("old", "new"):
                    self.assert_fields(report["histories"][0][name], {"reason": "disabled", "label": SECOND})

    def test_no_helper_call_and_no_overlapping_predicates(self):
        old, new = COMMITS["old"], COMMITS["new"]
        for selector, diagnostic in (
            ({"callee": "ConsensusAlg::receiveMessage"}, r"binding:.*receiveMessage.*"),
            (RECEIVE | {"path": ENTRYPOINT, "when": "round == 2"}, r"binding:.*(?:matching|site)"),
            (RECEIVE | {"when": "round == 1"}, r"binding:.*(?:overlap|exclusive|conflict|duplicate)"),
            (RECEIVE | {"when": "round < 3"}, r"binding:.*(?:unsupported|predicate|equality|scalar)"),
        ):
            with self.subTest(selector=selector):
                selected = review()
                selected["new"]["bindings"][SECOND] = selector
                self.incomplete(old, new, selected, "new", diagnostic)

    def test_interrupted_new_candidate_is_not_an_addition(self):
        old, new = COMMITS["old"], COMMITS["new"]
        tools = self.tmp / "bin"
        tools.mkdir()
        shim = tools / "java"
        shutil.copyfile(base.ROOT / "release-tests/fault-java.py", shim)
        shim.chmod(0o700)
        marker = self.tmp / "fault"
        real_java = shutil.which("java", path=self.env["PATH"])
        self.assertIsNotNone(real_java, "run this suite in nix develop")
        env = self.env | {"PATH": str(tools) + os.pathsep + self.env["PATH"], "RELEASE_TEST_REAL_JAVA": real_java,
                          "RELEASE_TEST_FAULT_MARKER": str(marker), "RELEASE_TEST_FAULT_OUTCOME": "1",
                          "RELEASE_TEST_JAVA_FAULT": "interrupt"}
        report = self.incomplete(old, new, review([[FIRST]]), "new", r"exploration: .*did not complete", env=env)
        self.assertEqual(marker.read_text(encoding="utf8"), "interrupt")
        self.assertEqual(report["old"]["closure"]["queued"], 0)
        self.assertNotIn("closure", report["new"])

    def test_compiled_unfiltered_projection_and_label_identity(self):
        expected = {"old": (9, 153, 162), "new": (9, 267, 330)}
        for name, revision in COMMITS.items():
            with self.subTest(side=name):
                graph = self.native[revision]
                self.assertEqual((len(graph.initial), len(graph.outgoing), sum(map(len, graph.outgoing.values()))), expected[name])
                result = subprocess.run(
                    ["node", str(base.ROOT / "release-tests/consensus_projection.cjs"), revision, json.dumps(side())],
                    cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=120,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                augmented = json.loads(result.stdout)
                states = {key: (state_values({k: v for k, v in row.items() if k != "qdSite"}), row["qdSite"])
                          for key, row in augmented["states"].items()}
                self.assertEqual({states[key][0] for key in augmented["initial"]}, graph.initial)
                self.assertEqual({states[key][1] for key in augmented["initial"]}, {"0"})
                self.assertEqual({state for state, _ in states.values()}, graph.outgoing.keys())
                for key, (source, tag) in states.items():
                    outgoing = [states[k] for k in augmented["outgoing"].get(key, [])]
                    self.assertTrue({state for state, _ in outgoing} == graph.outgoing[source],
                                    f"native successors differ at round={source.round}, stage={source.stage}, tag={tag}")
                    for target, target_tag in outgoing:
                        call, label = edge_call(source, target)
                        classified = augmented["sites"][target_tag]
                        self.assertEqual(classified["label"], label)
                        self.assert_call_site(classified["site"], call, label)
