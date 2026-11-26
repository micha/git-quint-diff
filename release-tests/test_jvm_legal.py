"""Offline controls for byte-pinned JVM notices and source companions."""

import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from zipfile import ZipFile


PACKAGING = Path(__file__).resolve().parents[1] / "packaging"
sys.path.insert(0, str(PACKAGING))
import jvm_legal as legal


def digest(data):
    return hashlib.sha256(data).hexdigest()


def upstream(members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, content in members:
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    stream.seek(0)
    return stream


def source_jar(entries):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for name, source in entries.items():
            archive.writestr(name, source)
    stream.seek(0)
    return stream


class JvmLegalTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_installed_bundle_preserves_bytes_and_checks_inventory(self):
        bundle = self.root / "in"
        target = self.root / "out"
        name = "notices/Test/LICENSE"
        license_text = b"fixture license\r\n"
        notice = bundle / name
        notice.parent.mkdir(parents=True)
        notice.write_bytes(license_text)
        for extra in ("JVM-SOURCES.md", "sources.json"):
            (bundle / extra).write_text("fixture", encoding="utf-8")
        (bundle / "notices.json").write_text(json.dumps({"schema_version": 1, "files": [
            {"path": name, "sha256": digest(license_text)}]}), encoding="utf-8")
        legal.install(target, bundle)
        self.assertEqual((target / name).read_bytes(), license_text)
        notice.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            legal.install(target, bundle)
        notice.write_bytes(license_text)
        extra = notice.with_name("NOTICE")
        extra.write_bytes(b"untracked by manifest")
        with self.assertRaisesRegex(ValueError, "differ from the manifest inventory"):
            legal.install(target, bundle)
        extra.unlink()
        notice.unlink()
        notice.symlink_to(target / name)
        with self.assertRaisesRegex(ValueError, "invalid or duplicate"):
            legal.install(target, bundle)

    def test_source_tree_skips_unrelated_binary_and_rejects_unexpected_paths(self):
        pin = {"root": "source", "files": ["LICENSE"], "prefixes": ["src/"]}
        entries = [("source/LICENSE", b"example\n"), ("source/src/Code.java", b"class Code {}\n"),
                   ("source/test/input.jar", b"\0archive fixture")]
        self.assertEqual(legal.read_tree(upstream(entries), pin).keys(), {"LICENSE", "src/Code.java"})
        for path, message in (("source/src/Code.java", "duplicate"), ("source/src/Bin.java", "non-text"),
                              ("source/../escape", "invalid JVM materials path"), ("other/LICENSE", "source root")):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, message):
                legal.read_tree(upstream([*entries, (path, b"\0")]), pin)
        with self.assertRaisesRegex(ValueError, "incomplete JVM source selection"):
            legal.read_tree(upstream(entries[1:]), pin)

    def test_maven_source_must_match_except_for_recognized_overlays(self):
        existing, version, generated = "p/Existing.java", "p/Version.java", "p/Generated.java"
        tree = {"src/" + existing: b"// existing\r\n", "src/" + version: b'"${mail.version}"\n'}
        entries = {existing: b"// existing\n", version: b'"1.2.3"\n', generated: b"class Generated {}\n",
                   "p/.Generated.java._trace": b"\0generated trace"}
        pin = {"input": "example.jar", "sources": 3, "overlays": 2, "generated": {"prefix": "p/"},
               "substitution": {"member": version, "version": "1.2.3"}}
        self.assertEqual(legal.collect_published(source_jar(entries), pin, tree),
                         {name: entries[name] for name in (version, generated)})
        for changed in (entries | {existing: b"// different\n"}, entries | {version: b'"1.2.4"\n'},
                        {name: data for name, data in entries.items() if not name.endswith("._trace")}):
            with self.assertRaisesRegex(ValueError, "published source differs"):
                legal.collect_published(source_jar(changed), pin, tree)

    def test_tar_is_deterministic_and_digest_mismatch_keeps_prior_output(self):
        files = {"project/src/B.java": b"class B {}", "project/LICENSE": b"example license\n"}
        one, two = io.BytesIO(), io.BytesIO()
        legal.write_sources(one, files)
        legal.write_sources(two, dict(reversed(list(files.items()))))
        self.assertEqual(one.getvalue(), two.getvalue())
        one.seek(0)
        with tarfile.open(fileobj=one) as archive:
            items = archive.getmembers()
            self.assertEqual([m.name for m in items], ["jvm-priority-sources/" + name for name in sorted(files)])
            self.assertTrue(all((m.uid, m.gid, m.mode, m.mtime) == (0, 0, 0o644, 0) for m in items))
        bundle = self.root / "legal"
        (bundle / "notices/Test").mkdir(parents=True)
        (bundle / "notices/Test/LICENSE").write_bytes(b"notice")
        (bundle / "notices.json").write_text(json.dumps({"schema_version": 1, "files": [
            {"path": "notices/Test/LICENSE", "sha256": digest(b"notice")}]}), encoding="utf-8")
        dest = self.root / "sources.tar"
        dest.write_bytes(b"prior archive")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch: priority source companion"):
            legal.pack({}, dest, {"projects": {}, "companion": {"sha256": "0" * 64}}, bundle)
        self.assertEqual(dest.read_bytes(), b"prior archive")

    def test_checked_in_notice_bundle(self):
        names = legal.read_notices().keys()
        for project in legal.pin_file("sources.json")["projects"]:
            self.assertTrue(any(name.startswith(f"notices/{project}/") for name in names), project)
        for name in ("notices/logback-1.5.32/EPL-2.0.txt", "notices/servlet-6.0.0/Apache-2.0.txt",
                     "notices/mail-1.6.8/doc-files/speclicense.html", "notices/lsp4j-0.21.1/EPL-1.0.txt",
                     "notices/lsp4j-0.21.1/org.eclipse.lsp4j.jsonrpc/about.html"):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
