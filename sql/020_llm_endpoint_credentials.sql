-- LLM 供应商端点凭据档案：按 Base URL 保存每家服务的加密 API Key 与最近使用模型，
-- 供管理设置在不同供应商之间切换时自动带出，避免每次切换都重新粘贴 Key。
-- Key 使用与 llm_provider_settings.api_key_encrypted 相同的 Fernet 主密钥加密。
-- 索引必须内联；禁止 ALTER。schema 会在每次 MySQL 启动重放 CREATE IF NOT EXISTS。

CREATE TABLE IF NOT EXISTS llm_endpoint_credentials (
    base_url VARCHAR(512) NOT NULL PRIMARY KEY,
    api_key_encrypted TEXT NOT NULL,
    model VARCHAR(255) NOT NULL DEFAULT '',
    updated_at VARCHAR(64) NOT NULL
);
