#!/usr/bin/env python3
"""Check restored JVM notices in both installs and the wheel, plus companion parity."""

import argparse
from email.parser import BytesParser
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from zipfile import ZipFile


PACKAGING = Path(__file__).resolve().parents[1] / "packaging"
sys.path.insert(0, str(PACKAGING))
import jvm_legal


def check_directory(root, expected):
    files = {path.relative_to(root).as_posix(): path.read_bytes()
             for path in root.rglob("*") if path.is_file()}
    if files != expected:
        raise ValueError(f"missing, additional, or changed JVM materials: {root}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nix-profile", type=Path, required=True)
    parser.add_argument("--pipx-python", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--nix-sources", type=Path, required=True)
    parser.add_argument("--wheel-sources", type=Path, required=True)
    args = parser.parse_args()

    notices = jvm_legal.read_notices()
    expected = notices | {name: (jvm_legal.LEGAL / name).read_bytes()
                          for name in ("JVM-SOURCES.md", "notices.json", "sources.json")}
    nix_legal = args.nix_profile / "share/licenses/git-quint-diff"
    check_directory(nix_legal / "jvm", expected)
    pipx_legal = Path(subprocess.check_output([args.pipx_python, "-I", "-c", """
from importlib.metadata import distribution
installed = distribution('git-quint-diff')
(metadata,) = (path for path in installed.files if path.name == 'METADATA')
print(installed.locate_file(metadata).parent / 'licenses')
"""], text=True).strip())
    check_directory(pipx_legal / "jvm", expected)
    pins = json.loads((PACKAGING / "payloads.json").read_text(encoding="utf-8"))
    notice_digest = pins["notice_files"]["Apalache-NOTICE"][1]
    for root in (nix_legal, pipx_legal):
        with (root / "Apalache-NOTICE").open("rb") as stream:
            jvm_legal.verify(stream, notice_digest, "Apalache NOTICE")
        if (root / "Apalache-LICENSE").read_bytes() != (nix_legal / "Apalache-LICENSE").read_bytes():
            raise ValueError(f"different Apalache license: {root}")

    with ZipFile(args.wheel) as wheel:
        (metadata,) = (name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
        prefix = metadata.removesuffix("METADATA") + "licenses/"
        members = [member for member in wheel.namelist() if member.startswith(prefix + "jvm/")]
        if len(members) != len(expected) or {member.removeprefix(prefix + "jvm/"): wheel.read(member)
                                             for member in members} != expected:
            raise ValueError("missing, additional, or changed JVM materials in wheel ZIP")
        declared = BytesParser().parsebytes(wheel.read(metadata)).get_all("License-File") or []
        if sorted(name for name in declared if name.startswith("jvm/")) != sorted("jvm/" + name for name in expected):
            raise ValueError("wheel METADATA does not list the complete JVM notice bundle")
        for name in ("Apalache-LICENSE", "Apalache-NOTICE"):
            if wheel.read(prefix + name) != (nix_legal / name).read_bytes():
                raise ValueError(f"different {name} in wheel ZIP")

    source_pin = jvm_legal.pin_file("sources.json")
    companion = source_pin["companion"]
    for folder in (args.nix_sources, args.wheel_sources):
        with (folder / companion["file"]).open("rb") as stream:
            jvm_legal.verify(stream, companion["sha256"], str(folder / companion["file"]))
    with tarfile.open(args.nix_sources / companion["file"], mode="r:") as archive:
        expected_source_notices = {"jvm-priority-sources/" + name: data for name, data in notices.items()
                                   if name.split("/")[1] in source_pin["projects"]}
        actual_source_notices = {item.name: archive.extractfile(item).read() for item in archive
                                 if item.name.startswith("jvm-priority-sources/notices/")}
        if actual_source_notices != expected_source_notices:
            raise ValueError("source companion does not preserve notices for all its components")
    print(f"Verified {len(notices)} verbatim JVM notices in Nix, pipx and the wheel; "
          f"matching source companion {companion['sha256']}.")


if __name__ == "__main__":
    main()
