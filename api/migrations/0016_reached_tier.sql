-- 0016 (12 Oct 2026): a pension case is shown to the Assistant AO only once the Senior Auditor has
-- forwarded it, and to the AO only once the Assistant AO has (api.workflow.TIER_RANK). Before this,
-- every tier officer saw every case of their wing from the moment it was filed.
--
-- reached_tier is the highest tier the case's current filing has been sent to (SENIOR_AUDITOR |
-- ASSISTANT_AO | AO; NULL reads as the Senior Auditor's). The department's filing resets it; a
-- forward or an override raises it; nothing lowers it, so an officer keeps sight of a case they
-- passed on or returned.
--
-- Existing cases: the tier that holds one now, raised to the highest tier any move since the
-- department's last filing sent it to. A decision (APPROVE / REJECT) is the AO's, so a decided case
-- has reached the AO. The same SQL runs on SQLite and PostgreSQL.
ALTER TABLE cases ADD COLUMN reached_tier TEXT;

UPDATE cases SET reached_tier = holder_tier WHERE holder_tier IS NOT NULL;

UPDATE cases SET reached_tier = 'AO'
 WHERE EXISTS (
    SELECT 1 FROM case_events e
     WHERE e.case_id = cases.id
       AND e.seq > COALESCE((SELECT MAX(f.seq) FROM case_events f WHERE f.case_id = cases.id AND f.action = 'FORWARD'), 0)
       AND (e.action IN ('APPROVE', 'REJECT')
            OR e.payload_json LIKE '%"to_tier": "AO"%'
            OR e.payload_json LIKE '%"holder_tier": "AO"%'));

UPDATE cases SET reached_tier = 'ASSISTANT_AO'
 WHERE COALESCE(reached_tier, 'SENIOR_AUDITOR') = 'SENIOR_AUDITOR'
   AND EXISTS (
    SELECT 1 FROM case_events e
     WHERE e.case_id = cases.id
       AND e.seq > COALESCE((SELECT MAX(f.seq) FROM case_events f WHERE f.case_id = cases.id AND f.action = 'FORWARD'), 0)
       AND (e.payload_json LIKE '%"to_tier": "ASSISTANT_AO"%'
            OR e.payload_json LIKE '%"holder_tier": "ASSISTANT_AO"%'));
