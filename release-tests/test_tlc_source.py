"""The TLC companion is a reproducible, checked source subset, not an upstream tar copy."""

import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile


SPEC = importlib.util.spec_from_file_location(
    "tlc_source", Path(__file__).resolve().parents[1] / "packaging" / "tlc_source.py")
tlc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tlc)


class TlcSourceTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.pin = {"revision": "broken-in-fixture-only", "companion_sha256": "unused"}
        self.prefix = f"tlaplus-{self.pin['revision']}/"
        self.files = {name: f"preserved {name}\n".encode() for name in tlc.SOURCE_FILES}
        self.files[tlc.PROJECT + "src/tlc2/TLC.java"] = b"class TLC {}\n"
        self.excluded = {tlc.PROJECT + "lib/compiled.jar": b"PK\0",
                         tlc.PROJECT + "src/tla2sany/drivers/drivers - Shortcut.lnk": b"shortcut\0",
                         "toolbox/launch.exe": b"MZ\0"}
        self.output = self.root / "companion.tar"

    def make_jar(self, entries):
        path = self.root / "backend.jar"
        with ZipFile(path, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        return path

    def upstream(self, entries, year=0):
        path = self.root / "upstream.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, data in entries:
                item = tarfile.TarInfo(self.prefix + name)
                item.mtime, item.mode = year, 0o755
                if data is None:
                    item.type = tarfile.SYMTYPE
                    item.linkname = "nowhere"
                    archive.addfile(item)
                else:
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
        self.pin["upstream_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def pack(self, path):
        tlc.pack(path, self.output, self.pin)

    def test_normalized_and_source_only(self):
        entries = list((self.files | self.excluded).items())
        # Compute the expected deterministic tar independently of upstream ordering and bytes.
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in sorted(self.files.items()):
                member = tarfile.TarInfo(self.prefix + name)
                member.mtime, member.uid, member.gid, member.mode, member.size = 0, 0, 0, 0o644, len(data)
                archive.addfile(member, io.BytesIO(data))
        self.pin["companion_sha256"] = hashlib.sha256(buffer.getvalue()).hexdigest()
        self.pack(self.upstream(entries))
        self.assertEqual(self.output.read_bytes(), buffer.getvalue())
        self.pack(self.upstream(reversed(entries), year=1_000_000))
        self.assertEqual(self.output.read_bytes(), buffer.getvalue())

    def test_rejects_unpinned_input_or_output(self):
        upstream = self.upstream(self.files.items())
        self.output.write_bytes(b"prior companion")
        with self.assertRaisesRegex(ValueError, "TLC source companion: SHA-256 mismatch"):
            self.pack(upstream)
        self.pin["upstream_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "upstream TLC archive: SHA-256 mismatch"):
            self.pack(upstream)
        self.assertEqual(self.output.read_bytes(), b"prior companion")

    def test_rejects_changed_source_members(self):
        src = tlc.PROJECT + "src/"
        for name, data, diagnostic in (
            ("LICENSE", b"duplicate", "duplicate"),
            (src + "tlc2/Unexpected.java", None, "non-regular"),
            (src + "tlc2/Binary.java", b"\0\0", "binary content"),
            (src + "tlc2/vendor.jar", b"PK", "unreviewed file"),
            (src + "../License.txt", b"traversal", "unexpected upstream TLC path"),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, diagnostic):
                self.pack(self.upstream([*self.files.items(), (name, data)]))
            self.assertFalse(self.output.exists())

    def test_rebuilt_entries_must_match_backend_bytes_and_inventory(self):
        def emit(root, name, data):
            file = self.root / root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)

        name = "tlc2/TLC.class"
        helper = "tlc2/TestMPRecorder.class"
        module = "tla2sany/StandardModules/TLC.tla"
        emit("class", name, b"class")
        emit("test-class", helper, b"helper")
        emit("test-class", tlc.UNSHIPPED_HELPER, b"build input only")
        emit("src", module, b"module")
        entries = {name: b"class", helper: b"helper", module: b"module", "scala/Unrelated.class": b"x"}
        with patch.object(tlc, "REBUILD_COUNTS", (1, 1, 1)), contextlib.redirect_stdout(io.StringIO()):
            tlc.compare_outputs(self.root, self.make_jar(entries))
            with self.assertRaisesRegex(ValueError, "rebuilt TLC entry differs: tlc2/TLC.class"):
                tlc.compare_outputs(self.root, self.make_jar(entries | {name: b"other"}))
            with self.assertRaisesRegex(ValueError, "embedded TLC class inventory differs"):
                tlc.compare_outputs(self.root, self.make_jar(entries | {tlc.UNSHIPPED_HELPER: b"extra"}))
