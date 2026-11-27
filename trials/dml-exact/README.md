# Exact DML compatibility trial

This opt-in trial is not part of the release or installed command. It runs a
scratch copy of the current CLI with just its Quint version check and displayed
backend version changed to 0.34.0. It leaves the shipped 0.33.1 pins, translator,
Apalache/TLC version, and historical DML blobs untouched. Both the trial CLI
and the native oracle use the stock untrimmed JAR from `nix develop`, not the
repacked JAR shipped in installed builds. The npm dependency lock is only for
this trial; `npm ci` verifies the package tarballs against it.

From the root of this checkout, with both DML commits already available locally:

```sh
export DML_REPO=/absolute/path/to/dml
trial=$(mktemp -d /tmp/dml-exact.XXXXXX)
mkdir "$trial/npm"
cp trials/dml-exact/package*.json "$trial/npm/"
nix develop --command npm --prefix "$trial/npm" ci --ignore-scripts --no-audit --no-fund
nix develop --offline --command python3 -B trials/dml-exact/run.py \
  "$DML_REPO" "$trial/npm" "$trial/results" --graphs
```

Delete the scratch directory when done. Installing dependencies may fetch npm
or Nix build inputs; the trial does not fetch missing Git objects. Use a scratch
path without spaces for the native Quint compiler. Omit `--graphs` to run only
the four CLI comparisons. The optional full check takes minutes and needs at
least 8 GiB of free scratch disk and several GiB of RAM. It separately compiles
original `init`/`step` with the Quint CLI and runs TLC outside the review's
60-second/32-MiB graph limits. It replays both delta witnesses against the
original TLC graph and compares outgoing successors from **each** reachable
tracked state before restricting any history. Missing closure or replay
failure makes the trial fail. The JSON reports and generated evidence stay in
the scratch directory.

See the [design record](../../docs/design-spiral.md#exact-upstream-dml-with-an-isolated-quint-pin)
for the selected requests, expected outcomes, and verification limits.
