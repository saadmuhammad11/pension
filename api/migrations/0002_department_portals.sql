-- A portal for every department; AG Upload retired (25 Sep 2026).
--
-- Departments gain the portal particulars the config file (api/departments.py) carries; the
-- seed fills them. Cases uploaded by the retired AG Upload role become ordinary department cases
-- (the department was always the case's own); their created_by is reassigned by the seed, once
-- the department's officer account exists, and the ag.upload account is then removed.
--
-- The CHECK constraints on users.role / cases.created_via still list AG_UPLOAD: SQLite cannot
-- alter a CHECK in place, every stored value is within the constraint, and rebuilding tables under
-- foreign keys and append-only triggers is risk for no gain. The role simply is not used any more.

ALTER TABLE departments ADD COLUMN slug TEXT;
ALTER TABLE departments ADD COLUMN is_police INTEGER NOT NULL DEFAULT 0;
ALTER TABLE departments ADD COLUMN theme TEXT;
ALTER TABLE departments ADD COLUMN port INTEGER;

UPDATE cases SET created_via = 'DEPARTMENT' WHERE created_via = 'AG_UPLOAD';

-- The account legacy cases are recorded under is an (inactive) officer of the LEGACY department.
UPDATE users SET role = 'DEPT_OFFICER', department_code = 'LEGACY', updated_at = updated_at
 WHERE username = 'legacy.import';

-- Two uploads in one submission can no longer share a sequence number.
CREATE UNIQUE INDEX IF NOT EXISTS case_documents_seq ON case_documents(case_id, submission_no, seq);

-- Login attempts, for the per-username rate limit (api.auth).
CREATE TABLE IF NOT EXISTS login_attempts (
    username    TEXT PRIMARY KEY,
    failures    INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    updated_at  TEXT NOT NULL
);
