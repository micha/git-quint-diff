# Retained JVM backend: redistribution audit

**Question:** Which exact inputs account for the classes in the trimmed
backend, and what still prevents public binary distribution?

**Baseline:** git-quint-diff `645178a0ffae47f2895aa9dd9dea840f1af7e2ef`,
Apalache release `v0.62.4` (`7954daf7563a69cce9d0b89c8542e40bf46f7c6e`),
upstream JAR SHA-256 `e5223915507b65cc5f1638bd037ede60f8a4fc1644aff46355779f9b05df9262`,
trimmed JAR SHA-256 `1d2dab08ca132c1d7cac2ca0cc3c1f743525b18a51aef3c5d97a4d549d30d5cd`.
The prediction was that the assembly would retain separate JVM dependencies
beyond TLC and Apalache even when the CLI never calls them. The artifact
confirms this and, in several cases, did not preserve the supplying notices.
**Keep the publication hold.** This is technical evidence and proposed
release work, not a finding that any package can be published as-is.

**Update after `0cbf05c`:** Both install forms now carry the pinned
[JVM notices and source instructions](../packaging/jvm-legal/JVM-SOURCES.md).
The wheel and separate Nix source build produce the same source-only
companion for the five priority dependencies below. The audit table
records why each was selected, not a claim that the remaining payload
is cleared. The LSP4J declarations are preserved, not resolved.

## What the class comparison proves

- The JAR has 29,849 non-directory entries: 29,531 `.class` files and 318
  other members. [The Maven inventory](jvm-backend-maven.tsv) records 99
  distinct coordinates accounting for **26,316 class members**, with no
  overlap among matching entries. Compare each retained class by ZIP
  member name and uncompressed bytes, including multi-release paths;
  exclude `module-info.class` from the Maven denominators because
  Apalache's assembly discards them. The source-JAR hashes identify
  published inputs; they are not proof of source completeness.
- Of the other 3,215 class members, 975 compile from the matched TLA+
  Tools sources, 21 match the Eclipse Orbit Activation bundle below,
  and 2,219 are under Apalache's namespaces (`at/forsyte/apalache`,
  `com/github/apalachemc/apalache`, `apalache`). The 975 include 12
  Commons Math classes compiled from TLC's vendored sources and two small
  Xtext API stubs in TLC's source tree, **not** the Xtext Maven library.
  The Apache Commons Math license/notice survived the merge; the two stubs
  have no upstream headers, and their provenance is the matched TLC tree.
- The publisher's version declarations can differ from the bits shipped.
  All 84 Servlet classes match **6.0.0**, not 6.1.0. Gson contains 223
  matches to **2.11.0** and another 32 from the TLC-vendored **2.14.0**;
  Apalache resolves name collisions with `MergeStrategy.last`, not by
  removing the entire class namespace from the earlier input. gRPC likewise
  has artifacts at 1.69.0, 1.62.2 and 1.41.0. Use the verified inventory
  rather than an upstream POM, package prefixes, or a single version per
  family. `javax.annotation/` here is JSR-305 3.0.2 (35 classes), not
  the `javax.annotation-api` distribution.

To repeat comparison from a row, split `group:artifact:version`. At
`https://repo.maven.apache.org/maven2/`, use path
`group/with/slashes/artifact/version/artifact-version.jar`, and append
`-sources` before `.jar` for the source. Check the SHA-256 in the row
before reading; `matching_classes` is the count of matching `.class`
members, not a claim that source or notice coverage is complete. Save both
JARs for each entry using the same paths in a local directory, then run
`python3 -B release-tests/check-backend-inventory.py "$backend" "$maven_dir"`.
This offline check validates both digests and replays the class counts.

## Priority 1: matched source and recipient instructions

Follow component-level licensing, not the assembly's filenames. For an
EPL distribution, ship the license and preserve component
attribution, make the corresponding source available, and give a statement
with the binary telling recipients how to get that source under the EPL
(§3.1–3.3). For Kiama, do the analogous work under MPL-2.0 §3.1–3.4.
Put the availability statement and exact source links where someone
obtaining **either** wheel or Nix binaries can find them. Merely generating
files on CI, linking to a moving branch, or distributing a `-sources.jar`
without needed build inputs is not the proposed release plan. Apply these
checks before publishing to a public binary cache as well as to a wheel host.

| Retained component | Source coordinate / technical check | Materials to provide or verify |
| --- | --- | --- |
| **TLA+ Tools / TLC** | [`tlaplus/tlaplus@94d0c5070852b37b801bb8998c436383ab7ee37b`](https://github.com/tlaplus/tlaplus/tree/94d0c5070852b37b801bb8998c436383ab7ee37b). Exact raw archive SHA-256 `aaa632e07322f2c3f5923bf9f691b963f261d2f59bba271b4012539ce3d1271d`. Independent rebuild of the filtered companion compared 969 production classes, six test helper classes and 20 TLC standard modules byte for byte. The current `v1.8.0` download is not the matched object. | TLA+ Tools' own source is declared MIT by the matched tree's `README.md` and root `LICENSE` (SHA-256 `3fa3a845ce5eb7b9b3508701dc1aa4d084b6b2c27cbae8cd44d277d10ee411bf`), not EPL. Preserve that license and the separate `License_tla2tools.txt` for Microsoft material. Publish the filtered source with original build files and pinned instructions for obtaining omitted compile inputs. Attribute the JAR's embedded dependencies separately; the TLC source proof does not cover them. |
| **Logback 1.5.32** | [`qos-ch/logback@e807335a67535b4eacce94e942c0bcb649665d93`](https://github.com/qos-ch/logback/tree/e807335a67535b4eacce94e942c0bcb649665d93) (`v_1.5.32`). `logback-classic` matches all 177 classes, `logback-core` all 481, including its Java 21 multi-release variant. All 599 non-module Java files in the two Maven source JARs match the tree with CRLF normalized to LF. | Choose EPL-2.0 over the alternative LGPL-2.1. Preserve root `LICENSE.txt` and `logback-classic/LICENSE.txt` / `logback-core/LICENSE.txt` (identical to one another), plus full EPL-2.0 text; the Logback files are declarations, not the full license. Make the matching sources and Maven build materials available. |
| **Jakarta Servlet API 6.0.0** | [`jakartaee/servlet@63d2d7e17b91e7a8c44e21607c550cf55e5e69eb`](https://github.com/jakartaee/servlet/tree/63d2d7e17b91e7a8c44e21607c550cf55e5e69eb) (`6.0.0-RELEASE`). All 75 non-module Java files in the Maven source JAR match the tree. | Take the EPL-2.0 route and keep the Apache-2.0 terms for the portions identified by the upstream `NOTICE.md`: `(EPL-2.0 OR GPL-2.0 WITH Classpath-exception-2.0) AND Apache-2.0`. Ship upstream `LICENSE.md`, `NOTICE.md`, Apache text and the matching API source and Maven build files. Jetty's umbrella notice describes different terms for a Servlet version; use Servlet's own versioned notice for this artifact. |
| **Jakarta Mail 1.6.8** | [`eclipse-ee4j/mail@f31ae63dd08cebebf3b5066b26f471f9c916b0b2`](https://github.com/eclipse-ee4j/mail/tree/f31ae63dd08cebebf3b5066b26f471f9c916b0b2). 177 classes from `mailapi` and 22 from `smtp`. The exact Maven binary JAR hashes also match TLC's two vendored inputs. Of 163 source-JAR Java files, 162 match; `javax/mail/Version.java` substitutes the Maven `mail.version` value. | EPL-2.0 (GPLv2+Classpath Exception is the declared secondary license). The confusing `META-INF/LICENSE_tla2tools.md` in the fat JAR is Mail's `LICENSE.md`, carried into the upstream TLC JAR by `customBuild.xml`, not a TLC project license. Preserve Mail's `LICENSE.md`, `NOTICE.md` and any applicable retained specification attribution (the upstream `mailapi` source and binary JARs include `doc-files/speclicense.html`). Provide API/SMTP source, including the build substitution. Do not reuse the raw tree as a release companion without auditing its `docker/JTReportParser` JARs. |
| **LSP4J 0.21.1** | [`eclipse-lsp4j/lsp4j@527f4c0c0c4b69e58d8e0c29c89cd64c32147f22`](https://github.com/eclipse-lsp4j/lsp4j/tree/527f4c0c0c4b69e58d8e0c29c89cd64c32147f22). Exact 152/81/11 classes from `debug`, `jsonrpc` and `jsonrpc.debug`; same bytes as TLC's Orbit-style filenames. The published `debug` source JAR contains 141 generated Java sources not present as Java in Git. | Upstream `LICENSE` and `NOTICE` and Java headers describe EPL-2.0 or EDL-1.0 (BSD-3-Clause). Maven POM lists EPL-2.0; `jsonrpc` binary `about.html` says EPL-1.0, dated 2007. Keep that file and both project notices; reconcile the differing declarations for these exact artifacts before relying on the permissive option. Conservative source plan: include the matching source JARs and source/build tree including generators, excluding or separately auditing Gradle wrapper binary. |
| **Kiama 2.5.1** | [`inkytonik/kiama@61750c32ccd51eee31271a78713fd94809a61928`](https://github.com/inkytonik/kiama/tree/61750c32ccd51eee31271a78713fd94809a61928). All 238 classes match `kiama_2.13`; all 41 Scala files in the source JAR match the tree. | Ship upstream MPL-2.0 `LICENSE` and source; tell recipients where to obtain Source Code Form under MPL-2.0. This is a distinct source obligation; the merged JAR has no standalone Kiama notice. |

## Priority 2: restore notices lost in assembly

- **Jetty 12.1.10:** all 1,583 classes match 11 Maven artifacts (6 Jetty
  core, 4 compression modules and EE10 Servlet). At
  [`jetty/jetty.project@986024525891c2c20ff08c58ba300dc3b9847586`](https://github.com/jetty/jetty.project/tree/986024525891c2c20ff08c58ba300dc3b9847586),
  source headers and `NOTICE.txt` offer Apache-2.0 **or** EPL-2.0. Use
  the Apache-2.0 option for Jetty itself, preserve full upstream
  `LICENSE` and `NOTICE.txt` (including Aki Yoshida's separate UnixCrypt
  copyright/conditions), and declare the repack. No separate source offer
  for Jetty itself on the Apache route; this does not cover Servlet or
  other projects. Do not ship its upstream tarball by default; it contains
  many third-party JARs in test fixtures. `jetty-compression-zstandard`
  and its service-provider line are still present after zstd-jni removal;
  do not describe that provider as included zstd-jni or supported runtime
  functionality.
- **Activation:** 21 `javax.activation/` classes match the exact input
  `tlatools/org.lamport.tlatools/lib/javax.mail/javax.activation_1.1.0.v201211130549.jar`
  from the matched TLC commit (JAR SHA-256
  `89690179f5e4e8c0963efb1a18d43f852e5334bc0bb68337eea2e78d24aad360`).
  Eclipse Orbit's `about.html` describes the retained JavaBeans
  Activation Framework as Apache Geronimo code under Apache-2.0,
  distinguishing it from the EPL-1.0 wrapper. Preserve `about.html` and
  its linked text license/notice (`about_files/`), or make the same
  material available alongside the code, including `META-INF/NOTICE.txt`
  and `META-INF/LICENSE.txt` from the exact JAR. Do not substitute the
  differently licensed/different-byte `javax.activation:activation:1.1`
  artifact. Maven Geronimo 1.0.2 is also not byte-identical.
- **Apalache:** preserved upstream Apache-2.0 `LICENSE` and `NOTICE`
  accompany the wheel. Keep the upstream notice verbatim and add an
  adjacent release attribution clarifying that its MIT label for TLA+
  Tools does not describe TLA+ Tools' bundled components, and explaining
  that solver distributions were removed. The pinned v0.62.4 source archive (`ba75d76c939c76512d246771b5610a105f8c46f346087c6ecd966bd71af3d370`)
  is the release source input, not proof of an identical fat-JAR rebuild.
  For example, its SBT build pulls the moving TLC v1.8.0 release asset;
  rebuilding this exact composition requires the matched TLC and the
  exact resolved inputs. Audit its non-code assets (logos, screenshots,
  included ADR PDF) before distributing all of it.
- **Additional notices:** both installs now carry the upstream Netty
  4.1.110.Final umbrella license and notice plus its 30 related legal
  files (including JCTools); these cover an aggregate distribution and
  do not imply every referenced dependency is retained. They also carry
  gRPC-Java's common license and notice for the three retained versions,
  the two Gson licenses, two protobuf licenses, and the separate
  uPickle and Geny licenses. See [the pinned manifest](../packaging/jvm-legal/notices.json).
  Still map retained resources and shaded code (e.g. BooPickle in Izumi,
  the particular JCTools subset in Netty, and Google common protos) to
  their exact supplying notices and sources. Compare surviving Commons,
  Jackson, SLF4J, Scala, Scalaz, Checker Qual, Jakarta Inject, Commons
  Math and JLine notices against their exact upstream bytes before
  declaring coverage.

### Source and notice pins

Repository paths below resolve from the commit specified above; fetch
source archives as `https://codeload.github.com/OWNER/REPO/tar.gz/COMMIT`
and individual files at
`https://raw.githubusercontent.com/OWNER/REPO/COMMIT/PATH`. These are hashes
of the evidence inputs, **not** an allowlist approving raw source tarballs
as release companions.

| Component | Raw source archive SHA-256 | Notice file SHA-256 |
| --- | --- | --- |
| Logback | `2f0a609dd8b5c2073fdf2596c5d070a1ec4e926b91255dfda1fb5092d0267e0c` | `LICENSE.txt`: `f1eedf4f2cb9e901d6ae549a06d0c20dcde0136d37e38b50adaf51d4673f66d2`; each module's `LICENSE.txt`: `9224b901579a551596e2a6f0b3488ce833f557bd1c83179858081a0f16a19209` |
| Jetty | `58d063f585f56f1b49038d6cddcc30db063f9a7176da75f5dfe297804d1772be` | `LICENSE`: `a59137290e5765724793162c89ac3bdd340b00ea3a32207de6e39f6188f1efbb`; `NOTICE.txt`: `ce642d8c8861ef05cf94c010a2d707425ed086d56641c127d0636fd0ac031e77` |
| Servlet | `40e526a67d616ff27e3e9ac9fbfe9658ffd95722260af941cf08493a66a4daf4` | `LICENSE.md`: `6e1f002892b81cbe0647019b150c8a056efc1add565671a4f8af629b6cd2cc7b`; `NOTICE.md`: `dc367b4a1a4c321c4f90001646c182d904583b410339fa22caef27b75eaeff47` |
| Mail | `7b051f0e86a407622c9234ebc9eed358c3a839cc4b79df21fa76fa791b9b5b46` | `LICENSE.md`: `6e1f002892b81cbe0647019b150c8a056efc1add565671a4f8af629b6cd2cc7b`; `NOTICE.md`: `bba43e29c8098aaa07c2130d979f6d44a62f9ad51f8061c96bf6889ff5926819`; JAR `doc-files/speclicense.html`: `1ac771659164bdbe9f2b86b276eb863e11638b250c56fc948a5c343efaacb00b` |
| LSP4J | `d4c2e563c4943e53e6d7992b7687af59d5edf7bb61e14411dbb3c706db1d9e72` | `LICENSE`: `ff2d746ce477bf54fa8ef96e66eae1bace8ed23c8c184b60b2c2ef2aa24d25ae`; `NOTICE`: `08c8ba13e84c3fa147a2b0774e35d515b290c5ccd50b1d4aff1d062e686759fb`; JAR `about.html`: `9c7157f55d3d48ddecd668cb0c462565f1757071fde71b17d14e821ba2e71828` |
| Kiama | `dcc820df11f98ba5e79f6d210919d5232347b998dbbec5c3ad9a2687890ed9de` | `LICENSE`: `1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5` |
| Eclipse Orbit Activation | Not needed to identify the retained Geronimo classes; exact TLC input JAR above | JAR `about.html`: `ef71fe180fba73fb7a920e0af20be8f7b30d43bb0b03a805ee4ded9a8034e668`; `META-INF/LICENSE.txt`: `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`; `META-INF/NOTICE.txt`: `2a5e421c9eaf25603ab951ff19100677331e2ed0f9b3174fec807e4b5e1d0395` |
| Netty [`2e218bbd0a416d6e8a7abb5e2d180fe9f19a9968`](https://github.com/netty/netty/tree/2e218bbd0a416d6e8a7abb5e2d180fe9f19a9968) | `c581f17dcae97ee60c7c2a8d2b34cec2d9b173b26b9aaa88cc59b4e8d4bf62ff` | `LICENSE.txt`: `aac73b3148f6d1d7111dbca32099f68d26c644c6813ae1e4f05f6579aa2663fe`; `NOTICE.txt`: `64e368e79be71463922ebb102b33088667cf975edeed8df7f68efe9f89835ca1`; also audit referenced per-component files under `license/`. |

For gRPC-Java, `LICENSE` (Apache-2.0, SHA-256
`cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`)
and `NOTICE.txt` (`d891421cec918666dce9dc4516dad6a76557d12203fec121662efff365e72d63`)
are byte-identical at the three shipped release commits
([1.69.0](https://github.com/grpc/grpc-java/tree/34a7cffcf3dca012cd3e48da14d127c3afd924bf),
[1.62.2](https://github.com/grpc/grpc-java/tree/3e993a9f44ff52bd3d5ac59dfa978d8e7d30e28b),
[1.41.0](https://github.com/grpc/grpc-java/tree/d291594443db7d43a6e984a1ae0c58883c7a1921)).
Check that notice's third-party entries against the selected modules;
it covers more modules than the backend includes. For uPickle 4.3.2, use
[the release MIT `LICENSE`](https://raw.githubusercontent.com/lihaoyi/upickle/5d492e8418131aef9cefd731235d8df0e65a8d05/LICENSE)
(SHA-256 `fc06ee462a6d140906b364eb86b1f0c86fc9134827f7605df49b84190d1e2120`);
for Geny 1.1.1 use [its separate MIT `LICENSE`](https://raw.githubusercontent.com/com-lihaoyi/geny/9b290357503e5601a650bc469a072bb9a2266efb/LICENSE)
(`f8a443667d027fd656ab15ad601b7a12489f3f8bbe0ee528b558a0b7fd1863db`).
A generic project MIT text does not preserve either copyright statement.

## Limits and release gate

This inventory covers class-member provenance for this backend digest. It
is not a recursive audit of every file inside the source tarballs, embedded
code within identified class members, or all non-class JAR resources.
Apalache-added standard modules share the TLC `StandardModules/` path;
attribute them to the supplying project, not by folder alone. The original
JAR also carries a Windows `.lnk` file from TLC's `src/tla2sany/drivers/`;
it is not compiled source and is intentionally absent from the source
companion. Consider removing it in a separately pinned repack.

Finish the full preserved/required/missing notice inventory (including
shaded code and non-class resources) and confirm the source delivery paths,
then finish the [other payload checks](wheel-payload-audit.md) and validate both
native install forms on the exact proposed release commit. Alternatively,
remove demonstrably unnecessary dependencies with a separately scoped,
byte-pinned repack and rerun the independent application/oracle checks. No
runtime dependency removal or new scheduler capability was exercised by
this audit.
