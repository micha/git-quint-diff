# Release candidate packaging

The Nix package and the platform wheels run the same source-bound command. Nix uses pinned store dependencies, not a wheel. The wheel includes Node.js, an OpenJDK distribution, Quint, and an Apalache/TLC JAR with the unused native solver payloads removed. Nix uses the same repacked JAR; the dev shell keeps the original upstream distribution for independent replay. The launchers select their own runtimes by absolute paths. Neither package supplies Git: use **Git 2.43 or newer** on your `PATH`. No model objects or backend dependencies are fetched during review. A partial clone must already have every required commit, tree and source blob for both sides.

The initial wheel targets are `manylinux_2_28_x86_64` (glibc 2.28+, not musl; Linux 4.18+ or distro equivalent) and `macosx_13_0_arm64` (macOS 13.5+, native arm64 Python). These are build targets, not a claim about an untested host. The flake exposes packages for Linux x86-64 and arm64 and macOS x86-64 and arm64; the RC matrix exercises Linux x86-64 and macOS arm64. The `aarch64-linux` flake package was also exercised locally. A wheel is several hundred MiB and needs room to unpack both runtimes.

## Build and install locally

Run the following from the source checkout. The wheel build needs Python 3.12+ and network access to obtain the pinned inputs, but the installed wheel needs only a supported host, Python 3.8+, and Git. Nix needs flakes and the `nix-command` feature enabled. For these checks, use disposable install locations:

```sh
repo=$PWD
scratch=$(mktemp -d)
caller_git=$(command -v git)
nix profile add --profile "$scratch/profile" .

# On a matching native host; use macosx_13_0_arm64 on Apple Silicon instead.
python3 -B packaging/build-wheel.py --platform manylinux_2_28_x86_64 --out-dir "$scratch/dist"
export PIPX_HOME="$scratch/pipx" PIPX_BIN_DIR="$scratch/pipx-bin"
# With pipx 1.16.6, also skip its shared-pip maintenance for an offline local install.
PIP_NO_INDEX=1 pipx install --skip-maintenance "$scratch"/dist/*.whl
```

Build into a fresh output directory to avoid mixing artifacts from different candidates. The TLA+ Tools companion is a source-only `.tar` pinned to the revision that reproduces the embedded TLC; see the [rebuild recipe](../packaging/TLC-SOURCE.md). Wheel builds also emit `jvm-priority-sources.tar`. Obtain the identical archive from the flake with `nix build .#jvm-source-companions --out-link "$scratch/jvm-sources"`. Both packages include the [JVM notice and source guide](../packaging/jvm-legal/JVM-SOURCES.md), which locates and identifies the matching sources. The wheel and companions are candidate artifacts, not cleared for redistribution.

Once installed, put the selected `bin` directory on `PATH` and run `git quint-diff --review review.json OLD NEW` in a model repository. `git-quint-diff --help` prints usage. See [review syntax, JSON v1, and exit statuses](source-review.md).

## Run the installed acceptance gate

The harness needs the development shell for its **independent** Quint/TLC oracle, but the installed process gets a fresh HOME and a minimal `PATH` containing Git and the installed subcommand, without system Node.js, Java, or Quint. It runs in disposable repositories, rejects caller attempts to redirect the pinned backend, and checks that a missing promised blob is not fetched. Fault-injection and internal scheduler-erasure tests still run in the development suite rather than swapping out components of the installed packages.

```sh
git init -q "$scratch/dml"
git -C "$scratch/dml" fetch --depth=1 --no-tags https://github.com/micha/dml.git \
  819ac9d9c496bf652ea85af12b3369844df2b1e4 c540078318bf52313a33d856c7825d6b09566b17
mkdir "$scratch/acceptance"
cd "$scratch/acceptance"
for bin in "$scratch/profile/bin" "$PIPX_BIN_DIR"; do
  nix develop "$repo" --command python3 -B "$repo/release-tests/check-installed.py" \
    "$bin" --dml-repo "$scratch/dml" --git "$caller_git"
done
```

CI runs this gate on both target hosts, including for pushes to `rc-validation/**`. It also checks the JVM notice files in both installations and the wheel ZIP and verifies both builds' source-companion digest. CI saves the SHA-256 manifest, not the binaries or a GitHub Release. The project's [MIT license](../LICENSE) is included in both packages. Before publishing an RC, require both native jobs to pass on the exact commit to be tagged and clear the [bundled dependency redistribution checks](../packaging/REDISTRIBUTION.md). Any rebuilt wheel and source companions must match the tested manifest or be validated as new artifacts. Keep the prototype archive and test fixtures out of the shipped runtime.
