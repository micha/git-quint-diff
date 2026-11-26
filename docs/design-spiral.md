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

## Next experiment: a real nondeterministic review

**Question:** Can direct action selection retain multiple real outcomes for one public history without requiring the reviewer to spell out the internal schedule? Pick an existing spec with genuine nondeterminism and an independently checkable revision that removes one of several outcomes. First compare it with itself, then review the change. Record how the binding identifies the public history, what internal steps it needs to allow, and whether the check preserves every reachable outcome. Defer the production interface until that evidence is in.
