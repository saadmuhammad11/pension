-- 0011: per-stage and per-model-call timing of every run, durable (perf/pipeline, 7 Oct 2026).
-- Written by pipeline.timing from the run's own thread and the pool threads it fans out to; read
-- by the benchmark and by anyone asking "where did the time go" after a restart.
CREATE TABLE IF NOT EXISTS run_timings (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT NOT NULL,               -- artifacts/run-<run_id>/ (or a GP Fund reading job id)
    kind        TEXT NOT NULL,               -- stage | model | queue
    stage       TEXT NOT NULL,               -- identify, verify, extract, assertions, signatures, determine, report, ...
    name        TEXT,                        -- a stage's own name; a model call's schema / role (vision, ocr)
    page        INTEGER,                     -- the page a model call read, where known
    started_at  TEXT NOT NULL,               -- ISO, local clock
    ended_at    TEXT NOT NULL,
    duration_s  REAL NOT NULL,               -- wall time of the stage, or the model call's round trip
    queue_s     REAL,                        -- time spent waiting before it started: a run for its slot, a page for a pool worker
    pages       INTEGER,                     -- pages the stage handled
    status      TEXT NOT NULL DEFAULT 'ok',  -- ok | error
    detail_json TEXT                         -- tokens, endpoint, error text, ...
);
CREATE INDEX IF NOT EXISTS run_timings_run ON run_timings(run_id, started_at);
