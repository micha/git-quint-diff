# Wheel payload spot check: Node.js, npm and Temurin

**Question:** Does the local Linux arm64 candidate carry the pinned runtime
files and their upstream notices? This is an artifact check, not approval to
redistribute the wheel or other targets.

| Payload | Checked on the Linux arm64 wheel | Still required |
| --- | --- | --- |
| Node.js 24.22.3 | The installed `node` executable and the cumulative `Node.js-LICENSE` are byte-identical to `bin/node` and `LICENSE` from the SHA-256-pinned official binary archive. | Repeat on the two matrix artifacts. Check that the cumulative notice covers the components built into each executable, including any separate source requirements. The Nix closure uses its own Node derivation, not this binary. |
| Quint 0.33.1 production npm tree | All 78 production lock paths (3,862 files) matched the exact npm tarball member names and bytes after checking the lock's SHA-512 pins. There were no additional `node_modules` files. Package manifests declare 48 MIT, 12 BSD-3-Clause, 11 ISC, four BlueOak-1.0.0 and three Apache-2.0 entries. | Confirm required downstream notices and any nested bundled-code attribution, including the notices already supplied separately and those embedded in source or README files. Repeat the inventory on the final artifacts; Nix compiles Quint using the pinned Nix npm dependency fetch instead. |
| Eclipse Temurin 21.0.13.1+2 | The linked image reports 19 modules. All have legal files in the wheel, with 73 copies in `.dist-info/licenses/OpenJDK` identical to those in the linked image. The retained release file names the pinned `temurin-build` commit. Both emitted source companions match their pins. | Check build/source completeness for each linked host image. The original OpenJDK source archive also contains binary test fixtures (for example `test/jdk/jdk/internal/loader/URLClassPath/testclasses.jar`); check their terms or omit unneeded artifacts from a separately audited companion. Check the Nix runtime closure independently of this Temurin image. |

The npm packages lacking a standalone license/notice file at their package
root were `@sweet-monads/either`, `@sweet-monads/maybe`,
`@types/lodash.clonedeep`, `undici-types`, `isarray`, and `seedrandom`.
The build adds files for Sweet Monads, DefinitelyTyped and Undici Types.
The `isarray` README and `seedrandom.js` contain MIT terms; individual
Seedrandom algorithm files also carry attribution. `bignumber.js` has a
standalone British-spelled `LICENCE.md`; it is not a missing notice.
A package's manifest license is not proof of coverage of every file it ships.

Reproduce by comparing ZIP members in the wheel with the archives pinned
by [`payloads.json`](../packaging/payloads.json) and the wheel's
`payload/quint/upstream-package-lock.json`: match Node's binary and notice,
check every non-`dev` npm archive's lock integrity and exact regular files,
compare `payload/java/legal/` with `.dist-info/licenses/OpenJDK/`, then inspect
`payload/java/release` and `payload/java/temurin-build-release`. This does not
prove correspondence of all Node and OpenJDK binary code with its source or
close the [publication hold](../packaging/REDISTRIBUTION.md#publication-hold).
