# Source-bound review (first slice)

Run `git quint-diff --review FILE [--json] OLD NEW` in the model repository. `OLD` and `NEW` are commit IDs or refs resolving to commits. This command does not implement index, working-tree, or merge-base syntax. The [example review](source-review.example.json) is paired with three known fixture commits; follow the [README](../README.md#try-it) to generate them.

## Review file

- `scenario` names the comparison. `histories` is the exact list of public label sequences to check, each of length 0–2. Use `[]` as a history to observe all initialized states without taking a step.
- `old` and `new` each select an `entrypoint` relative to the repository root, a `module` defined in that file, and its original nullary `init` and `step` actions. `observe` is a read-only Quint expression in that module, evaluated immediately after the last selected public step (at initialization for `[]`). Both sides must use the same scalar observation type: integer, Boolean or string. Values outside the backend's supported range are errors, not rounded observations.
- `bindings` maps each selected label to a direct call occurrence. Positions (`line`, `column`) are one-based Quint source positions at the beginning of the callee name. `callee` names its resolved declaration as `module::action`. Map explicitly on both revisions; use `null` for deliberate absence. Omitting both coordinates requires a unique direct occurrence of that callee. Identical effects do not identify a call. A stale, conflicting, or ambiguous selector is not absence.
- `hidden` lists the original alternatives allowed as hidden steps, by positions at the start of their expressions. Unlisted alternatives and public labels out of order are excluded. There is no native-transition bound: hidden steps can repeat until the finite reachable state space at that prefix is closed.

## Supported today

The scheduler must be local to the entrypoint module. Select a single leaf or alternatives of a top-level `any`. Bind a public leaf that is itself a direct action call, or an `all` with one direct action call plus state guards or assignments. Calls may be nullary or take literal integers, Booleans, or strings. Imported callees and two-hop file imports work; source imports must be regular blobs in each exact revision. The model may retain native nondeterminism inside callees or hidden leaves. No caller-local public arguments, nested scheduler binding, imported scheduler selection, constant instantiation configuration, or pre-state label predicates yet. See the [target release contract](supported-scheduler.md) for the intended scope after the consensus milestone.

The pinned backend requires Quint 0.33.1, Apalache 0.62.4/TLC, and the JDK in `nix develop`. It has compiler and evaluator limits; a backend error, timeout (60 seconds per Java process), or required evidence failure makes the review incomplete. This budget is not a semantic search cutoff.

## Read the result

`0` means **exhaustive** for the selected scenario and histories only. `1` means **incomplete**, with diagnostic side where known and no outcome deltas. `2` means invalid arguments or review format. A closed empty set explicitly distinguishes a missing label mapping from a bound label disabled after the first reachable prefix at which matching stops. A denial is an observed value, not an empty set.

JSON v1 describes each side's commit, source blobs, original scheduler and resolved call declarations, observation, and closure statistics. TLC statistics describe the history product, not the native graph. Histories are ordered by length and then by serialized label order; removals precede additions. A delta witness includes the producing revision, scenario, history, outcome, initialized state and original transitions (including hidden steps). State values are TLA+ literals keyed by the pinned compiler's variable names, not independent display strings or just the observed fields. Terminal output shows equivalent scope, changes, and witness steps for a human reviewer.
