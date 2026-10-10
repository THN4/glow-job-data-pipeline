# Skill Catalog Rebuild Preview

## Purpose

The current catalog contains skill rows that need to be reviewed as one set.
Build the proposed catalog from the approved bootstrap list and raw skill
checkpoint evidence, then review the preview before applying any database
reset or catalog changes.

`config/skills.yaml` is the bootstrap input used to start or recreate the
approved catalog. It is not the place to add every newly extracted skill.
All extracted names, whether they resemble a bootstrap skill or suggest a new
skill, enter the same candidate grouping and suggestion flow. After approval,
the database catalog becomes the runtime source of truth.

## Preview behavior

Run:

```powershell
python -m scripts.preview_skill_catalog_rebuild
```

The script reads every `*.json` file under
`data/processed/skill_extraction/`, deduplicates postings by provider job ID,
and compares raw extracted names with canonical names and aliases from the
bootstrap catalog. It does not read or write PostgreSQL and does not edit
checkpoints.

The preview groups case and spacing variants. It also groups names containing
the same words in a different order, such as `AI agent` and `agent AI`, and
marks how the group was formed. This lexical grouping is a review aid: the LLM
must consider the evidence before proposing a canonical mapping.

The output is
`data/processed/skill_candidates/catalog_rebuild_preview.csv`. It includes
observed names, occurrence and posting counts, source runs, career names,
evidence examples, likely bootstrap matches, possible duplicate candidates,
model suggestions, and blank manual decision columns. Possible duplicates are
review flags, not automatic merges.

To add suggestions for the top candidates, explicitly call Gemini:

```powershell
python -m scripts.preview_skill_catalog_rebuild --suggest-limit 100
```

Gemini suggestions do not change a skill or candidate record in PostgreSQL.
When more than one candidate is suggested, a second Gemini pass flags semantic
duplicates across the proposed names; those groups are sent to manual review.
The preview uses other candidate labels as context so equivalent new-skill
proposals can converge on one canonical spelling.
`ready_for_approval` means the suggestion meets the preview's support checks;
it is still a proposal. `manual_review` covers uncertain or weak evidence,
generic collection phrases, compound phrases, and decisions below the support
threshold. A proposal needs high model confidence and at least one matching
evidence excerpt from a posting. New skills may be surfaced from one posting;
the preview does not create them automatically, and possible duplicates still
go to manual review. The model's confidence is not a calibrated probability.

To compare candidates with the catalog currently in PostgreSQL, run:

```powershell
python -m scripts.preview_skill_catalog_rebuild --compare-database-catalog
```

This reads canonical skill names and aliases from PostgreSQL. Exact matches are
shown separately from approximate name matches; approximate matches are search
hints and must be checked against the evidence. The interactive reviewer loads
the catalog read-only and displays the same comparison beside each candidate:

```powershell
python -m scripts.review_skill_catalog_preview
```

To check counts without starting the interactive review, run:

```powershell
python -m scripts.review_skill_catalog_preview --summary
```

To print the entire current DB catalog as a separate list (including category,
approved/provisional status, aliases, and bootstrap membership), run:

```powershell
python -m scripts.review_skill_catalog_preview --list-catalog
```

To flag existing comma/conjunction aliases and canonical names that differ only
by a verified parenthetical acronym, run this read-only audit:

```powershell
python -m scripts.review_skill_catalog_preview --audit-catalog-names
```

Choose map-existing, create-new, ignore, or split. For split, enter the number
of component skills, then choose map-existing or create-new for each component;
the reviewer validates names and categories and builds the saved split data for
you, so there is no need to type JSON. Enter `q` at any prompt to cancel the
split without saving it. The reviewer saves decisions
only to the CSV; it does not apply them to PostgreSQL or rewrite extraction
checkpoints. Decisions are saved after each completed row. Press Enter to skip
a row and `q` to stop. To search for a canonical
name that is not among the displayed matches, type `?text` at the canonical
name prompt. Canonical names marked `create_new` earlier in the same CSV can
also be selected by later candidates, so equivalent candidates can point to
one approved spelling. By default it shows `manual_review` candidates and candidates
with an exact current DB match. Add `--all-candidates` to include every row,
including candidates that have not received an LLM suggestion yet. Preview
generation preserves prior suggestions and decisions by default; `--fresh`
starts a new output without them. For `create-new`, choose the candidate name,
the LLM-proposed name, or enter a custom canonical name.

## Safe boundary before database changes

The preview and manual decision columns are the review stage. The reviewer
does not update PostgreSQL or rewrite extraction checkpoints. The previous
per-run resolver and review commands have been removed from the active
workflow. `scripts.load_job_skills` and `scripts.run_pipeline` do not resolve
unknown names automatically.

After reviewing the proposed catalog, run the separate apply/reset operation
to:

1. preserves postings, extraction checkpoints, and source evidence;
2. backs up the current skill catalog and job-skill associations;
3. rebuilds canonical skills and aliases from the approved preview;
4. reloads job-skill associations from the selected checkpoints, expanding
   reviewed split phrases into their selected components; and
5. reports before/after counts and unresolved candidates.

Split components are loaded from transformed checkpoint copies in the backup
folder; the original extraction checkpoints remain unchanged. Their review
queue row is marked `split_applied`.

## Composite labels and duplicate canonical names

This section records the source findings, implementation choices, checks, and
the boundary before any database reset.

### Findings and source references

- `src/skills/catalog_rebuild_preview.py::_preview_status` currently sends any
  candidate containing a comma, `and`, `or`, or spaced slash to manual review.
  The candidate suggester prompt in `src/skills/candidate_suggester.py::_build_prompt`
  also tells Gemini not to map multi-skill phrases to a single skill, but does
  not ask it to split the phrase. This explains why obvious comma-separated
  lists reach the reviewer.
- `scripts/rebuild_skill_catalog_from_checkpoints.py::_build_final_catalog`
  adds observed names as aliases for `create_new` and `map_existing` decisions.
  The `split_into_skills` branch does not add the full observed name as an
  alias; `_write_split_checkpoints` instead replaces the composite raw name
  with the reviewed components in transformed checkpoint copies.
- `src/skills/normalizer.py::skill_name_key` performs Unicode NFKC, case-folding,
  and whitespace normalization only. It does not expand acronyms or strip
  parenthetical text, so `Machine Learning` and `Machine Learning (ML)` remain
  distinct keys. `_family_key` in `src/skills/catalog_rebuild_preview.py`
  compares all tokens and therefore does not group those two names as the same
  family. The duplicate scan only flags possible matches for review; it does
  not merge canonical skills.
- Runtime alias lookup in `src/skills/normalizer.py::normalize_skills_for_jobs`
  is an exact normalized-key lookup. It does not split aliases. A composite
  alias therefore maps the whole extracted phrase to one `skill_id`.

### Implementation plan

1. Add a deterministic post-extraction composite-label pass for comma- and
   semicolon-separated skill names. It will trim empty components and
   deduplicate equivalent components, then carry the original posting,
   evidence, requirement, and proficiency fields to each component. It will
   retain the source composite for traceability, but never create an alias
   from that full composite. Initially, slash and conjunction-based phrases
   remain review-only because they can express one combined skill or an
   ambiguous relationship.
2. Run catalog matching and candidate suggestions on the individual
   components. Existing exact canonical/alias matches can resolve without
   manual review. Only unknown or ambiguous components enter the review
   queue; an explicit one-to-one component mapping may create an alias for
   that component alone.
3. Strengthen duplicate handling in layers. Formatting-only equivalence stays
   automatic. Parenthetical acronym handling is automatic only when the
   abbreviation can be verified against the canonical name (for example,
   `ML` matching the initials of `Machine Learning`) and the key is
   unambiguous. Token-order variants and semantic matches remain suggestions
   for review rather than automatic merges.
4. Change the rebuild/apply workflow to reuse saved extraction checkpoints by
   default. The current `scripts/rebuild_skill_catalog_from_checkpoints.py`
   calls `_reextract_checkpoints` during `--apply`; the new default must not
   invoke the job-level extractor again. Re-extraction will remain an explicit
   opt-in. Candidate suggestions may still call Gemini for novel components
   unless disabled, but they are not a full job-description extraction pass.
5. Add a read-only audit preview for existing aliases and canonical names.
   Composite-looking aliases and likely duplicates will be listed with their
   canonical targets and evidence counts. No existing alias or skill will be
   deleted or merged automatically. Any eventual data cleanup must be reviewed
   separately, backed up, and followed by rebuilding affected job-skill links
   and aggregates.

### Acceptance checks

- A raw label such as `Python, SQL` produces two component observations and
  never creates `Python, SQL` as an alias.
- When both components match approved catalog entries, neither component
  requires manual review; when only one is unknown, only that component is
  queued.
- A manually mapped component can create an alias for that component, but not
  for the original composite phrase.
- `Machine Learning (ML)` is recognized as a possible match for
  `Machine Learning` under the verified-acronym rule, while unrelated or
  ambiguous parenthetical text is not silently removed.
- A no-write dry run reports before/after candidate groups, matched components,
  unmatched split components, and composite groups. It does not call Gemini,
  so the final number of manual reviews remains unknown until candidate
  suggestions are generated; candidate-group count alone is not presented as
  review count or as a guaranteed reduction.
- Tests cover splitting, evidence/provenance preservation, alias prevention,
  acronym equivalence, ambiguous-name safety, and reuse of checkpoints without
  invoking the extractor.

### Scope boundary

Implementation may update code, tests, and this plan. It will not execute
`--apply`, delete or merge catalog rows, edit `core.skill_aliases`, or alter
stored job-skill links. Those database actions require a separate reviewed
preview and explicit user direction.

### Implementation and dry-run status (2026-10-10)

The code now performs evidence-checked comma/semicolon splitting in both
preview aggregation and runtime normalization, maps verified parenthetical
acronyms to a matching base canonical, deduplicates verified-acronym proposals
while rebuilding, rejects composite labels as single-skill aliases, and
transfers saved comma-split decisions to their individual components. The
read-only `--audit-catalog-names` command lists composite aliases and
verified-acronym canonical duplicates with their job counts. The
rebuild command now reuses saved checkpoints by default; `--reextract` is the
explicit opt-in to call the job-level extractor.

The current read-only dry run over 2 checkpoint runs / 137 jobs found 37
evidence-supported composite occurrences, producing 142 components. Seven
components matched the bootstrap catalog directly; 135 remained unmatched for
candidate suggestion. The raw candidate-group count changed from 660 before
splitting to 705 after splitting (+45), so this number is not evidence that
manual-review work has already decreased. The dry run made no Gemini calls,
file writes, or database writes; actual review counts depend on the later
candidate-suggestion statuses.
