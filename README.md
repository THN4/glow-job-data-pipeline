# Glow-Job Data Pipeline

This repository provides data-processing packages for Glow-Job. The implemented market domain collects Thailand job postings and prepares structured job-market data; resume processing and learning-document ingestion are scaffolded as separate domains for future work. The intended market flow is JSearch extraction, raw response storage, validation, cleaning, deduplication, normalization, skill extraction, PostgreSQL loading, and career-level aggregation. See [Repository architecture](docs/architecture/repository-architecture.md) for the domain boundaries and full data flow.

Postings with no usable publication date are retained when their other required fields are valid. They are stored with `posted_at = NULL` and `posted_at_status = 'unknown'`; relative dates that can be parsed are labeled `estimated`. Career statistics can use either `posted_at` (provider publication date) or `first_seen_at` (when our pipeline first collected the posting). The first-seen basis includes undated postings and describes when our pipeline discovered jobs; it cannot recreate market history from before collection began.

The current pipeline can fetch JSearch results, preserve them as raw JSON under `data/raw/`, replay a complete saved run without calling the API, validate and clean job records, and deduplicate repeated postings while retaining query provenance and all distinct `apply_options` links. It normalizes company names using confirmed aliases and emits fuzzy candidates for review, then maps job titles to configured career categories while preserving the original title. Skill extraction with Gemini keeps evidence-backed raw results in checkpoints. A clean catalog rebuild re-extracts skills from saved job descriptions, proposes canonical names for review, and only writes the catalog after review and explicit apply. Company candidates are written to a run-specific CSV under `data/processed/company_match_candidates/`; unconfirmed company matches are not merged automatically. Unmapped or ambiguous careers remain in the output with their status. Invalid records, cleaning rejections, and pipeline counts are reported in the logs; raw responses remain available for review. The full scope is in [market-pipeline-spec.md](docs/market/market-pipeline-spec.md), and branch conventions are in [git-workflow.md](docs/architecture/git-workflow.md).

## Local setup

Use Python 3.10 or newer.

### PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m scripts.market.main
# Replay an existing run (replace the value with a run folder name under data/raw/)
python -m scripts.market.main --replay-run-id 20260928T120000000000Z
python -m pytest
```

### Command Prompt (CMD)

```cmd
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
python -m scripts.market.main
rem Replay an existing run (replace the value with a run folder name under data/raw/)
python -m scripts.market.main --replay-run-id 20260928T120000000000Z
python -m pytest
```

Set credentials in `.env` as the corresponding integrations are added. Do not commit `.env`. Edit `config/pipeline.yaml` to configure `search` request parameters and `validation` thresholds; edit `config/careers.yaml` to add career search queries without changing Python code.

To extract skills from an existing raw run, set `GEMINI_API_KEY` in `.env` and run:

```shell
python -m scripts.market.main --replay-run-id 20260928T120000000000Z --extract-skills --skill-limit 2
```

Replace the example run ID with a saved run. Omit `--skill-limit 2` to process every unique job. Gemini reads the cleaned JD and returns raw skill names with supporting evidence. During normal runtime, the pipeline matches exact canonical names and confirmed aliases from PostgreSQL; each result retains `skills` (raw), `normalized_skills` (matched), and `unmatched_skills` (review needed). For the clean catalog rebuild, use the dedicated prepare/review/apply flow below instead of seeding skill names from a YAML file. New Gemini requests start at least 10 seconds apart by default; `--skill-request-interval 20` changes that spacing. Results are saved after each job in `data/processed/skill_extraction/<run_id>.json`; rerunning the same run skips completed jobs and retries failed ones. A Gemini HTTP 429 currently stops the run without an automatic retry; successful checkpoint entries remain, so you can resume later with the same run ID. Each new request uses API quota. Request spacing helps with per-minute limits but cannot fix a daily quota or a token limit reached by a single request; check your project's active limits in Google AI Studio. These JSON files are local checkpoints for review, not database records.

## Local PostgreSQL

Docker Compose reads the `DB_*` settings from `.env` and keeps database files in a named Docker volume.

```powershell
docker compose up -d postgres
python -m scripts.database.migrate
python -m scripts.market.seed_reference_data
docker compose exec postgres psql -U glowjob -d glowjob -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('core', 'market', 'system') ORDER BY schema_name;"
```

The seed command upserts configured career names and creates one `general` profile for each career, so market postings have a reference profile to point to. The verification command uses the default local database name and user from `.env.example`; adjust them if you changed `DB_NAME` or `DB_USER`. The same commands work in PowerShell and CMD. Migrations are tracked in `system.schema_migrations` and can be safely re-run; already-applied files are skipped. Migration `006` belongs to the earlier database-backed candidate resolver; the current rebuild preview is offline and does not use its review queue. See [migrations/README.md](migrations/README.md) for the migration convention and [the pipeline DBML](docs/database/schemas/pipeline-schema.dbml) for the pipeline schema plan.

## Clean skill-catalog rebuild

The rebuild starts from the cleaned job-description checkpoints and an empty skill catalog. It does not import names from `config/skills.yaml` or the existing skill catalog. The command below calls Gemini again for every saved posting, creates concise candidate groups, and asks Gemini to propose canonical names. No database rows change during preparation or review. Without `--force-all-extraction`, completed checkpoints from the current prompt version are reused.

1. Prepare fresh extraction and a new candidate preview (requires `GEMINI_API_KEY`):

   ```shell
   python -m scripts.market.rebuild_skill_catalog_from_checkpoints --prepare-only --reextract --force-all-extraction
   ```

2. Review uncertain candidates and inspect the proposed catalog names:

   ```shell
   python -m scripts.market.review_skill_catalog_preview --summary
   python -m scripts.market.list_skill_catalog_rebuild_names
   python -m scripts.market.review_skill_catalog_preview
   ```

   The reviewer saves decisions only in `data/processed/skill_candidates/catalog_rebuild_preview.csv`. `ready_for_approval` candidates already have a proposed canonical decision; resolve `manual_review` and `needs_llm_suggestion` rows, then use `--list-catalog` to inspect selected names. You can map a candidate to a proposed name, create a custom canonical name, ignore it, or split it into components. The reviewer does not write to PostgreSQL.

   To correct a previous decision or merge duplicate proposals before apply, reopen candidates with:

   ```shell
   python -m scripts.market.review_skill_catalog_preview --include-reviewed --all-candidates
   ```

   Keep the preferred canonical proposal and map each duplicate candidate to it. This changes only the preview CSV; it does not re-extract jobs or update the database. If the catalog was already applied, edit the saved preview this way and run apply again to rebuild skill aliases and posting-skill links from the checkpoints.

3. After reviewing all candidates, apply the rebuild:

   ```shell
   python -m scripts.market.rebuild_skill_catalog_from_checkpoints --apply
   ```

   Apply creates a timestamped backup, verifies checkpoint coverage for postings in the database, resets only `core.skills`, `core.skill_aliases`, `core.skill_candidate_reviews`, `market.job_skills`, and `market.career_skill_stats` with `RESTART IDENTITY`, then reloads the skill links and career aggregates. Skill IDs start from 1 again. Job postings, careers, companies, and raw job data are preserved. Apply is allowed when all required manual-review decisions are resolved; high-confidence `ready_for_approval` proposals do not need an extra manual decision. For split decisions, only transformed checkpoint copies used during apply contain the component names; the original extraction checkpoints stay unchanged.

After the catalog is applied, use `python -m scripts.market.load_job_skills <run_id>` for future checkpoint loads.

## Aggregate career skill demand

After applying the database migrations, load the saved skill run again so previously loaded postings receive `skill_extraction_completed=true`. Then refresh a date window using the desired date basis:

```shell
python -m scripts.database.migrate
python -m scripts.market.load_job_skills 20260927T172453146903Z
python -m scripts.market.aggregate_career_skills 2026-09-01 2026-09-30 --date-basis first_seen_at
```

The dates are inclusive UTC dates. By default, the command uses `posted_at`, so jobs without a known publication date are excluded from that date window. Pass `--date-basis first_seen_at` to group jobs by when this pipeline first collected them; this includes undated postings and keeps first-seen time fixed across later runs. The command replaces statistics for that window and basis, so rerunning it does not duplicate rows. It reports eligible postings, career profiles, and skill statistics. `importance_tier` stays `unknown` until a reviewed threshold is defined. A small sample produces uncertain percentages; first-seen trends become useful after repeated collections and cannot recreate historical observations that were never captured.

## Run the local pipeline in one command

After running migrations, seeding career reference data, and applying the reviewed skill catalog, replay a saved raw run, load its completed skills, and refresh one UTC posting-date window:

```shell
python -m scripts.market.run_pipeline --replay-run-id 20260927T172453146903Z --replay-query-count 6 --start-date 2026-09-01 --end-date 2026-09-30 --date-basis first_seen_at --skill-limit 2
```

The example's first two jobs already have completed skill extraction results, so replay skips JSearch and does not repeat those extraction requests. Unknown skill names remain in the extraction checkpoint for the separate catalog preview and review flow. That older raw run contains six queries; `--replay-query-count 6` preserves its completeness check after new careers are added to the configuration. New runs use the current query count automatically. Replay may call Gemini for jobs beyond the completed extraction checkpoint, but it does not resolve skill candidates or write new skills to PostgreSQL. Omit `--skill-limit` to process the full raw run; a limit selects the first N career-mapped jobs overall, not N jobs per career. A limit smaller than an existing checkpoint is rejected to protect saved progress.

To start a new run with JSearch and Gemini, use `--live` instead of `--replay-run-id`:

```shell
python -m scripts.market.run_pipeline --live --start-date 2026-09-01 --end-date 2026-09-30 --date-basis first_seen_at
```

The command prints the run ID and per-stage counts. If skill extraction is incomplete, it stops before loading and aggregation; successful jobs remain in the checkpoint so you can resume with `--replay-run-id <run_id>`. The aggregation window includes every eligible posting currently loaded in the database, including postings from earlier runs. Run `python -m scripts.market.seed_reference_data` after adding careers and before loading their postings. The current six-career configuration makes 14 JSearch search queries per live run, requesting up to two pages per query, followed by Gemini requests for jobs that pass validation. Scheduling, cloud storage, and monitoring are separate later tasks.

## Layout

- `src/market/`: implemented job-market ingestion, cleaning, normalization, skill extraction, loading, and aggregation
- `src/resume/`: scaffold for CV/resume parsing, extraction, normalization, and schemas
- `src/documents/`: scaffold for skill-learning document ingestion, parsing, chunking, extraction, and embeddings
- `src/shared/`: reusable skill-name normalization, LLM and database adapters, utilities, and schemas
- `config/`: editable career and pipeline settings
- `data/raw/`, `data/processed/`: local data directories, excluded from Git
- `migrations/`: database migrations
- `scripts/market/`, `scripts/database/`: domain CLI tools
- `tests/market/`, `tests/shared/`: implemented test suites; `tests/resume/` and `tests/documents/` are reserved for future behavior
- `docs/`: documentation grouped by domain and cross-domain topic

Use `python -m scripts.market.main` for market extraction/replay and `python -m scripts.market.run_pipeline` for the full market workflow with loading and aggregation. Implementations remain under `src.market`; future resume and document workflows will have their own namespaced entry points.

CLI implementations and tests are grouped by domain under `scripts/` and `tests/`. Run commands with their domain-qualified module paths, such as `python -m scripts.market.run_pipeline`. See [script guide](scripts/README.md) and [test guide](tests/README.md).
