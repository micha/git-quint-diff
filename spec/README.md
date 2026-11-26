# Finite comparison model

[`fixture_models.qnt`](fixture_models.qnt) defines the initial states, public labels, transition relations, and observations for three selected comparisons. [`comparison.qnt`](comparison.qnt) keeps the set of states each side can reach after a common history. It extends each frontier with **all** successors for the next label, then projects the final frontier to a set of observations. `added` is `NEW − OLD`; `removed` is `OLD − NEW`.

If the frontier becomes empty, the model records the first blocked step (one-based). An undeclared label is `MissingAction`; a declared label with no successor from any current state is `DisabledAction`. Both differ from a reachable state observed as `denied`. Extending a blocked history does not replace the original reason or revive the frontier.

## Checked scope and results

The model enumerates all histories of lengths **0–2** over each pair's union of public labels, including repeats and histories that cannot execute. The empty history observes the starting states. Observations are taken only at the end of each history. `fixtureOracle` checks the exact outcomes, first blocked step (if any), and both deltas against literals; `deltaLaw` checks that the deltas are disjoint, reconstruct each side, and distinguish an empty projection from a reached state.

- **Approval change (`new_user`, 7 histories):** the user begins without a ticket or training. Each acquisition is single-use, and NEW allows them in either order. Approval requires a ticket on OLD and both a ticket and training on NEW.
- **Nondeterministic self-comparison (`pending_review`, 3 histories):** one `request_review` can end as `approved` or `denied` on both sides. No history yields a delta.
- **Nondeterministic removal (`pending_review`, 3 histories):** after `request_review`, OLD reaches `{approved, denied}` and NEW reaches `{denied}`. The empty history reaches `{pending}` on both sides in both review comparisons; repeating `request_review` is disabled at step 2 on both sides.

These are all nonempty deltas in scope:

| Comparison | History | Removed (−) | Added (+) |
| --- | --- | --- | --- |
| Approval | `obtain_ticket` | `approved` | `denied` |
| Approval | `obtain_training` | — | `denied` |
| Approval | `obtain_ticket → obtain_training` | — | `approved` |
| Approval | `obtain_training → obtain_ticket` | — | `approved` |
| Nondeterministic removal | `request_review` | `approved` | — |

For example, `obtain_ticket → obtain_training` is missing step 2 on OLD, not denied. `obtain_ticket → obtain_ticket` is disabled at step 2 on both sides. `obtain_training → obtain_training` is missing step 1 on OLD and disabled at step 2 on NEW; this is not an outcome difference.

## Reproduce

From the repository root, using the pinned shell (Quint 0.33.1 and the TLC backend from Apalache 0.62.4):

```sh
nix develop --command quint verify spec/comparison.qnt --backend tlc --invariants deltaLaw fixtureOracle
```

TLC reported **3 initial states, 19 generated, 13 distinct, 0 left on queue**, and no violations. TLC counts the initial state as depth 1, so its graph depth of 3 means two public steps. The six length-two states stutter at the bound; the repeated states count toward the 19 generated but do not add histories.

Negative control (expected exit status **1** with an invariant counterexample, not a tool error):

```sh
nix develop --command quint verify spec/comparison.qnt --backend tlc --invariant naivePairedEquivalence
```

TLC rejects the claim that every paired observation agrees in the self-comparison after `request_review`. The trace has `{approved, denied}` on each side. Picking `approved` on OLD and `denied` on NEW would falsely remove `approved` and add `denied`, despite equal sets. Generated Apalache logs are ignored by Git.

This is exhaustive **within the stated bound for these models**. It does not check longer histories, evaluator failures, Git snapshots, CLI replay, or witness ordering.
