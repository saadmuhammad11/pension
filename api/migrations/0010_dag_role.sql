-- 0010: the Deputy Accountant General (Pension) role, AG_DAG (business decisions C1, G1, G6 of
-- 7 Oct 2026). SQLite cannot widen a CHECK constraint in place, so the users table is rebuilt
-- with the same columns (0001 plus must_change_password from 0009) and its rows copied over.
-- api.db.migrate() turns foreign-key enforcement off around a migration, so the drop and the
-- rename below do not trip the references from cases, case_documents and case_runs.
CREATE TABLE IF NOT EXISTS users_v10 (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('DEPT_OFFICER', 'AG_UPLOAD', 'AG_REVIEWER', 'AG_DAG', 'ADMIN')),
    department_code TEXT REFERENCES departments(code),
    active          INTEGER NOT NULL DEFAULT 1,
    token_version   INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO users_v10 (id, username, display_name, password_hash, role, department_code, active,
                                 token_version, created_at, updated_at, must_change_password)
    SELECT id, username, display_name, password_hash, role, department_code, active,
           token_version, created_at, updated_at, must_change_password FROM users;
DROP TABLE users;
ALTER TABLE users_v10 RENAME TO users;
