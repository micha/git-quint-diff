#!/usr/bin/env python3
"""Retain the pinned Apalache translator and TLC without unused native libraries."""

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import stat
import tempfile
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo


# Apalache v0.62.4 release apalache.tgz, member apalache/lib/apalache.jar.
# A new upstream JAR requires a fresh dependency/inventory audit, not just a new hash.
UPSTREAM_SHA256 = "e5223915507b65cc5f1638bd037ede60f8a4fc1644aff46355779f9b05df9262"
REMOVED_TREE_COUNTS = {
    "cvc5-libs/": 16,
    "io/github/cvc5/": 60,
    "com/microsoft/z3/": 182,
    "tools/aqua/turnkey/": 10,
    "com/github/luben/zstd/": 39,
}
SOLVER_NATIVES = {
    "cvc5-libs/linux/aarch_64/libcvc5jni.so",
    "cvc5-libs/linux/x86_64/libcvc5jni.so",
    "cvc5-libs/osx/aarch_64/libcvc5jni.dylib",
    "cvc5-libs/osx/x86_64/libcvc5jni.dylib",
    "cvc5-libs/windows/aarch_64/cvc5jni.dll",
    "cvc5-libs/windows/x86_64/cvc5jni.dll",
    "com/microsoft/z3/windows/amd64/vcruntime140.dll",
    "com/microsoft/z3/windows/amd64/vcruntime140_1.dll",
    "com/microsoft/z3/windows/x86/vcruntime140.dll",
} | {
    f"com/microsoft/z3/{platform}/{arch}/lib{lib}.{extension}"
    for platform, arches, extension in (
        ("linux", ("aarch64", "amd64"), "so"),
        ("osx", ("aarch64", "amd64"), "dylib"),
        ("windows", ("amd64", "x86"), "dll"),
    )
    for arch in arches for lib in ("z3", "z3java")
}
ZSTD_NATIVES = {
    f"{platform}/{arch}/libzstd-jni-1.5.7-8.{extension}"
    for platform, arches, extension in (
        ("aix", ("ppc64",), "so"),
        ("darwin", ("aarch64", "x86_64"), "dylib"),
        ("freebsd", ("amd64", "i386"), "so"),
        ("linux", ("aarch64", "amd64", "arm", "i386", "loongarch64", "mips64",
                   "ppc64", "ppc64le", "riscv64", "s390x"), "so"),
        ("win", ("aarch64", "amd64", "x86"), "dll"),
    )
    for arch in arches
}
NATIVE_NAME = re.compile(r"\.(?:so(?:\.\d+)*|dylib|dll|jnilib|a|lib|exe)$", re.I)
SIGNATURE_NAME = re.compile(r"^META-INF/(?:SIG-|[^/]*\.(?:SF|RSA|DSA|EC)$)", re.I)
MANIFEST = "META-INF/MANIFEST.MF"


def to_retain(archive):
    names = archive.namelist()
    if len(set(names)) != len(names):
        raise ValueError("duplicate names in upstream JAR")
    if any(SIGNATURE_NAME.match(name) for name in names):
        raise ValueError("refusing to repack a signed upstream JAR")
    native = {name for name in names if NATIVE_NAME.search(name)}
    expected = SOLVER_NATIVES | ZSTD_NATIVES
    if native != expected:
        raise ValueError(f"unexpected native inventory: missing={sorted(expected - native)}, "
                         f"extra={sorted(native - expected)}")
    for prefix, count in REMOVED_TREE_COUNTS.items():
        if sum(name.startswith(prefix) for name in names) != count:
            raise ValueError(f"unexpected entry count for {prefix}")
    required = {MANIFEST, "at/forsyte/apalache/io/quint/Quint.class", "tlc2/TLC.class"}
    if not required.issubset(names):
        raise ValueError(f"missing backend entries: {sorted(required.difference(names))}")

    kept = [name for name in names if name not in ZSTD_NATIVES and not name.startswith(tuple(REMOVED_TREE_COUNTS))]
    if native.intersection(kept):
        raise ValueError("native entry would remain in backend JAR")
    # JAR streaming readers expect the manifest before other members.
    return sorted(kept, key=lambda name: (name != MANIFEST, name))


def repack(source, output):
    if source.resolve() == output.resolve():
        raise ValueError("input and output paths must differ")
    with source.open("rb") as stream:
        digest = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        if digest.hexdigest() != UPSTREAM_SHA256:
            raise ValueError(f"upstream JAR SHA-256 mismatch: {digest.hexdigest()}")
        stream.seek(0)
        with ZipFile(stream) as src:
            names = to_retain(src)
            with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as pending:
                temp = Path(pending.name)
                try:
                    # No dependence on zlib versions, host permissions or wall clock.
                    # Only ZIP metadata changes; retained entry bytes stay intact.
                    with ZipFile(pending, "w", compression=ZIP_STORED) as dst:
                        for name in names:
                            entry = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                            entry.create_system = 3
                            entry.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10 if entry.is_dir() else (
                                (stat.S_IFREG | 0o644) << 16)
                            entry.file_size = src.getinfo(name).file_size
                            with src.open(name) as reader, dst.open(entry, "w") as writer:
                                shutil.copyfileobj(reader, writer, length=1024 * 1024)
                    pending.close()
                    temp.chmod(0o644)
                    temp.replace(output)
                finally:
                    temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_jar", type=Path)
    parser.add_argument("output_jar", type=Path)
    args = parser.parse_args()
    try:
        repack(args.input_jar, args.output_jar)
    except (BadZipFile, OSError, ValueError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
