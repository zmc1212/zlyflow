-- 2026-11-12: 「云端视频模型」执行器（executor = cloud_video）。直连可灵 Kling、火山方舟（即梦/Seedance）、
-- MiniMax 海螺三家厂商官方 API；每厂商一行设置（多行表，行缺失时由 storage 层 ensure-row 补齐默认值）。
-- 可灵/方舟为 AccessKey + SecretKey 双密钥（分别存 api_key_encrypted / api_secret_encrypted），海螺仅单 Key。
-- generation_items 复用既有 executor / remote_task_id / remote_status 列，无需变更。
CREATE TABLE IF NOT EXISTS cloud_video_provider_settings (
    provider_key VARCHAR(32) NOT NULL PRIMARY KEY,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    base_url VARCHAR(512) NULL,
    api_key_encrypted TEXT NULL,
    api_secret_encrypted TEXT NULL,
    extra_config_json LONGTEXT NULL,
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
