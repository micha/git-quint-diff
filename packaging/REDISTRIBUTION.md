# Wheel payload and source companions

The candidate wheel needs only Python and Git at runtime. It includes a release
build of Node.js (binary and its cumulative license), the published npm build
of Quint and its exact production lock dependencies, the unmodified Apalache
release JAR (including TLC and the JAR's notices), and a headless `jlink` image
built with the matching Eclipse Temurin 21 JDK. The input versions and archive
digests are in `payloads.json` in the wheel's `.dist-info` directory. License
and notice files supplied in the bundled npm packages or JAR are retained. The
wheel also contains the upstream Node.js, Quint, Apalache and OpenJDK license
texts, OpenJDK module notices, and separately fetched upstream notices listed
in `payloads.json`.

Every wheel build also emits the exact Temurin release's corresponding OpenJDK
source archive **and** the `temurin-build` scripts archive at the commit in the
JDK release metadata. Keep both files with the matching wheel(s); do not offer a
binary wheel for download without making the matching source materials
available under the applicable terms (OpenJDK: GPL v2 with Classpath Exception).
`build-wheel.py` records the `jlink` command used to assemble the image.

These are internal release-candidate build instructions, not publication
authorization. The wheel includes the project's [MIT license](../LICENSE)
for its own code and documentation; that license does not apply to bundled
components. Before public redistribution, audit all transitive
redistribution obligations, including native solver libraries inside
the upstream Apalache JAR (see cvc5's COPYING and its notes on optional and
bundled third-party libraries). The OpenJDK companions alone do not settle that
audit. Do not upload to PyPI or attach to a public release as part of this gate.

## Build

On a matching native host, with Python 3.12+ and HTTPS access to the official
upstream archives:

```sh
python3 packaging/build-wheel.py --platform manylinux_2_28_x86_64 --out-dir dist
# On Apple Silicon (macOS 13.5+):
python3 packaging/build-wheel.py --platform macosx_13_0_arm64 --out-dir dist
```

Linux arm64 is available as a local test target (`manylinux_2_28_aarch64`),
not a matrix-gated RC artifact. `--cache-dir` retains verified download inputs
outside the warehouse of generated files; each cached file is rechecked on
reuse. The build does not install from npm or use pip, and the installed
command does not fetch any dependency.
