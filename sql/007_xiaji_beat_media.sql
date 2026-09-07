-- 导台2 镜头：渲染图与视频。列由 XiajiEpisodeStore.initialize 的 ensure_column 补齐，避免重复 ALTER。
-- 文档基线字段：
-- xiaji_beats.render_job_id / render_url / render_prompt / render_model / render_status / render_error
-- xiaji_beats.video_job_id / video_url / video_prompt / video_prompt_zh / video_model / video_duration / video_status / video_error
SELECT 1;
