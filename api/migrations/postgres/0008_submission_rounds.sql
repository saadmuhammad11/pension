-- 0008 for PostgreSQL: ../0008_submission_rounds.sql with the rules on history as trigger
-- functions (refuse_change, from 0001) and the conditional ones as WHEN clauses.

CREATE TABLE IF NOT EXISTS case_rounds (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    submission_no   INTEGER NOT NULL,
    opened_at       TEXT NOT NULL,
    opened_by       TEXT,
    opened_via      TEXT NOT NULL,                        -- CREATE | ADD_DOCS | REPLACE_DOC | BACKFILL
    submitted_at    TEXT,
    submitted_by    TEXT,
    closed_at       TEXT,
    closed_action   TEXT,
    UNIQUE (case_id, submission_no)
);
CREATE INDEX IF NOT EXISTS case_rounds_case ON case_rounds(case_id, submission_no);
CREATE OR REPLACE TRIGGER case_rounds_closed_is_final BEFORE UPDATE ON case_rounds
    FOR EACH ROW WHEN (OLD.closed_at IS NOT NULL)
    EXECUTE FUNCTION refuse_change('a closed submission round is final');
CREATE OR REPLACE TRIGGER case_rounds_no_delete BEFORE DELETE ON case_rounds
    FOR EACH ROW EXECUTE FUNCTION refuse_change('case_rounds rows are never deleted');
ALTER TABLE case_rounds ENABLE ALWAYS TRIGGER case_rounds_closed_is_final;
ALTER TABLE case_rounds ENABLE ALWAYS TRIGGER case_rounds_no_delete;

CREATE TABLE IF NOT EXISTS case_round_requests (
    id                  TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES cases(id),
    from_submission_no  INTEGER NOT NULL,
    for_submission_no   INTEGER NOT NULL,
    event_id            TEXT,
    action              TEXT NOT NULL,
    items_json          TEXT NOT NULL DEFAULT '[]',
    remark              TEXT NOT NULL DEFAULT '',
    requested_by        TEXT,
    requested_by_name   TEXT,
    run_id              TEXT,
    at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS case_round_requests_case ON case_round_requests(case_id, for_submission_no);
CREATE OR REPLACE TRIGGER case_round_requests_no_update BEFORE UPDATE ON case_round_requests
    FOR EACH ROW EXECUTE FUNCTION refuse_change('case_round_requests is append-only');
CREATE OR REPLACE TRIGGER case_round_requests_no_delete BEFORE DELETE ON case_round_requests
    FOR EACH ROW EXECUTE FUNCTION refuse_change('case_round_requests is append-only');
ALTER TABLE case_round_requests ENABLE ALWAYS TRIGGER case_round_requests_no_update;
ALTER TABLE case_round_requests ENABLE ALWAYS TRIGGER case_round_requests_no_delete;

CREATE TABLE IF NOT EXISTS case_round_checks (
    id                  TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES cases(id),
    submission_no       INTEGER NOT NULL,
    run_id              TEXT NOT NULL,
    mode                TEXT NOT NULL,                    -- FULL | INCREMENTAL
    base_run_id         TEXT,
    base_submission_no  INTEGER,
    started_by          TEXT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    state               TEXT NOT NULL,                    -- running | done | failed
    duration_s          DOUBLE PRECISION,
    documents_json      TEXT NOT NULL DEFAULT '[]',
    steps_json          TEXT NOT NULL DEFAULT '{}',
    findings_json       TEXT NOT NULL DEFAULT '[]',
    resolution_json     TEXT NOT NULL DEFAULT '[]',
    changes_json        TEXT NOT NULL DEFAULT '{}',
    carried_json        TEXT NOT NULL DEFAULT '{}',
    issues_json         TEXT NOT NULL DEFAULT '{}',
    error               TEXT
);
CREATE INDEX IF NOT EXISTS case_round_checks_case ON case_round_checks(case_id, submission_no, started_at);
CREATE INDEX IF NOT EXISTS case_round_checks_run ON case_round_checks(run_id);
CREATE OR REPLACE TRIGGER case_round_checks_finished_is_final BEFORE UPDATE ON case_round_checks
    FOR EACH ROW WHEN (OLD.finished_at IS NOT NULL)
    EXECUTE FUNCTION refuse_change('a finished verification record is final');
CREATE OR REPLACE TRIGGER case_round_checks_no_delete BEFORE DELETE ON case_round_checks
    FOR EACH ROW EXECUTE FUNCTION refuse_change('case_round_checks rows are never deleted');
ALTER TABLE case_round_checks ENABLE ALWAYS TRIGGER case_round_checks_finished_is_final;
ALTER TABLE case_round_checks ENABLE ALWAYS TRIGGER case_round_checks_no_delete;

ALTER TABLE case_documents ADD COLUMN IF NOT EXISTS replaces_document_id TEXT;
ALTER TABLE case_documents ADD COLUMN IF NOT EXISTS superseded_in_submission INTEGER;
ALTER TABLE case_runs ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'FULL';
ALTER TABLE case_runs ADD COLUMN IF NOT EXISTS base_run_id TEXT;
