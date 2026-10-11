# Learning Graph: Document-to-Skill Flow

## Purpose and scope

This document describes the planned knowledge workflow that follows the market pipeline. It uses canonical names from `core.skills` to connect the domains. The market workflow answers *which skills the job market requests*; the learning graph answers *which skills should be learned first, and what sources support that order*. The fact that many jobs mention both Python and Apache Airflow does not prove that Python is a prerequisite for Airflow.

The knowledge workflow is **not implemented in this repository**. The `knowledge.*` tables appear only in the [combined DBML](../database/schemas/glow-job.dbml) and [database schema overview](../database/database-schema-overview.md). There is no migration or document-ingestion pipeline for them yet. This file describes a plan, not current system behavior.

```text
Market: JSearch → job skills → career skill demand
                          │
                          └── Select skills for learning content
                                      ↓
Knowledge: source documents → store source/files → parse text → chunk content
                                                        ├──→ semantic search/RAG (later)
                                                        └──→ propose skill relationships
                                                                      ↓
                                                           review evidence and skill names
                                                                      ↓
                                                           human verification
                                                                      ↓
                                                        usable learning graph
```

## Proposed workflow

### 1. Select skills and sources

Start with canonical skills in `core.skills` that support the product goals. `market.career_skill_stats` may help prioritize them when enough market data is available. Begin with three to five skills and a small number of official documents before scaling ingestion.

For each source, record its title, URL, publisher, source type, collection date, and original-file location in `knowledge.knowledge_sources`. Capture a document version or publication date when available. Check access and copy-retention terms before downloading. Store original files in object storage; keep metadata and a `storage_key` in the database so the source can be retrieved later.

### 2. Parse documents into traceable text

Parse HTML, Markdown, or PDF and remove non-content elements while preserving headings, hierarchy, page URLs, and document locations where possible. Split the text into section- or paragraph-based chunks. Associate each chunk with a `source_id`, `chunk_index`, and metadata such as section, language, and version.

`knowledge.knowledge_chunks` is intended to store searchable text and evidence. Embedding generation and vector search are **optional later RAG work**, not prerequisites for creating a graph. If embeddings are stored as a PostgreSQL `vector`, select and install the vector extension before creating a production migration.

### 3. Propose skill relationships

Use document text as evidence for rules or an LLM to propose relationships such as `prerequisite`, `recommended_before`, or `related`. Each proposal should identify the source and target skills, relationship type, evidence text, and source.

Hypothetical example: a tutorial says, “Learners should know Python before writing Airflow DAGs.” The system could propose `Python → Apache Airflow` as a `prerequisite`, attaching that sentence and its `source_id`. If the document merely mentions Python and Airflow on the same page, that is **not enough** evidence to create a prerequisite edge.

Resolve skill names found in documents against `core.skills` and `core.skill_aliases` before creating relationships that reference `skill_id`. Send unmatched or ambiguous names for review; do not guess or create skills and relationships automatically.

### 4. Review and publish the graph

Verify that the evidence exists in the source, the `source_id` is valid, both skills exist, no edge points from a skill to itself, and the proposed relationship does not conflict with verified edges. For `prerequisite` relationships, check for cycles that would make the learning order unusable. An LLM confidence value may assist review but is not evidence by itself.

Store proposals with `evidence_text`, `source_id`, and `is_verified=false` in `knowledge.skill_dependencies` or a review area designed later. Only relationships reviewed and confirmed by a person should become `is_verified=true` and be used to generate learning sequences.

`knowledge.learning_modules` is intended to define topics and learning outcomes for each skill and level, grounded in sources and verified graph relationships. Do not generate a personalized roadmap directly from raw documents; personalization belongs to the application and requires user-specific information.

## Related tables

| Table in combined DBML | Purpose |
|---|---|
| `core.skills`, `core.skill_aliases` | Canonical skill names and verified alternative names used to connect market and knowledge data. |
| `knowledge.knowledge_sources` | Metadata and original-file location for source documents. |
| `knowledge.knowledge_chunks` | Searchable and citable text segments; embeddings are optional. |
| `knowledge.skill_dependencies` | Graph edges with relationship type, evidence, and verification status. |
| `knowledge.learning_modules` | Learning topics and outcomes by skill and level. |
| `market.career_skill_stats` | Market data for prioritizing which skills get content first; it does not prove prerequisites. |

## Recommended MVP and decisions required before schema implementation

1. Select three to five skills and a few official sources. Store each source, its parsed text, and traceable provenance.
2. Extract prerequisite edges only when the text provides clear evidence. Route proposals for human review, then experiment with the verified graph.
3. Add `recommended_before` and `related` relationships, learning modules, embedding search, and larger-scale ingestion only when the initial results justify them.

Before creating knowledge migrations, decide whether one document can cover multiple skills. The current DBML has a single `skill_id` on both `knowledge_sources` and `knowledge_chunks`. If multi-skill documents are required, consider a link table instead. Do not duplicate an entire document just to assign a different `skill_id`. Also decide how document versions and evidence locations are represented, and how files are retained if the repository or storage provider changes.

The current DBML allows one `source_id` and one `evidence_text` per unique row in `knowledge.skill_dependencies`. If one relationship needs evidence from multiple documents, design a separate evidence and review-status table before creating migrations.

If market and knowledge data live in separate databases, do not assume their numeric `skill_id` values will match. Exchange a stable name or key, then resolve it to the destination database’s `skill_id`.
