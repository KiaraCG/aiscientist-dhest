"""Release guards: only allowlisted code/templates and fixed synthetic examples."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from zipfile import ZipFile
import make_shareable_zip as pack

ROOT=Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'release'
        self.root.mkdir()
        names=[s for s in (ROOT/'PACKAGE_FILES.txt').read_text().splitlines() if s and not s.startswith('#')]
        for name in names:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)

    def test_clean_release_has_only_placeholder_env(self):
        data=pack.payloads(self.root)
        self.assertIn('.env.example',data)
        self.assertFalse(any(Path(n).name=='.env' for n in data))

    def test_private_workspace_not_selected(self):
        (self.root/'.env').write_text('private local configuration, not for distribution')
        (self.root/'private').mkdir();(self.root/'private/real_scan.pdf').write_bytes(b'private')
        data=pack.payloads(self.root)
        self.assertNotIn('.env',data);self.assertNotIn('private/real_scan.pdf',data)

    def test_adding_env_to_allowlist_fails(self):
        p=self.root/'PACKAGE_FILES.txt';p.write_text(p.read_text()+'.env\n')
        (self.root/'.env').write_text('not for sharing')
        with self.assertRaisesRegex(ValueError,'Forbidden'):pack.payloads(self.root)

    def test_modified_env_example_fails(self):
        (self.root/'.env.example').write_text('changed placeholder file')
        with self.assertRaisesRegex(ValueError,'changed'):pack.payloads(self.root)

    def test_replaced_example_pdf_fails(self):
        (self.root/'examples/minimal_exam/RawExams/Exam001.pdf').write_bytes(b'%PDF-not-the-synthetic-fixture')
        with self.assertRaisesRegex(ValueError,'changed'):pack.payloads(self.root)

    def test_symlink_rejected(self):
        p=self.root/'score_exams.py';p.unlink();p.symlink_to(ROOT/'score_exams.py')
        with self.assertRaisesRegex(ValueError,'Symlink'):pack.payloads(self.root)

    def test_path_traversal_rejected(self):
        p=self.root/'PACKAGE_FILES.txt';p.write_text(p.read_text()+'../outside.py\n')
        with self.assertRaisesRegex(ValueError,'Unsafe'):pack.payloads(self.root)

    def test_private_key_marker_rejected(self):
        p=self.root/'score_exams.py'
        # Construct a fake recognizable marker at runtime, not an actual key.
        p.write_text(p.read_text()+'\n# '+'-----BEGIN '+'PRIVATE KEY-----'+'\n')
        with self.assertRaisesRegex(ValueError,'credential'):pack.payloads(self.root)


if __name__=='__main__':unittest.main()
