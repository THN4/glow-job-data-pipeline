ALTER TABLE market.job_postings
    ADD COLUMN posted_at_status text NOT NULL DEFAULT 'unknown';
ALTER TABLE market.job_postings
    ADD COLUMN first_seen_at timestamptz;

UPDATE market.job_postings
SET posted_at_status = 'unclassified'
WHERE posted_at IS NOT NULL;
UPDATE market.job_postings
SET first_seen_at = created_at;

ALTER TABLE market.job_postings
    ALTER COLUMN first_seen_at SET DEFAULT now(),
    ALTER COLUMN first_seen_at SET NOT NULL;

ALTER TABLE market.job_postings
    ADD CONSTRAINT ck_job_postings_posted_at_status
    CHECK (
        posted_at_status IN ('exact', 'estimated', 'unknown', 'unclassified')
    );

ALTER TABLE market.career_skill_stats
    ADD COLUMN analysis_date_basis text NOT NULL DEFAULT 'posted_at';

ALTER TABLE market.career_skill_stats
    DROP CONSTRAINT career_skill_stats_pkey;

ALTER TABLE market.career_skill_stats
    ADD CONSTRAINT career_skill_stats_pkey PRIMARY KEY (
        career_profile_id,
        skill_id,
        analysis_start_date,
        analysis_end_date,
        analysis_date_basis
    );

ALTER TABLE market.career_skill_stats
    ADD CONSTRAINT ck_career_skill_stats_date_basis
    CHECK (analysis_date_basis IN ('posted_at', 'first_seen_at'));
