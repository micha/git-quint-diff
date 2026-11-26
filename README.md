# git-quint-diff

Review what two commits **add or remove from a Quint model's behavior**, not just what changed in the source. Git selects the model snapshots; the review selects the original scheduler calls, public histories, and observation. The CLI compares the **sets** of reachable outcomes and supplies a replayable witness for each addition or removal. It uses neither LLMs nor random simulation.

**Status:** Fresh implementation, first source-bound slice. It supports finite schedulers with direct calls in top-level alternatives. The [imported consensus scheduler](docs/first-release-acceptance.md#2-imported-consensus-scheduler) is the next milestone, not yet supported. The pure-adapter prototype and seven design experiments are archived at `prototype-handoff` (`064f97d`).

## Try it

Run `nix develop` from this checkout to get the pinned Quint, Apalache/TLC, and Java tools. Then, still in this checkout:

```sh
export PATH="$PWD:$PATH"
review="$PWD/docs/source-review.example.json"
scratch=$(mktemp -d)
git archive prototype-handoff experiments/source_binding | tar -x -C "$scratch"
python3 -B "$scratch/experiments/source_binding/make_fixture.py" "$scratch/repo"
python3 -c 'import json, sys; r = json.load(open(sys.argv[1])); r["new"] = r["old"]; print(json.dumps(r))' \
  "$review" > "$scratch/self.json"
cd "$scratch/repo"
git quint-diff --review "$scratch/self.json" old old
git quint-diff --review "$review" old changed
```

The self-comparison has no deltas. Then `old → changed` removes `3` and adds `4` for `[beta]`, with no delta for `[alpha]`. The example uses different mappings because the call sites moved. Add `--json` for a versioned report.

The tool reads only committed Git objects, including transitive imports. It reports exhaustive closure **only for the selected histories**; neither a failed binding nor an unfinished search is an empty outcome set. See [review syntax and current limits](docs/source-review.md), the [scheduler contract](docs/supported-scheduler.md), and the [acceptance plan](docs/first-release-acceptance.md).

## Develop

```sh
nix develop --command python3 -B -m unittest discover -s release-tests -v
```

The harness runs the new executable on disposable Git repositories. It reads fixture input from the archive tag and does not use prototype code as the program under test. See [the design record](docs/design-spiral.md) for the archive and independent checks.
