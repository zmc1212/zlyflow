# ZLY AI Video Studio API 文档

更新日期：2026-08-11

## 使用方式

工作台监听本机与局域网 IPv4 地址的 `7865` 端口。启动 `启动本地视频工作台.bat` 后，以下三个地址由 FastAPI 自动从当前后端代码生成；其中 `127.0.0.1` 可替换为本机 IPv4 地址。

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:7865/api/docs` | Swagger UI，可在浏览器中填写参数、上传文件并直接发起请求。 |
| `http://127.0.0.1:7865/api/redoc` | ReDoc，只读浏览版。 |
| `http://127.0.0.1:7865/api/openapi.json` | OpenAPI 3.1 JSON，是接口定义的唯一来源，可供代码生成和第三方工具导入。 |

本项目采用 **FastAPI OpenAPI + Swagger UI/ReDoc** 作为主文档工具：它已随 FastAPI 提供，不增加部署服务，也能从 Pydantic 模型、参数校验和路由自动同步。若团队需要接口用例、自动化测试、Mock 或多人协作，可把 `/api/openapi.json` 下载为文件后导入 Apifox；不要在 Apifox 中单独维护另一份接口定义。

## 通用约定

- 所有业务接口以 `/api` 开头，响应为 JSON，媒体下载接口除外。
- 除 `/api/health`、`/api/auth/status`、`/api/auth/setup` 和 `/api/auth/login` 外，业务接口都需要 `zly_ai_video_studio_session` HttpOnly Cookie。所有写操作还需要登录响应中的 `csrf_token`，通过 `X-CSRF-Token` 请求头提交。
- 本机访问可使用 `http://127.0.0.1:7865`；局域网员工端的目录写入必须通过受信任 HTTPS。不得将 `7865` 直接暴露到公网。
- 创建任务使用 `multipart/form-data`，不是 JSON；`references` 可重复提交多个图片文件，上传顺序有业务含义。
- 单张参考图最大 50 MB，且 `Content-Type` 必须为 `image/*`。
- 创建任务成功返回 `202 Accepted`，表示已入队，并不代表图片或视频已经生成完成。
- 轮询间隔建议为 1-2 秒；任务终态为 `succeeded`、`partial`、`failed`、`interrupted` 或 `cancelled`。
- 通用错误格式为 `{"detail": "错误说明"}`。参数校验错误状态码为 `422`，资源不存在为 `404`，单个文件超过限制为 `413`。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 检查工作台和当前配置的 ComfyUI 实例可用性。 |
| `GET` | `/api/auth/status` | 获取首次初始化或当前登录状态。 |
| `POST` | `/api/auth/setup` | 从工作站本机创建首位超级管理员。 |
| `POST` | `/api/auth/login` | 登录并设置 HttpOnly 会话 Cookie。 |
| `POST` | `/api/auth/logout` | 注销当前会话。 |
| `POST` | `/api/auth/password` | 修改当前密码；初始密码用户必须先调用。 |
| `GET/POST` | `/api/admin/users` | 管理员读取或创建员工账号。 |
| `PATCH` | `/api/admin/users/{user_id}` | 调整角色或启停账号。 |
| `POST` | `/api/admin/users/{user_id}/reset-password` | 重置初始密码并撤销该用户会话。 |
| `GET/PUT` | `/api/admin/providers/comfy` | 超级管理员读取或保存 ComfyUI 连接地址。 |
| `POST` | `/api/admin/providers/comfy/test` | 超级管理员测试当前输入的 ComfyUI 地址，不必先保存。 |
| `GET` | `/api/modes` | 获取工作流能力注册表、图片尺寸和提示词预设。 |
| `GET` | `/api/modes/{mode_id}` | 获取一个工作流在 `POST /api/jobs` 中的完整参数契约。 |
| `POST` | `/api/jobs` | 提交一个生成任务。 |
| `GET` | `/api/jobs` | 按创建时间倒序读取任务列表。 |
| `GET` | `/api/jobs/{job_id}` | 查询单个任务的进度、状态和输出。 |
| `POST` | `/api/jobs/{job_id}/cancel` | 停止排队中、生成中或已中断的任务。 |
| `GET` | `/api/library` | 列出当前用户已成功生成的资源元数据。 |
| `POST` | `/api/admin/providers/llm/models` | 超级管理员向上游拉取模型目录；硅基流动对照模型广场价格 0 / Free 筛选免费模型。 |
| `GET` | `/api/admin/providers/vlm` | 超级管理员读取 VLM 视觉模型配置。 |
| `PUT` | `/api/admin/providers/vlm` | 超级管理员保存 VLM 视觉模型配置（独立 Key，与 LLM 分离）。 |
| `POST` | `/api/admin/providers/vlm/test` | 测试 VLM 视觉模型连接。 |
| `POST` | `/api/admin/providers/vlm/models` | 拉取上游目录并筛选名称含 VL/Vision 的视觉模型。 |
| `GET` | `/api/vlm/status` | 查询视觉模型是否可用及当前模型名。 |
| `POST` | `/api/llm/optimize-prompt` | 按工作流/技能优化提示词，不创建生成任务。 |
| `POST` | `/api/llm/analyze-subject` | 上传主体参考图，由独立 VLM 配置提取外貌描述。 |
| `POST` | `/api/llm/split-script` | 将剧本拆成结构化分镜头脚本。 |
| `GET` | `/api/director/art-styles` | 读取 9 类 34 条画风目录。`imageUrl` 为同源预览地址。 |
| `GET` | `/api/director/art-styles/{style_id}/preview` | 读取画风 JPEG 预览（登录后，服务端缓存 OpenDirector CDN）。 |
| `GET` | `/api/director/projects` | 列出当前用户的导演工程摘要。 |
| `POST` | `/api/director/projects` | 创建导演工程，可带 `source_script` 与 Recipe/时间轴 payload。 |
| `POST` | `/api/director/projects/migrate` | 将浏览器 localStorage 工程迁入 SQLite；相同 ID 跳过。 |
| `GET` | `/api/director/projects/{project_id}` | 读取工程全文，含剧本原文与 payload。 |
| `PUT` | `/api/director/projects/{project_id}` | 更新标题、原文或 payload；`source_script` 可写空字符串清空。 |
| `DELETE` | `/api/director/projects/{project_id}` | 删除当前用户的导演工程。 |
| `POST` | `/api/director/projects/{project_id}/copy` | 复制工程到当前用户项目库。 |
| `POST` | `/api/director/projects/{project_id}/convert-to-recipe` | 将旧时间轴工程转为 Recipe。 |
| `GET` | `/api/xiaji/art-style` | 读取当前用户导台2 默认画风。 |
| `PUT` | `/api/xiaji/art-style` | 保存默认画风。JSON `art_style_id` 必须是画风目录 id，空字符串表示清除。 |
| `GET` | `/api/xiaji/projects` | 列出当前用户的导台2 项目。 |
| `POST` | `/api/xiaji/projects` | 新建导台2 项目。JSON 可选 `name`、`settings`。 |
| `GET` | `/api/xiaji/projects/{project_id}` | 读取项目名称与导入设置。 |
| `PATCH` | `/api/xiaji/projects/{project_id}` | 更新名称或 `settings`。 |
| `DELETE` | `/api/xiaji/projects/{project_id}` | 删除项目及其内容库文档、资产和剧集。 |
| `GET` | `/api/xiaji/documents` | 列出当前项目的内容库文档摘要。必填 query `project_id`。 |
| `POST` | `/api/xiaji/documents` | 上传 TXT / Markdown / DOCX。必填 query `project_id`。可选表单 `replace=true`：先清空本项目文稿/资产/剧集再导入。 |
| `POST` | `/api/xiaji/documents/paste` | 粘贴纯文本。必填 query `project_id`。JSON 可选 `replace`。 |
| `GET` | `/api/xiaji/documents/{document_id}` | 读取原文与章节。 |
| `PUT` | `/api/xiaji/documents/{document_id}/chapters` | 保存人工校对后的章节列表。 |
| `GET` | `/api/xiaji/assets` | 列出当前项目导台2 资产。必填 query `project_id`，可选 `kind`。 |
| `POST` | `/api/xiaji/assets/sync` | 从当前项目内容库分析同步角色/场景/道具/解说。必填 query `project_id`。 |
| `POST` | `/api/xiaji/assets` | 新建资产。必填 query `project_id`。`definition.visual_style` 为空时写入项目 `settings.visual_style`。 |
| `GET` | `/api/xiaji/assets/{asset_id}` | 读取资产定义与媒体。 |
| `PUT` | `/api/xiaji/assets/{asset_id}` | 更新名称与定义。 |
| `DELETE` | `/api/xiaji/assets/{asset_id}` | 删除资产。 |
| `POST` | `/api/xiaji/assets/{asset_id}/generate-image` | 入队生成肖像、造型、场景正面/背面/360 或道具主视图/转面三视图/细节特写，立即 **202** 返回 `job_id`。JSON 可选 `look_id`、`style`、`ethnicity`、`model`、场景 `scene_view`（`master` / `reverse` / `panorama`）、道具 `prop_view`（`master` / `turnaround` / `detail`）。角色肖像在已选画风时把画风 JPEG 预览作为 REFERENCE 1；无法加载预览时 **422**。`look_id` 造型图必须已有肖像，并把它作为身份锚点传入；画幅 16:9、1K、四面板 sheet；无肖像或无外观描述时 **422**。`scene_view=reverse` / `panorama` 必须已有正面源图，并把它作为第 1 张参考图传入；`panorama` 再按顺序附上已有背面。`prop_view=turnaround` / `detail` 必须已有主视图作为 REFERENCE 1。无正面/主视图时附图返回 **422**。随后轮询 `GET /api/jobs/{job_id}`。 |
| `POST` | `/api/xiaji/assets/{asset_id}/upload-image` | 上传参考图。 |
| `POST` | `/api/xiaji/assets/{asset_id}/define-voice` | 用大模型生成声线定义。 |
| `POST` | `/api/xiaji/assets/{asset_id}/generate-voice` | 按定义合成试听音频。 |
| `POST` | `/api/xiaji/assets/{asset_id}/upload-voice` | 上传声线参考音频。 |
| `GET` | `/api/xiaji/jobs` | 列出当前项目生成任务。必填 `project_id`。含生图/视频、大模型调用、整集自动生成与合成成片。每条含提示词、`options`、`parameters` 全量入参，以及 `references[].url`（`/api/jobs/{id}/references/{n}`）用于预览传入图。大模型失败时 `error` 为原因，`llm_output.raw` 为模型原文。合成任务 `slot=compose`，完成后带成片 `preview_url`。 |
| `GET` | `/api/xiaji/episodes` | 列出当前项目剧集。必填 query `project_id`。 |
| `POST` | `/api/xiaji/episodes/from-analysis` | 从内容库剧集规划落库。必填 `project_id`。JSON 可选 `document_id`、`force`。 |
| `GET` | `/api/xiaji/episodes/{episode_id}` | 读取原文行、资产绑定、Beat、草图/视频与成片字段（`compose_*`、`compose_blockers`、`compose_ready`）。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/compose` | 入队本机 ffmpeg 拼接成片，并写入全部任务（`xiaji_llm_jobs.kind=compose`）。JSON 可选 `resolution`（`1280x720` / `1920x1080`）、`add_subtitles`、`force`。精品剧有至少一段 `video_url` 即可；解说剧对入片镜头另需 `audio_url`。无 ffmpeg 或未配置存储 **503**。无视频 **422**。立即 **202** `{ ok, status: "composing", episode, job_id }`，轮询 GET 剧集或 `GET /api/xiaji/jobs`。 |
| `GET` | `/api/xiaji/episodes/{episode_id}/export/video` | 下载成片 MP4。不成片 **404**。 |
| `GET` | `/api/xiaji/episodes/{episode_id}/export/srt` | 按各镜时长导出对白 SRT。无对白 **404**。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/export/zip` | 打包各镜视频、成片与 SRT。 |
| `PATCH` | `/api/xiaji/episodes/{episode_id}` | 更新剧集标题。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/generate-script` | 入队按原文**逐行标注** Beat（一行一个，不改写、不合并），立即 **202** 返回 `{ ok, status, episode }`。场次头直接落 `scene_heading`；内容行调大模型补画面/对白类型，单行失败则规则兜底。JSON 可选 `force`。随后轮询 `GET /api/xiaji/episodes/{episode_id}`，`status` 变为 `script_ready` 或带回 `error`。 |
| `PUT` | `/api/xiaji/episodes/{episode_id}/beats` | 保存人工校对后的 Beat。 |
| `PATCH` | `/api/xiaji/episodes/{episode_id}/beats/{beat_id}` | 更新单条 Beat 文案、出场身份、场景和道具。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/beats/{beat_id}/upload-sketch` | 上传镜头草图（multipart `file`）。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/beats/{beat_id}/upload-in-frame` | 上传本镜衔接帧（上一镜视频截图）。multipart `file`，可选表单 `sec`、`manual`（`1` 表示手动截取）、`source_job_id`。无上一镜视频 **422**。第一条可出片 Beat **422**。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-sketch` | 为单个 Beat 入队**分镜草图**（白纸色块草稿，不是写实成片），**202** 返回 `job_id`。提示词写入项目 `settings.visual_style` 的风格说明；若选了画风再附加目录 `promptPrefix`。JSON 可选 `force`、`model`、`scene_view`（`front` / `reverse`）。参考图只带场景正反面弱参考。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/generate-sketches` | 批量入队本集草图（跳过已成功）。**202**。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-render` | 把已有草图精绘为渲染图。无草图 **422**。提示词始终带项目风格说明；动画风格走非真人收束。参考图顺序：草图、每个角色的头像再造型、场景主图。头像取 `media_kind=portrait`，不得用造型 job 充当人脸。任务失败时 beat `render_status=failed` 并写 `render_error`，不再保持 generating。已有渲染图时传 `force: true` 重新入队。**202**。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/beats/{beat_id}/video-prompt` | 用已配置大模型生成本 Beat 的 LightX2V 多参考视频提示词。无渲染图 **422**。从第二条可出片 Beat 起，无上一镜 `video_url` 或本镜衔接帧 **422**。JSON `duration` 为界面所选秒数（缺省才回退 Beat `video_duration` 或 5）。有衔接时中英稿必须写清 0-1.5s 从 `<Picture 1>` 过渡到本镜精绘，之后按本镜动作写。中英稿第一段会写入本镜动作（【必须演出】/ MUST PLAY THIS ACTION）；参考图只锁身份与空间，不冻住站位。用户提示写入项目风格说明；未选画风时动画风格仍按 `visual_style` 允许字效。界面保存 `video_prompt_zh`，入队使用 `video_prompt`。写入 `xiaji_llm_jobs`。本机不传 `<Audio n>`。**200** `{ ok, episode, prompt_zh, prompt_en, pictures }`。旧路径 `.../generate-video-prompt` 仍接受 POST。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/beats/{beat_id}/generate-video` | 用渲染图（及可选衔接帧）生成镜头视频。无渲染图 **422**。后续镜无上一镜视频或衔接帧 **422**。若已有英文 `video_prompt` 则原样入队，否则回退模板。JSON 可选 `force`、`family`（默认 LightX2V R2V）、`duration`、`quality`、`aspect_ratio`、`speed`、`custom_steps`、`scene_view`。R2V 有衔接时参考图顺序：上一镜截图、本镜精绘、角色头像、造型、场景；无衔接时仍以精绘为首张。I2V 有衔接时只把衔接帧当首帧，精绘不当全片尾帧。视频 job 失败或记录缺失时 `video_status=failed`，可再点生成重新入队。**202**。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/auto-run` | 添加本集自动生成任务。从 Beat 1 起串行：草图→精绘→（后续镜自动抽上一镜末帧）→提示词→视频。请求体锁定 `family/duration/quality/aspect_ratio/speed/custom_steps/scene_view`，后续镜全部使用。已有产物的步骤跳过。同集已有 queued/running **409**。无脚本或未配置 LLM/执行器 **422/503**。**202** `{ ok, run }`。 |
| `GET` | `/api/xiaji/episodes/{episode_id}/auto-run` | 读取本集最近一次自动生成进度（`status/progress/cursor/message/error`）。 |
| `POST` | `/api/xiaji/episodes/{episode_id}/auto-run/cancel` | 请求取消进行中的自动生成；在尚未入队下一步前退出。 |
| `POST` | `/api/director/recipes/run` | 启动导演流水线，写入 Recipe。可选 `agents` 只跑指定步骤（如 script+storyboard 按剧本一次生成全部分镜）。 |
| `POST` | `/api/director/recipes/{project_id}/step` | 重跑单个 Agent。 |
| `GET` | `/api/director/library-assets` | 列出当前用户的人物/场景/道具资产。可选 `kind`。 |
| `POST` | `/api/director/library-assets` | 新建员工级资产。 |
| `POST` | `/api/director/library-assets/from-recipe` | 把 Recipe 人物/场景/道具快照写入资产库。 |
| `PUT` | `/api/director/library-assets/{asset_id}` | 更新资产。 |
| `DELETE` | `/api/director/library-assets/{asset_id}` | 删除资产。 |
| `POST` | `/api/director/library-assets/{asset_id}/image` | 上传资产参考图。 |
| `GET` | `/api/director/library-assets/{asset_id}/image` | 读取资产参考图。 |
| `POST` | `/api/director/recipes/{project_id}/insert-library-assets` | 从资产库插入人物/场景/道具到 Recipe。 |
| `POST` | `/api/director/recipes/{project_id}/generate-assets` | 为角色/场景提交 GRS 定妆图。 |
| `POST` | `/api/director/recipes/{project_id}/generate-stills` | 为分镜提交 GRS 静帧，可再设为首帧。 |
| `POST` | `/api/director/recipes/{project_id}/frames` | 上传分镜首帧或尾帧（multipart：`shot_id`、`slot`、`file`）。 |
| `GET` | `/api/director/recipes/{project_id}/frames/{shot_id}/{slot}` | 读取已上传的分镜首帧或尾帧。 |
| `POST` | `/api/director/recipes/{project_id}/render-shots` | 按镜提交所选工作流族的视频任务（T2V/I2V/R2V 仍自动匹配）。 |
| `POST` | `/api/director/recipes/{project_id}/shots/{shot_id}/translate-prompt` | 把镜头中文正文按官方 h3-prompt-writing skill 翻译为英文 H3 正文并返回，不落库。LLM 未配置 503、缺中文正文 422、未知 shot 404。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/h3-prompt` | 剧集工坊素材组：入队 `h3_prompt` 任务生成本镜 H3 提示词（传入 `visual_prompt` / `audio` / `video_prompt_zh`，会剥掉动作里整段粘贴的台词；内心/旁白不作为开口对白）。先按对白+调度把 `video_duration` 抬到能演完，再按该秒数由程序渲染六段 Ref2VA（`<Subject n>`、锁定 `<d>`、一句运镜接一句台词），并注入导演台1 同款 timing 预算；英文须达可出片厚度且含 camera/lighting/sound），**202** 返回 `job_id`。结果写入 beat `h3_prompt` 与匹配后的 `video_duration`。整集/逐镜视频对已保存提示词做同一套渲染再跑厚度校验，通过则复用，过薄或对白对不上才重渲染。 |
| `GET` | `/api/director/export-capabilities` | 查询本机 ffmpeg/ffprobe 与 TTS 是否可用，以及音色目录。 |
| `POST` | `/api/director/recipes/{project_id}/tts` | 按对白调用 OpenAI 兼容 `/audio/speech` 生成逐镜 TTS；`character_id` 时写角色试听。不使用 Edge TTS。 |
| `GET` | `/api/director/recipes/{project_id}/tts/{shot_id}` | 读取已生成的分镜 TTS 音频。 |
| `GET` | `/api/director/recipes/{project_id}/voices/{character_id}` | 读取角色 TTS 试听。 |
| `POST` | `/api/director/recipes/{project_id}/bgm` | multipart 上传配乐。 |
| `GET` | `/api/director/recipes/{project_id}/bgm` | 读取工程配乐。 |
| `POST` | `/api/director/recipes/{project_id}/mux` | 用本机 ffmpeg concat 批准/成功镜头并混 TTS/BGM，可选烧字幕。失败镜不进入成片。未安装 ffmpeg 返回 503。 |
| `GET` | `/api/director/recipes/{project_id}/mux` | 下载工作台内成片 MP4。 |
| `GET` | `/api/director/recipes/{project_id}/export.fcpxml` | 下载 FCPXML 时间线。 |
| `GET` | `/api/director/recipes/{project_id}/export.edl` | 下载 CMX 3600 EDL。 |
| `GET` | `/api/admin/providers/tts` | 超级管理员读取独立 TTS 配置（密钥脱敏）。 |
| `PUT` | `/api/admin/providers/tts` | 超级管理员保存独立 TTS；可勾选复用 LLM 凭据。 |
| `POST` | `/api/admin/providers/tts/test` | 测试 TTS `/audio/speech` 连接。 |
| `POST` | `/api/director/batches` | 主题裂变多条脚本并并行排队所选工作流族的文生。 |
| `POST` | `/api/director/batches/{project_id}/render` | 对已有批量工程按 `item_ids` 重新排队 H3 文生。 |
| `GET` | `/api/jobs/{job_id}/outputs/{output_index}/download` | 下载当前用户待交付的暂存资源。 |
| `POST` | `/api/jobs/{job_id}/outputs/{output_index}/delivered` | 确认浏览器已落盘并删除服务器暂存。 |
| `GET` | `/api/media/{filename}` | 兼容读取当前用户的旧版结果文件。 |

## 系统与工作流

### `GET /api/health`

用于启动检查。`webui` 为 `ok` 表示 API 进程可用；`comfy.reachable` 表示当前配置的 ComfyUI `/system_stats` 是否可连接。默认地址为 `http://127.0.0.1:8188`，超级管理员可在管理后台覆盖。

```json
{
  "webui": "ok",
  "comfy": {
    "reachable": true,
    "url": "http://127.0.0.1:8188",
    "error": null
  }
}
```

### `GET /api/modes`

前端或外部客户端应以此接口返回值为准，不硬编码模式、参考图数量或 H3 选项。每个 `modes[]` 项均包含 `parameters` 数组；数组的 `name` 是 `POST /api/jobs` 的表单字段名，`values` 为枚举值，`min_items`/`max_items` 描述参考图数量，`schema` 描述 `options` JSON 字符串解析后的对象。

| `id` | 参考图 | 说明 |
| --- | --- | --- |
| `image` | 0-1 | Flux2-Klein 文生图；支持 `negative_prompt` 和 `image_size`。 |
| `ltx-video` | 固定 3 张 | 场景、主体、风格三图生成首帧后制作 LTX 视频。 |
| `vace-video` | 固定 3 张 | 场景、主体、风格三图直接制作 Wan VACE 视频。 |
| `minimax-h3-lightx2v-t2v` | 0 张 | LightX2V 文生；默认 1.0 MP、4 步 euler。 |
| `minimax-h3-lightx2v-i2v` | 1-2 张 | LightX2V 首帧必填，尾帧可选。 |
| `minimax-h3-lightx2v-r2v` | 1-9 张 | LightX2V 多参考；使用 Ref2V 4 步 LoRA，提示词 `<Picture n>`。 |
| `minimax-h3-dual-accel-t2v` | 0 张 | 八步双加速文生；默认 0.4 MP、8 步 `res_multistep`，FL2V 8 步 LoRA + KJ Sage + H3 Sage。 |
| `minimax-h3-dual-accel-i2v` | 1-2 张 | 八步双加速首尾帧；首帧必填，尾帧可选。 |
| `minimax-h3-dual-accel-r2v` | 1-9 张 | 八步双加速多参考；提示词 `<Picture n>`。 |
| `minimax-h3-t2v` | 0 张 | MiniMax H3 文生视频。 |
| `minimax-h3-i2v` | 1-2 张 | MiniMax H3 首帧必填，尾帧可选。 |
| `minimax-h3-r2v` | 1-9 张 | MiniMax H3 多参考视频；提示词以 `<Picture n>` 对应上传顺序。 |
| `minimax-h3-t8-all-reference` | 0-9 张 | H3 全能参考多速率工作流；`auto` 按图片数量选择 `T2VA`+FL2VA / `Ref2VA`+Ref2VA。快速/均衡挂 Turbo LoRA（全量 INT8）；高质量用 pruned 且不挂 LoRA。提示词使用 `<Picture n>`，也接受 `@图片n`。 |
| `minimax-h3-t8-dual-clock` | 0-1 张 | H3 双时钟采样工作流；无图文生，单图为首帧 I2VA，默认 8 步。 |

每个 mode 还包含 `catalog_group`、`catalog_group_label`、`catalog_group_order`。视频工作流分组为 `lightx2v`（LightX2V）、`dual_accel`（八步双加速）、`official_h3`（官方 MiniMax H3）、`custom`（自定义 T8）。前端按下拉分组展示，不硬编码组名。

### `GET /api/modes/{mode_id}`

返回指定模式的参数详情，适合外部客户端在选择工作流后动态创建表单。`mode_id` 可使用上表的任一 `id`，例如：

```text
GET /api/modes/minimax-h3-r2v
```

返回示例中的 `parameters` 可直接映射到提交接口：

```json
{
  "id": "minimax-h3-r2v",
  "request_content_type": "multipart/form-data",
  "parameters": [
    {"name": "mode", "type": "string", "required": true, "values": ["minimax-h3-r2v"]},
    {"name": "prompt", "type": "string", "required": true},
    {"name": "references", "type": "array", "required": true, "min_items": 1, "max_items": 9, "content_type": "image/*"},
    {
      "name": "options",
      "type": "string",
      "required": false,
      "default": "{}",
      "schema": {
        "type": "object",
        "properties": {
          "aspect_ratio": {"type": "string", "pattern": "^(?:\\d+(?:\\.\\d*)?|\\.\\d+)\\s*:\\s*(?:\\d+(?:\\.\\d*)?|\\.\\d+)$", "default": "16:9"},
          "megapixels": {"enum": [0.2, 0.3, 0.4, 0.5], "default": 0.2},
          "duration": {"minimum": 2, "maximum": 15, "default": 5}
        }
      }
    }
  ]
}
```

## 任务

### `POST /api/jobs`

请求字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `mode` | string | 是 | 工作流 ID，必须是 `/api/modes` 的一个 `id`。 |
| `prompt` | string | 是 | 创作提示词。 |
| `negative_prompt` | string | 否 | 仅 `image` 模式生效，默认空字符串。 |
| `image_size` | string | `image` 时是 | `横版 1280 x 720`、`方图 1024 x 1024` 或 `竖版 720 x 1280`。 |
| `options` | string | 否 | JSON 字符串；仅 H3 模式使用，其他模式传 `{}`。 |
| `references` | file[] | 视模式而定 | 图片文件数组，字段名必须重复为 `references`。 |

H3 的 `options` 形如：

```json
{"aspect_ratio":"16:9","megapixels":0.2,"duration":5}
```

- `aspect_ratio`：任意有限正数的 `宽:高` 字符串，例如 `16:9`、`2:3`、`3:2` 或 `21:9`；必须放在 `options` JSON 字符串中，不是独立的 multipart 字段。
- `megapixels`：`0.2`、`0.3`、`0.4`、`0.5`。
- `duration`：2 到 15 秒。实际输出帧数按 24fps、17n+5 网格向上对齐，因此 2 秒约为 56 帧（约 2.3 秒）。
- `speed`：`fast` / `balanced` / `quality` / `custom`，控制采样步数；默认 `balanced`。
- `weight_profile`：`full`（默认，全量 INT8，可挂加速 LoRA）或 `pruned`（精简 INT8，强制关闭加速 LoRA）。显示在创建栏，与生成速度并列。

两个 T8 模式也通过 `options` 提交参数，但字段更多。调用方必须以对应的 `GET /api/modes/{mode_id}` schema 为准；schema 包含 `type`、`enum`、`minimum`、`maximum`、`step`、`default`、`ui_group` 和可选 `unit`。`ui_group` 的语义为：`primary` 是创建页必要参数，`advanced` 进入“更多设置”，`internal` 由系统托管且不进入创建表单。未识别或缺失的层级应按 `internal` 处理。参数分为：

- 通用：`task_type`、`aspect_ratio`、`megapixels`、`multiple`、`duration`、`seed`。
- 音频与参考策略：`audio_mode`、`audio_denoise_strength`、`add_source_as_reference`、`prompt_primary_audio_ordinal`、`strict_prompt_tags`、`ref_image_size`、`reference_video_policy`。
- 采样：多速率模式的 `video_steps`/`audio_steps`，双时钟模式的 `steps`，以及两者共有的 `shift_video`/`shift_audio`。
- 模型与运行：模型、CLIP、VAE、LoRA、LoRA 强度、SageAttention；多速率模式另含预留显存参数。
- 输出：帧率、循环、H.264 像素格式、CRF、元数据、音频裁剪和 ping-pong。`filename_prefix` 与 `save_output` 由服务端固定。

### 按工作流提交参数

| `mode` | 必填字段 | 可选字段 | `references` 规则 |
| --- | --- | --- | --- |
| `image` | `mode`、`prompt`、`image_size` | `negative_prompt` | 0-1 张图片。 |
| `ltx-video` | `mode`、`prompt`、`references` | 无 | 固定 3 张，上传顺序为场景、主体、风格。 |
| `vace-video` | `mode`、`prompt`、`references` | 无 | 固定 3 张，上传顺序为场景、主体、风格。 |
| `minimax-h3-t2v` | `mode`、`prompt` | `options` | 不可上传参考图。 |
| `minimax-h3-i2v` | `mode`、`prompt`、`references` | `options` | 1-2 张；第一张首帧必填，第二张为可选尾帧。 |
| `minimax-h3-r2v` | `mode`、`prompt`、`references` | `options` | 1-9 张；`<Picture 1>` 对应第一张，依此类推。 |
| `minimax-h3-lightx2v-t2v` | `mode`、`prompt` | `options` | 不可上传参考图。 |
| `minimax-h3-lightx2v-i2v` | `mode`、`prompt`、`references` | `options` | 1-2 张；第一张首帧必填，第二张为可选尾帧。 |
| `minimax-h3-lightx2v-r2v` | `mode`、`prompt`、`references` | `options` | 1-9 张；`<Picture 1>` 对应第一张，依此类推。 |
| `minimax-h3-dual-accel-t2v` | `mode`、`prompt` | `options` | 不可上传参考图。 |
| `minimax-h3-dual-accel-i2v` | `mode`、`prompt`、`references` | `options` | 1-2 张；第一张首帧必填，第二张为可选尾帧。 |
| `minimax-h3-dual-accel-r2v` | `mode`、`prompt`、`references` | `options` | 1-9 张；`<Picture 1>` 对应第一张，依此类推。 |
| `minimax-h3-t8-all-reference` | `mode`、`prompt` | `options`、`references` | 0-9 张；`task_type=Ref2VA` 时至少 1 张。 |
| `minimax-h3-t8-dual-clock` | `mode`、`prompt` | `options`、`references` | 0-1 张；无图为 `T2VA`，单图为 `I2VA` 首帧。`task_type=Ref2VA` 时至少 1 张。 |

非 H3 工作流无需提交 `options`。原有 H3 模式未传时使用 `16:9`、`0.2 MP`、`5 秒`；T8 模式使用各自源工作流默认值。`GET /api/modes/{mode_id}` 是参数取值和约束的唯一来源。

使用 `curl.exe` 创建 H3 多参考任务的示例：

```powershell
curl.exe -X POST http://127.0.0.1:7865/api/jobs `
  -F "mode=minimax-h3-r2v" `
  -F "prompt=<Picture 1> 中的角色走进 <Picture 2> 的场景，镜头缓慢推进。" `
  -F "options={\"aspect_ratio\":\"16:9\",\"megapixels\":0.2,\"duration\":5}" `
  -F "references=@D:\素材\角色.png" `
  -F "references=@D:\素材\场景.png"
```

成功响应为 `202`。返回体是入队后的当前任务快照：worker 尚未领取时 `status` 为 `queued`；若 ComfyUI worker 已经开始准备或提交，则可能直接为 `running`。

```json
{
  "id": "WvhSEuCWne1d",
  "mode": "minimax-h3-r2v",
  "status": "queued",
  "stage": "等待排队",
  "progress": 0,
  "prompt": "<Picture 1> 中的角色走进 <Picture 2> 的场景，镜头缓慢推进。",
  "negative_prompt": "",
  "image_size": null,
  "options": {"aspect_ratio": "16:9", "quality": "0.2", "megapixels": 0.2, "duration": 5, "speed": "balanced", "reference_image_size": "match"},
  "reference_count": 2,
  "references": [
    {"index": 1, "url": "/api/jobs/WvhSEuCWne1d/references/1"},
    {"index": 2, "url": "/api/jobs/WvhSEuCWne1d/references/2"}
  ],
  "request_parameters": [
    {"name": "mode", "label": "工作流", "value": "minimax-h3-r2v", "visibility": "primary"},
    {"name": "prompt", "label": "创作提示词", "value": "<Picture 1> 中的角色走进 <Picture 2> 的场景，镜头缓慢推进。", "visibility": "primary"},
    {"name": "references", "label": "参考图", "value": 2, "visibility": "primary"},
    {"name": "options.aspect_ratio", "label": "画面比例", "value": "16:9", "visibility": "primary"},
    {"name": "options.megapixels", "label": "画质", "value": 0.2, "unit": "MP", "visibility": "advanced"},
    {"name": "options.duration", "label": "时长", "value": 5, "unit": "秒", "visibility": "primary"}
  ],
  "outputs": [],
  "error": null,
  "created_at": "2026-08-06T00:00:00+00:00",
  "updated_at": "2026-08-06T00:00:00+00:00"
}
```

### `GET /api/jobs` 和 `GET /api/jobs/{job_id}`

列表接口支持可选查询参数 `limit`，范围会被限制为 1-200，默认 100。管理员和超级管理员还可传 `user_id`：指定账号 ID 只返回该用户任务，`all` 返回全部用户任务；员工传入该参数会被忽略，始终只看到自己的任务。单任务接口返回与创建任务相同的对象。`request_parameters` 由工作流注册表生成，回显任务实际使用的标准化有效值；`visibility` 与 option 的 `ui_group` 一致，用于区分创作参数和内部运行参数。带 `ui_visible_when` 的字段仅在条件成立时出现，例如未选自定义速度时不回显 `custom_steps`。参考图通过 `references` 预览 URL 回显。出于隐私和路径安全，响应中不包含上传素材的本地路径。

```powershell
Invoke-RestMethod http://127.0.0.1:7865/api/jobs/WvhSEuCWne1d
```

任务成功时，`outputs` 包含媒体元数据：

```json
{
  "status": "succeeded",
  "stage": "生成完成",
  "progress": 100,
  "outputs": [
    {"kind": "video", "path": "minimax_h3_20260806_120000_a1b2c3d4.mp4", "label": "MiniMax H3 视频"}
  ],
  "error": null
}
```

任务失败时，`status` 为 `failed`，`error` 含后端或 ComfyUI 的错误摘要。用户停止生成时，`status` 为 `cancelled`，不会自动重新提交。

### `POST /api/jobs/{job_id}/cancel`

任务所有者或管理员可停止排队中、生成中或已中断的任务。视频任务会向当前配置的 ComfyUI 发送 `/interrupt`（仅当该 `prompt_id` 正在运行）或从 `/queue` 删除排队项，并将任务标为 `cancelled`，禁止自动重提。图片任务只停止工作台等待，云端 GRS 可能仍会继续。已完成或已失败任务返回 `409`。

```powershell
Invoke-RestMethod -Method Post `
  -Headers @{"X-CSRF-Token" = "<login response csrf_token>"} `
  http://127.0.0.1:7865/api/jobs/WvhSEuCWne1d/cancel
```

### `POST /api/jobs/{job_id}/retry`

当任务因 ComfyUI 或 FRP 连接中断而变为 `interrupted`，或已安全记录为 `failed` / `cancelled` 时，任务所有者或管理员可调用本接口立即重试。工作台仍会在 ComfyUI 恢复后自动接回或重新提交中断的 H3 视频任务，但用户停止的 `cancelled` 任务不会自动重提。接口只接受已清除 `prompt_id` 的终态任务，将其恢复为 `queued` 并重新加入单 worker 队列；仍在 ComfyUI 中执行的任务会返回 `409`，不会重复提交。

```powershell
Invoke-RestMethod -Method Post `
  -Headers @{"X-CSRF-Token" = "<login response csrf_token>"} `
  http://127.0.0.1:7865/api/jobs/WvhSEuCWne1d/retry
```

## 导台2 内容库与资产库

导台2 以项目为容器。先 `POST /api/xiaji/projects` 再建内容库和资产。列表、上传、粘贴、同步、新建资产均需 query `project_id`，且项目必须属于当前登录用户。文稿与章节按项目隔离。`POST /api/xiaji/documents` 为 `multipart/form-data`（`file` 必填，可选 `title`、`art_style_id`、`replace`）。`POST /api/xiaji/documents/paste` 为 JSON（`text` 必填，可选 `title`、`art_style_id`、`replace`）。`replace=true` 时先清空本项目内容库、资产、剧集和大模型任务，再写入新文稿。二者都同步规则切分章节、调用已配置 LLM 分析，并在成功后写入**同一项目**的资产库。无章节标题时整篇为一章且状态为 `review_required`，否则 `indexed`/`ready`。精品剧识别「第X集 / Episode N」为剧集边界（与「第N段」相同，优先于按字数估算），正文按一行一个镜头进入后续脚本 Beat；对白行「角色：台词」、画面行各占一行。`PUT .../chapters` 整表替换章节顺序与正文。项目 `settings.art_style_id` 与内容库所选画风共用导演台 `GET /api/director/art-styles` 目录，可为空。`settings.visual_style` 为 sourceXd 六项风格（默认 `chinese_period_drama`），资产生图、镜头草图/精绘和视频提示词始终写入对应风格说明；仅在选择画风时附加目录 `promptPrefix` 与预览参考图。新建项目会预填 `GET /api/xiaji/art-style` 的用户默认画风。

资产库 `xiaji_assets` 按项目隔离（唯一约束 `project_id + kind + name`），类型为 `character` / `scene` / `prop` / `voice`。角色含面部提示词、造型列表和五档声线槽位；场景含环境提示词，并按 `scene_view=master|reverse|panorama` 分别生成正面源图、背面和 2:1 的 360 全景（提示词对齐虾塘场景合同，背面/全景不覆盖正面 `image_job_id`）。生成背面时把正面源图作为 `jobs.references` 第 1 张（REFERENCE 1）；生成 360 时按顺序传入正面、已有背面。无正面源图时背面和 360 入队均 **422**。道具按 `prop_view=master|turnaround|detail` 分别生成主视图、1x3 转面三视图和细节特写（提示词与画幅对齐 sourceXd `nanobanana_prop.py`：16:9、产品摄影白底、转面为 FRONT/SIDE/BACK 三面板；工作台 GRS 分辨率用 1K。转面/特写必须已有主视图，把它作为 REFERENCE 1，且不覆盖主视图 `image_job_id`；无主视图时 **422**）。`voice` 名称为「解说」表示旁白。`POST /api/xiaji/assets/{id}/generate-image` 校验已启用 GRS 工作流后写入 `jobs` 与 `xiaji_asset_media`（`media_kind` + `slot` + `job_id`）并返回 **202** `{ ok, job_id, status: "generating", asset }`（`model` 为空则取默认启用项；请求体可带 `style` / `art_style_id`、`ethnicity`、`look_id`、`scene_view`、`prop_view`）。画风解析为请求 `art_style_id`/`style` → 资产 `definition.art_style_id` → 项目 `settings.art_style_id`；命中目录后把 `promptPrefix` 写入生图提示词，并写回资产 `art_style_id`。角色肖像还会把画风 JPEG 预览作为 `jobs.references` 第 1 张；预览加载失败则 **422**。新建资产与内容库 sync 只给空的 `art_style_id` 写入导入/项目画风，不覆盖已保存画风。旧 `visual_style` 粗粒度代码不再作为生图前缀。角色造型对齐 sourceXd 身份图：必须已有肖像并作为第 1 张参考图（身份锚点），options 为 16:9 / 1K，提示词为四面板 Identity Lock；无肖像或无服装外观描述时 **422**。造型只更新该 look 的 `job_id` 和 media 行，不覆盖肖像 `image_job_id`。请求内不提交、不等待 GRS；worker 在 `BackgroundTasks` 中 `enqueue_generation`。前端用 `GET /api/jobs/{job_id}` 查终态，再 GET 资产列表由 `_hydrate_asset` 按 media 槽位写回：`portrait`/`master` → `image_url`，`look` → 对应造型 `image_url`，分视角写入 `back_image_url` 等字段。资产生图回填按 `xiaji_asset_media` 槽位进行。`GET /api/xiaji/jobs?project_id=` 列出该项目全部任务：资产生图（肖像/造型/分视角）、镜头草图/精绘/视频，以及大模型调用（内容导入分析、生成脚本、声线定义）。生图任务含状态、提示词、参考图、options 与回调 URL；LLM 任务含系统/用户提示词、完整 `messages`、模型与采样参数、业务入参和模型输出。删除项目时同时删除 `xiaji_llm_jobs`。

## 导演台工程

导演工程与生成任务隔离，员工只能读写自己的记录。`POST /api/llm/split-script` 只即时返回分镜 JSON，不入库；前端把原文 `source_script` 与 shots 一并 `POST`/`PUT` 到 `/api/director/projects`。列表接口只返回 `has_source_script` 与 `kind`，不回传全文。手改空文案后 `PUT source_script` 仍会落盘。

`GET /api/director/art-styles` 返回 9 类 34 条画风（`id`、`name_zh`、`name_en`、`category`、`description`、`promptPrefix`、`imageUrl`、`keywords`）。`promptPrefix` 与 OpenDirector 公开种子一致。`imageUrl` 一律为同源 `/api/director/art-styles/{id}/preview`，浏览器不直连 `files.seme.cc`。`GET /api/director/art-styles/{style_id}/preview` 需要登录，优先返回本地缓存 JPEG；缺失时由服务端从 OpenDirector CDN（`style_01.jpg`–`style_34.jpg`）拉取并写入 `backend/app/director_catalog/previews/`。未知 id 返回 404。Recipe payload 的 `artStyle` 必须使用目录中的 id；保存时服务端用目录覆盖名称、`promptPrefix` 与预览地址，禁止自造风格。

`payload.kind`：缺省或旧数据为时间轴；`director_recipe` 含 `script`（title/summary/fullStory）、`artStyle`、`characters`、`locations`、`scenes[].shots`、`agentStatus`；`batch_run` 为批量主题裂变。`POST /api/director/projects/{project_id}/convert-to-recipe` 把时间轴 shots 映射为 scenes，不自动改写未请求转换的旧工程。

导演主路径不再走 `POST /api/llm/split-script`（该接口仍保留给兼容/测试，拆分时同样读取 MiniMax H3 官方 `h3-prompt-writing` 原文）。`POST /api/director/recipes/run` 顺序调用研究/脚本/画风/分镜/角色/场景/配音/配乐/媒体 9 个 Agent，复用现有 LLM Provider；可选 `agents` 只跑指定步骤（例如 `["script","storyboard"]` 按剧本一次生成全部分镜；该子集里脚本失败仍会继续拆镜，但上游余额不足/欠费会立即停止并返回 HTTP 502，`detail` 含上游原文）。分镜 Agent 必须覆盖完整剧本，通常一次输出 8–24 个独立镜头，失败时不再回退成单条「主镜头」。模型若返回 `[Shot n]` 散文也会拆成镜头。分镜 Agent 读取官方 skill 与 `base-en.txt`，同时生成中文 `description`（界面展示）和英文 `promptText`（官方镜头正文）。点击导演台左栏「镜头设计」（阶段内「设计 / 制作」切换）时，若还没有真实镜头列表，前端会自动按剧本调用上述子集。当前任务写在 `/director/:projectId?stage=`，桌面视图写在 `?view=plan|timeline`（默认方案；手机锁定方案视图），刷新与后退保持位置。桌面剪辑视图读写同一份 `director_recipe`，镜头轨与刻度直接按 `scenes[].shots[].durationSec` 铺开（不先转旧时间轴 shot），出片/静帧/配音/成片仍走现有 `render-shots` / `stills` / `tts` / `mux`，不新增 payload kind。媒体编译把 T2V/I2V 写成 `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`，把 R2V 写成 Ref2VA 六段式。画风只能选自目录。每个 Agent 开始时把 `payload.agentStatus` 写成 `running` 并落盘，因此运行中 `GET /api/director/projects/{id}` 可看到当前步；整次 POST 仍等全部 Agent 结束后才返回。`agentStatus[].message` 是给人看的阶段（例如「正在读剧本」「正在写分镜（已收到 1200 字）」「已写出 12 个镜头」），不是模型 token 或思考过程。`payload.pipelineRun` 记录本次实际跑的 `agents` 与是否仍在运行，供前端按子集计算进度（只跑 script+storyboard 时分母是 2 而不是 9）。思考模式保持关闭。导演对话走 SSE 流式读取：连接超时 20 秒，分块空闲 300 秒，完整分镜可超过原先 180 秒整段超时。分镜生成中 `agentStatus.message` 会更新为「正在写分镜（已收到 N 字）」，不回传原文。`generate-assets` 为角色和场景提交 GRS 生图任务；运行中 `GET /api/jobs` 的 `progress` 按约 2 分钟预期映射到 12–90%，完成时 100%。启用七牛云时，定妆输出会转存对象存储，任务带稳定 `cloud_url`（不含过期签名），并写入 Recipe 的 `imageUrl`；`download_url` 仍为同源 `/api/jobs/.../download`。`render-shots` 把本镜用到的定妆图编成最多 9 张 `<Picture n>` 参考图，再按 Recipe 的 `videoWorkflowFamily` 提交该族 T2V/I2V/R2V（缺省 `official_h3`；有人物/场景定妆走该族 R2V，仅有首帧/上一镜尾帧走该族 I2V，都没有走该族 T2V）；云端定妆会先拉到暂存再作为参考。配置了 LLM 时，入队前会先把镜头标为 `queued` 并调用大模型润色最终 H3 提示词，因此 `GET /api/director/projects/{id}` 在 `render-shots` 尚未返回时也能看到排队；未知 `shot_ids` 返回 422。勾选 `usePreviousEndFrame` 时编译器把上一镜 `endFrameUrl`（没有则用上一镜静帧）接到本镜首帧。`POST .../generate-stills` 复用定妆同一 GRS 通道，prompt 为本镜描述 + 画风 + 角色/场景图，结果写入 `stillJobId`/`stillUrl`。`POST .../frames` 保存首尾帧到 `data/uploads`。员工级资产库 `GET/POST /api/director/library-assets` 保存人物/场景/道具（图 + prompt），按登录用户隔离；`POST .../from-recipe` 从当前 Recipe 快照入库，`POST .../insert-library-assets` 复制进 `characters`/`locations` 并写 `libraryAssetId`。不引入系列/分集层级。`POST /api/director/batches` 把主题裂变成多条脚本并并行排队所选工作流族的文生（`video_workflow_family`，缺省官方 H3），不强制角色参考。`POST /api/director/batches/{project_id}/render` 对已有批量条目重新排队；`item_ids` 为空时提交全部条目。

导演台提交 `POST /api/jobs` 时：预览/成片各自读取工程 payload 的 `previewQuality`/`previewSpeed` 与 `finalQuality`/`finalSpeed`。默认预览 `quality=0.4`、`speed=fast`；默认成片 `quality=1.0`、`speed=balanced`。可选 MP 为 0.4 / 0.7 / 1.0 / 2.0，速度为 fast（4 步）/ balanced（8 步）/ quality（20 步）。工程级 `weightProfile`（`full` / `pruned`，默认 `full`）写入 `options.weight_profile`，预览与成片共用。旧工程无新字段时，成片 MP 仍跟 `canvasTier`，模型体积仍为完整权重。批量接龙与整段提交使用成片档。Recipe 分镜保存时始终规范化 `camera`（缺省中景前推）并保留 `error`；`POST .../render-shots` 按请求的 `render_pass` 入队，并把该档写入 `takes[].renderPass`。手改后的 `description` 进入编译 prompt（无 `promptText` 时回退 `description`）。检查器文案 Tab 的「中文镜头正文」即镜头中文 `description`（同时是静帧提示与编译回退来源），与「英文镜头正文」一一对应；`POST /api/director/recipes/{project_id}/shots/{shot_id}/translate-prompt` 用已配置 LLM 把它（或请求体 `text`；兼容字段 `promptTextZh` 优先于 `description`）按官方 skill 翻译成英文 `promptText`（对白/画面文字保留原语言、人名不翻译），只返回 `{promptText}` 由前端写回；LLM 未配置返回 503。

Recipe 第三版声音层：`payload.audio`（配乐 URL/音量/淡入淡出）、`payload.subtitles`（位置/字号/描边）、`payload.export`（mux 状态与时长）。`POST .../tts` 按分镜对白调用独立 TTS（OpenAI 兼容 `/audio/speech`，可复用 LLM 凭据），结果写入 `shots[].ttsStatus`/`ttsUrl`，不是 SQLite jobs。`POST .../mux` 只拼接失败/中断/停止之外的镜头，优先 `approvedTakeId`；本机未找到 ffmpeg/ffprobe 时返回 503。剪映草稿接口不变。`GET .../export.fcpxml` 与 `export.edl` 由镜头入出点、对白和音频轨生成。

## 作品库与媒体

### `GET /api/library`

返回完成任务的输出，并补充 `results` 中尚未写入任务记录的历史文件。每项包含 `kind`、`path`、`label`、`job_id` 与 `created_at`；历史文件的 `job_id` 为 `null`。

### `GET /api/media/{filename}`

`filename` 必须是任务 `outputs[].path` 或作品库记录的 `path`。接口仅会读取 `results` 目录下的同名文件，路径片段会被剥离，不能借此读取任意文件。

```text
http://127.0.0.1:7865/api/media/minimax_h3_20260806_120000_a1b2c3d4.mp4
```

## Apifox 导入

1. 在浏览器打开 `http://127.0.0.1:7865/api/openapi.json` 并保存为 `zly-ai-video-studio-openapi.json`。
2. 在 Apifox 新建 HTTP 项目，选择“导入 OpenAPI/Swagger”，选择该 JSON 文件。
3. 后端路由或模型变更后，重新下载并用“智能合并”导入，或让 Apifox 指向受控的 OpenAPI 文件副本。

工作台仅面向本机和可信局域网，不要使用需要 Apifox 云端服务器访问本机 URL 的自动 URL 导入方式，也不要为导入而将 API 公开到互联网。

## 账号与资源交付约定

首次访问先读取 `GET /api/auth/status`。当 `setup_required=true` 时，只能从工作站本机提交：

```json
POST /api/auth/setup
{"username":"admin","display_name":"管理员","password":"至少十位的初始密码"}
```

登录和初始化响应包含 `user` 与 `csrf_token`，并通过 `Set-Cookie` 写入会话。非浏览器客户端必须同时维护 Cookie，并在 `POST/PATCH` 请求中发送 `X-CSRF-Token`。员工接口的任务列表、单任务、参考图、作品库和输出下载都会校验 `jobs.owner_user_id`；普通员工访问其他人的资源时按不存在处理。

任务的每个 `outputs[]` 包含 `delivery_status`。只要输出尚未本地交付（`pending` 或 `cloud`），就会返回短路径 `download_url`，包括部分完成或失败但已落盘的图片；启用七牛云时另有稳定 `cloud_url`（对象域名+键，不含过期签名）。浏览器将响应体写入员工授权目录后调用：

```text
POST /api/jobs/{job_id}/outputs/{output_index}/delivered
X-CSRF-Token: <login response csrf_token>
```

回执成功后 `delivery_status` 变为 `local`，`download_url` 变为 `null`，`data/staging` 暂存和固定 ComfyUI `output` 中记录的原始输出会同时删除。ComfyUI 清理目标必须是 `type=output` 且解析路径位于固定 `Comfyui/output` 根目录，否则回执失败并保留 ZLY AI Video Studio 暂存供重试。该操作表示调用方已经可靠落盘，不可在下载开始前提前调用。未来七牛云 provider 继续使用相同任务输出状态，云端对象定位由 provider 负责，不把七牛 SDK 参数暴露到任务接口。
