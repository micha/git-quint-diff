#!/usr/bin/env python3
"""Assemble and independently rebuild the source companion for the embedded TLC."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
PROJECT = "tlatools/org.lamport.tlatools/"
SOURCE_FILES = {"LICENSE", "README.md", "DEVELOPING.md"} | {PROJECT + name for name in (
    "README.md", "build.properties", "customBuild.xml", "project.properties", "logging.properties",
    "META-INF/MANIFEST.MF", "doc/License.txt", "javacc/tla+.jj", "lib/vendored-jars.json",
)}
HELPERS = (
    "tlc2/TestMPRecorder.java", "tlc2/tool/CommonTestCase.java",
    "tlc2/tool/liveness/ModelCheckerTestCase.java", "util/IsolatedTestCaseRunner.java",
    "tlc2/tool/liveness/TTraceModelCheckerTestCase.java",
)
# ModelCheckerTestCase needs this class to compile; upstream dist omits it.
UNSHIPPED_HELPER = "tlc2/tool/liveness/TTraceModelCheckerTestCase.class"
SOURCE_FILES.update(PROJECT + "test/" + name for name in HELPERS)
SOURCE_SUFFIXES = {".cfg", ".java", ".md", ".properties", ".sty", ".tla", ".txt", ".xsd"}
SOURCE_OTHER = {"tla2sany/README", "tla2tex/README", "tla2tex/words.all"}
OMITTED = {"model/.gitignore", "tla2sany/drivers/drivers - Shortcut.lnk", "tlc2/tool/fp/FPSetsIdxCalculationBits.jpg"}
BUILD_INPUTS = (
    "lib/javacc-4.0.jar", "lib/jacocoant.jar", "lib/javax.mail/mailapi-1.6.8.jar",
    "lib/jline/jline-terminal-3.25.0.jar", "lib/jline/jline-console-3.25.0.jar",
    "lib/jline/jline-builtins-3.25.0.jar", "lib/jline/jline-reader-3.25.0.jar",
    "lib/gson/gson-2.14.0.jar", "lib/lsp/org.eclipse.lsp4j.jsonrpc_0.21.1.v20230829-0012.jar",
    "lib/lsp/org.eclipse.lsp4j.debug_0.21.1.v20230829-0012.jar", "lib/prettier4j-0.3.2.jar",
    "lib/junit-4.12.jar", "lib/hamcrest-core-1.3.jar",
)
ANT_DIGESTS = (
    "763acda4a69588c9ea8817a952851ff0c2fc4bffa1d081c2565dc407f29d5794",
    "5c8551990307a032336d98ddaed549a39a689f07d4d4c6b950601bf22b3d6a1b",
)
CLASS_PREFIXES = ("formatter/", "model/", "org/apache/commons/math3/", "org/eclipse/xtext/",
                  "pcal/", "tla2sany/", "tla2tex/", "tlc2/", "util/")
MODULE_PREFIX = "tla2sany/StandardModules/"
REBUILD_COUNTS = (969, 6, 20)


def check_hash(stream, expected, label):
    actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"{label}: SHA-256 mismatch: {actual}")
    stream.seek(0)


def read_upstream(path, pin, select):
    """Read named files, never unpack the raw archive or follow its links."""
    found = {}
    with path.open("rb") as stream:
        check_hash(stream, pin["upstream_sha256"], "upstream TLC archive")
        with tarfile.open(fileobj=stream, mode="r:gz") as archive:
            prefix = f"tlaplus-{pin['revision']}/"
            for item in archive:
                if item.isdir():
                    continue
                name = item.name.removeprefix(prefix)
                if not item.name.startswith(prefix) or PurePosixPath(name).as_posix() != name or (
                    name.startswith("/") or ".." in PurePosixPath(name).parts
                ):
                    raise ValueError(f"unexpected upstream TLC path: {item.name}")
                if select(name):
                    if not item.isfile() or name in found:
                        raise ValueError(f"non-regular or duplicate TLC file: {item.name}")
                    found[name] = archive.extractfile(item).read()
    return found


def include_source(name):
    if name in SOURCE_FILES:
        return True
    prefix = PROJECT + "src/"
    if not name.startswith(prefix):
        return False
    name = name.removeprefix(prefix)
    if name in OMITTED:
        return False
    if PurePosixPath(name).suffix not in SOURCE_SUFFIXES and name not in SOURCE_OTHER:
        raise ValueError(f"unreviewed file in TLC src/: {name}")
    return True


def companion_name(pin):
    return f"tlaplus-{pin['revision']}-source.tar"


def pack(upstream, output, pin):
    files = read_upstream(upstream, pin, include_source)
    if not SOURCE_FILES <= files.keys():
        raise ValueError(f"missing TLC source files: {sorted(SOURCE_FILES - files.keys())}")
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as pending:
        temp = Path(pending.name)
        try:
            # Plain USTAR is independent of platform compression libraries and mtimes.
            with tarfile.open(fileobj=pending, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for name, data in sorted(files.items()):
                    data.decode("utf-8")
                    if b"\0" in data:
                        raise ValueError(f"binary content in TLC source file: {name}")
                    item = tarfile.TarInfo(f"tlaplus-{pin['revision']}/{name}")
                    item.mode, item.mtime, item.uid, item.gid = 0o644, 0, 0, 0
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
            pending.flush()
            with temp.open("rb") as stream:
                check_hash(stream, pin["companion_sha256"], "TLC source companion")
            pending.close()
            temp.chmod(0o644)
            temp.replace(output)
        finally:
            temp.unlink(missing_ok=True)


def compare_outputs(project, backend):
    def files(root, pattern):
        return {p.relative_to(root).as_posix(): p for p in root.rglob(pattern)}

    production = files(project / "class", "*.class")
    helpers = files(project / "test-class", "*.class")
    if helpers.pop(UNSHIPPED_HELPER, None) is None:
        raise ValueError(f"missing compiler output for {UNSHIPPED_HELPER}")
    modules = {n: p for n, p in files(project / "src", "*.tla").items() if n.startswith(MODULE_PREFIX)}
    if (len(production), len(helpers), len(modules)) != REBUILD_COUNTS or production.keys() & helpers.keys():
        raise ValueError("unexpected TLC rebuild inventory")
    with ZipFile(backend) as jar:
        names = jar.namelist()
        lookup = set(names)
        if len(names) != len(lookup):
            raise ValueError("duplicate member in backend JAR")
        shipped = {n for n in names if n.endswith(".class") and n.startswith(CLASS_PREFIXES)}
        if shipped != production.keys() | helpers.keys():
            raise ValueError("embedded TLC class inventory differs from the rebuild")
        for name, file in sorted((production | helpers | modules).items()):
            if name not in lookup or jar.read(name) != file.read_bytes():
                raise ValueError(f"rebuilt TLC entry differs: {name}")
    print(f"Matched {len(production)} production classes, {len(helpers)} test helper classes "
          f"and {len(modules)} TLC standard modules byte for byte.")


def verify(companion, upstream, backend, jdk, ant, ant_launcher, pin):
    for path, digest in zip((ant, ant_launcher), ANT_DIGESTS, strict=True):
        with path.open("rb") as stream:
            check_hash(stream, digest, path)
    env = {key: value for key, value in os.environ.items() if key not in (
        "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "JDK_JAVAC_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH",
    )}
    java = jdk / "bin/java"
    version = subprocess.run([java, "-version"], env=env, check=True, capture_output=True, text=True).stderr
    if 'version "17.0.21"' not in version or "Temurin-17.0.21+9" not in version:
        raise ValueError("the TLC rebuild requires Temurin 17.0.21+9")
    with tempfile.TemporaryDirectory() as scratch:
        with companion.open("rb") as stream:
            check_hash(stream, pin["companion_sha256"], "TLC source companion")
            with tarfile.open(fileobj=stream, mode="r:") as archive:
                archive.extractall(scratch, filter="data")
        project = Path(scratch) / f"tlaplus-{pin['revision']}" / PROJECT
        names = {PROJECT + name for name in BUILD_INPUTS}
        inputs = read_upstream(upstream, pin, names.__contains__)
        if inputs.keys() != names:
            raise ValueError(f"missing TLC build inputs: {sorted(names - inputs.keys())}")
        for name, data in inputs.items():
            path = project / name.removeprefix(PROJECT)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        subprocess.run([java, "-cp", str(ant) + os.pathsep + str(ant_launcher),
                        "org.apache.tools.ant.Main", "-f", "customBuild.xml", "clean", "compile"],
                       cwd=project, env=env, check=True)
        (project / "test-class").mkdir()
        subprocess.run([jdk / "bin/javac", "--release", "11", "-g", "-encoding", "UTF-8", "-Werror", "-cp",
                        os.pathsep.join(("class", "lib/junit-4.12.jar", "lib/hamcrest-core-1.3.jar")),
                        "-d", "test-class", *("test/" + name for name in HELPERS)], cwd=project, env=env, check=True)
        compare_outputs(project, backend)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack_parser = commands.add_parser("pack", help="build a normalized source-only tar")
    verify_parser = commands.add_parser("verify", help="rebuild the companion and compare it with the shipped JAR")
    for parser_, arguments in ((pack_parser, ("upstream", "companion")),
                               (verify_parser, ("upstream", "backend", "companion", "jdk", "ant", "ant_launcher"))):
        for argument in arguments:
            parser_.add_argument(argument, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    pin = json.loads((HERE / "payloads.json").read_text(encoding="utf-8"))["tlc_source"]
    if args.command == "pack":
        pack(args.upstream, args.companion, pin)
    else:
        verify(args.companion, args.upstream, args.backend, args.jdk, args.ant, args.ant_launcher, pin)


if __name__ == "__main__":
    main()
