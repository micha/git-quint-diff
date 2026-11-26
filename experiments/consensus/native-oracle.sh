#!/usr/bin/env bash
# Run: nix develop --command bash experiments/consensus/native-oracle.sh /path/to/quint-checkout
set -euo pipefail
export LC_ALL=C NO_COLOR=1

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 QUINT_CHECKOUT [MONITOR_REPORT.json]" >&2
  exit 2
fi
if [[ $(quint --version) != 0.33.1 ]]; then
  echo 'Run with Quint 0.33.1 from nix develop.' >&2
  exit 2
fi

checkout=$1
old=883cc2c579bd11954129d207899790e80fb8c91e
new=35df73a703259890303659e421f79016897993b3
model_dir=examples/classic/distributed/ConsensusAlgorithm
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
for side in old new; do
  mkdir "$scratch/$side"
  for path in KSetAgreementConsensus.qnt ConsensusAlg.qnt; do
    git --no-replace-objects -C "$checkout" cat-file blob "${!side}:$model_dir/$path" > "$scratch/$side/$path"
  done
  cp -- "$script_dir/native_oracle.qnt" "$scratch/$side/"
done
printf '%s\n' '{"workers":"1","maxHeap":"-Xmx1G"}' > "$scratch/tlc.json"

verify() {
  timeout 120 quint verify "../$side/native_oracle.qnt" --backend tlc \
    --init init --step step --apalache-version 0.62.4 --tlc-config ../tlc.json \
    --server-endpoint "${CONSENSUS_ORACLE_ENDPOINT:-localhost:19854}" \
    --verbosity 3 "$@" > verify.log 2>&1
}

fail() {
  printf 'Unexpected TLC result for %s:\n' "$name" >&2
  tee /dev/stderr < verify.log >/dev/null
  exit 1
}

stats() {
  grep -E '^[0-9]+ states generated,|^The depth' verify.log
}

cover() (
  name=$1 side=$2 kind=$3 property=$4 expected=$5
  mkdir "$scratch/$name"
  cd "$scratch/$name"
  if verify "--$kind" "$property"; then fail; fi
  if [[ $kind == invariant ]]; then
    grep -Fxq 'Error: Invariant q_inv is violated.' verify.log || fail
  else
    grep -Fxq "Error: Action property $property is violated." verify.log || fail
  fi
  grep -Fxq 'error: found a counterexample' verify.log || fail

  # The invariant only checks the final state. Confirm the trace has the
  # expected round/stage sequence, including all original administrative steps.
  sequence=$(awk '
    $2 ~ /^native_oracle_KSetAgreementConsensus_stage$/ {
      stage = $4; sub(/^\[/, "", stage)
    }
    $2 ~ /^native_oracle_KSetAgreementConsensus_round$/ { round = $4 }
    /^$/ && stage != "" && round != "" {
      printf "%s%s:%s", sep, round, stage
      sep = " "; stage = ""; round = ""
    }
  ' verify.log)
  [[ $sequence == "$expected" ]] || fail
  printf '%s: %s\n' "$name" "$sequence"
  stats
  if [[ ${CONSENSUS_SHOW_TLC_TRACE:-0} == 1 ]]; then
    awk '/^State 1:/ { trace=1 } /^[0-9]+ states generated,/ { trace=0 } trace' verify.log
  fi
)

closure() (
  side=$1 name=$side-closure
  mkdir "$scratch/$name"
  cd "$scratch/$name"
  verify --invariant "${side}Bounds" --temporal sameEffect || fail
  grep -Fxq 'Model checking completed. No error has been found.' verify.log || fail
  grep -Eq '^[0-9]+ states generated, [0-9]+ distinct states found, 0 states left on queue\.$' verify.log || fail
  printf '%s: outcome bounds and helper overlap hold on the full original scheduler\n' "$name"
  stats
)

round1='1:Starting 1:Sending 1:Receiving 1:Computing'
round2="$round1 2:Starting 2:Sending 2:Receiving 2:Computing"
cover old-first-0 old invariant neverDeliveredAll "$round1"
cover new-first-0 new invariant neverDeliveredAll "$round1"
cover new-first-1 new invariant neverOmittedOne "$round1"
cover new-first-2 new invariant neverOmittedBoth "$round1"
cover old-second-0 old invariant neverSecondReceive "$round2"
cover new-second-0 new invariant neverSecondReceive "$round2"
closure old
closure new
cover old-helper-overlap old temporal disjoint "$round1"
cover new-helper-overlap new temporal disjoint "$round1"
if [[ $# == 2 ]]; then
  python3 -B "$script_dir/replay-native.py" "$scratch" "$2"
fi
