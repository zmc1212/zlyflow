-- 006_alter_job_result_url_to_text.sql
-- 将 ai_project_jobs 表中的 result_url 改为 TEXT，避免长 URL 截断或报错

ALTER TABLE `ai_project_jobs` MODIFY COLUMN `result_url` TEXT DEFAULT NULL;
