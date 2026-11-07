#!/usr/bin/env python3
"""Read-only audit of the published PDF archive; never download or replace PDFs.

The original .github/paper-mirror-status.json and journal_pdf_status.json are
historical workflow outputs, not authoritative current-file attestations.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(".github/papers.json")
JOURNALS = Path(".github/journal_pdf_sources.json")
HTML = Path("research/index.html")
PDF_DIR = Path("research/papers")
MIN_BYTES = 5 * 1024
MAX_BYTES = 26 * 1024 * 1024
ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}\Z")
PDF_NAME = re.compile(r"[A-Za-z0-9_-]+\.pdf\Z")


def _read_manifest(path: Path, id_key: str) -> dict[str, dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"Expected an array in {path}")
    indexed: dict[str, dict] = {}
    filenames: set[str] = set()
    for row in rows:
        aid = row[id_key]
        name = row["filename"]
        if not isinstance(aid, str) or not ARXIV_ID.fullmatch(aid):
            raise ValueError(f"Invalid arXiv ID in {path}: {aid!r}")
        if not isinstance(name, str) or not PDF_NAME.fullmatch(name):
            raise ValueError(f"Unsafe PDF filename in {path}: {name!r}")
        if aid in indexed or name in filenames:
            raise ValueError(f"Duplicate ID or filename in {path}: {aid}, {name}")
        indexed[aid] = row
        filenames.add(name)
    return indexed


def audit(root: Path, *, revision: str = "", run_id: str = "") -> dict:
    """Inspect bytes and links. This function performs no filesystem writes."""
    mirror = _read_manifest(root / MANIFEST, "id")
    journals = _read_manifest(root / JOURNALS, "arxiv")
    for aid, journal in journals.items():
        if aid not in mirror or mirror[aid]["filename"] != journal["filename"]:
            raise ValueError(f"Journal filename disagrees with mirror manifest: {aid}")
        if not re.fullmatch(r"[0-9a-f]{64}", journal["sha256"]):
            raise ValueError(f"Invalid expected journal SHA-256: {aid}")
        if type(journal["bytes"]) is not int or journal["bytes"] <= 0:
            raise ValueError(f"Invalid expected journal size: {aid}")

    pdf_dir = root / PDF_DIR
    if pdf_dir.is_symlink():
        raise ValueError("PDF archive directory must not be a symlink")
    html = (root / HTML).read_text(encoding="utf-8")
    linked = re.findall(r'href="([^"]+)"[^>]*>PDF</a>', html)
    expected_links = {
        "/research/papers/" + row["filename"] for row in mirror.values()
    }
    problems: list[str] = []
    if len(linked) != len(expected_links):
        problems.append(f"Expected {len(expected_links)} PDF buttons, found {len(linked)}")
    for url in sorted(expected_links):
        if linked.count(url) != 1:
            problems.append(f"Expected exactly one PDF button linking to {url}")
    for url in sorted(set(linked) - expected_links):
        problems.append(f"Unexpected PDF button: {url}")

    records: list[dict] = []
    for aid, row in mirror.items():
        name = row["filename"]
        journal = journals.get(aid)
        path = pdf_dir / name
        record = {
            "arxiv": aid,
            "filename": name,
            "version_class": "journal" if journal else "preprint",
            "local_url": "/research/papers/" + name,
            "link_count": linked.count("/research/papers/" + name),
            "status": "missing",
        }
        if journal:
            record["sha256_expected"] = journal["sha256"]
            record["size_expected"] = journal["bytes"]
        if path.is_symlink():
            record["status"] = "symlink_refused"
        elif path.is_file():
            if path.stat().st_size > MAX_BYTES:
                record["status"] = "oversize"
            else:
                payload = path.read_bytes()  # Full-file read, not a header-only check.
                size = len(payload)
                record["size_bytes"] = size
                record["sha256_observed"] = hashlib.sha256(payload).hexdigest()
                # Git's object ID helps correlate this audit with `git ls-tree`.
                record["git_blob_sha1"] = hashlib.sha1(
                    f"blob {size}\0".encode("ascii") + payload
                ).hexdigest()
                structure_ok = (
                    MIN_BYTES <= size <= MAX_BYTES
                    and payload.startswith(b"%PDF-")
                    and b"%%EOF" in payload[-4096:]
                )
                record["pdf_structure_ok"] = structure_ok
                if not structure_ok:
                    record["status"] = "invalid_pdf_structure"
                elif journal:
                    if size != journal["bytes"]:
                        record["status"] = "journal_size_mismatch"
                    elif record["sha256_observed"] != journal["sha256"]:
                        record["status"] = "journal_sha256_mismatch"
                    else:
                        record["status"] = "journal_sha256_match"
                else:
                    # An observed digest is NOT a pinned preprint-version attestation.
                    record["status"] = "preprint_structure_ok_unpinned"
        if record["link_count"] != 1:
            problems.append(f"Missing/duplicate webpage link for arXiv:{aid}")
        if record["status"] not in (
            "journal_sha256_match", "preprint_structure_ok_unpinned"
        ):
            problems.append(f"arXiv:{aid}: {record['status']}")
        records.append(record)

    unlisted = sorted(
        item.name for item in pdf_dir.glob("*.pdf")
        if item.name not in {row["filename"] for row in mirror.values()}
    )
    return {
        "schema": "research-pdf-integrity-v1",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": revision or os.environ.get("GITHUB_SHA", "unavailable"),
        "github_run_id": run_id or os.environ.get("GITHUB_RUN_ID", "local"),
        "historical_records_unmodified": [
            ".github/paper-mirror-status.json",
            ".github/journal_pdf_status.json",
        ],
        "ok": not problems,
        "records": records,
        "unlisted_pdf_files": unlisted,  # informational; e.g. retained old DCDS alias
        "errors": problems,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write report outside repository")
    args = parser.parse_args()
    try:
        result = audit(ROOT)
    except Exception as error:
        result = {
            "schema": "research-pdf-integrity-v1",
            "audited_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": os.environ.get("GITHUB_SHA", "unavailable"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "ok": False, "records": [],
            "errors": [f"Audit aborted: {type(error).__name__}: {error}"],
        }
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        destination = args.report.resolve()
        if destination == ROOT or ROOT in destination.parents:
            parser.error("Report must be saved outside the repository checkout")
        destination.write_text(encoded, encoding="utf-8")
    else:
        print(encoded)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write("### Read-only PDF archive audit\n")
            output.write(f"Commit: `{result['git_commit']}`; passed: **{result['ok']}**.\n")
            output.write("Journal: expected SHA-256 matched; preprints: only observed, unpinned hashes.\n")
            for error in result["errors"]:
                output.write(f"- {error}\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
