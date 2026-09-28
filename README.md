# Glow-Job Data Pipeline

This repository collects recent Thailand job postings and prepares structured job-market data for Glow-Job. The intended flow is JSearch extraction, raw response storage, validation, cleaning, deduplication, normalization, skill extraction, career-level aggregation, and PostgreSQL loading. User-specific features belong to other services.

The current pipeline can fetch JSearch results and preserve them as raw JSON under `data/raw/`. It can also replay a complete saved run without calling the API. Database loading and later transformation stages are still future work. The full scope is in [project-spec.md](project-spec.md), and branch conventions are in [git-workflow.md](git-workflow.md).

## Local setup

Use Python 3.10 or newer.

### PowerShell

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m src.main
# Replay an existing run (replace the value with a run folder name under data/raw/)
python -m src.main --replay-run-id 20260928T120000000000Z
python -m pytest
```

### Command Prompt (CMD)

```cmd
py -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
python -m src.main
rem Replay an existing run (replace the value with a run folder name under data/raw/)
python -m src.main --replay-run-id 20260928T120000000000Z
python -m pytest
```

Set credentials in `.env` as the corresponding integrations are added. Do not commit `.env`. Edit `config/pipeline.yaml` for collection limits and `config/careers.yaml` to add career search queries without changing Python code.

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
- `migrations/`, `scripts/`, `tests/`: future migrations, helpers, and tests
