# Candidate payloads and source companions

Links to project files are relative to the source repository (see the wheel's
`Project-URL: Source`). This candidate is not a public source offer.

The candidate wheel needs only Python and Git at runtime. It includes a release
build of Node.js (binary and its cumulative license), the published npm build
of Quint and its exact production lock dependencies, a trimmed Apalache JAR
(including TLC), and a headless `jlink` image built with the matching Eclipse
Temurin 21 JDK. The input versions and archive digests are in `payloads.json`
in the wheel's `.dist-info` directory. Existing notices in the npm tarballs
and surviving JAR members remain in those payloads. The wheel separately
includes the upstream Node.js, Quint, Apalache and OpenJDK license texts,
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

The Temurin wheel image's `lib/security/cacerts` is derived from Mozilla's
certificate data and is under [MPL-2.0](https://www.mozilla.org/MPL/2.0/).
Obtain the Source Code Form from `security/certdata.txt` and the generation
recipe in `security/README.md` inside the matching
`temurin-build-8d9fd6fa96e5066571a13823b07c2934e5958d8b.tar.gz` companion, or
from [that exact source revision](https://github.com/adoptium/temurin-build/tree/8d9fd6fa96e5066571a13823b07c2934e5958d8b/security).
Keep that source available alongside the binary. This statement does not
apply to the separate Nix JDK's trust store.

The build emits the pinned Apalache 0.62.4 source and a filtered, matched
[TLA+ Tools source companion](TLC-SOURCE.md) from commit `94d0c5070852`. The
companion replaces the investigative `v1.8.0` archive and omits the raw
Tools archive's third-party JARs. Keep the rebuild recipe and repack script
with these materials. Review the Apalache and Temurin archives independently;
matching a source revision is not approval to distribute every file in it.

TLC's own source is MIT. `META-INF/LICENSE_tla2tools.md` in the merged JAR
is **Jakarta Mail's EPL-2.0 text**, copied into the upstream TLC build from
`mailapi-1.6.8.jar`. The separately preserved `License_tla2tools.txt` is the
Microsoft MIT text. Both packages preserve the upstream Apalache NOTICE
verbatim and install a separate [JVM notice and source guide](jvm-legal/JVM-SOURCES.md)
as `jvm/JVM-SOURCES.md` under the package's license directory. This bundle
restores pinned notices for Logback, Servlet, Mail, LSP4J, Kiama, Jetty,
Orbit Activation, TLC, and selected other components. Both builds can
produce the same `jvm-priority-sources.tar` for the selected
EPL/MPL dependencies, with exact input links and release-availability
instructions in the installed guide. The Nix source target now also
produces the same filtered TLA+ Tools tar, and both installs carry its
rebuild recipe. Neither tar is a runtime dependency. Nix and the wheel
carry the same pinned Quint, Sweet Monads, Undici Types and DefinitelyTyped
notices, as well as the Node.js cumulative license and the separate
nbytes license. They use different Node.js and Java derivations or binary
inputs; matching these notices does not clear either platform's closure.

## Publication hold

The wheel includes the project's [MIT license](../LICENSE) for its own code
and documentation; that license does not apply to bundled components. The
[backend inventory](../docs/jvm-redistribution-audit.md) identifies the
classes and supplying artifacts, not complete redistribution coverage.
Complete the remaining notice and corresponding-source checks for
shaded components and [release companions](../docs/source-companion-audit.md).
The [resource inventory](../docs/jvm-backend-resources.tsv) identifies the
inputs, not rights in nested assets. Resolve the [LSP4J claims and Xbase
attribution](../docs/lsp4j-license-evidence.md) before redistributing that bundle, and make the pinned companions available with the matching
binaries before any public distribution. The
[wheel payload audit](../docs/wheel-payload-audit.md) records local
Node.js, npm and Temurin checks and the remaining host and closure work.
Do not upload a wheel, JAR, source companion, or Nix closure to a public
download or binary cache until these checks are cleared.

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
