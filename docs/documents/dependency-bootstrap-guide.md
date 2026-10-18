# Catalog dependency bootstrap: superseded experiment

The user clarified on 2026-10-18 that dependencies must come only from their
prepared documents. The catalog-only generation of 491 relationships from
539 skills was outside that scope and is not a current review or handoff queue.
No human approvals or database inserts were made from that batch.

The uncommitted general-knowledge generator was removed. Its local raw responses
and catalog-bootstrap-v1 JSON/Markdown remain as reference artifacts. Current
commands reject that manifest format to avoid reviewing or exporting it by mistake.

Use the [prepared-document dependency workflow](skill-dependency-review-guide.md).
The root CMD shortcut now opens prepared-documents-v1.json:

```cmd
scripts\rag\review_dependencies.cmd
```