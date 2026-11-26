# Design spiral

This repository is for experiments. We will archive it and start the program from scratch once the experiments have given us enough evidence to design it. Carry forward requirements, representative cases, reproducible checks, and the reasons behind design decisions. Do not assume the prototype's language, evaluator integration, flags, adapter shape, or JSON schema will carry over.

For each iteration, state the design question first. Record which revisions and scenarios were tried, what behavior should distinguish them, what the tool actually showed, and what the experiment did not establish. Keep the deterministic comparison contract in force: no LLMs, no random sampling, and no change claimed from an incomplete search.

## Baseline: controlled fixtures

The [Quint model](../spec/README.md) checks the set comparison on all selected histories through depth two. The CLI replay checks on temporary Git repositories cover an import-only change, nondeterministic outcomes, stable witness ordering, and failures that must not appear as behavioral changes. These are controlled fixtures, not evidence that the prototype fits a real review workflow.

The fixtures establish that a finite pure adapter is one workable way to enumerate successors. They do not establish that authors can write such adapters easily or that an adapter faithfully reflects actions already defined in an existing spec.

## Experiment 1: publication in DML

**Question:** How much extra work does it take to review a real Quint change with the current adapter, and is the resulting evidence useful to a reviewer?

### Prediction (before running the prototype)

Use [DML](https://github.com/micha/dml)'s `tests/recorded_return_design.qnt`, the finite design model for returning and publishing a recorded scale. OLD is `819ac9d9c496bf652ea85af12b3369844df2b1e4`; NEW is `c540078318bf52313a33d856c7825d6b09566b17` ("Check the requested factor before publishing a scale").

- Scenario `initial_source`: use the model's `init`, with `main = previousMain` and `returned = absent`.
- Selected labels: `stage_alternate` stages `alternate` (factor −2); `publish_alternate_expected_3` requests ordinary publication of `alternate` with `expectedMain = previousMain`, expected factor 3, no alias, and no injected failure. OLD's `publish` has no expected-factor argument; the label still describes the same request on both sides.
- Observe `(event.receipt, source.main, source.returned)`, not the arithmetic result: both scales can produce zero.
- Expected history: `stage_alternate → publish_alternate_expected_3`. Remove `(alternate, alternate, absent)` from OLD; add `(absent, previousMain, alternate)` from NEW. Both sides execute the publish action. NEW's rejection is a reported outcome, not a disabled action. As a control, a matching-factor request should publish on both sides.
- These are two **public** operations, not two transitions of the model's `step`: the full path also needs `startReturn` before staging and an event reset between staging and publication. Neither administrative transition is a selected public label.

### What the prototype actually did

```sh
nix develop --command python3 -B experiments/dml/adapter-boundary.py ../dml
```

1. **Exact Git revisions.** At public depth 0–2 (seven requested histories), both original entrypoints fail to parse under the prototype's pinned Quint 0.33.1: `QNT000` at `observation` declarations. Both DML revisions also pin 0.33.1 for their local replay shell, although this design model uses newer syntax. The probe tries both comparison directions because the CLI stops at the first bad snapshot.
2. **Isolate the adapter constraint.** In temporary commits only, change `observation` qualifiers to `val` and import the otherwise untouched stateful model. A label can bind the original `stage` and the side-specific `publish` signatures as action aliases without restating their guards. But `initialStates` and `successors` cannot call `init`, `stage`, or `publish` through pure functions: Quint rejects the bridges with `QNT200`. The shim only gets us far enough to test the effects; it is not a patch to DML or a behavior comparison. A pure adapter would need the transition logic extracted into shared pure functions or reimplemented separately. We did neither.

All four probes exit 1 with `incomplete`, zero completed histories, and no `+`/`−` rows or equivalence claim. Both output formats show the requested scope and failure; neither provides a behavior witness. Depth was not the limiting factor: no exploration started, so this experiment provides no evidence about practical search depths for this model. Merely upgrading the parser would not supply the `review` module that the CLI requires.

### Independent check on the original model

Quint 0.34.0 parses both exact blobs. Supply that executable separately; the project's shell still pins 0.33.1 and provides Java and the Apalache 0.62.4 distribution used to run TLC.

```sh
DML_SHOW_TLC_TRACE=1 nix develop --command bash experiments/dml/scheduler-oracle.sh \
  ../dml /absolute/path/to/quint-0.34.0
```

The oracle covers the predicted trace using the model's original `init` and `step`. After `startReturn → stage(alternate) → reset event → publish`:

| Original snapshot and request | `(receipt, main, returned)` |
| --- | --- |
| OLD, no factor argument | `(12, 12, 0)` (`alternate`, `alternate`, `absent`) |
| NEW, requested factor `3` | `(0, 3, 12)` (`absent`, `previousMain`, `alternate`); the whole source record is unchanged |
| NEW control, requested factor `−2` | `(12, 12, 0)`; the OLD action is the same for either request |

TLC reached each target at depth five including the initial state. The OLD, NEW mismatch, and NEW matching covers stopped with 482, 802, and 798 states queued, respectively. This confirms scheduler reachability, not absence of other outcomes across the state space. Inspecting the original `stage` and `publish` bodies explains the specific path: with the arguments and administrative steps fixed, the only new condition is factor equality. The arithmetic result is not used as evidence. These are checks of DML's finite design model, not replay of its native implementation or output from `git quint-diff`.

## Experiment 2: select existing DML actions directly

**Question:** Can a deterministic bounded checker reuse `init`, the scheduler transitions, the two public actions, and a state observation from both exact blobs, without rewriting the model's guards?

### What was selected

[`direct_actions.py`](../experiments/dml/direct_actions.py) is a separate experiment, not a change to `git quint-diff`. It reads the same two committed blobs as Experiment 1 and writes each unchanged to an isolated temporary directory. Neither blob has transitive imports. A [generated Quint module](../experiments/dml/direct_actions_driver.py) imports the original model and selects:

1. `init`, then `startReturn` in the worker phase;
2. `stage(alternate)` when the scheduler is ready for a source operation;
3. the original `step` when the stage report is present, forcing its event-clear branch;
4. `publish(alternate, previousMain, …, false, 0)` when ready again. NEW uses `plannedFactor` (`3`) for the mismatch or `alternateFactor` (`−2`) for the control. OLD has no factor argument and calls the same action for either public request.

The selection fixes scheduler branches and arguments; it does not copy the stage or publish guards. We checked both original schedulers admit these choices. The only added state is the wrapper's phase, which distinguishes the two histories even when their model states coincide.

### How it checks complete sets

Quint 0.34.0 compiles the wrapper to TLA+ using Apalache 0.62.4. TLC searches it with one worker and stops on a counterexample to “every end state has a previously witnessed `(history, observation)`.” Save the structured witness, extend the invariant to allow that pair, and repeat. The final pass must succeed and exhaust the search: a witness (even with zero queued states) is not a proof that no other outcome exists. The transition relation is the same in every pass; it is not filtered by previously seen observations. This requires no list of expected outcomes in advance. An unavailable tool, runtime failure, missing expected fixture path, timeout, or unclosed search reports `incomplete`, with no comparison claim.

### Observed results

| Selected public history | OLD outcomes | NEW outcomes | Delta |
| --- | --- | --- | --- |
| `stage_alternate → publish_alternate_expected_3` | `{(12, 12, 0)}` | `{(0, 3, 12)}` | `− (12, 12, 0)`; `+ (0, 3, 12)` |
| `stage_alternate → publish_alternate_expected_minus_2` | `{(12, 12, 0)}` | `{(12, 12, 0)}` | None |

The mismatch on NEW executes `publish` and leaves the whole source record unchanged. Both sides closed in three TLC runs (two witnesses and one exhaustive pass). The closing pass on each side had **6 generated, 6 distinct, 0 queued**, at depth 5 including `init`. The four witnesses agree with the independent original-scheduler covers above. We also checked that, after dropping the wrapper's phase, all original variables agree at each state along the selected scheduler paths.

```sh
# Use an absolute path to a Quint 0.34.0 executable; nix develop supplies Java and the pinned jar.
nix develop --command python3 -B experiments/dml/direct_actions.py ../dml /path/to/quint-0.34.0
# Add --json for the structured scope, outcome sets, and witnesses.
DML_CHECKOUT=../dml DML_QUINT=/path/to/quint-0.34.0 \
  nix develop --command python3 -B experiments/dml/test_direct_actions.py -v
```

The live checks repeat the review with invalid saved working-tree source, add a second outcome to one history in a temporary selector, and check that a missing expected path or a runtime error after a witness does not produce a delta. Those probes test the checker, not additional DML behavior. The checker limits each tool invocation to 120 seconds and each side to 32 different history/outcome pairs.

**Scope:** This exhausts only two explicitly selected length-2 histories, each with four model transitions. It does not compare prefixes as separate histories, exhaust the original scheduler, or check the DML implementation. The two real DML histories each have one outcome per side; the extra outcome in the test is synthetic. Selecting the actions was enough here, but choosing the bindings and the scheduler context still required reading both revisions. The wrapper and compiler plumbing are not production interfaces.

## Experiment 3: preserve DML's scheduler choices

**Question:** Can the checker retain multiple outcomes for one public history without requiring the reviewer to spell out the internal schedule?

### Prediction (before running the comparison)

Reuse the exact DML model and commits from Experiment 1 and the two length-2 public histories from Experiment 2. Instead of fixing the schedule, run the original `init` and `step`. Match public operations by their event report (command and requested arguments, **not** the receipt). Allow all original transitions with an empty report before the selected publish; reject other reported operations and stop immediately on the selected publish. In particular, the reviewer does not prescribe when to start the return, when to clear the stage report, or whether another writer updates `main`.

Observe the publication receipt alone: `alternate` (`12`) or `absent` (`0`). The ref state is part of the execution evidence, not the comparison key. OLD should accept when `main` still matches `previousMain`, and reject if a report-free scheduler step moves `main` first. Both should be reachable for the same public history. NEW should reject the factor-3 request regardless of schedule but retain both outcomes for the matching factor −2. Compare OLD with itself first (no delta), then OLD with NEW (only `− 12` for the factor-3 history). A search restricted to four original transitions cannot fit a competing write; it should not be mistaken for full scheduler coverage.

### Binding and outcome sets

[`scheduler_actions.py`](../experiments/dml/scheduler_actions.py) compiles each committed blob unchanged. A history monitor on the compiled `step` reads the successor event and tracks whether the stage and publish labels have occurred. It does not assign any model variable or encode any transition guard. Both publish labels select the request for `alternate` with expected main `previousMain`, `aliasesMain=false`, and `failAt=0`; the labels constrain the factor on NEW and share the same original action on OLD. With no transition bound the monitor has no step counter. TLC can collapse cycles that return to the same full model state and history phase, not states that merely share a receipt.

| History (after `stage_alternate`) | OLD outcomes | NEW outcomes | OLD → NEW |
| --- | --- | --- | --- |
| `publish_alternate_expected_3` | `{0, 12}` | `{0}` | `− 12` |
| `publish_alternate_expected_minus_2` | `{0, 12}` | `{0, 12}` | None |

The self-comparison ran first and found both receipts for each history on each side, with no delta. A shortest witness for the OLD rejection uses five original steps: start return, stage, clear the report, a report-free write moving `main` from `3` to `0`, and publish. The OLD acceptance skips that write. NEW can reject the factor-3 request even with `main` still at `3`. These are all executions of `publish`, not missing actions or disabled steps. The receipt-only comparison does not claim that rejection reasons or ref states are unchanged.

All four unbounded closing passes (two for self and two for the change) had **572 generated, 182 distinct, 0 queued**; each OLD side took five TLC runs and the changed NEW side took four, including the closure run. The result is exhaustive **for these two public histories and the report-free transitions allowed by the monitor**. It does not compare shorter prefixes, other requests, paths with other reported operations, or the DML implementation. At `--max-transitions 4`, OLD has only `{12}` per history, so the mismatch reports `− 12` and `+ 0` within that smaller scope. At five steps, the OLD rejection is reachable and `+ 0` disappears. At three, neither history finishes on either side. `init` does not count against the transition bound.

### Independent checks and reproduction

The [oracle](../experiments/dml/nondeterminism-oracle.sh) uses the original `init` and `step` without a monitor. It found the current-main and stale-main outcomes in four and five transitions respectively and checked that the only reports along each witness were the requested stage and publish. Its stale-main witness moved `main` to `competingMain` (`4`), a different path to the same receipt. The covers establish presence, not exclusion. Separate invariants checked to closure over the **full original scheduler** restrict the selected requests' receipts to `0` or `12` on OLD, and permit `12` only for the matching factor on NEW. Together with the covers, they independently establish the outcome sets. Those closing runs reached depth 28 including `init`: OLD had **1,269,121 generated, 611,528 distinct, 0 queued**; NEW had **2,367,361 generated, 1,160,648 distinct, 0 queued**.

```sh
export DML_CHECKOUT=../dml DML_QUINT=/absolute/path/to/quint-0.34.0
nix develop --command python3 -B experiments/dml/scheduler_actions.py "$DML_CHECKOUT" "$DML_QUINT" --self
nix develop --command python3 -B experiments/dml/scheduler_actions.py "$DML_CHECKOUT" "$DML_QUINT" --json
nix develop --command bash experiments/dml/nondeterminism-oracle.sh "$DML_CHECKOUT" "$DML_QUINT"
nix develop --command python3 -B -m unittest discover -s experiments/dml -v
```

The live tests also check scope at three, four, and five transitions, stable results and witnesses with invalid saved working-tree source in a scratch clone, and `incomplete` rather than empty results when the backend is unavailable. The same 120-second invocation timeout and 32-outcome limit from Experiment 2 apply to this comparison. Run concurrent compilations with different `DML_TLC_ENDPOINT` ports if they conflict.

## Experiment 4: select actions without an event report

**Question:** Can a reviewer identify public actions in an existing model that does not record an event report, without copying its scheduler guards or losing hidden choices? Can the checker avoid mistaking a different action with the same effect for a selected call?

### Prediction (before running the comparison)

Use upstream [Quint](https://github.com/quint-co/quint)'s `examples/classic/distributed/ConsensusAlgorithm/KSetAgreementConsensus.qnt`, which imports and re-exports `ConsensusAlg.qnt`. Compare OLD `883cc2c579bd11954129d207899790e80fb8c91e` with NEW `35df73a703259890303659e421f79016897993b3` ("Fix union and improve comments"). The scheduler lives in the imported module, and the transition change is in its `receiveMessages` action. The other file changes only in test comments. A scenario module imports `KSetAgreementConsensus`, giving a file chain from the review driver to the model.

- Use the model's `init` and `step`, with `N=3` (the source's `Procs` is `1..N-1`), `F=1`, `ACTUAL_FAULTS=1`, `K=1`, and `MAX_ROUNDS=2`. Do not fix initial proposals, which process crashes, or who gets the optional message.
- Select the scheduler call to `receiveMessages` in round 1 and in round 2. Other original branches are hidden, not new steps. Observe the number of process slots (including the crashed process) whose `S` contains the empty set immediately after the selected public call. This measures the model's explicit no-delivery marker, not the eventual consensus decision.
- For `receive_round_1`, OLD should only allow `0` and NEW should allow `0`, `1`, and `2`: the revised choice gives each of the two processes an independent no-delivery option. For `receive_round_1 → receive_round_2`, both should allow only `0`: the first round spends the sole crash, and no later optional crash message is available. Compare OLD with itself first. A separate check should demonstrate that a test helper with an identical full-state effect is not a scheduled public call.

### What the binding had to specify

[`action_identity.py`](../experiments/consensus/action_identity.py) stages the two exact committed files in isolation per side and compiles the scenario. It annotates the named calls inside the **compiled original** `step` with a fresh action tag. The scheduler body is copied mechanically; erasing those tag assignments yields the original body, including its guards, stage updates, and nondeterministic choices. It never calls `receiveMessages` on its own or selects it by looking at `S`. Hidden calls do not advance the public history. The two outcomes are measured immediately after the respective receives; the second receive ends exploration on that path.

The reviewer supplied the initialized instance, the specific scheduler call and round-to-label mapping, and the observation. Nothing had to be added to the original source. The importer can resolve the model through the committed file chain, but this experiment recognizes a pinned compiler's specific scheduler shape and rejects missing or ambiguous expected call sites. It does not infer which actions are public or generally resolve source identities after flattening. Quint 0.34.0 compiles with `--invariant=true` to omit an unrelated historical `validity` formula using `getOnlyElement`; compiling that formula in this older model failed without the option. `init` and `step` still come from the original model.

### Observed results

| Selected history | OLD | NEW | OLD → NEW |
| --- | --- | --- | --- |
| `receive_round_1` | `{0}` | `{0, 1, 2}` | `+ 1`, `+ 2` |
| `receive_round_1 → receive_round_2` | `{0}` | `{0}` | None |

OLD self-comparison ran first and had no delta. The monitor closed in three TLC runs on each OLD side (**135 generated, 135 distinct, 0 queued** in the closing pass), and five runs on changed NEW (**279 generated, 237 distinct, 0 queued**). Round-1 witnesses take three original transitions; round-2 witnesses take seven. At a bound of two neither history finishes, and at three only the first does. No bound was needed for the table, but it is exhaustive only for the stated instance, histories, and observation at the instant of each selected call. The scheduler fixes the order of kinds of steps; this checks retained choices within that order, not arbitrary interleaving or consensus properties. In particular, the second round's identical observation does not show that its complete states or decisions are equivalent.

### Independent check and negative control

The [native oracle](../experiments/consensus/native-oracle.sh) uses pinned Quint 0.33.1 and the original scheduler without action tags. Reachability covers find each listed result; separate invariants exclude other results. Its closing passes include the rest of the original scheduler: OLD **171 generated, 153 distinct, 0 queued**; NEW **339 generated, 267 distinct, 0 queued**, both at depth nine including `init`. Independently replaying the comparison JSON with that compiler verifies all six witnesses against the native `init` and `step`, constraining all seven original state variables at every frame. Changing one intermediate proposal from `1` to `9` without changing the labels or reported outcome caused replay to fail.

The declared test helper `receiveMessage(Set())`, together with the same stage update, satisfies the **full** before/after transition predicate of a native all-delivery receive on both revisions. The oracle proves that overlap for zero omissions, then refutes a deliberately false disjointness check with a first-round witness on each side. The original scheduler only invokes `receiveMessages`; a matcher based on whether a named action's relation accepts the state pair would misattribute the helper. The monitor does not report the helper, and its binding tests reject both a missing call replaced by the helper and a duplicate call site.

```sh
export CONSENSUS_CHECKOUT=/path/to/quint-repo CONSENSUS_QUINT=/absolute/path/to/quint-0.34.0
nix develop --command python3 -B experiments/consensus/action_identity.py "$CONSENSUS_CHECKOUT" "$CONSENSUS_QUINT" --self
nix develop --command python3 -B experiments/consensus/action_identity.py "$CONSENSUS_CHECKOUT" "$CONSENSUS_QUINT" --json > /tmp/consensus-comparison.json
nix develop --command bash experiments/consensus/native-oracle.sh "$CONSENSUS_CHECKOUT" /tmp/consensus-comparison.json
nix develop --command python3 -B -m unittest discover -s experiments/consensus -v
```

The live tests also rerun with both saved working-tree files invalid, check stable witness order, and require `incomplete` for missing snapshots or an unavailable backend. The original CLI is unchanged. The checker reuses the earlier limits: 120 seconds per invocation and 32 history/outcome pairs per side.

## Experiment 5: source-level bindings across revisions

**Question:** Can a reviewer bind public labels to source-level call sites without depending on flattened names or compiler formatting, including when two call sites invoke the same definition?

### Prediction (before running the comparison)

Use a controlled three-commit Git fixture: OLD, a refactor that moves the two public branches and renames the scheduler and imported callee, and a change that alters only the `beta` branch's argument. Start at `x = 0`. A hidden preparation step can set `x` to `1` or `2`; both public branches can then call the same action with the same argument. Hide preparation and reset, select the single-call histories `alpha` and `beta`, and observe `x` immediately after the call. Compare OLD with itself first. In OLD and the refactor both labels should reach `{3}`; in the changed revision only `beta` should switch from `{3}` to `{4}`. Attributing calls by their state effects cannot distinguish the two OLD sites. A selector that names only their shared callee should fail as ambiguous, not guess by order. Check projected scheduler edges separately from the history comparison, before cutting paths at the selected call.

### What the reviewer mapped

[`make_fixture.py`](../experiments/source_binding/make_fixture.py) creates the commits from the [fixture sources](../experiments/source_binding/fixtures/). No upstream model was changed for this control. The explicit per-revision [bindings](../experiments/source_binding/bindings.json) point into `workflow.qnt` and identify the imported action by file, module and name:

| Revision | Commit | Scheduler → callee | `alpha` line:column | `beta` line:column |
| --- | --- | --- | --- | --- |
| `old` | `0a5db49fffb644269f455207705dd59f71eb9933` | `step` → `marks::mark` | `12:28` | `14:28` |
| `refactor` | `75325f79c4a62330c971d8dfab971cbc447f99b3` | `dispatch` → `marks::record` | `18:28` | `15:7` |
| `changed` | `d627ef22313d7733711712168d82df02e60163f9` | `dispatch` → `marks::record` | `18:28` | `15:7` |

[`source_bindings.py`](../experiments/source_binding/source_bindings.py) stages the exact entrypoint and import in separate directories, ignoring the saved working tree. It uses pinned Quint 0.33.1's parsed AST, source map and name-resolution table to check that each position is a call to the intended declaration. The source-layer edit wraps each original scheduler branch with one fresh tag assignment: `alpha`, `beta`, or `hidden`. The supported shape is a top-level `any` of `all` branches, with each selected call a direct conjunct of its branch. No guard or update is regenerated. The TLA+ checker uses the compiled entrypoints and monitor definitions; it does not match compiled call names or scheduler formatting. The history filter is separate from the tags and stops after the first public call.

The resolver can say which declaration a given call invokes and where it occurs in one commit. It cannot establish that one occurrence means `alpha`, or that its identity survives a move: the reviewer provides that mapping independently for each side. AST IDs and source positions are not cross-revision keys. Since both OLD calls have the same guards and effect, even a swap would pass the OLD→refactor outcome check; verifying source provenance is necessary. Dropping `alpha`'s position leaves two candidates and reports `incomplete` before exploration. A stale position finds zero sites and mapping both labels to one branch also fails. These are binding failures, not removed behavior.

### Observed results

| Comparison (in run order) | `alpha` OLD → NEW | `beta` OLD → NEW | Delta |
| --- | --- | --- | --- |
| OLD → OLD | `{3}` → `{3}` | `{3}` → `{3}` | None |
| OLD → refactor | `{3}` → `{3}` | `{3}` → `{3}` | None |
| OLD → changed | `{3}` → `{3}` | `{3}` → `{4}` | `beta`: `− 3`, `+ 4` |

Each side closed in three TLC runs (two witnesses and one successful exhaustion pass: **7 generated, 5 distinct, 0 queued**). Both changed `beta` witnesses go from `x=0` through hidden `x=1` to the selected call; the model also permits `x=2` before that call. Rerunning with both saved source files invalid yielded identical structured output and witnesses. This is exhaustive for the two single-call histories and observation in the fixture, not a comparison of longer histories or arbitrary Quint schedulers.

### Independent check and reproduction

The [native oracle](../experiments/source_binding/native_oracle.py) loads committed sources independently, compiles the untagged and tagged models, and compares their full reachable graphs **without** the history filter. Erasing the tag preserves the initial state, reachable states and outgoing projected edges from **each** reachable tagged state. It also checks the tagged edge triples against hand-written expectations. Source tests separately remove the inserted wrappers and recover the original entrypoint byte for byte; the imported file was never edited.

| Revision | Native generated / distinct / edges | Tagged generated / distinct / edges |
| --- | --- | --- |
| OLD and refactor (each) | 8 / 4 / 5 | 11 / 6 / 10 |
| Changed | 9 / 5 / 8 | 11 / 6 / 10 |

All six graph searches had one initial state and zero queued at closure. The projected native graph is unchanged by the refactor. The change makes `1→4`, `2→4` and the reset `4→0` reachable, while the `alpha` branch still reaches `3`. A negative control removes `0→2` only at initialization; the global projected edge union still agrees because that edge remains possible after reset, but the per-state check rejects it. Swapping the public tags in `changed` leaves the native edge relation intact but fails the tagged edge check. The separate checker paths and fixture results were cross-reviewed.

```sh
# Run in nix develop (Quint 0.33.1, Apalache 0.62.4/TLC).
scratch=$(mktemp -d)
python3 -B experiments/source_binding/make_fixture.py "$scratch/repo"
for case in old refactor changed; do
  python3 -B experiments/source_binding/source_bindings.py compare "$scratch/repo" "$case"
  python3 -B experiments/source_binding/source_bindings.py stage "$scratch/repo" "$case" "$scratch/$case"
  python3 -B experiments/source_binding/native_oracle.py "$scratch/repo" "$case" "$case" "$scratch/$case"
done
# Expected exit 1 and incomplete, with no deltas:
python3 -B experiments/source_binding/source_bindings.py compare "$scratch/repo" refactor --ambiguous --json
python3 -B -m unittest discover -s experiments/source_binding -v
```

## Experiment 6: source bindings in a real imported scheduler

**Question:** Does source-level tagging still preserve behavior when a real scheduler selects a nondeterministic action through nested `if` and `match` branches?

### Prediction (before running the comparison)

Revisit Experiment 4's upstream pair: OLD `883cc2c579bd11954129d207899790e80fb8c91e` and NEW `35df73a703259890303659e421f79016897993b3`. Instantiate `KSetAgreementConsensus` with `N=3`, `F=1`, `ACTUAL_FAULTS=1`, `K=1`, and `MAX_ROUNDS=2`, through its original import of `ConsensusAlg`. Bind `receiveMessages` at its source call in `ConsensusAlg.step`; the pre-state round determines `receive_round_1` or `receive_round_2`. Observe the count of process slots whose `S` contains the empty set immediately after each receive, including the crashed process's slot. Run OLD against itself first: both histories should reach `{0}` on each side. Then expect `{0}` → `{0,1,2}` after round 1, with a witness for each of the two new counts, and `{0}` → `{0}` after `receive_round_1 → receive_round_2`.

Replay those witnesses through original `init` and `step` with all seven original variables constrained. Check erasure on the full scheduler separately from the selected-history filter, comparing outgoing projected edges from each reachable tagged state. Unsupported nesting should be `incomplete`, not an empty outcome or a reason to reconstruct guards or match compiled scheduler calls.

### Binding and instrumentation

[`source_actions.py`](../experiments/consensus/source_actions.py) stages the exact regular blobs in separate scratch directories. The scenario driver imports `KSetAgreementConsensus.qnt`, which in turn imports and re-exports `ConsensusAlg.qnt`. In both commits the selector is `ConsensusAlg.qnt:248:30`: a direct nullary call in the `Receiving` arm. Quint 0.33.1's AST, resolver table and source map check that position against the `receiveMessages` declaration at `181:10`. The checker follows the conditional's action branches and the payload-free `match` arms, down to a bare action or one direct action with simple assignments. It does not search arbitrary subexpressions for a matching name or use compiled scheduler names. Stale, missing, duplicate, and unsupported sites fail before exploration; using a helper with the same effect does not rescue a failed binding.

Adding a tag to original `step` directly failed typechecking: unrelated upstream runs join `init` and `step` and require the same update effects. Instead, append a tagged sibling `reviewStep` using the exact source slice of the original predicate and insert wrappers only at AST-delimited leaves. A separate `reviewInit` calls the original `init`. The committed scheduler and other declarations remain intact, and the intermediate import is never edited. Erasing the wrappers from the sibling recovers the original predicate byte for byte: no guards, assignments, or nondeterministic choices were reconstructed. The selected leaf writes the current round to a fresh tag; hidden leaves and initialization write zero. Only the separate history checker interprets the tag as progress and stops at the second selected receive.

### Observed results

OLD self-comparison ran first and found `{0}` on both sides of both histories, with no delta. The change reproduced Experiment 4, this time without editing compiled scheduler text:

| Selected history | OLD | NEW | OLD → NEW |
| --- | --- | --- | --- |
| `receive_round_1` | `{0}` | `{0, 1, 2}` | `+ 1`, `+ 2` |
| `receive_round_1 → receive_round_2` | `{0}` | `{0}` | None |

Each OLD side closed in three TLC runs (**135 generated, 135 distinct, 0 queued** in the final pass), and changed NEW closed in five (**279 generated, 237 distinct, 0 queued**). The witnesses take three original transitions for the first history and seven for the second, excluding `init`. Repeating the comparison with both saved working-tree sources invalid reproduced the same bindings, outcomes and witnesses. There was no original transition bound, but these results are exhaustive only for this instance, these histories, and this observation. They don't establish state equality after round two or a consensus property.

### Independent checks and reproduction

[`projection_oracle.py`](../experiments/consensus/projection_oracle.py) independently loads and compiles the original `q_init` and `q_step`. It checks the full original and tagged graphs, without the history filter. Erasing the tag preserves the initial and reachable state sets and the outgoing projected edges from **each** reachable tagged state. The oracle independently identifies receive edges by native stage and round and checks every tag. Both graphs have nine initial states, no queued states, and search depth nine including `init`:

| Revision | Native generated / distinct / unique edges | Tagged generated / distinct / unique edges |
| --- | --- | --- |
| OLD | 171 / 153 / 162 | 171 / 153 / 162 |
| NEW | 339 / 267 / 330 | 339 / 267 / 330 |

The oracle independently derives the same two outcome sets from native reachability. It replays four self-comparison and six changed-comparison witnesses by matching each entire seven-variable initial state and each full consecutive state pair in the closed native graph. This requires an original `q_init` state and an original `q_step` edge at every frame, not just compatible observations. It rejects a witness that changes an initial proposal at a later frame, even if its labels and final omission count are unchanged. A wrong tag that hides the receive preserves the native graph but fails the tag check. A separate control loses an edge only from one tagged state and demonstrates why checking just the union of projected edges isn't enough. The two implementations were cross-reviewed.

```sh
# In nix develop: Quint 0.33.1 and Apalache 0.62.4/TLC.
export CONSENSUS_CHECKOUT=/path/to/quint-repo
scratch=$(mktemp -d)
driver=experiments/consensus/source_actions.py
oracle=experiments/consensus/projection_oracle.py
python3 -B "$driver" compare "$CONSENSUS_CHECKOUT" --self --json > "$scratch/self.json"
python3 -B "$driver" compare "$CONSENSUS_CHECKOUT" --json > "$scratch/comparison.json"
for side in old new; do
  python3 -B "$driver" stage "$CONSENSUS_CHECKOUT" "$side" "$scratch/$side"
  python3 -B "$oracle" "$CONSENSUS_CHECKOUT" "$side" "$scratch/$side" --report "$scratch/comparison.json"
done
python3 -B "$oracle" "$CONSENSUS_CHECKOUT" old "$scratch/old" --report "$scratch/self.json"
python3 -B -m unittest discover -s experiments/consensus -p test_source_actions.py -v
python3 -B -m unittest discover -s experiments/consensus -p test_projection_oracle.py -v
```

The experiment does not establish support for arbitrary Quint `match`, `any`, or local bindings. It uses the parser and compiler from one pinned version, and the checker and oracle support only this fixed instance. The production CLI is unchanged.

## Experiment 7: source bindings under nondeterministic arguments

**Question:** Can a source binding identify which requests an existing scheduler issued when a selected call's arguments come from local `nondet` bindings, without reimplementing the scheduler or reading an event report to identify the call?

### Prediction (before running the comparison)

Revisit Experiment 3's DML pair (`819ac9d9c496bf652ea85af12b3369844df2b1e4` → `c540078318bf52313a33d856c7825d6b09566b17`, `tests/recorded_return_design.qnt`). Start at the original `init`. Bind `stage(alternate)` and ordinary `publish(alternate, previousMain, …, false, 0)` at their original `any` branches, using their local nondeterministic argument values, not an event report to identify calls. Map OLD's factorless request to both public factor labels, allow the same report-free scheduling choices as Experiment 3, exclude other operations, and observe the receipt immediately after the selected publish.

Run OLD against itself first: expect `{0, 12}` for both histories on both sides, with no delta. Then expect only `− 12` for factor `3`, with both outcomes retained for factor `−2`. The OLD `12` witness should publish after stage and report reset; the OLD `0` witness can include an intervening write that makes the expected main stale. NEW should be able to report `0` for the factor mismatch even with main still current. Compare against Experiment 3's native evidence and measure the cost of independently checking erasure on the full unfiltered scheduler. Use that evidence to decide whether the first fresh implementation should support argument binding or report it as `incomplete`.

### Binding inside the scheduler

[`argument_bindings.py`](../experiments/dml/argument_bindings.py) stages the exact regular blob from each commit. Quint 0.34.0 resolves the `sourceStep` sites to the original `stage` and `publish` declarations:

| Snapshot | `stage` site → declaration | `publish` site → declaration |
| --- | --- | --- |
| OLD | `154:5` → `119:10` | `159:5` → `129:10` |
| NEW | `160:5` → `123:10` | `166:5` → `133:10` |

The checker follows action positions inside `if`, `any`, and local `nondet … oneOf()` bodies. The tagged siblings of `step`, `workerStep`, and `sourceStep` use the original source slices. The tag assignment for a selected site is inside the very same local bindings as its original call. It tests the actual arguments (including `mode == 3` and `if (mode == 3) 0 else mode`), not a re-derived check on the mode or anything in the successor event. Removing the tag wrappers and restoring the two routing names recovers the three original predicates byte for byte. The original declarations are untouched.

Every scheduler leaf is explicitly classified. The six tags distinguish hidden operations, selected stage, the two NEW publish variants, other operations, and the factorless OLD publish. Other stage/publish arguments and select/export/collect are not silently hidden. The history filter, separate from the unfiltered scheduler, maps the single OLD publish tag to either factor label without duplicating a native action. It reads only the tag to decide progress; `event.receipt` is read only as the observation. Unknown sites, duplicate selectors, and unsupported scheduler forms or argument expressions fail closed.

### Observed results

OLD self-comparison ran first and returned `{0, 12}` for each history on each side, with no delta. The changed comparison reproduced Experiment 3:

| History (after `stage_alternate`) | OLD outcomes | NEW outcomes | Delta |
| --- | --- | --- | --- |
| `publish_alternate_expected_3` | `{0, 12}` | `{0}` | `− 12` |
| `publish_alternate_expected_minus_2` | `{0, 12}` | `{0, 12}` | None |

All four closing passes had **572 generated, 182 distinct, 0 queued**. Each OLD side used five TLC runs; changed NEW used four. A successful publication takes four original transitions; stale-main rejection takes five. NEW's factor-3 rejection takes four with main still at `3`. These are executions of `publish`, not blocked calls. The invalid saved working-tree control reproduced the same bindings, outcomes, and witness order. There is no transition bound; exhaustion is only for these two histories, their specified hidden sites, and the receipt observation, not for other requests or the DML implementation.

### Independent check and reproduction

[`source_projection_oracle.py`](../experiments/dml/source_projection_oracle.py) independently stages and compiles the unchanged commits and checks both native and tagged graphs without the history filter. It compares outgoing projected edges from every reachable tagged state, plus the initial and reachable state sets. The oracle uses the native successor event to verify each tag and independently derive the outcome sets and shortest witness lengths; the source binder does not use that event for call identity. Witness replay checks all four original variables (`returning`, `worker`, `source`, `event`) on each original `q_init` frame and `q_step` edge. Negative controls reject an edge loss that the global projection union would miss, an incorrect legacy tag with an unchanged native graph, and a reachable state on the wrong witness edge.

Both revisions had one initial state, zero queued at closure, and search depth 28 including `init`. The native and tagged statistics agree in each revision:

| Revision | Generated | Distinct | Unique edges | Native / tagged DOT bytes |
| --- | ---: | ---: | ---: | ---: |
| OLD | 1,269,121 | 611,528 | 1,263,248 | 779,023,468 / 803,484,767 |
| NEW | 2,367,361 | 1,160,648 | 2,361,488 | 1,534,768,197 / 1,581,194,355 |

The independent checker reproduced both outcome sets and shortest lengths and replayed **all 15 witnesses** (eight from self-comparison, seven from the change). The full graph check visited roughly 3,400 and 6,400 times the 182 distinct states in the scoped review on OLD and NEW respectively. The entire independent sweep took minutes per revision in the concurrent run. The checker retains the two typed graphs in memory, but only one DOT dump at a time (up to about 1.5 GiB on disk here). These are regression-check costs, not the costs of the scoped comparison.

```sh
# In nix develop. Supply Quint 0.34.0 separately; the shell default is 0.33.1.
export DML_CHECKOUT=../dml DML_QUINT=/absolute/path/to/quint-0.34.0
scratch=$(mktemp -d)
driver=experiments/dml/argument_bindings.py
oracle=experiments/dml/source_projection_oracle.py
python3 -B "$driver" compare "$DML_CHECKOUT" "$DML_QUINT" --self --json > "$scratch/self.json"
python3 -B "$driver" compare "$DML_CHECKOUT" "$DML_QUINT" --json > "$scratch/diff.json"
for side in old new; do
  python3 -B "$driver" stage "$DML_CHECKOUT" "$DML_QUINT" "$side" "$scratch/$side"
done
python3 -B "$oracle" "$DML_CHECKOUT" "$DML_QUINT" old "$scratch/old" \
  --report "$scratch/self.json" --report "$scratch/diff.json"
python3 -B "$oracle" "$DML_CHECKOUT" "$DML_QUINT" new "$scratch/new" --report "$scratch/diff.json"
# Also run the full-graph check as an opt-in regression test. Use a scratch
# directory with room for the graph; this takes minutes, not seconds.
TMPDIR="$scratch" DML_FULL_PROJECTION=1 \
  python3 -B -m unittest discover -s experiments/dml -p test_source_projection_oracle.py -v
```

## Next milestone: prepare the fresh implementation

**Question:** What is the smallest source-bound comparison that an independent reviewer can reproduce without any of the experiment drivers?

Write a handoff with a supported-shape contract and black-box acceptance cases before archiving the prototype. Scope the first implementation to two committed snapshots, side-local imports, explicit per-revision bindings to supported direct calls with no arguments or literal arguments, short selected histories, and replayable outcome witnesses. Use the source-binding controls and the imported consensus receive histories to check this slice. Keep unsupported binding, backend failures, and unfinished searches visibly `incomplete`. Do not carry over the experiment flags, schema, or source rewriting implementation by default.

Defer general argument binding in the first slice. DML shows it can work without copying guards, but this experiment relies on pinned grammar and scope shapes, a mapping for every scheduler leaf, and an explicit old/new signature correspondence. Keep DML as both an initial fail-closed control and a later positive acceptance case. Full-graph erasure is an independent regression oracle, not a required pass of every review.
