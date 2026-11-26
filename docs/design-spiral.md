# Design spiral

Start each iteration with a question. Record the actual inputs, prediction, checks, and limits before expanding what the CLI claims to support.

## Archive

`prototype-handoff` points to `064f97d4258c57a4dd83f8e27c65bb995dc38aa9`. It retains the pure-adapter CLI, verified Quint comparison model, exact fixtures, seven design experiments, and their oracle commands. See the [archived experiment record](https://github.com/micha/git-quint-diff/blob/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/docs/design-spiral.md) or run locally:

```sh
git show prototype-handoff:docs/design-spiral.md
git show prototype-handoff:spec/README.md
```

To run an archived oracle, extract that tag into a scratch directory and use the pinned shell from the current checkout. The current CLI never invokes the archive. The release tests extract only the small source-binding fixture and its deterministic fixture maker from that commit.

## Fresh implementation: committed source-site comparison

**Question:** Can a standalone command pass the source-site and failure controls on committed blobs without the prototype's evaluator or drivers in the runtime path?

Use the three exact commits and independent source selectors in [acceptance §1](first-release-acceptance.md#1-source-binding-identical-effects-moved-sites-literal-changes). Select `[alpha]` and `[beta]`, from `init` at `x = 0`, allowing only preparation and reset as hidden steps; observe `x` immediately after the public call. Expect no delta on self-comparison or refactor. In `old → changed`, expect `beta` to change from `{3}` to `{4}` and `alpha` to remain `{3}`.

That is what the new executable reports. With those two histories, TLC closed each side at 9 generated, 7 distinct, 0 queued in the **history product** (including observation capture states). The witness on each side replayed `x = 0 → 1 → 3 or 4`, with the recovery site independently checked. The unchanged refactor outcomes alone would not detect a swap of the equal-effect calls; positions and resolved declarations were also checked independently.

### Design and verification

- The Git loader reads exact regular blobs and resolves imports in memory within each commit. No checkout or synthetic tree fallback. The test with an unchanged entrypoint and forwarding import got `{3}` → `{4}` on both labels even with an unrelated HEAD, invalid saved/staged sources, and a replacement ref.
- Quint resolves call occurrences on the original parsed model. After flattening, the backend gives whole alternatives separate definitions from their typed IR, with no modification to the committed scheduler or duplication of its guards in the tool. The public observation and history-prefix tracker are separate from those definitions. Apalache's converter runs offline; TLC explores the finite product of original states, history progress, and last source site. Capture edges read the observation only at exact endpoints and are never included in a native witness.
- A separate regression checks the whole unfiltered transition relation from every reachable tagged state against the original scheduler and hand-checked native fixture graphs. It rejects a tag-dependent edge loss that preserves the projected edge union. An independent site-identity check rejects an equal-effect swap that would preserve even the tagged edge union.
- Reachable evaluation errors, stale/ambiguous/conflicting selectors, unsupported local arguments, invalid blobs, and unavailable backend all failed closed. A fault after NEW had a candidate still produced no delta when closure acknowledgement or a required witness edge was lost. Empty histories, longer histories with hidden progress, denial, disabled calls, and deliberate absence were tested separately.

Reproduce with `nix develop --command python3 -B -m unittest discover -s release-tests -v` (17 tests passed). These checks covered the top-level scheduler slice only.

## Fresh implementation: imported consensus scheduler

**Question:** Can the same source-bound runtime preserve an imported, nested scheduler and its nondeterminism without model-specific recognition?

[Acceptance §2](first-release-acceptance.md#2-imported-consensus-scheduler) pairs upstream `883cc2c579bd11954129d207899790e80fb8c91e` and `35df73a703259890303659e421f79016897993b3`, at `N=3`, `F=1`, `ACTUAL_FAULTS=1`, `K=1`, `MAX_ROUNDS=2`. Count the process slots whose `S` contains the empty set, immediately after each selected history. Predict round one `{0}` → `{0,1,2}` and rounds one–two `{0}` → `{0}`.

OLD self-comparison ran first and returned `{0}` for both histories on both sides. OLD → NEW matched both predictions, with only `+ 1` and `+ 2` for `[receive_round_1]`. Reversing the comparison removed exactly those values. The two-history product closed at OLD 171 generated / 171 distinct and NEW 381 generated / 339 distinct, each with zero queued. Selecting only `[receive_round_2]` found no execution, even when the round-one call was left unclassified: the tool did not silently hide it. Invalid saved source files and a dirty index left the committed comparison unchanged.

- Bind calls on the original parsed scheduler, resolving the selected module instance. Check source paths and branching routes again after flattening. Reuse the typed conditions, scrutinee and chosen leaf, without changing the native scheduler. Compile pre-state equalities separately from the native branches; they classify one site's executions rather than replace its guards. A small generic regression changes the predicate variable during the bound step, so using the post-state instead would fail.
- Independently compile the original scheduler via the Quint CLI and check its TLC graph. OLD closed at 9 initial / 153 distinct / 162 unique edges; NEW at 9 / 267 / 330. Unfiltered classified graphs closed at 9 / 171 / 180 and 9 / 297 / 360 respectively. For every reachable classified state, erasing the tag preserved its outgoing native successors. Check tag and source identity separately against original stage and round routing.
- Replay all reported witnesses in the original graph using all seven original variables. Both added outcomes have three-step witnesses. The oracle found seven native steps to the two-round endpoints, which have no deltas. Mutating a later proposal to `9` made replay fail. Selecting the uncalled helper or conflicting predicates, or losing NEW's closure after finding a candidate, returned `incomplete` without deltas.
- The exact historical [DML pair](first-release-acceptance.md#3-dml-deliberately-out-of-scope) is still `incomplete`: Quint 0.33.1 rejects OLD at `observation` (`QNT000`). That proves only parser failure. The independently typechecked derivative still rejects the locally chosen public argument during binding.

Reproduce with `nix develop --command python3 -B -m unittest discover -s release-tests -v` (24 tests passed). The [consensus fixture](../release-tests/fixtures/consensus/README.md) reconstructs the exact upstream commit IDs and required objects offline. These results cover the selected scenario and finite histories, not general Quint support.

## First release candidate: packaging

**Question:** Can someone install the command and reproduce the same scoped reports without giving the installed process access to this checkout, the prototype, or system Node.js and Java?

The [packaging gate](packaging.md) runs the same black-box checks through `git quint-diff` from a disposable model repository for both install paths. Nix supplies a default package with pinned store dependencies. A platform wheel supplies the same JS and Java sources and a checksummed runtime payload. The test harness keeps the development shell separate for independent oracles. No scheduler scope was added.

The archived source-site fixture still has only `− 3` and `+ 4` for `[beta]`; the exact upstream consensus pair above still has only `+ 1` and `+ 2` for `[receive_round_1]`, with producing traces replayed against the original native scheduler. The exact historical DML pair still fails closed at OLD's parser (`QNT000`), and the separate typechecked derivative rejects locally chosen public arguments. A partial-clone control also rejects a relevant missing blob even when an accessible promisor could supply it. Fetch required model objects explicitly before reviewing.

On Linux arm64 with system Git 2.43.0, both `nix profile add .` and an offline `pipx` install of the local arm64 test wheel were checked. In a network namespace without external connectivity and with the source checkout masked, the two installations emitted byte-identical JSON for `old → changed`. An initial wheel could launch Node and compile but not explore: the slim Java image lacked TLC's RMI and naming classes. The final wheel uses the pinned JAR's `jdeps` module set, excluding GUI support and adding source-file compilation and JAR filesystem modules. Both installed suites passed 22 tests, with the four development-only checks skipped in each. The development suite passed 26 tests and skipped the installed-only check. The tested local wheel's SHA-256 was `939ac5e9abd5d45f2a1a0fb9c21601be5c0d86c3b30e7d41bb01074467fb3b6e`; it is not a release artifact.

## Next milestone: validate and publish an RC

Run both native matrix jobs on the release commit (Linux x86-64 and macOS arm64), and resolve the first-party licensing and bundled dependency redistribution checks before tagging or offering binaries for download. The workflow saves checksums only until that gate is cleared. Do not expand the scheduler subset or add working-tree comparisons before this gate passes.
