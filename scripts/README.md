# Script index

Command implementations are grouped by the domain that owns their behavior.
Run them from the `data-pipeline/` repository root with `python -m`.

| Package | Responsibility |
|---|---|
| `scripts.market` | JSearch extraction/replay, full pipeline, skill catalog review, skill loading, and career-skill aggregation. |
| `scripts.database` | Database migration and schema operations shared across domains. |
| `scripts.resume` | Resume extraction CLI and API-flow client. |
| `scripts.documents` | Reserved for learning-document workflows when those commands are implemented. |

Examples:

```powershell
python -m scripts.market.main --help
python -m scripts.market.run_pipeline --help
python -m scripts.market.review_skill_catalog_preview --summary
python -m scripts.database.migrate
```

Run a CV directly through preprocessing, the configured model provider, and
post-processing with:

```powershell
python -m scripts.resume.extract ..\backend\test_resume\01-fullstack-developer-en.pdf --summary
```

`python -m scripts.resume.try_api <path-to-cv>` calls a running backend API;
start that server from `backend/` first. Resume commands use `src/resume/`,
while API hosting and persistence stay in the backend.

Use the namespaced commands shown above in terminal instructions and
automation. The previous root-level command paths have been removed.
