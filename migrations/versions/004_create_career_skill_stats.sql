-- A completed extraction may contain no recognized skills, but still counts
-- toward the denominator of career-level demand percentages.
ALTER TABLE market.job_postings
    ADD COLUMN skill_extraction_completed boolean NOT NULL DEFAULT false;

CREATE TABLE market.career_skill_stats (
    career_profile_id bigint NOT NULL REFERENCES core.career_profiles (career_profile_id),
    skill_id bigint NOT NULL REFERENCES core.skills (skill_id),
    analysis_start_date date NOT NULL,
    analysis_end_date date NOT NULL,
    demand_count integer NOT NULL CHECK (demand_count >= 0),
    total_jobs integer NOT NULL CHECK (total_jobs > 0),
    demand_percentage numeric(5, 2) NOT NULL
        CHECK (demand_percentage BETWEEN 0 AND 100),
    required_count integer NOT NULL DEFAULT 0 CHECK (required_count >= 0),
    preferred_count integer NOT NULL DEFAULT 0 CHECK (preferred_count >= 0),
    optional_count integer NOT NULL DEFAULT 0 CHECK (optional_count >= 0),
    weighted_demand_score numeric(8, 4)
        CHECK (weighted_demand_score BETWEEN 0 AND 1),
    target_level text NOT NULL DEFAULT 'unknown'
        CHECK (target_level IN ('beginner', 'intermediate', 'advanced', 'expert', 'unknown')),
    target_level_confidence numeric(4, 3)
        CHECK (target_level_confidence BETWEEN 0 AND 1),
    level_observation_count integer NOT NULL DEFAULT 0
        CHECK (level_observation_count >= 0),
    importance_tier text NOT NULL DEFAULT 'unknown'
        CHECK (importance_tier IN ('core', 'important', 'optional', 'unknown')),
    last_updated timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (career_profile_id, skill_id, analysis_start_date, analysis_end_date),
    CHECK (analysis_start_date <= analysis_end_date),
    CHECK (demand_count <= total_jobs)
);
