-- LLM/VLM 快速服务预设独立配置；运行时仍由各自 settings 单例表指向当前生效预设。

CREATE TABLE IF NOT EXISTS llm_provider_profiles (
    profile_id VARCHAR(64) NOT NULL PRIMARY KEY,
    base_url VARCHAR(512) NOT NULL,
    api_key_encrypted TEXT NULL,
    model VARCHAR(255) NOT NULL,
    reasoning_effort VARCHAR(16) NOT NULL DEFAULT 'low',
    vision_capability VARCHAR(16) NOT NULL DEFAULT 'unknown',
    vision_capability_source VARCHAR(32) NULL,
    vision_capability_checked_at VARCHAR(64) NULL,
    vision_capability_message TEXT NULL,
    vision_capability_fingerprint VARCHAR(64) NULL,
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS vlm_provider_profiles (
    profile_id VARCHAR(64) NOT NULL PRIMARY KEY,
    use_llm_credentials TINYINT(1) NOT NULL DEFAULT 0,
    base_url VARCHAR(512) NOT NULL,
    api_key_encrypted TEXT NULL,
    model VARCHAR(255) NOT NULL,
    vision_capability VARCHAR(16) NOT NULL DEFAULT 'unknown',
    vision_capability_source VARCHAR(32) NULL,
    vision_capability_checked_at VARCHAR(64) NULL,
    vision_capability_message TEXT NULL,
    vision_capability_fingerprint VARCHAR(64) NULL,
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
