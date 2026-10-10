ALTER TABLE core.skill_candidate_reviews
    DROP CONSTRAINT IF EXISTS skill_candidate_reviews_resolution_status_check;

ALTER TABLE core.skill_candidate_reviews
    ADD CONSTRAINT ck_skill_candidate_reviews_resolution_status
        CHECK (resolution_status IN (
            'mapped_existing', 'created_provisional', 'created_approved',
            'ignored', 'pending_review', 'split_applied'
        ));
