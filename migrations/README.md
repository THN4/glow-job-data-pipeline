# Database migrations

Migration files are applied in filename order by `python -m scripts.migrate`. Each successful file is recorded in `system.schema_migrations`, so running the command again skips already-applied migrations.

The first migration creates the database objects needed to load JSearch market postings and their ingestion/query provenance. Later pipeline tables such as skills and career aggregates should be added in their own migration when those stages are implemented. Migration `005` adds a date-quality label, a stable `first_seen_at`, and a date basis to career statistics. This lets the pipeline retain postings with no provider-supplied date and aggregate trends either by publication date or by when the pipeline first collected each posting. Existing dated rows are labeled `unclassified` because earlier versions did not record whether their date was exact or estimated; their `first_seen_at` is backfilled from `created_at`.
