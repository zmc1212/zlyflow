"""导演台2（AI Media Studio）后端模块。

复刻自 origin/dev0914（z-admin + server），保持 API 路径与业务逻辑一致：
- /api/projects 及其 documents/assets/episodes/jobs 子路径
- 数据表 ai_*（建表见 sql/013_media_studio_init.sql）
- Provider 配置不复刻 dev0914 的 ai_*_provider_settings 表，
  统一经 provider_bridge 读取工作台现有 /api/admin/providers 配置存储。
"""
