-- 2026-10-20: standalone script diagnosis, additive and idempotent.
CREATE TABLE IF NOT EXISTS ai_script_diagnoses (
    id VARCHAR(64) PRIMARY KEY,
    owner_id VARCHAR(64) NOT NULL,
    client_request_id VARCHAR(96) NOT NULL,
    title VARCHAR(255) NOT NULL,
    project_id VARCHAR(96),
    document_id VARCHAR(96),
    status VARCHAR(32) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    model VARCHAR(255) NOT NULL DEFAULT '',
    input_json LONGTEXT NOT NULL,
    report_json LONGTEXT,
    error TEXT,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uq_diagnosis_request (owner_id, client_request_id),
    KEY idx_diagnosis_owner_updated (owner_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
