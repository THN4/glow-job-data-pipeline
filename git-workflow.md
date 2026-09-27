# Glow-Job Data Pipeline Git Workflow

## 1. Purpose

This document defines the Git workflow for the **Glow-Job Data Pipeline** repository.

This repository only handles:

```text
Job Data Collection
        ↓
Processing
        ↓
Normalization
        ↓
Skill Extraction
        ↓
Aggregation
        ↓
Ready-to-use Job Market Data
```

User-related features must not be developed in this repository.

---

# 2. Branch Model

The repository will use:

```text
main
 │
 └── develop
       │
       ├── feature/*
       ├── fix/*
       ├── refactor/*
       ├── experiment/*
       └── docs/*
```

---

# 3. main

```text
main
```

Contains the latest stable version.

Code in `main` should:

- Run successfully
- Pass tests
- Be suitable for demo
- Have stable database migrations
- Have no known critical pipeline errors

Do not develop directly on `main`.

---

# 4. develop

```text
develop
```

Main integration branch.

Feature development starts from:

```text
develop
```

and completed features merge back into:

```text
develop
```

When the pipeline reaches a stable milestone:

```text
develop
   ↓
main
```

---

# 5. Feature Branch Format

Use:

```text
feature/<feature-name>
```

Examples:

```text
feature/project-setup

feature/jsearch-extraction

feature/raw-data-storage

feature/database-schema

feature/job-validation

feature/job-cleaning

feature/job-deduplication

feature/company-normalization

feature/career-mapping

feature/skill-extraction

feature/skill-normalization

feature/job-skills

feature/career-skill-aggregation

feature/pipeline-monitoring

feature/aws-s3

feature/aws-rds

feature/aws-scheduler
```

---

# 6. Branch Scope Rule

A branch should represent one clear pipeline responsibility.

Good:

```text
feature/job-deduplication
```

Good:

```text
feature/skill-extraction
```

Avoid:

```text
feature/data-pipeline
```

if it contains:

```text
JSearch
Database
Cleaning
Deduplication
Skills
AWS
```

Large branches are harder to review and merge.

---

# 7. Phase 1 — Project Setup

Branch:

```text
feature/project-setup
```

Tasks:

- Project folder structure
- Python package setup
- `.gitignore`
- `.env.example`
- `requirements.txt`
- Logging configuration
- Basic config system
- Test structure

Merge into:

```text
develop
```

---

# 8. Phase 2 — JSearch Extraction

Branch:

```text
feature/jsearch-extraction
```

Tasks:

- JSearch client
- API authentication
- Search queries
- Thailand filtering
- Pagination
- Error handling
- Rate-limit handling
- Response parsing

Expected output:

```text
JSearch
    ↓
Raw API Response
```

---

# 9. Phase 3 — Raw Data Storage

Branch:

```text
feature/raw-data-storage
```

Tasks:

- Save original JSearch response
- Organize raw files by ingestion date
- Store query metadata
- Store collection timestamps
- Prevent unnecessary repeated requests during development

Output:

```text
data/raw/
```

---

# 10. Phase 4 — Database Schema

Branch:

```text
feature/database-schema
```

Tasks:

- PostgreSQL configuration
- Database connection
- ORM / repository setup
- Database migrations

Initial tables:

```text
companies

career_roles

job_postings

skills

skill_aliases

job_skills

career_skills
```

Optional pipeline table:

```text
ingestion_runs
```

---

# 11. Phase 5 — Job Validation

Branch:

```text
feature/job-validation
```

Tasks:

- Required field validation
- Missing description detection
- Invalid country detection
- Invalid job record filtering
- Validation error reporting

Flow:

```text
Raw Job
   ↓
Validation
   ↓
Valid / Invalid
```

---

# 12. Phase 6 — Job Cleaning

Branch:

```text
feature/job-cleaning
```

Tasks:

- Clean Job Description
- Remove HTML
- Normalize whitespace
- Standardize dates
- Standardize missing values
- Normalize country/location format

---

# 13. Phase 7 — Job Deduplication

Branch:

```text
feature/job-deduplication
```

Tasks:

- Detect same provider job ID
- Detect same source URL
- Compare company/title/location
- Prevent duplicate inserts
- Support repeated ingestion runs

Output:

```text
Unique Job Dataset
```

---

# 14. Phase 8 — Company Normalization

Branch:

```text
feature/company-normalization
```

Tasks:

- Clean company names
- Detect aliases
- Assign canonical `company_id`
- Preserve original company name when necessary

Example:

```text
Siam Commercial Bank
SCB
The Siam Commercial Bank

        ↓

company_id = 15
```

---

# 15. Phase 9 — Career Mapping

Branch:

```text
feature/career-mapping
```

Tasks:

- Normalize job titles
- Preserve raw job title
- Map jobs to `career_id`
- Support configurable career definitions

Example:

```text
Junior Data Engineer
Senior Data Engineer
Cloud Data Engineer

        ↓

Data Engineer
```

---

# 16. Phase 10 — Skill Extraction

Branch:

```text
feature/skill-extraction
```

Tasks:

- Process Job Description
- Extract technical skills
- Extract tools
- Extract frameworks
- Identify required/preferred skills
- Store confidence when available

Example:

```text
Python → required
SQL → required
Kafka → preferred
```

---

# 17. Experimental Skill Extraction

Alternative extraction approaches should initially use:

```text
experiment/<name>
```

Examples:

```text
experiment/llm-skill-extraction

experiment/spacy-skill-extraction

experiment/dictionary-skill-extraction

experiment/embedding-skill-extraction
```

The selected approach can later be integrated into:

```text
feature/skill-extraction
```

---

# 18. Phase 11 — Skill Normalization

Branch:

```text
feature/skill-normalization
```

Tasks:

- Canonical skill matching
- Alias matching
- Duplicate skill merging
- Skill category mapping

Example:

```text
Amazon Web Services
Amazon AWS
AWS

        ↓

AWS
```

---

# 19. Phase 12 — Job Skills

Branch:

```text
feature/job-skills
```

Tasks:

Populate:

```text
job_skills
```

Relationship:

```text
job_postings
       ↓
job_skills
       ↓
skills
```

Example:

```text
Job #101

Python  required
SQL     required
AWS     preferred
```

---

# 20. Phase 13 — Career Skill Aggregation

Branch:

```text
feature/career-skill-aggregation
```

Tasks:

- Group valid jobs by career
- Count skill occurrence
- Count required occurrence
- Count preferred occurrence
- Calculate demand percentage
- Store analysis time window
- Update `career_skills`

Output:

```text
Data Engineer

SQL        84%
Python     79%
AWS        47%
Airflow    44%
```

---

# 21. Phase 14 — Ingestion Run Tracking

Branch:

```text
feature/ingestion-run-tracking
```

Tasks:

Track:

```text
run_id

started_at
finished_at

jobs_fetched
jobs_valid
jobs_duplicate
jobs_inserted

errors
status
```

This branch becomes useful once repeated ingestion runs are introduced.

---

# 22. Phase 15 — Pipeline Logging

Branch:

```text
feature/pipeline-logging
```

Example logs:

```text
[INFO] Starting ingestion

[INFO] Career: Data Engineer

[INFO] 100 jobs fetched

[INFO] 91 jobs valid

[INFO] 7 duplicates removed

[INFO] 84 new jobs inserted

[INFO] Starting skill extraction

[INFO] Pipeline completed
```

---

# 23. Phase 16 — Pipeline Monitoring

Branch:

```text
feature/pipeline-monitoring
```

Possible metrics:

```text
Jobs fetched

Jobs inserted

Invalid jobs

Duplicate jobs

Skill extraction success rate

Skill extraction failure rate

Jobs per career

Jobs per company

Last successful ingestion
```

---

# 24. AWS Branches

Cloud implementation should remain separated.

Use:

```text
feature/aws-s3

feature/aws-rds

feature/aws-compute

feature/aws-scheduler
```

---

# 25. AWS S3

Branch:

```text
feature/aws-s3
```

Purpose:

Replace or extend:

```text
Local Raw JSON
```

with:

```text
Amazon S3
```

Flow:

```text
JSearch
   ↓
Raw JSON
   ↓
Amazon S3
```

---

# 26. AWS RDS

Branch:

```text
feature/aws-rds
```

Purpose:

Move:

```text
Local PostgreSQL
```

to:

```text
Amazon RDS PostgreSQL
```

The pipeline logic should not need major modification.

---

# 27. AWS Scheduler

Branch:

```text
feature/aws-scheduler
```

Possible architecture:

```text
EventBridge
     ↓
Lambda / ECS
     ↓
Data Pipeline
```

Implement only after the pipeline works locally.

---

# 28. Fix Branches

Use:

```text
fix/<problem>
```

Examples:

```text
fix/jsearch-pagination

fix/api-rate-limit

fix/duplicate-job-insertion

fix/company-alias-mapping

fix/career-mapping

fix/skill-percentage

fix/database-connection
```

Flow:

```text
develop
   ↓
fix/*
   ↓
develop
```

---

# 29. Hotfix Branches

Use only for critical issues in `main`.

Format:

```text
hotfix/<problem>
```

Example:

```text
hotfix/database-migration
```

Flow:

```text
main
 ↓
hotfix/*
 ↓
main
```

The same fix should also be merged into:

```text
develop
```

---

# 30. Refactor Branches

Use:

```text
refactor/<name>
```

Examples:

```text
refactor/jsearch-client

refactor/database-layer

refactor/skill-normalizer

refactor/pipeline-config
```

Refactoring should not intentionally change system behavior.

---

# 31. Documentation Branches

Use:

```text
docs/<name>
```

Examples:

```text
docs/project-spec

docs/database-schema

docs/pipeline-architecture

docs/aws-setup
```

---

# 32. Recommended Initial Development Sequence

```text
feature/project-setup
        ↓
feature/jsearch-extraction
        ↓
feature/raw-data-storage
        ↓
feature/database-schema
        ↓
feature/job-validation
        ↓
feature/job-cleaning
        ↓
feature/job-deduplication
        ↓
feature/company-normalization
        ↓
feature/career-mapping
        ↓
feature/skill-extraction
        ↓
feature/skill-normalization
        ↓
feature/job-skills
        ↓
feature/career-skill-aggregation
```

After the core pipeline is stable:

```text
feature/ingestion-run-tracking
        ↓
feature/pipeline-logging
        ↓
feature/pipeline-monitoring
        ↓
feature/aws-s3
        ↓
feature/aws-rds
        ↓
feature/aws-scheduler
```

---

# 33. Parallel Development

Not all branches must wait for the previous branch if interfaces are clear.

Example:

```text
Developer A
feature/jsearch-extraction

Developer B
feature/database-schema

Developer C
experiment/llm-skill-extraction
```

These can be developed simultaneously.

However, dependent features should wait for required interfaces to stabilize.

---

# 34. Dependency Example

```text
feature/jsearch-extraction
        ↓
feature/job-validation
        ↓
feature/job-cleaning
        ↓
feature/job-deduplication
```

Meanwhile:

```text
feature/database-schema
```

can be developed in parallel.

Skill extraction depends on having clean Job Descriptions:

```text
feature/job-cleaning
        ↓
feature/skill-extraction
```

---

# 35. Local Merge Flow (Solo Development)

Feature work is developed on a short-lived feature branch, then merged locally into `develop` with `--no-ff`. This preserves a merge commit that marks where the feature branch was integrated.

```bash
git switch develop
git pull --ff-only origin develop
```

Create a feature branch:

```bash
git switch -c feature/job-deduplication
```

Implement the feature, run its tests, and commit the work:

```bash
git add .
git commit -m "feat: add job deduplication"
```

Return to `develop`, update it, and merge the feature locally:

```bash
git switch develop
git pull --ff-only origin develop
git merge --no-ff feature/job-deduplication -m "feat: add job deduplication"
```

Push the updated integration branch. Keep the local feature branch as a reference to the completed work; create a new feature branch for the next task.

```bash
git push origin develop
```

---

# 36. Pre-Merge Checklist

Before merging a feature into `develop`:

- Feature works locally
- Tests pass
- GitHub Actions checks pass when available
- No secrets are committed
- `.env` is not committed
- New environment variables are documented
- Database changes include migrations
- New config values are documented
- No unnecessary debug code remains
- Existing pipeline behavior is not unintentionally broken

---

# 37. Merge Strategy

Use a no-fast-forward merge when integrating a feature branch:

```text
git merge --no-ff feature/<feature-name>
```

This creates a merge commit on `develop`, even when Git could move the branch pointer forward directly. The feature's individual commits remain in history, and the merge commit marks the integration point.

Use clear commit messages for both feature commits and the merge commit, following the commit format in Section 38.

---

# 38. Commit Format

Use:

```text
<type>: <description>
```

Types:

```text
feat
fix
refactor
docs
test
chore
build
ci
```

Examples:

```text
feat: add JSearch pagination

feat: add company normalization

feat: implement skill extraction

fix: prevent duplicate job insertion

fix: handle jobs without descriptions

refactor: simplify database repository

test: add career aggregation tests

docs: update pipeline specification
```

---

# 39. Commit Guidelines

Good:

```text
feat: add job validation
```

Good:

```text
fix: handle missing company name
```

Avoid:

```text
update
```

Avoid:

```text
fix stuff
```

Avoid:

```text
changes
```

Each commit should represent one meaningful change.

---

# 40. Branch Naming Rules

Use:

```text
lowercase
kebab-case
```

Correct:

```text
feature/career-skill-aggregation
```

Avoid:

```text
Feature/CareerSkillAggregation
```

Avoid personal branch names:

```text
thanatip-test
```

Branch names should describe the work.

---

# 41. Branch Lifetime

Feature work should be short-lived. Completed local feature branches may be kept as references.

Flow:

```text
Create Branch
      ↓
Implement Feature
      ↓
Test
      ↓
Merge locally into develop with --no-ff
      ↓
Push develop
      ↓
Keep feature branch as a reference
```

---

# 42. Release Flow

Stable features:

```text
feature/*
    ↓
develop
    ↓
Integration Testing
    ↓
main
```

Possible tags:

```text
v0.1.0
v0.2.0
v0.3.0
v1.0.0
```

Example:

```text
v0.1.0
JSearch extraction works

v0.2.0
Database pipeline works

v0.3.0
Skill extraction works

v0.4.0
Career aggregation works

v1.0.0
Stable competition data pipeline
```

---

# 43. Definition of Done

A feature branch is complete when:

- Feature works
- Required tests pass
- Errors are handled
- Configuration is documented
- No credentials are committed
- Code follows repository structure
- Relevant logs exist
- Related migration exists if required
- Feature is merged into `develop` locally and pushed successfully

---

# 44. Repository Boundary

Do not add branches such as:

```text
feature/user-skills

feature/job-matching

feature/application-tracking

feature/roadmap

feature/interview-agent
```

to this repository.

Those belong to other Glow-Job services.

This repository ends at:

```text
Structured Job Market Data
        +
Job Skills
        +
Career Skills
```

---

# 45. Final Branch Overview

```text
main
│
└── develop
    │
    ├── feature/project-setup
    │
    ├── feature/jsearch-extraction
    │
    ├── feature/raw-data-storage
    │
    ├── feature/database-schema
    │
    ├── feature/job-validation
    │
    ├── feature/job-cleaning
    │
    ├── feature/job-deduplication
    │
    ├── feature/company-normalization
    │
    ├── feature/career-mapping
    │
    ├── feature/skill-extraction
    │
    ├── feature/skill-normalization
    │
    ├── feature/job-skills
    │
    ├── feature/career-skill-aggregation
    │
    ├── feature/ingestion-run-tracking
    │
    ├── feature/pipeline-logging
    │
    ├── feature/pipeline-monitoring
    │
    ├── feature/aws-s3
    │
    ├── feature/aws-rds
    │
    └── feature/aws-scheduler
    │
    ├── fix/*
    ├── refactor/*
    ├── experiment/*
    └── docs/*
```

---

# 46. Core Git Principle

The Git workflow should follow the same boundary as the pipeline itself:

```text
Collect
   ↓
Clean
   ↓
Normalize
   ↓
Extract
   ↓
Aggregate
   ↓
Store
```

Nothing related to user-specific application logic should be included in this repository.
