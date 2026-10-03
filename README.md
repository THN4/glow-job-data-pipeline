# Glow-Job Data Pipeline

This repository collects recent Thailand job postings and prepares structured job-market data for Glow-Job. The intended flow is JSearch extraction, raw response storage, validation, cleaning, deduplication, normalization, skill extraction, career-level aggregation, and PostgreSQL loading. User-specific features belong to other services.

The current pipeline can fetch JSearch results and preserve them as raw JSON under `data/raw/`. It can also replay a complete saved run without calling the API. The first PostgreSQL migration covers market ingestion and its required career/company references; skill extraction and aggregation tables will be added when those pipeline stages are implemented. The full scope is in [project-spec.md](doc/project-spec.md), and branch conventions are in [git-workflow.md](doc/git-workflow.md).

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

Set credentials in `.env` as the corresponding integrations are added. Do not commit `.env`. Edit `config/pipeline.yaml` to configure `search` request parameters and `validation` thresholds; edit `config/careers.yaml` to add career search queries without changing Python code. The validation thresholds are loaded and checked now; job-level filtering will be implemented in the validation phase.

## Local PostgreSQL

Docker Compose reads the `DB_*` settings from `.env` and keeps database files in a named Docker volume.

```powershell
docker compose up -d postgres
python -m scripts.migrate
python -m scripts.seed_reference_data
docker compose exec postgres psql -U glowjob -d glowjob -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('core', 'market', 'system') ORDER BY schema_name;"
```

The seed command upserts configured career names and creates one `general` profile for each career, so market postings have a reference profile to point to. The verification command uses the default local database name and user from `.env.example`; adjust them if you changed `DB_NAME` or `DB_USER`. The same commands work in PowerShell and CMD. Migrations are tracked in `system.schema_migrations` and can be safely re-run; already-applied files are skipped. See [migrations/README.md](migrations/README.md) for the migration convention and [the pipeline DBML](doc/schemas/pipeline-schema.dbml) for the pipeline schema plan.

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
