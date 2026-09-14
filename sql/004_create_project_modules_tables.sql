-- ====================================================================
-- 创建项目子模块表：内容库、资产库、剧集工坊、全部任务
-- 数据库: media22
-- 规则: 数据表必须统一以 ai_ 为前缀
-- ====================================================================

-- 1. 项目剧本文档表 (内容库)
CREATE TABLE IF NOT EXISTS `ai_project_documents` (
    `id` VARCHAR(64) NOT NULL PRIMARY KEY,
    `project_id` VARCHAR(64) NOT NULL,
    `filename` VARCHAR(255) NOT NULL,
    `file_size` INT NOT NULL DEFAULT 0,
    `input_mode` VARCHAR(32) NOT NULL DEFAULT 'paste',
    `status` VARCHAR(32) NOT NULL DEFAULT 'ready',
    `spine_template` VARCHAR(64) NOT NULL DEFAULT 'drama',
    `visual_style` VARCHAR(64) NOT NULL DEFAULT 'chinese_period_drama',
    `raw_text` LONGTEXT DEFAULT NULL,
    `analysis_json` LONGTEXT DEFAULT NULL,
    `created_at` VARCHAR(64) NOT NULL,
    `updated_at` VARCHAR(64) NOT NULL,
    KEY `idx_ai_doc_project` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. 项目资产库表 (资产库: 角色、场景、道具)
CREATE TABLE IF NOT EXISTS `ai_project_assets` (
    `id` VARCHAR(64) NOT NULL PRIMARY KEY,
    `project_id` VARCHAR(64) NOT NULL,
    `kind` VARCHAR(32) NOT NULL DEFAULT 'character',
    `name` VARCHAR(128) NOT NULL,
    `role` VARCHAR(64) DEFAULT NULL,
    `description` TEXT DEFAULT NULL,
    `visual_prompt` TEXT DEFAULT NULL,
    `image_url` VARCHAR(512) DEFAULT NULL,
    `voice_id` VARCHAR(64) DEFAULT NULL,
    `created_at` VARCHAR(64) NOT NULL,
    `updated_at` VARCHAR(64) NOT NULL,
    KEY `idx_ai_asset_project` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. 项目剧集工坊表 (剧集工坊: 分集与脚本镜头)
CREATE TABLE IF NOT EXISTS `ai_project_episodes` (
    `id` VARCHAR(64) NOT NULL PRIMARY KEY,
    `project_id` VARCHAR(64) NOT NULL,
    `episode_num` INT NOT NULL DEFAULT 1,
    `title` VARCHAR(255) NOT NULL,
    `status` VARCHAR(32) NOT NULL DEFAULT 'draft',
    `script_text` LONGTEXT DEFAULT NULL,
    `shots_count` INT NOT NULL DEFAULT 0,
    `created_at` VARCHAR(64) NOT NULL,
    `updated_at` VARCHAR(64) NOT NULL,
    KEY `idx_ai_ep_project` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. 项目生成任务表 (全部任务: 异步任务、队列与进度)
CREATE TABLE IF NOT EXISTS `ai_project_jobs` (
    `id` VARCHAR(64) NOT NULL PRIMARY KEY,
    `project_id` VARCHAR(64) NOT NULL,
    `job_type` VARCHAR(64) NOT NULL,
    `title` VARCHAR(255) NOT NULL,
    `status` VARCHAR(32) NOT NULL DEFAULT 'queued',
    `progress` INT NOT NULL DEFAULT 0,
    `result_url` VARCHAR(512) DEFAULT NULL,
    `error_message` TEXT DEFAULT NULL,
    `created_at` VARCHAR(64) NOT NULL,
    `updated_at` VARCHAR(64) NOT NULL,
    KEY `idx_ai_job_project` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
