-- H3 video jobs store six full prompts plus the complete ComfyUI workflow snapshot.
ALTER TABLE `ai_project_jobs`
  MODIFY COLUMN `payload_json` LONGTEXT DEFAULT NULL;
