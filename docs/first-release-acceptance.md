# First-release black-box acceptance

**Question:** Can an independent reviewer reproduce a source-bound comparison of two committed Quint schedulers without running any of the prototype comparison drivers?

Use the [supported-scheduler contract](supported-scheduler.md) for the supported subset and the meaning of search status. This plan specifies inputs and assertions, not a CLI spelling, a review file format, a JSON schema, or an evaluator. Run the implementation under test through its public interface in both reporting modes. The test harness may translate these review inputs into its chosen format and decode its reports; it must not compute the tool's answers for it. The prototype's oracles are evidence for the expected results, not the program under test. Use disposable Git repositories for fixture commits, dirty snapshots, and fault cases; keep generated reports untracked.

## 1. Source binding: identical effects, moved sites, literal changes

Create a scratch repository with [make_fixture.py][maker] and the archived [fixture sources][fixtures]. For example, from the current checkout:

```sh
scratch=$(mktemp -d)
git archive prototype-handoff experiments/source_binding | tar -x -C "$scratch"
python3 -B "$scratch/experiments/source_binding/make_fixture.py" "$scratch/repo"
```

Verify the resulting commit IDs, not just the tag names. Use `workflow.qnt` → `marks.qnt`, module `workflow`, original `init` (`x = 0`), and the following independent bindings for each commit. Coordinates below are one-based and point at the beginning of the callee name; an equivalent selector may use another position representation.

| Fixture revision and commit | Scheduler in `workflow` → callee in `marks.qnt` | `alpha` site in `workflow.qnt` | `beta` site in `workflow.qnt` |
| --- | --- | --- | --- |
| `old` `0a5db49fffb644269f455207705dd59f71eb9933` | `step` → `marks::mark` | `12:28` (`mark(3)`, intake) | `14:28` (`mark(3)`, recovery) |
| `refactor` `75325f79c4a62330c971d8dfab971cbc447f99b3` | `dispatch` → `marks::record` | `18:28` (`record(3)`, intake) | `15:7` (`record(3)`, recovery) |
| `changed` `d627ef22313d7733711712168d82df02e60163f9` | `dispatch` → `marks::record` | `18:28` (`record(3)`, intake) | `15:7` (`record(4)`, recovery) |

Hide only the preparation branch (chooses `1` or `2`) and the reset branch (`x` in `{3,4}` to `0`). Select exactly `[alpha]` and `[beta]`; observe the integer `x` immediately after each selected call, with no native-transition bound.

| Run in this order | `alpha` OLD → NEW | `beta` OLD → NEW | Deltas |
| --- | --- | --- | --- |
| `old` → `old` | `{3}` → `{3}` | `{3}` → `{3}` | None |
| `old` → `refactor` | `{3}` → `{3}` | `{3}` → `{3}` | None |
| `old` → `changed` | `{3}` → `{3}` | `{3}` → `{4}` | Only `beta`: `− 3`, `+ 4` |

All three runs close exhaustively **within the selected scope**. The producing `beta` witnesses start at `x=0`, take the original preparation step to `1` or `2`, and then the correctly bound recovery call to `3` or `4`. Check the reported positions and resolved declarations against the committed sources, including for the no-delta refactor: swapping the equal-effect OLD or refactor sites would pass an outcome-only check. Repeat with NEW `refactor` using (separately) a callee-only selector for `alpha` (two candidates), OLD's `alpha` coordinates (no matching site), and the same refactor occurrence for both labels. Each is an incomplete binding, not an absent or disabled action; no change may be attributed to the affected binding.

**Independent check.** The native graph for `old` and `refactor` is `0→1`, `0→2`, `1→3`, `2→3`, `3→0`; `changed` adds `1→4`, `2→4`, `4→0`. Derive the labels separately from the branch occurrences above, not from the before/after pair. The [native source fixture oracle][site-oracle] checks unmodified native reachability and tagged edges with pinned Quint 0.33.1 and Apalache 0.62.4/TLC. For implementations that track labels in extra state, add a separate internal regression: compare initial and reachable state sets and outgoing native projections **from each reachable augmented state**, before applying the history filter. The [negative controls][site-controls] swap tags without changing native edges and remove `0→2` only from the initial tagged state (the edge remains available after a hidden reset), without changing the global edge union. These demonstrate the limits of outcome-only and aggregate edge checks; neither an instrumented graph nor a full-graph pass is required at the release interface.

### Small derivatives

Unless specified otherwise, make each derivative as a separate child of `changed` in the scratch fixture; keep the other file and declarations unchanged. Derivative inputs are identified by their parent/input edit, not by a preassigned commit ID. Use the generated commit ID for the review, and resolve selectors at the edited positions instead of silently reusing stale coordinates.

- **Exact histories and hidden progress.** Self-compare `changed` with histories supplied in order `[beta, alpha]`, `[alpha]`, `[]`. The completed histories are exactly `[]`, `[alpha]`, `[beta, alpha]` in that order, with outcome sets `{0}`, `{3}`, `{3}` on each side. Do not report `[beta]` as a separately requested outcome. The longer history needs the hidden reset and preparation between the two calls; those moves are native steps, not public labels. Repeat with only `[alpha]` and leave preparation unclassified (not hidden) on either side: both sides have no match even though `alpha` is still bound. An unlisted alternative must not silently become a hidden step.
- **Do not merge by observation.** In `changed`, replace the intake guard with `x == 1` and the recovery guard with `x == 2`. Compare the derivative with itself for `[alpha]` and `[beta]`, observing `if (x <= 2) 0 else x`. Both hidden prepared states look the same under the observation, but both must survive: `[alpha]` has `{3}`, `[beta]` has `{4}` on each side. No deltas.
- **Denial, disabled, and deliberately absent.** Compare `changed` to a child where only the recovery guard is `x == 20`; nothing writes `20`. Use the same two singleton histories and observe `if (x == 3) "denied" else "approved"`. `alpha` reaches `{"denied"}` on both sides. `beta` reaches `{"approved"}` on OLD and has no matching execution on NEW: its validly bound call is disabled from the empty prefix even after hidden closure. Remove only `approved` for `beta`. Repeat with a separate child that deletes the recovery branch and explicitly maps `beta` as absent on NEW. The sets and delta are the same, but the reason on NEW is explicit absence, not disabled or failed binding.

## 2. Imported consensus scheduler

Use [upstream Quint](https://github.com/quint-co/quint) OLD `883cc2c579bd11954129d207899790e80fb8c91e` and NEW `35df73a703259890303659e421f79016897993b3`. The entrypoint is `examples/classic/distributed/ConsensusAlgorithm/KSetAgreementConsensus.qnt`, module `KSetAgreementConsensus`, importing and re-exporting `ConsensusAlg.qnt` in the same directory. In each snapshot instantiate `N=3`, `F=1`, `ACTUAL_FAULTS=1`, `K=1`, `MAX_ROUNDS=2`. Use the original `init` and `ConsensusAlg.step`; leave the proposals, crash, and message choices free.

In both snapshots bind `ConsensusAlg.qnt:248:30` in the `Receiving` match arm to `ConsensusAlg::receiveMessages` (declaration `181:10`). Label it `receive_round_1` when the **pre-state** `round == 1` and `receive_round_2` when `round == 2`. Hide the other native scheduler leaves (`stuttering`, `crash`, `sendMessages`, `computeAction`). Observe `Procs.filter(p => procState.get(p).S.contains(Set())).size()` immediately after the final public call, including the crashed slot. This is a count of no-delivery markers, not a consensus decision.

| Exact history | OLD → OLD | OLD → NEW | Change |
| --- | --- | --- | --- |
| `[receive_round_1]` | `{0}` → `{0}` | `{0}` → `{0,1,2}` | `+ 1`, `+ 2` |
| `[receive_round_1, receive_round_2]` | `{0}` → `{0}` | `{0}` → `{0}` | None |

Run self-comparison first. Require scoped exhaustive closure for both rows. As a reverse check, NEW → OLD removes exactly `1` and `2` for round one, with the witnesses on OLD (the producing side of this reverse comparison). As a history-filter check, request just `[receive_round_2]` on NEW → NEW: neither side can execute it without the intervening visible `receive_round_1`. Both outcome sets are empty and neither label is absent. Do not silently hide a selected public call because it is not the next requested label.

**Independent check.** [Native covers and invariants][consensus-covers], driven by [native-oracle.sh][consensus-script], establish presence and exclusion using the unchanged scheduler. The [projection oracle][consensus-projection] independently derives the same sets from the native graphs (nine initial states each, 153 / 267 distinct states and 162 / 330 unique edges at OLD / NEW closure). These are oracle reference counts, not required release search statistics. Adapt its report decoding or replay independently; do not reuse bindings or compiled transition predicates produced by the implementation under test as the oracle. Verify every supplied witness from `init` through each original `step` edge, constraining all seven original variables (`round`, `stage`, `crashed`, `newlyCrashed`, `correctProcsMessages`, `crashedProcsMessages`, `procState`), checking the correct call/round and recomputing the outcome. The shortest witnesses take three and seven native steps, excluding `init`; a stable replayable choice is required, not a particular trace.

The test helper `receiveMessage(Set())` with the same stage update can satisfy the **entire** before/after relation of a native all-delivery receive; the scheduler does not call the helper. Request a binding to that helper in `step` instead and require incomplete, not an inferred call or a no-change success. Separately mutate a witnessed proposal at a later frame to `9` without changing the claimed history or outcome. The independent replay checker must reject it; merely checking the reported label and count would accept it.

## 3. DML-derived argument selection and historical parser failure

### Finite derivative

Use the [fixture and side-local review inputs](../release-tests/fixtures/dml/README.md) for OLD `d3525cc2f98964fa0a04949fb6736b3da03610f5` and NEW `fab07489fc91c6b447b6bd7d2b5bbd5541cae5b3`. These are reproducible scratch commits, not upstream DML revisions. The committed scheduler chooses a stage candidate and independently chooses the publish candidate, expected main, and failure mode. NEW also chooses an expected factor. Bind `stage_alternate` to `stage` with tuple `[12]`. For each factor, use a separate review and bind the corresponding publish label to `[12, 3, false, 0]` on OLD and `[12, 3, factor, false, 0]` on NEW. Only the handoff, report clearing, and main move are hidden. Observe `receipt` after the exact history.

| Review | OLD outcomes | NEW outcomes | Deltas |
| --- | --- | --- | --- |
| OLD self, stage then expected `3` | `{0,12}` | `{0,12}` | None |
| Forward, stage then expected `3` | `{0,12}` | `{0}` | `− 12` |
| Forward, stage then expected `−2` | `{0,12}` | `{0,12}` | None |

Stage alone returns `{12}` on both sides. Test reverse comparison for expected `3` and replay its `+ 12` as well as the forward removal against all five original variables. Confirm exact closure with the original freely chosen arguments; `0` is a publish receipt for rejection. Independently compile the original scheduler and compare its outgoing native projection from each reachable tagged state, not just an aggregate edge set. Check the arguments and label of each tagged edge against the fixture's native event, including all unmatched tuples, which must stay in the unfiltered scheduler but not in the review. The runtime may not use that event to bind a call. A separate, typechecked derivative from §1 uses a local `nondet` choice on just one `all` term: it exposes both outcomes without `args`, and exact distinct tuples at the same occurrence expose only their matching outcomes without bypassing the guard.

### Exact upstream snapshots

Use [DML](https://github.com/micha/dml) OLD `819ac9d9c496bf652ea85af12b3369844df2b1e4` and NEW `c540078318bf52313a33d856c7825d6b09566b17`, entrypoint `tests/recorded_return_design.qnt`, module `recorded_return_design`, original `init` and `step`. Attempt to select `stage(alternate)` then ordinary `publish(alternate, previousMain, …, false, 0)` with requested factors `3` and `−2`, under the public labels `stage_alternate → publish_alternate_expected_3` and `stage_alternate → publish_alternate_expected_minus_2`. Select the actual `sourceStep` calls: OLD stage `154:5`, publish `159:5`; NEW stage `160:5`, publish `166:5`. Observe `event.receipt`. OLD's factorless publish would have to correspond to both labels. The release need not represent this argument mapping in a review format: request bindings at the stated occurrences to exercise rejection. Do not replace call binding with matching the successor `event` report, fixing arbitrary local choices, or rewriting the scheduler.

Expect **incomplete**, with a side and parse diagnostic, no established outcome sets and no deltas. The pinned Quint 0.33.1 parser rejects `observation` on OLD. This covers only parser failure. The original `step` also calls named routing actions, whose bodies are outside the current scheduler contract. The [archived native DML checks][dml-record] used Quint 0.34.0 and establish the expected sets for their original review scope; they do not establish that the current runtime can review those commits.

## 4. Git, exploration, and report failures

- **Transitive import-only change and dirty snapshots.** In a `refactor` child, change `workflow.qnt` to `import bridge.* from "./bridge"`. Add `bridge.qnt` defining `module bridge` with `import marks.* from "./marks"` and `export marks.*`. Use this commit as OLD. In its child (NEW), change only the `record` body in `marks.qnt` to `x' = destination + 1`. Assert identical `workflow.qnt` and `bridge.qnt` blob IDs on both sides. For the review from §1, with `marks::record` now resolved through two imports, both singleton histories change `{3}` → `{4}`. Repeat with unrelated HEAD (`changed`), invalid saved versions of all three files, and a different invalid `marks.qnt` staged in the index; keep the requested committed IDs fixed. Require the same results, provenance, and ordered witnesses. Verify HEAD/ref, index, and saved file bytes are unchanged by invocation. Repeat with a Git replacement ref mapping the generated OLD commit to its NEW child; the comparison must still use the exact original blobs. Also rerun the consensus pair with both its saved model files invalid in a disposable checkout.
- **Fail closed on unavailable source.** In separate `refactor` children, delete `marks.qnt`, delete `workflow.qnt`, or append `@` to the committed `marks.qnt`. In each case supply a valid copy of the affected file in the index and working tree after committing the defect. Compare each child against `refactor` in both directions. Also substitute a known nonexistent commit/ref for a requested side. Require incomplete with the failing side and path or revision; never fall back to HEAD, index, worktree, or the opposite snapshot. Also reject non-snapshot dependencies in separate `refactor` children: replace the import path with an absolute path to a valid copy of `marks.qnt` or with `../marks` and keep the valid copy outside the repository root; replace `marks.qnt` with a symlink to a committed regular copy `real-marks.qnt`; or change the import to `./vendor/marks` with `vendor` a gitlink to the `refactor` commit and a valid checkout there. None is an eligible regular blob at the imported path in that snapshot.
- **Observation fails after a valid execution.** Use `old` → `changed` with exactly `[beta]`, retaining the valid bindings but selecting `if (x == 4) List(3).nth(x) else x` (out of bounds at NEW's reachable observation). Check that the pure observation typechecks independently and that the failing branch is exercised, or inject the equivalent evaluator fault if the observation form is outside the chosen evaluator surface. OLD's producing `3` is not a removal: NEW's set is **unknown**, not empty. Report incomplete with observation evaluation as the cause.
- **Unfinished search and evidence.** Fail the explorer before closure (unavailable backend, or an injected interruption/resource failure after one candidate was found). In the changed consensus comparison, interrupt NEW's `[receive_round_1]` after any first candidate but before NEW's closure. Even if OLD has closed, the unresolved history cannot produce a delta. Also reject missing or malformed required witness evidence rather than treating it as a valid trace. Use the implementation's own test harness or a controllable backend for faults; no public fault-injection flag is required. Unresolved histories have no deltas. An overall incomplete result may withhold all deltas, or retain only those of separately closed histories with valid evidence.
- **Explicit bound, if offered.** In the changed consensus review, request at most two native transitions: neither history completes on either side. At three, the first row has its full expected sets and changes, the second does not complete within the bound. These are completed **bounded** reviews, with the bound reported and `init` not counted. A timeout or budget exhaustion inside the same declared scope is instead **incomplete**. Neither warrants equivalence beyond the reported scope.

## 5. Cross-cutting report assertions

Verify both terminal and versioned machine-readable output. They must agree on the resolved snapshots, selected instance, bindings and history/observation scope, limits, search status, and actual changes. The structured report must let the test distinguish closed empty sets, absence, disabled steps, and unresolved results without scraping display strings. Require a replayable producing witness for each delta, identifiable by revision, scenario, history, outcome and ordered native steps with source provenance for public calls. Distinguish exhaustive closure for the exact selection from an explicit bound or an incomplete run. Check shortest public histories first, stable tie and witness order across fresh invocations, and factual addition/removal labels with no `Findings` column. Do not require identical whitespace, generated-path strings, or state counts across backends. Passing these cases supports the stated release slice, not equivalence on other observations, histories, or Quint models.

[maker]: https://github.com/micha/git-quint-diff/blob/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/experiments/source_binding/make_fixture.py
[fixtures]: https://github.com/micha/git-quint-diff/tree/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/experiments/source_binding/fixtures
[site-oracle]: https://github.com/micha/git-quint-diff/blob/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/experiments/source_binding/native_oracle.py
[site-controls]: https://github.com/micha/git-quint-diff/blob/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/experiments/source_binding/test_native_oracle.py
[consensus-covers]: https://github.com/micha/git-quint-diff/blob/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/experiments/consensus/native_oracle.qnt
[consensus-script]: https://github.com/micha/git-quint-diff/blob/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/experiments/consensus/native-oracle.sh
[consensus-projection]: https://github.com/micha/git-quint-diff/blob/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/experiments/consensus/projection_oracle.py
[dml-record]: https://github.com/micha/git-quint-diff/blob/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/docs/design-spiral.md#experiment-7-source-bindings-under-nondeterministic-arguments
