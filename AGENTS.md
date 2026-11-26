# Agent guide

Read [README.md](README.md) for the proposed CLI and approval example. This repository owns snapshot loading, model exploration, comparison, and terminal/JSON output. It does not depend on Neovim or on a checkout of `nvim-quint-viewer`. Do not implement editor integration here. No implementation language or public configuration format has been selected yet.

## Comparison contract

- Git selects OLD and NEW snapshots for the whole repository. Resolve each model's entrypoint and transitive imports inside that side's snapshot. Do not check out another branch or let an OLD import read working-tree source. The saved working tree is not an editor buffer.
- Compare explicitly selected scenarios, public action histories, and observable outcomes. For each history, compare the **sets** of reachable outcomes from OLD and NEW. `NEW − OLD` is added behavior; `OLD − NEW` is removed. Arbitrary paired executions cannot establish a difference in nondeterministic models.
- A missing action, a declared action that cannot take a step, and an observed denial are distinct. Report absence of a matching execution only when the search supports it. Never turn an evaluation failure, unsupported model, or incomplete search into an empty outcome set.
- Use deterministic traversal and stable witness ordering, with shortest histories first. No LLM or random simulation is required. Expose the observation and search scope in both terminal and JSON output; distinguish exhaustive, bounded, and incomplete results. JSON will be a versioned interface, not a serialization of display strings.

## Start here: Quint first

1. Specify the comparison before writing the CLI. Start with a finite approval model in which OLD can approve after `obtain_ticket` and NEW requires `obtain_training` too. Model the expected removed and added witnesses and verify the rules with Quint/TLC in the pinned `nix develop` shell. Record the checked state space and bounds. Include a nondeterministic model compared with itself and a case where one of two possible outcomes is removed.
2. Implement the smallest standalone `git-quint-diff` CLI that can exercise those cases on real Git snapshots. Replay histories against the real command, check the witness content and scope against the model, and include a negative control (for example, a false difference made by picking one outcome per side).
3. Add a fixture where only an import changes and the entrypoint is untouched. Confirm OLD and NEW are independent and that rerunning the comparison produces the same witness order. Keep generated results untracked.

Verification checks the model; fixture replay checks the CLI on the histories exercised. Neither is a claim about unchecked models or histories.
