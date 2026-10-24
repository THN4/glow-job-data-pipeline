# Market domain

`src.market` owns the job-market pipeline and is the only domain implemented
end to end at this time.

| Package | Responsibility |
|---|---|
| `ingestion` | Query JSearch, save/replay raw responses, validate incoming records, and persist job postings. |
| `cleaning` | Clean provider fields and job descriptions, including date and location cleanup. |
| `normalization` | Deduplicate postings, normalize company names, and map job titles to configured careers. |
| `skill_extraction` | Extract evidence-backed skills from JDs, manage catalog candidates/review, match the shared catalog, and load job-skill rows. |
| `aggregation` | Calculate career-level skill-demand statistics from loaded postings. |
| `config` | Load market-specific search, validation, career, and logging settings. |

## Execution order

`src.market.pipeline.run_pipeline` orchestrates the market flow:

1. Start a JSearch run or replay saved raw responses.
2. Validate, clean, deduplicate, normalize company names, and map careers.
3. Extract skills from cleaned JDs and save resumable checkpoints.
4. Match canonical skills and aliases, score evidence, and load postings and
   matched skills into PostgreSQL.
5. Refresh the selected career-statistics date window.

See the detailed [Market end-to-end flow](../../docs/market/market-pipeline-flow.md)
for the input/output and persistence boundary of each stage.

`src.market.main.main` performs job processing and optional skill extraction.
Use `python -m scripts.market.main` for that CLI, or
`python -m scripts.market.run_pipeline` for the full market workflow including
loading and aggregation.

Unknown skill names stay in checkpoint data and are not silently inserted into
the catalog. Use the [repository architecture](../../docs/architecture/repository-architecture.md)
for the distinction between normal matching and catalog rebuild/review.
