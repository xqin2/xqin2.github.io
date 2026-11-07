"""Offline regression tests for the read-only PDF archive verifier."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from mirror_papers import audit


def fake_pdf(text: bytes) -> bytes:
    return b"%PDF-1.6\n" + text + b"X" * 6000 + b"\n%%EOF\n"


class TestReadOnlyArchive(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.meta = self.root / ".github"
        self.papers = self.root / "research" / "papers"
        self.meta.mkdir(parents=True)
        self.papers.mkdir(parents=True)
        self.journal = "Journal_Edition.pdf"
        self.preprint = "Preprint.pdf"
        self.journal_bytes = fake_pdf(b"Journal paper title / Version of Record")
        (self.papers / self.journal).write_bytes(self.journal_bytes)
        (self.papers / self.preprint).write_bytes(fake_pdf(b"Preprint title"))
        self.mirror = [
            {"id": "2308.01528", "filename": self.journal},
            {"id": "2611.06117", "filename": self.preprint},
        ]
        self.versions = [{
            "arxiv": "2308.01528", "filename": self.journal,
            "bytes": len(self.journal_bytes),
            "sha256": hashlib.sha256(self.journal_bytes).hexdigest(),
        }]
        self._save_manifests()
        self.html = self.root / "research" / "index.html"
        self._save_links()
        self.historical = {
            ".github/paper-mirror-status.json": b'{"status":"verified","size_bytes":812901}\n',
            ".github/journal_pdf_status.json": b'{"status":"retained_existing"}\n',
        }
        for name, content in self.historical.items():
            (self.root / name).write_bytes(content)

    def _save_manifests(self):
        (self.meta / "papers.json").write_text(json.dumps(self.mirror))
        (self.meta / "journal_pdf_sources.json").write_text(json.dumps(self.versions))

    def _save_links(self):
        self.html.write_text(
            '<ol><li><a href="/research/papers/' + self.journal + '">PDF</a></li>'
            '<li><a href="/research/papers/' + self.preprint + '">PDF</a></li></ol>'
        )

    def _observe(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in self.root.rglob("*") if p.is_file()
        }

    def test_matching_journal_has_pinned_sha_preprint_does_not(self):
        before = self._observe()
        report = audit(self.root, revision="test-commit", run_id="test-run")
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["git_commit"], "test-commit")
        journal, preprint = report["records"]
        self.assertEqual(journal["status"], "journal_sha256_match")
        self.assertEqual(journal["sha256_expected"], journal["sha256_observed"])
        self.assertEqual(preprint["status"], "preprint_structure_ok_unpinned")
        self.assertNotIn("sha256_expected", preprint)
        self.assertEqual(before, self._observe())

    def test_same_size_altered_journal_fails_and_is_not_overwritten(self):
        target = self.papers / self.journal
        altered = self.journal_bytes.replace(b"Journal paper", b"journal paper")
        self.assertEqual(len(altered), len(self.journal_bytes))
        target.write_bytes(altered)
        before = self._observe()
        report = audit(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["records"][0]["status"], "journal_sha256_mismatch")
        self.assertEqual(before, self._observe())

    def test_journal_size_mismatch_is_distinct_from_sha_mismatch(self):
        target = self.papers / self.journal
        target.write_bytes(self.journal_bytes + b"extra bytes")
        before = self._observe()
        report = audit(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["records"][0]["status"], "journal_size_mismatch")
        self.assertEqual(before, self._observe())

    def test_unlisted_pdf_alias_is_informational_and_never_deleted(self):
        (self.papers / "Old_Journal_Alias.pdf").write_bytes(self.journal_bytes)
        before = self._observe()
        report = audit(self.root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["unlisted_pdf_files"], ["Old_Journal_Alias.pdf"])
        self.assertEqual(before, self._observe())

    def test_missing_journal_never_triggers_arxiv_download_or_file_creation(self):
        (self.papers / self.journal).unlink()
        before = self._observe()
        report = audit(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["records"][0]["status"], "missing")
        self.assertEqual(before, self._observe())

    def test_pdf_structure_failure_is_reported_without_deletion(self):
        (self.papers / self.preprint).write_bytes(b"not a PDF" * 1500)
        before = self._observe()
        report = audit(self.root)
        self.assertFalse(report["ok"])
        self.assertEqual(report["records"][1]["status"], "invalid_pdf_structure")
        self.assertEqual(before, self._observe())

    def test_manifest_and_research_link_disagreement_fails_closed(self):
        self.html.write_text(self.html.read_text().replace(
            "/research/papers/" + self.journal,
            "/research/papers/Journal_Edition_old.pdf",
        ))
        before = self._observe()
        report = audit(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(any("Journal_Edition.pdf" in p for p in report["errors"]))
        self.assertEqual(before, self._observe())

    def test_journal_manifest_filename_mismatch_fails_before_access(self):
        self.versions[0]["filename"] = "Unexpected.pdf"
        self._save_manifests()
        with self.assertRaisesRegex(ValueError, "filename disagrees"):
            audit(self.root)

    def test_duplicate_ids_rejected(self):
        self.mirror.append(dict(self.mirror[0]))
        self._save_manifests()
        with self.assertRaisesRegex(ValueError, "Duplicate ID or filename"):
            audit(self.root)

    def test_no_version_rollback_when_existing_preprint_changes(self):
        new_content = fake_pdf(b"Preprint version 2, same logical paper")
        (self.papers / self.preprint).write_bytes(new_content)
        before = self._observe()
        report = audit(self.root)
        self.assertTrue(report["ok"])
        record = report["records"][1]
        self.assertEqual(record["status"], "preprint_structure_ok_unpinned")
        self.assertEqual(record["sha256_observed"], hashlib.sha256(new_content).hexdigest())
        self.assertEqual(before, self._observe())


if __name__ == "__main__":
    unittest.main()
