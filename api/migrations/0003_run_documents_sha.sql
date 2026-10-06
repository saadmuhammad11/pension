-- 25 Sep 2026: a verification remembers exactly which documents it read, so "run the check on the
-- current documents before submitting" is decided by content, not by timestamps.
ALTER TABLE case_runs ADD COLUMN docs_sha TEXT;
