-- Dev-only trace log. Written only when DEBUG_RETAIN_TRACES=true.
CREATE TABLE IF NOT EXISTS traces (
    request_id   TEXT PRIMARY KEY,
    created_at   REAL NOT NULL,
    mode         TEXT NOT NULL,
    destination  TEXT NOT NULL,
    input_text   TEXT NOT NULL,
    response     TEXT NOT NULL,   -- GenerateResponse JSON, trace included
    trace        TEXT NOT NULL    -- sanitised TraceStage list JSON
);
