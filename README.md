# Glow-Job Data Pipeline

This repository collects recent Thailand job postings and prepares structured job-market data for Glow-Job. The intended flow is JSearch extraction, raw response storage, validation, cleaning, deduplication, normalization, skill extraction, career-level aggregation, and PostgreSQL loading. User-specific features belong to other services.

Postings with no usable publication date are retained when their other required fields are valid. They are stored with `posted_at = NULL` and `posted_at_status = 'unknown'`; relative dates that can be parsed are labeled `estimated`. Career statistics can use either `posted_at` (provider publication date) or `first_seen_at` (when our pipeline first collected the posting). The first-seen basis includes undated postings and describes when our pipeline discovered jobs; it cannot recreate market history from before collection began.

The current pipeline can fetch JSearch results, preserve them as raw JSON under `data/raw/`, replay a complete saved run without calling the API, validate and clean job records, and deduplicate repeated postings while retaining query provenance and all distinct `apply_options` links. It normalizes company names using confirmed aliases and emits fuzzy candidates for review, then maps job titles to configured career categories while preserving the original title. Skill extraction with Gemini keeps raw results in checkpoints; catalog rebuild suggestions are generated in a separate offline preview, and are not added to PostgreSQL automatically. `config/skills.yaml` supplies the bootstrap catalog for that preview and database seeding. Company candidates are written to a run-specific CSV under `data/processed/company_match_candidates/`; unconfirmed company matches are not merged automatically. Unmapped or ambiguous careers remain in the output with their status. Invalid records, cleaning rejections, and pipeline counts are reported in the logs; raw responses remain available for review. The full scope is in [project-spec.md](doc/project-spec.md), and branch conventions are in [git-workflow.md](doc/git-workflow.md).

## Local setup

Use Python 3.10 or newer.

### PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m src.main
# Replay an existing run (replace the value with a run folder name under data/raw/)
python -m src.main --replay-run-id 20260928T120000000000Z
python -m pytest
```

### Command Prompt (CMD)

```cmd
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
python -m src.main
rem Replay an existing run (replace the value with a run folder name under data/raw/)
python -m src.main --replay-run-id 20260928T120000000000Z
python -m pytest
```

Set credentials in `.env` as the corresponding integrations are added. Do not commit `.env`. Edit `config/pipeline.yaml` to configure `search` request parameters and `validation` thresholds; edit `config/careers.yaml` to add career search queries without changing Python code.

To extract skills from an existing raw run, set `GEMINI_API_KEY` in `.env` and run:

```shell
python -m src.main --replay-run-id 20260928T120000000000Z --extract-skills --skill-limit 2
```

Replace the example run ID with a saved run. Omit `--skill-limit 2` to process every unique job. Run the database migration and `python -m scripts.seed_skill_catalog` first. Gemini reads the cleaned JD and returns raw skill names with supporting evidence. The pipeline matches exact canonical names and confirmed aliases from PostgreSQL; each result retains `skills` (raw), `normalized_skills` (matched), and `unmatched_skills` (review needed). Unmatched names are never assigned a guessed `skill_id`. New Gemini requests start at least 10 seconds apart by default; `--skill-request-interval 20` changes that spacing. Results are saved after each job in `data/processed/skill_extraction/<run_id>.json`; rerunning the same run skips completed jobs and retries failed ones. A Gemini HTTP 429 currently stops the run without an automatic retry; successful checkpoint entries remain, so you can resume later with the same run ID. Each new request uses API quota. Request spacing helps with per-minute limits but cannot fix a daily quota or a token limit reached by a single request; check your project's active limits in Google AI Studio. To check extraction quality on three hand-written JDs, run `python -m scripts.evaluate_skill_extraction`; the report is saved in `data/processed/skill_evaluation/report.json`. These JSON files are local checkpoints for review, not database records.

## Local PostgreSQL

Docker Compose reads the `DB_*` settings from `.env` and keeps database files in a named Docker volume.

```powershell
docker compose up -d postgres
python -m scripts.migrate
python -m scripts.seed_reference_data
python -m scripts.seed_skill_catalog
docker compose exec postgres psql -U glowjob -d glowjob -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('core', 'market', 'system') ORDER BY schema_name;"
```

The seed command upserts configured career names and creates one `general` profile for each career, so market postings have a reference profile to point to. The verification command uses the default local database name and user from `.env.example`; adjust them if you changed `DB_NAME` or `DB_USER`. The same commands work in PowerShell and CMD. Migrations are tracked in `system.schema_migrations` and can be safely re-run; already-applied files are skipped. Migration `006` belongs to the earlier database-backed candidate resolver; the current rebuild preview is offline and does not use its review queue. See [migrations/README.md](migrations/README.md) for the migration convention and [the pipeline DBML](doc/schemas/pipeline-schema.dbml) for the pipeline schema plan.

## Load job skills from a checkpoint

To load skills that already match the current canonical catalog or its confirmed aliases:

```shell
python -m scripts.migrate
python -m scripts.seed_reference_data
python -m scripts.seed_skill_catalog
python -m scripts.load_job_skills 20260927T172453146903Z
```

Replace the run ID with a file name under `data/processed/skill_extraction/` (without `.json`). This command does not call Gemini or resolve unknown skill names. Unmatched skills remain in the checkpoint until the catalog rebuild has been reviewed and applied. Completed extractions with no matched skills still load the posting; failed extractions and postings without a provider ID or mapped career remain only in the checkpoint. The loader does not populate `market.job_search_matches` yet. Repeating the command updates existing rows instead of duplicating them. `importance_weight` uses the initial rule in the skill extraction spec. The loader calculates skill, requirement, and proficiency confidence from verified evidence and explicit cues, then calculates overall confidence when all three are available.

## Preview a skill-catalog rebuild

Build one read-only preview from all saved skill checkpoints and the bootstrap catalog:

```shell
python -m scripts.preview_skill_catalog_rebuild
```

The command writes `data/processed/skill_candidates/catalog_rebuild_preview.csv`. It deduplicates repeated postings across checkpoint runs, groups exact spelling/case variants, and flags phrases made of the same words in a different order (for example, `AI agent` and `agent AI`). Gemini suggestions are optional and remain proposals:

```shell
python -m scripts.preview_skill_catalog_rebuild --suggest-limit 100 --compare-database-catalog
```

`--compare-database-catalog` adds exact canonical/alias matches and approximate name matches from PostgreSQL using read-only queries. Approximate matches are hints for review, not proof that two names mean the same skill. `preview_status=ready_for_approval` means the suggestion passed the preview's evidence and support checks; it has not been written to PostgreSQL. `manual_review` identifies low-confidence, weakly supported, generic, compound, or possibly duplicate candidates. The optional Gemini step also compares proposed names across candidates and marks possible semantic duplicates for review. This preview does not change the database or extraction checkpoints. Suggestions and manual decisions in the existing output CSV are preserved by default; use `--fresh` only when you intentionally want to discard them.

Review candidates interactively, with the current DB catalog, aliases, similar names, LLM suggestion, and posting evidence shown together:

```shell
python -m scripts.review_skill_catalog_preview
```

To see the remaining counts without opening the reviewer, run `python -m scripts.review_skill_catalog_preview --summary`. By default it reviews candidates with a pending DB status, other `manual_review` rows, and candidates with an exact DB match, while skipping candidates that already have a resolved status in `core.skill_candidate_reviews`. Pass `--all-candidates` to include unresolved candidates still waiting for an LLM suggestion. Pass `--include-reviewed` only when you intentionally want to revisit a CSV-reviewed or DB-resolved candidate. Later candidates can map to canonical names previously marked `create_new` in the same CSV, which helps group duplicate candidates under one approved spelling. The command saves decisions to the preview CSV only; it does not write the database. See [skill-candidate-review-spec.md](doc/skill-candidate-review-spec.md) for the full process.

To print the full current DB canonical catalog separately from similarity hints, run `python -m scripts.review_skill_catalog_preview --list-catalog`. It includes categories, approved/provisional status, aliases, and whether each canonical name is in the bootstrap catalog.

To recall names you manually marked `create_new` in the review CSV, including whether each has been applied to DB, run `python -m scripts.review_skill_catalog_preview --list-saved-creations`.

## Rebuild the skill catalog from saved jobs

The clean rebuild backs up the skill tables and extraction checkpoints, re-extracts skills from the saved job descriptions, resets only skill catalog/review/link/statistics tables, then reloads matched job skills. It keeps postings, career profiles, and raw source data. High-confidence candidates that pass the preview checks are applied automatically; uncertain candidates stay in `core.skill_candidate_reviews` with their rationale and evidence for manual review. Existing manual decisions in the preview CSV are reused.

Inspect the proposed scope first:

```shell
python -m scripts.rebuild_skill_catalog_from_checkpoints --dry-run
```

Run the rebuild after reviewing the dry-run summary:

```shell
python -m scripts.rebuild_skill_catalog_from_checkpoints --apply
```

The command writes a timestamped backup under `data/processed/skill_catalog_backups/`. Gemini extraction and suggestions may take several minutes. If Gemini returns evidence that is not an exact quote, the rebuild keeps that job's prior completed extraction and reports the fallback count; invalid catalog mappings and conflicting categories for the same proposed canonical name go to manual review. Other extraction or suggestion errors stop before the database reset. Rerun the same command to resume completed extraction and suggestion work. Pending candidates can be inspected with:

```sql
SELECT candidate_name, resolution_status, suggested_skill_name,
       suggested_skill_category, confidence_level, job_count, occurrence_count,
       rationale, examples
FROM core.skill_candidate_reviews
WHERE resolution_status = 'pending_review'
ORDER BY job_count DESC, candidate_name;
```

The interactive preview reviewer continues to save manual decisions in the CSV; use the catalog rebuild command again to apply those saved decisions. Split decisions replace the compound extracted phrase with the selected components in a transformed checkpoint copy under the timestamped backup; the original extraction checkpoints remain unchanged. The rebuilt job-skill links use the split components, and the review queue records the candidate as `split_applied`.

## Aggregate career skill demand

After applying the database migrations, load the saved skill run again so previously loaded postings receive `skill_extraction_completed=true`. Then refresh a date window using the desired date basis:

```shell
python -m scripts.migrate
python -m scripts.load_job_skills 20260927T172453146903Z
python -m scripts.aggregate_career_skills 2026-09-01 2026-09-30 --date-basis first_seen_at
```

The dates are inclusive UTC dates. By default, the command uses `posted_at`, so jobs without a known publication date are excluded. Pass `--date-basis first_seen_at` to group jobs by when this pipeline first collected them; this includes undated postings and keeps first-seen time fixed across later runs. The command replaces statistics for that window and basis, so rerunning it does not duplicate rows. It reports eligible postings, career profiles, and skill statistics. `importance_tier` stays `unknown` until a reviewed threshold is defined. A small sample produces uncertain percentages; first-seen trends become useful after repeated collections and cannot recreate historical observations that were never captured.

## Run the local pipeline in one command

After running migrations and seeding careers and skills, replay a saved raw run, load its completed skills, and refresh one UTC posting-date window:

```shell
python -m scripts.run_pipeline --replay-run-id 20260927T172453146903Z --replay-query-count 6 --start-date 2026-09-01 --end-date 2026-09-30 --date-basis first_seen_at --skill-limit 2
```

The example's first two jobs already have completed skill extraction results, so replay skips JSearch and does not repeat those extraction requests. Unknown skill names remain in the extraction checkpoint for the separate catalog preview and review flow. That older raw run contains six queries; `--replay-query-count 6` preserves its completeness check after new careers are added to the configuration. New runs use the current query count automatically. Replay may call Gemini for jobs beyond the completed extraction checkpoint, but it does not resolve skill candidates or write new skills to PostgreSQL. Omit `--skill-limit` to process the full raw run; a limit selects the first N career-mapped jobs overall, not N jobs per career. A limit smaller than an existing checkpoint is rejected to protect saved progress.

To start a new run with JSearch and Gemini, use `--live` instead of `--replay-run-id`:

```shell
python -m scripts.run_pipeline --live --start-date 2026-09-01 --end-date 2026-09-30 --date-basis first_seen_at
```

The command prints the run ID and per-stage counts. If skill extraction is incomplete, it stops before loading and aggregation; successful jobs remain in the checkpoint so you can resume with `--replay-run-id <run_id>`. The aggregation window includes every eligible posting currently loaded in the database, including postings from earlier runs. Run `python -m scripts.seed_reference_data` after adding careers and before loading their postings. The current six-career configuration makes 14 JSearch search queries per live run, requesting up to two pages per query, followed by Gemini requests for jobs that pass validation. Scheduling, cloud storage, and monitoring are separate later tasks.

## Layout

- `src/extract/`: provider clients and query building
- `src/validation/`: raw job checks
- `src/transform/`: cleaning, deduplication, and normalization
- `src/skills/`: skill extraction and aggregation
- `src/load/`: PostgreSQL access and repositories
- `src/storage/`: raw response storage
- `src/models/`: shared data models
- `src/config/`: settings and logging
- `config/`: editable career and pipeline settings
- `data/raw/`, `data/processed/`: local data directories, excluded from Git
- `migrations/`, `scripts/`, `tests/`: database migrations, helpers, and tests
