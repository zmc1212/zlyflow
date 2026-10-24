-- 2026-10-19: additive director assistant storage. No existing content is rewritten.
CREATE TABLE IF NOT EXISTS ai_assistant_records (
    id VARCHAR(96) PRIMARY KEY,
    owner_id VARCHAR(64) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    parent_id VARCHAR(96) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'ready',
    version INTEGER NOT NULL DEFAULT 1,
    payload_json LONGTEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    KEY idx_assistant_owner_kind (owner_id, kind, updated_at),
    KEY idx_assistant_parent (parent_id, kind, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS ai_assistant_events (
    run_id VARCHAR(96) NOT NULL,
    seq INTEGER NOT NULL,
    event_json LONGTEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (run_id, seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS ai_assistant_project_locks (
    project_id VARCHAR(64) PRIMARY KEY,
    updated_at VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
