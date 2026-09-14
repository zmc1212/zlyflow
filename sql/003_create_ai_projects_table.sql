-- ====================================================================
-- 创建 AI 创作项目表
-- 规则: 数据表必须统一以 ai_ 为前缀
-- ====================================================================

CREATE TABLE IF NOT EXISTS `ai_projects` (
    `id` VARCHAR(64) NOT NULL PRIMARY KEY,
    `name` VARCHAR(255) NOT NULL,
    `description` TEXT DEFAULT NULL,
    `cover_url` VARCHAR(512) DEFAULT NULL,
    `status` VARCHAR(32) NOT NULL DEFAULT 'active',
    `settings_json` LONGTEXT DEFAULT NULL,
    `created_at` VARCHAR(64) NOT NULL,
    `updated_at` VARCHAR(64) NOT NULL,
    KEY `idx_ai_projects_updated_at` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 从历史导台项目安全导入（如存在 xiaji_projects 则同步基础记录）
INSERT INTO `ai_projects` (`id`, `name`, `description`, `settings_json`, `created_at`, `updated_at`)
SELECT `id`, `name`, '导台创作项目', `settings_json`, `created_at`, `updated_at`
FROM `xiaji_projects`
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`);
