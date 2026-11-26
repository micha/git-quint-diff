#!/usr/bin/env python3
"""Check wheel payload bytes against pinned local upstream inputs, without installing or downloading."""

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import posixpath
import re
import stat
import tarfile
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {
    "manylinux_2_28_aarch64": ("linux-arm64", "aarch64_linux", ""),
    "manylinux_2_28_x86_64": ("linux-x64", "x64_linux", ""),
    "macosx_13_0_arm64": ("darwin-arm64", "aarch64_mac", "/Contents/Home"),
}
MODULES = set("""java.base java.compiler java.logging java.management java.naming java.rmi
                 java.scripting java.security.jgss java.security.sasl java.sql java.transaction.xa
                 java.xml jdk.attach jdk.compiler jdk.internal.jvmstat jdk.internal.opt jdk.jfr
                 jdk.unsupported jdk.zipfs""".split())
PAYLOAD = "git_quint_diff/payload/"
NOTICE = re.compile(r"licen[cs]e|notice|copying", re.IGNORECASE)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked(path, expected, algorithm="sha256"):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, algorithm).hexdigest()
    require(digest == expected, f"{algorithm} mismatch: {path}")
    return path


def cached(cache, digest, algorithm="sha256"):
    return checked(cache / f"{algorithm}-{digest}", digest, algorithm)


def tar_files(path, select, *, legal_links=False):
    """Read selected regular members as bytes (no extraction). Only JDK legal symlinks are allowed."""
    files, links = {}, {}
    roots = set()
    with tarfile.open(path, "r|*") as tar:
        for member in tar:
            root, _, name = member.name.partition("/")
            roots.add(root)
            parts = member.name.split("/")
            require(all(part and part not in (".", "..") for part in parts),
                    f"invalid member path: {path}: {member.name}")
            if member.isdir() or not select(name):
                continue
            require(name and name not in files and name not in links, f"duplicate file: {path}: {name}")
            if member.isfile():
                files[name] = tar.extractfile(member).read()
            elif legal_links and member.issym() and not member.linkname.startswith("/"):
                links[name] = posixpath.normpath(posixpath.join(posixpath.dirname(name), member.linkname))
            else:
                raise ValueError(f"non-regular member: {path}: {name}")
    require(len(roots) == 1, f"expected one archive root: {path}")
    for name, target in links.items():
        seen = {name}
        while target in links and target not in seen:
            seen.add(target)
            target = links[target]
        require(target in files and target.rsplit("/", 2)[0] == name.rsplit("/", 2)[0],
                f"unresolved or external legal link: {path}: {name}")
        files[name] = files[target]
    return files


def check_files(z, prefix, expected):
    actual = {name[len(prefix):] for name in z.namelist() if name.startswith(prefix)}
    missing, extra = sorted(expected.keys() - actual), sorted(actual - expected.keys())
    require(not missing and not extra, f"different {prefix} tree: missing={missing[:5]}, extra={extra[:5]}")
    for key, data in expected.items():
        require(z.read(prefix + key) == data, f"wheel payload differs: {prefix}{key}")


def check_quint(z, cache, pins, legal):
    q = pins["quint"]
    names = {"LICENSE", "quint/package-lock.json"}
    source = tar_files(cached(cache, q["source"]), names.__contains__)
    lock_bytes = source["quint/package-lock.json"]
    lock = json.loads(lock_bytes)
    require(lock["lockfileVersion"] == 3 and lock["packages"][""]["version"] == q["version"],
            "unexpected Quint lockfile")
    prefix = PAYLOAD + "quint/"
    require(z.read(legal + "Quint-LICENSE") == source["LICENSE"], "Quint source license differs")
    tree = tar_files(cached(cache, q["npm"]), lambda _: True)
    require("upstream-package-lock.json" not in tree, "unexpected lock in Quint npm archive")
    tree["upstream-package-lock.json"] = lock_bytes
    declared, without_root_notice = Counter(), []
    for key, value in sorted(lock["packages"].items()):
        if not key or value.get("dev"):
            continue
        integrity = value["integrity"]
        require(integrity.startswith("sha512-"), f"unexpected integrity algorithm: {key}")
        digest = base64.b64decode(integrity[7:], validate=True).hex()
        require(len(digest) == 128, f"invalid digest length: {key}")
        files = tar_files(cached(cache, digest, "sha512"), lambda _: True)
        pkg = json.loads(files["package.json"])
        require(pkg["version"] == value["version"], f"npm version differs: {key}")
        declared[pkg.get("license", "<undeclared>")] += 1
        if not any("/" not in name and NOTICE.search(name) for name in files):
            without_root_notice.append(key)
        for name, data in files.items():
            path = f"{key}/{name}"
            require(path not in tree, f"overlapping npm path: {path}")
            tree[path] = data
    check_files(z, prefix, tree)
    return {"production_packages": sum(declared.values()),
            "production_files": sum(name.startswith("node_modules/") for name in tree),
            "declared_licenses": dict(declared), "without_root_notice": without_root_notice}


def check_java(z, cache, pins, target, subdir, legal, sources):
    java = pins["temurin"]
    prefix = PAYLOAD + "java/"
    image = z.read(prefix + "release").decode()
    modules = re.search(r'^MODULES="([^"]+)"$', image, flags=re.MULTILINE)
    require(modules and len(modules[1].split()) == len(MODULES) and set(modules[1].split()) == MODULES,
            "wrong image module declaration")
    home = subdir.lstrip("/") + ("/" if subdir else "")
    vendor_legal = home + "legal/"
    # jlink rewrites release and lib/modules; the other retained arm64 Linux
    # files match the parent JDK. Check that property on each new native image.
    vendor_files = {name[len(prefix):] for name in z.namelist()
                    if name.startswith(prefix) and not name.startswith(prefix + "legal/")}
    require({"bin/java", "lib/modules", "lib/security/cacerts"} <= vendor_files,
            "incomplete Java image payload")
    vendor_files -= {"release", "temurin-build-release", "lib/modules"}
    upstream = tar_files(cached(cache, java[target]),
                         lambda name: name == home + "release" or name.removeprefix(home) in vendor_files or (
                             name.startswith(vendor_legal) and name[len(vendor_legal):].split("/")[0] in MODULES),
                         legal_links=True)
    release = upstream.pop(home + "release")
    for name in sorted(vendor_files):
        require(z.read(prefix + name) == upstream.pop(home + name), f"Java file differs from vendor JDK: {name}")
    require(release == z.read(prefix + "temurin-build-release"), "Temurin vendor release metadata differs")
    require(f'BUILD_SOURCE="git:{java["build-commit"]}"' in release.decode().splitlines(),
            "Temurin build source identity differs")
    notices = {name[len(vendor_legal):]: data for name, data in upstream.items()}
    for module in MODULES:
        for name in ("ADDITIONAL_LICENSE_INFO", "ASSEMBLY_EXCEPTION", "LICENSE"):
            require(f"{module}/{name}" in notices, f"missing upstream legal member: {module}/{name}")
    check_files(z, prefix + "legal/", notices)
    check_files(z, legal + "OpenJDK/", notices)
    checked(sources / f"OpenJDK21U-jdk-sources_{java['version'].replace('+', '_')}.tar.gz", java["sources"])
    checked(sources / f"temurin-build-{java['build-commit']}.tar.gz", java["build-source"])
    return {"modules_in_release": len(MODULES), "legal_files_per_copy": len(notices),
            "other_vendor_files": len(vendor_files)}


def verify(wheel, cache, target, sources, pins_path):
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    node_target, java_target, subdir = PLATFORMS[target]
    with ZipFile(wheel) as z:
        members = z.namelist()
        require(len(set(members)) == len(members), "duplicate ZIP entry")
        require(all(stat.S_ISREG(item.external_attr >> 16)
                    and all(p not in ("", ".", "..") for p in item.filename.split("/"))
                    for item in z.infolist()), "non-regular or unexpected ZIP member path")
        metadata = [name for name in members if name.endswith(".dist-info/WHEEL")]
        require(len(metadata) == 1, "expected one WHEEL metadata file")
        (meta,) = metadata
        info = meta.removesuffix("WHEEL")
        legal = info + "licenses/"
        tags = [line for line in z.read(meta).decode().splitlines() if line.startswith("Tag:")]
        require(tags == [f"Tag: py3-none-{target}"], "wrong WHEEL platform tag")
        require(json.loads(z.read(info + "payloads.json")) == pins, "wheel input pins differ from checkout")
        node = tar_files(cached(cache, pins["node"][node_target]), {"bin/node", "LICENSE"}.__contains__)
        with z.open(PAYLOAD + "node") as binary:
            require(hashlib.file_digest(binary, "sha256").digest() == hashlib.sha256(node["bin/node"]).digest(),
                    "Node binary differs")
        require(z.read(legal + "Node.js-LICENSE") == node["LICENSE"], "Node license differs")
        for name, (_, digest) in pins["notice_files"].items():
            require(hashlib.sha256(z.read(legal + name)).hexdigest() == digest, f"wheel notice differs: {name}")
        return {"platform": target, "node_binary_sha256": hashlib.sha256(node["bin/node"]).hexdigest(),
                "node_license_sha256": hashlib.sha256(node["LICENSE"]).hexdigest(),
                "quint": check_quint(z, cache, pins, legal),
                "temurin": check_java(z, cache, pins, java_target, subdir, legal, sources)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--platform", required=True, choices=PLATFORMS)
    parser.add_argument("--cache-dir", required=True, type=Path, help="download cache supplied to build-wheel.py")
    parser.add_argument("--sources-dir", type=Path, help="Temurin companion directory (default: wheel's directory)")
    parser.add_argument("--pins", type=Path, default=ROOT / "packaging/payloads.json",
                        help="trusted checked-out manifest (default: this revision's packaging/payloads.json)")
    args = parser.parse_args()
    try:
        report = verify(args.wheel, args.cache_dir, args.platform, args.sources_dir or args.wheel.parent, args.pins)
    except (OSError, ValueError, KeyError, BadZipFile, tarfile.TarError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
