ALTER TABLE core.skills
    ADD COLUMN catalog_status text NOT NULL DEFAULT 'approved'
        CHECK (catalog_status IN ('approved', 'provisional'));

CREATE TABLE core.skill_candidate_reviews (
    candidate_key text PRIMARY KEY,
    candidate_name text NOT NULL,
    observed_names jsonb NOT NULL DEFAULT '[]'::jsonb,
    resolution_status text NOT NULL
        CHECK (resolution_status IN (
            'mapped_existing', 'created_provisional', 'created_approved',
            'ignored', 'pending_review'
        )),
    resolution_method text NOT NULL DEFAULT 'automatic'
        CHECK (resolution_method IN ('automatic', 'human')),
    suggestion_decision text
        CHECK (suggestion_decision IN (
            'existing_skill', 'new_skill', 'not_skill', 'uncertain'
        )),
    confidence_level text
        CHECK (confidence_level IN ('high', 'medium', 'low')),
    suggested_skill_name text,
    suggested_skill_category text,
    resolved_skill_id bigint REFERENCES core.skills (skill_id),
    occurrence_count integer NOT NULL DEFAULT 0 CHECK (occurrence_count >= 0),
    job_count integer NOT NULL DEFAULT 0 CHECK (job_count >= 0),
    examples jsonb NOT NULL DEFAULT '[]'::jsonb,
    rationale text,
    last_seen_run_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_skill_candidate_reviews_status
    ON core.skill_candidate_reviews (resolution_status, job_count DESC);
