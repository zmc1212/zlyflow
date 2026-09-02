-- 导台2 项目：内容库、资产库、剧集工坊、风格中心、制作助手同属一个项目
-- 文档/资产上的 project_id 由应用启动时 ensure_column + 回填，避免重复执行 ALTER

CREATE TABLE IF NOT EXISTS xiaji_projects (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    settings_json LONGTEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    KEY idx_xiaji_projects_owner_updated (owner_user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
