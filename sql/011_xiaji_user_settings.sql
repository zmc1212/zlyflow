-- 导台2 当前用户默认画风，供新项目和内容库预填

CREATE TABLE IF NOT EXISTS xiaji_user_settings (
    owner_user_id VARCHAR(64) NOT NULL PRIMARY KEY,
    art_style_id VARCHAR(64) NOT NULL DEFAULT '',
    updated_at VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
