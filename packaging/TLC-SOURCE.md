# Rebuild the embedded TLC from its source companion

The Apalache 0.62.4 payload contains TLC built from TLA+ Tools revision
[`94d0c5070852b37b801bb8998c436383ab7ee37b`](https://github.com/tlaplus/tlaplus/tree/94d0c5070852b37b801bb8998c436383ab7ee37b).
Do not substitute the archive or JAR named `v1.8.0`: the later release asset
has different class bytes. The wheel build produces
`tlaplus-94d0c5070852b37b801bb8998c436383ab7ee37b-source.tar` (plain POSIX USTAR,
SHA-256 `01a19bf1e82ffcb768371bcae287ce87bd2cad8fa0cdcad5d9e372c4c3a862ca`).
Keep this companion and this rebuild recipe with any distribution of the backend.

The companion copies the matching Tools source, parser grammar, resources,
Ant files, the helper test sources needed for the shipped classes, and notices.
File contents are not rewritten. It does not include Toolbox, vendored JARs,
unrelated tests, repositories, bundled JavaCC docs, or the checked-in Windows
shortcut and debug illustration. The existing backend JAR still has the old
shortcut; the source-companion change does not change the backend bytes. The
companion retains the root MIT text, `doc/License.txt`, and notices in the
source files (including the notices for the checked-in Commons Math code).
The binary's `META-INF/LICENSE_tla2tools.md` is the Eclipse Public License
text carried in from the vendored `mailapi` JAR, not the license of TLC's
own source. This companion is not source for that dependency, Apalache's
additional standard modules and Scala classes, or the other JVM dependencies.

## Rebuild inputs

Use Python 3.12+. Download and check these inputs separately. Only the filtered
companion is an output of this process; do not copy the raw Tools archive, JDK
or build JARs into it.

| Input | SHA-256 |
| --- | --- |
| [Raw Tools archive at the matched revision](https://codeload.github.com/tlaplus/tlaplus/tar.gz/94d0c5070852b37b801bb8998c436383ab7ee37b) | `aaa632e07322f2c3f5923bf9f691b963f261d2f59bba271b4012539ce3d1271d` |
| [Temurin JDK 17.0.21+9 for Linux arm64](https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.21%2B9/OpenJDK17U-jdk_aarch64_linux_hotspot_17.0.21_9.tar.gz) (build JVM, not the wheel JVM) | `3e4eca7ead088f080af1476007decf010a240a1eb4e1e78c54fa32fbcc347084` |
| [`ant-1.10.15.jar`](https://repo.maven.apache.org/maven2/org/apache/ant/ant/1.10.15/ant-1.10.15.jar) | `763acda4a69588c9ea8817a952851ff0c2fc4bffa1d081c2565dc407f29d5794` |
| [`ant-launcher-1.10.15.jar`](https://repo.maven.apache.org/maven2/org/apache/ant/ant-launcher/1.10.15/ant-launcher-1.10.15.jar) | `5c8551990307a032336d98ddaed549a39a689f07d4d4c6b950601bf22b3d6a1b` |

Set `raw` to the downloaded Tools archive, `jar` to the `apalache.jar` from
the wheel (or the same repack in the Nix store), `companion` to the emitted
`.tar`, and `jdk`, `ant`, `launcher` to the unpacked JDK and the two JAR paths.
Use `pack` if you need to regenerate the companion; `verify` can run directly
on the emitted tar:

```sh
python3 -B packaging/tlc_source.py pack "$raw" "$companion"
python3 -B packaging/tlc_source.py verify "$raw" "$jar" "$companion" "$jdk" "$ant" "$launcher"
```

The verifier checks the companion digest and stages only the files in
`BUILD_INPUTS` from the SHA-256-checked raw Tools archive. This gives Ant its
original JavaCC 4.0 and compile dependencies (their identities are given in
`lib/vendored-jars.json` in the companion); none is emitted. It uses the
unmodified `customBuild.xml clean compile` target, then builds the helper
sources separately with the upstream Java 11 release, debug and UTF-8 flags.
`TTraceModelCheckerTestCase` is needed at compile time but its class is not
in the embedded JAR. Verification compares 969 production classes, six
helper classes, and 20 Tools standard modules by member name and bytes, and
checks for additional classes in the Tools namespaces. It does not attempt to
rebuild the full upstream distribution or certify any other embedded classes.
