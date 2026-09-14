-- 为 ai_project_jobs 表添加 payload_json 列，存储任务完整调用参数
-- 包括：调用模型名称、API 地址、完整 prompt、aspect_ratio、宽高等

ALTER TABLE `ai_project_jobs`
  ADD COLUMN `payload_json` TEXT DEFAULT NULL AFTER `error_message`,
  ADD COLUMN `completed_at` VARCHAR(64) DEFAULT NULL AFTER `payload_json`;
