# Pinned upstream consensus fixture

These are the unchanged `ConsensusAlg.qnt` and `KSetAgreementConsensus.qnt` blobs from [upstream Quint](https://github.com/quint-co/quint), under its [Apache 2.0 license](LICENSE). The sources credit Tatjana Kirda, Josef Widder and Gabriela Moreira, Informal Systems, 2024–2025. The fixtures are the commits `883cc2c579bd11954129d207899790e80fb8c91e` (OLD) and `35df73a703259890303659e421f79016897993b3` (NEW, its child), at `examples/classic/distributed/ConsensusAlgorithm`.

`consensus_fixture.py` reconstructs an offline shallow partial clone with these **exact** commit IDs. The text commit objects and `git ls-tree` listings carry the exact path from each commit to the two blobs. Unrelated files and trees are promised but unavailable, as is older history beyond OLD. Git checks the reconstructed objects; the fixture builder also verifies both commit IDs and the committed source bytes before tests use them. The index and saved files contain only the two selected sources. No tarball of the upstream project or network access is needed during testing.

To reproduce these inputs from an upstream clone, from the project root (set `upstream` to the path to that clone):

```sh
fixture=release-tests/fixtures/consensus
model=examples/classic/distributed/ConsensusAlgorithm
for side in old new; do
  case $side in
    old) rev=883cc2c579bd11954129d207899790e80fb8c91e ;;
    new) rev=35df73a703259890303659e421f79016897993b3 ;;
  esac
  mkdir -p "$fixture/$side/trees"
  git -C "$upstream" --no-replace-objects cat-file commit "$rev" > "$fixture/$side/commit.txt"
  git -C "$upstream" --no-replace-objects ls-tree "$rev" > "$fixture/$side/trees/root.txt"
  for path in examples examples/classic examples/classic/distributed "$model"; do
    git -C "$upstream" --no-replace-objects ls-tree "$rev:$path" > "$fixture/$side/trees/${path##*/}.txt"
  done
  for file in ConsensusAlg.qnt KSetAgreementConsensus.qnt; do
    git -C "$upstream" --no-replace-objects cat-file blob "$rev:$model/$file" > "$fixture/$side/$file"
  done
done
git -C "$upstream" --no-replace-objects cat-file blob 883cc2c579bd11954129d207899790e80fb8c91e:LICENSE > "$fixture/LICENSE"
```
