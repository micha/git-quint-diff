# Platform payload audit: Node.js, npm, and OpenJDK

**Question:** Which files and notices do the host-specific inputs supply,
and what must still be checked against the actual release artifacts?

**Baseline:** `bd059bae71fd699b74388509bd6e4be0be78446c`, local Linux arm64
wheel SHA-256 `6bd3c29be263e26a6cab8b923acab2e1bf783100be63106d272ae68dafa17b0a`,
and the `aarch64-linux` default package from the locked Nixpkgs revision
`f1e5c356f35d07e7b71a6b5e6c9338e0b029e0c0`. Expect matching npm production
code, different Node/Java build inputs for Nix, and legal files that vary
with the linked image. The measurements below distinguish vendor inputs
from install artifacts. Keep the [publication hold](../packaging/REDISTRIBUTION.md#publication-hold).

## Wheel: exact payload checks

| Wheel platform | Node.js 24.22.3 vendor `bin/node` SHA-256 | Temurin 21.0.13.1+2 vendor legal files for the 19 selected modules | Wheel checked in this audit |
| --- | --- | ---: | --- |
| `manylinux_2_28_aarch64` (local test target) | `8f9c2a55879e9705cb285b6cdd649d95df642c6720f052cb30f300d2677da99f` | 73 | Yes |
| `manylinux_2_28_x86_64` | `a7ec1b37e6ff9d187e4198c5b6df9a4eb1c74dd31804fb3bac55cc4ceca1ac01` | 73 | No; vendor archive only |
| `macosx_13_0_arm64` | `ba7073582822078d8c90bca3facacc46690bc5366fab4b815aeef9148cd6e854` | 72 | No; vendor archive only |

- **Node.js.** All three archive hashes match [`payloads.json`](../packaging/payloads.json).
  Each archive's root `LICENSE` matches the official v24.22.3 source
  archive (SHA-256 `48ca3aa8a9b02133356922ef4fc80200e00598c80a4ef446f7c39a459222593d`,
  as listed in the vendor `SHASUMS256.txt`). The root notice is cumulative,
  but omits the separate MIT `deps/nbytes/LICENSE` with `Copyright (c)
  2024 Node.js`. Both Linux vendor executables define `nbytes::` symbols;
  the Darwin executable contains `nbytes` references and its build config
  also sets `node_shared_nbytes` to `false`. The Nix Node 24.22.1 binary
  defines `nbytes::` symbols too. The two pins now used by both installs
  match byte for byte at Node.js commits
  [e63cab0 (24.22.3)](https://github.com/nodejs/node/tree/e63cab040c09d43ceef8cb35508c40044614e906)
  and [ce7aaf1 (24.22.1)](https://github.com/nodejs/node/tree/ce7aaf1cee78b8cf0ce17364260535c418d3ed26):
  root `LICENSE` `5888dbb9a1d2b18f2c3e6c5f6af1b39de658372b402a0577b002777f14c62ace`,
  `deps/nbytes/LICENSE` `782ab5b8ae1540c1a2b102fdd00990ed268d4a3a98e90ad7fe724b489d7bb0f2`.
  The two Linux executables require host libraries including `libstdc++.so.6`
  and `libgcc_s.so.1`, which the Node wheel payload does not include.
  Still review all retained nested code and its notices; the root notice
  and matching source archive alone do not prove coverage.
- **Quint and npm.** The entire Quint npm package and its copied lock file
  matched the pinned package and source inputs. All 78 production lock
  paths (3,862 files) matched the exact file names and bytes of their
  SHA-512-pinned npm archives; no extra `node_modules` files. Manifest
  declarations: 48 MIT, 12 BSD-3-Clause, 11 ISC, four BlueOak-1.0.0, three
  Apache-2.0. The six packages without a standalone root notice were
  `@sweet-monads/either`, `@sweet-monads/maybe`, `@types/lodash.clonedeep`,
  `undici-types`, `isarray`, and `seedrandom`. The first four have matching
  supplementary project notices. `isarray`'s README and `seedrandom.js`
  provide MIT terms; individual Seedrandom algorithms retain attribution.
  `bignumber.js` uses `LICENCE.md`; `protobufjs/google/LICENSE` is an
  example of a retained nested notice. Repeat the exact package check on
  both native wheels, and finish the nested attribution audit; a package
  manifest is not evidence about every vendored file.
- **Temurin.** The 19-module selected legal trees in both Linux JDKs match
  one another byte for byte; the Darwin JDK lacks only `java.base/gcc.md`.
  The checked local wheel has two exact copies of the Linux legal tree
  (`payload/java/legal` and `.dist-info/licenses/OpenJDK`). The 47 other
  retained image files compared to the parent JDK, including `bin/java`,
  `lib/server/libjvm.so` and `lib/security/cacerts`, also match byte for
  byte. The `release` module list is checked separately; this is not a
  complete expected `jlink` file inventory or a reproduction of
  `lib/modules`. All three vendor JDK `release` files name OpenJDK source
  `8799347eca78` and build commit `8d9fd6fa96e5066571a13823b07c2934e5958d8b`.
  Both emitted source companions match their archive pins.

### Temurin open issues

The [exact release's vendor SBOMs](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.13.1%2B2)
(`OpenJDK21U-sbom_{aarch64_linux,x64_linux,aarch64_mac}_hotspot_21.0.13.1_2.json`)
record GCC 11.3.0 and static libstdc++ configuration on both Linux
builds, and Clang 15.0.0 on macOS. The retained Linux arm64 `libjvm.so`
records GCC 11.3.0 in `.comment` and does not list `libstdc++.so.6` as a
dynamic dependency. The Linux `java.base/gcc.md` (SHA-256
`589e34f142cdf7d1430daa573e61c2e3dd0330c9eb5a2c00d4a98b3a4450810b`)
contains GPLv3 and the GCC Runtime Library Exception, but its heading
names libgcc/libstdc++ **14.2.0**. Compiler version, link mode and notice
heading together do not establish the exact linked library version.
Identify the inputs from the devkits and confirm their license and
exception coverage. Use the vendor build config to establish corresponding
source and build completeness for each linked image.

The three vendor `lib/security/cacerts` files match the local wheel
(SHA-256 `868c92b50f99bcb97b1b84b87850a69623264972b3e18e868646a894535980a5`).
Adoptium's [security README](https://github.com/adoptium/temurin-build/blob/8d9fd6fa96e5066571a13823b07c2934e5958d8b/security/README.md)
identifies the generated truststore as MPL-2.0, not OpenJDK's GPL.
In the unpacked `temurin-build` companion, `cd security` and run
`bash ./mk-cacerts.sh --nokeystore` to regenerate inputs from its exact
`certdata.txt` (SHA-256 `3ec2b4d240dc12c747eaf450061db84af757c483bbda302f9e29ceb5d70be510`).
The SHA-256 sets of the DER certificates in `certs/` and those printed
by `keytool -list -rfc` from the wheel truststore matched all 117
certificates. This compares certificate contents, not keystore serialization.
Keep the MPL notice and point binary recipients to this exact source and
recipe. The companion also carries the curl-derived `mk-ca-bundle.pl`;
check its separate `COPYING` terms before distributing the scripts.

The pinned OpenJDK source archive is not text-only. A file-extension
inventory identified 43 JARs, 15 `.class` files, two ZIPs and various
certificate/keystore fixtures under `test/`; e.g.
`test/jdk/jdk/internal/loader/URLClassPath/testclasses.jar`. Source-tree
assets also include images and one TTF. This count does not cover every
binary by content. Preserve the source needed to build the exact image;
scope a filtered companion or audit the retained assets and fixtures
before serving the raw archive. The build-scripts archive is separate.

## Nix: exact local closure, not wheel equivalence

`nix-store -qR` finds 65 store paths including the local root
`/nix/store/5zdji5qckmzrryby1bj618q1ifciyvmr-git-quint-diff-0.1.0-rc1`.
The five direct references are Bash 5.3p9, Node.js 24.22.1, Quint CLI
0.33.1, OpenJDK headless 21.0.12.1+1, and the trimmed Apalache JAR.
Nix Node uses shared libraries including OpenSSL 3.6.5, ICU 78.3, libuv
1.52.1 and SQLite 3.53.3, distinct from the official Node wheel build.
`nix why-depends` traces Nix Node's npm 11.19.1 and Corepack 0.36.0 store
outputs. The closure also includes tool, development and static-library
outputs; a process not calling a component does not remove its payload
from a recursively copied Nix closure. The local OpenJDK has 69 modules
and legal directories for them, not Temurin's 19-module linked image.
Its [Nixpkgs source pin](https://github.com/NixOS/nixpkgs/blob/f1e5c356f35d07e7b71a6b5e6c9338e0b029e0c0/pkgs/development/compilers/openjdk/21/source.json)
is `openjdk/jdk21u` at `jdk-21.0.12.1+1`.

Comparing the realized Nix Quint tree with the wheel: all 529 shared
Quint package files match; only the wheel adds the upstream npm lock
copy. Nix has all 3,862 production dependency files; 3,860 match and the
two executable files (`@grpc/proto-loader/build/bin/proto-loader-gen-types.js`
and `which/bin/node-which`) differ only by patched shebangs. Nix adds
`node_modules/.package-lock.json` and two `.bin` symlinks. The baseline
Nix tree lacked Quint's root notice and the three supplementary npm
notice files carried by the wheel; the shared pins now install them in
both forms, alongside the Node root and nbytes notices. A local rebuild
confirmed that all seven shared notice files match the wheel and the pins;
the Nix runtime closure still contains 65 store paths.

Do not infer clearance for a public binary cache from pinning Nixpkgs or
from an installed CLI test. Audit the final closure independently on
both native targets (and any other target intended for binary distribution);
record each retained output, matching sources and patches, and available
notices. If limiting distribution to package source/evaluation rather
than redistributing a full closure, state that scope explicitly.

## Reproduce on the native candidates

Build on a host listed in [packaging.md](packaging.md) and run this
manual offline comparison before discarding the test artifacts:

```sh
cache="$scratch/wheel-cache"
platform=manylinux_2_28_x86_64 # or macosx_13_0_arm64 on Apple Silicon
python3 -B packaging/build-wheel.py --platform "$platform" \
  --out-dir "$scratch/dist" --cache-dir "$cache"
python3 -B release-tests/check-wheel-payload.py "$scratch"/dist/*.whl \
  --platform "$platform" --cache-dir "$cache"
out=$(nix build .# --no-link --print-out-paths)
nix-store -q --references "$out"
nix path-info -r --json --json-format 1 "$out" > "$scratch/nix-closure.json"
```

Use the checkout's pins for the current candidate, or pass `--pins` with
a separately checked-out historical manifest. The comparison passed on the
baseline and local notice-restoration builds and rejected controls with the
wrong platform and a missing pinned notice. On each final native host,
complete this ZIP/notice comparison, then run the installed acceptance suite
and save checksums for the exact tested artifacts. A vendor input audit,
this local arm64 result, or a previous native run is not evidence for a
new native wheel or Nix closure.
