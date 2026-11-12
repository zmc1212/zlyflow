-- 邮箱自助找回密码：
--   1) mail_provider_settings —— 管理设置里的 SMTP 发件服务（密码密文存储）。
--   2) password_reset_codes   —— 一次性重置验证码，哈希 + 有效期 + 尝试次数。
-- users.email 列由 AuthStore.initialize() 通过 ensure_column 走运行时兜底，避免重复 ALTER。

CREATE TABLE IF NOT EXISTS mail_provider_settings (
    id TINYINT NOT NULL PRIMARY KEY,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    host VARCHAR(255) NOT NULL DEFAULT '',
    port INTEGER NOT NULL DEFAULT 465,
    security VARCHAR(16) NOT NULL DEFAULT 'ssl',
    username VARCHAR(255) NOT NULL DEFAULT '',
    password_encrypted TEXT NULL,
    from_address VARCHAR(255) NOT NULL DEFAULT '',
    from_name VARCHAR(120) NOT NULL DEFAULT 'ZLY AI Studio',
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT chk_mail_settings_id CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS password_reset_codes (
    user_id VARCHAR(64) NOT NULL PRIMARY KEY,
    code_hash VARCHAR(512) NOT NULL,
    expires_at VARCHAR(64) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_reset_codes_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
