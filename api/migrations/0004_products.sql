-- 28 Sep 2026: one portal, two products. A case is a pension case or a GP Fund case; the GP Fund
-- module (GP/backend, on :8201) examines the latter and keeps its own case, whose id is kept here.
ALTER TABLE cases ADD COLUMN product TEXT NOT NULL DEFAULT 'PENSION';
ALTER TABLE cases ADD COLUMN gpf_case_id TEXT;
CREATE INDEX IF NOT EXISTS cases_product ON cases(product, status);
