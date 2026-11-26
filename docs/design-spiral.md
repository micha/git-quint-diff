# Design spiral

Start each iteration with a question. Record the actual inputs, prediction, checks, and limits before expanding what the CLI claims to support.

## Archive

`prototype-handoff` points to `064f97d4258c57a4dd83f8e27c65bb995dc38aa9`. It retains the pure-adapter CLI, verified Quint comparison model, exact fixtures, seven design experiments, and their oracle commands. See the [archived experiment record](https://github.com/micha/git-quint-diff/blob/064f97d4258c57a4dd83f8e27c65bb995dc38aa9/docs/design-spiral.md) or run locally:

```sh
git show prototype-handoff:docs/design-spiral.md
git show prototype-handoff:spec/README.md
```

To run an archived oracle, extract that tag into a scratch directory and use the pinned shell from the current checkout. The current CLI never invokes the archive. The release tests extract only the source-binding fixture and deterministic fixture maker at that commit.

## Fresh implementation: committed source-site comparison

**Question:** Can a standalone command pass the source-site and failure controls on committed blobs without the prototype's evaluator or drivers in the runtime path?

Use the three exact commits and independent source selectors in [acceptance §1](first-release-acceptance.md#1-source-binding-identical-effects-moved-sites-literal-changes). Select `[alpha]` and `[beta]`, from `init` at `x = 0`, allowing only preparation and reset as hidden steps; observe `x` immediately after the public call. Expect no delta on self-comparison or refactor. In `old → changed`, expect `beta` to change from `{3}` to `{4}` and `alpha` to remain `{3}`.

That is what the new executable reports. With those two histories, TLC closed each side at 9 generated, 7 distinct, 0 queued in the **history product** (including observation capture states). The witness on each side replayed `x = 0 → 1 → 3 or 4`, with the recovery site independently checked. The unchanged refactor outcomes alone would not detect a swap of the equal-effect calls; positions and resolved declarations were also checked independently.

### Design and verification

- The Git loader reads exact regular blobs and resolves imports in memory within each commit. No checkout or synthetic tree fallback. The test with an unchanged entrypoint and forwarding import got `{3}` → `{4}` on both labels even with an unrelated HEAD, invalid saved/staged sources, and a replacement ref.
- Quint resolves call occurrences on the original parsed model. After flattening, the backend gives whole alternatives separate definitions from their typed IR, with no modification to the committed scheduler or duplication of its guards in the tool. The public observation and history-prefix tracker are separate from those definitions. Apalache's converter runs offline; TLC explores the finite product of original states, history progress, and last source site. Capture edges read the observation only at exact endpoints and are never included in a native witness.
- A separate regression checks the whole unfiltered transition relation from every reachable tagged state against the original scheduler and hand-checked native fixture graphs. It rejects a tag-dependent edge loss that preserves the projected edge union. An independent site-identity check rejects an equal-effect swap that would preserve even the tagged edge union.
- Reachable evaluation errors, stale/ambiguous/conflicting selectors, unsupported local arguments, invalid blobs, and unavailable backend all failed closed. A fault after NEW had a candidate still produced no delta when closure acknowledgement or a required witness edge was lost. Empty histories, longer histories with hidden progress, denial, disabled calls, and deliberate absence were tested separately.

Reproduce with `nix develop --command python3 -B -m unittest discover -s release-tests -v` (17 tests passed). These are finite fixture checks and failure controls, not evidence for nested schedulers or for unchecked Quint operators. The [current user surface](source-review.md) is narrower than the [first-release contract](supported-scheduler.md).

## Next milestone: imported consensus scheduler

**Question:** Can the same source-bound runtime preserve an imported, nested scheduler and its nondeterminism without model-specific recognition?

Implement source resolution for the imported scheduler, instance constants, nested `if`/payload-free `match` action positions, and mutually exclusive pre-state scalar label predicates. Run [acceptance §2](first-release-acceptance.md#2-imported-consensus-scheduler) on the pinned upstream revisions. Run OLD self-comparison first; then require round one `{0}` → `{0,1,2}` and rounds one–two `{0}` → `{0}`. Replay witnesses through the unchanged scheduler with all seven original variables constrained, and independently check unfiltered erasure and label identity. Keep DML's locally bound arguments out of scope.
