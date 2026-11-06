#!/usr/bin/env python3
"""Mirror verified public PDFs to GitHub Pages without introducing broken links.

Only files that pass PDF checks are linked locally. On any download failure, the
existing arXiv PDF link remains unchanged. Designed for GitHub Actions.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".github/papers.json"
STATUS = ROOT / ".github/paper-mirror-status.json"
HTML = ROOT / "research/index.html"
DEST = ROOT / "research/papers"
MAX_BYTES = 26 * 1024 * 1024
MIN_BYTES = 5 * 1024

# These names are fixed and intentionally do not depend on untrusted URL inputs.
PREFERRED_SOURCES = {
    "2611.06117": [
        "https://users.cms.caltech.edu/~hou/papers/Nonuniqueness_3DNSE_Viscous_Cascade_2026.pdf",
    ]
}


def verified_pdf(file_path: Path) -> bool:
    if not file_path.is_file():
        return False
    size = file_path.stat().st_size
    if not (MIN_BYTES <= size <= MAX_BYTES):
        return False
    with file_path.open("rb") as file:
        if not file.read(1024).startswith(b"%PDF-"):
            return False
        file.seek(max(0, size - 4096))
        if b"%%EOF" not in file.read():
            return False
    return True


def download_pdf(url: str, output: Path) -> tuple[bool, str]:
    temp = output.with_suffix(".pdf.part")
    temp.unlink(missing_ok=True)
    try:
        request = Request(
            url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; XiangQinAcademicHomepage/1.0; PDF archive)",
                "Accept": "application/pdf,*/*;q=0.7",
            }
        )
        with urlopen(request, timeout=50) as response, temp.open("wb") as out:
            # Protect the Actions worker from accidentally downloading huge files.
            if int(response.headers.get("Content-Length", 0)) > MAX_BYTES:
                return False, "PDF exceeds 26 MiB limit"
            size = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    return False, "PDF exceeds 26 MiB limit"
                out.write(chunk)
        if not verified_pdf(temp):
            return False, "Response was not a complete PDF"
        temp.replace(output)
        return True, f"validated {output.stat().st_size} bytes"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        return False, type(error).__name__ + ": " + str(error)[:160]
    finally:
        temp.unlink(missing_ok=True)


def sources_for(arxiv: str) -> list[str]:
    return [
        *PREFERRED_SOURCES.get(arxiv, []),
        "https://arxiv.org/pdf/" + arxiv,
        "https://export.arxiv.org/pdf/" + arxiv,
    ]


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    page = HTML.read_text(encoding="utf-8")
    DEST.mkdir(parents=True, exist_ok=True)
    if len(set(row["id"] for row in manifest)) != len(manifest):
        raise ValueError("Duplicate paper IDs in mirror manifest")
    entries = []
    for row in manifest:
        aid = row["id"]
        filename = row["filename"]
        if not re.fullmatch(r"\d{4}\.\d{4,5}", aid):
            raise ValueError("Invalid arXiv ID: " + aid)
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.pdf", filename):
            raise ValueError("Invalid PDF filename: " + filename)
        path = DEST / filename
        state = "verified" if verified_pdf(path) else "download_failed"
        errors = []
        if state != "verified":
            if path.exists():
                path.unlink()
            for source in sources_for(aid):
                ok, message = download_pdf(source, path)
                if ok:
                    state = "verified"
                    break
                errors.append(source + " (" + message + ")")
                time.sleep(1)
        arxiv_url = "https://arxiv.org/pdf/" + aid
        local_url = "/research/papers/" + filename
        old_link = '<a href="' + arxiv_url + '">PDF</a>'
        new_link = '<a href="' + local_url + '">PDF</a>'
        # Idempotent on repeated runs; only point locally to verified files.
        if state == "verified":
            if old_link in page:
                page = page.replace(old_link, new_link, 1)
            elif new_link not in page:
                raise ValueError("No PDF link for " + aid)
        else:
            if new_link in page:
                page = page.replace(new_link, old_link, 1)
        entries.append({
            "arxiv": aid,
            "filename": filename,
            "status": state,
            "size_bytes": path.stat().st_size if state == "verified" else 0,
            "errors": errors[-2:],
        })
        print(aid, state, filename, flush=True)
    # Every local PDF link must correspond to a verified local PDF.
    for local in re.findall(r'href="(/research/papers/[^"]+\.pdf)"', page):
        if not verified_pdf(ROOT / local.lstrip("/")):
            raise RuntimeError("Broken local PDF target: " + local)
    HTML.write_text(page, encoding="utf-8")
    STATUS.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    successes = sum(row["status"] == "verified" for row in entries)
    print(f"{successes}/{len(entries)} PDF mirrors verified", flush=True)
    if successes == 0:
        print("::warning::No valid PDFs mirrored; existing arXiv links have been retained.")
    with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as summary:
        summary.write(f"Verified PDF mirrors: **{successes}/{len(entries)}**.\n")
        summary.write("Unverified PDF links remain on arXiv; no broken self-hosted links are published.\n")


if __name__ == "__main__":
    main()
