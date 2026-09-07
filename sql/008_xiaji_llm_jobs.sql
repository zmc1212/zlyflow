-- 导台2 大模型调用任务：内容导入分析、生成脚本、声线定义等

CREATE TABLE IF NOT EXISTS xiaji_llm_jobs (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    owner_user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    target VARCHAR(512) NOT NULL,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    model VARCHAR(255) NULL,
    prompt LONGTEXT NOT NULL,
    system_prompt LONGTEXT NULL,
    messages_json LONGTEXT NULL,
    parameters_json LONGTEXT NOT NULL,
    response_json LONGTEXT NULL,
    error TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    KEY idx_xiaji_llm_jobs_project (project_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
