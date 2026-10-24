# Scheduled Market pipeline validation

Date: **2026-10-24, Asia/Bangkok**. Raw storage partitions and run IDs use UTC.
Branch: `feature/ec2-market-pipeline`.

## Checks performed

| Check | Result |
|---|---|
| Existing targeted pipeline regression checks | 26 passed |
| Initial full Market suite, including new runner/recovery cases | 144 passed |
| Final suite after adding summary-warning checks | **146 passed in 71.26 seconds**, including 25 new scheduled/recovery cases |
| Actual `scripts.market.run_scheduled_pipeline --live --dry-run` | Passed; 14 configured queries, S3 mode, inclusive 184-day UTC window, no service calls/writes |
| Existing AWS profile / S3 access | Credential refresh and limited listing succeeded for `glow-job-raw-data` in `us-east-1` |
| RDS preflight | Read-only schema, approved-catalog and configured-career checks passed through the existing SSH tunnel |
| Live raw upload | One JSearch query/page returned 10 valid postings; its complete raw response was uploaded to S3 |
| S3 readback | The stored JSON exactly matched the local raw record |
| Completed-run resume | Returned the saved result without repeating work |
| Real SQL loading and aggregation | Checked using an isolated temporary PostgreSQL instance with schema and public catalog/career references only |

Unit/regression tests ran without network access and without mounting application
`.env` files into the test container. The temporary PostgreSQL instance contained
no copied user/Resume data. Live API credentials were supplied to the bounded
sample process without recording their values in reports.

## Live sample and source quality

Run ID: `20261023T174556753072Z` (UTC).

```text
s3://glow-job-raw-data/raw/jsearch/2026/10/23/20261023T174556753072Z/001_data_engineer.json
```

The first sample used the new scheduled orchestrator with a test-only adapter
limiting the existing pipeline to one extracted job. The production scheduled CLI
still has no job limit. The sample JD was only 326 characters, ended mid-sentence,
and supplied no exact technical-skill evidence. Extraction correctly returned an
empty skill list and loaded the posting. An initial smoke assertion expecting a
nonzero skill count failed; this was not a provider or SQL execution failure.

The same saved raw response was then replayed through the existing full pipeline,
extending the checkpoint to a second job with a fuller JD. This made **no additional
JSearch request** and skipped the first completed skill extraction. Results:

| Result | Count |
|---|---:|
| Postings in isolated test DB | 2 |
| Catalog-matched job-skill links | 7 |
| Market statistic rows | 7 |
| Unmatched extracted skill occurrences retained for review | 11 |
| Matched skills flagged for confidence review | 6 |
| User records in the isolated DB | 0 |

This checks execution and data flow, not completeness of the source JD or quality
approval of every extracted classification. Unmatched names were not added to
the catalog. A warning was added to the scheduled summary when postings load
without any verified catalog-matched skills, with a regression check for it.

## Artifacts

Local ignored artifacts are under:

```text
data/processed/pipeline_runs/validation-20261024/
├── live_check.py
├── extend_live_check.py
└── artifacts/
    ├── live-check-report.json
    ├── extended-live-check-report.json
    ├── raw/...
    └── processed/...
```

The drivers are disposable validation harnesses, not production commands. The
saved journal contains the temporary container's data paths and is for inspection;
it is not a production resume journal on EC2. The original first-sample report is
retained along with the extended replay report rather than rewritten to hide the
empty-skill observation.

## Deployment boundary

- No data was written to RDS during these checks. SQL loading was tested in the
  isolated DB; the real RDS application role's write permissions still need an
  EC2 deployment check.
- S3 access used the existing local AWS login profile. This does not establish
  that the future EC2 instance role has the required permissions.
- This was a bounded one-query/two-job live sample, not a full 14-query production
  run. Full-run API volume, duration and quota behavior were not measured.
- Cron, external alerting and IAM attachment were not enabled or changed.
- Temporary test containers/network are removed after saving the reports. The
  genuine sample raw object remains in S3.

## 2026-10-24 follow-up: S3 recovery and RDS write

This follow-up supersedes the earlier "no RDS write" boundary above. The local
AWS login and Windows SSH tunnel were used for a bounded live check. RDS was
verified read-only as database `glowjob` before the first write (137 postings).

- Run `20261024T040831952799Z`: one `Data Engineer` query, one page,
  `date_posted=week`. JSearch returned zero jobs. The first attempt exposed a
  missing `company_aliases.yaml` in the disposable validation config overlay;
  after including it, resume reused saved raw without another JSearch call and
  completed `no_jobs`, refreshing the existing Market statistics window.
- Run `20261024T041054428496Z`: one `Data Analyst` query, one page,
  `date_posted=week`. Again zero jobs and `no_jobs`.
- Run `20261024T041150723137Z`: one `Data Engineer` query, one page,
  `date_posted=all`, to exercise downstream work. Ten jobs passed validation,
  Gemini completed ten skill extractions, and RDS gained ten postings plus 78
  catalog-matched job-skill links. Final RDS totals were 147 postings, 1,556
  job-skill links and 1,905 statistics rows. The completed run reported 52
  unmatched skill occurrences and 68 skills flagged for review; no catalog
  skills were automatically created.

S3 raw JSON had the same parsed content as the local raw file. The new S3
`state.json`, skill checkpoint, company candidate CSV and summary matched their
local files byte-for-byte. A missing state file was restored to a temporary
path through the real S3 client and matched the original bytes. The focused
Market checks passed (45 tests) after the recovery and date-filter updates.

The provider's `week` results did not agree with its `all` response: the latter
contained jobs labelled 4-5 days old. Applying the new local 7-day rule to the
saved `all` response retained three jobs and excluded seven (four older and
three without a usable date). The repository now requests `date_posted=all`
and uses `search.posted_within_days: 7` before loading. The ten-posting RDS
sample above intentionally ran with the older, unfiltered validation overlay;
seven of those ten would be excluded by the current weekly rule. Existing
postings were not deleted by this validation.

This was a one-query, one-page sample, not the full scheduled workload. The
future EC2 instance role's new S3 permission, deployment path, cron schedule,
and full 14-query runtime remain unverified.

### Corrected weekly-filter live run

Run ID: `20261024T041749173803Z`. This run used the current configuration:
`date_posted=all` with a local rolling 7-day posting-date filter. The JSearch
response contained 20 records; six had a usable posting date within seven days,
eight had no usable posting date, and six were older than seven days. Only the
six recent records continued through the pipeline. Gemini extracted skills for
all six.

| Result | Count |
|---|---:|
| Raw JSearch records saved locally and to S3 | 20 |
| Recent postings processed and loaded | 6 |
| Catalog-matched job-skill links loaded | 27 |
| Unmatched skill occurrences retained for review | 38 |
| Skills flagged for confidence review | 26 |
| Older or undated records excluded | 14 |

RDS totals after the run were 153 postings, 1,583 job-skill links and 1,905
career-skill-stat rows. Compared with the immediately preceding RDS check, this
run added six postings and 27 matched links. Unmatched names were not added to
the catalog. The raw response and all four recovery artifacts (`state.json`,
`skill_checkpoint.json`, `summary.json` and `company_candidates.csv`) were read
back from S3 and matched their local files byte-for-byte.

The prior unfiltered sample remains in RDS: seven of its ten records would not
pass the current 7-day filter. This run did not delete those earlier records.
The current configuration's 7-day filter and this run were exercised with one
career query and one JSearch page only. The complete 14-query schedule and the
EC2 instance role remain unverified.
