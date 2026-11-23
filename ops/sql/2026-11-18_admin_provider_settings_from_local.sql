-- ============================================================================
-- 管理设置迁移：开发工作台 → 正式服务器（自适应版 v2）
-- 生成时间：2026-11-19 00:31 (UTC+8)
-- 来源：192.168.10.200:3307 / ai-media（开发库当前生效配置）
-- 目标：正式服务器 ai-media
--
-- 与 v1 的区别：v1 直接按开发库的列名 INSERT，遇到线上缺列会报
--   1054 Unknown column。本版先读取 information_schema，只写目标库真实存在的列，
--   缺列、缺表（如旧镜像没有 llm_endpoint_credentials / cloud_video_provider_settings）
--   都会自动跳过，因此不需要先对齐表结构。
--
-- 覆盖：LLM 大模型、VLM 视觉模型、TTS、七牛存储、GRS 图片、云端视频（scnet）、
--       邮件 SMTP、音乐生成、LLM 端点档案
-- 不含：账号/用户、项目/任务/素材；ComfyUI 地址（线上是 127.0.0.1:18188，不覆盖）
--
-- 用法：在 Navicat 里连 ai-media，打开本文件整段执行；或
--   docker compose exec -T mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ai-media' < 本文件
--
-- 特性：幂等（REPLACE，重复执行结果一致）；不写 last_test_* 与余额；
--       执行后请在管理设置各卡片点一次「测试连接」。
-- 如果线上镜像较新、但库还缺 profile_id / vision_* 这些列，文件末尾附了可选的
-- ALTER 补齐语句（默认注释掉，按需手工执行）。
-- 前提：*_encrypted 列是 Fernet 密文，线上 .env 的
--       ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY 必须与开发机 data/credential.key 一致。
-- ============================================================================

SET NAMES utf8mb4;
SET SESSION group_concat_max_len = 1000000;

-- ---------------------------------------------------------------------------
-- 1. LLM 大模型
-- 线上表若没有 profile_id / vision_* 等新列，会自动只写存在的列。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'id', '1'),
    (2, 'enabled', '1'),
    (3, 'base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
    (4, 'api_key_encrypted', 'gAAAAABq890slHTQjRcl0HsqIQ3KU04NZb1xM8E9PC2T8kVVPY-IFSBRyn4Va6pOZ3E0QfirxVLcDgfLgvXcjjElXMkWkx1vmHI0-PjuZBQ04YL1P3pWZv8DOxzdM5I90vwsLmLTaS2gRtbQddba8_u4Kq3gQfN-dRq-u8Z7EHxJom2CjYPlyzPgDptLqQUYAvyM4bpO-OLofbqqkOPyzCf4IGQGxW51KQxVS3Dsb0buME969cHz8aU='),
    (5, 'model', 'deepseek-v4.1-flash-1017'),
    (6, 'assistant_models_json', '["qwen-plus"]'),
    (7, 'profile_id', 'dashscope'),
    (8, 'reasoning_effort', 'low'),
    (9, 'vision_capability', 'supported'),
    (10, 'vision_capability_source', 'probe'),
    (11, 'vision_capability_checked_at', '2026-09-29T08:16:41.853673+00:00'),
    (12, 'vision_capability_message', '双色图视觉验证通过'),
    (13, 'vision_capability_fingerprint', 'b6f0e79b7c774cc274cd7f77b04884e1e89029eefc7ae6043df13e071b5a7ffc'),
    (14, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'llm_provider_settings' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'llm_provider_settings' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `llm_provider_settings` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 2. VLM 视觉模型
-- 关闭「复用大模型凭据」，用 VLM 自己的 Key。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'id', '1'),
    (2, 'enabled', '1'),
    (3, 'base_url', 'https://api.qnaigc.com/v1'),
    (4, 'api_key_encrypted', 'gAAAAABq6APEBtvQb-mTNC2moJZaQht0v1uozZIikM2oOYHZ3kXp6gid28SybRujN4Om9-VYBzcEQJopAtfuGqR9ugiW1lE1guAm_SSxBgDiD_3ujimaX65fjpemBn7wW9tWDllp4JWNTaB2EWnlxtoRo0PI1Ujv2cUx9iaxjnbzSpHLNirn2eM='),
    (5, 'model', 'qiniu/conatus-free'),
    (6, 'use_llm_credentials', '0'),
    (7, 'profile_id', 'zhipu'),
    (8, 'vision_capability', 'unknown'),
    (9, 'vision_capability_source', NULL),
    (10, 'vision_capability_checked_at', NULL),
    (11, 'vision_capability_message', NULL),
    (12, 'vision_capability_fingerprint', NULL),
    (13, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'vlm_provider_settings' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'vlm_provider_settings' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `vlm_provider_settings` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 3. TTS 语音合成
-- 小米 MiMo TTS（OpenAI 兼容）。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'id', '1'),
    (2, 'enabled', '1'),
    (3, 'use_llm_credentials', '0'),
    (4, 'base_url', 'https://api.xiaomimimo.com/v1'),
    (5, 'api_key_encrypted', 'gAAAAABq60OLMk_oxLJxYBRosDCV7xhcgwk9ZDOJfbJcGh9TrENsdg6_3jKaVJdV4v_71mQ40sp6eZ_VQ0TsfrmweceBNHw2sl9A6EYHhEeLvT_EM-jYfLoawfCumPSODh58V2bw6ZoPJssHIBBEO3u8cTEn5_5gxQ=='),
    (6, 'model', 'mimo-v2.5-tts'),
    (7, 'voice', '冰糖'),
    (8, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'tts_provider_settings' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'tts_provider_settings' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `tts_provider_settings` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 4. 媒体存储（七牛云）
-- Bucket / 域名 / 对象前缀与开发环境一致。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'id', '1'),
    (2, 'enabled', '1'),
    (3, 'access_key_encrypted', 'gAAAAABqfs_dCVUrEZvkI8FvR6QX3G2TOXOuvGPYNkMasWd1cxPIzLac6MHvUxlIV5FXvGktiNUC_oHbf3zZpS8YxxgaVitOzXnw7tpExrGIUyCpf-YqInnwpFgmvZVa8KJf3fEDGrMJ'),
    (4, 'secret_key_encrypted', 'gAAAAABqfs_dje7cZvdXd49XjEVYu4fKNahw2KlI7lTIh8p5gETrNR4wcXS29QgbLzYV3g5GLCYcMRz47p0YJXQbBBvpq8jOHYJ1UJr5FBGPvuo30Tyf9R3K3h-5RyJu6HUduTitHd_5'),
    (5, 'bucket', 'zly-images'),
    (6, 'region', 'z0'),
    (7, 'domain', 'https://img.zlyun168.com'),
    (8, 'object_prefix', 'zly-ai-video-studio/'),
    (9, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'qiniu_provider_settings' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'qiniu_provider_settings' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `qiniu_provider_settings` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 5. AI 供应商 · GRS 图片
-- 余额与测试结果不迁移。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'id', '1'),
    (2, 'enabled', '1'),
    (3, 'base_url', 'https://grsai.dakka.com.cn'),
    (4, 'api_key_encrypted', 'gAAAAABqfsgGDUkCT_TaiaAFE4wAmdzxp8sRNT2gn5WKdd2PbCEOwri9BiK4Nz-KroOza6joczwh3OqE_nQrU9AKYP1sa1zprZoE3EX5tMBs4CmaPNPPdf0CwJFtcGP_RgMx0lH1zwYZ'),
    (5, 'gpt_image_2_enabled', '1'),
    (6, 'gpt_image_2_vip_enabled', '1'),
    (7, 'models', 'gpt-image-2'),
    (8, 'vip_models', 'gpt-image-2-vip'),
    (9, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'grs_provider_settings' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'grs_provider_settings' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `grs_provider_settings` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 6. AI 供应商 · 云端视频（超算互联网）
-- 可灵 / 即梦 / 海螺未启用，不写；旧镜像没有这张表时自动跳过。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'provider_key', 'scnet'),
    (2, 'enabled', '1'),
    (3, 'base_url', NULL),
    (4, 'api_key_encrypted', 'gAAAAABq9s9Rw8wmdQMJHhFYbTapicmURlPjHeD9aItOkq5_obU3XZ93GyLd4TjuvlqT82mycT-XfTm3whhHeOju-O63n6ytAsoQTJ8_e7Cgdaz4ApxYDTZE2WFXatWYgBQgBvMg8-hV'),
    (5, 'api_secret_encrypted', NULL),
    (6, 'extra_config_json', NULL),
    (7, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'cloud_video_provider_settings' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'cloud_video_provider_settings' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `cloud_video_provider_settings` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 7. 邮件服务（SMTP）
-- QQ 邮箱 SMTP 465/SSL。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'id', '1'),
    (2, 'enabled', '1'),
    (3, 'host', 'smtp.qq.com'),
    (4, 'port', '465'),
    (5, 'security', 'ssl'),
    (6, 'username', 'iahgnoroag@qq.com'),
    (7, 'password_encrypted', 'gAAAAABq8WVu7hzHYyV6Zj5R-80fneHNhTYr3_j1mkrJcdPMe952IY9BnG-ZtwfxJ_XIklVU3HynB4HL6c7pRw3M7giAMEUXmFA3QGzFGis-AHTlpPcQFoY='),
    (8, 'from_address', 'iahgnoroag@qq.com'),
    (9, 'from_name', 'ZLY AI Studio'),
    (10, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'mail_provider_settings' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'mail_provider_settings' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `mail_provider_settings` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 8. AI 供应商 · 音乐生成
-- base_url 是办公网地址，线上若走别的地址请在管理设置里改。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'id', '1'),
    (2, 'base_url', 'http://192.168.10.54:8791'),
    (3, 'access_key_encrypted', 'gAAAAABq7iXPaMvDSX1gJEUIxLC1QPKcNRIbrUFMOEFmirdzOb8hzWm1JkWI0HzqnU7F5djw6co-l2-xhpc1Xl7Ei022kpkp37CPuweQwL_EUdskPjq8950FFvy0hHd0scbKGj_r14R56JL8rt1cjrFdDQeaVQJzc6yMQ5lO2y_ay0-SotJP7LE='),
    (4, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'music_provider_settings' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'music_provider_settings' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `music_provider_settings` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 9. LLM 端点档案（https://api.qnaigc.com/v1）
-- 旧镜像没有这张表时自动跳过。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'base_url', 'https://api.qnaigc.com/v1'),
    (2, 'api_key_encrypted', 'gAAAAABq50bqXxPHDdlvN-QciFsAu8rSAejYge6vesW2wDQv27xbE2S2NC3O5CRb6UInH-oMvyzw_21e02fKhu22ykit95hjlX0c46lub-JPXUdAmoY0DlWEL8RprGWMGqzJZfBaOvq9FA0P28K-MHp995du4PEvwQaCnudewYXUcKRfxiVc-CE='),
    (3, 'model', 'qiniu/conatus-free'),
    (4, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'llm_endpoint_credentials' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'llm_endpoint_credentials' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `llm_endpoint_credentials` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 10. LLM 端点档案（https://dashscope.aliyuncs.com/compatible-mode/v1）
-- 旧镜像没有这张表时自动跳过。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
    (2, 'api_key_encrypted', 'gAAAAABq890slHTQjRcl0HsqIQ3KU04NZb1xM8E9PC2T8kVVPY-IFSBRyn4Va6pOZ3E0QfirxVLcDgfLgvXcjjElXMkWkx1vmHI0-PjuZBQ04YL1P3pWZv8DOxzdM5I90vwsLmLTaS2gRtbQddba8_u4Kq3gQfN-dRq-u8Z7EHxJom2CjYPlyzPgDptLqQUYAvyM4bpO-OLofbqqkOPyzCf4IGQGxW51KQxVS3Dsb0buME969cHz8aU='),
    (3, 'model', 'deepseek-v4.1-flash-1017'),
    (4, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'llm_endpoint_credentials' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'llm_endpoint_credentials' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `llm_endpoint_credentials` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 11. LLM 端点档案（https://discovery-api.intern-ai.org.cn/v1）
-- 旧镜像没有这张表时自动跳过。
-- ---------------------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS `_cfg`;
CREATE TEMPORARY TABLE `_cfg` (`seq` INT NOT NULL PRIMARY KEY, `col` VARCHAR(64) NOT NULL, `val` MEDIUMTEXT NULL);
INSERT INTO `_cfg` (`seq`, `col`, `val`) VALUES
    (1, 'base_url', 'https://discovery-api.intern-ai.org.cn/v1'),
    (2, 'api_key_encrypted', 'gAAAAABq5ySAlsG8M4uXA62btcMf1gn8UTzlmiNEWYQ8wvBZRXcPD2shI22ub6NEDkuxILVJh9VCNoX-CDkdS7vyRSBV4GKn6ZY54Qm_8LwqqhGUkAVEQ_h_9pC9OynOgA1IFTwF9T7lvTb9kXCHz9Vyyw4bCON3N7_mmswbhrMgre9g04PUDpw='),
    (3, 'model', 'intern-s2'),
    (4, 'updated_at', '2026-11-18T16:31:29.730614+00:00');
SELECT GROUP_CONCAT(CONCAT('`', c.`col`, '`') ORDER BY c.`seq`) INTO @cols
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'llm_endpoint_credentials' AND ic.column_name = c.`col`);
SELECT GROUP_CONCAT(IF(c.`val` IS NULL, 'NULL', QUOTE(c.`val`)) ORDER BY c.`seq`) INTO @vals
  FROM `_cfg` c WHERE EXISTS (SELECT 1 FROM information_schema.columns ic WHERE ic.table_schema = 'ai-media' AND ic.table_name = 'llm_endpoint_credentials' AND ic.column_name = c.`col`);
SET @sql := IF(@cols IS NULL, 'DO 0',
  CONCAT('REPLACE INTO `llm_endpoint_credentials` (', @cols, ') VALUES (', @vals, ')'));
PREPARE `_cfg_stmt` FROM @sql; EXECUTE `_cfg_stmt`; DEALLOCATE PREPARE `_cfg_stmt`;

-- ---------------------------------------------------------------------------
-- 自检（只读）：看各配置表是否已存在、大概有多少行
-- ---------------------------------------------------------------------------
SELECT table_name, table_rows
  FROM information_schema.tables
 WHERE table_schema = 'ai-media'
   AND (table_name LIKE '%provider_settings' OR table_name = 'llm_endpoint_credentials')
 ORDER BY table_name;

-- 回滚：执行前先备份（容器内）
-- docker compose exec -T mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" ai-media \
--   grs_provider_settings qiniu_provider_settings llm_provider_settings llm_endpoint_credentials \
--   vlm_provider_settings tts_provider_settings music_provider_settings \
--   cloud_video_provider_settings mail_provider_settings' > settings_backup.sql

-- ---------------------------------------------------------------------------
-- 附：可选 schema 补齐（默认全部注释，不执行）
-- 仅当线上镜像是 2026-11 之后版本、界面会写这些列，而库还是老结构时才需要；
-- 执行前建议先备份，执行后重新跑一遍本文件即可把档案字段也写进去。
-- ---------------------------------------------------------------------------
-- ALTER TABLE `llm_provider_settings`
--   ADD COLUMN `reasoning_effort` VARCHAR(16) NOT NULL DEFAULT 'low',
--   ADD COLUMN `profile_id` VARCHAR(64) NOT NULL DEFAULT 'modelscope',
--   ADD COLUMN `vision_capability` VARCHAR(16) NOT NULL DEFAULT 'unknown',
--   ADD COLUMN `vision_capability_source` VARCHAR(32) NULL,
--   ADD COLUMN `vision_capability_checked_at` VARCHAR(64) NULL,
--   ADD COLUMN `vision_capability_message` TEXT NULL,
--   ADD COLUMN `vision_capability_fingerprint` VARCHAR(64) NULL;
-- ALTER TABLE `vlm_provider_settings`
--   ADD COLUMN `use_llm_credentials` TINYINT(1) NOT NULL DEFAULT 0,
--   ADD COLUMN `profile_id` VARCHAR(64) NOT NULL DEFAULT 'zhipu',
--   ADD COLUMN `vision_capability` VARCHAR(16) NOT NULL DEFAULT 'unknown',
--   ADD COLUMN `vision_capability_source` VARCHAR(32) NULL,
--   ADD COLUMN `vision_capability_checked_at` VARCHAR(64) NULL,
--   ADD COLUMN `vision_capability_message` TEXT NULL,
--   ADD COLUMN `vision_capability_fingerprint` VARCHAR(64) NULL;
