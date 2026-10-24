-- 0018 for PostgreSQL: AG_ADDL, the Additional Accountant General. PostgreSQL widens a CHECK
-- in place, so no table rebuild; users_role_check is the name the constraint has carried since
-- 0001. See the SQLite file of the same name for why the role exists and what it may do.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('DEPT_OFFICER', 'AG_UPLOAD', 'AG_REVIEWER', 'AG_DAG', 'ADMIN',
                    'AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO', 'AG_ADDL'));
