-- Prevent repeated loads from creating another company for the same exact name.
CREATE UNIQUE INDEX uq_companies_name_lower
    ON core.companies (lower(company_name));

CREATE TABLE market.job_skills (
    job_id bigint NOT NULL REFERENCES market.job_postings (job_id),
    skill_id bigint NOT NULL REFERENCES core.skills (skill_id),
    raw_skill_name text NOT NULL,
    requirement_type text NOT NULL DEFAULT 'unknown'
        CHECK (requirement_type IN ('required', 'preferred', 'optional', 'unknown')),
    proficiency_level text NOT NULL DEFAULT 'unknown'
        CHECK (proficiency_level IN ('beginner', 'intermediate', 'advanced', 'expert', 'unknown')),
    importance_weight numeric(4, 3) NOT NULL CHECK (importance_weight BETWEEN 0 AND 1),
    skill_confidence numeric(4, 3) CHECK (skill_confidence BETWEEN 0 AND 1),
    requirement_confidence numeric(4, 3) CHECK (requirement_confidence BETWEEN 0 AND 1),
    proficiency_confidence numeric(4, 3) CHECK (proficiency_confidence BETWEEN 0 AND 1),
    overall_confidence numeric(4, 3) CHECK (overall_confidence BETWEEN 0 AND 1),
    evidence_text text NOT NULL,
    extraction_method text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, skill_id)
);

CREATE INDEX ix_job_skills_skill_id ON market.job_skills (skill_id);
