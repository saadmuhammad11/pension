-- 0015 (9 Oct 2026): signing out ends the one token that signed out, not every session of the account.
--
-- Sign-out used to bump users.token_version, which ended every session of the account; since the
-- senior officers share one login (ag.reviewer, decision S10) one person signing out threw the
-- others out mid-case. Every session token now carries a jti; sign-out records it here until the
-- token's own expiry, and every request refuses a token whose jti (or whose parent's, for the GP
-- Fund frame and media tokens) is listed. Rows past their expiry are swept at each sign-out.
CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti        TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS revoked_tokens_expiry ON revoked_tokens(expires_at);
