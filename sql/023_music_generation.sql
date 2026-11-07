-- 2026-11-07: 「音乐」模块。后端代理调用远端 YuE2 Studio（REST /v1/music/jobs）生成歌曲，
-- 成品转存七牛后把 result_url 记在 music_jobs；服务地址与访问密钥存 music_provider_settings。
CREATE TABLE IF NOT EXISTS music_provider_settings (
    id TINYINT NOT NULL PRIMARY KEY,
    base_url VARCHAR(512) NOT NULL DEFAULT 'http://192.168.10.54:8791',
    access_key_encrypted TEXT NULL,
    last_test_status VARCHAR(32) NULL,
    last_test_message TEXT NULL,
    last_test_at VARCHAR(64) NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT chk_music_settings_id CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS music_jobs (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL DEFAULT '',
    style LONGTEXT NOT NULL,
    lyrics LONGTEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'queued',
    progress INT NOT NULL DEFAULT 0,
    params_json LONGTEXT NULL,
    result_url VARCHAR(1024) NULL,
    result_format VARCHAR(16) NULL,
    cover_url VARCHAR(1024) NULL,
    duration_seconds INT NULL,
    remote_job_id VARCHAR(64) NULL,
    remote_song_id VARCHAR(64) NULL,
    error_message TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    completed_at VARCHAR(64) NULL,
    KEY idx_music_jobs_owner_created (owner_user_id, created_at)
);
