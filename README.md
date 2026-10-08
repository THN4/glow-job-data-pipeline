# Glow-Job Data Pipeline

This repository collects recent Thailand job postings and prepares structured job-market data for Glow-Job. The intended flow is JSearch extraction, raw response storage, validation, cleaning, deduplication, normalization, skill extraction, career-level aggregation, and PostgreSQL loading. User-specific features belong to other services.

The current pipeline can fetch JSearch results, preserve them as raw JSON under `data/raw/`, replay a complete saved run without calling the API, validate and clean job records, and deduplicate repeated postings while retaining query provenance and all distinct `apply_options` links. It normalizes company names using confirmed aliases and emits fuzzy candidates for review, then maps job titles to configured career categories while preserving the original title. Skill extraction with Gemini can be enabled explicitly after career mapping; extracted names are then matched against the reviewed PostgreSQL skill catalog. Company candidates are written to a run-specific CSV under `data/processed/company_match_candidates/`; unconfirmed company matches are not merged automatically. Unmapped or ambiguous careers remain in the output with their status. Invalid records, cleaning rejections, and pipeline counts are reported in the logs; raw responses remain available for review. The first PostgreSQL migration covers market ingestion, and the second adds the skill catalog; job-skill and aggregation tables will be added in later stages. The full scope is in [project-spec.md](doc/project-spec.md), and branch conventions are in [git-workflow.md](doc/git-workflow.md).

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

Replace the example run ID with a saved run. Omit `--skill-limit 2` to process every unique job. Run the database migration and `python -m scripts.seed_skill_catalog` first. Gemini reads the cleaned JD and returns raw skill names with supporting evidence. The pipeline matches exact canonical names and confirmed aliases from PostgreSQL; each result retains `skills` (raw), `normalized_skills` (matched), and `unmatched_skills` (review needed). Unmatched names are never assigned a guessed `skill_id`. New Gemini requests start at least 10 seconds apart by default; `--skill-request-interval 20` changes that spacing. Results are saved after each job in `data/processed/skill_extraction/<run_id>.json`; rerunning the same run skips completed jobs and retries failed ones. If Gemini still returns HTTP 429 after the SDK's built-in retries, the run stops so you can resume later with the same run ID. Each new request uses API quota. Request spacing helps with per-minute limits but cannot fix a daily quota or a token limit reached by a single request; check your project's active limits in Google AI Studio. To check extraction quality on three hand-written JDs, run `python -m scripts.evaluate_skill_extraction`; the report is saved in `data/processed/skill_evaluation/report.json`. These JSON files are local checkpoints for review, not database records.

## Local PostgreSQL

Docker Compose reads the `DB_*` settings from `.env` and keeps database files in a named Docker volume.

```powershell
docker compose up -d postgres
python -m scripts.migrate
python -m scripts.seed_reference_data
python -m scripts.seed_skill_catalog
docker compose exec postgres psql -U glowjob -d glowjob -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('core', 'market', 'system') ORDER BY schema_name;"
```

The seed command upserts configured career names and creates one `general` profile for each career, so market postings have a reference profile to point to. The verification command uses the default local database name and user from `.env.example`; adjust them if you changed `DB_NAME` or `DB_USER`. The same commands work in PowerShell and CMD. Migrations are tracked in `system.schema_migrations` and can be safely re-run; already-applied files are skipped. See [migrations/README.md](migrations/README.md) for the migration convention and [the pipeline DBML](doc/schemas/pipeline-schema.dbml) for the pipeline schema plan.

## Load job skills from a checkpoint

After skill extraction, load a saved run into PostgreSQL without another JSearch or Gemini request:

```shell
python -m scripts.migrate
python -m scripts.seed_reference_data
python -m scripts.seed_skill_catalog
python -m scripts.load_job_skills 20260927T172453146903Z
```

Replace the run ID with a file name under `data/processed/skill_extraction/` (without `.json`). The loader inserts or updates mapped postings, exact-name companies, and confirmed job-skill matches in one transaction. Completed extractions with no matched skills still load the posting; failed extractions and postings without a provider ID or mapped career remain only in the checkpoint. Unmatched skill names and query/run metadata stay in that checkpoint for review; the loader does not populate `market.job_search_matches` yet. Repeating the command updates existing rows instead of duplicating them. `importance_weight` uses the initial rule in the skill extraction spec. The loader calculates skill, requirement, and proficiency confidence from verified evidence and explicit cues, then calculates overall confidence when all three are available. Ambiguous or unsupported classifications retain `NULL` confidence for review.

## Aggregate career skill demand

After migration `004_create_career_skill_stats.sql`, load the saved skill run again so previously loaded postings receive `skill_extraction_completed=true`. Then refresh a posting-date window:

```shell
python -m scripts.migrate
python -m scripts.load_job_skills 20260927T172453146903Z
python -m scripts.aggregate_career_skills 2026-09-01 2026-09-30
```

The dates are inclusive UTC `posted_at` dates. Only completed extractions with a nonempty JD and a known `posted_at` enter the denominator, including jobs with no matched skills. The command replaces statistics for that window, so rerunning it does not duplicate rows; if no jobs qualify, that window has no statistics. It reports the number of eligible postings, career profiles, and saved skill statistics. `importance_tier` stays `unknown` until a reviewed threshold is defined. A small checkpoint produces a small sample; do not treat its percentages as market-wide estimates.

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
