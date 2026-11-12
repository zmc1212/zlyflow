-- 2026-11-10: 音乐页「精选音乐」。管理员把生成成功的歌曲冻结成只读快照，所有登录成员可见。
CREATE TABLE IF NOT EXISTS ai_featured_music (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    job_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    owner_user_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT NULL,
    style TEXT NOT NULL,
    lyrics MEDIUMTEXT NOT NULL,
    result_url VARCHAR(1024) NOT NULL,
    cover_url VARCHAR(1024) NULL,
    duration_seconds INT NULL,
    result_format VARCHAR(16) NULL,
    sort_order INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'published',
    published_by VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    published_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uniq_featured_music_job (job_id),
    KEY idx_featured_music_status_order (status, sort_order, published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
