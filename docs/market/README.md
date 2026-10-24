# Market domain documentation

The Market pipeline collects job postings, extracts job requirements, links
skills to the shared catalog, and calculates career-level demand statistics.

- [End-to-end pipeline flow](market-pipeline-flow.md): stages from JSearch or
  raw replay through PostgreSQL loading and aggregation.
- [Project specification](market-pipeline-spec.md): domain scope and intended
  data model.
- [Pipeline data structures](pipeline-data-structures.md): how job records
  change across processing stages.
- [Skill extraction specification](skill-extraction-spec.md): extraction and
  catalog-matching rules.
- [Skill candidate review guide](skill-candidate-review-guide.md): separate
  clean-catalog prepare, review, and apply workflow.
