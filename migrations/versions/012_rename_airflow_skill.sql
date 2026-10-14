-- Normalize the canonical skill label while preserving its existing skill_id.
UPDATE core.skills
SET skill_name = 'Apache Airflow',
    updated_at = now()
WHERE lower(skill_name) = 'airflow';

-- Keep the former canonical label usable when matching older job/document data.
-- If this alias is already claimed by another skill, leave it unchanged for review.
INSERT INTO core.skill_aliases (skill_id, alias)
SELECT s.skill_id, 'airflow'
FROM core.skills AS s
WHERE lower(s.skill_name) = 'apache airflow'
  AND NOT EXISTS (
      SELECT 1
      FROM core.skill_aliases AS a
      WHERE lower(a.alias) = 'airflow'
  );
