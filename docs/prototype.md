# Bounded CLI prototype

Run `git quint-diff -h` for the command syntax. The prototype takes a repository-relative `.qnt` entrypoint, one scenario, at least one public action label, an explicit maximum history length, and two commit refs. It does not infer any of those selections. Both revisions must contain the chosen entrypoint; transitive imports are read from regular Git blobs in the same revision. Absolute paths, imports outside the repository, symlinks, and submodule contents are unsupported. The index and working tree are not read for model source.

## Review adapter

The entrypoint must define a module named `review`. It may import other modules. For example:

```quint
module review {
  pure val publicActions: Set[str] = Set("obtain_ticket")
  pure def initialStates(scenario: str): Set[bool] =
    if (scenario == "new_user") Set(false) else Set()
  pure def successors(hasTicket: bool, label: str): Set[bool] =
    if (label == "obtain_ticket" and not(hasTicket)) Set(true) else Set()
  pure def observe(hasTicket: bool): str =
    if (hasTicket) "approved" else "denied"
}
```

Both revisions must provide initial states for the selected scenario. An action can be absent on one side; it need not occur in both `publicActions` sets. A declared action returns its **entire** finite successor set, including an empty set when disabled. Represent nondeterministic choices by multiple successors, not a call to `oneOf`. Each side can use its own state type. End-of-history observations are strings in this version. The pure adapter is the behavior being compared: the CLI does not automatically extract transitions from arbitrary Quint `action` definitions or verify that an adapter matches another model.

## Evidence and limits

The terminal view shows changed histories and concrete producing traces without a `Findings` column. `--json` emits `schema_version: 1` with the resolved commits and review scope. Its `histories` array includes every completed history, including the empty history, in shortest-first order and lexicographically within each length. Each row gives both outcome sets, an optional first blocked step per side (one-based), the added and removed labels, and one producing state sequence per change. State values are JSON booleans, strings, arrays (lists), or objects (records); other values use `#bigint`, `#tup`, `#set`, `#map`, or `#variant` tags.

- **Exit 0 (`bounded`):** all histories through the requested depth were checked, with or without changes. This says nothing about longer histories.
- **Exit 1 (`incomplete`):** the requested review could not finish. For example, an import could not be loaded, the adapter was unsupported, or an evaluation failed. The report gives an error and retains only histories already completed on both sides; it does not treat the failing history as an empty outcome set.
- **Exit 2:** invalid arguments or a requested depth/history count outside the prototype limits; no review was run.

Depth is 0–100 and the requested history count is capped at 10,000. The prototype also caps individual source blobs at 8 MiB and returned sets and frontiers at 10,000 elements. These checks do not bound all intermediate work within Quint. Use finite adapters with tractable computations. The prototype uses the evaluator from the Quint version pinned by `nix develop`; there is no simulation or random sampling.
