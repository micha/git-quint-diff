# Source-first trial: an upstream consensus change

Can a reviewer install from the candidate source, review a real change, and independently replay the evidence? This path needs Git 2.43+, Nix with `nix-command` and `flakes` enabled, and network access for build inputs and the explicit upstream Git fetch. You do not need Node.js, Java, or Quint on your `PATH`. No project wheel or binary cache is needed.

## 1. Install in a disposable profile

Use the candidate source supplied by the maintainer: a checkout at the stated candidate revision, or an unpacked source archive from that revision. The public default branch need not contain the candidate. The archive must include `flake.nix` and `flake.lock`; it does not need `.git` or the `prototype-handoff` tag. For example, the maintainer can make a source-only archive with `git archive --format=tar --output=/tmp/git-quint-diff-source.tar HEAD` from the candidate checkout.

Start in the candidate source directory and run these blocks in the same shell:

```sh
source_dir=$PWD
scratch=$(mktemp -d)
nix profile add --profile "$scratch/profile" .
export PATH="$scratch/profile/bin:$PATH"
git-quint-diff --help
```

## 2. Review two real Quint commits

The [ready-to-run review](consensus-review.json) selects the original imported scheduler and two exact histories. It counts process slots, including the crashed slot, whose `S` contains the empty set immediately after the final receive. This is a count of no-delivery markers, not a consensus decision. The [scope and source locations](first-release-acceptance.md#2-imported-consensus-scheduler) explain the selection.

Fetch the commits before reviewing; no checkout is needed. The installed command does not fetch missing objects during review.

```sh
old=883cc2c579bd11954129d207899790e80fb8c91e
new=35df73a703259890303659e421f79016897993b3
git init -q --object-format=sha1 "$scratch/model"
git -C "$scratch/model" fetch --no-tags --depth=1 https://github.com/quint-co/quint.git "$old" "$new"
cd "$scratch/model"
review="$source_dir/docs/consensus-review.json"
git quint-diff --review "$review" "$old" "$old"
git quint-diff --review "$review" "$old" "$new"
git quint-diff --review "$review" --json "$old" "$new" > "$scratch/forward.json"
```

The self-comparison should show `{0}` on both sides for both histories. The forward comparison should report:

| Exact public history | OLD | NEW | Delta |
| --- | --- | --- | --- |
| `receive_round_1` | `{0}` | `{0,1,2}` | `+ 1`, `+ 2` |
| `receive_round_1 → receive_round_2` | `{0}` | `{0}` | None |

Both results should be `exhaustive` **for those histories and that instance**, with zero queued states. If either run reports `incomplete`, record the failing command and diagnostic rather than treating it as no change.

## 3. Replay the reported additions independently

Use the development shell only for this check. The oracle reads the NEW blobs directly from the fetched repository and runs pinned Quint/TLC on the original `init` and `step`, with only a constant-instance wrapper. It does not compile or run the comparator's scheduler instrumentation. It checks all seven original variables at initialization and each reported edge, verifies the source site and round from native routing, and recomputes the final observation.

```sh
nix develop "$source_dir" --command python3 -B "$source_dir/release-tests/replay-consensus-witnesses.py" \
  "$scratch/model" "$scratch/forward.json"
```

Expect `Replayed +1` and `Replayed +2`, each through three original transitions after initialization. This replay checks presence in NEW, not absence in OLD or correctness beyond the selected scope. The scratch directory contains the JSON report and disposable Nix profile. If you no longer need them, leave the model directory (`cd "$source_dir"`) and remove `"$scratch"`.
