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

### Next experiment: select existing actions directly

**Question:** Can a deterministic bounded checker reuse `init`, the scheduler transitions, the two public actions, and a state observation from both exact blobs, without rewriting the model's guards?

Start with this same DML history and the matching-factor control on a Quint version that parses both revisions. Bind each public request to the existing action and its side-specific arguments; make the startup and event reset explicit in the evidence. Check the complete outcomes for the histories and bounds actually explored, report unsupported or incomplete work explicitly, and cross-check witness states against the independent model replay. This experiment should test whether action selection is enough here, not commit us to a production configuration format or a general rule for hiding internal steps.
