"""Opt-in compatibility trial; leaves the checkout and installed CLI untouched."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess

from projection import verify

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODEL = "tests/recorded_return_design.qnt"
MODULE = "recorded_return_design"
REVISIONS = {
    "old": ("819ac9d9c496bf652ea85af12b3369844df2b1e4", "a6e72d5def37cad7be90043f1f95acc1fe073519"),
    "new": ("c540078318bf52313a33d856c7825d6b09566b17", "b8d8418be612161232e626fabe548e9e0ebe648a"),
}
SCENARIO = "dml_return"
STAGE = "stage_alternate"
PUBLISH = {3: "publish_alternate_expected_3", -2: "publish_alternate_expected_minus_2"}
ROUTES = [f"{MODULE}::{name}" for name in ("workerStep", "sourceStep")]
VERSION = "0.34.0"
BACKEND = f"Quint {VERSION} / Apalache 0.62.4 / TLC"
JAR_SHA = "e5223915507b65cc5f1638bd037ede60f8a4fc1644aff46355779f9b05df9262"
ENV = {**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_ALLOW_PROTOCOL": ""}


def pos(line, column=5):
    return {"path": MODEL, "line": line, "column": column}


def side(version, factor):
    if version == "old":
        worker, source = pos(176, 25), pos(178, 10)
        worker_hidden, clear, source_hidden = [146, 148, 149], 177, [160, 162, 168]
        stage, publish = 154, 159
    else:
        worker, source = pos(183, 25), pos(185, 10)
        worker_hidden, clear, source_hidden = [152, 154, 155], 184, [167, 169, 175]
        stage, publish = 160, 166
    return {"entrypoint": MODEL, "module": MODULE, "init": "init", "step": "step", "observe": "event.receipt",
            "routing": ROUTES, "bindings": {
                STAGE: pos(stage) | {"callee": f"{MODULE}::stage", "via": [source], "args": [12]},
                PUBLISH[factor]: pos(publish) | {"callee": f"{MODULE}::publish", "via": [source],
                                                 "args": [12, 3, *([factor] if version == "new" else []), False, 0]},
            }, "hidden": [*(pos(line) | {"via": [worker]} for line in worker_hidden), pos(clear, 35),
                          *(pos(line) | {"via": [source]} for line in source_hidden)]}


def dump(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf8")


def run(*args, cwd, env=ENV, output=None, timeout=180):
    # Keep child diagnostics visible, and retain machine reports on failure.
    if output is not None:
        with output.open("wb") as stream:
            subprocess.run(args, cwd=cwd, env=env, stdout=stream, check=True, timeout=timeout)
    else:
        return subprocess.check_output(args, cwd=cwd, env=env, timeout=timeout)


def trial_cli(work):
    dest = work / "cli"
    shutil.copytree(ROOT / "runtime", dest / "runtime")
    executable = Path(shutil.copy2(ROOT / "git-quint-diff", dest))
    for path, old, new in (
        (dest / "runtime/quint-model.cjs", "version !== '0.33.1') throw new Error('expected Quint 0.33.1')",
         f"version !== '{VERSION}') throw new Error('expected Quint {VERSION}')"),
        (executable, "Quint 0.33.1 / Apalache 0.62.4 / TLC", BACKEND),
    ):
        text = path.read_text(encoding="utf8")
        if text.count(old) != 1:
            raise ValueError(f"trial backend pin/display no longer matches: {path}")
        path.write_text(text.replace(old, new), encoding="utf8")
    return executable


def check_witness_sites(witness, old):
    def action(name, line):
        return {"callee": f"{MODULE}::{name}",
                "declaration": pos(line, 10) | {"action": name, "module": MODULE}}

    handoff, clear = old["hidden"][2:4]
    handoff = handoff | {"via": [pos(176, 25) | action("workerStep", 142)]}
    stage, publish = (old["bindings"][label] for label in (STAGE, PUBLISH[3]))
    route = {"via": [pos(178, 10) | action("sourceStep", 152)]}
    expected = [handoff, stage | action("stage", 119) | route, clear, publish | action("publish", 129) | route]
    assert [step["site"] for step in witness["steps"]] == expected, witness


def compare(repo, work, cli, env):
    configs, witnesses = {}, []
    for name, left, right, factor in (("self", "old", "old", 3), ("forward", "old", "new", 3),
                                      ("reverse", "new", "old", 3), ("matching", "old", "new", -2)):
        history = [STAGE, PUBLISH[factor]]
        config = {"scenario": SCENARIO, "histories": [[STAGE], history],
                  "old": side(left, factor), "new": side(right, factor)}
        file = configs[name] = work / f"{name}.review.json"
        dump(file, config)
        output = work / f"{name}.json"
        run(cli, "--json", "--review", file, REVISIONS[left][0], REVISIONS[right][0], cwd=repo, env=env,
            output=output)
        report = json.loads(output.read_text())
        assert report["status"] == "exhaustive" and report["diagnostics"] == [], report
        assert report["scope"]["backend"] == BACKEND, report["scope"]
        for key, version in (("old", left), ("new", right)):
            revision, blob = REVISIONS[version]
            assert report[key]["revision"] == revision and report[key]["blobs"] == {MODEL: blob}, report[key]
            assert report[key]["closure"]["queued"] == 0, report[key]
        stage, publish = report["histories"]
        assert stage["history"] == [STAGE] and publish["history"] == history, report["histories"]
        assert stage["old"]["outcomes"] == stage["new"]["outcomes"] == [12] and stage["deltas"] == [], stage
        expected = tuple([0] if version == "new" and factor == 3 else [0, 12] for version in (left, right))
        actual = publish["old"]["outcomes"], publish["new"]["outcomes"]
        deltas = [(d["change"], d["outcome"]) for d in publish["deltas"]]
        changes = {"forward": [("-", 12)], "reverse": [("+", 12)]}
        assert actual == expected and deltas == changes.get(name, []), publish
        for delta in publish["deltas"]:
            witness = delta["witness"]
            assert (witness["revision"], witness["scenario"], witness["history"], witness["outcome"]) == (
                REVISIONS["old"][0], SCENARIO, history, 12), witness
            assert [step["label"] for step in witness["steps"]] == [None, STAGE, None, PUBLISH[3]], witness
            check_witness_sites(witness, side("old", 3))
            witnesses.append(witness)
        print(f"{name}: {actual[0]} → {actual[1]}, deltas {deltas}", flush=True)
    return configs, witnesses


def native(repo, revision, blob, directory, quint, env):
    directory.mkdir()
    actual = run("git", "rev-parse", "--verify", f"{revision}:{MODEL}", cwd=repo).decode().strip()
    if actual != blob:
        raise ValueError(f"wrong or missing exact blob for {revision}: {actual}")
    entry = directory / f"{MODULE}.qnt"
    run("git", "cat-file", "blob", blob, cwd=repo, output=entry)
    run(quint, "typecheck", entry.name, cwd=directory, env=env)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    run(quint, "compile", entry.name, "--main", MODULE, "--init", "init", "--step", "step", "--target", "tlaplus",
        "--verbosity", "0", "--apalache-version", "0.62.4", "--server-endpoint", f"127.0.0.1:{port}",
        cwd=directory, env=env, output=directory / f"{MODULE}.tla")
    (directory / f"{MODULE}.cfg").write_text("INIT q_init\nNEXT q_step\n", encoding="utf8")


def explore(directory, jar, env):
    run("java", "-Xmx1024m", "-XX:+UseParallelGC", "-Duser.language=en", "-Duser.country=US",
        f"-Djava.io.tmpdir={directory}", "-cp", jar, "tlc2.TLC", "-deadlock", "-workers", "1", "-fp", "0",
        "-seed", "0", "-noGenerateSpecTE", "-dump", "dot", "graph.dot", f"{MODULE}.tla",
        cwd=directory, env=env, output=directory / "tlc.log", timeout=600)


def graphs(repo, work, cli, configs, witnesses, quint, jar, env):
    for version, (revision, blob) in REVISIONS.items():
        plain = work / f"native-{version}"
        native(repo, revision, blob, plain, quint, env)
        explore(plain, jar, env)
        for config in (("forward",) if version == "old" else ("forward", "matching")):
            tagged = work / f"tagged-{version}-{config}"
            run("node", HERE / "tagged.cjs", cli.parent, revision, configs[config], version, tagged, cwd=repo, env=env)
            explore(tagged, jar, env)
            verify(plain, tagged, witnesses if version == "old" else ())


def main():
    if not __debug__:
        raise SystemExit("run the compatibility assertions with unoptimized Python")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("repo", type=Path, help="local DML repository containing both original revisions")
    p.add_argument("npm", type=Path, help="scratch npm installation prefix from the trial lockfile")
    p.add_argument("work", type=Path, help="new directory for the isolated CLI and evidence")
    p.add_argument("--graphs", action="store_true", help="also run native replay and full unfiltered projection")
    args = p.parse_args()
    repo, npm, work = (path.resolve() for path in (args.repo, args.npm, args.work))
    jar = Path(os.environ["QUINT_HOME"]).resolve() / "apalache-dist-0.62.4/apalache/lib/apalache.jar"
    with jar.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != JAR_SHA:
            raise ValueError("trial requires the untrimmed 0.62.4 distribution from nix develop")
    quint = npm / "node_modules/.bin/quint"
    java = shutil.which("java")
    if not java:
        raise ValueError("trial requires Java from nix develop")
    env = ENV | {"QUINT_DIFF_QUINT_PACKAGE": str(npm / "node_modules/@informalsystems/quint"),
                 "QUINT_HOME": str(jar.parents[3]), "QUINT_DIFF_JAVA": java}
    if run(quint, "--version", cwd=ROOT, env=env).decode().strip() != VERSION:
        raise ValueError(f"trial requires Quint {VERSION} installed from its lockfile")
    work.mkdir()
    cli = trial_cli(work)
    configs, witnesses = compare(repo, work, cli, env)
    if args.graphs:
        graphs(repo, work, cli, configs, witnesses, quint, jar, env)


if __name__ == "__main__":
    main()
