# Job Description Skill Extraction Specification

## 1. Purpose and scope

This document describes the implemented job-level skill extraction and loading
flow. It covers evidence-backed extraction from one cleaned job description,
catalog matching, confidence and importance scoring, database loading, and the
later career-level aggregation step. The numeric scoring rules are project
heuristics; they are not calibrated probabilities.

The extraction stage produces job-level records for `market.job_skills` after
catalog matching. `market.career_skill_stats` is calculated from multiple
completed job extractions and is not an LLM output for one job.

```text
Cleaned job description
        ↓
Gemini extracts atomic skills and exact evidence
        ↓
Validate output shape and evidence quotes
        ↓
Match canonical skills and aliases from PostgreSQL
        ↓
Apply deterministic importance and confidence rules
        ↓
Load matched, evidence-verified skills into market.job_skills
        ↓
Aggregate eligible jobs into market.career_skill_stats
```

## 2. Responsibilities

| Component | Responsibility |
|---|---|
| Job cleaning | Prepares a job description before extraction; it does not preselect candidate skill names. |
| Gemini extraction | Returns `raw_skill_name`, `requirement_type`, `proficiency_level`, and an exact `evidence_text` quote. |
| Response validation | Checks the JSON shape, allowed values, and that evidence is an exact substring of the submitted description. Invalid format/evidence is retried once; a second failure is an extraction failure. |
| Skill normalization | Matches exact canonical names and aliases after deterministic name normalization. It does not use fuzzy similarity for automatic database matching. |
| Scoring and loading | Verifies that the skill name appears in evidence, calculates scores from rules, and writes matched skills and extraction-completion status. Unknown catalog names remain unmatched in checkpoints. |
| Aggregation | Counts completed, dated jobs within the requested window and career profile. It can use either the provider publication date or the pipeline's first-seen date. |

## 3. Per-job extraction contract

The checkpoint result for one posting has this general shape:

```json
{
  "job_ref": "jsearch:provider-job-123",
  "extraction_status": "completed",
  "skills": [
    {
      "raw_skill_name": "Postgres",
      "requirement_type": "required",
      "proficiency_level": "unknown",
      "evidence_text": "Experience using Postgres in production is required."
    }
  ]
}
```

`job_ref` associates the result with a posting before a database `job_id` is
available. The checkpoint distinguishes `completed` with `skills: []` from
`failed`; a failed extraction must not be counted as a job with no skills.

The normalized database representation includes `skill_id`, the canonical
`skill_name`, the observed `raw_skill_name`, classification fields, scores,
evidence, and `extraction_method`. The LLM does not assign database IDs or
scores. In the current loader, `extraction_method` is stored as `llm`.

## 4. Extraction fields

### `raw_skill_name`

The concise skill label returned from the job description. The extraction prompt
asks for one distinct skill per item, without surrounding prose or a list of
multiple skills. Established composite names such as `CI/CD` are retained as a
single skill when they name one skill. Enumerations such as `Python, SQL, and
Tableau` or `Python or R` should be returned as separate items.

### `requirement_type`

Allowed values are `required`, `preferred`, `optional`, and `unknown`.

| Value | Meaning |
|---|---|
| `required` | The description states that the skill is required or mandatory. |
| `preferred` | The skill is an advantage, such as a plus, bonus, or nice-to-have. |
| `optional` | The description explicitly marks it optional without a preferred qualification cue. |
| `unknown` | The description mentions the skill but does not provide enough context to classify it. |

The extractor prompt maps `plus`, `bonus`, and `nice-to-have` wording to
`preferred`. A skill explicitly stated as unused must not be extracted as a
requirement.

### `proficiency_level`

Allowed values are `beginner`, `intermediate`, `advanced`, `expert`, and
`unknown`. This field describes the level requested by the job, not an
assessment of an applicant.

| Job-description cue | Level | Initial confidence |
|---|---|---:|
| `beginner` | `beginner` | 0.95 |
| `basic`, `fundamental` | `beginner` | 0.90 |
| `intermediate` | `intermediate` | 0.95 |
| `working knowledge`, `practical experience` | `intermediate` | 0.85 |
| `advanced` | `advanced` | 0.95 |
| `strong`, `solid` directly describing the skill | `advanced` | 0.80 |
| `expert` | `expert` | 0.98 |
| `deep expertise`, `specialist` | `expert` | 0.90 |
| No clear level cue | `unknown` | 0.95 |

The extractor must not infer a level from years of experience alone. Ambiguous
phrases such as `proficient` are not assigned a level automatically by the
current prompt policy.

### `evidence_text`

Evidence must be copied exactly as a continuous substring from the cleaned job
description. The parser rejects missing or non-exact quotes. The scoring step
also checks that the raw skill name appears in the evidence. If evidence cannot
support a returned skill or classification, confidence remains unresolved or
the extraction is rejected; the system must not invent a paraphrased quote.

## 5. Catalog normalization and matching

The normalizer applies Unicode compatibility normalization, case folding, and
whitespace cleanup before lookup. It supports these deterministic cases:

- Exact canonical-name and confirmed-alias matches.
- Verified acronym suffix forms, for example a canonical name followed by a
  matching acronym in parentheses, when the acronym initials validate.
- A leading `and` or `or` is removed only if the complete remaining label
  matches a catalog entry.
- A comma- or semicolon-separated label is split only when every component is
  present in the supporting evidence. Slash-separated strings are not split by
  this rule because `/` can be part of a single skill name such as `CI/CD`.

No fuzzy or semantic match automatically assigns a `skill_id`. Names not
matched to the catalog remain in `unmatched_skills` in the checkpoint; the
normal job-skill loader does not create skills or aliases. Use the separate
[clean catalog rebuild and review flow](skill-candidate-review-guide.md) to
resolve unknown names.

Matching only establishes a catalog-name relationship. The loader also checks
the cited evidence before storing a job-skill row. It stores at most one row per
`(job_id, skill_id)`; repeated mentions of one canonical skill are consolidated.
Conflicting proficiency levels become `unknown` for that matched skill.

## 6. Importance and confidence scoring

### `importance_weight`

The loader calculates this deterministic score; Gemini does not provide it.

```text
importance_weight = 0.7 × requirement_score + 0.3 × proficiency_score
```

Requirement scores: `required=1.00`, `preferred=0.60`, `optional=0.30`,
`unknown=0.40`. Proficiency scores: `expert=1.00`, `advanced=0.90`,
`intermediate=0.70`, `beginner=0.50`, `unknown=0.60`. The result is rounded to
three decimal places. For example, `required + advanced` yields `0.970`.

### Confidence fields

Confidence values are evidence-strength heuristics, not guarantees of semantic
correctness or calibrated probabilities.

| Field | Meaning |
|---|---|
| `skill_confidence` | Strength of the canonical-name match, subject to evidence validation. |
| `requirement_confidence` | Whether the requirement classification is supported by clear cues or a recognized section heading. |
| `proficiency_confidence` | Whether the proficiency classification is supported by a clear cue. |
| `overall_confidence` | Weighted summary, calculated only when requirement and proficiency confidence are available. |

Current skill-match values are `1.00` for exact canonical names and `0.95` for
exact aliases. A skill with `catalog_status=provisional` receives `0.70`. If
the raw name does not appear in the evidence, the skill is not loaded.

The scorer checks known requirement and proficiency cues, negation, repeated
mentions, and a limited set of recognized section headings. Repeated skill
mentions, conflicts, unsupported classifications, and certain conditional or
negated contexts can produce `NULL` confidence values for review. An `unknown`
classification can receive `0.95` when no cue is found; this means the system
is confident that the text did not specify a classification, not that it knows
the actual level.

When all components are available:

```text
overall_confidence = 0.40 × skill_confidence
                   + 0.35 × requirement_confidence
                   + 0.25 × proficiency_confidence
```

The value is rounded to three decimal places. If a required component is
unresolved, `overall_confidence` is `NULL`; scores are not renormalized.

## 7. Database record

`market.job_skills` stores one row per `(job_id, skill_id)` with:

- `raw_skill_name`, `requirement_type`, and `proficiency_level`
- `importance_weight`
- `skill_confidence`, `requirement_confidence`,
  `proficiency_confidence`, and `overall_confidence`
- `evidence_text` and `extraction_method`

The canonical name is obtained by joining `skill_id` to `core.skills`. The
loader processes only completed extractions, postings with stable provider IDs,
and jobs mapped to a configured career profile. A successful extraction with an
empty skill list still sets `skill_extraction_completed=true`; a failed
extraction does not. Catalog-unmatched or evidence-unverified skills are not
written to `market.job_skills`.

## 8. Career-level aggregation

The aggregation command computes statistics by career profile and an inclusive
UTC date window. Select the date field with `--date-basis`:

- `posted_at` (default) uses the provider's publication date. Jobs with no
  usable `posted_at` are not part of that date window.
- `first_seen_at` uses the earliest collection time retained for the posting.
  It includes jobs with no publication date, but describes when the pipeline
  observed them; it cannot reconstruct market activity before collection.

Only postings with `skill_extraction_completed=true` and a non-empty job
description are eligible. Successfully extracted jobs with no matched skills
remain in `total_jobs` and the denominator. Failed extractions are not loaded as
completed. `demand_count` counts jobs containing a skill, not raw mentions.
The aggregator calculates `demand_percentage`, requirement counts, and the
average `importance_weight` over eligible jobs. `target_level` is the most
frequent known proficiency level; a tie yields `unknown`. `importance_tier`
remains `unknown` because no reviewed tier thresholds are currently configured.

The aggregation refresh replaces statistics for the selected date window and
basis, so rerunning the same command does not duplicate those rows.

## 9. Implemented behavior and future work

| Capability | Status |
|---|---|
| Gemini extraction of atomic labels and evidence | Implemented; the prompt version is `atomic-skill-v2`. |
| JSON, enum, and exact-quote validation | Implemented; one format/evidence retry is allowed. |
| Canonical and alias normalization; unmatched checkpoint retention | Implemented. |
| Exact evidence verification and rule-based scoring | Implemented. |
| Fuzzy or embedding-based automatic matching | Not implemented; fuzzy similarity is not used to assign catalog IDs. |
| Fully automated interpretation of every negation, section, or conditional phrase | Not implemented; ambiguous cases may have unresolved confidence. |
| Career-level aggregation by publication or first-seen date | Implemented. |
| Automatic `importance_tier` thresholds | Not configured; values remain `unknown`. |
| Resume extraction and learning-document/RAG processing | Scaffolded for future domains; see the [repository architecture](../architecture/repository-architecture.md). |

## 10. Acceptance checks for extraction quality

When reviewing extraction output, check that:

1. Each returned skill is supported by an exact quote from the job description.
2. Lists of distinct skills are emitted as separate items.
3. A skill stated as unused is not classified as required.
4. Proficiency is not inferred without a level cue.
5. Confirmed aliases map to one canonical skill while preserving the raw name.
6. A job does not contain duplicate rows for the same canonical skill.
7. Completed-empty results are distinguishable from failed extractions.
8. Importance and confidence values can be reproduced from the documented
   rules.
9. Aggregation includes completed-empty jobs in its denominator and excludes
   failed extractions.
