-- 2026-11-08: 音乐对话创作助手。music_chats/music_chat_messages 支撑多轮对话持续迭代歌曲参数，
-- 提案确认后入队生成；music_jobs.chat_id 记录版本链溯源（列由 JobStore._ensure_column 兜底补齐）。
CREATE TABLE IF NOT EXISTS music_chats (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL DEFAULT '新对话',
    anchor_job_id VARCHAR(64) NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    KEY idx_music_chats_owner (owner_user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS music_chat_messages (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    chat_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    role VARCHAR(16) NOT NULL,
    content LONGTEXT NOT NULL,
    proposal_json LONGTEXT NULL,
    job_id VARCHAR(64) NULL,
    created_at VARCHAR(64) NOT NULL,
    KEY idx_music_chat_messages_chat (chat_id, created_at),
    CONSTRAINT fk_music_chat_messages_chat FOREIGN KEY (chat_id)
        REFERENCES music_chats (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
