# Glow-Job Data Pipeline Specification

## 1. Project Overview

The **Glow-Job Data Pipeline** is responsible for collecting, processing, normalizing, and preparing up-to-date job market data for the Glow-Job platform.

The pipeline focuses on transforming raw Job Description data into structured and ready-to-use job market information.

This project does **not** handle:

- User profiles
- User skills
- Skill gap matching
- Job matching
- Personalized roadmap generation
- Application tracking
- Interview feedback
- Recommendation logic

These features belong to other parts of the Glow-Job system.

---

# 2. Main Objective

The objective of this pipeline is to:

1. Collect recent job postings in Thailand.
2. Preserve raw job data.
3. Validate and clean job records.
4. Remove duplicate job postings.
5. Normalize company information.
6. Normalize job titles and career roles.
7. Extract skills from Job Descriptions.
8. Normalize extracted skills.
9. Store skills required by individual jobs.
10. Aggregate skill demand at the career level.
11. Store structured data in PostgreSQL.
12. Produce reliable job market data that can be consumed by other Glow-Job services.

---

# 3. Pipeline Scope

The pipeline begins with:

```text
External Job Data
```

and ends with:

```text
Ready-to-use Job Market Data
```

Overall flow:

```text
JSearch API
    ↓
Data Extraction
    ↓
Raw Data Storage
    ↓
Validation
    ↓
Cleaning
    ↓
Deduplication
    ↓
Company Normalization
    ↓
Job Title / Career Normalization
    ↓
Skill Extraction
    ↓
Skill Normalization
    ↓
Job-Level Skill Data
    ↓
Career-Level Aggregation
    ↓
PostgreSQL
    ↓
Ready-to-use Job Market Data
```

---

# 4. Out of Scope

The following components are intentionally excluded from this repository:

```text
User Profile
User Skills
Skill Gap Analysis
Job Recommendation
Company Recommendation
Job Matching
Career Roadmap
Application Tracking
Interview Simulation
Feedback Re-planning
```

The pipeline only prepares the data required by these future services.

---

# 5. Primary Data Source

The initial primary data provider is:

**JSearch API**

JSearch will be used to retrieve recent job postings relevant to the Thailand job market.

Expected fields may include:

```text
job_id
job_title
employer_name
job_description
job_location
job_city
job_state
job_country

job_employment_type

job_publisher
job_apply_link

job_posted_at
job_posted_at_timestamp

employer_website

additional metadata
```

The original API response should be preserved before transformation.

---

# 6. Data Provider vs Publisher

The system must distinguish between:

```text
provider
```

and:

```text
publisher
```

Example:

```text
provider  = JSearch
publisher = LinkedIn
```

`provider` represents the service Glow-Job directly requests data from.

`publisher` represents the source platform listed in the job information.

This distinction should be stored in the database for data lineage.

---

# 7. Job Market Scope

Initial market:

```text
Thailand
```

The pipeline should prioritize:

- Recent jobs
- Relevant jobs
- Unique jobs
- Jobs containing usable Job Descriptions

The architecture must not hard-code a small number of career roles.

The system should support adding many career categories over time.

Example:

```text
Data Engineer
Data Analyst
Software Engineer
Backend Engineer
Frontend Engineer
Cloud Engineer
DevOps Engineer
Cybersecurity Analyst
Business Analyst
Product Manager
UX/UI Designer
...
```

The initial development may test with a small number of careers, but the architecture must support expansion.

---

# 8. Career Search Configuration

Career search queries should be configurable.

Example:

```yaml
careers:

  data_engineer:
    career_name: "Data Engineer"

    queries:
      - "Data Engineer"
      - "Junior Data Engineer"
      - "Data Platform Engineer"
      - "ETL Developer"
      - "Cloud Data Engineer"
      - "Big Data Engineer"
```

Future careers can be added without modifying the pipeline logic.

---

# 9. Data Collection Strategy

The pipeline should prioritize:

```text
Recent
Relevant
Unique
Complete
```

job postings.

Recommended target during development:

```text
200–500 unique Job Descriptions per career
```

However, the system should not force an artificial minimum.

If fewer relevant jobs are available, the pipeline should use the real available sample.

Possible initial time window:

```text
Last 90 days
```

This value should be configurable.

---

# 10. Data Ingestion Flow

```text
Career Configuration
       ↓
Generate Search Queries
       ↓
JSearch API
       ↓
API Response Validation
       ↓
Raw Data Storage
       ↓
Job Record Extraction
       ↓
Cleaning
       ↓
Deduplication
       ↓
Normalization
       ↓
Database Loading
```

---

# 11. Raw Data Storage

All raw API responses should be preserved before transformation.

Local development:

```text
data/
└── raw/
    ├── 2026-09-26/
    │   ├── data-engineer-page-1.json
    │   ├── data-engineer-page-2.json
    │   └── backend-engineer-page-1.json
```

Raw storage provides:

- Data lineage
- Debugging
- Reprocessing
- Reproducibility
- Reduced API usage during development
- Historical comparison

Future cloud implementation may use:

```text
Amazon S3
```

---

# 12. Raw Data Metadata

Each ingestion batch should record:

```text
provider
search_query
career_target
requested_at
response_status
page
number_of_results
```

Example:

```text
provider       = JSearch
search_query   = Data Engineer in Thailand
career_target  = Data Engineer
requested_at   = 2026-09-26
page           = 1
```

---

# 13. Data Validation

Before processing, each job should be validated.

Minimum requirements:

- Job title exists
- Job Description exists
- Company information exists when available
- Job belongs to the selected country scope
- Job data can be identified with a stable key or combination of fields

Invalid records should not enter the final analytical dataset.

---

# 14. Data Cleaning

Cleaning responsibilities include:

- Remove unnecessary HTML
- Remove excessive whitespace
- Standardize null values
- Standardize dates
- Standardize country codes
- Standardize employment type
- Clean text encoding issues
- Remove unusable descriptions

Example:

```text
"  Data   Engineer \n\n"

        ↓

"Data Engineer"
```

---

# 15. Job Deduplication

The same job may appear multiple times because of:

- Multiple search queries
- Multiple API pages
- Repeated ingestion runs
- Multiple publishers
- Reposted jobs

Deduplication should consider:

```text
provider_job_id
source_url
company
job_title
location
posted_at
description similarity
```

Priority matching strategy:

```text
1. provider_job_id

2. source_url

3. normalized company
   +
   normalized title
   +
   location

4. description similarity
```

Duplicate jobs must not inflate career skill statistics.

---

# 16. Companies

Companies should be stored separately from job postings.

Table:

```text
companies
```

Suggested schema:

```text
company_id
company_name
normalized_name
company_website

created_at
updated_at
```

Example:

```text
1 | Agoda
2 | SCB
3 | LINE MAN Wongnai
```

---

# 17. Company Normalization

Raw company names may vary.

Example:

```text
SCB
Siam Commercial Bank
The Siam Commercial Bank PCL
```

The system should attempt to map them into a canonical company record.

Example:

```text
normalized_name = Siam Commercial Bank
company_id = 15
```

Original company information should still be preserved when useful.

---

# 18. Career Roles

Career categories should be stored in:

```text
career_roles
```

Suggested schema:

```text
career_id
career_name
description
is_active

created_at
updated_at
```

Example:

```text
1 | Data Engineer
2 | Data Analyst
3 | Backend Engineer
```

The table must support adding more careers without schema changes.

---

# 19. Job Title Normalization

Job titles returned by the API should remain preserved.

Example:

```text
Senior Data Engineer
Junior Data Engineer
Cloud Data Engineer
Data Engineer II
```

Raw field:

```text
job_title
```

Normalized field:

```text
normalized_job_title
```

Example:

```text
job_title = "Senior Data Engineer"

normalized_job_title = "Data Engineer"
```

---

# 20. Career Mapping

Each job should be mapped to a career category when possible.

Example:

```text
Senior Data Engineer
Junior Data Engineer
Cloud Data Engineer

        ↓

career_id = Data Engineer
```

Career mapping may initially use:

- Rule-based mapping
- Search query context
- Keyword mapping
- LLM classification

The method may evolve later.

---

# 21. Job Postings Table

Main table:

```text
job_postings
```

Suggested schema:

```text
job_id
provider_job_id

company_id
career_id

job_title
normalized_job_title

job_description

location
city
state
country

employment_type

provider
publisher

source_url

posted_at
collected_at

search_query

created_at
updated_at
```

---

# 22. Skill Extraction

Skills should be extracted from each Job Description.

Flow:

```text
Job Description
       ↓
Text Cleaning
       ↓
NLP / LLM
       ↓
Skill Extraction
       ↓
Skill Normalization
```

Example Job Description:

```text
Candidates should have experience with Python,
SQL, Apache Airflow and AWS.

Experience with Kafka is a plus.
```

Expected result:

```text
Python   → required
SQL      → required
Airflow  → required
AWS      → required
Kafka    → preferred
```

---

# 23. Skill Extraction Approach

Initial recommended approach:

```text
LLM-based extraction
        +
Skill Dictionary
        +
Normalization Rules
```

The LLM should identify candidate skills.

The normalization layer should map extracted values into canonical skill records.

---

# 24. Skills Table

Table:

```text
skills
```

Suggested schema:

```text
skill_id
skill_name
skill_category

created_at
updated_at
```

Example:

```text
1 | Python
2 | SQL
3 | Apache Airflow
4 | AWS
5 | Apache Spark
6 | Kafka
```

---

# 25. Skill Aliases

Skill aliases should not necessarily be stored directly inside the `skills` table.

Recommended table:

```text
skill_aliases
```

Schema:

```text
alias_id
skill_id
alias
```

Example:

```text
AWS
Amazon AWS
Amazon Web Services

        ↓

skill_id = AWS
```

Another example:

```text
Postgres
Postgre SQL
PostgreSQL

        ↓

skill_id = PostgreSQL
```

---

# 26. Job Skills

Skills extracted from individual Job Descriptions should be stored in:

```text
job_skills
```

Suggested schema:

```text
job_id
skill_id

requirement_type
confidence

created_at
```

Requirement types may include:

```text
required
preferred
optional
unknown
```

Example:

```text
Job 101

Python   required
SQL      required
Airflow  required
Kafka    preferred
```

---

# 27. Skill Extraction Confidence

When supported by the extraction method, the pipeline may store:

```text
confidence
```

Example:

```text
Python  required   0.98
Kafka   preferred  0.90
```

Confidence should be used as metadata rather than treated as absolute truth.

---

# 28. Career Skill Aggregation

After `job_skills` are available, the system should calculate market-level skill demand.

Example:

```text
400 Data Engineer jobs

SQL      appears in 340 jobs
Python   appears in 312 jobs
AWS      appears in 190 jobs
Airflow  appears in 180 jobs
```

Calculation:

```text
Skill Demand Percentage
=
Jobs containing skill
-----------------------
Total valid jobs
× 100
```

Example:

```text
SQL

340 / 400 × 100

= 85%
```

---

# 29. Career Skills Table

Aggregated results should be stored in:

```text
career_skills
```

Suggested schema:

```text
career_id
skill_id

demand_count
total_jobs
demand_percentage

required_count
preferred_count

analysis_start_date
analysis_end_date

last_updated
```

Example:

```text
Data Engineer

SQL       85%
Python    78%
AWS       47%
Airflow   45%
Spark     38%
Kafka     25%
```

---

# 30. Important Difference

The pipeline must distinguish between:

```text
job_skills
```

and:

```text
career_skills
```

`job_skills` answers:

```text
What skills does this specific job require?
```

`career_skills` answers:

```text
What skills are commonly required by the market
for this career?
```

---

# 31. Database Architecture

Initial database:

```text
PostgreSQL
```

Main relationships:

```text
companies
    │
    │ 1:N
    ▼
job_postings
    │
    │ N:M
    ▼
job_skills
    │
    ▼
skills


career_roles
    │
    │ 1:N
    ▼
job_postings


career_roles
    │
    │ N:M
    ▼
career_skills
    │
    ▼
skills
```

---

# 32. Recommended Core Tables

Initial database should include:

```text
companies

career_roles

job_postings

skills

skill_aliases

job_skills

career_skills
```

Optional future pipeline tables:

```text
ingestion_runs

pipeline_errors

career_search_queries
```

---

# 33. Ingestion Runs

Recommended table:

```text
ingestion_runs
```

Purpose:

Track every pipeline execution.

Suggested schema:

```text
run_id
provider
started_at
finished_at
status

jobs_fetched
jobs_valid
jobs_duplicate
jobs_inserted

error_count
```

This will help monitor pipeline reliability.

---

# 34. Search Query Configuration

Search queries should preferably not be hard-coded.

Example:

```yaml
careers:

  data_engineer:
    name: Data Engineer

    queries:
      - Data Engineer
      - Junior Data Engineer
      - Data Platform Engineer

  backend_engineer:
    name: Backend Engineer

    queries:
      - Backend Engineer
      - Backend Developer
      - Backend Software Engineer
```

---

# 35. Pipeline Configuration

Configurable values may include:

```text
country
time_window
results_per_query
maximum_pages
career_queries
minimum_description_length
```

Example:

```yaml
country: TH
time_window_days: 90
max_pages: 5
```

---

# 36. Local-First Development

The first version should run locally.

Architecture:

```text
JSearch
   ↓
Python Pipeline
   ↓
Raw JSON
   ↓
Local PostgreSQL
```

Cloud infrastructure must not block development.

---

# 37. AWS-Ready Architecture

Future architecture:

```text
                 JSearch
                    │
                    ▼
              Data Pipeline
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
      Amazon S3          Amazon RDS
      Raw Data            PostgreSQL
```

Possible future compute:

```text
AWS Lambda
Amazon ECS
Amazon EC2
```

Possible scheduling:

```text
Amazon EventBridge
```

AWS should be introduced only after the local pipeline works correctly.

---

# 38. Environment Variables

Example:

```env
JSEARCH_API_KEY=

DB_HOST=
DB_PORT=5432
DB_NAME=glowjob
DB_USER=
DB_PASSWORD=

LLM_API_KEY=
```

Future:

```env
AWS_REGION=
S3_BUCKET_NAME=
```

---

# 39. Security

Secrets must never be committed.

Never commit:

```text
JSEARCH_API_KEY
LLM_API_KEY
DB_PASSWORD
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

Use:

```text
.env
```

and commit only:

```text
.env.example
```

---

# 40. Recommended Repository Structure

```text
glow-job-data-pipeline/
│
├── src/
│   │
│   ├── extract/
│   │   ├── jsearch_client.py
│   │   └── query_builder.py
│   │
│   ├── validation/
│   │   └── job_validator.py
│   │
│   ├── transform/
│   │   ├── job_cleaner.py
│   │   ├── deduplicator.py
│   │   ├── company_normalizer.py
│   │   ├── job_title_normalizer.py
│   │   └── career_mapper.py
│   │
│   ├── skills/
│   │   ├── extractor.py
│   │   ├── normalizer.py
│   │   └── aggregator.py
│   │
│   ├── load/
│   │   ├── database.py
│   │   └── repositories/
│   │
│   ├── storage/
│   │   ├── raw_storage.py
│   │   └── s3_storage.py
│   │
│   ├── models/
│   │
│   ├── config/
│   │
│   └── main.py
│
├── config/
│   ├── careers.yaml
│   └── pipeline.yaml
│
├── data/
│   ├── raw/
│   └── processed/
│
├── migrations/
│
├── tests/
│
├── scripts/
│
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── SPEC.md
└── GIT_WORKFLOW.md
```

---

# 41. Development Phases

## Phase 1 — Project Setup

Goal:

Create the initial pipeline structure.

Tasks:

- Python project setup
- Environment variables
- Logging
- Config files
- Testing structure

---

## Phase 2 — JSearch Extraction

Goal:

Retrieve Thailand job data.

Tasks:

- JSearch client
- Multiple search queries
- Pagination
- Error handling
- Rate-limit handling
- Response validation

Output:

```text
Raw API Response
```

---

## Phase 3 — Raw Storage

Goal:

Preserve original data.

Tasks:

- Save JSON
- Store query metadata
- Store collection timestamp
- Organize batches

Output:

```text
Raw Dataset
```

---

## Phase 4 — Database Setup

Goal:

Create PostgreSQL storage.

Tables:

```text
companies
career_roles
job_postings
skills
skill_aliases
job_skills
career_skills
```

---

## Phase 5 — Validation & Cleaning

Goal:

Produce usable job records.

Tasks:

- Validate required fields
- Clean text
- Normalize dates
- Normalize locations
- Remove unusable jobs

---

## Phase 6 — Deduplication

Goal:

Prevent duplicate records.

Tasks:

- Provider ID matching
- URL matching
- Company/title/location matching
- Description similarity when necessary

---

## Phase 7 — Company Normalization

Goal:

Create canonical company identities.

Output:

```text
company_id
```

---

## Phase 8 — Career Mapping

Goal:

Map raw job titles into career categories.

Output:

```text
job_title
normalized_job_title
career_id
```

---

## Phase 9 — Skill Extraction

Goal:

Extract skills from Job Descriptions.

Output:

```text
skill
requirement_type
confidence
```

---

## Phase 10 — Skill Normalization

Goal:

Map extracted skill variants to canonical skills.

Example:

```text
Amazon Web Services
AWS

        ↓

AWS
```

---

## Phase 11 — Job Skill Storage

Goal:

Populate:

```text
job_skills
```

---

## Phase 12 — Career Skill Aggregation

Goal:

Produce market-level skill demand.

Output:

```text
career_skills
```

---

## Phase 13 — Pipeline Automation

After the core pipeline is stable:

```text
Scheduled Run
    ↓
Fetch New Jobs
    ↓
Validate
    ↓
Deduplicate
    ↓
Process New Jobs
    ↓
Update Skills
    ↓
Recalculate Career Skills
```

---

## Phase 14 — AWS Migration

Optional later phase:

```text
Raw JSON → Amazon S3

PostgreSQL → Amazon RDS

Scheduled Execution → EventBridge + Compute
```

---

# 42. Pipeline Output

The final output of this repository should provide:

### Job-level data

```text
Company
Job Title
Career
Job Description
Location
Posted Date
Source
Required Skills
Preferred Skills
```

### Career-level data

```text
Career
Skill
Demand Count
Demand Percentage
Required Count
Preferred Count
Time Window
```

---

# 43. Definition of Ready-to-Use Data

Data is considered ready for downstream Glow-Job services when:

- Raw jobs have been validated
- Duplicates have been removed
- Company identity has been normalized
- Career has been identified
- Skill names have been normalized
- Job-level skills have been extracted
- Career-level demand has been calculated
- Data is available through PostgreSQL

---

# 44. MVP Success Criteria

The first complete pipeline is successful when it can:

```text
1. Retrieve recent Thailand jobs from JSearch

2. Preserve the raw API response

3. Store valid job postings in PostgreSQL

4. Prevent duplicate job records

5. Normalize company information

6. Map jobs to careers

7. Extract skills from Job Descriptions

8. Normalize skill names

9. Populate job_skills

10. Calculate career_skills
```

Expected final example:

```text
Career: Data Engineer
Sample Size: 327 jobs

SQL         84%
Python      79%
AWS         47%
Airflow     44%
Spark       38%
Docker      31%
Kafka       26%
```

---

# 45. Recommended Development Order

```text
Project Setup
     ↓
JSearch Extraction
     ↓
Raw Storage
     ↓
PostgreSQL
     ↓
Validation
     ↓
Cleaning
     ↓
Deduplication
     ↓
Company Normalization
     ↓
Career Mapping
     ↓
Skill Extraction
     ↓
Skill Normalization
     ↓
Job Skills
     ↓
Career Skill Aggregation
     ↓
Pipeline Monitoring
     ↓
Automation
     ↓
AWS Migration
```

---

# 46. Core Principle

This repository has one responsibility:

> Transform raw job-market data into structured, normalized, and ready-to-use job-market intelligence for the Glow-Job platform.

The pipeline should remain independent from user-specific application logic.