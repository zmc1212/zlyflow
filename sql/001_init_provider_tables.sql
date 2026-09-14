-- ====================================================================
-- 初始化 AI 供应商、LLM 大模型、媒体存储配置表
-- 规则: 数据表必须统一以 ai_ 为前缀
-- ====================================================================

-- 1. ComfyUI 视频后端配置表
CREATE TABLE IF NOT EXISTS `ai_comfy_provider_settings` (
    `id` INT NOT NULL PRIMARY KEY,
    `base_url` VARCHAR(512) NOT NULL DEFAULT 'http://127.0.0.1:8188',
    `last_test_status` VARCHAR(64) DEFAULT NULL,
    `last_test_message` TEXT DEFAULT NULL,
    `last_test_at` VARCHAR(64) DEFAULT NULL,
    `updated_at` VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. GRS 图片供应商配置表
CREATE TABLE IF NOT EXISTS `ai_grs_provider_settings` (
    `id` INT NOT NULL PRIMARY KEY,
    `enabled` TINYINT(1) NOT NULL DEFAULT 0,
    `base_url` VARCHAR(512) NOT NULL DEFAULT 'https://grsai.dakka.com.cn',
    `api_key_encrypted` TEXT DEFAULT NULL,
    `gpt_image_2_enabled` TINYINT(1) NOT NULL DEFAULT 1,
    `gpt_image_2_vip_enabled` TINYINT(1) NOT NULL DEFAULT 1,
    `models` VARCHAR(255) NOT NULL DEFAULT 'gpt-image-2',
    `vip_models` VARCHAR(255) NOT NULL DEFAULT 'gpt-image-2-vip',
    `max_storyboard_concurrency` INT NOT NULL DEFAULT 5,
    `last_test_status` VARCHAR(64) DEFAULT NULL,
    `last_test_message` TEXT DEFAULT NULL,
    `last_test_at` VARCHAR(64) DEFAULT NULL,
    `last_balance` DOUBLE DEFAULT NULL,
    `last_balance_at` VARCHAR(64) DEFAULT NULL,
    `updated_at` VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. GRS 生图模型配置目录表
CREATE TABLE IF NOT EXISTS `ai_grs_image_models` (
    `workflow_id` VARCHAR(128) NOT NULL PRIMARY KEY,
    `provider_model` VARCHAR(128) NOT NULL UNIQUE,
    `display_name` VARCHAR(128) NOT NULL,
    `description` TEXT DEFAULT NULL,
    `profile` VARCHAR(64) NOT NULL,
    `resolutions_json` TEXT DEFAULT NULL,
    `enabled` TINYINT(1) NOT NULL DEFAULT 1,
    `sort_order` INT NOT NULL DEFAULT 100,
    `is_default` TINYINT(1) NOT NULL DEFAULT 0,
    `builtin` TINYINT(1) NOT NULL DEFAULT 0,
    `created_at` VARCHAR(64) NOT NULL,
    `updated_at` VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. LLM 大模型配置表
CREATE TABLE IF NOT EXISTS `ai_llm_provider_settings` (
    `id` INT NOT NULL PRIMARY KEY,
    `enabled` TINYINT(1) NOT NULL DEFAULT 0,
    `base_url` VARCHAR(512) NOT NULL DEFAULT 'https://api-inference.modelscope.cn/v1',
    `api_key_encrypted` TEXT DEFAULT NULL,
    `model` VARCHAR(255) NOT NULL DEFAULT 'deepseek-ai/DeepSeek-V4-Flash-0731',
    `last_test_status` VARCHAR(64) DEFAULT NULL,
    `last_test_message` TEXT DEFAULT NULL,
    `last_test_at` VARCHAR(64) DEFAULT NULL,
    `updated_at` VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. 七牛云媒体存储配置表
CREATE TABLE IF NOT EXISTS `ai_qiniu_provider_settings` (
    `id` INT NOT NULL PRIMARY KEY,
    `enabled` TINYINT(1) NOT NULL DEFAULT 0,
    `access_key_encrypted` TEXT DEFAULT NULL,
    `secret_key_encrypted` TEXT DEFAULT NULL,
    `bucket` VARCHAR(128) NOT NULL DEFAULT '',
    `region` VARCHAR(64) NOT NULL DEFAULT 'z0',
    `domain` VARCHAR(255) NOT NULL DEFAULT '',
    `object_prefix` VARCHAR(255) NOT NULL DEFAULT 'zly-ai-video-studio/',
    `last_test_status` VARCHAR(64) DEFAULT NULL,
    `last_test_message` TEXT DEFAULT NULL,
    `last_test_at` VARCHAR(64) DEFAULT NULL,
    `updated_at` VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 初始化基础配置记录 (默认 ID=1)
INSERT INTO `ai_comfy_provider_settings` (`id`, `base_url`, `updated_at`)
VALUES (1, 'http://127.0.0.1:8188', NOW())
ON DUPLICATE KEY UPDATE `id` = `id`;

INSERT INTO `ai_grs_provider_settings` (`id`, `enabled`, `base_url`, `updated_at`)
VALUES (1, 0, 'https://grsai.dakka.com.cn', NOW())
ON DUPLICATE KEY UPDATE `id` = `id`;

INSERT INTO `ai_llm_provider_settings` (`id`, `enabled`, `base_url`, `model`, `updated_at`)
VALUES (1, 0, 'https://api-inference.modelscope.cn/v1', 'deepseek-ai/DeepSeek-V4-Flash-0731', NOW())
ON DUPLICATE KEY UPDATE `id` = `id`;

INSERT INTO `ai_qiniu_provider_settings` (`id`, `enabled`, `region`, `object_prefix`, `updated_at`)
VALUES (1, 0, 'z0', 'zly-ai-video-studio/', NOW())
ON DUPLICATE KEY UPDATE `id` = `id`;

-- 初始化 GRS 常用内置模型
INSERT INTO `ai_grs_image_models` (`workflow_id`, `provider_model`, `display_name`, `description`, `profile`, `resolutions_json`, `enabled`, `sort_order`, `is_default`, `builtin`, `created_at`, `updated_at`)
VALUES
('grs-gpt-image-2', 'gpt-image-2', 'NanoBanana 极速通用 (标准)', '低延迟通用生图模型，适合快速出图', 'nano_banana', '["1024x1024","1024x1536","1536x1024"]', 1, 10, 1, 1, NOW(), NOW()),
('grs-gpt-image-2-vip', 'gpt-image-2-vip', 'NanoBanana 极速通用 (VIP通道)', 'VIP 优先队列，生成速度更快且并发更高', 'nano_banana', '["1024x1024","1024x1536","1536x1024"]', 1, 20, 0, 1, NOW(), NOW())
ON DUPLICATE KEY UPDATE `workflow_id` = `workflow_id`;
