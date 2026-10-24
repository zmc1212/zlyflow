-- Editing documents are independent of adopted shots and protected per account.
CREATE TABLE IF NOT EXISTS ai_smart_edit_documents (
    id VARCHAR(64) PRIMARY KEY,
    project_id VARCHAR(64) NOT NULL,
    owner_user_id VARCHAR(64) NOT NULL,
    sequence_id VARCHAR(160) NOT NULL,
    revision INT NOT NULL DEFAULT 1,
    document_json LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_smart_edit_project_owner (project_id, owner_user_id),
    CONSTRAINT fk_smart_edit_project FOREIGN KEY (project_id) REFERENCES ai_projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
