-- Scope and audit metadata for evidence-backed dependencies.
-- Existing rows remain unchanged and unknown until their scope is reviewed.
ALTER TABLE knowledge.skill_dependencies
    ADD COLUMN scope_type text NOT NULL DEFAULT 'unknown'
        CHECK (scope_type IN ('general', 'document_specific', 'conditional', 'unknown')),
    ADD COLUMN scope_note varchar(500),
    ADD COLUMN chunk_id bigint,
    ADD COLUMN evidence_content_hash text
        CHECK (evidence_content_hash IS NULL OR evidence_content_hash ~ '^[0-9a-f]{64}$'),
    ADD COLUMN reviewed_by varchar(100),
    ADD COLUMN reviewed_at timestamptz,
    ADD COLUMN review_note text;

ALTER TABLE knowledge.knowledge_chunks
    ADD CONSTRAINT uq_knowledge_chunks_chunk_source UNIQUE (chunk_id, source_id);

ALTER TABLE knowledge.skill_dependencies
    ADD CONSTRAINT fk_skill_dependencies_chunk_source
        FOREIGN KEY (chunk_id, source_id)
        REFERENCES knowledge.knowledge_chunks (chunk_id, source_id) ON DELETE RESTRICT;

-- NOT VALID preserves any pre-existing verification history without inventing
-- missing audit fields. New inserts/updates must meet the constraint. Runtime
-- excludes old unknown/incomplete rows until a real review supplies metadata.
ALTER TABLE knowledge.skill_dependencies
    ADD CONSTRAINT ck_skill_dependencies_verified_scope_audit CHECK (
        NOT is_verified OR (
            scope_type <> 'unknown'
            AND (scope_type = 'general' OR (scope_note IS NOT NULL AND length(btrim(scope_note)) >= 3))
            AND source_id IS NOT NULL AND chunk_id IS NOT NULL
            AND evidence_content_hash IS NOT NULL
            AND evidence_text IS NOT NULL AND length(btrim(evidence_text)) > 0
            AND reviewed_by IS NOT NULL AND length(btrim(reviewed_by)) > 0
            AND reviewed_at IS NOT NULL
            AND review_note IS NOT NULL AND length(btrim(review_note)) >= 3
        )
    ) NOT VALID;

ALTER TABLE knowledge.skill_dependencies DROP CONSTRAINT uq_skill_dependencies_edge;

CREATE UNIQUE INDEX uq_skill_dependencies_general_edge
    ON knowledge.skill_dependencies (prerequisite_skill_id, target_skill_id, dependency_type)
    WHERE scope_type = 'general';

CREATE UNIQUE INDEX uq_skill_dependencies_scoped_edge
    ON knowledge.skill_dependencies
        (prerequisite_skill_id, target_skill_id, dependency_type, scope_type, source_id, scope_note)
    WHERE scope_type IN ('document_specific', 'conditional');

CREATE UNIQUE INDEX uq_skill_dependencies_unknown_edge
    ON knowledge.skill_dependencies (prerequisite_skill_id, target_skill_id, dependency_type)
    WHERE scope_type = 'unknown';

CREATE INDEX ix_skill_dependencies_verified_scope_target
    ON knowledge.skill_dependencies (scope_type, target_skill_id) WHERE is_verified;
