-- 0001 for PostgreSQL (9 Oct 2026): the schema of ../0001_init.sql in the engine's own forms.
--
-- Same tables, same columns, same meanings: TEXT primary keys (UUID hex), ISO-8601 TEXT
-- timestamps, INTEGER 0/1 flags, CHECK constraints for the enums. What differs is the mechanics:
-- the append-only rule is a trigger function, and the triggers are ENABLE ALWAYS so that a test
-- running with referential checks off (session_replication_role = replica) still meets them. The
-- error code is integrity_constraint_violation, which the driver raises as IntegrityError --
-- what sqlite raised for RAISE(ABORT), so the same except clauses hold on both engines.

CREATE OR REPLACE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '%', TG_ARGV[0] USING ERRCODE = 'integrity_constraint_violation';
END $$;

CREATE TABLE IF NOT EXISTS departments (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    digital     INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('DEPT_OFFICER', 'AG_UPLOAD', 'AG_REVIEWER', 'ADMIN')),
    department_code TEXT REFERENCES departments(code),
    active          INTEGER NOT NULL DEFAULT 1,
    -- Bumped on disable and on password reset; a token carrying an older value is refused.
    token_version   INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id              TEXT PRIMARY KEY,
    case_no         TEXT NOT NULL UNIQUE,                 -- PC-2026-000042
    department_code TEXT NOT NULL REFERENCES departments(code),
    created_via     TEXT NOT NULL CHECK (created_via IN ('DEPARTMENT', 'AG_UPLOAD')),
    created_by      TEXT NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL CHECK (status IN (
                        'DRAFT', 'AI_CHECKING', 'AI_FAILED', 'AI_CHECKED', 'FORWARDED',
                        'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'RETURNED', 'DOCS_REQUESTED')),
    claimant_name   TEXT,
    variant         TEXT,
    intake_json     TEXT NOT NULL DEFAULT '{}',           -- annual_pay etc., passed to the pipeline
    submission_no   INTEGER NOT NULL DEFAULT 1,
    current_run_id  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cases_department_status ON cases(department_code, status);
CREATE INDEX IF NOT EXISTS cases_created_via ON cases(created_via);

CREATE TABLE IF NOT EXISTS case_documents (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    submission_no   INTEGER NOT NULL,
    seq             INTEGER NOT NULL,
    filename        TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    bytes           BIGINT NOT NULL,
    stored_path     TEXT NOT NULL,
    uploaded_by     TEXT NOT NULL REFERENCES users(id),
    uploaded_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS case_documents_case ON case_documents(case_id, submission_no, seq);

CREATE TABLE IF NOT EXISTS case_runs (
    id                  TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES cases(id),
    run_id              TEXT NOT NULL,                    -- artifacts/run-<run_id>/
    submission_no       INTEGER NOT NULL,
    started_by          TEXT NOT NULL REFERENCES users(id),
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    state               TEXT NOT NULL,                    -- queued | running | done | failed
    verdict             TEXT,
    high_flags          INTEGER,
    blocking_flags_json TEXT,
    checklist_result    TEXT,
    error               TEXT,
    auto_forward        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS case_runs_case ON case_runs(case_id, started_at);
CREATE INDEX IF NOT EXISTS case_runs_state ON case_runs(state);

CREATE TABLE IF NOT EXISTS case_events (
    id               TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL REFERENCES cases(id),
    seq              INTEGER NOT NULL,
    action           TEXT NOT NULL,
    from_status      TEXT,
    to_status        TEXT NOT NULL,
    actor_id         TEXT,
    actor_name       TEXT,
    actor_role       TEXT,
    actor_department TEXT,
    remark           TEXT NOT NULL DEFAULT '',
    payload_json     TEXT NOT NULL DEFAULT '{}',
    run_id           TEXT,
    at               TEXT NOT NULL,
    UNIQUE (case_id, seq)
);
CREATE OR REPLACE TRIGGER case_events_no_update BEFORE UPDATE ON case_events
    FOR EACH ROW EXECUTE FUNCTION refuse_change('case_events is append-only');
CREATE OR REPLACE TRIGGER case_events_no_delete BEFORE DELETE ON case_events
    FOR EACH ROW EXECUTE FUNCTION refuse_change('case_events is append-only');
ALTER TABLE case_events ENABLE ALWAYS TRIGGER case_events_no_update;
ALTER TABLE case_events ENABLE ALWAYS TRIGGER case_events_no_delete;

CREATE TABLE IF NOT EXISTS audit_log (
    id          TEXT PRIMARY KEY,
    at          TEXT NOT NULL,
    actor_id    TEXT,
    actor_name  TEXT,
    actor_role  TEXT,
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    before_json TEXT,
    after_json  TEXT,
    reason      TEXT NOT NULL DEFAULT '',
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS audit_log_at ON audit_log(at);
CREATE OR REPLACE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION refuse_change('audit_log is append-only');
CREATE OR REPLACE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION refuse_change('audit_log is append-only');
ALTER TABLE audit_log ENABLE ALWAYS TRIGGER audit_log_no_update;
ALTER TABLE audit_log ENABLE ALWAYS TRIGGER audit_log_no_delete;
