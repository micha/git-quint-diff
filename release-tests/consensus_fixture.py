"""Materialize the two exact upstream snapshots from local fixture objects."""

from pathlib import Path
import subprocess


FIXTURE = Path(__file__).parent.resolve() / "fixtures/consensus"
COMMITS = {
    "old": "883cc2c579bd11954129d207899790e80fb8c91e",
    "new": "35df73a703259890303659e421f79016897993b3",
}
MODEL = Path("examples/classic/distributed/ConsensusAlgorithm")
SCHEDULER = (MODEL / "ConsensusAlg.qnt").as_posix()
ENTRYPOINT = (MODEL / "KSetAgreementConsensus.qnt").as_posix()


def git(repo, env, *args, data=None):
    result = subprocess.run(["git", "--no-replace-objects", *args], cwd=repo, env=env, input=data,
                            capture_output=True, timeout=30)
    if result.returncode:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr.decode()}")
    return result.stdout


def materialize(repo, env):
    repo.mkdir()
    env = env | {"GIT_NO_LAZY_FETCH": "1"}

    def run(*args, data=None):
        return git(repo, env, *args, data=data)

    # This is a shallow, offline partial clone. `mktree --missing` keeps the
    # unneeded siblings' original IDs instead of substituting synthetic trees.
    run("init", "--quiet", "--object-format=sha1", "--initial-branch=main")
    objects = set()
    for side, expected in COMMITS.items():
        directory = FIXTURE / side
        for path in (ENTRYPOINT, SCHEDULER):
            objects.add(run("hash-object", "-w", "--stdin", data=(directory / Path(path).name).read_bytes()).strip())
        for tree in sorted((directory / "trees").glob("*.txt")):
            objects.add(run("mktree", "--missing", data=tree.read_bytes()).strip())
        commit = run("hash-object", "-t", "commit", "-w", "--stdin", data=(directory / "commit.txt").read_bytes()).strip()
        if commit.decode() != expected:
            raise AssertionError(f"Unexpected fixture commit: {side} {commit!r}")
        objects.add(commit)
    # Git's promisor pack semantics allow missing unrelated objects while
    # retaining normal commit/tree traversal and byte-for-byte verification.
    run("config", "core.repositoryformatversion", "1")
    run("config", "extensions.partialClone", "upstream")
    run("config", "remote.upstream.promisor", "true")
    run("config", "remote.upstream.url", (repo / ".git/unavailable-upstream").as_posix())
    pack = run("pack-objects", "--stdout", data=b"\n".join(sorted(objects)) + b"\n")
    run("index-pack", "--stdin", "--promisor", data=pack)
    (repo / ".git/shallow").write_text(COMMITS["old"] + "\n", encoding="ascii")
    for side, commit in COMMITS.items():
        run("update-ref", f"refs/tags/{side}", commit)
    run("update-ref", "HEAD", COMMITS["new"])
    run("fsck", "--full", "--no-dangling")

    destination = repo / MODEL
    destination.mkdir(parents=True)
    for side, commit in COMMITS.items():
        for path in (ENTRYPOINT, SCHEDULER):
            blob = run("cat-file", "blob", f"{commit}:{path}")
            if blob != (FIXTURE / side / Path(path).name).read_bytes():
                raise AssertionError(f"Unexpected committed model bytes: {side} {path}")
            if side == "new":
                (repo / path).write_bytes(blob)
    run("add", "--", ENTRYPOINT, SCHEDULER)
