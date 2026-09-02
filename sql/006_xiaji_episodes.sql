-- 导台2 剧集工坊：剧集规划、资产绑定、Beat 脚本与镜头草图

CREATE TABLE IF NOT EXISTS xiaji_episodes (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL,
    owner_user_id VARCHAR(64) NOT NULL,
    number INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    source_document_id VARCHAR(64) NULL,
    content_summary TEXT NULL,
    main_conflict TEXT NULL,
    cliffhanger TEXT NULL,
    key_events_json LONGTEXT NOT NULL,
    original_lines_json LONGTEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    error TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uk_xiaji_episodes_project_number (project_id, number),
    KEY idx_xiaji_episodes_project (project_id, number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS xiaji_episode_links (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    episode_id VARCHAR(64) NOT NULL,
    asset_id VARCHAR(64) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    first_seen_line INTEGER NOT NULL DEFAULT 0,
    KEY idx_xiaji_episode_links_episode (episode_id, kind),
    CONSTRAINT fk_xiaji_episode_links_episode FOREIGN KEY (episode_id) REFERENCES xiaji_episodes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS xiaji_beats (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    episode_id VARCHAR(64) NOT NULL,
    sequence INTEGER NOT NULL,
    beat_kind VARCHAR(32) NOT NULL,
    heading VARCHAR(255) NULL,
    speaker VARCHAR(128) NULL,
    dialogue TEXT NULL,
    action TEXT NULL,
    character_ids_json LONGTEXT NOT NULL,
    scene_id VARCHAR(64) NULL,
    prop_ids_json LONGTEXT NOT NULL,
    sketch_job_id VARCHAR(64) NULL,
    sketch_url TEXT NULL,
    sketch_prompt TEXT NULL,
    sketch_model VARCHAR(255) NULL,
    status VARCHAR(32) NOT NULL,
    error TEXT NULL,
    UNIQUE KEY uk_xiaji_beats_episode_seq (episode_id, sequence),
    KEY idx_xiaji_beats_episode (episode_id, sequence),
    CONSTRAINT fk_xiaji_beats_episode FOREIGN KEY (episode_id) REFERENCES xiaji_episodes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
