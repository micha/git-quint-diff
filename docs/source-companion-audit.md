# Candidate source companions: archive audit

**Question:** Do the source archives generated for `bd059ba` contain only
reviewed corresponding source and build inputs? No. Two filtered tars
contain selected text files; the builder also emits three raw upstream
archives. A pinned archive is evidence for investigation and build input,
not by itself a release-ready source offer.

| Archive | Exact candidate inventory | Remaining release work |
| --- | --- | --- |
| `jvm-priority-sources.tar` (`2145fed8…`) | 1,513 regular files, no links. Selected upstream code, build inputs and notices; [the previous iteration](design-spiral.md#release-candidate-priority-jvm-redistribution-materials) compiled all five components. | Make the exact tar and adjacent notices available with matching binaries; resolve the [LSP4J/Xbase terms](lsp4j-license-evidence.md). Do not substitute the raw project tars. |
| `tlaplus-94d0c5070852b37b801bb8998c436383ab7ee37b-source.tar` (`01a19bf1…`) | 744 regular files, no links; the [independent build](../packaging/TLC-SOURCE.md) matched 975 classes and 20 modules. The separate Nix source target now emits this same tar as the wheel. | Make the tar and exact build recipe available. The recipe identifies vendored compile inputs but the tar does not redistribute them or supply source for other retained dependencies. |
| `apalache-0.62.4-source.tar.gz` (`ba75d76c…`) | 1,691 regular files and two symlinks (build/install paths), from the raw release source. `docs/src/adr/006rfc.pdf`, screenshots, illustrations and logos are included. The archive supplies the exact 14 Apalache standard modules and two `.proto` resources identified in the [backend inventory](jvm-backend-resources.tsv). | Either review the non-code assets or prepare a pinned source-only companion that excludes them and retains required notices and build inputs. Pin the exact resolved TLC and Maven inputs before making any claim about rebuilding the shipped Apalache assembly. |
| `OpenJDK21U-jdk-sources_21.0.13.1_2.tar.gz` (`427e3eae…`) | 69,051 regular files, no links. The `test/` subtree includes 45 ZIP/JAR signatures, 15 Java class signatures, and a PDF. Example: `test/jdk/jdk/internal/loader/URLClassPath/testclasses.jar`. | Review or exclude unneeded binary fixtures using an audited source filter. Establish corresponding source completeness for each wheel JDK image and reconcile the [Linux GCC runtime evidence](wheel-payload-audit.md); the OpenJDK archive by itself does not document everything linked into vendor binaries. |
| `temurin-build-8d9fd6fa96e5066571a13823b07c2934e5958d8b.tar.gz` (`0c9489a9…`) | 154 regular files, no links, from the vendor release's recorded build commit. No ZIP/JAR, class, native binary or PDF signature was found in this scan. Includes the Mozilla certificate data (MPL-2.0) and the separately attributed curl `mk-ca-bundle.pl` generator. | Keep the certificate data and generator's attribution. Scripts and build definitions are not the actual inputs they download: identify exact devkits, bundled native libraries and applicable source/notice materials for each linked image. This archive does not apply to the Nix JDK. |

Reproduce by generating the private candidate wheel, verifying the archive
SHA-256 values from [`payloads.json`](../packaging/payloads.json) and
[`sources.json`](../packaging/jvm-legal/sources.json), and iterating each tar's
members without extracting them. The signature scan checks the leading
bytes of regular files for ZIP, Java class, ELF, Mach-O, PE, ar and PDF.
It does not audit the contents of nested archives, all non-text formats,
third-party terms, or completeness of vendor build dependencies. A passing
archive hash or successful compile does not clear the
[publication hold](../packaging/REDISTRIBUTION.md#publication-hold).
