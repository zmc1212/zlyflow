-- 2026-11-04: 首页「精选作品」展示位。管理员发布时冻结作品展示快照，普通用户只读。
CREATE TABLE IF NOT EXISTS ai_featured_works (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    project_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT NULL,
    cover_url VARCHAR(1024) NULL,
    snapshot_json LONGTEXT NOT NULL,
    episode_count INT NOT NULL DEFAULT 0,
    shot_count INT NOT NULL DEFAULT 0,
    sort_order INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'published',
    published_by VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    published_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uniq_featured_project (project_id),
    KEY idx_featured_status_order (status, sort_order, published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
