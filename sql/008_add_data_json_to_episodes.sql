-- 008: 为剧集工坊 ai_project_episodes 表增加 data_json 字段持久化分镜结构与生成数据
ALTER TABLE `ai_project_episodes`
ADD COLUMN `data_json` LONGTEXT DEFAULT NULL AFTER `script_text`;
