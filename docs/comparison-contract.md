# Comparison design and acceptance plan

`git-quint-diff` is a deterministic Git subcommand. It does not use LLMs or random simulation. The comparison below comes before choosing an implementation language or a public review format.

## What gets compared

Git selects OLD and NEW. Resolve each side's entrypoint and transitive imports within that side's snapshot, without checking out another revision. The working-tree side, when requested, reads saved files, not editor buffers.

One review definition selects the model, corresponding starting scenarios, public action labels, and an end-of-history observation. Use the same selected labels on both sides: a label may exist on just one side, so do not reduce the selection to the intersection of declared actions. Each side provides a starting set of states for each selected scenario. The pure-adapter prototype explores only the named public steps. The [first fresh implementation](supported-scheduler.md) selects existing Quint scheduler calls and permits explicitly designated hidden steps; it never inserts internal steps implicitly.

For a given scenario and history:

- Start with all states allowed by the scenario. For each action label, retain every successor reachable by that label from any retained state, including through any explicitly permitted hidden steps before that label. Observe immediately after the last label; the empty history observes the starting states.
- Evaluate the observation on all final states and collect the distinct results. Compare these **outcome sets**, not individual executions, counts, or unobservable state. If an observation combines multiple fields, compare each observation as a whole to preserve correlations.
- An outcome is added when NEW produces it and OLD is known not to; removal is the reverse. Replay on the producing side establishes presence. Proving absence on the other side requires complete exploration for that history; a chosen execution alone never proves absence.

An observed `denied` is an outcome of a matching execution. An absent public action and a declared action with no successor from any state at a reachable prefix are distinct reasons a history can have no matching trace. If some states can take the action, the history continues through those states, even if others cannot. If both sides have no matching trace, there is no outcome delta, even if the reasons differ. An evaluation failure, unsupported model, or interrupted exploration is not evidence of an empty outcome set. If we cannot determine whether a candidate outcome occurs on the other side, do not mark it added or removed.

## Reporting and scope

Use factual `+` and `−` outcome labels, not a `Findings` column or generated interpretation. Report the review scope, witness evidence, and search status in both terminal and versioned JSON output. Visit shorter histories first and use a fixed order for ties and for choosing among equivalent witnesses. A witness should identify its scenario, public history, outcome, and enough of the producing execution to check it even when the history admits multiple outcomes.

An explicit list of histories defines the review scope; a complete result can be exhaustive for that list without covering other histories. When asking instead for all histories up to a maximum length, the bound limits **which histories** were checked, not the validity of differences for histories explored completely. An original-transition bound limits **which executions** were checked. Report limits explicitly. Failing to finish a history within the requested scope is **incomplete**, not a completed bounded result. Neither an explicit list nor exhaustion through a depth establishes anything about unsearched histories or executions.

## Pure-adapter prototype replay checks

Verify the finite comparison model with Quint/TLC first and record the checked scope. Then use the CLI on real Git revisions and check these cases against that model:

| Case | Required result |
| --- | --- |
| Approval, `new_user` → `obtain_ticket` | OLD `{approved}`, NEW `{denied}`: remove `approved`, add `denied`. |
| Approval, `new_user` → `obtain_ticket` → `obtain_training` | OLD has no matching trace because the training action is absent; NEW has `{approved}`: add `approved`, remove nothing for this history. |
| Same nondeterministic model on both sides | A history reaches two distinct outcomes on each side and produces no delta. Selecting a different valid execution on each side would produce a spurious delta; check this as a negative control. |
| One nondeterministic outcome disappears | The common outcome produces no delta; exactly the missing outcome is removed. |
| Only a transitive import changes | The entrypoint is unchanged; each side uses its own imported source. Use a third import version in the saved working tree so a read outside either commit cannot pass unnoticed. Check witness content and order on a repeat run. |

For the approval case, a depth-one run must not report the length-two witness; a depth-two run must report it, after shorter histories. Also check a prefix that reaches two states with the same current observation where only one enables the next action. The enabled branch must survive; neither selecting a single state nor merging states by current observation is sound. Separately check that a declared action with no successor is not called absent, and that an evaluation or exploration failure cannot create a false delta.

Verify the producing witness and the reported search scope; neither a single witness nor replay of these fixtures proves correctness on untested histories or models. Keep generated results untracked.
