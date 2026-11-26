# Wheel payload and source companions

The candidate wheel needs only Python and Git at runtime. It includes a release
build of Node.js (binary and its cumulative license), the published npm build
of Quint and its exact production lock dependencies, a trimmed Apalache JAR
(including TLC), and a headless `jlink` image built with the matching Eclipse
Temurin 21 JDK. The input versions and archive digests are in `payloads.json`
in the wheel's `.dist-info` directory. License and notice files supplied in
bundled npm packages or in the retained JAR entries are copied. The wheel also
contains the upstream Node.js, Quint, Apalache and OpenJDK license texts,
OpenJDK module notices, and separately fetched upstream notices listed in
`payloads.json`.

`repack-backend.py` removes the cvc5 and Z3 bindings, their native libraries
(including Windows runtime DLLs), and zstd-jni from the exact Apalache 0.62.4
release JAR. The shipped entry points only translate Quint IR and explore it
with TLC; this is not a general Apalache distribution. The same repacker is used
by Nix and the wheel builder. The development shell keeps the upstream JAR
unmodified for the independent Quint/TLC oracle.

Every wheel build also emits the exact Temurin release's corresponding OpenJDK
source archive **and** the `temurin-build` scripts archive at the commit in the
JDK release metadata. Keep both files with the matching wheel(s); do not offer a
binary wheel for download without making the matching source materials
available under the applicable terms (OpenJDK: GPL v2 with Classpath Exception).
`build-wheel.py` specifies the `jlink` command used to assemble the image.
The build also emits the pinned Apalache 0.62.4 and TLA+ Tools 1.8.0 sources.
TLC's EPL-2.0 notice is `META-INF/LICENSE_tla2tools.md` in the JAR, not the
separate `License_tla2tools.txt` for Microsoft material. Keep the repack script
available with the release sources.

## Publication hold

The wheel includes the project's [MIT license](../LICENSE) for its own code
and documentation; that license does not apply to bundled components. The
solver exclusions and source companions are not a complete redistribution
audit. In particular, the fat JAR still contains other JVM packages that
must be inventoried and matched with notices and, where the chosen license
requires it, corresponding source. Examples to resolve include Logback
1.5.32 and Jetty 12.1.10 (including its Servlet dependencies); the merged
JAR does not supply separately identified notices for them. Also verify the
Node.js and linked JDK payloads and the production npm package inventory on
the artifacts to be published. Do not upload a wheel, JAR, or Nix closure to
a public download or binary cache until these checks are cleared.

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
