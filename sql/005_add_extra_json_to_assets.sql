-- ====================================================================
-- 为 ai_project_assets 表扩展 extra_json 字段
-- 用于存储角色的头像 (portrait)、身份/造型 (identities/costumes) 及多版本形象配置
-- ====================================================================

ALTER TABLE `ai_project_assets`
ADD COLUMN `extra_json` LONGTEXT DEFAULT NULL AFTER `voice_id`;
