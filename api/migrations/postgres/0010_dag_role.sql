-- 0010 for PostgreSQL: the AG_DAG role. PostgreSQL widens a CHECK in place, so no table rebuild;
-- users_role_check is the name PostgreSQL gave the constraint in 0001.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('DEPT_OFFICER', 'AG_UPLOAD', 'AG_REVIEWER', 'AG_DAG', 'ADMIN'));
