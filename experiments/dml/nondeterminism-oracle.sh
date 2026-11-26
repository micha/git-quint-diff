#!/usr/bin/env bash
# Independent check: use the original DML init and step, without a history monitor.
# Run: nix develop --command bash experiments/dml/nondeterminism-oracle.sh ../dml /absolute/path/to/quint-0.34.0
set -euo pipefail
export LC_ALL=C NO_COLOR=1

if [[ $# != 2 || $2 != /* ]]; then
  echo "Usage: $0 DML_CHECKOUT /absolute/path/to/quint-0.34.0" >&2
  exit 2
fi
dml=$1
quint=$2
if [[ $("$quint" --version) != 0.34.0 ]]; then
  echo 'The exact snapshots require Quint 0.34.0 (not the shell’s 0.33.1).' >&2
  exit 2
fi

old=819ac9d9c496bf652ea85af12b3369844df2b1e4
new=c540078318bf52313a33d856c7825d6b09566b17
model=tests/recorded_return_design.qnt
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/old" "$scratch/new"
git --no-replace-objects -C "$dml" cat-file blob "$old:$model" > "$scratch/old/recorded_return_design.qnt"
git --no-replace-objects -C "$dml" cat-file blob "$new:$model" > "$scratch/new/recorded_return_design.qnt"
printf '%s\n' '{"workers":"1","maxHeap":"-Xmx1G"}' > "$scratch/tlc.json"

# Both snapshots record these arguments. OLD has no expectedFactor argument,
# so each OLD witness applies to both public requests.
request='event.command == "publish" and event.wanted == alternate and event.expectedMain == previousMain and not(event.aliasesMain) and event.failAt == 0'
staged="$request and event.before.returned == alternate and event.before.producerPin == producer"
current="$staged and event.before.main == previousMain and event.before.objects == initialSource.objects.union(closure(alternate))"
stale="$staged and event.before.main == competingMain and event.before.objects == initialSource.objects.union(closure(alternate)).union(closure(competingMain))"
accept='event.receipt == alternate and source.main == alternate and source.returned == absent'
reject='event.receipt == absent and source == event.before'
matching='event.expectedFactor == alternateFactor'
mismatch='event.expectedFactor == plannedFactor'

verify() {
  if ! timeout 120 "$quint" verify "../$side/recorded_return_design.qnt" --backend tlc \
    --init init --step step --apalache-version 0.62.4 --tlc-config ../tlc.json \
    --server-endpoint "${DML_TLC_ENDPOINT:-localhost:18822}" \
    --verbosity 3 "$@" > verify.log 2>&1; then
    tee /dev/stderr < verify.log >/dev/null
    exit 1
  fi
}

stats() {
  grep -E 'states generated,|^The depth' verify.log
}

cover() (
  name=$1 side=$2 target=$3 receipt=$4 transitions=$5
  mkdir "$scratch/$name"
  cd "$scratch/$name"
  verify --observation "$target"
  # The target only inspects the final state; confirm that the returned original
  # scheduler trace realizes the requested public history. No order is imposed on
  # report-free transitions, nor do we search for them in a separate wrapper.
  trace=$(awk '/^State 1:/ { trace=1 } /^[0-9]+ states generated,/ { trace=0 } trace' verify.log)
  reports=$(awk '
    /^State / { command=""; wanted="" }
    /command \|-> / { command=$NF; sub(/,$/, "", command) }
    /wanted \|-> / { wanted=$NF; sub(/,$/, "", wanted) }
    /receipt \|-> / && command != "\"\"" { receipt=$NF; sub(/,$/, "", receipt); print command, wanted, receipt }
  ' <<< "$trace")
  states=$(grep -Ec '^State [0-9]+:' <<< "$trace" || true)
  if ! grep -q '^\[observed\]' verify.log || [[ $states -ne $((transitions + 1)) ]] ||
    [[ $reports != $'"stage" 12 12\n"publish" 12 '"$receipt" ]]; then
    printf 'Unexpected TLC witness for %s:\n' "$name" >&2
    tee /dev/stderr < verify.log >/dev/null
    exit 1
  fi
  printf '%s: receipt %s, %s transitions including any report-free steps\n' "$name" "$receipt" "$((states - 1))"
  stats
  if [[ ${DML_SHOW_TLC_TRACE:-0} == 1 ]]; then
    printf '%s\n' "$trace"
  fi
)

check_invariant() (
  name=$1 side=$2 allowed=$3
  mkdir "$scratch/$name"
  cd "$scratch/$name"
  verify --invariant "($request) implies ($allowed)"
  if ! grep -q '^Model checking completed\. No error has been found\.$' verify.log ||
    ! grep -Eq '^[0-9]+ states generated, [0-9]+ distinct states found, 0 states left on queue\.$' verify.log; then
    printf 'TLC did not confirm exhaustive closure for %s:\n' "$name" >&2
    tee /dev/stderr < verify.log >/dev/null
    exit 1
  fi
  printf '%s: receipt invariant holds on the full original scheduler\n' "$name"
  stats
)

cover old-current old "$current and $accept" 12 4
cover old-stale old "$stale and $reject" 0 5
cover new-mismatch new "$current and $mismatch and $reject" 0 4
cover new-matching-current new "$current and $matching and $accept" 12 4
cover new-matching-stale new "$stale and $matching and $reject" 0 5

# These global upper bounds also apply to the subset of traces with the selected
# public histories. Together with the bounded witnesses they establish the sets.
check_invariant old-closure old 'event.receipt == absent or event.receipt == alternate'
check_invariant new-closure new "event.receipt == absent or ($matching and event.receipt == alternate)"
