# Source-bound review

Run `git quint-diff --review FILE [--json] OLD NEW` in the model repository. `OLD` and `NEW` are commit IDs or refs resolving to commits. This command does not implement index, working-tree, or merge-base syntax. Try the [upstream consensus review](source-trial.md). The smaller [moved-call example](source-review.example.json) uses the fixture commits in [acceptance §1](first-release-acceptance.md#1-source-binding-identical-effects-moved-sites-literal-changes).

## Discover selectors

Before writing a review, list where the selected scheduler calls actions in one committed snapshot:

```sh
git quint-diff --discover --entrypoint path/to/model.qnt --module Model --step step OLD
```

Repeat for `NEW` with the entrypoint, module, and visible scheduler name from that revision. Discovery resolves and typechecks the committed entrypoint and its imports, without a review file, constants, an initializer, or a Java run. It lists leaves in scheduler order and shows each supported call's position and resolved declaration. The leaf may start at an `all`, not at the call within it.

With `--json`, the version 1 `discovery` report gives the resolved commit and source blob IDs. Copy `leaves[].call.selector` into `bindings` for a public call you choose. For a step you explicitly want to allow as hidden, copy `leaves[].leaf` into `hidden` instead. `call: null` means no supported public selector was offered for that leaf, not that an action is absent or disabled. Choose your own labels, cross-revision mappings, predicates, and hidden steps.

Exit `0` (`complete`) means source discovery succeeded, not that calls are reachable or that the model will compile and close under the review backend. Exit `1` (`incomplete`) reports a snapshot, source, or backend diagnostic and offers no selectors; exit `2` means invalid arguments. Only a review checks outcomes.

## Review file

- `scenario` names the comparison. `histories` is the exact list of public label sequences to check, each of length 0–2. Use `[]` as a history to observe all initialized states without taking a step.
- `old` and `new` each select an `entrypoint` relative to the repository root, a `module` defined in that file, and its original nullary `init` and `step` actions. Use the names visible in the module (which may import or re-export the actions). Optional `constants` maps instance parameters to JSON integers, Booleans, or strings. `observe` is a read-only Quint expression in the selected instance, evaluated immediately after the last selected public step (at initialization for `[]`). Both sides must use the same scalar observation type: integer, Boolean, or string. Unsupported values are errors, not rounded or substituted observations.
- `bindings` maps each selected label to a direct call occurrence. Positions (`line`, `column`) are one-based Quint source positions at the beginning of the callee name. A positioned selector defaults to the entrypoint; use `path` (relative to the repository root) for a call in an imported file. `callee` names the resolved declaration as `module::action`. Map explicitly on both revisions; use `null` for deliberate absence. Omitting the position requires a unique direct occurrence of that callee in the selected scheduler. Identical effects do not identify a call. A stale, conflicting, or ambiguous selector is not absence.
- An optional `when` on a binding classifies the call by a pre-state test of the form `round == 1`: one state variable visible in the selected instance, compared to a scalar literal. If sharing a site this way, all labels must test the same variable against distinct literals.
- Alternatively, give `args` as the exact full argument tuple (for example, `"args": [12, 3, -2, false, 0]`). Tuple entries must be JSON scalar literals of the corresponding Quint operand types; there are no wildcards. Use distinct tuples when sharing a site by `args`. Each side specifies its own tuple, which may have a different arity. Using neither filter labels the entire occurrence. Do not mix `when` and `args` at a site. A call that matches none of its site's filters is neither public nor hidden in that review. Discovery returns the site, not suggested tuple values.
- `hidden` lists the original leaves allowed as hidden steps, by positions at the start of their expressions (with `path` for imported leaves). Unlisted leaves and public labels out of order are excluded. There is no native-transition bound: hidden steps can repeat until the finite reachable state space at that prefix is closed.

## Supported today

The runtime can bind calls through nested action-position `any`, `if`, and payload-free `match`, including in an imported scheduler. A public leaf is a direct action call or an `all` with one direct action call plus state guards or assignments. The leaf or just the call term may be enclosed by local `nondet … = …oneOf()` binders. Operands may be scalar literals, in-scope choice values, or expressions combining those forms with equality and `if`. The runtime tests the actual operands within the original binders; it does not use successor state to infer the arguments. See the [DML-derived example](../release-tests/fixtures/dml/README.md). Branching inside a local binder, other operand expressions, payload-binding matches, and binding through scheduler helper bodies are outside the [release contract](supported-scheduler.md). All transitive file imports must be regular blobs in each exact revision.

The [installed command](../README.md#install) uses pinned Quint 0.33.1 and Apalache 0.62.4/TLC. It does not fetch dependencies or missing Git objects when reviewing; fetch any required objects yourself before starting. The backend has compiler and evaluator limits; for example, the translator cannot pass string literals containing backslashes, quotes, or control characters through losslessly. A backend error, timeout (60 seconds per Java process), or required evidence failure makes the review incomplete. This budget is not a semantic search cutoff.

## Read the result

`0` means **exhaustive** for the selected scenario and histories only. `1` means **incomplete**, with diagnostic side where known and no outcome deltas. `2` means invalid arguments or review format. A closed empty set explicitly distinguishes a missing label mapping from a bound label disabled after the first reachable prefix at which matching stops. A denial is an observed value, not an empty set.

JSON v1 describes each side's commit, source blobs, original scheduler and resolved call declarations, observation, and closure statistics. TLC statistics describe the history product, not the native graph. Histories are ordered by length and then by serialized label order; removals precede additions. A delta witness includes the producing revision, scenario, history, outcome, initialized state and original transitions (including hidden steps). State values are TLA+ literals keyed by the pinned compiler's variable names, not independent display strings or just the observed fields. Terminal output shows equivalent scope, changes, and witness steps for a human reviewer.
