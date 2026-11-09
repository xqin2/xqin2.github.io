# Xiang Qin — academic homepage

Public deployment for https://xqin2.github.io/. Editable website data and templates are maintained in the **private** `xqin2study/academic-homepage` repository.

GitHub Pages serves public `main` from `/(root)`; `.nojekyll` disables Jekyll. The site has About, Education and Research, a shared 404 page, and a contact-email footer.

## Website deployment

Make site content and design changes in the private source, then test and build. Automatic publication needs a write-enabled public-repo deploy key plus `PUBLIC_PAGES_DEPLOY_KEY` in the private repo; without that key, the private workflow fails after the successful build, and the public website does **not** update. See the private `docs/DEPLOYMENT.md`. GitHub Pages success alone does not prove the private source is synchronized.

The public `research/papers/` directory holds locally hosted PDF files. The private publisher excludes both that archive and `.github/` from destructive sync. The DCDS 2026 *journal edition* has the single canonical name `Generalized_SQG_1D_Self_Similar_2026.pdf`.

## PDF integrity and controlled import

`.github/workflows/mirror-papers.yml` performs a **read-only** integrity audit of all current PDF bytes and Research links. Journal versions have fixed SHA-256 references; preprint SHA-256 values are observed but not pinned. Each run preserves a separate JSON Actions artifact, without modifying Git files.

The old `.github/paper-mirror-status.json` and `.github/journal_pdf_status.json` are historical audit outputs only, not live attestations; preserve them.

Journal PDF installation is **manual-only**. Normal manual invocations only verify current files. The optional explicit `import_missing` action may install a file only when the target does not exist and downloaded content matches its pinned SHA-256; it must never overwrite current PDFs or historic status files.

Do not publish credentials or unpublished research, and confirm permissions for redistributing journal PDFs.
