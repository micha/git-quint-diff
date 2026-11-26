"""Release backend repacking does not change retained classes, resources or notices."""

import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from backend_resources import check_origins, check_resources, digest, read_inventory


PATH = Path(__file__).resolve().parents[1] / "packaging" / "repack-backend.py"
SPEC = importlib.util.spec_from_file_location("repack_backend", PATH)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


class BackendPayloadTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.retained = {
            "META-INF/": b"",
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\r\n\r\n",
            "META-INF/LICENSE_tla2tools.md": b"fixture notice",
            "META-INF/services/example.Provider": b"example.Implementation\n",
            "at/forsyte/apalache/io/quint/Quint.class": b"translator",
            "tlc2/TLC.class": b"checker",
            "tla2sany/StandardModules/TLC.tla": b"TLC standard module",
        }
        self.entries = self.retained | dict.fromkeys(backend.SOLVER_NATIVES | backend.ZSTD_NATIVES, b"native") | {
            "cvc5-libs/": b"",
            "io/github/cvc5/Solver.class": b"cvc5 Java binding",
            "com/microsoft/z3/Context.class": b"Z3 Java binding",
            "tools/aqua/turnkey/TurnKey.class": b"Z3 Java loader",
            "com/github/luben/zstd/Zstd.class": b"zstd Java binding",
        }
        self.enterContext(patch.object(backend, "REMOVED_TREE_COUNTS", {
            "cvc5-libs/": 7, "io/github/cvc5/": 1, "com/microsoft/z3/": 16,
            "tools/aqua/turnkey/": 1, "com/github/luben/zstd/": 1,
        }))

    def make_jar(self, names_and_data, name="upstream.jar", *, year=2024, compression=ZIP_DEFLATED):
        path = self.root / name
        with ZipFile(path, "w") as jar:
            for name, data in names_and_data:
                info = ZipInfo(name, (year, 6, 3, 2, 1, 0))
                info.comment = b"Upstream per-entry metadata"
                jar.writestr(info, data, compress_type=compression)
        return path

    def repack_fixture(self, source, dest):
        # Only repin the fixture's bytes; the real validation and rewrite run.
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        with patch.object(backend, "UPSTREAM_SHA256", digest):
            backend.repack(source, dest)

    def test_deterministic_repack_and_exact_retention(self):
        first = self.make_jar(self.entries.items())
        second = self.make_jar(reversed(list(self.entries.items())), "second.jar", year=2026, compression=ZIP_STORED)
        one, two = self.root / "one.jar", self.root / "two.jar"
        self.repack_fixture(first, one)
        self.repack_fixture(second, two)
        self.assertEqual(one.read_bytes(), two.read_bytes())
        with ZipFile(one) as jar:
            self.assertEqual(jar.namelist(), [backend.MANIFEST, *sorted(self.retained.keys() - {backend.MANIFEST})])
            self.assertEqual({name: jar.read(name) for name in jar.namelist()}, self.retained)
            for entry in jar.infolist():
                self.assertEqual(entry.compress_type, ZIP_STORED)
                self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(entry.comment, b"")

    def test_unpinned_input_does_not_replace_destination(self):
        source = self.make_jar(self.entries.items())
        dst = self.root / "prior.jar"
        dst.write_bytes(b"existing destination")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            backend.repack(source, dst)
        self.assertEqual(dst.read_bytes(), b"existing destination")

    def test_changed_inventory_is_rejected_even_with_a_new_pin(self):
        dst = self.root / "out.jar"
        for change, message in (
            (self.entries | {"other-platform/plugin.so": b"new native"}, "unexpected native inventory"),
            ({name: data for name, data in self.entries.items() if not name.endswith("aarch_64/cvc5jni.dll")},
             "unexpected native inventory"),
            (self.entries | {"io/github/cvc5/Another.class": b"changed dependency"}, "unexpected entry count"),
            (self.entries | {"META-INF/CERT.SF": b"signature"}, "signed upstream JAR"),
        ):
            with self.subTest(message=message):
                source = self.make_jar(change.items())
                with self.assertRaisesRegex(ValueError, message):
                    self.repack_fixture(source, dst)
                self.assertFalse(dst.exists())

    def test_resource_checks_distinguish_merged_sources_and_changed_payload(self):
        name = "META-INF/services/example.Provider"
        data = b"example.One\nexample.Two\n"
        row = digest(data), "distinct-lines", (("first", name), ("second", name))
        rows = {name: row}
        archive = self.make_jar([(name, data), ("example/One.class", b"ignored")])
        self.assertEqual(check_resources(archive, rows), {name: data})
        inputs = {"first": {name: b"example.One\r\n"}, "second": {name: b"example.Two\nexample.One"}}
        check_origins({name: data}, rows, inputs)
        with self.assertRaisesRegex(ValueError, "source evidence does not match"):
            check_origins({name: data}, {name: (row[0], row[1], row[2][::-1])}, inputs)
        with self.assertRaisesRegex(ValueError, "changed backend resource"):
            check_resources(self.make_jar([(name, b"changed")]), rows)
        with self.assertRaisesRegex(ValueError, "member inventory differs"):
            check_resources(self.make_jar([(name, data), ("unexpected.txt", b"")]), rows)

    def test_duplicate_entry_is_rejected(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            source = self.make_jar([*self.entries.items(), ("tlc2/TLC.class", b"duplicate")])
        with self.assertRaisesRegex(ValueError, "duplicate names"):
            self.repack_fixture(source, self.root / "out.jar")


@unittest.skipUnless(os.environ.get("QUINT_HOME"), "requires the pinned upstream backend from nix develop")
class PinnedBackendPayloadTest(unittest.TestCase):
    def test_pinned_jar_retains_every_other_entry(self):
        upstream = Path(os.environ["QUINT_HOME"]) / "apalache-dist-0.62.4/apalache/lib/apalache.jar"
        scratch = Path(self.enterContext(tempfile.TemporaryDirectory()))
        output = scratch / "repacked.jar"
        backend.repack(upstream, output)
        with output.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        self.assertEqual(digest, "1d2dab08ca132c1d7cac2ca0cc3c1f743525b18a51aef3c5d97a4d549d30d5cd")
        check_resources(output, read_inventory())
        with ZipFile(upstream) as original, ZipFile(output) as repacked:
            kept = set(repacked.namelist())
            self.assertEqual(len(kept), len(repacked.namelist()))
            removed = set(original.namelist()) - kept
            self.assertEqual(len(removed), 325)
            self.assertTrue(all(name in backend.ZSTD_NATIVES or name.startswith(tuple(backend.REMOVED_TREE_COUNTS))
                                for name in removed))
            self.assertFalse(any(backend.NATIVE_NAME.search(name) for name in kept))
            for name in sorted(kept):
                with original.open(name) as old, repacked.open(name) as new:
                    while True:
                        chunk = old.read(1024 * 1024)
                        if chunk != new.read(1024 * 1024):
                            self.fail(f"changed retained entry: {name}")
                        if not chunk:
                            break
