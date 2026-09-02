-- 导台2 内容库：LLM 导入分析结果（角色/场景/道具/剧集规划）

CREATE TABLE IF NOT EXISTS xiaji_document_analyses (
    document_id VARCHAR(64) NOT NULL PRIMARY KEY,
    model VARCHAR(255) NOT NULL,
    summary TEXT NULL,
    analysis_json LONGTEXT NOT NULL,
    logs LONGTEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT fk_xiaji_analyses_document FOREIGN KEY (document_id) REFERENCES xiaji_documents(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
