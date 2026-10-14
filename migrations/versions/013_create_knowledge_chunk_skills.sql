-- Migrate existing single-skill links to support chunks that cover multiple skills.
CREATE TABLE knowledge.knowledge_chunk_skills (
    chunk_id bigint NOT NULL REFERENCES knowledge.knowledge_chunks (chunk_id) ON DELETE CASCADE,
    skill_id bigint NOT NULL REFERENCES core.skills (skill_id),
    CONSTRAINT pk_knowledge_chunk_skills PRIMARY KEY (chunk_id, skill_id)
);

CREATE INDEX ix_knowledge_chunk_skills_skill_id
    ON knowledge.knowledge_chunk_skills (skill_id);

INSERT INTO knowledge.knowledge_chunk_skills (chunk_id, skill_id)
SELECT chunk_id, skill_id
FROM knowledge.knowledge_chunks
WHERE skill_id IS NOT NULL;

ALTER TABLE knowledge.knowledge_chunks
    DROP COLUMN skill_id;
