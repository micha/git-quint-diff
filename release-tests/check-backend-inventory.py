#!/usr/bin/env python3
"""Check the retained backend's Maven class inventory against local, pinned JARs."""

import argparse
import csv
import hashlib
from pathlib import Path
from zipfile import ZipFile


INVENTORY = Path(__file__).resolve().parents[1] / "docs" / "jvm-backend-maven.tsv"
BACKEND_SHA256 = "1d2dab08ca132c1d7cac2ca0cc3c1f743525b18a51aef3c5d97a4d549d30d5cd"


def check_sha256(path, expected):
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch: {path}")


def classes(path):
    with ZipFile(path) as jar:
        result = {}
        for name in jar.namelist():
            if name.endswith(".class") and name.rsplit("/", 1)[-1] != "module-info.class":
                if name in result:
                    raise ValueError(f"duplicate class in {path}: {name}")
                result[name] = hashlib.sha256(jar.read(name)).digest()
        return result


def verify(backend, maven):
    check_sha256(backend, BACKEND_SHA256)
    shipped = classes(backend)
    matched = set()
    coordinates = set()
    with INVENTORY.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            coordinate = row["coordinate"]
            if coordinate in coordinates:
                raise ValueError(f"duplicate coordinate: {coordinate}")
            coordinates.add(coordinate)
            group, artifact, version = coordinate.split(":")
            directory = maven.joinpath(*group.split("."), artifact, version)
            binary = directory / f"{artifact}-{version}.jar"
            check_sha256(binary, row["binary_jar_sha256"])
            check_sha256(directory / f"{artifact}-{version}-sources.jar", row["source_jar_sha256"])
            candidates = classes(binary)
            exact = {name for name, digest in candidates.items() if shipped.get(name) == digest}
            if (len(exact), len(candidates)) != (int(row["matching_classes"]), int(row["artifact_classes"])):
                raise ValueError(f"class count mismatch: {coordinate}")
            if matched & exact:
                raise ValueError(f"overlapping class evidence: {coordinate}: {sorted(matched & exact)}")
            matched.update(exact)
    if (len(coordinates), len(matched), len(shipped)) != (99, 26_316, 29_531):
        raise ValueError("backend class inventory totals changed")
    print(f"{len(coordinates)} Maven coordinates matched {len(matched)}/{len(shipped)} backend classes.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", type=Path, help="the trimmed Apalache/TLC JAR")
    parser.add_argument("maven", type=Path, help="local directory with the Maven Central URL layout")
    args = parser.parse_args()
    try:
        verify(args.backend, args.maven)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
