-- 29 Sep 2026: the GP Fund module's cases move from JSON snapshots (GP/backend/data/cases) into
-- the shared database. The module (GP/backend, gpf.store.SqliteCaseRepository) owns these two
-- tables and creates them itself when it starts against a database that lacks them; the case
-- system reaches the module's cases through its API (api.gpf_bridge), not by reading them here.
--
-- A case's state is the module's own versioned record -- facts, results recomputed from those
-- facts, history, disposals, audit, uploads -- kept whole as JSON (jsonb on PostgreSQL), with the
-- columns the register is asked by alongside it.
CREATE TABLE IF NOT EXISTS gpf_cases (
    id           TEXT PRIMARY KEY,                 -- refundable-11c43ffd, death-scan-e46374b7
    kind         TEXT NOT NULL,                    -- refundable | nonrefundable | final | death | ...
    officer_id   TEXT,                             -- da | ao | dag: the band the case is worked in
    officer_name TEXT,
    version      INTEGER NOT NULL DEFAULT 1,       -- facts version; results are never edited
    returns      INTEGER NOT NULL DEFAULT 0,
    issued       INTEGER NOT NULL DEFAULT 0,
    case_disp    TEXT,                             -- the officer's disposal of the whole case
    from_scans   INTEGER NOT NULL DEFAULT 0,       -- 1: read from a department's scans
    state_json   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS gpf_cases_kind ON gpf_cases(kind, updated_at);
CREATE INDEX IF NOT EXISTS gpf_cases_disp ON gpf_cases(case_disp);

-- Every page the module stores: content-addressed under GPF_DATA_DIR/uploads, never overwritten.
CREATE TABLE IF NOT EXISTS gpf_documents (
    id           TEXT PRIMARY KEY,
    case_id      TEXT NOT NULL,                    -- a gpf_cases id, or the scan batch id before the case exists
    name         TEXT NOT NULL,
    stored_as    TEXT NOT NULL,                    -- relative to GPF_DATA_DIR/uploads
    sha256       TEXT NOT NULL,
    bytes        INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    saved_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS gpf_documents_case ON gpf_documents(case_id, saved_at);
