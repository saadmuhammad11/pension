-- 30 Sep 2026: submission rounds. A case the Accountant General sends back for missing papers
-- comes back as round N+1; the verification of that round analyses only the papers that are new
-- in it and reuses everything already read (pipeline.carryover). These tables keep the record of
-- every round: what the AG asked for, which papers answered it, which pipeline steps ran and
-- which were reused, and what each round found. Nothing in an earlier round is overwritten.
--
-- Additive only: new tables, and new nullable columns on case_documents and case_runs whose
-- NULL/default means exactly what an existing row meant before.

-- One row per round of papers on a case. Round 1 is the first filing.
CREATE TABLE IF NOT EXISTS case_rounds (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES cases(id),
    submission_no   INTEGER NOT NULL,
    opened_at       TEXT NOT NULL,
    opened_by       TEXT,                                 -- users.id; NULL for a backfilled round
    opened_via      TEXT NOT NULL,                        -- CREATE | ADD_DOCS | REPLACE_DOC | BACKFILL
    submitted_at    TEXT,                                 -- the department's FORWARD of this round
    submitted_by    TEXT,
    closed_at       TEXT,                                 -- sent back, approved or rejected
    closed_action   TEXT,
    UNIQUE (case_id, submission_no)
);
CREATE INDEX IF NOT EXISTS case_rounds_case ON case_rounds(case_id, submission_no);

-- A closed round is history: it may not be changed or removed.
CREATE TRIGGER IF NOT EXISTS case_rounds_closed_is_final BEFORE UPDATE ON case_rounds
WHEN OLD.closed_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'a closed submission round is final'); END;
CREATE TRIGGER IF NOT EXISTS case_rounds_no_delete BEFORE DELETE ON case_rounds
BEGIN SELECT RAISE(ABORT, 'case_rounds rows are never deleted'); END;

-- What the AG (or the automatic return) asked the department for, answered by for_submission_no.
-- items_json: [{"kind": "CHECKLIST", "id": "AG-06", "requirement": ..., "status": "MISSING"},
--              {"kind": "DOCUMENT", "label": ..., "pages": [5, 6], "note": ...}]
CREATE TABLE IF NOT EXISTS case_round_requests (
    id                  TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES cases(id),
    from_submission_no  INTEGER NOT NULL,                 -- the round that was sent back
    for_submission_no   INTEGER NOT NULL,                 -- the round that must answer it
    event_id            TEXT,                             -- case_events.id of the RETURN / REQUEST_DOCS / AUTO_RETURN
    action              TEXT NOT NULL,
    items_json          TEXT NOT NULL DEFAULT '[]',
    remark              TEXT NOT NULL DEFAULT '',
    requested_by        TEXT,                             -- users.id; NULL for the system
    requested_by_name   TEXT,
    run_id              TEXT,                             -- the verification the request rested on
    at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS case_round_requests_case ON case_round_requests(case_id, for_submission_no);
CREATE TRIGGER IF NOT EXISTS case_round_requests_no_update BEFORE UPDATE ON case_round_requests
BEGIN SELECT RAISE(ABORT, 'case_round_requests is append-only'); END;
CREATE TRIGGER IF NOT EXISTS case_round_requests_no_delete BEFORE DELETE ON case_round_requests
BEGIN SELECT RAISE(ABORT, 'case_round_requests is append-only'); END;

-- One row per verification run in a round: full or incremental, what was reused, what it found,
-- how each requested item stands, and how long it took. Final once finished_at is set.
CREATE TABLE IF NOT EXISTS case_round_checks (
    id                  TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES cases(id),
    submission_no       INTEGER NOT NULL,
    run_id              TEXT NOT NULL,
    mode                TEXT NOT NULL,                    -- FULL | INCREMENTAL
    base_run_id         TEXT,                             -- the earlier round's run results were reused from
    base_submission_no  INTEGER,
    started_by          TEXT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    state               TEXT NOT NULL,                    -- running | done | failed
    duration_s          REAL,
    documents_json      TEXT NOT NULL DEFAULT '[]',       -- each document: NEW | REPLACEMENT | REUSED, pages
    steps_json          TEXT NOT NULL DEFAULT '{}',       -- per stage: pages/reads run vs reused
    findings_json       TEXT NOT NULL DEFAULT '[]',       -- the findings as they stood when the run finished
    resolution_json     TEXT NOT NULL DEFAULT '[]',       -- each requested item: RESOLVED | STILL_MISSING | ...
    changes_json        TEXT NOT NULL DEFAULT '{}',       -- new / cleared / unchanged findings against the base round
    carried_json        TEXT NOT NULL DEFAULT '{}',       -- officer decisions carried from the base round
    issues_json         TEXT NOT NULL DEFAULT '{}',       -- api.case_runs.open_issues at finish
    error               TEXT
);
CREATE INDEX IF NOT EXISTS case_round_checks_case ON case_round_checks(case_id, submission_no, started_at);
CREATE INDEX IF NOT EXISTS case_round_checks_run ON case_round_checks(run_id);
CREATE TRIGGER IF NOT EXISTS case_round_checks_finished_is_final BEFORE UPDATE ON case_round_checks
WHEN OLD.finished_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'a finished verification record is final'); END;
CREATE TRIGGER IF NOT EXISTS case_round_checks_no_delete BEFORE DELETE ON case_round_checks
BEGIN SELECT RAISE(ABORT, 'case_round_checks rows are never deleted'); END;

-- A document the department replaced stays on file; it is marked superseded and left out of the
-- bundle from that round on. NULL on every existing row: nothing has been replaced before.
ALTER TABLE case_documents ADD COLUMN replaces_document_id TEXT;
ALTER TABLE case_documents ADD COLUMN superseded_in_submission INTEGER;

-- How a run was made. 'FULL' is what every run so far has been.
ALTER TABLE case_runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'FULL';
ALTER TABLE case_runs ADD COLUMN base_run_id TEXT;
