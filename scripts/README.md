# Script index

Command implementations are grouped by the domain that owns their behavior.
Run them from the `data-pipeline/` repository root with `python -m`.

| Package | Responsibility |
|---|---|
| `scripts.market` | JSearch extraction/replay, full pipeline, skill catalog review, skill loading, and career-skill aggregation. |
| `scripts.database` | Database migration and schema operations shared across domains. |
| `scripts.resume` | Resume extraction CLI, API-flow client, and Gemini quality evaluator. |
| `scripts.documents` | Crawl/review/parse/chunk/load learning documents into the shared knowledge database. |

Examples:

```powershell
python -m scripts.market.main --help
python -m scripts.market.run_pipeline --help
python -m scripts.market.run_scheduled_pipeline --live --dry-run
python -m scripts.market.review_skill_catalog_preview --summary
python -m scripts.database.migrate
```

For the complete EC2 worker command, S3/local recovery, run journals and locking,
see the [scheduled Market pipeline guide](../docs/market/scheduled-pipeline-guide.md).
Its Linux wrapper is `scripts/market/run_scheduled_pipeline.sh`. The older
`run_scheduled_ingestion.sh` only starts extraction.

Run a CV directly through preprocessing, the configured model provider, and
post-processing with:

```powershell
python -m scripts.resume.extract ..\backend\test_cvs\01-fullstack-developer-en.pdf --summary
```

Check the resume gold-set manifest without making model calls, or explicitly
run the cases through Gemini and save a quality report:

```powershell
python -m scripts.resume.evaluate_samples --dry-run
python -m scripts.resume.evaluate_samples --run-model
```

The model run requires `RESUME_EXTRACTOR=gemini` and `GEMINI_API_KEY`; use
`--case <manifest-filename>` to limit the run. See
[`backend/test_cvs/README.md`](../../backend/test_cvs/README.md) for the report
fields and evaluation limitations.

`python -m scripts.resume.try_api <path-to-cv>` calls a running backend API;
start that server from `backend/` first. Resume commands use `src/resume/`,
while API hosting and persistence stay in the backend.

Use the namespaced commands shown above in terminal instructions and
automation. The previous root-level command paths have been removed.
