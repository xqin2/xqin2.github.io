#!/usr/bin/env python3
"""Manual, non-overwriting import for pinned journal PDFs.

Only explicit workflow_dispatch can trigger this code. A completed journal PDF
is never overwritten or deleted, even when its hash differs from the pin.
Historical status files are never modified; reports live outside the repo.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 27 * 1024 * 1024
PDF_NAME = re.compile(r"[A-Za-z0-9_-]+\.pdf\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_pdf(data: bytes) -> bool:
    return 5120 <= len(data) <= MAX_BYTES and data.startswith(b"%PDF-") and b"%%EOF" in data[-4096:]


def download(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS PDF sources are accepted")
    request = Request(url, headers={"User-Agent": "XiangQinHomepage/1.0", "Accept": "application/pdf,*/*;q=0.5"})
    with urlopen(request, timeout=60) as response:
        if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
            raise ValueError("Oversized response")
        result = response.read(MAX_BYTES + 1)
    if len(result) > MAX_BYTES:
        raise ValueError("Oversized response")
    return result


def install_absent(path: Path, record: dict) -> tuple[str, str]:
    """Create only if absent. os.link raises FileExistsError on a race."""
    errors: list[str] = []
    for url in record.get("sources", []):
        tmp_path = None
        try:
            data = download(url)
            if not valid_pdf(data) or len(data) != record["bytes"] or sha256(data) != record["sha256"]:
                errors.append("Source does not match pinned PDF: " + url)
                continue
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".journal-", suffix=".part", delete=False) as f:
                f.write(data)
                tmp_path = Path(f.name)
            try:
                os.link(tmp_path, path)  # no replacement of existing targets
                return "installed_missing", url
            except FileExistsError:
                return "concurrent_target_exists", "Target appeared during import"
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc)[:160])
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
    return "missing_import_failed", "; ".join(errors[:4])


def run(mode: str, root: Path = ROOT) -> dict:
    records = json.loads((root / ".github/journal_pdf_sources.json").read_text("utf-8"))
    if not isinstance(records, list):
        raise ValueError("Expected a list of journal pins")
    folder = root / "research/papers"
    if folder.is_symlink():
        raise ValueError("PDF archive must not be a symlink")
    if mode == "import_missing":
        folder.mkdir(parents=True, exist_ok=True)
    seen = set()
    rows = []
    for record in records:
        name, aid = record["filename"], record["arxiv"]
        if (not isinstance(name, str) or not PDF_NAME.fullmatch(name) or
                aid in seen or not isinstance(record["sha256"], str) or
                not SHA256.fullmatch(record["sha256"]) or
                type(record["bytes"]) is not int or record["bytes"] < 5120):
            raise ValueError("Invalid or duplicate journal entry: " + str(aid))
        seen.add(aid)
        target = folder / name
        detail = ""
        if target.is_symlink():
            status = "symlink_refused"
        elif target.exists():
            if not target.is_file():
                status = "not_regular_file"
            else:
                actual = target.read_bytes()
                detail = "Observed SHA-256: " + sha256(actual)
                status = ("journal_sha256_match" if
                          (valid_pdf(actual) and len(actual) == record["bytes"] and
                           sha256(actual) == record["sha256"]) else "journal_mismatch_preserved")
        elif mode == "import_missing":
            status, detail = install_absent(target, record)
        else:
            status = "missing"
        rows.append({
            "arxiv": aid, "filename": name, "status": status,
            "sha256_expected": record["sha256"], "size_expected": record["bytes"], "detail": detail,
        })
        print(aid, status, flush=True)
    return {
        "schema": "journal-manual-audit-v1",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": os.environ.get("GITHUB_SHA", "local"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "mode": mode,
        "ok": all(row["status"] in ("journal_sha256_match", "installed_missing") for row in rows),
        "records": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("audit", "import_missing"), default="audit")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = run(args.mode)
    content = json.dumps(result, indent=2) + "\n"
    if args.report:
        target = args.report.resolve()
        if target == ROOT or ROOT in target.parents:
            parser.error("Report location must be outside the repository")
        target.write_text(content, encoding="utf-8")
    else:
        print(content)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
