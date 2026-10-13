-- 0017 (13 Oct 2026): the two indexes the hot paths were missing (audit of 13 Oct, H-08 and M-07).
-- Both are additive. Nothing reads differently because of them; the same rows come back, faster.
--
-- case_runs.run_id is looked up on its own by seven call sites -- the report, the page images,
-- the event stream, the bundle, and the gate that decides whether an approval must carry a
-- written justification -- and had no index at all, so every one of them was a sequential scan
-- over the table. It is NOT made unique here: the table already holds rows that share a run_id,
-- and a unique index would fail to build on the live data. De-duplicating them is a separate
-- decision for the office, since it means choosing which of two recorded runs is the real one.
-- Until then the ORDER BY tiebreakers in the code decide it the same way every time.
CREATE INDEX IF NOT EXISTS case_runs_run ON case_runs(run_id);

-- Every single sign-in runs two queries over audit_log filtered on action and entity_id: the
-- last LOGIN for the account, and whether the administrator reset its password since. The only
-- index was on `at`, so both were sequential scans over a table that is append-only and never
-- pruned -- it degrades for the life of the system.
CREATE INDEX IF NOT EXISTS audit_log_entity ON audit_log(entity_id, action);
