-- 0014 (9 Oct 2026, scope change C3/C4): the three-tier AG workflow per pension wing.
--
-- Roles AG_SENIOR_AUDITOR, AG_ASSISTANT_AO and AG_AO join the users table; every AG officer at
-- a tier belongs to one pension wing (Pension-I .. Pension-V, api.departments.PENSION_SECTION_ORDER),
-- kept in its own column -- a wing is not a department. SQLite cannot widen a CHECK constraint in
-- place, so the users table is rebuilt (as 0010 did) with the one new column and its rows copied.
--
-- Who holds a case inside the AG is a COLUMN on cases (holder_tier: SENIOR_AUDITOR | ASSISTANT_AO | AO),
-- not a set of new statuses: the existing statuses keep their meaning and every filter, report and
-- old history row reads as before, while the register shows "With Senior Auditor, Pension-III"
-- from status + holder + the department's wing. Cases the AG already holds start in the Senior
-- Auditor's queue, where the new flow begins.
CREATE TABLE IF NOT EXISTS users_v14 (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('DEPT_OFFICER', 'AG_UPLOAD', 'AG_REVIEWER', 'AG_DAG', 'ADMIN',
                                                 'AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO')),
    department_code TEXT REFERENCES departments(code),
    active          INTEGER NOT NULL DEFAULT 1,
    token_version   INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    pension_wing    TEXT
);
INSERT OR IGNORE INTO users_v14 (id, username, display_name, password_hash, role, department_code, active,
                                 token_version, created_at, updated_at, must_change_password)
    SELECT id, username, display_name, password_hash, role, department_code, active,
           token_version, created_at, updated_at, must_change_password FROM users;
DROP TABLE users;
ALTER TABLE users_v14 RENAME TO users;

ALTER TABLE cases ADD COLUMN holder_tier TEXT;
UPDATE cases SET holder_tier = 'SENIOR_AUDITOR'
 WHERE holder_tier IS NULL AND status IN ('FORWARDED', 'AI_CHECKING', 'AI_FAILED', 'UNDER_REVIEW');
CREATE INDEX IF NOT EXISTS cases_holder ON cases(status, holder_tier);
