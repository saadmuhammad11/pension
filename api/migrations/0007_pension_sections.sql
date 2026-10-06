-- 29 Sep 2026: the AG office's Pension section (Pension-I .. Pension-V) that works each
-- department's cases, from api.departments.PENSION_SECTIONS; the seed writes it. NULL for the
-- legacy bucket and retired codes. The AG Review sidebar groups departments by it.
ALTER TABLE departments ADD COLUMN pension_section TEXT;
