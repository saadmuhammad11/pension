-- 29 Sep 2026: the case type on the case. A department declares it at intake (mandatory for
-- a pension case); the AI's own reading of the papers is kept beside it after each check.
--   case_type          the type the case is worked as: declared, corrected by the AG, or -- for
--                      cases filed before this -- what the AI detected
--   case_type_source   DECLARED | CORRECTED | DETECTED
--   detected_case_type what the last verification read off the papers, with its confidence
-- The list of types is config/case_types.json, shared with the portal; validated in Python.
ALTER TABLE cases ADD COLUMN case_type TEXT;
ALTER TABLE cases ADD COLUMN case_type_source TEXT;
ALTER TABLE cases ADD COLUMN detected_case_type TEXT;
ALTER TABLE cases ADD COLUMN detected_case_type_confidence REAL;
CREATE INDEX IF NOT EXISTS cases_case_type ON cases(product, case_type);
