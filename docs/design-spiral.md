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

## Next experiment: select actions without an event report

**Question:** Can a reviewer identify public actions in an existing model that does not record an event report, without copying its scheduler guards or losing hidden interleavings? Use a different real Quint model, preferably with transitive imports. Select public transitions by action identity or an explicit binding, and independently check that the original scheduler allows the producing witnesses and that the binding does not relabel unrelated transitions with the same state effect. Compare exact Git revisions and record where the model needs annotation versus what the tool can infer. Do not make the DML event convention or the experimental monitor a requirement for the production tool.
