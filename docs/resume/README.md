# Resume domain documentation

This folder documents the implemented Resume flow and its boundary with the
host Backend:

- [Current end-to-end flow](resume-pipeline-flow.md): upload through
  preprocessing, Gemini extraction, user review, and confirmed-profile save.
- [Current-state review](01-current-state-review.md): existing flow, evidence,
  and identified gaps.
- [Proposed extraction scope and specification](02-extraction-spec.md): target
  behavior, domain boundaries, and quality requirements. Treat its proposed
  items as design context; the flow document describes current behavior.

The implementation preserves raw profile skill labels as `rawName`, exposes
provider/model and processing versions in extraction metadata, scopes the cache
to the file plus output-affecting configuration, and uses Gemini for model-backed
CV extraction. PDFs are classified page by page; mixed text/scanned documents
send both readable text and page images to Gemini in source order. If image
page limits omit scanned pages, `meta.isPartial` is true and the result warning
lists those page numbers.
The Gemini prompt treats CV contents as untrusted data and requires atomic
skill/tool entries. `mock` remains available for tests and local development.

The reusable package layout is also summarized in the
[resume package README](../../src/resume/README.md). The backend owns API routes,
uploads, job lifecycle, profile persistence, and the adapter that reads the
shared skill catalog. The extraction engine remains database-free and preserves
the wording found in the CV. After extraction, the backend compares those labels
with the same `core.skills` and `core.skill_aliases` catalog used by Market,
using shared deterministic matching rules. This lets the review screen show
existing canonical skills without making the resume model infer or create
catalog entries. Unmatched or ambiguous skills stay visible for review and are
not silently discarded.

When the Backend has database settings, it saves a user-confirmed profile to
the `app` schema using an anonymous session identity. Without DB settings, its
local development repository uses JSON. The reusable extraction package does
not write either store. Reusable cross-domain schema decisions belong in the
[database schema overview](../database/database-schema-overview.md).
