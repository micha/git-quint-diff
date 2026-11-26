#!/usr/bin/env python3
"""Reproduce the pure adapter blocker without modifying the DML checkout."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
MODEL = "tests/recorded_return_design.qnt"
OLD = "819ac9d9c496bf652ea85af12b3369844df2b1e4"
NEW = "c540078318bf52313a33d856c7825d6b09566b17"
ACTIONS = ["publish_alternate_expected_3", "stage_alternate"]

# Effect probe, not an adapter: the state/observation stubs are deliberately
# inert. Only the three calls into the original stateful actions are at issue.
WRAPPER = """module review {{
  import recorded_return_design as dml from "./recorded_return_design"
  pure val publicActions: Set[str] = Set("stage_alternate", "publish_alternate_expected_3")

  action stageAlternate = dml::stage(dml::alternate)
  action publishAlternate = dml::publish(dml::alternate, dml::previousMain, {factor}false, 0)

  pure def initialStates(scenario: str): Set[bool] =
    if (dml::init) Set(false) else Set()
  pure def afterStage(state: bool): Set[bool] =
    if (stageAlternate) Set(state) else Set()
  pure def afterPublish(state: bool): Set[bool] =
    if (publishAlternate) Set(state) else Set()
  pure def successors(state: bool, label: str): Set[bool] =
    if (label == "stage_alternate") afterStage(state)
    else if (label == "publish_alternate_expected_3") afterPublish(state)
    else Set()

  pure def observe(state: bool): str = "not evaluated"
}}
"""

ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
ENV.update(
    PATH=f"{ROOT}{os.pathsep}{ENV.get('PATH', os.defpath)}",
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_CONFIG_NOSYSTEM="1",
)


def git(repo, *args, expect=0):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], env=ENV, capture_output=True, timeout=60,
    )
    if proc.returncode != expect:
        raise RuntimeError(f"git {args}: exit {proc.returncode}, expected {expect}\n"
                           f"{proc.stdout.decode()}\n{proc.stderr.decode()}")
    return proc.stdout


def probe(repo, entrypoint, first, second, diagnostics):
    scope = ["--model", entrypoint, "--scenario", "initial_source", "--max-depth", "2"]
    for label in ACTIONS:
        scope += ["--action", label]
    args = ["quint-diff", *scope, first, second]
    result = json.loads(git(repo, *args, "--json", expect=1))
    expected = dict(model=entrypoint, scenario="initial_source", actions=ACTIONS,
                    max_depth=2, old_revision=first, new_revision=second,
                    status="incomplete", histories=[])
    assert {key: result[key] for key in expected} == expected, result
    for pattern in diagnostics:
        assert re.search(pattern, result["error"]), result
    terminal = git(repo, *args, expect=1).decode()
    assert "incomplete (0 histories checked)" in terminal, terminal
    assert "No added or removed outcomes" not in terminal, terminal
    print(terminal, end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dml", type=Path, help="DML checkout containing both original commits")
    dml = parser.parse_args().dml.resolve()
    for first, second in [(OLD, NEW), (NEW, OLD)]:
        # The CLI stops on the first failure. Reverse the order to check each entrypoint.
        probe(dml, MODEL, first, second, [rf"{re.escape(MODEL)}:.*QNT000.*'observation'"])

    with tempfile.TemporaryDirectory(prefix="git-quint-diff-dml-") as directory:
        repo = Path(directory)
        git(repo, "init", "--quiet", "--template=", "--initial-branch=probe")
        git(repo, "config", "user.name", "Adapter Boundary Probe")
        git(repo, "config", "user.email", "probe@example.invalid")
        (repo / "tests").mkdir()
        entrypoint = "tests/review.qnt"
        commits = []
        for original, factor in [(OLD, ""), (NEW, "dml::plannedFactor, ")]:
            # Quint 0.33.1 cannot parse observation declarations. For this
            # separate probe, lower only their qualifiers to ordinary vals;
            # the observations are not used by the wrapper.
            blob = git(dml, "show", f"{original}:{MODEL}")
            shimmed, count = re.subn(rb"^  observation ", b"  val ", blob, flags=re.MULTILINE)
            assert count > 0, original
            (repo / MODEL).write_bytes(shimmed)
            (repo / entrypoint).write_text(WRAPPER.format(factor=factor), encoding="utf-8")
            git(repo, "add", "--", MODEL, entrypoint)
            git(repo, "commit", "--quiet", "-m", f"Effect probe for {original}")
            commit = git(repo, "rev-parse", "HEAD").decode().strip()
            assert git(repo, "show", f"{commit}:{MODEL}") == shimmed
            commits.append(commit)
        print("\nEffect probes (temporary commits, observation qualifiers shimmed):")
        errors = [rf"QNT200.*pure def `{name}`" for name in ("initialStates", "afterStage", "afterPublish")]
        for first, second in (commits, commits[::-1]):
            probe(repo, entrypoint, first, second, errors)


if __name__ == "__main__":
    main()
