# Sources for the retained JVM components

The default Nix package installs this directory under
`share/licenses/git-quint-diff/jvm/`. The wheel installs it in
`git_quint_diff-*.dist-info/licenses/jvm/`. See `notices.json` for the
upstream origin and SHA-256 of each verbatim notice. The project's MIT
license does not replace any of these terms. Apalache's own unmodified
license and notice are one directory up. The backend was repacked to omit
unused solver distributions and zstd-jni. Jetty itself is supplied under
Apache-2.0; its umbrella notice is not the license for Servlet 6.0.0. The
retained Orbit Activation classes are Apache-2.0 Geronimo code; the
original Eclipse bundle attribution is preserved separately. Netty and
gRPC notices can refer to optional components not shipped here.

## Obtaining the source

The same filtered TLA+ Tools source tar is available from the wheel build
and the separate Nix source target. See [the TLC rebuild recipe](../TLC-SOURCE.md)
for the exact archive name, checksum, and independent rebuild procedure.
It does not supply source for any embedded dependency.

For **Logback 1.5.32, Jakarta Servlet API 6.0.0, Jakarta Mail 1.6.8,
LSP4J 0.21.1 and Kiama 2.5.1**, use `jvm-priority-sources.tar`. Its
SHA-256, the exact upstream archives and the published source artifacts
are listed in the adjacent `sources.json`, under `companion` and
`inputs`. Those URLs are pinned to immutable revisions or exact artifact
versions. To choose the sources for one component, use its entry in
`projects`. The `tree` gives the exact upstream source and build files;
`published` identifies the matching Maven source JARs.

- A wheel build produces the companion next to the wheel, not in the
  Python environment. Use the companion from the same release as the wheel.
- For the Nix package, build `nix build .#jvm-source-companions` from the
  exact source revision of the binary package. `result/` contains the
  same companion. It is not a runtime dependency.
- From that revision, you can also download the `inputs` to a directory,
  naming each file by its JSON key, then run
  `python3 -B packaging/jvm_legal.py pack INPUT_DIR OUTPUT_DIR`. The
  command verifies every input SHA-256 and the resulting archive. These
  are build/recipient steps; `git quint-diff` never fetches sources or
  dependencies at review time.

This is a private candidate, not a published source offer. Before any
binary distribution, including a public Nix cache, make this exact
companion durably available with the matching binary downloads and tell
recipients where to get it. Keep the original license and attribution
files with the code. Logback is supplied under EPL-2.0 (it also offers
LGPL-2.1); Servlet and Mail are supplied under EPL-2.0, with the separate
Apache-2.0 terms identified by Servlet's upstream notice. Kiama's Source
Code Form is available under MPL-2.0.

LSP4J's release tree and source headers say EPL-2.0 or EDL-1.0 and the
Maven POM says EPL-2.0; the exact `jsonrpc` bundle's legacy `about.html`
says EPL-1.0. Both declarations, their terms, and the exact sources are
preserved. We do not select a BSD-only route or discard the artifact
notice; confirm the terms for that bundle before public
redistribution. LSP4J debug also adapts Xbase's `ToStringBuilder` and
`ToStringContext` (Copyright (c) 2014, 2018 itemis AG (http://www.itemis.eu)
and others). See the upstream [Xbase notice](notices/xbase-lib-2.28.0/about_org.eclipse.xtext.xbase.lib.html)
and the full [EPL-2.0 text](notices/logback-1.5.32/EPL-2.0.txt). The modified
source is `org.eclipse.lsp4j.debug/src/main/java/org/eclipse/lsp4j/debug/util/ToStringBuilder.java`
in the LSP4J tree in the companion. This does not mean the full Xbase library is installed.

## What's in the companion

The archive carries the selected upstream production source and resources,
original Maven/Gradle/sbt build files, and applicable notices. It omits
unrelated docs/assets and test fixtures, including Mail's prebuilt report
parser JARs and LSP4J's Gradle wrapper binary. If building from the tar,
unpack with `tar -xmf jvm-priority-sources.tar`. Ignoring the normalized
mtime avoids an epoch-zero timestamp issue in Mail's Maven resource
processing. Use the Gradle version in
`gradle/wrapper/gradle-wrapper.properties` (8.0.2) with the retained LSP4J
build files. Build only the supplied production modules; this is not a
snapshot for running every upstream test, publishing, or building the
full upstream Maven reactors. See the exact upstream trees for the
omitted projects, tests, and associated build profiles.

The build compares published Java/Scala/Xtend sources with the selected
upstream files (line-ending normalization for comparison only). It
preserves the precise build-substituted Mail `Version.java` and 141
published LSP4J debug-generated Java files under each component's
`published/` directory. The Mail template and the LSP4J debug protocol
and Xtend generators are included in the corresponding checkout trees.
These checks are source correspondence and archive integrity, not a
claim that every original vendor build was reproduced byte for byte.
