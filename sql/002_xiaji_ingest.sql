-- 导台2 内容库：原文与章节（虾料独立重建最小模型）

CREATE TABLE IF NOT EXISTS xiaji_documents (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    source_format VARCHAR(16) NOT NULL,
    original_text LONGTEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    billed_char_count INTEGER NOT NULL DEFAULT 0,
    chapter_count INTEGER NOT NULL DEFAULT 0,
    estimated_episodes INTEGER NOT NULL DEFAULT 0,
    error TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    KEY idx_xiaji_documents_owner_updated (owner_user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS xiaji_chapters (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    document_id VARCHAR(64) NOT NULL,
    sequence INTEGER NOT NULL,
    title VARCHAR(512) NOT NULL,
    content LONGTEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uk_xiaji_chapters_doc_seq (document_id, sequence),
    CONSTRAINT fk_xiaji_chapters_document FOREIGN KEY (document_id) REFERENCES xiaji_documents(id) ON DELETE CASCADE,
    KEY idx_xiaji_chapters_document (document_id, sequence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
