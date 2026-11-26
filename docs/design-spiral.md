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

## Release candidate: native validation and redistribution

**Question:** Do both install forms pass on the intended native hosts, and can the tested payloads be made available with all required license and source materials?

Run the matrix on a candidate source branch; the workflow saves only checksums. The owner selected MIT for first-party code and documentation. The native jobs must pass on the commit to be tagged; that alone does not clear the bundled dependency gate.

The exact upstream Apalache 0.62.4 release JAR (`e5223915…`) embeds cvc5, Z3, and zstd-jni native builds, including binaries for platforms the CLI does not target. Neither the IR translator nor the tested TLC path requires them. Both install forms now use a deterministic repack that removes 325 entries, including 39 native binaries; the regression checks every retained entry byte for byte and verifies the output SHA-256 `1d2dab08ca132c1d7cac2ca0cc3c1f743525b18a51aef3c5d97a4d549d30d5cd`. The independent oracle still uses the unmodified backend. Wheel builds now emit Apalache sources and the declared TLA+ Tools source archive as well as the Temurin companions.

### Native validation

[Actions run 45851704558](https://github.com/micha/git-quint-diff/actions/runs/45851704558) passed on `8e14ac3fb2982c0f349bccce9d75c5038a931eed` on Linux x86-64 and macOS arm64. Each of the four installed runs (Nix and pipx on both hosts) passed 22 tests with four development-only skips, using Git 2.56.1. The Linux development run passed 31 tests with one installed-only skip. This checks the candidate on those native runners, not the oldest supported OS versions. The local arm64 Linux builds also passed both installed suites with Git 2.43.0; their backend JAR hashes and source-site fixture JSON matched between install forms.

CI retained only checksum manifests. The four companion file digests matched the build pins on both runners. The tested wheel digests were:

| Wheel platform | SHA-256 |
| --- | --- |
| `manylinux_2_28_x86_64` | `d7b706efaecd86aa861efca7177a3a9d59d88d388ef8b44a983ccc7139f2d10e` |
| `macosx_13_0_arm64` | `270df994aa07eacde65a36296bd2c1860447ffdad07229a71d9359a5f60b0986` |

### TLC provenance investigation

The current `v1.8.0` TLC release asset postdates the Apalache archive and its `tlc2/TLC.class` differs from the embedded class. Two independent builds from `94d0c5070852b37b801bb8998c436383ab7ee37b` matched all 969 production class outputs byte for byte. The six shipped test helper classes and the Tools standard modules were also matched. The checked-out revision is evidence of source provenance, not clearance of the raw archive's vendored binaries.

## Release candidate: verified TLC source companion

**Question:** Can the wheel build emit a source-only companion that recreates the embedded TLC classes without copying the upstream tree's build binaries, and can we identify what else is actually shipped?

From `645178a`, replace only the investigative `v1.8.0` companion. Predict that the deterministic tar from the matched October commit produces the original TLC bytes when built with its pinned tools. Require the Nix and wheel backend to keep SHA-256 `1d2dab08…`.

Both reviewers rebuilt the packaged companion (SHA-256 `01a19bf1e82ffcb768371bcae287ce87bd2cad8fa0cdcad5d9e372c4c3a862ca`) and compared it with the trimmed JAR extracted from a Linux arm64 wheel: **969 production classes, six helper classes, and 20 Tools standard modules** matched byte for byte. The tar is normalized, only includes selected text files, and omits upstream vendored JARs. Its [rebuild recipe](../packaging/TLC-SOURCE.md) supplies only checked build inputs from a separate raw archive. Synthetic controls rejected a changed pin, links or binary content in selected sources, and changed compiled output.

The reviewers traced the merged JAR's renamed `META-INF/LICENSE_tla2tools.md` back to `mailapi-1.6.8.jar` through the exact TLC Ant `dist` recipe and matched the notice bytes. The [TLC project](https://github.com/tlaplus/tlaplus/blob/94d0c5070852b37b801bb8998c436383ab7ee37b/README.md) identifies its own source as MIT. Jakarta Mail's EPL obligations survive the merge; the TLC source companion alone cannot satisfy them.

Independently rechecked the [99 Maven artifact pairs](jvm-backend-maven.tsv): 26,316 class members matched without overlap, plus 975 matched to the Tools rebuild, 21 to the Orbit Activation input, and 2,219 under Apalache namespaces. This found separate notice/source gaps and mixed versions the declared dependency labels alone did not establish. See the [JVM audit](jvm-redistribution-audit.md) and the local [Node, npm and Temurin checks](wheel-payload-audit.md). This inventories the class members, not every retained resource, nested attribution, corresponding source, or host-specific payload.

On Linux arm64 with caller Git 2.43.0, the development run passed 35 tests (one installed-only skip) and each installed Nix/pipx run outside the checkout passed 22 (four development-only skips). The wheel used for installed acceptance had SHA-256 `4aa354e2625f83f1c1b830d69ed35351078330bd88b532faa94c0d0792cd4789`; a subsequent build with a wording-only notice change differed only in that notice and the wheel `RECORD`. Both install forms retained the same backend digest. No new native matrix run or binary publication was performed for this milestone.

### Next milestone: package notices and provide corresponding source

Keep the [publication hold](../packaging/REDISTRIBUTION.md#publication-hold). Restore retained notices in both install forms and deliver the exact EPL/MPL source materials for retained dependencies, starting with Logback, Servlet, Mail, LSP4J and Kiama. Close the resource, shaded-code, source-archive and platform-specific checks on the resulting payloads. Then rerun both native jobs on the exact release commit and match their artifact checksums before seeking publication approval. Do not expand scheduler scope or add working-tree comparisons before the release gate passes.
