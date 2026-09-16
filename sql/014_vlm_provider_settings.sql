-- 独立视觉大模型配置，与 llm_provider_settings 分离：文本走 LLM，看图走 VLM。
-- 索引必须内联；禁止 ALTER。schema 会在每次 MySQL 启动重放 CREATE IF NOT EXISTS。

CREATE TABLE IF NOT EXISTS vlm_provider_settings (
    id TINYINT NOT NULL PRIMARY KEY,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    base_url VARCHAR(512) NOT NULL DEFAULT 'https://open.bigmodel.cn/api/paas/v4',
    api_key_encrypted TEXT NULL,
    model VARCHAR(255) NOT NULL DEFAULT 'glm-4v-flash',
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT chk_vlm_settings_id CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
