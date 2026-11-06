#!/usr/bin/env python3
"""Install only exact SHA256 matches for the owner's four journal-version PDFs.

The original file bytes are already separately retained in the Git history.
If a candidate source cannot be retrieved or differs, leave the live file intact.
"""
import hashlib
import json
import os
from pathlib import Path
import ssl
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".github/journal_pdf_sources.json"
REPORT = ROOT / ".github/journal_pdf_status.json"
DEST = ROOT / "research/papers"
MAX_BYTES = 27 * 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def download(url, insecure=False):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AcademicHomepage/1.0)",
            "Accept": "application/pdf,application/octet-stream;q=0.8,*/*;q=0.1",
        },
    )
    context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=60, context=context) as response:
        if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
            raise ValueError("Response exceeds the maximum PDF size")
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("Response exceeds the maximum PDF size")
    return payload


def attempt(record):
    target = DEST / record["filename"]
    expected = record["sha256"]
    if target.is_file() and sha256(target.read_bytes()) == expected:
        return "already_installed", None

    errors = []
    for source in record["sources"]:
        for insecure in (False, True) if source.startswith("https://users.cms.caltech.edu/") else (False,):
            try:
                payload = download(source, insecure=insecure)
                if len(payload) != record["bytes"]:
                    errors.append("size mismatch")
                    continue
                if not payload.startswith(b"%PDF-") or b"%%EOF" not in payload[-4096:]:
                    errors.append("invalid PDF")
                    continue
                if sha256(payload) != expected:
                    errors.append("SHA-256 mismatch")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
                    tmp.write(payload)
                    temporary = Path(tmp.name)
                temporary.replace(target)
                return "installed", None
            except (OSError, ValueError, urllib.error.URLError) as exc:
                errors.append(type(exc).__name__ + ": " + str(exc)[:140])
    return "retained_existing", "; ".join(errors[:4])


def main():
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(records) != 4 or len(set(r["arxiv"] for r in records)) != 4:
        raise ValueError("Expected four unique journal records")
    statuses = []
    for record in records:
        name = record["filename"]
        if not name.endswith(".pdf") or "/" in name or "\\" in name or ".." in name:
            raise ValueError("Invalid target name")
        status, error = attempt(record)
        entry = {
            "arxiv": record["arxiv"],
            "filename": name,
            "expected_sha256": record["sha256"],
            "status": status,
        }
        if error:
            entry["note"] = error
        statuses.append(entry)
        print(record["arxiv"], status, error or "", flush=True)
    REPORT.write_text(json.dumps(statuses, indent=2) + "\n", encoding="utf-8")
    with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as file:
        for r in statuses:
            file.write("- " + r["arxiv"] + ": " + r["status"] + "\n")
        file.write("Exact uploaded bytes are required. Failed downloads NEVER replace the existing PDF.\n")


if __name__ == "__main__":
    main()
