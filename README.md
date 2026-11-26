# git-quint-diff

Review what two commits **add or remove from a Quint model's behavior**, not just what changed in the source. Git selects the model snapshots; the review selects the original scheduler calls, public histories, and observation. The CLI compares the **sets** of reachable outcomes and supplies a replayable witness for each addition or removal. It uses neither LLMs nor random simulation.

**Status:** Pre-release. The source-bound runtime supports imported, nested schedulers and pre-state label predicates. It has been checked on the [upstream Quint consensus pair](docs/first-release-acceptance.md#2-imported-consensus-scheduler). The pure-adapter prototype and seven design experiments are archived at `prototype-handoff` (`064f97d`).

## Install

Both packages use **Git 2.43 or newer** from your `PATH`. You do not need to install Node.js, Java, or Quint separately.

- **Nix:** Run `nix profile add .` in this checkout. For a published tag, use `nix profile add github:micha/git-quint-diff/<tag>` instead (replace `<tag>`).
- **pipx:** Run `pipx install --pip-args=--no-index <wheel-url>` with the URL of the matching release wheel, or pass the path to a locally built wheel. The initial wheel targets are Linux x86-64 with glibc 2.28+ and Apple Silicon with macOS 13.5+. Pre-release builds have not been published.

See [packaging and installed acceptance](docs/packaging.md) to build or verify a candidate.

## Try it

With the command installed, run this example from the source checkout (Python 3 is used to create the example repository and review):

```sh
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

The harness runs the executable on disposable Git repositories, including offline reconstructions of the exact upstream consensus commits. It checks consensus outcomes and witnesses against an independently compiled native scheduler. See [the design record](docs/design-spiral.md) for the checks and prototype archive.
