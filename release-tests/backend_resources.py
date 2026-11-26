#!/usr/bin/env python3
"""Verify the trimmed JAR's non-class members and, optionally, their pinned inputs."""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import tarfile
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/jvm-backend-resources.tsv"
GENERATED = {"META-INF/MANIFEST.MF", "META-INF/javamail.default.address.map"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check_file(path, expected):
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch: {path}")


def read_inventory(path=INVENTORY):
    rows = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            name, mode = row["member"], row["evidence"]
            source = row["sources"]
            refs = () if source == "-" else tuple(tuple(ref.split("#", 1)) for ref in source.split(";"))
            if name in rows or any(len(ref) != 2 or not all(ref) for ref in refs):
                raise ValueError(f"duplicate resource or malformed source: {name}")
            if mode == "generated":
                if name not in GENERATED or refs:
                    raise ValueError(f"unknown generated resource: {name}")
            elif mode not in {"exact", "distinct-lines"} or not refs or name in GENERATED:
                raise ValueError(f"unsupported resource evidence: {name}")
            rows[name] = (row["sha256"], mode, refs)
    if Counter(item[1] for item in rows.values()) != {"exact": 308, "distinct-lines": 8, "generated": 2}:
        raise ValueError("unexpected resource evidence totals")
    return rows


def check_resources(backend, rows):
    with ZipFile(backend) as jar:
        entries = [item.filename for item in jar.infolist() if not item.is_dir()
                   and not item.filename.endswith(".class")]
        if set(entries) != rows.keys() or len(entries) != len(rows):
            raise ValueError("backend non-class member inventory differs")
        shipped = {name: jar.read(name) for name in entries}
    for name, (expected, _, _) in rows.items():
        if digest(shipped[name]) != expected:
            raise ValueError(f"changed backend resource: {name}")
    return shipped


def archive_members(path, sha256, prefix, names):
    check_file(path, sha256)
    found = {}
    with tarfile.open(path, "r|gz") as archive:
        for item in archive:
            if not item.name.startswith(prefix):
                continue
            name = item.name.removeprefix(prefix)
            if name not in names:
                continue
            if name in found or not item.isfile():
                raise ValueError(f"duplicate or non-regular source member: {path}: {name}")
            found[name] = archive.extractfile(item).read()
    if found.keys() != names:
        raise ValueError(f"missing source members: {path}: {sorted(names - found.keys())}")
    return found


def source_inputs(rows, maven, apalache, tlc):
    required = defaultdict(set)
    for _, _, refs in rows.values():
        for coordinate, name in refs:
            required[coordinate].add(name)
    pins = json.loads((ROOT / "packaging/payloads.json").read_text(encoding="utf-8"))
    tlc_pin = pins["tlc_source"]
    inputs = {
        "apalache": archive_members(apalache, pins["backend_sources"]["apalache-0.62.4-source.tar.gz"][1],
                                    "apalache-0.62.4/", required.pop("apalache")),
        "tlc": archive_members(tlc, tlc_pin["upstream_sha256"], f"tlaplus-{tlc_pin['revision']}/", required.pop("tlc")),
    }
    with (ROOT / "docs/jvm-backend-maven.tsv").open(encoding="utf-8", newline="") as stream:
        pins = {row["coordinate"]: row["binary_jar_sha256"] for row in csv.DictReader(stream, delimiter="\t")}
    for coordinate, names in required.items():
        group, artifact, version = coordinate.split(":")
        binary = maven.joinpath(*group.split("."), artifact, version, f"{artifact}-{version}.jar")
        check_file(binary, pins[coordinate])
        with ZipFile(binary) as jar:
            listed = jar.namelist()
            if len(set(listed)) != len(listed):
                raise ValueError(f"duplicate member in source JAR: {binary}")
            inputs[coordinate] = {name: jar.read(name) for name in names}
    return inputs


def check_origins(shipped, rows, inputs):
    for name, (_, mode, refs) in rows.items():
        contents = [inputs[coordinate][member] for coordinate, member in refs]
        if mode == "exact":
            matches = all(data == shipped[name] for data in contents)
        elif mode == "distinct-lines":
            lines = dict.fromkeys(line for data in contents for line in data.splitlines())
            matches = b"\n".join(lines) + b"\n" == shipped[name]
        elif name == "META-INF/javamail.default.address.map":
            # The matched TLC customBuild.xml creates it using Ant <touch>.
            matches = shipped[name] == b""
        else:
            # Assembly-generated main manifest; not a copy of any supplying JAR's manifest.
            manifest = shipped[name].splitlines()
            matches = (b"Implementation-Version: 0.62.4" in manifest and
                       b"Main-Class: at.forsyte.apalache.tla.Tool" in manifest)
        if not matches:
            raise ValueError(f"resource source evidence does not match: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", type=Path)
    parser.add_argument("--inputs", type=Path, nargs=3, metavar=("MAVEN_DIR", "APALACHE_TAR_GZ", "TLC_TAR_GZ"),
                        help="also verify origins against the local Maven layout and two upstream source archives")
    args = parser.parse_args()
    try:
        rows = read_inventory()
        shipped = check_resources(args.backend, rows)
        if args.inputs:
            check_origins(shipped, rows, source_inputs(rows, *args.inputs))
        print(f"Verified {len(rows)} non-class backend members" + (" and their pinned input evidence." if args.inputs else "."))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
