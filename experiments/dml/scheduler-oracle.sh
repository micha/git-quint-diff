#!/usr/bin/env bash
# Cover the selected publication histories using DML's original init and step.
# Run from this repo: nix develop --command bash experiments/dml/scheduler-oracle.sh ../dml /absolute/path/to/quint-0.34.0
set -euo pipefail

if [[ $# != 2 || $2 != /* ]]; then
  echo "Usage: $0 DML_CHECKOUT /absolute/path/to/quint-0.34.0" >&2
  exit 2
fi
dml=$1
quint=$2
if [[ $("$quint" --version) != 0.34.0 ]]; then
  echo 'The exact snapshots require Quint 0.34.0 for this check (not the shell’s 0.33.1).' >&2
  exit 2
fi

old=819ac9d9c496bf652ea85af12b3369844df2b1e4
new=c540078318bf52313a33d856c7825d6b09566b17
model=tests/recorded_return_design.qnt
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/old" "$scratch/new"
git -C "$dml" show "$old:$model" > "$scratch/old/recorded_return_design.qnt"
git -C "$dml" show "$new:$model" > "$scratch/new/recorded_return_design.qnt"
printf '%s\n' '{"workers":"1","maxHeap":"-Xmx1G"}' > "$scratch/tlc.json"

# Constrain the request and the exact staged source, not just the receipt.
common='event.command == "publish" and event.wanted == alternate and event.expectedMain == previousMain and not(event.aliasesMain) and event.failAt == 0 and event.before.main == previousMain and event.before.returned == alternate and event.before.producerPin == producer and event.before.objects == initialSource.objects.union(closure(alternate))'
accept='event.receipt == alternate and source.main == alternate and source.returned == absent and source.producerPin == event.before.producerPin and source.objects == event.before.objects'
reject='event.receipt == absent and source == event.before'

cover() (
  name=$1 side=$2 target=$3
  mkdir "$scratch/$name"
  cd "$scratch/$name"
  # This is a reachability query. TLC stops on a witness of the observation.
  if ! "$quint" verify "../$side/recorded_return_design.qnt" --backend tlc \
    --tlc-config ../tlc.json --server-endpoint "${DML_TLC_ENDPOINT:-localhost:18822}" \
    --verbosity 3 --observation "$target" > verify.log 2>&1; then
    tee /dev/stderr < verify.log >/dev/null
    exit 1
  fi
  # TLC prints the path including the initializer. The only FALSE → TRUE
  # returning transition is startReturn; the next empty command clears stage.
  commands=$(awk '/command \|-> / { sub(/^.*command \|-> /, ""); sub(/,$/, ""); print }' verify.log)
  phases=$(awk '/ returning = (TRUE|FALSE)$/ { print $NF }' verify.log)
  if ! grep -q '^\[observed\]' verify.log ||
    [[ $commands != $'""\n""\n"stage"\n""\n"publish"' ||
       $phases != $'FALSE\nTRUE\nTRUE\nTRUE\nTRUE' ]]; then
    printf 'Unexpected TLC witness for %s:\n' "$name" >&2
    tee /dev/stderr < verify.log >/dev/null
    exit 1
  fi
  printf '%s: observed after startReturn → stage → clear report → publish\n' "$name"
  grep -E 'states generated,|^The depth' verify.log
  if [[ ${DML_SHOW_TLC_TRACE:-0} == 1 ]]; then
    awk '/^State 1:/ { trace=1 } /^[0-9]+ states generated,/ { trace=0 } trace' verify.log
  fi
)

cover old-accept old "$common and $accept"
cover new-mismatch new "$common and event.expectedFactor == plannedFactor and $reject"
cover new-matching new "$common and event.expectedFactor == alternateFactor and $accept"
