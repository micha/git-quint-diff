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

## Release candidate: priority JVM redistribution materials

**Question:** Can both install forms deliver the restored notices and let a recipient get the same matching source companion without changing what runs during review?

From `0cbf05c`, restore the notices identified by the class audit. Predict that the wheel and a separate Nix build produce identical source for Logback, Servlet, Mail, LSP4J and Kiama, and that both installs retain backend SHA-256 `1d2dab08ca132c1d7cac2ca0cc3c1f743525b18a51aef3c5d97a4d549d30d5cd`.

- The reviewers independently fetched 28 distinct provenance URLs and matched 63 installed notice files byte for byte, including the original TLC MIT notice, the Orbit wrapper attribution, and Netty's umbrella notices and 30 related files. The Netty notice describes an aggregate distribution, not the exact retained code. LSP4J's release tree and the exact `jsonrpc` artifact disagree on the declared EPL version. Both declarations and license texts are preserved and the exact source is supplied, but the discrepancy remains a publication blocker.
- The source build verifies five pinned upstream trees and nine exact Maven source artifacts. It compares every Java, Scala and Xtend source against the selected tree and preserves the built `Version.java` from Mail and 141 generated LSP4J Java files. An independent check matched the published sources and other non-`META-INF` source-JAR content, except generated `._trace` files, to retained files. The archive excludes prebuilt JARs, unrelated assets and tests.
- Builds from the unpacked companion reproduced all 658 retained Logback classes byte for byte (Maven 3.9.11 and Temurin 21.0.13.1+2), and all 238 Kiama classes (sbt 1.9.2 `core / compile` and Scala 2.13.7 invoked independently on Temurin 17.0.21+9). Servlet and Mail compiled on the latter JDK using Maven 3.8.8 and 3.9.11 respectively and matched class names, not the vendor bytes. LSP4J's three projects built on the same JDK with Gradle 8.0.2 and regenerated all 141 published Java files byte for byte. All 244 class names matched, also confirmed by an independent `javac --release 11 -g` check using the supplied generated files and Gson 2.10.1; class bytes differed. These checks did not run the full upstream test or publishing tasks.
- The wheel build and `nix build .#jvm-source-companions` emitted the same `jvm-priority-sources.tar` (SHA-256 `2145fed8f79cfaba9331d3b80adb2c11e2d7062865ebd0fa2b5407555ccced9e`). The [installed guide](../packaging/jvm-legal/JVM-SOURCES.md) names the exact source inputs, packages, and availability steps for recipients. No downloads were added at review time. The [artifact checker](../release-tests/check-jvm-legal.py) verifies both installs, the wheel ZIP and companion parity; the native workflow still saves only checksums.

On Linux arm64 with caller Git 2.43.0, development acceptance passed 40 tests (one expected skip), and installed acceptance outside the checkout with no system Node.js or Java passed 22 tests each for Nix and pipx (four expected skips each). Both packages kept the expected backend digest. The reviewers independently rebuilt the local wheel with SHA-256 `6bd3c29be263e26a6cab8b923acab2e1bf783100be63106d272ae68dafa17b0a`, verified its JVM materials, and confirmed its runtime was unchanged from the acceptance-tested wheel. Both final installs also passed the archived source-site regression. No native matrix or public distribution was performed for this milestone.

## Release candidate: retained payload and source audit

**Question:** What do the binaries at `bd059ba` retain beyond the previously
matched JVM classes, and which unresolved items would still stop release?
We expected wheel/Nix JVM parity, but not parity between their Node and Java
inputs, and expected raw source archives to carry additional files.

- Two reviewers checked all 318 [retained non-class JAR entries](jvm-backend-resources.tsv)
  against pinned input evidence (308 exact, eight service merges or
  normalizations, two generated). The class replay still matches the same
  99 Maven artifacts. Four new upstream notice files cover identified
  JCTools, Izumi, Google common protos and the nested Xbase copy. Both
  packages also preserve matching Node/nbytes and Quint/npm notices.
- The [LSP4J check](lsp4j-license-evidence.md) found that the exact `jsonrpc`
  about file predates the EPL migration and is also in the source JAR.
  It also found copied Xbase EPL-2.0 code in `debug`, distinct from that
  stale-looking notice. No exact-artifact clarification was obtained;
  an EDL-only assumption is not supported.
- The [host audit](wheel-payload-audit.md) adds an offline wheel comparator
  checked against the local arm64 wheel and with negative controls. The
  native Linux x86-64 and macOS arm64 **vendor inputs**, not their final
  installs, were checked. Temurin's certificate set matched the companion
  source; the Linux GCC notice and build evidence do not yet identify the
  exact linked libgcc/libstdc++. The checked Nix arm64 closure has 65 paths
  including the root, not a mirror of the wheel's runtime.
- The wheel and separate Nix target now produce both identical filtered
  source tars (`2145fed8…` for the priority set, `01a19bf1…` for TLC).
  The [source archive audit](source-companion-audit.md) found unreviewed
  raw companion assets and binary test fixtures. Neither tar is a runtime
  dependency; the backend remains `1d2dab08…`.

On Linux arm64 with caller Git 2.43.0, development passed 41 tests (one
expected skip) and each installation passed 22 outside the checkout (four
expected skips). The two reviewers independently built and checked the
local wheel with SHA-256 `c071055e600f9efacebc9c68b3acffb57dde520ef91c2e34a935f43f9f101012`.
It differed from the acceptance-tested wheel only in the redistribution
notice and `RECORD`. The Nix runtime closure's referenced paths did not
change. No new native matrix was run.

Backend trimming and the remaining platform and archive source audits are deferred for the source-first trial. They still matter before publishing binaries: seek exact-artifact LSP4J clarification, verify any new repack against the native oracle and both installed suites, and rerun the checksum-only native matrix on the exact candidate. The [publication hold](../packaging/REDISTRIBUTION.md#publication-hold) remains in force.

## Source-first trial: real review from an unpacked candidate

**Question:** Can a reviewer go from a source-only candidate to a replayed witness without the project history, a wheel, or help from the maintainer?

Two collaborators tried independent scratch copies of `abc9dccb159e53b66295d39c8f57267e1dfb53f3` on Linux arm64 (Git 2.43.0, Nix 2.35.6). Installing from a Git archive into a new profile worked; reading the README and following its old demo stopped at `git archive prototype-handoff` because the source archive had no Git history. The candidate was local; neither the public default branch nor the checksum-only validation branch supplied this revision. The [new guide](source-trial.md) starts with supplied candidate source and uses a checked-in review file, not the archived fixture. A literal guide run also caught Git intercepting `git quint-diff --help` for a man page; `git-quint-diff --help` works.

Both collaborators fetched the actual upstream commits in [acceptance §2](first-release-acceptance.md#2-imported-consensus-scheduler), not the offline fixture. The predicted `{0}` on both histories in OLD self-comparison, `{0}` → `{0,1,2}` for round one and `{0}` → `{0}` for rounds one and two all held. The installed executable ran outside the source tree with a fresh HOME and a PATH containing only caller Git and the installed command. The forward terminal/JSON reports agreed: only `+ 1` and `+ 2`, each with three native transitions, and exhaustive closure in the selected scope (OLD 171 generated / 171 distinct; NEW 381 / 339; zero queued on both). The reverse and out-of-order history controls also agreed with the original scheduler.

The guide's replay helper independently compiled NEW's original `init` and `step`, matched all seven state variables at every frame, and recomputed both outcomes. The second collaborator separately compiled both original graphs and used a different checker to reproduce the outcome sets, replay the forward and reverse witnesses, and reject changing a later proposal to `9`. The standalone helper also rejected that mutation. Both collaborators checked the guide in archive-style directories, and `nix build --rebuild --no-link .` matched the existing Nix output from the unpacked source. With the historical DML repo supplied, the development suite ran 42 tests: 41 passed and one installed-only case was skipped. No runtime, scheduler support, packaging pins, or public artifacts changed.

This was a **collaborator dry run**, not an outside-user session or a cold-store build.

## Outside-user trial: handoff ready, feedback pending

**Question:** Where does a Quint user who did not help build the candidate first get stuck, or how long does it take them to replay a witness unaided on their usual machine?

The [forwardable handoff](outside-trial.md) fixes the candidate to `158ec18df0242c68995975fde4f06f8361060df5`, records the source archive digest, and asks for the host, elapsed time, and first replay or concrete blocker. The archive carries the tested guide and review; the handoff instructions are separate. Both collaborators independently verified the archive digest and ran the guide from extracted copies on Linux arm64 with existing Nix stores. The clean-config run needed the declared `nix-command` and `flakes` features enabled. Both reproduced a replay failure with spaces in `TMPDIR` and successful replay with `/tmp`. The handoff documents these prerequisites without changing the candidate. No outside participant has reported a result yet.

No outside participant is available, so that trial is deferred. Public wheels and project binary caches remain on hold.

## One-command demo and a second upstream change

**Question:** Can a first try show a real behavioral change without fetching a model, setting up a profile, or writing a review file?

`nix run .#demo` runs the installed command on the exact offline consensus fixture in a temporary repository. The default package does not carry the demo. Both collaborators ran it offline from unpacked source with build inputs already present: round one added `1` and `2`, and the two-receive history was unchanged. It removed its scratch directory; the default package derivation matched `158ec18`.

Separately, both collaborators wrote or checked a new review of upstream `6c76880b5ddc11de201acaa7f54a393799d15af6` → `e0a028017bdf60340178748ed11f62a89a7887bc`. In the same constants instance as the receive demo, observe `Procs.map(p => procState.get(p).x).size()` at initialization and after the first send, hiding only the round's crash branch. OLD assigns two distinct proposals; NEW allows the slots to start with the same proposal. Both histories closed at `{2}` → `{1,2}`. Independent checks against the original scheduler replayed both additions and confirmed the sets; the native graphs had 33 / 488 reachable states. This is proposal diversity in that instance, not a claim about consensus decisions.

## Discover call sites before writing a review

**Question:** Can a reviewer start with just a committed entrypoint, module, and scheduler, then find valid source selectors without tracing imports and counting columns by hand?

Repeat the exact upstream proposal-diversity review above, this time authoring its selectors from discovery on each revision separately. Expect to find the original imported send site and the crash leaf, then recover `{2}` → `{1,2}` at initialization and after the first send. Discovery must not name public labels, guess correspondence, designate hidden steps, or claim reachability. Use the moved-call fixture to check that identical calls remain distinct and that a renamed or moved site is emitted at its new position.

From a repository with both upstream commits available locally, run the following for each `REV`:

```sh
git quint-diff --discover --json \
  --entrypoint examples/classic/distributed/ConsensusAlgorithm/KSetAgreementConsensus.qnt \
  --module KSetAgreementConsensus --step step REV
```

Both collaborators authored the selectors from the two lists. Each listed five leaves in `ConsensusAlg.qnt`. The `sendMessages` call moved from `232:28` to `247:28`; the crash **leaf** moved from `231:23` to `246:23` (the `crash` call is at column 29, not the position to use for `hidden`). Each reviewer still chose the public label, constrained it with `round == 1`, hid only the crash leaf, and supplied the constants and observation from the earlier review. Reusing OLD's call position in NEW gave an incomplete review with no deltas.

OLD self-comparison matched `{2}` for both histories. The forward comparison found `{2}` → `{1,2}` at initialization and after the first send, with only `+1` in each. The history products closed at 8 generated / 8 distinct and 128 / 128 respectively, with zero queued. Both collaborators independently checked the original `init`/`step` graphs (OLD 33 reachable states and 40 edges; NEW 488 states and 600 edges) and replayed all seven state variables on the two witnesses, of lengths zero and two. A changed final proposal of `9` did not replay. Discovery eliminated manual coordinate counting and import tracing in this review. It did not choose the review scope or validate other schedulers, and no outside user tried it.

The offline receive fixture also builds a review from discovery output and checks it against the native oracle. The moved-call and failure cases cover distinct equal-effect occurrences, stable ordering, dirty index and working-tree isolation, a malformed import, a missing promised blob, and omission of a call taking a computed argument. Discovery uses the same public-leaf eligibility check as binding, without instantiating the model or starting Java. On Linux arm64, the development suite passed 45 checks (one installed-only skip) and the Nix-installed suite passed 26 (four development-only skips) with caller Git 2.43.0. The offline demo still reports only `+1` and `+2` after the first receive. The backend and pins did not change.

**Next question:** Can we bind a DML scheduler call with locally chosen arguments without regenerating its choices, guards, or updates? Start with a typechecked DML example and independently check both the outcomes and each reachable tagged state's projection onto the unfiltered native graph. The pinned parser rejects the exact historical pair before binding, so keep that boundary separate. Working-tree modes and public binaries are not part of that milestone.
