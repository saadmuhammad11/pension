-- 0013 (9 Oct 2026, scope change C1): one master store of signing authorities, with specimen
-- signatures, for pension and GP Fund.
--
-- Until now pension kept one specimen authority in rules/specimens/register.json and GP Fund a
-- provisional delegation-of-authority register with no specimens (GP/backend/gpf/doa.py). Both
-- are imported here (api.signatories import); the files stay as the fallback for a pipeline
-- that runs without a database. Rows are never deleted: an authority is closed with an end date,
-- and every change is an audit_log row. Portable DDL: TEXT, INTEGER 0/1, ISO dates as TEXT.
CREATE TABLE IF NOT EXISTS signing_authorities (
    id                      TEXT PRIMARY KEY,
    product_scope           TEXT NOT NULL DEFAULT 'BOTH',       -- PENSION | GPF | BOTH
    department_code         TEXT,                               -- api/departments code where it maps
    department_name         TEXT NOT NULL,
    department_aliases_json TEXT NOT NULL DEFAULT '[]',
    post                    TEXT NOT NULL,
    post_aliases_json       TEXT NOT NULL DEFAULT '[]',
    officer_name            TEXT,
    scope                   TEXT,                               -- what the authority may sanction
    effective_from          TEXT NOT NULL,
    effective_to            TEXT,
    letter_no               TEXT,
    letter_date             TEXT,
    letter_path             TEXT,                               -- the authorising letter's scan
    provisional             INTEGER NOT NULL DEFAULT 0,         -- 1: GP Fund's provisional register, not yet the office's list
    source                  TEXT NOT NULL,                      -- PENSION_REGISTER | GPF_PROVISIONAL | ADMIN
    gpf_authority_id        TEXT,
    gpf_signatory_id        TEXT,
    may_sign_for            INTEGER NOT NULL DEFAULT 0,
    stamp_text              TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    closed_at               TEXT,
    closed_by               TEXT
);
CREATE INDEX IF NOT EXISTS signing_authorities_dept ON signing_authorities(department_code, post);
CREATE INDEX IF NOT EXISTS signing_authorities_scope ON signing_authorities(product_scope, effective_from);

CREATE TABLE IF NOT EXISTS signatory_specimens (
    id            TEXT PRIMARY KEY,
    authority_id  TEXT NOT NULL REFERENCES signing_authorities(id),
    stored_path   TEXT NOT NULL,
    sha256        TEXT,
    bytes         INTEGER,
    uploaded_by   TEXT,
    uploaded_at   TEXT NOT NULL,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS signatory_specimens_authority ON signatory_specimens(authority_id, uploaded_at);
