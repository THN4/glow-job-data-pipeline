# Resume domain documentation

The resume/CV package provides reusable parsing, extraction contracts and
prompts, schemas, and post-processing. The host backend owns API routes,
uploads, job lifecycle, and profile persistence. CLI scripts and database
loading for Resume are not implemented yet.

The package boundaries and implementation constraints are documented in the
[resume package README](../../src/resume/README.md). Resume-specific database
tables and retention rules should be documented here when those requirements
are defined. Reusable cross-domain schema decisions belong in [the database
schema overview](../database/database-schema-overview.md).
