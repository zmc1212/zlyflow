-- ZLY AI Video Studio MySQL schema (database: ai-media)
-- Execute against the remote instance documented in docs/存储配置.md.

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    username VARCHAR(128) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(512) NOT NULL,
    role VARCHAR(32) NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    must_change_password TINYINT(1) NOT NULL DEFAULT 1,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    last_login_at VARCHAR(64) NULL,
    UNIQUE KEY uk_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sessions (
    token_hash VARCHAR(64) NOT NULL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    expires_at VARCHAR(64) NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    KEY idx_sessions_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER NOT NULL PRIMARY KEY AUTO_INCREMENT,
    actor_user_id VARCHAR(64) NULL,
    action VARCHAR(128) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_id VARCHAR(64) NULL,
    detail TEXT NULL,
    ip_address VARCHAR(64) NULL,
    created_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_audit_actor FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
    KEY idx_audit_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS jobs (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NULL,
    mode VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    stage VARCHAR(255) NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    prompt LONGTEXT NOT NULL,
    negative_prompt LONGTEXT NOT NULL,
    image_size VARCHAR(64) NULL,
    options_json LONGTEXT NOT NULL,
    submitted_options_json LONGTEXT NOT NULL,
    options_submitted TINYINT(1) NOT NULL DEFAULT 0,
    comfy_prompt_id VARCHAR(128) NULL,
    comfy_client_id VARCHAR(128) NULL,
    comfy_phase VARCHAR(64) NULL,
    references_json LONGTEXT NOT NULL,
    outputs_json LONGTEXT NOT NULL,
    error TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    media_type VARCHAR(32) NOT NULL DEFAULT 'video',
    title VARCHAR(255) NULL,
    pinned TINYINT(1) NOT NULL DEFAULT 0,
    last_round_id VARCHAR(96) NULL,
    source_job_id VARCHAR(64) NULL,
    source_generation_item_id VARCHAR(128) NULL,
    source_output_index INTEGER NULL,
    legacy_read_only TINYINT(1) NOT NULL DEFAULT 0,
    finished_at VARCHAR(64) NULL,
    execution_elapsed_ms INTEGER NULL,
    KEY idx_jobs_owner_created (owner_user_id, created_at),
    KEY idx_jobs_pinned_created (pinned, created_at),
    KEY idx_jobs_owner_pinned_created (owner_user_id, pinned, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS schema_migrations (
    name VARCHAR(128) NOT NULL PRIMARY KEY,
    applied_at VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS job_rounds (
    id VARCHAR(96) NOT NULL PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL,
    sequence INTEGER NOT NULL,
    mode VARCHAR(128) NOT NULL,
    media_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    stage VARCHAR(255) NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    prompt LONGTEXT NOT NULL,
    negative_prompt LONGTEXT NOT NULL,
    image_size VARCHAR(64) NULL,
    options_json LONGTEXT NOT NULL,
    submitted_options_json LONGTEXT NOT NULL,
    options_submitted TINYINT(1) NOT NULL DEFAULT 0,
    references_json LONGTEXT NOT NULL,
    error TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    finished_at VARCHAR(64) NULL,
    execution_elapsed_ms INTEGER NULL,
    UNIQUE KEY uk_rounds_job_sequence (job_id, sequence),
    CONSTRAINT fk_rounds_job FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    KEY idx_rounds_job_sequence (job_id, sequence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS generation_items (
    id VARCHAR(128) NOT NULL PRIMARY KEY,
    round_id VARCHAR(96) NOT NULL,
    item_index INTEGER NOT NULL,
    executor VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    stage VARCHAR(255) NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    remote_task_id VARCHAR(128) NULL,
    remote_status VARCHAR(64) NULL,
    comfy_prompt_id VARCHAR(128) NULL,
    comfy_client_id VARCHAR(128) NULL,
    comfy_phase VARCHAR(64) NULL,
    cancel_requested TINYINT(1) NOT NULL DEFAULT 0,
    outputs_json LONGTEXT NOT NULL,
    error TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    finished_at VARCHAR(64) NULL,
    execution_elapsed_ms INTEGER NULL,
    UNIQUE KEY uk_items_round_index (round_id, item_index),
    CONSTRAINT fk_items_round FOREIGN KEY (round_id) REFERENCES job_rounds(id) ON DELETE CASCADE,
    KEY idx_items_round_index (round_id, item_index),
    KEY idx_items_remote_task (remote_task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS grs_provider_settings (
    id TINYINT NOT NULL PRIMARY KEY,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    base_url VARCHAR(512) NOT NULL DEFAULT 'https://grsai.dakka.com.cn',
    api_key_encrypted TEXT NULL,
    gpt_image_2_enabled TINYINT(1) NOT NULL DEFAULT 1,
    gpt_image_2_vip_enabled TINYINT(1) NOT NULL DEFAULT 1,
    models TEXT NOT NULL,
    vip_models TEXT NOT NULL,
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    last_balance DOUBLE NULL,
    last_balance_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT chk_grs_settings_id CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS qiniu_provider_settings (
    id TINYINT NOT NULL PRIMARY KEY,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    access_key_encrypted TEXT NULL,
    secret_key_encrypted TEXT NULL,
    bucket VARCHAR(255) NOT NULL DEFAULT '',
    region VARCHAR(32) NOT NULL DEFAULT 'z0',
    domain VARCHAR(512) NOT NULL DEFAULT '',
    object_prefix VARCHAR(255) NOT NULL DEFAULT 'zly-ai-video-studio/',
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT chk_qiniu_settings_id CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS llm_provider_settings (
    id TINYINT NOT NULL PRIMARY KEY,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    base_url VARCHAR(512) NOT NULL DEFAULT 'https://api-inference.modelscope.cn/v1',
    api_key_encrypted TEXT NULL,
    model VARCHAR(255) NOT NULL DEFAULT 'Qwen/Qwen2.5-Coder-32B-Instruct',
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT chk_llm_settings_id CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS comfy_provider_settings (
    id TINYINT NOT NULL PRIMARY KEY,
    base_url VARCHAR(512) NOT NULL DEFAULT 'http://127.0.0.1:8188',
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT chk_comfy_settings_id CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tts_provider_settings (
    id TINYINT NOT NULL PRIMARY KEY,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    use_llm_credentials TINYINT(1) NOT NULL DEFAULT 1,
    base_url VARCHAR(512) NOT NULL DEFAULT '',
    api_key_encrypted TEXT NULL,
    model VARCHAR(255) NOT NULL DEFAULT 'tts-1',
    voice VARCHAR(64) NOT NULL DEFAULT 'alloy',
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT chk_tts_settings_id CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS director_projects (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    source_script LONGTEXT NOT NULL,
    style_vibe VARCHAR(255) NULL,
    requested_shot_count INTEGER NULL,
    payload_json LONGTEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    content_revision INTEGER NOT NULL DEFAULT 1,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    KEY idx_director_projects_owner_updated (owner_user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS director_library_assets (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    prompt_text LONGTEXT NOT NULL,
    gender VARCHAR(32) NOT NULL DEFAULT '',
    image_url TEXT NULL,
    image_job_id VARCHAR(64) NULL,
    image_path TEXT NULL,
    source_project_id VARCHAR(64) NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    KEY idx_director_library_assets_owner_kind (owner_user_id, kind, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS director_operations (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL,
    owner_user_id VARCHAR(64) NOT NULL,
    kind VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    request_json LONGTEXT NOT NULL,
    result_json LONGTEXT NOT NULL,
    error TEXT NULL,
    cancel_requested TINYINT(1) NOT NULL DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_director_operations_project FOREIGN KEY (project_id) REFERENCES director_projects(id) ON DELETE CASCADE,
    KEY idx_director_operations_project_updated (project_id, updated_at),
    KEY idx_director_operations_owner_status (owner_user_id, status, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS grs_image_models (
    workflow_id VARCHAR(128) NOT NULL PRIMARY KEY,
    provider_model VARCHAR(128) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    profile VARCHAR(64) NOT NULL,
    resolutions_json TEXT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_default TINYINT(1) NOT NULL DEFAULT 0,
    builtin TINYINT(1) NOT NULL DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uk_grs_image_models_provider (provider_model)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
