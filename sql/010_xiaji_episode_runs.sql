-- 导台2 整集自动生成编排：锁定视频参数，按 Beat 串行草图→精绘→提示词→视频

CREATE TABLE IF NOT EXISTS xiaji_episode_runs (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    episode_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    video_params_json LONGTEXT NOT NULL,
    cursor_json LONGTEXT NULL,
    error TEXT NULL,
    cancel_requested TINYINT NOT NULL DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    KEY idx_xiaji_episode_runs_episode (episode_id, created_at),
    KEY idx_xiaji_episode_runs_project (project_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
