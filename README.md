# git-quint-diff

Review what two commits **add or remove from a Quint model's behavior**, not just what changed in the source. Git selects the model snapshots; the review selects the original scheduler calls, public histories, and observation. The CLI compares the **sets** of reachable outcomes and supplies a replayable witness for each addition or removal. It uses neither LLMs nor random simulation.

**Status:** Pre-release. The source-bound runtime supports imported, nested schedulers and pre-state label predicates. It has been checked on the [upstream Quint consensus pair](docs/first-release-acceptance.md#2-imported-consensus-scheduler). The pure-adapter prototype and seven design experiments are archived at `prototype-handoff` (`064f97d`).

## Install

Both packages use **Git 2.43 or newer** from your `PATH`. You do not need to install Node.js, Java, or Quint separately.

- **Nix:** From a supplied candidate checkout or unpacked source archive, follow the [source-first trial](docs/source-trial.md) to install in a disposable profile. No archived tag is needed.
- **pipx:** A matching wheel can be built and installed locally; see [packaging and installed acceptance](docs/packaging.md). Public wheels are on hold.

## Try it

The [source-first trial](docs/source-trial.md#2-review-two-real-quint-commits) compares two real upstream Quint commits. It shows how to fetch them, use the [ready-made review](docs/consensus-review.json), and replay the producing witnesses independently. The first receive adds outcomes `1` and `2`; the two-receive history has no delta. These values count process slots with a no-delivery marker, not consensus decisions.

The tool reads only committed Git objects, including transitive imports. It reports exhaustive closure **only for the selected histories**; neither a failed binding nor an unfinished search is an empty outcome set. See [review syntax and current limits](docs/source-review.md), the [scheduler contract](docs/supported-scheduler.md), and the [acceptance plan](docs/first-release-acceptance.md).

## Develop

```sh
nix develop --command python3 -B -m unittest discover -s release-tests -v
```

The full harness needs a Git checkout containing the archived `prototype-handoff` commit. It runs the executable on disposable Git repositories, including offline reconstructions of the exact upstream consensus commits. It checks consensus outcomes and witnesses against an independently compiled native scheduler. See [the design record](docs/design-spiral.md) for the checks and prototype archive.

## License

The project's own code and documentation are under the [MIT License](LICENSE). Vendored fixtures and runtime dependencies retain their own terms; see the [consensus fixture license](release-tests/fixtures/consensus/LICENSE) and [candidate redistribution notes](packaging/REDISTRIBUTION.md).
