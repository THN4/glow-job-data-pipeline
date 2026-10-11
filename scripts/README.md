# Script index

Command implementations are grouped by the domain that owns their behavior.
Run them from the repository root with `python -m`.

| Package | Responsibility |
|---|---|
| `scripts.market` | JSearch extraction/replay, full pipeline, skill catalog review, skill loading, and career-skill aggregation. |
| `scripts.database` | Database migration and schema operations shared across domains. |
| `scripts.resume` | Reserved for resume workflows when those commands are implemented. |
| `scripts.documents` | Reserved for learning-document workflows when those commands are implemented. |

Examples:

```powershell
python -m scripts.market.main --help
python -m scripts.market.run_pipeline --help
python -m scripts.market.review_skill_catalog_preview --summary
python -m scripts.database.migrate
```

Use the namespaced commands shown above in terminal instructions and
automation. The previous root-level command paths have been removed.
