-- 0014 for PostgreSQL: the three tiers and the pension wing on users; the holder tier on cases.
-- See ../0014_wing_tiers.sql for why a column and not new statuses. PostgreSQL widens the CHECK in
-- place (users_role_check is the name it gave the constraint in 0001, re-made in 0010).
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('DEPT_OFFICER', 'AG_UPLOAD', 'AG_REVIEWER', 'AG_DAG', 'ADMIN',
                    'AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS pension_wing TEXT;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS holder_tier TEXT;
UPDATE cases SET holder_tier = 'SENIOR_AUDITOR'
 WHERE holder_tier IS NULL AND status IN ('FORWARDED', 'AI_CHECKING', 'AI_FAILED', 'UNDER_REVIEW');
CREATE INDEX IF NOT EXISTS cases_holder ON cases(status, holder_tier);
