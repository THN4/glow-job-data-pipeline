# Clean Skill Catalog Rebuild

## Goal

Create a new skill catalog from job-description evidence without carrying forward
the old skill names or IDs. The category vocabulary is a small set of structural
labels in `src/skills/categories.py`; it does not contain a predefined list of
skill names. Gemini proposes atomic skill names from the saved job descriptions,
and the reviewer resolves proposals before they reach PostgreSQL.

## Prepare a fresh review set

Run this from the repository root with `GEMINI_API_KEY` configured:

```powershell
python -m scripts.rebuild_skill_catalog_from_checkpoints --prepare-only --reextract --force-all-extraction
```

This reads the saved, cleaned job descriptions in
`data/processed/skill_extraction/` and calls Gemini again for every posting.
The extraction prompt asks for one skill per item and requests concise names,
splitting enumerations such as `Python, SQL, and Tableau` into individual
skills. It preserves established single labels such as `CI/CD`. A separate
Gemini proposal step suggests canonical names and flags possible duplicates.
The model's confidence is a review hint, not a calibrated probability.

Preparation backs up the checkpoint JSON files and the prior preview into a
timestamped directory under `data/processed/skill_catalog_backups/`. It writes
the new extraction and preview locally, but does not change PostgreSQL. If
Gemini fails or returns invalid evidence, the operation stops before any DB
reset. Rerun preparation to retry the incomplete extraction; successful current
prompt entries are reused unless `--force-all-extraction` is specified again.

## Review

See counts and inspect the selected canonical names:

```powershell
python -m scripts.review_skill_catalog_preview --summary
python -m scripts.list_skill_catalog_rebuild_names
python -m scripts.review_skill_catalog_preview --list-catalog
```

Review the uncertain rows interactively:

```powershell
python -m scripts.review_skill_catalog_preview
```

The candidate view includes occurrence counts, posting counts, LLM proposal,
similar proposed names, and job-description evidence. Depending on the row,
choose map to an existing proposed name, create a canonical name, ignore, or
split into individual skills. For a new name, the reviewer offers the proposed
name for quick selection and also accepts a custom name. Split components can
each map to another selected name or create their own canonical name.

Decisions are saved to
`data/processed/skill_candidates/catalog_rebuild_preview.csv`; reviewing does
not write to PostgreSQL. `ready_for_approval` rows already have an automatic
proposal and do not require a manual decision unless you want to correct one.
Resolve `manual_review` and `needs_llm_suggestion` rows before apply. The apply
command refuses to reset the DB while any required manual decision remains.

### Correct a previous decision or merge duplicate proposals

If two candidate names refer to the same skill, keep one proposed canonical
name and map the other candidate to it. To revisit saved decisions and
high-confidence proposals, run:

```powershell
python -m scripts.review_skill_catalog_preview --include-reviewed --all-candidates
```

This edits only the preview CSV; it does not call Gemini or write to the DB.
After checking the proposed catalog with `--list-catalog`, run `--dry-run`,
then `--apply` to rebuild canonical skills, aliases, and job-skill links from
the saved checkpoints. If the catalog was already applied, the same process
can be repeated: apply backs up and rebuilds the five skill-related tables
again, and restarts skill IDs from 1. Job postings and other non-skill tables
remain in place.

## Apply after review

```powershell
python -m scripts.rebuild_skill_catalog_from_checkpoints --apply
```

Before writing, the script verifies that available checkpoints cover every
posting currently in the DB and creates a JSON backup of the five skill tables.
Then, in one database transaction, it truncates and restarts identity only for:

- `core.skills`
- `core.skill_aliases`
- `core.skill_candidate_reviews`
- `market.job_skills`
- `market.career_skill_stats`

The rebuild recreates skills, aliases, reviewed candidate records, posting-skill
links, and career aggregates. `core.skills.skill_id` starts at 1 again. Posting,
company, career, and source tables are retained. If apply validation fails, the
transaction does not commit the reset.

For a split decision, apply substitutes the selected components into temporary
checkpoint copies used by the loader. The original Gemini extraction results
remain available in the checkpoint backup and are not overwritten by the split.

## After the rebuild

The database catalog becomes the source of truth for normal runtime matching.
Future extraction can match exact canonical names and approved aliases. Unknown
names remain unmatched until they are reviewed through a later catalog update.
There is no YAML skill-name seed file or separate skill seeding command.
