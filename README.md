# git-quint-diff

Review what a change to a [Quint](https://quint.sh/) specification **adds or removes from its behavior**, not just what changed in the source. This is a standalone CLI project for terminal and CI use. A future `:QuintDiff` in [nvim-quint-viewer](https://github.com/micha/nvim-quint-viewer) can consume the same results.

**Status: design spiral, not the production implementation.** This bounded prototype compares two committed Git snapshots using a finite Quint review adapter. We are using it to learn from real reviews before archiving this work and starting a fresh implementation. Prototype flags, adapters, and JSON are not commitments for that implementation. See the [experiment log and next questions](docs/design-spiral.md).

## What a review looks like

Suppose standard approval used to require a ticket and now also requires training. Start both revisions from the `new_user` scenario: an untrained member with no ticket or admin exception. Compare the same public action history in both revisions and observe standard approval at the end:

| Initial scenario | Public action history | OLD | NEW |
| --- | --- | --- | --- |
| `new_user` | `obtain_ticket` | Approved | Denied |
| `new_user` | `obtain_ticket → obtain_training` | No matching trace (`obtain_training` did not exist) | Approved |

The ticket-only route to approval was removed; a ticket-plus-training route was added. A missing trace is not a denial or an execution error. Each row should have replayable evidence, with the shortest examples first. The CLI is deterministic and does not use LLMs at any stage, including when generating reports.

## Try the prototype

From this checkout, run `nix develop`. In that shell, put this checkout on `PATH`, then switch to a repository whose two revisions both contain a [review adapter](docs/prototype.md):

```sh
export PATH="$PWD:$PATH" # while still in the git-quint-diff checkout
cd /path/to/model-repo
git quint-diff --model models/review.qnt --scenario new_user \
  --action obtain_ticket --action obtain_training --max-depth 2 HEAD^ HEAD
```

Add `--json` for versioned output. The prototype always reports a depth bound; it does not claim equivalence beyond that bound. See [prototype usage and limits](docs/prototype.md).

## Proposed Git syntax

```sh
git quint-diff                   # index → saved working tree
git quint-diff HEAD              # HEAD → saved working tree
git quint-diff v1 v2             # v1 → v2
git quint-diff main...feature    # merge base → feature
```

Git selects the snapshots; review options select the model, starting scenario, and public actions. The prototype takes those options explicitly and supports only the two-revision form above. Each side resolves its own imports from its own snapshot, so an unchanged entrypoint can still have different behavior. This is a Git subcommand, not a per-file `git diff` driver. Ordinary `git diff` stays as it is.

The terminal view will label added (`+`) and removed (`−`) outcomes directly, with no `Findings` column. Versioned JSON will carry the same changes and search scope for automation. If exploration stops at a bound, the output will state the bound rather than imply equivalence. See the [comparison design and acceptance plan](docs/comparison-contract.md) for details.

## Develop

Run `nix develop` for Git, Quint, Node.js, Python, and Java, with the Apalache distribution Quint uses to run TLC pinned in the shell. See the [Quint model and verification record](spec/README.md) for the checked fixtures and bounds. Run `nix develop --command python3 -B tests/replay.py -v` to replay the cases against the CLI on temporary Git repositories. See [AGENTS.md](AGENTS.md) for the comparison contract.
