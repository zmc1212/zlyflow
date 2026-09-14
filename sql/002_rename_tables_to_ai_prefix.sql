-- ====================================================================
-- 将原供应商配置表统一重命名为以 ai_ 开头的前缀
-- 符合开发规则: 所有数据表必须以 ai_ 开头
-- ====================================================================

RENAME TABLE
    `comfy_provider_settings` TO `ai_comfy_provider_settings`,
    `grs_provider_settings` TO `ai_grs_provider_settings`,
    `grs_image_models` TO `ai_grs_image_models`,
    `llm_provider_settings` TO `ai_llm_provider_settings`,
    `qiniu_provider_settings` TO `ai_qiniu_provider_settings`;
