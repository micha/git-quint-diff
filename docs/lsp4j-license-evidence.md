# Exact LSP4J 0.21.1 license evidence

**Question:** Is the EPL-1.0 declaration in the retained LSP4J input a
separately licensed component, a stale notice, or enough to prevent an
EDL-only distribution? The evidence points to a stale generic notice, but
it is not an exact-artifact clarification from upstream. A separate
Xbase copy has its own EPL-2.0 attribution. Keep the publication hold.

## What the exact inputs say

The [backend class inventory](jvm-backend-maven.tsv) pins three Maven Central
`org.eclipse.lsp4j` artifact pairs at 0.21.1. Their 152 (`debug`), 81
(`jsonrpc`) and 11 (`jsonrpc.debug`) classes all match the retained assembly.
The matching tag points to [527f4c0](https://github.com/eclipse-lsp4j/lsp4j/tree/527f4c0c0c4b69e58d8e0c29c89cd64c32147f22).

| Evidence | Checked declaration |
| --- | --- |
| `jsonrpc` binary and source JAR root `about.html` | Identical bytes (`9c7157f55d3d48ddecd668cb0c462565f1757071fde71b17d14e821ba2e71828`) to the three copies in the tagged `jsonrpc`, `generator` and core release tree. Dated June 5, 2007; says the plug-in is provided under EPL-1.0 unless otherwise indicated. Neither other JAR pair carries this resource; none of these six JAR manifests has a `Bundle-License` header. |
| Maven POMs | All three say EPL-2.0, with no EDL option, matching the tagged `gradle/maven-deployment.gradle`. SHA-256: `debug` `2217cf5cafa98944949674ddd833c3946ec3f5f3d9827c9206aede9f30200710`, `jsonrpc` `8d4cf998ef236236daa4ca513405a391abb0ecf2e91da0a750a3e7e5d4443c1f`, `jsonrpc.debug` `2882c71a2aa4dbed6502b939ea0dc30b472c1b7e0d7c05b999390b591e3d7d53`. |
| Tagged root `LICENSE` and `NOTICE` | Both declare EPL-2.0 or EDL-1.0. `NOTICE` uses `EPL-2.0 OR BSD-3-Clause` and identifies Gson separately under Apache-2.0. [`#564`](https://github.com/eclipse-lsp4j/lsp4j/pull/564) records the deliberate addition of the EDL text to `LICENSE`. |
| Published sources | 209 of 212 `.java` files in the three source JARs have `SPDX-License-Identifier: EPL-2.0 OR BSD-3-Clause`. The other three are present in the tag without headers: the `jsonrpc` `Tuple` and `TupleTypeAdapters` (introduced together by [38037e0](https://github.com/eclipse-lsp4j/lsp4j/commit/38037e06641e8cb13112402abc65538b527dca44)), and the `debug` copy below. The lack of a header is not a separate license grant. |

`git log --follow v0.21.1 -- org.eclipse.lsp4j.jsonrpc/src/main/resources/about.html`
shows the resource was introduced by [00a2337](https://github.com/eclipse-lsp4j/lsp4j/commit/00a2337d42c76a3178182bb0913ccc914ae6cabd)
in 2016 with no change through this tag. It predates the 2018 project
[request to migrate from EPL-1.0](https://github.com/eclipse-lsp4j/lsp4j/issues/233)
and [migration commit](https://github.com/eclipse-lsp4j/lsp4j/commit/ad99a3d77139351dbc00c2dacd388fe749652309).
Upstream [`#563`](https://github.com/eclipse-lsp4j/lsp4j/pull/563) corrected
an EPL-1.0 relic specifically in the Eclipse **feature** that showed up
when installing into an IDE; it did not change this plug-in resource. It
is evidence of the project transition, not a ruling about this file.

## Xbase code retained inside `debug`

[086ffce](https://github.com/eclipse-lsp4j/lsp4j/commit/086ffce4f67cdd52a7c1cd61c37e5323431a5714)
explicitly adds `debug/util/ToStringBuilder.java` from `xbase.lib`. The
release and copy commit's parent both set Xtend to `2.28.0`. In the
[matching Xbase version's source JAR](https://repo.maven.apache.org/maven2/org/eclipse/xtext/org.eclipse.xtext.xbase.lib/2.28.0/org.eclipse.xtext.xbase.lib-2.28.0-sources.jar)
(SHA-256 `2b35e9ccd4308f605e213371bb26f458b6a84bbd1e3a13cecaac0eba607db69f`),
`org/eclipse/xtext/xbase/lib/util/ToStringBuilder.java` and
`ToStringContext.java` both carry `SPDX-License-Identifier: EPL-2.0`
(no EDL alternative) and `Copyright (c) 2014, 2018 itemis AG (http://www.itemis.eu) and others.`
The source-JAR `about_org.eclipse.xtext.xbase.lib.html` declares EPL-2.0
(SHA-256 `ee66d2fb3b4c0d2ed2e7f698bc9ed4e3d6cf77fa5caf40ad03296125db1ac5f0`).

A diff against exact `debug` published source shows substantially the same
builder, with package changed, the header removed, Guava helpers replaced,
and `ToStringContext` nested; its body matches the Xbase source after
stripping indentation. The backend contains the adapted builder and its
nested classes, not the entire Xbase library. Keep the Xbase attribution,
EPL-2.0 terms and adapted source (already present in the priority source
tar). A project-wide EDL declaration alone cannot establish coverage of
those copied portions. This is separate from TLC's two Xtext API stubs.

## Before redistribution

Keep the project license, notice, exact `about.html`, the EPL-1.0 text,
and the matched source available. Ask Eclipse LSP4J maintainers to confirm
for these exact 0.21.1 Maven artifacts whether the EPL-1.0 `about.html`
is stale, which terms should accompany the `jsonrpc` binaries, and how
upstream attributes the copied Xbase builder and context. This audit did
not contact upstream; no host-specific result settles these questions.
