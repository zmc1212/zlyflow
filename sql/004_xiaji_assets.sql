-- 导台2 资产库：角色 / 场景 / 道具 / 声线（虾塘独立重建）

CREATE TABLE IF NOT EXISTS xiaji_assets (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    source_document_id VARCHAR(64) NULL,
    definition_json LONGTEXT NOT NULL,
    image_job_id VARCHAR(64) NULL,
    image_object_key VARCHAR(512) NULL,
    image_url TEXT NULL,
    error TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uk_xiaji_assets_owner_kind_name (owner_user_id, kind, name),
    KEY idx_xiaji_assets_owner_kind (owner_user_id, kind, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS xiaji_asset_media (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    asset_id VARCHAR(64) NOT NULL,
    media_kind VARCHAR(32) NOT NULL,
    slot VARCHAR(64) NOT NULL DEFAULT '',
    job_id VARCHAR(64) NULL,
    object_key VARCHAR(512) NULL,
    url TEXT NULL,
    prompt TEXT NULL,
    model VARCHAR(255) NULL,
    is_official TINYINT NOT NULL DEFAULT 1,
    created_at VARCHAR(64) NOT NULL,
    KEY idx_xiaji_asset_media_asset (asset_id, media_kind, created_at),
    CONSTRAINT fk_xiaji_asset_media_asset FOREIGN KEY (asset_id) REFERENCES xiaji_assets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
