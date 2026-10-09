-- 0012 (9 Oct 2026, frontend review F8): a repeated upload is answered with the first answer.
-- A department's browser on slow Wi-Fi retries a filing whose answer never arrived; without this
-- the retry filed the case twice. The key is the client's (Idempotency-Key header, a UUID per
-- attempt), per user; rows are kept for a day.
CREATE TABLE IF NOT EXISTS idempotency_keys (
    user_id       TEXT NOT NULL,
    key           TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    status_code   INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE INDEX IF NOT EXISTS idempotency_keys_created ON idempotency_keys(created_at);
