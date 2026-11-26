# Agent guide

Read [README.md](README.md) for current usage and [docs/design-spiral.md](docs/design-spiral.md) for the milestone and archive. This repository owns snapshot loading, model exploration, comparison, and terminal/JSON output. It does not depend on Neovim or `nvim-quint-viewer`. Do not implement editor integration here.

## Design spiral

Start each iteration with a question. Record exact revisions, predicted behavior, actual checks, and limitations before expanding the supported scope. Keep the [scheduler contract](docs/supported-scheduler.md) and [black-box acceptance cases](docs/first-release-acceptance.md) independent of the runtime. The prototype at `prototype-handoff` is evidence, not a runtime dependency. Do not copy its flags, internal drivers, or model-specific compiler workarounds into production.

## Comparison contract

- Git selects OLD and NEW snapshots for the whole repository. Resolve each entrypoint and all transitive imports in its own snapshot. Do not check out another revision or fall back to HEAD, working tree, index, replacement object, symlink, or gitlink.
- Preserve original initialization, guards, choices and updates. Bind explicit public labels to resolved source occurrences on each side; equal effects do not identify a call. Hide only explicitly selected branches.
- Compare **sets** of outcomes for the same scenario and exact public history. `NEW − OLD` is added behavior; `OLD − NEW` is removed. Do not merge states by observation or infer absence from paired runs. Disablement, explicit absence, and observed denial are distinct.
- Use deterministic traversal and stable witness ordering, shortest public histories first. Never manufacture a delta from an unsupported model, evaluation error, or unfinished search. Expose scope in both terminal and versioned JSON. Distinguish exhaustive, bounded (if offered), and incomplete results. No LLMs, random simulation, or `Findings` column.

Test the new executable in disposable Git repositories and independently check producing witnesses. If tracking call labels in extra state, use a separate regression which checks unfiltered scheduler projection **from each reachable tracked state**, and separately verify label identity. Verification checks the model; fixture replay checks the CLI only on the histories exercised. Keep generated output untracked.
