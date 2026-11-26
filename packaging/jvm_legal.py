#!/usr/bin/env python3
"""Install pinned priority JVM notices and assemble the matching source companion."""

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from zipfile import ZipFile


LEGAL = Path(__file__).resolve().parent / "jvm-legal"
SOURCE_SUFFIXES = (".java", ".scala", ".xtend")


def safe_path(name):
    path = PurePosixPath(name)
    if path.as_posix() != name or path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts:
        raise ValueError(f"invalid JVM materials path: {name!r}")
    return path


def text(name, data, encoding="utf-8"):
    try:
        data.decode(encoding)
    except UnicodeDecodeError as error:
        raise ValueError(f"non-text JVM source member: {name}") from error
    if b"\0" in data:
        raise ValueError(f"non-text JVM source member: {name}")
    return data


def verify(stream, digest, name):
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or hashlib.file_digest(stream, "sha256").hexdigest() != digest:
        raise ValueError(f"JVM materials SHA-256 mismatch: {name}")
    stream.seek(0)


def pin_file(name, legal=LEGAL):
    pin = json.loads((legal / name).read_text(encoding="utf-8"))
    if pin["schema_version"] != 1:
        raise ValueError(f"unsupported JVM materials schema: {name}")
    return pin


def read_notices(legal=LEGAL):
    files = {}
    for item in pin_file("notices.json", legal)["files"]:
        name = item["path"]
        parts = safe_path(name).parts
        path = legal / name
        if len(parts) < 3 or parts[0] != "notices" or name in files or path.resolve() != path or not path.is_file():
            raise ValueError(f"invalid or duplicate JVM notice: {name}")
        with path.open("rb") as source:
            verify(source, item["sha256"], name)
            files[name] = source.read()
    found = {p.relative_to(legal).as_posix() for p in (legal / "notices").rglob("*")
             if p.is_symlink() or not p.is_dir()}
    if not files or found != files.keys():
        raise ValueError("JVM notice files differ from the manifest inventory")
    return files


def install(destination, legal=LEGAL):
    for name, data in read_notices(legal).items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name in ("JVM-SOURCES.md", "notices.json", "sources.json"):
        shutil.copyfile(legal / name, destination / name)


def read_tree(stream, tree):
    files = {}
    required = set(tree["files"])
    prefixes = tuple(tree["prefixes"])
    latin1 = set(tree.get("latin1", []))
    with tarfile.open(fileobj=stream, mode="r:gz") as archive:
        for item in archive:
            safe_path(item.name)
            if item.isdir():
                continue
            prefix = tree["root"] + "/"
            if not item.name.startswith(prefix):
                raise ValueError(f"unexpected JVM source root: {item.name}")
            name = item.name.removeprefix(prefix)
            if name not in required and not name.startswith(prefixes):
                continue
            if not item.isfile() or name in files:
                raise ValueError(f"non-regular or duplicate JVM source: {item.name}")
            files[name] = text(name, archive.extractfile(item).read(), "latin-1" if name in latin1 else "utf-8")
    if not (required | latin1) <= files.keys() or not all(
        any(name.startswith(prefix) for name in files) for prefix in prefixes
    ):
        raise ValueError(f"incomplete JVM source selection: {tree['root']}")
    return files


def collect_published(stream, pin, tree):
    """Verify published source against the tree; return only known build-produced sources."""
    overlays = {}
    n_sources = 0
    with ZipFile(stream) as archive:
        names = archive.namelist()
        lookup = set(names)
        if len(names) != len(lookup):
            raise ValueError(f"duplicate source JAR entry: {pin['input']}")
        for name in names:
            if not name.endswith(SOURCE_SUFFIXES):
                continue
            path = safe_path(name)
            n_sources += 1
            src = text(name, archive.read(name))
            normalized = src.replace(b"\r\n", b"\n")
            matches = [data.replace(b"\r\n", b"\n") for member, data in tree.items() if member.endswith("/" + name)]
            if normalized in matches:
                continue
            version_source = pin.get("substitution", {})
            generated = pin.get("generated", {})
            if name == version_source.get("member") and [normalized] == [
                data.replace(b"${mail.version}", version_source["version"].encode("ascii")) for data in matches
            ]:
                overlays[name] = src
            elif not matches and generated and name.startswith(generated["prefix"]) and name.endswith(".java") and (
                path.with_name("." + path.name + "._trace").as_posix() in lookup
            ):
                overlays[name] = src
            else:
                raise ValueError(f"published source differs from selected tree: {pin['input']}: {name}")
    if n_sources != pin["sources"] or len(overlays) != pin.get("overlays", 0):
        raise ValueError(f"unexpected source JAR inventory: {pin['input']}")
    return overlays


def source_members(inputs, pin, legal=LEGAL):
    @contextmanager
    def checked(name):
        with inputs[name].open("rb") as stream:
            verify(stream, pin["inputs"][name]["sha256"], name)
            yield stream

    files = {}
    for component, project in pin["projects"].items():
        tree = project["tree"]
        with checked(tree["input"]) as stream:
            upstream = read_tree(stream, tree)
        for name, data in upstream.items():
            files[f"{component}/{tree['root']}/{name}"] = data
        for release in project["published"]:
            with checked(release["input"]) as stream:
                for name, data in collect_published(stream, release, upstream).items():
                    files[f"{component}/published/{release['input'].removesuffix('-sources.jar')}/{name}"] = data
    for name, data in read_notices(legal).items():
        if PurePosixPath(name).parts[1] in pin["projects"]:
            files[name] = data
    return files


def write_sources(stream, files):
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(files.items()):
            item = tarfile.TarInfo("jvm-priority-sources/" + safe_path(name).as_posix())
            item.mode, item.mtime, item.uid, item.gid = 0o644, 0, 0, 0
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))


def pack(inputs, output, pin, legal=LEGAL):
    files = source_members(inputs, pin, legal)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as pending:
        temporary = Path(pending.name)
        try:
            write_sources(pending, files)
            pending.flush()
            with temporary.open("rb") as stream:
                verify(stream, pin["companion"]["sha256"], "priority source companion")
            pending.close()
            temporary.chmod(0o644)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install", help="install the verified notice bundle")
    install_parser.add_argument("destination", type=Path)
    pack_parser = commands.add_parser("pack", help="assemble the exact source tar from a directory of pinned inputs")
    pack_parser.add_argument("inputs", type=Path)
    pack_parser.add_argument("destination", type=Path, help="directory for the assembled companion")
    args = parser.parse_args()
    if args.command == "install":
        install(args.destination)
    else:
        pin = pin_file("sources.json")
        args.destination.mkdir(parents=True, exist_ok=True)
        pack({name: args.inputs / safe_path(name) for name in pin["inputs"]},
             args.destination / safe_path(pin["companion"]["file"]), pin)


if __name__ == "__main__":
    main()
