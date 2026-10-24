-- 2026-10-21: infinite canvas projects, current JSON draft and version history.
CREATE TABLE IF NOT EXISTS canvas_projects (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    title VARCHAR(160) NOT NULL,
    tags_json VARCHAR(512) NOT NULL DEFAULT '[]',
    is_favorite TINYINT(1) NOT NULL DEFAULT 0,
    deleted_at VARCHAR(64) NULL,
    preview_json TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    KEY idx_canvas_projects_owner_updated (owner_user_id, updated_at),
    KEY idx_canvas_projects_owner_deleted (owner_user_id, deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS canvas_drafts (
    canvas_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 1,
    checksum VARCHAR(64) NOT NULL DEFAULT '',
    content LONGTEXT NOT NULL,
    node_count INTEGER NOT NULL DEFAULT 0,
    updated_by VARCHAR(64) NOT NULL DEFAULT '',
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_canvas_drafts_project FOREIGN KEY (canvas_id) REFERENCES canvas_projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS canvas_draft_versions (
    id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    canvas_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version INTEGER NOT NULL,
    checksum VARCHAR(64) NOT NULL DEFAULT '',
    content LONGTEXT NOT NULL,
    node_count INTEGER NOT NULL DEFAULT 0,
    created_by VARCHAR(64) NOT NULL DEFAULT '',
    created_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uk_canvas_draft_version (canvas_id, version),
    CONSTRAINT fk_canvas_versions_project FOREIGN KEY (canvas_id) REFERENCES canvas_projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
