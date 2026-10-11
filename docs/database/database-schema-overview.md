# Glow-Job Database Schema Overview

## 1. Purpose and implementation status

This document separates the database objects implemented by this repository's
migrations from the broader Glow-Job schema proposed for the host application.
The SQL migration files in `migrations/versions/` are the source of truth for
what this repository currently creates. The DBML/DBDiagram files are design
references and may describe planned application or knowledge-domain tables
that are not created by these migrations.

The current pipeline uses PostgreSQL. Its migrations create three schemas:

```text
core    Shared reference data and the skill catalog
market  Job postings, extracted skills, and market aggregates
system  Ingestion and schema-migration bookkeeping
```

The `app` and `knowledge` schemas shown in the combined Glow-Job diagrams are
future design areas. This repository currently has no migrations or processing
implementation for user accounts, resumes, roadmaps, learning documents,
embeddings, or skill dependencies. See the [learning-graph design](../documents/learning-graph-flow.md)
and [repository architecture](../architecture/repository-architecture.md) for
the documented boundaries.

## 2. Current schema map

```text
core
├── companies
├── careers
├── career_profiles
├── skills
├── skill_aliases
└── skill_candidate_reviews  # Legacy resolver queue; current rebuild uses CSV

market
├── job_postings
├── job_search_matches
├── job_skills
└── career_skill_stats

system
├── ingestion_runs
└── schema_migrations
```

For the full pipeline-oriented database model, see
[pipeline-schema.dbml](schemas/pipeline-schema.dbml). For the broader target
Glow-Job model, see [glow-job.dbml](schemas/glow-job.dbml). Apply migrations
with `python -m scripts.database.migrate`; see the [migration guide](../../migrations/README.md).

## 3. Domain responsibilities

### `core`

Stores shared reference records used by the market pipeline, including
companies, careers, career profiles, canonical skills, and confirmed skill
aliases. A canonical skill has one `skill_id`; market job-skill rows refer to
that ID rather than copying the canonical name.

`core.skill_candidate_reviews` was introduced for the earlier automatic
candidate resolver. The current clean catalog rebuild stores review decisions
in a local CSV preview and replaces the legacy review table during apply; it
does not use this table as its active review queue.

### `market`

Stores provider job postings and query provenance, verified skills extracted
from job descriptions, and career-level aggregates. `market.job_skills` links a
posting to a canonical `core.skills` record and retains the observed raw name,
classification, evidence, and scoring fields.

### `system`

Stores ingestion-run metadata and the migration history. Local JSON files under
`data/raw/` and `data/processed/` are pipeline artifacts, not rows in
`system`.

## 4. Implemented tables

### Shared reference data

| Table | Purpose |
|---|---|
| `core.companies` | Canonical company names and optional normalized names and website. |
| `core.careers` | Configured career categories. |
| `core.career_profiles` | Job-search and market-analysis profiles linked to a career. |
| `core.skills` | Canonical skill catalog, including `skill_category` and `catalog_status` (`approved` or `provisional`). |
| `core.skill_aliases` | Confirmed alternate names mapped to a canonical skill. |
| `core.skill_candidate_reviews` | Legacy automatic candidate-resolution records; retained in schema for compatibility. |

### Market data

| Table | Purpose |
|---|---|
| `market.job_postings` | Provider posting details, career and company references, publication-date quality, first-seen time, and extraction-completion status. |
| `market.job_search_matches` | The search run, career profile, query, and collection time associated with a posting. |
| `market.job_skills` | One matched canonical skill per job, with raw label, requirement/proficiency, evidence, importance, and confidence fields. |
| `market.career_skill_stats` | Career-level demand statistics for a date window and date basis. |

### Operational data

| Table | Purpose |
|---|---|
| `system.ingestion_runs` | Source run state, counts, timestamps, and errors. |
| `system.schema_migrations` | Applied migration versions and timestamps, managed by the migration runner. |

## 5. Important fields and behavior

### Job dates

`market.job_postings.posted_at` stores the provider's publication timestamp
when one can be parsed. `posted_at_status` is one of `exact`, `estimated`,
`unknown`, or `unclassified` (the last value is used for older rows migrated
without quality metadata). `first_seen_at` stores the earliest available
pipeline collection time for the posting and is retained across later upserts.

Career aggregates are keyed by `analysis_date_basis`:

- `posted_at` uses provider publication time and excludes postings without a
  usable publication date from the selected window.
- `first_seen_at` uses pipeline discovery time and can include postings whose
  publication date is unknown.

### Job skill rows

`market.job_skills` has a primary key on `(job_id, skill_id)`, so a canonical
skill occurs at most once per posting. It stores `raw_skill_name` and
`evidence_text` for traceability. A catalog-unmatched name is retained in the
local skill checkpoint and is not inserted as a job-skill row by the normal
loader.

`skill_extraction_completed` on `market.job_postings` distinguishes a
successful extraction with no matched skills from a job that has not completed
extraction. Aggregation uses this flag and a usable job description to select
its denominator; it does not infer completion from the existence of rows in
`market.job_skills`.

### Candidate review and catalog reset

The current rebuild review is an offline CSV workflow. On apply, the rebuild
backs up and replaces only the skill-related tables `core.skills`,
`core.skill_aliases`, `core.skill_candidate_reviews`, `market.job_skills`, and
`market.career_skill_stats`. It restarts skill identities while retaining job
postings, companies, careers, and ingestion records. Review and apply details
are in the [skill-candidate review guide](../market/skill-candidate-review-guide.md).

## 6. Migration history

| Migration | Change |
|---|---|
| `001_create_market_ingestion.sql` | Creates `core`, `market`, and `system` pipeline tables for companies, careers, profiles, ingestion runs, job postings, and search matches. |
| `002_create_skill_catalog.sql` | Creates canonical skills and skill aliases. |
| `003_create_job_skills.sql` | Creates job-skill links and adds extraction-completion status to postings. |
| `004_create_career_skill_stats.sql` | Creates career-level skill aggregates. |
| `005_add_posted_at_status.sql` | Adds publication-date quality, `first_seen_at`, and aggregate date basis. |
| `006_add_automatic_skill_candidate_resolution.sql` | Adds provisional catalog status and the legacy candidate-review table. |
| `007_add_split_applied_candidate_status.sql` | Adds the `split_applied` status to the legacy candidate-review table. |

Migration files are applied in order by `python -m scripts.database.migrate`.
Successful versions are tracked in `system.schema_migrations`; applied
migrations are skipped on later runs.

## 7. Future Glow-Job schemas

The combined schema diagrams include proposed `app` tables for accounts,
profiles, resumes, user skills, roadmaps, progress, and applications, plus
`knowledge` tables for learning sources, chunks, skill dependencies, and
learning modules. These are target designs only. They are not created by the
current migration set and must not be treated as live database tables until
their migrations and domain workflows are implemented.

The `embedding` field in the conceptual knowledge model assumes a PostgreSQL
vector extension or another vector-store design; this repository does not
currently provision either one.
