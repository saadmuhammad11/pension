-- A password someone else set is replaced at first sign-in (5 Oct 2026, docs/DEPLOYMENT.md F1).
--
-- Set when the seed or the administrator gives an account its password and the deployment asks
-- for it (api.settings.force_password_change: on in production); cleared when the officer
-- chooses their own. While it is set, the account may sign in, read who it is and change its
-- password, and nothing else (api.auth).

ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0;
