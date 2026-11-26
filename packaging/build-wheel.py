#!/usr/bin/env python3
"""Build a native pipx wheel from pinned upstream artifacts; no install hooks."""

import argparse
import base64
import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote, urlsplit
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import jvm_legal
import tlc_source


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PACKAGE = "git_quint_diff"
VERSION = "0.1.0rc1"
PLATFORMS = {
    "manylinux_2_28_x86_64": ("Linux", "x86_64", "linux-x64", "x64_linux", ""),
    # Native test target; the first RC matrix only gates Linux x86_64 and Mac arm64.
    "manylinux_2_28_aarch64": ("Linux", "aarch64", "linux-arm64", "aarch64_linux", ""),
    "macosx_13_0_arm64": ("Darwin", "arm64", "darwin-arm64", "aarch64_mac", "Contents/Home"),
}
# jdeps --multi-release 21 --ignore-missing-deps --print-module-deps on the
# pinned fat JAR, plus the source-file compiler and JAR filesystem. Omit
# java.desktop: git-quint-diff runs TLC without the Toolbox or GUI tools.
MODULES = ("java.management,java.naming,java.rmi,java.scripting,java.security.jgss,"
           "java.security.sasl,java.sql,jdk.attach,jdk.compiler,jdk.jfr,jdk.unsupported,jdk.zipfs")


def fetch(cache, url, expected, algorithm="sha256"):
    target = cache / (algorithm + "-" + expected)

    def check(path):
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, algorithm).hexdigest() != expected:
                raise ValueError(f"{algorithm} mismatch: {url} ({path})")

    if not target.exists():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as tmp:
            downloaded = Path(tmp.name)
            try:
                with urlopen(url, timeout=120) as source:
                    shutil.copyfileobj(source, tmp, length=1024 * 1024)
                tmp.close()
                check(downloaded)
                downloaded.replace(target)
            finally:
                downloaded.unlink(missing_ok=True)
    else:
        check(target)
    return target


def extract(archive, directory):
    with tarfile.open(archive) as tar:
        tar.extractall(directory, filter="data")


def copy_files(directory, target):
    """Copy a tree into the install payload, dereferencing only internal file links."""
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() and (not path.resolve().is_relative_to(directory) or not path.is_file()):
            raise ValueError(f"unsupported payload link: {path}")
        if not path.is_dir():
            dest = target / path.relative_to(directory)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)


def npm_lock(cache, quint, source, scratch):
    # Keep Quint's release lock topology and integrity hashes, without npm resolving
    # new versions, installing dev dependencies, linking executables or running scripts.
    lock = json.loads((source / "quint" / "package-lock.json").read_text(encoding="utf-8"))
    if lock["lockfileVersion"] != 3 or lock["packages"][""]["version"] != json.loads(
        (quint / "package.json").read_text(encoding="utf-8")
    )["version"]:
        raise ValueError("unsupported or mismatched Quint package lock")
    packages = [(key, value) for key, value in lock["packages"].items() if key and not value.get("dev")]

    def download(item):
        key, value = item
        parts = PurePosixPath(key).parts
        url = urlsplit(value["resolved"])
        integrity = value["integrity"]
        if not re.fullmatch(r"(?:node_modules/(?:@[\w.-]+/)?[\w.-]+/)*node_modules/(?:@[\w.-]+/)?[\w.-]+", key) or (
            ".." in parts or "." in parts or url.scheme != "https" or url.netloc != "registry.npmjs.org" or
            not integrity.startswith("sha512-") or any(value.get(k) for k in ("link", "optional", "inBundle"))
        ):
            raise ValueError(f"unsupported lock entry: {key}")
        digest = base64.b64decode(integrity[7:], validate=True)
        if len(digest) != 64:
            raise ValueError(f"invalid npm digest: {key}")
        return key, value["version"], fetch(cache, value["resolved"], digest.hex(), "sha512")

    with ThreadPoolExecutor(max_workers=8) as pool:
        # Install parent packages before nested dependencies; never overwrite their trees.
        for key, version, archive in pool.map(download, sorted(packages)):
            with tempfile.TemporaryDirectory(dir=scratch) as unpacked:
                extract(archive, unpacked)
                (pkg,) = list(Path(unpacked).iterdir())
                if json.loads((pkg / "package.json").read_text(encoding="utf-8"))["version"] != version:
                    raise ValueError(f"unexpected npm package at {key}")
                dest = quint / key
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.mkdir()
                copy_files(pkg, dest)
    shutil.copyfile(source / "quint" / "package-lock.json", quint / "upstream-package-lock.json")


def stage(scratch, cache, target, pins):
    _, _, node_target, java_target, java_subdir = PLATFORMS[target]
    base = scratch / "wheel"
    info = base / f"{PACKAGE}-{VERSION}.dist-info"
    licenses = info / "licenses"
    licenses.mkdir(parents=True)
    shutil.copyfile(ROOT / "LICENSE", licenses / "git-quint-diff-LICENSE")
    payload = base / PACKAGE / "payload"
    payload.mkdir(parents=True)
    shutil.copyfile(HERE / "launcher.py", payload.parent / "__init__.py")
    shutil.copyfile(ROOT / "git-quint-diff", payload / "git-quint-diff")
    (payload / "runtime").mkdir()
    for name in ("git-snapshot.cjs", "quint-model.cjs", "tlc.cjs", "Translate.java"):
        shutil.copyfile(ROOT / "runtime" / name, payload / "runtime" / name)

    node_version = pins["node"]["version"]
    node_dir = f"node-v{node_version}-{node_target}"
    extract(fetch(cache, f"https://nodejs.org/dist/v{node_version}/{node_dir}.tar.xz",
                  pins["node"][node_target]), scratch)
    shutil.copy2(scratch / node_dir / "bin" / "node", payload / "node")

    java = pins["temurin"]
    version = java["version"]
    release = f"https://github.com/adoptium/temurin21-binaries/releases/download/{quote('jdk-' + version)}"
    binary = f"OpenJDK21U-jdk_{java_target}_hotspot_{version.replace('+', '_')}.tar.gz"
    extract(fetch(cache, f"{release}/{binary}", java[java_target]), scratch)
    jdk = scratch / ("jdk-" + version) / java_subdir
    build_commit = java["build-commit"]
    if f'BUILD_SOURCE="git:{build_commit}"' not in (jdk / "release").read_text().splitlines():
        raise ValueError("Temurin build source pin does not match the JDK release metadata")
    linked = scratch / "java-image"
    subprocess.run([str(jdk / "bin" / "jlink"), "--add-modules", MODULES, "--no-man-pages",
                    "--no-header-files", "--compress=zip-6", "--output", str(linked)], check=True)
    copy_files(linked, payload / "java")
    shutil.copyfile(jdk / "release", payload / "java" / "temurin-build-release")
    copy_files(linked / "legal", licenses / "OpenJDK")
    name = f"OpenJDK21U-jdk-sources_{version.replace('+', '_')}.tar.gz"
    sources = {
        name: fetch(cache, f"{release}/{name}", java["sources"]),
        f"temurin-build-{build_commit}.tar.gz": fetch(
            cache, f"https://codeload.github.com/adoptium/temurin-build/tar.gz/{build_commit}", java["build-source"]),
    }

    version = pins["quint"]["version"]
    quint_src = scratch / f"quint-{version}"
    extract(fetch(cache, f"https://codeload.github.com/quint-co/quint/tar.gz/refs/tags/v{version}",
                  pins["quint"]["source"]), scratch)
    extract(fetch(cache, f"https://registry.npmjs.org/@informalsystems/quint/-/quint-{version}.tgz",
                  pins["quint"]["npm"]), scratch)
    quint = payload / "quint"
    copy_files(scratch / "package", quint)
    npm_lock(cache, quint, quint_src, scratch)

    apalache = pins["apalache"]
    version = apalache["version"]
    extract(fetch(cache, f"https://github.com/apalache-mc/apalache/releases/download/v{version}/apalache.tgz",
                  apalache["sha256"]), scratch)
    apalache_home = payload / "quint-home" / f"apalache-dist-{version}" / "apalache"
    (apalache_home / "lib").mkdir(parents=True)
    backend = apalache_home / "lib" / "apalache.jar"
    subprocess.run([sys.executable, "-B", str(HERE / "repack-backend.py"),
                    str(scratch / "apalache" / "lib" / "apalache.jar"), str(backend)], check=True)
    shutil.copyfile(scratch / "apalache" / "LICENSE", licenses / "Apalache-LICENSE")
    sources.update({name: fetch(cache, url, digest)
                    for name, (url, digest) in sorted(pins["backend_sources"].items())})
    tlc_pin = pins["tlc_source"]
    upstream = fetch(cache, f"https://codeload.github.com/tlaplus/tlaplus/tar.gz/{tlc_pin['revision']}",
                     tlc_pin["upstream_sha256"])
    source_name = tlc_source.companion_name(tlc_pin)
    generated = scratch / "generated-sources"
    generated.mkdir()
    sources[source_name] = generated / source_name
    tlc_source.pack(upstream, sources[source_name], tlc_pin)
    source_pin = jvm_legal.pin_file("sources.json")
    source_name = source_pin["companion"]["file"]
    sources[source_name] = generated / source_name
    jvm_legal.pack({name: fetch(cache, item["url"], item["sha256"])
                    for name, item in source_pin["inputs"].items()}, sources[source_name], source_pin)
    jvm_legal.install(licenses / "jvm")
    local_notices = {"Node.js-LICENSE": scratch / node_dir / "LICENSE", "Quint-LICENSE": quint_src / "LICENSE"}
    for name, (url, digest) in sorted(pins["notice_files"].items()):
        if name in local_notices:
            source = local_notices[name]
            with source.open("rb") as stream:
                jvm_legal.verify(stream, digest, name)
        else:
            source = fetch(cache, url, digest)
        shutil.copyfile(source, licenses / name)
    for name in ("REDISTRIBUTION.md", "TLC-SOURCE.md"):
        shutil.copyfile(HERE / name, licenses / name)
    shutil.copyfile(HERE / "payloads.json", info / "payloads.json")

    tag = f"py3-none-{target}"
    license_headers = "".join(f"License-File: {p.relative_to(licenses).as_posix()}\n"
                              for p in sorted(licenses.rglob("*")) if p.is_file())
    (info / "METADATA").write_text("Metadata-Version: 2.4\nName: git-quint-diff\n"
                                   f"Version: {VERSION}\nRequires-Python: >=3.8\n"
                                   "Summary: Source-bound comparisons of committed Quint models\n"
                                   "Project-URL: Source, https://github.com/micha/git-quint-diff\n"
                                   f"{license_headers}\n", encoding="utf-8")
    (info / "WHEEL").write_text("Wheel-Version: 1.0\nGenerator: git-quint-diff/build-wheel\n"
                                f"Root-Is-Purelib: false\nTag: {tag}\n", encoding="utf-8")
    (info / "entry_points.txt").write_text("[console_scripts]\ngit-quint-diff = git_quint_diff:main\n",
                                           encoding="utf-8")
    return base, info, f"{PACKAGE}-{VERSION}-{tag}.whl", sources


def wheel_file(name, executable=False):
    entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
    entry.compress_type = ZIP_DEFLATED
    return entry


def write_wheel(base, info, destination):
    rows = io.StringIO(newline="")
    record = csv.writer(rows, lineterminator="\n")
    with ZipFile(destination, "w") as archive:
        for path in sorted(base.rglob("*"), key=lambda path: (path.is_relative_to(info), path.as_posix())):
            if not path.is_file():
                continue
            name = path.relative_to(base).as_posix()
            entry = wheel_file(name, executable=bool(path.stat().st_mode & stat.S_IXUSR))
            digest = hashlib.sha256()
            with path.open("rb") as source, archive.open(entry, "w") as target:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    target.write(chunk)
            integrity = base64.urlsafe_b64encode(digest.digest()).decode("ascii").rstrip("=")
            record.writerow((name, "sha256=" + integrity, entry.file_size))
        name = (info / "RECORD").relative_to(base).as_posix()
        record.writerow((name, "", ""))
        archive.writestr(wheel_file(name), rows.getvalue())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=PLATFORMS)
    parser.add_argument("--out-dir", type=Path, default=Path("dist"))
    parser.add_argument("--cache-dir", type=Path, help="reuse downloads, verifying every digest on every build")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("the wheel builder requires Python 3.12 or newer")
    if (platform.system(), platform.machine()) != PLATFORMS[args.platform][:2]:
        parser.error(f"{args.platform} requires a native build host")
    pins = json.loads((HERE / "payloads.json").read_text(encoding="utf-8"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.out_dir.resolve()) as directory:
        scratch = Path(directory)
        cache = args.cache_dir or (scratch / "downloads")
        cache.mkdir(parents=True, exist_ok=True)
        base, info, name, sources = stage(scratch, cache, args.platform, pins)
        write_wheel(base, info, scratch / name)
        for source_name, source in sources.items():
            shutil.copyfile(source, scratch / source_name)
            (scratch / source_name).replace(args.out_dir / source_name)
        (scratch / name).replace(args.out_dir / name)
        print(args.out_dir / name)


if __name__ == "__main__":
    main()
