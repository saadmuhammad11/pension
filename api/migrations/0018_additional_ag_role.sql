-- 0018 (24 Oct 2026, office decision): AG_ADDL, the Additional Accountant General.
--
-- AG_REVIEWER was one role for two offices -- its label read "AG / Additional AG and senior
-- officers (all wings, every tier)" -- so the register could not say which of them had acted
-- on a case. They are separated by NAME and not by power: both act at any tier in any wing and
-- override, exactly as the single role did, and api/workflow.ANY_TIER carries both. What the
-- office gains is an audit that distinguishes the Accountant General from the Additional
-- Accountant General; what it does not gain, deliberately, is a new rank between them.
--
-- SQLite cannot widen a CHECK constraint in place, so the users table is rebuilt as 0010 and
-- 0014 did, with the same columns and its rows copied. api.db.migrate() turns foreign-key
-- enforcement off around a migration, so the drop and the rename do not trip the references
-- from cases, case_documents and case_runs. PostgreSQL widens the constraint in place
-- (migrations/postgres/0018_additional_ag_role.sql).
CREATE TABLE IF NOT EXISTS users_v18 (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('DEPT_OFFICER', 'AG_UPLOAD', 'AG_REVIEWER', 'AG_DAG', 'ADMIN',
                                                 'AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO', 'AG_ADDL')),
    department_code TEXT REFERENCES departments(code),
    active          INTEGER NOT NULL DEFAULT 1,
    token_version   INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    pension_wing    TEXT
);
INSERT OR IGNORE INTO users_v18 (id, username, display_name, password_hash, role, department_code, active,
                                 token_version, created_at, updated_at, must_change_password, pension_wing)
    SELECT id, username, display_name, password_hash, role, department_code, active,
           token_version, created_at, updated_at, must_change_password, pension_wing FROM users;
DROP TABLE users;
ALTER TABLE users_v18 RENAME TO users;
