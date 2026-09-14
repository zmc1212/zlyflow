ALTER TABLE `ai_grs_provider_settings`
  ADD COLUMN `max_storyboard_concurrency` INT NOT NULL DEFAULT 5 AFTER `vip_models`;
