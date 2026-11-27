# git-quint-diff

Review what two commits **add or remove from a Quint model's behavior**, not just what changed in the source. Git selects the model snapshots; the review selects the original scheduler calls, public histories, and observation. The CLI compares the **sets** of reachable outcomes and supplies a replayable witness for each addition or removal. It uses neither LLMs nor random simulation.

**Status:** Pre-release. The source-bound runtime supports imported, nested schedulers and labels selected by pre-state predicates or exact call arguments, including local choices. It has been checked on the [upstream Quint consensus pair](docs/first-release-acceptance.md#2-imported-consensus-scheduler) and a [finite DML-derived fixture](docs/first-release-acceptance.md#3-dml-derived-argument-selection-and-historical-parser-failure). The pure-adapter prototype and seven design experiments are archived at `prototype-handoff` (`064f97d`).

## Try it

From a candidate checkout or unpacked source archive, with Nix flakes enabled:

```sh
nix run .#demo
```

This runs the packaged command on a temporary fixture made from two real upstream Quint commits. No permanent install, model checkout, or model fetch is needed. Nix may download build inputs on first use. Look for `+ 1` and `+ 2` after the first receive and no change after two receives. These are counts of process slots with a no-delivery marker, not consensus decisions.

## Install

To keep the command, run `nix profile add .` (Nix 2.30+) from the candidate source. For a local wheel instead, see [packaging](docs/packaging.md); public wheels are on hold. Both installed packages use **Git 2.43 or newer** from your `PATH`; neither needs a separate Node.js, Java, or Quint install.

The [full walkthrough](docs/source-trial.md) covers the [review file](docs/consensus-review.json) and independent witness replay if you want to check how the demo works. To write your own review, [discover call sites](docs/source-review.md#discover-selectors) in each commit before choosing public labels and hidden steps.

The tool reads only committed Git objects, including transitive imports. It reports exhaustive closure **only for the selected histories**; neither a failed binding nor an unfinished search is an empty outcome set. See [review syntax and current limits](docs/source-review.md), the [scheduler contract](docs/supported-scheduler.md), and the [acceptance plan](docs/first-release-acceptance.md).

## Develop

```sh
nix develop --command python3 -B -m unittest discover -s release-tests -v
```

The full harness needs a Git checkout containing the archived `prototype-handoff` commit. It runs the executable on disposable Git repositories, including offline reconstructions of the exact upstream consensus commits. It checks consensus outcomes and witnesses against an independently compiled native scheduler. See [the design record](docs/design-spiral.md) for the checks and prototype archive.

## License

The project's own code and documentation are under the [MIT License](LICENSE). Vendored fixtures and runtime dependencies retain their own terms; see the [consensus fixture license](release-tests/fixtures/consensus/LICENSE) and [candidate redistribution notes](packaging/REDISTRIBUTION.md).
