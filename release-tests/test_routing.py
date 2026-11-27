"""Route-position controls with an imported scheduler and a shared leaf."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_cli as base


ENTRY = "workflow.qnt"
OPERATIONS = "ops.qnt"
ROUTER = "Ops::sourceStep"
BODY = """module Ops {
  var x: int
  action init = x' = 0
  action tick = x' = if (x == 2) 0 else x + 1
  action sourceStep = tick
}
"""
HEAD = """module Workflow {
  import Ops.* from "./ops"
  action step = if (x == 0) sourceStep else sourceStep
}
"""


def position(path, line, column):
    return {"path": path, "line": line, "column": column}


class RoutingTest(unittest.TestCase):
    invoke = base.CliTest.invoke
    installed_invocation = base.CliTest.installed_invocation
    machine_report = base.CliTest.machine_report
    assert_rows = base.CliTest.assert_rows
    incomplete = base.CliTest.incomplete

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.tmp / "model"
        self.repo.mkdir()
        self.settings = self.tmp / "review.json"
        self.env = base.git_env() | {"GIT_NO_LAZY_FETCH": "1", "GIT_AUTHOR_DATE": "2025-01-01T00:00:00Z",
                                     "GIT_COMMITTER_DATE": "2025-01-01T00:00:00Z"}
        self.git("init", "--quiet", "--initial-branch=fixture", "--object-format=sha1")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, env=self.env, text=True).strip()

    def commit(self, entry=HEAD, body=BODY):
        (self.repo / ENTRY).write_text(entry, encoding="utf8")
        (self.repo / OPERATIONS).write_text(body, encoding="utf8")
        self.git("add", "--", ENTRY, OPERATIONS)
        self.git("commit", "--quiet", "-m", "Test named scheduler routing")
        return self.git("rev-parse", "HEAD")

    def discover(self, revision, route):
        command, env = self.installed_invocation() if base.INSTALLED else ([str(base.CLI)], self.env | {
            "QUINT_HOME": str(self.tmp / "missing-tlc"), "QUINT_DIFF_JAVA": str(self.tmp / "missing-java"),
        })
        result = subprocess.run([*command, "--discover", "--json", "--entrypoint", ENTRY, "--module", "Workflow",
                                 "--step", "step", "--route", route, revision], cwd=self.repo, env=env,
                                capture_output=True, text=True, timeout=30)
        return result.returncode, json.loads(result.stdout)

    def test_route_positions_distinguish_a_shared_call_and_hidden_leaf(self):
        revision = self.commit()
        code, discovery = self.discover(revision, ROUTER)
        self.assertEqual(code, 0, discovery)
        self.assertEqual(discovery["status"], "complete")
        self.assertEqual(discovery["blobs"], {path: self.git("rev-parse", f"{revision}:{path}")
                                              for path in (ENTRY, OPERATIONS)})
        leaves = discovery["leaves"]
        shared = position(OPERATIONS, 5, 23)
        route_decl = position(OPERATIONS, 5, 10) | {"module": "Ops", "action": "sourceStep"}
        self.assertEqual([leaf["leaf"] for leaf in leaves], [shared | {"via": [position(ENTRY, 3, column)]}
                                                             for column in (29, 45)])
        self.assertEqual([leaf["call"]["selector"] for leaf in leaves],
                         [leaf["leaf"] | {"callee": "Ops::tick"} for leaf in leaves])
        for leaf in leaves:
            self.assertEqual(leaf["via"], [leaf["leaf"]["via"][0] | {"callee": ROUTER, "declaration": route_decl}])

        def side(public, hidden):
            return {"entrypoint": ENTRY, "module": "Workflow", "init": "init", "step": "step",
                    "observe": "x", "routing": [ROUTER], "bindings": {"tick": public["call"]["selector"]},
                    "hidden": [hidden["leaf"]]}

        # Two explicit scopes of the same snapshot. In OLD the first arm is
        # hidden and the second becomes public at x=1. NEW observes the first arm.
        config = {"scenario": "distinguish_routes", "histories": [["tick"]],
                  "old": side(leaves[1], leaves[0]), "new": side(leaves[0], leaves[1])}
        report = self.machine_report(self.invoke(revision, revision, config), "exhaustive", config)
        self.assert_rows(report, [(["tick"], [2], [1], [("-", 2), ("+", 1)])])
        removed, added = (delta["witness"] for delta in report["histories"][0]["deltas"])
        for witness in (removed, added):
            self.assertEqual(list(witness["initial"].values()), ["0"])
        self.assertEqual([(step["label"], list(step["state"].values()), step["site"]["via"]) for step in removed["steps"]],
                         [(None, ["1"], leaves[0]["via"]), ("tick", ["2"], leaves[1]["via"])])
        self.assertEqual([(step["label"], list(step["state"].values()), step["site"]["via"]) for step in added["steps"]],
                         [("tick", ["1"], leaves[0]["via"])])

        for target, diagnostic in (("binding", r"binding:.*ambiguous.*tick"), ("hidden", r"binding:.*hidden.*ambiguous")):
            with self.subTest(selector=target):
                ambiguous = copy.deepcopy(config)
                selector = ambiguous["new"]["bindings"]["tick"] if target == "binding" else ambiguous["new"]["hidden"][0]
                del selector["via"]
                self.incomplete(revision, revision, ambiguous, "new", diagnostic)

    def test_routes_preserve_match_arms_and_instantiated_constants(self):
        revision = self.commit('''module Workflow {
  import Ops.* from "./ops"
  export Ops.*
  type Phase = Ready | Idle
  var phase: Phase
  action init = all { x' = 0, phase' = Ready }
  action step = match phase {
    | Ready => ready
    | Idle => all { x' = x, phase' = Ready }
  }
  action ready = if (x == 0) route else all { x' = 0, phase' = Idle }
  action route = all { tick, phase' = Idle }
}
''', '''module Ops {
  const limit: int
  var x: int
  action tick = x' = limit
}
''')
        routing = ["Workflow::ready", "Workflow::route"]
        old = {"entrypoint": ENTRY, "module": "Workflow", "init": "init", "step": "step", "observe": "x",
               "constants": {"limit": 41}, "routing": routing,
               "bindings": {"tick": {"callee": "Ops::tick"}}, "hidden": []}
        config = {"scenario": "routed_instance", "histories": [["tick"], ["tick", "tick"]], "old": old,
                  "new": old | {"constants": {"limit": 42}, "routing": routing[::-1]}}
        report = self.machine_report(self.invoke(revision, revision, config), "exhaustive", config)
        self.assert_rows(report, [(["tick"], [41], [42], [("-", 41), ("+", 42)]), (["tick", "tick"], [], [], [])])
        for delta in report["histories"][0]["deltas"]:
            step, = delta["witness"]["steps"]
            self.assertEqual([hop["callee"] for hop in step["site"]["via"]], routing)
            self.assertEqual(step["site"]["declaration"]["path"], OPERATIONS)

    def test_configured_router_must_be_a_bare_nullary_action_leaf(self):
        for body, scheduler, route, diagnostic in (
            (BODY, "if (x == 0) sourceStep else all { x != 0, sourceStep }", ROUTER, "entire action-position leaf"),
            (BODY.replace("action sourceStep = tick", "action setTo(n: int): bool = x' = n"), "setTo(1)",
             "Ops::setTo", "bare nullary routing action"),
            (BODY, "tick", ROUTER, "no eligible scheduler routing call"),
        ):
            with self.subTest(scheduler=scheduler):
                revision = self.commit(HEAD.replace("if (x == 0) sourceStep else sourceStep", scheduler), body)
                code, report = self.discover(revision, route)
                self.assertEqual(code, 1, report)
                self.assertEqual(report["status"], "incomplete")
                self.assertEqual(report["leaves"], [])
                self.assertEqual(report["diagnostics"][0]["phase"], "binding")
                self.assertIn(diagnostic, report["diagnostics"][0]["message"])
