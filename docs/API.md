# ZLY AI Video Studio API 文档

## 2026-09-27 v2 写稿及显式新建任务

新建 Director 写稿默认 `h3-skill-direct-v2`。冻结输入增加 `skill_revision="2.0.0"`、`validation_policy="dialogue_quotes_and_actual_references_v2"`，`skill_path` 指向 `skills/h3-director-authoring/SKILL.md`；system 是该文件完整 UTF-8 文本。既有 v1、旧完整稿合同继续按其冻结版本处理。

`POST /api/projects/{project}/episodes/{episode}/workshop/jobs/{job}/actions` 新增 `action="regenerate"`，请求沿用 `expected_revision`、`expected_reference_fingerprint`，可传当前 `writing_author`。仅支持终态 `workshop_prompt` 任务；服务端使用原任务镜头范围选择当前整组，读取当前剧本／素材，默认首次整组写稿，不继承旧原稿、返修意见或失败输入。创建新任务的 payload 保存 `regenerated_from_job_id`；返回当前 `WorkshopView`，保留原任务全部字段。在排队／运行中重复相同来源任务与请求不重复新建。镜头删除、来源过期、版本冲突及素材失效继续走现有检查。

`action="retry"` 不变：重试原冻结合同，不升级版本。生成／保存／采纳／出片对 v2 使用同一完整性策略，成对引用引号差异不改写原稿，汉字、停顿、句序和虚构参考检查保留。无表结构变化。受影响文件、验证与回滚见 [v2 实施记录](导演台纯Skill-v2正式链路对齐-2026-09-27.md)。

## 2026-09-27 工坊写稿 JSON 增量

现有 `/api/projects/{project}/episodes/{episode}/workshop` 及 prompts/actions 路径不变。新 Director 提示词任务 `payload.authoring.contracts[group_id]` 的 `version` 为 `h3-skill-direct-v1`，新增 `user`、`system_sha256`、`user_sha256`、`input_sha256`、`source_sha256`、`source`（document_id/revision/fingerprint/source_type/text）、`materials`、`material_source`、`beat_ids`、`references`、`image_hashes`、`image_hash_policy`、`revision_beat_id`、`revision_note`、`text_normalization`、`projection_policy`。`skill_text/system` 保留完整 Skill；`context_policy=full_source_no_truncation`。`image_hashes` 与 references 的 `image_locator_sha256` 哈希地址，不是图像字节；快照不新增带鉴权 URL 或 Base64 图像。

`writing_history` 保留一次调用的 raw、input、errors、origin、content_call_count；author 元数据增加 `sent_system_sha256`、`sent_user_sha256`、`sent_parameters`。失败任务保留 `rejected_groups` 原稿并报告待人工处理，不自动内容返修。新稿及采纳组保存 `contract_version`；未知版本报“未知写稿合同版本，仅允许查看”。来源缺失／冲突、超 180000 字符预算或显式 fact_extraction 请求在创建时返回既有参数错误响应，不静默截断或改换作者。旧任务重试沿用原 snapshot。详细兼容与验证见 [实施记录](导演台纯Skill实施记录-2026-09-27.md)。

## 2026-09-26：视觉能力与 VLM 复用语义

`GET /api/admin/providers/llm|vlm` 与对应 `POST .../test` 返回 `vision_capability`（`unknown/supported/unsupported`）、`vision_capability_source`、`vision_capability_checked_at`、脱敏 `vision_capability_message` 和 `supports_vision`。有效证据绑定 profile/URL/模型/凭据，有效期 24 小时；过期或连接变化后为 unknown。文本连通性成功不等于可看图；历史 `legacy_name_guess` 不授权图片。指纹和原始凭据不公开。

VLM `use_llm_credentials=true` 表示完整复用 LLM，不再仅借地址/Key：

- GET 的 `base_url`、`model`、能力与最近测试字段返回实际 LLM 值；新增 `connection_source=llm|vlm`。`profile_id` 仍标识保留的独立 VLM profile，`independent_base_url` / `independent_model` 用于恢复独立表单，不返回独立明文 Key。
- PUT 忽略复用请求中的独立地址/模型/Key，保留原独立配置，只更新 VLM 启用与复用开关。已验证同一 LLM 不重复探测；未验证时验证真实 LLM，失败返回 422 且不保存复用。并发连接变更同样拒绝旧验证结果。
- POST `/vlm/test` 在复用模式测试实际已保存的 LLM，更新其能力记录，两个设置页共享结果；失败明确报错。关闭复用时仍按独立 VLM 地址/模型/Key 工作。
- 测试未保存的独立表单输入不为已保存连接授权，响应消息明确标记“当前输入未保存”。

`GET /api/llm/status` 的 `supports_vision`、`authoring_vision` 与 `analysis_vision` 使用有效端点能力，不按模型名猜测。任务证据提供 requested/actual model、source、status、image count、request id、fallback、warning 与 decision reason；默认带图失败阻断，显式纯文本回退必须有警告。工坊指定作者契约不变。兼容、受影响文件、验证命令和回滚见 [实施记录](大模型视觉能力路由彻底修复开发计划-2026-09-26.md)。

## 2026-09-26 完整组稿与作者证据扩展

在既有 `/api/projects/{project_id}/episodes/{episode_id}` 前缀下，路由和鉴权保持不变：

- `GET /workshop` 增加 `writing_author` 与 `writing_profiles`，仅含 `profile_id`、`model`、`reasoning_effort` 这类可公开的配置字段，不返回密钥。
- `POST /workshop/prompts` 的 Director 请求可传 `writing_author: {profile_id, model, reasoning_effort}` 与 `fact_extraction: "" | "vlm"`；仍需 `expected_revision`，支持原有 `expected_reference_fingerprint`。省略作者时解析已采纳作者或当前 LLM 配置，创建时锁定实际端点和合同；不能通过请求更换凭据来源。未知图片处理模式拒绝。
- 任务 `payload.authoring.contracts[group_id]` 保存版本、完整 skill／system、skill 和剧本哈希及 `context_policy`；`writing_history[]` 保存轮次、组、输入、图像 URL、原稿、差异、问题、检查结果与 `author` 请求／响应元数据。供应商没有返回的信息为未知；无密钥。
- `payload.common_prompt_candidates[group_id]` 与 `payload.candidates[beat_id]` 是未采纳候选；`authoring.reviews`、`authoring.rejected_groups` 分别保存规则检查及较好但未通过草稿。`structure_status`、`content_status`、`semantic_status`、`media_status` 不可混为成功状态。
- `POST /workshop/jobs/{job_id}/actions` 的采纳沿用原事务与并发保护：整组公共设定和所有镜头一起提交，新增 `group_prompt_history`、正文 `contract_version/content_digest/authoring_job_id` 作为归档与保真证据。过期来源、参考、正文或锁定项变化拒绝覆盖。
- `prompt_scope=shot_revision` 仍要求单镜和返修意见；模型看完整组上下文，但公共设定及其他镜头不可修改，越权报告“需整组返修”。默认最多三次作者调用，失败证据保留，不自动提交视频。

兼容：附加 JSON 字段，旧任务继续可读，不批量补造调用元数据。受影响实现、测试命令与安全回滚见 [架构增量](ARCHITECTURE.md#2026-09-26-增量完整组稿合同与作者证据)；桌面与真实 GPT-6／视频验收尚未完成，见 [续接记录](导演台满意版效果恢复开发计划-2026-09-26.md#11-续接实施记录2026-09-26)。

## 2026-09-25 工坊参考快照扩展

v7 计划返回 `reference_fingerprint`；组返回 `reference_policy: auto | manual` 和 `reference_issues: string[]`。工坊保存、写词、任务采纳以及工坊视频创建可提交 `expected_reference_fingerprint`；资产快照变化返回 `VERSION_CONFLICT`，不覆盖旧稿。PATCH 可传 `auto_reference_group_ids: string[]` 恢复指定组自动关联。旧客户端字段可省略，原 `expected_revision` 校验继续生效。兼容及回滚见 [修复记录](工坊参考图自动关联修复-2026-09-25.md)。

## 2026-09-25 当前工坊 API

新增分集 `/workshop`、`/shot-plan`、`/workshop/prompts` 与 `/workshop/jobs/{job_id}/actions`；写入必须携带 `expected_revision`。v7 的旧 prompt-previews 与 H3 入口委托统一服务，旧方案 patch 不能写入 v7。新建全流程 AI 操作返回 410，历史任务接口保留。完整输入、候选语义、兼容性和回滚见 [统一工坊 v7 API](导演台统一工坊-v7.md#api)。

2026-09-24：HTTP 接口保持兼容。`ProjectDetailService.transfer_episodes_from_document(..., episode_num=1)` 新增可选服务层单集同步范围，指定时不替换或删除其他集，拒绝同步未规划镜头的目标集。前端在 `episode.data.script_stale` 存在时提前显示同步指引；入队前原有版本保护仍生效。

## 2026-09-24 Director v5 兼容增量

现有 `POST /api/projects/{project_id}/episodes/{episode_id}/prompt-previews`、`.../prompt-previews/{job_id}/apply`、`.../prompt-revisions`、任务查询、SSE 和重试地址不变。服务端按 `ZLY_DIRECTOR_RELIABLE` 为新 Director 请求写入 `request.pipeline_version=5`；客户端不自行决定协议版本。

任务 payload 增加 `stage_progress`（版本、来源摘要指纹、状态、尝试次数、更新时间、错误）和 `checkpoints.source_check/scene_resolution/director_design/segment_generation/structural_preview/review_dispatch`。正文逐段保存；`review_dispatch.job_id` 指向独立审稿任务。`failure` 保留 `code/stage/part_id/segment_ids/attempt/retryable/message/detail`，新版还提供 `category` 与 `resume.checkpoints/completed_segment_ids`。未知全局问题不伪装成最后一个 Part 的失败。

v5 预览 `schema_version=5`；每个 `parts[]` 附带 `render_mode: director|shot`、`workflow_id`、有序 `segment_ids`、`execution_options` 和可空的 `render_blocker`。`shot` 组仅一段，Director 组服从注册表容量；无路线可预览但不能出片。正文完成时 `quality_status=not_reviewed`；必须另存审稿通过版本后才能出片。保存仍执行来源指纹和方案版本冲突检查。

SSE 仅为显示通道。连接断开、网络 `TypeError` 或重连耗尽不能作为任务失败依据；客户端持续查询，只有持久化 `failed/cancelled/interrupted` 才显示失败。运行租约属于内部实现，不要求客户端续租。视频 `render_plan.chunks[]` 保存每组路由、graph、参数、输出、素材登记标记；重试不会重新提交已有成功输出。

受影响文件、验证命令、兼容性和回滚见 [实施记录](Director扩写稳定性-2026-09-24.md)。无 API 删除或数据库表变更。

更新日期：2026-09-20

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
| `POST` | `/api/jobs/{job_id}/upscale` | 对已成功成片提交独立超分任务。JSON 可选 `scale` 为 `2` 或 `4`，缺省 2x。 |
| `GET` | `/api/jobs` | 按创建时间倒序读取任务列表。 |
| `GET` | `/api/jobs/{job_id}` | 查询单个任务的进度、状态和输出。 |
| `POST` | `/api/jobs/{job_id}/cancel` | 停止排队中、生成中或已中断的任务。 |
| `GET` | `/api/library` | 列出当前用户已成功生成的资源元数据。 |
| `POST` | `/api/admin/providers/llm/models` | 超级管理员向上游拉取模型目录；硅基流动对照模型广场价格 0 / Free 筛选免费模型。 |
| `GET` | `/api/admin/providers/vlm` | 超级管理员读取 VLM 视觉模型配置。 |
| `PUT` | `/api/admin/providers/vlm` | 超级管理员保存 VLM 视觉模型配置。可选 `use_llm_credentials` 复用 LLM 页 Base URL / Key，模型名仍在本页。 |
| `POST` | `/api/admin/providers/vlm/test` | 测试 VLM 视觉模型连接。 |
| `POST` | `/api/admin/providers/vlm/models` | 拉取上游目录并筛选名称含 VL/Vision 的视觉模型。 |
| `GET` | `/api/vlm/status` | 查询视觉模型是否可用及当前模型名。 |
| `GET` | `/api/llm/status` | 查询文本大模型是否可用。`supports_vision` 表示写稿路径能否附图；`authoring_vision` / `analysis_vision` 分别给出写稿与反推/拉片路由。 |
| `POST` | `/api/llm/optimize-prompt` | 按工作流/H3 风格技能/可选技能包优化提示词，不创建生成任务。可选 `skill_pack_id`（须为 `GET /api/skill-packs` 中的 id）。可选 `image_urls`（最多 8 张）；解析器可看图时带图优化，否则只写张数。 |
| `GET` | `/api/skill-packs` | 列出导演台技能包配方（含空 id 的默认程序装箱，含 `summary` / `author` / `cover`）。`cover` 仅为 http(s) 地址，选择页热链播放。首页新建与项目顶栏用此列表绑定 `extra.skill_pack_id`。Plaza 短剧模板不是生成页 H3 风格芯片。 |
| `POST` | `/api/llm/analyze-subject` | 上传主体参考图提取外貌描述。默认走 VLM；VLM 未开且 LLM 可看图时回退 LLM。 |
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
| `POST` | `/api/projects` | 创建导台2项目。可选 `extra.skill_pack_id` 绑定技能包，写入 `settings_json.extra`。未知 id 返回 400。 |
| `PUT` | `/api/projects/{project_id}` | 更新导台2项目。可改 `name`。可单独提交 `extra` 合并进 `settings.extra`；只改 `settings` 时保留已有 extra。 |
| `GET` | `/api/projects/{project_id}/documents` | 列出内容库文档。`analysis.episodes[]` 含程序切集结果：`episode_num`、`body`（本集 Markdown）、`shots`（出片镜，含 `duration_sec`、`opening_state`、`closing_state`、`transition_note`）、规划成功时 `shots_source=llm`。进行中的镜头规划带 `shot_plan_job_id`，文档 `status` 为 `planning`。导入后未确认画幅时 `status` 为 `awaiting_aspect`，并带 `aspect_hint`（`suggested` / `hits` / `conflicts`）。 |
| `POST` | `/api/projects/{project_id}/documents` | 导入或粘贴剧本文档。JSON：`raw_text`，可选 `filename` / `spine_template` / `visual_style` / `input_mode`（缺省 `paste`）。程序按 `# 第N集` 切集（不改集号），每集写入 `body` 后立刻返回 200，**不**自动入队 `shot_plan`。需要规划时文档 `status=awaiting_aspect`，响应带 `aspect_hint` 与 `needs_shot_plan`。`input_mode=ai_pipeline` 不规划。工程名仍为默认「未命名导演工程」时按文档名或剧目标题自动改名，响应可带 `project_name`。 |
| `POST` | `/api/projects/{project_id}/documents/{doc_id}/shot-plan` | 确认成片画幅后入队 `shot_plan`。JSON 可选 `aspect_ratio`，写入 `settings.extra.workshop_aspect_ratio` 并作为规划权威画幅。JSON 可选 `force: true` 覆盖已 `shots_source=llm` 的出片镜（不删工坊 Take）。**202** 返回 `job_id`。AI 流水线返回 400；未 `force` 且已全部 `shots_source=llm` 仍 400；已有进行中任务返回原 `job_id` 并标 `duplicate`。 |
| `GET` | `/api/projects/{project_id}/jobs` | 列出项目任务，含 `image_generation` / `video_generation` / `h3_prompt` / `shot_plan` / `ai_pipeline` / `tts_generation`。列表 `payload` 只保留工坊/表格需要的字段（镜号、状态、结果 URL、精简 `shots`/`stream`），不含草稿、`request_body`、原始 `payload_json`。`shot_plan` 的 `payload.document_id` 用于跳回内容库该文档。 |
| `GET` | `/api/projects/{project_id}/jobs/{job_id}` | 读取单条任务的完整 `payload`（含草稿、提示词、`request_body`）。不存在 **404**。 |
| `GET` | `/api/voice-bank` | 读取内置短剧配音声线目录（IndexTTS 官方示例）。 |
| `GET` | `/api/voice-bank/{preset_id}/audio` | 读取内置声线 wav。未知 id **404**。 |
| `POST` | `/api/projects/{project_id}/assets/{asset_id}/generate` | 资产生图。JSON `target_type`：`identity` 为角色设定板（16:9、2K、`2048x1152`），不要求已有头像；无外观描述且无原片参考图时 **400**。无原片/旧设定板/头像时按纯文生图提交（prompt 标明 text-to-image，不写未附图或改图）。参考图顺序：原片 > 其他已出图造型（排除当前 look）> 仅当两档都没有时才用旧 `avatar_url`。`prop_reference` 为道具设定板（同样 16:9、2K、`2048x1152`）；无外观描述且无原片 **400**；无原片时 prompt 标明 text-to-image。`prop_turnaround` / `prop_detail` 仍可用但不在界面露出。`avatar` 仍可用但不在界面露出。头像 / 场景分辨率仍为 1K。 |
| `POST` | `/api/projects/{project_id}/assets/{asset_id}/voice` | multipart 上传角色参考音，写入 `extra.voice.ref_audio_url`。非角色或空文件 400。 |
| `POST` | `/api/projects/{project_id}/assets/{asset_id}/voice/preset` | JSON `{ preset_id }` 绑定内置短剧声线。未知 id 400。 |
| `DELETE` | `/api/projects/{project_id}/assets/{asset_id}/voice` | 清除角色参考音。 |
| `POST` | `/api/projects/{project_id}/assets/{asset_id}/voice/preview` | 用当前声线合成试听，写入 `extra.voice.preview_url`。 |
| `GET` | `/api/projects/{project_id}/assets/{asset_id}/voice/extract-sources` | 列出该角色有开口对白且已有 H3 原片 `video_url` 的镜头（`episode_id` / `beat_id` / `seq` / `line_preview` / `duration_sec` / `video_url`）。只读解析 `data_json`，不回写 beats。非角色 400。 |
| `POST` | `/api/projects/{project_id}/assets/{asset_id}/voice/extract` | JSON `{ episode_id, beat_id, start_sec, end_sec }`。按用户框选的 1–15 秒从该镜 H3 原片抽 16 kHz mono wav，写入 `extra.voice.ref_audio_url`，清空 `preset_id`，记录 `source`。同步、不入队。缺区间 / 过短 / 过长 / 越界 / 无开口 / 无原片 / 无音轨 / 缺 ffmpeg **400**。 |
| `GET` | `/api/projects/{project_id}/episodes/{episode_id}/dubbing` | 读取本集台词轨（从 Beat 对白展开，合并已持久化的 `dubbing_lines`）。另含 `compose_blocked` / `compose_block_reason`：绑定半解说包时旁白未配音则合成禁用。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/dubbing/sync` | 从分镜同步台词轨并写回 `beats[].dubbing_lines`。 |
| `PATCH` | `/api/projects/{project_id}/episodes/{episode_id}/dubbing/lines/{line_id}` | 更新单句文本/情绪/强度/语速/混音。改文本会清空已生成音频。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/dubbing/generate` | 单句或批量入队 `tts_generation`。JSON 可选 `line_id` / `line_ids`；缺省生成本集全部。**202** 返回 `job_id`。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/generate-video` | 按工作流入队整集或逐镜视频。最终 R2V 只上传本镜角色设定板与绑定道具设定板，角色优先、最多 9 张；场景卡、三联母图与三张裁切格仅供写稿，不上传视频模型，零参考镜头走 T2V。入队时按本镜时代写入 `character_look_ids`。JSON 可带注册表 options，含 `upscale_after=off\|2\|4`。仅逐镜/选中镜会在原片写入后自动按选定倍数超分；整集直出不自动超分。**202** 返回 `job_id`。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-video` | 单镜入队。R2V 顺序同上。可带 `upscale_after`；超分失败仍保留原片。成功后原片写入 `video_url` 并归档到 `video_takes`（默认采用最新）。**202**。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/compose` | 拼接各镜 `video_url` 为分集成片。JSON 可选 `mix_dubbing`（缺省 true）：内心/旁白叠到对应镜，`mix=replace` 的开口句静音该镜 H3 原声。半解说包旁白未配音 **400**。**202** 返回 `job_id`。不因 `upscale_after` 自动超分。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/video-takes/adopt` | 采用本镜一条成功成片为正式原片。JSON `{ url }` 或 `{ job_id }`。校验确属本镜 `shot`/`selection` 成功抽卡后写 `video_url`；该 Take 已有 2x 则同步 `upscaled_video_url`，否则清空。采用的那条留在 `video_takes`。不属于本镜 **400**。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/upscale` | 对本镜已成功成片提交独立超分。JSON 可选 `scale` 为 `2` 或 `4`，缺省 2x。原片 `video_url` 不变，结果写入 `upscaled_video_url` 并挂到当前采用 Take，超分不单独成 Take。进行中任务 **409**；无成片或相对当前连接 GPU 显存预估过大 **422**。**202** 返回 `job_id`。 |
| `POST` | `/api/projects/{project_id}/jobs/{job_id}/upscale` | 对导演台2「全部任务」里已成功的视频生成任务提交超分。JSON 可选 `scale` 为 `2` 或 `4`，缺省 2x。用该任务 `result_url` 作原片；有关联单镜则写回 Beat。超分任务本身 / 未完成 / 多镜 selection **422**；同一成片进行中超分 **409**；相对当前连接 GPU 显存过大 **422**。整集直出和拼接片可手动点，过长可能被拒绝。**202**。 |
| `POST` | `/api/projects/{project_id}/documents/{doc_id}/transfer-episodes` | 把内容库该文档的分集/出片镜头写入剧集工坊。JSON `{ mode }`：`overwrite`（缺省）按本剧本重写已有集的 `data_json.beats` 并删除剧本里没有的旧集；`append` 跳过已有集号只补新集。只拷贝文档里已有的出片镜，同步时不再调大模型规划。成功返回 `mode`、`replaced_episodes`、`created_episodes`、`skipped_episodes`、`deleted_episodes`、`transferred_shots`。未知 mode 或未识别到分集返回 400。 |
| `PUT` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}` | 更新单条 Beat。可写 `h3_prompt` 与 `h3_prompt_source`（`manual` / `generated`），以及 `timestamped_zh_prompt`。手动保存的六段出片按原文使用。服务端可写 `video_takes`；前端选用成片请走 `…/video-takes/adopt`，不要直接改 `video_url`。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/h3-prompt` | 剧集工坊素材组：为当前分镜入队 **一个** `h3_prompt` 任务，不再按口型/内心/近景规则拆镜。JSON 可选 `aspect_ratio`，写入 `beat_info` 作为写稿权威画幅（否则读 `extra.workshop_aspect_ratio` / 配方缺省）。未绑技能包时程序从本镜动作/运镜/台词编译六段 Ref2VA。绑定半解说包时由 LLM 一次写出中文八块分秒稿（时间码从本镜 `00:00` 起；可看图时看角色卡/场景卡/整张三联）和英文六段；配方临时 `skip_program_pack=true` 时出片英文用 GPT 六段原文（规范化 `<Picture>` / `<Subject>`、六段 `name:` 标题，并在 `detailed_description` 补 `[Shot 1]`；内心改成官方 `says in an off-screen voiceover` 且 `</d>` 后闭嘴），不再程序灌水、中文时间码或轿厢句，也不走第二次装箱 LLM；写稿合同写清开口 / 角色内心 / 第三人称旁白三通道与编号表演顺序，无旁白时禁止用内心或开口句充数，也不再把内心折进旁白原文交给模型；内心挂在触发画面时段，表演顺序第 1 句不是内心时禁止写在 00:00 起幅；中文分秒接受小数时间码与标题首字乱码，英文 `<d>` 可省略 `[Chinese]`；同一人连续多句按问号/句号切开后逐字校验；内心口型同步 `says:` 会先修补再校验；半解说包另校验台词去重与 `<d>` 表演顺序；中文分秒仍写入 `timestamped_zh_prompt`。说明句 stub（例如只回「官方八块中文分秒稿与」）会打回重写，失败文案不再展开缺标题清单。看图写作对 GPT-5 / o 使用管理设置保存的 `reasoning_effort`（默认 `low`，`auto` 时不发送）、`max_tokens=16000`。中文或英文未通过校验则任务 `failed`，`payload` 含 `author_errors` / `vision_*` / `author_raw_draft` 与残稿，不覆盖 Beat，不回退无时间码骨架。R2V 参考图为角色设定板 + 场景卡 + 有绑定则道具设定板（占满 9 槽剩余位，不硬限 2 张）+ 三联起幅/中格/结果三张成片画幅构图（不送整张三联）。设定板只锁身份/发型/服装，道具设定板只锁外形与材质并覆盖场景卡同名陈设，禁止把分格、白底、重复小人/小物件带进镜头。工坊若已有拆开的出片镜，`payload.merge_as_one=true` 则合并回一条再生成。`h3_prompt_source=manual` 的镜按原文出片。**202** 返回 `job_id`。生成过程可通过 `GET /api/projects/{project_id}/jobs/{job_id}/events` 直播思考与正文。 |
| `GET` | `/api/projects/{project_id}/jobs/{job_id}/events` | 按 `job_type` 订阅任务 SSE。`h3_prompt`：`status` / `reasoning` / `delta` / `done` / `error`。`shot_plan`：另有 `episode_done`（该集 `shots` 已写入 `analysis_json`），`status` 含第几集/共几集。可用 `since` 或 `Last-Event-ID` 续传。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-triptych` | 为当前分镜入队 16:9 三联关键帧母图（内部三等分裁切，默认 2K）。JSON 可选 `aspect_ratio`，写入提示词里的成片画幅构图标签。参考图为时代匹配的造型设定板 + 场景卡 + 本镜道具设定板（占满 9 槽剩余位）；已有造型图时不再追加 `avatar_url`，缺对应时代造型则拒绝入队。完成后写入 `triptych_url` 与 `triptych_look_ids`，裁切起幅/中格/结果到 `triptych_panels.start|mid|end` 供本地 H3 素材组使用；整张三联不作为 `<Picture n>`。**202** 返回 `job_id`。 |
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
| `POST` | `/api/director/hypit/{project_id}/source-video` | 上传 Hypit 复刻参考片（与 VACE 复刻台分离）。 |
| `GET` | `/api/director/hypit/{project_id}/source` | 读取 Hypit 复刻参考片。 |
| `GET` | `/api/director/hypit/{project_id}/transcript` | 读取本机 WhisperX 转写 JSON。 |
| `GET` | `/api/director/hypit/{project_id}/result` | 读取 Hypit 编译成片。 |
| `POST` | `/api/director/hypit/{project_id}/reveal` | 打开本机 `data/hypit/{user}/{project}` 工程目录。 |
| `POST` | `/api/director/hypit/{project_id}/operations` | `hypit_transcribe` 拉片或 `hypit_compile` 编译；不接受 VACE 操作。H3 画面默认 `http://192.168.10.54:8188`（`hypit.runtime.json` / `ZLY_HYPIT_COMFY_URL`），与工作台本机 Comfy 分离。 |
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

### `POST /api/jobs/{job_id}/upscale`

对已成功的视频成片新建独立 `nvidia-rtx-vsr` 任务（2x 或 4x / ULTRA，一次到位）。JSON 可选 `{ "scale": 2 }` 或 `{ "scale": 4 }`，缺省 2x。原片任务不变；超分结果是新任务的输出。同一原片已有排队中、生成中或已中断的超分时返回 `409`。按原片宽×高×帧数×选定倍数预估显存，与当前连接 ComfyUI `/system_stats` 的总显存比较，过大时返回 `422`（读不到显存则不编造限额）。当前连接的 ComfyUI 若未安装 `RTXVideoSuperResolution`（包名 `Nvidia_RTX_Nodes_ComfyUI`，需 `nvidia-vfx==0.1.0.1`）也返回 `422`。不要通过 `POST /api/jobs` 直接创建 `nvidia-rtx-vsr`（该工作流 `hidden_from_catalog`）。H3 系列也可在创建时把 `options.upscale_after` 设为 `"2"` 或 `"4"`（旧布尔 `true` 视为 2x），成片成功后同一任务会先 `POST /free` 再接跑超分，失败仍保留原片。

```powershell
Invoke-RestMethod -Method Post `
  -Headers @{"X-CSRF-Token" = "<login response csrf_token>"; "Content-Type" = "application/json"} `
  -Body '{"scale":2}' `
  http://127.0.0.1:7865/api/jobs/WvhSEuCWne1d/upscale
```

## 导台2 项目内容库（`/api/projects`）

导演台2 内容库走 `POST /api/projects/{project_id}/documents`，不是 `/api/xiaji/documents`。集边界只认台本 `# 第N集`（无集头则整篇第 1 集）；剧本里的 `### 镜头` 只当素材。粘贴/文件导入立刻落库并扫描 `aspect_hint`，文档 `status=awaiting_aspect`，**不**自动入队 `shot_plan`。确认成片画幅后 `POST …/documents/{doc_id}/shot-plan`（JSON 可选 `aspect_ratio`，可选 `force: true` 覆盖已规划镜头）写入 `settings.extra.workshop_aspect_ratio` 再逐集规划（H3 合同 5–15 秒，写入 `opening_state` / `closing_state` / `transition_note`），成功则 `shots_source=llm`。规划 prompt 以确认画幅为权威。过程通过 `GET …/jobs/{job_id}/events` 直播；内容库按集显示瘦进度，当前集用残缺 JSON 解析出的镜头卡逐张出现（思考默认折叠，不展示 JSON），`episode_done` 后换成归一化结果，规划中禁止同步工坊。全部任务有「镜头规划」Tab，可按 `payload.document_id` 跳回 `/director2/projects/:id/content?mode=manual&doc=:docId&tab=episodes`。AI 流水线回写的文档（`input_mode=ai_pipeline`）不二次规划。未 `force` 且已全部 `shots_source=llm` 仍 400。`POST …/transfer-episodes` 把文档已有出片镜写入剧集工坊，同步时不再调大模型规划。`POST …/h3-prompt` 点哪条入队一个任务，按 `sequence` 填 `previous_shot`（落幅姿势 + 切型），不再按口型/内心/近景规则改镜头列表。工坊 `POST …/generate-video` 可带 `options.upscale_after=off|2|4`：仅逐镜/选中镜在原片写入后自动按选定倍数超分；整集直出和 `POST …/compose` 不自动超分。逐镜/选中镜成功后把旧原片归档进 `video_takes`，`video_url` 默认采用最新；成片 Tab 用 `POST …/beats/{beat_id}/video-takes/adopt` 选用历史抽卡。已出片镜头可 `POST …/beats/{beat_id}/upscale`（JSON 可选 `scale`），结果写入 `upscaled_video_url` 并挂到当前采用 Take。全部任务已成功视频可 `POST …/jobs/{job_id}/upscale`（同样可选 `scale`）。

## 导台2 内容库与资产库

导台2 以项目为容器。先 `POST /api/xiaji/projects` 再建内容库和资产。列表、上传、粘贴、同步、新建资产均需 query `project_id`，且项目必须属于当前登录用户。文稿与章节按项目隔离。`POST /api/xiaji/documents` 为 `multipart/form-data`（`file` 必填，可选 `title`、`art_style_id`、`replace`）。`POST /api/xiaji/documents/paste` 为 JSON（`text` 必填，可选 `title`、`art_style_id`、`replace`）。`replace=true` 时先清空本项目内容库、资产、剧集和大模型任务，再写入新文稿。二者都同步规则切分章节、调用已配置 LLM 分析，并在成功后写入**同一项目**的资产库。无章节标题时整篇为一章且状态为 `review_required`，否则 `indexed`/`ready`。精品剧识别「第X集 / Episode N」为剧集边界（与「第N段」相同，优先于按字数估算），正文按一行一个镜头进入后续脚本 Beat；对白行「角色：台词」、画面行各占一行。`PUT .../chapters` 整表替换章节顺序与正文。项目 `settings.art_style_id` 与内容库所选画风共用导演台 `GET /api/director/art-styles` 目录，可为空。`settings.visual_style` 为 sourceXd 六项风格（默认 `chinese_period_drama`），资产生图、镜头草图/精绘和视频提示词始终写入对应风格说明；仅在选择画风时附加目录 `promptPrefix` 与预览参考图。新建项目会预填 `GET /api/xiaji/art-style` 的用户默认画风。

资产库 `xiaji_assets` 按项目隔离（唯一约束 `project_id + kind + name`），类型为 `character` / `scene` / `prop` / `voice`。角色含面部提示词、造型列表和五档声线槽位；场景含环境提示词，并按 `scene_view=master|reverse|panorama` 分别生成正面源图、背面和 2:1 的 360 全景（提示词对齐虾塘场景合同，背面/全景不覆盖正面 `image_job_id`）。生成背面时把正面源图作为 `jobs.references` 第 1 张（REFERENCE 1）；生成 360 时按顺序传入正面、已有背面。无正面源图时背面和 360 入队均 **422**。道具按 `prop_view=master|turnaround|detail` 分别生成主视图、1x3 转面三视图和细节特写（提示词与画幅对齐 sourceXd `nanobanana_prop.py`：16:9、产品摄影白底、转面为 FRONT/SIDE/BACK 三面板；工作台 GRS 分辨率用 1K。转面/特写必须已有主视图，把它作为 REFERENCE 1，且不覆盖主视图 `image_job_id`；无主视图时 **422**）。`voice` 名称为「解说」表示旁白。`POST /api/xiaji/assets/{id}/generate-image` 校验已启用 GRS 工作流后写入 `jobs` 与 `xiaji_asset_media`（`media_kind` + `slot` + `job_id`）并返回 **202** `{ ok, job_id, status: "generating", asset }`（`model` 为空则取默认启用项；请求体可带 `style` / `art_style_id`、`ethnicity`、`look_id`、`scene_view`、`prop_view`）。画风解析为请求 `art_style_id`/`style` → 资产 `definition.art_style_id` → 项目 `settings.art_style_id`；命中目录后把 `promptPrefix` 写入生图提示词，并写回资产 `art_style_id`。角色肖像还会把画风 JPEG 预览作为 `jobs.references` 第 1 张；预览加载失败则 **422**。新建资产与内容库 sync 只给空的 `art_style_id` 写入导入/项目画风，不覆盖已保存画风。旧 `visual_style` 粗粒度代码不再作为生图前缀。角色造型对齐 sourceXd 身份图：必须已有肖像并作为第 1 张参考图（身份锚点），options 为 16:9 / 1K，提示词为四面板 Identity Lock；无肖像或无服装外观描述时 **422**。造型只更新该 look 的 `job_id` 和 media 行，不覆盖肖像 `image_job_id`。请求内不提交、不等待 GRS；worker 在 `BackgroundTasks` 中 `enqueue_generation`。前端用 `GET /api/jobs/{job_id}` 查终态，再 GET 资产列表由 `_hydrate_asset` 按 media 槽位写回：`portrait`/`master` → `image_url`，`look` → 对应造型 `image_url`，分视角写入 `back_image_url` 等字段。资产生图回填按 `xiaji_asset_media` 槽位进行。`GET /api/xiaji/jobs?project_id=` 列出该项目全部任务：资产生图（肖像/造型/分视角）、镜头草图/精绘/视频，以及大模型调用（内容导入分析、生成脚本、声线定义）。生图任务含状态、提示词、参考图、options 与回调 URL；LLM 任务含系统/用户提示词、完整 `messages`、模型与采样参数、业务入参和模型输出。删除项目时同时删除 `xiaji_llm_jobs`。

## 导演台工程

导演工程与生成任务隔离，员工只能读写自己的记录。`POST /api/llm/split-script` 只即时返回分镜 JSON，不入库；前端把原文 `source_script` 与 shots 一并 `POST`/`PUT` 到 `/api/director/projects`。列表接口只返回 `has_source_script` 与 `kind`，不回传全文。手改空文案后 `PUT source_script` 仍会落盘。

`GET /api/director/art-styles` 返回 9 类 34 条画风（`id`、`name_zh`、`name_en`、`category`、`description`、`promptPrefix`、`imageUrl`、`keywords`）。`promptPrefix` 与 OpenDirector 公开种子一致。`imageUrl` 一律为同源 `/api/director/art-styles/{id}/preview`，浏览器不直连 `files.seme.cc`。`GET /api/director/art-styles/{style_id}/preview` 需要登录，优先返回本地缓存 JPEG；缺失时由服务端从 OpenDirector CDN（`style_01.jpg`–`style_34.jpg`）拉取并写入 `backend/app/director_catalog/previews/`。未知 id 返回 404。Recipe payload 的 `artStyle` 必须使用目录中的 id；保存时服务端用目录覆盖名称、`promptPrefix` 与预览地址，禁止自造风格。

`payload.kind`：缺省或旧数据为时间轴；`director_recipe` 含 `script`（title/summary/fullStory）、`artStyle`、`characters`、`locations`、`scenes[].shots`、`agentStatus`；`batch_run` 为批量主题裂变；`shot_replication` 为 VACE 参考片复刻；`hypit_replication` 为 Hypit 结构复刻（与 VACE 并列，不混 payload）。`POST /api/director/projects/{project_id}/convert-to-recipe` 把时间轴 shots 映射为 scenes，不自动改写未请求转换的旧工程。

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

## 动作与镜头编排 API（2026-09-23）

项目接口使用现有登录会话和变更请求的 `X-CSRF-Token`：

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/projects/{p}/episodes/{e}/beats/{b}/action-previs` | multipart `description`、`images[]`（最多四张）、可选 `video`；返回 202 与 `job_id`。镜头时长须 2–15 秒。 |
| `GET /api/projects/{p}/episodes/{e}/beats/{b}/action-previs/latest` | 当前镜头最新任务或 null。 |
| `GET /api/projects/{p}/action-previs/{job_id}` | 任务状态、方案版本、质量与产物。 |
| `PUT /api/projects/{p}/action-previs/{job_id}/plan` | `{plan,expected_revision}`；只允许 `awaiting_review`，版本冲突 409。 |
| `POST /api/projects/{p}/action-previs/{job_id}/render` | `{expected_revision}`；锁定已审稿版本并排队远端。 |
| `POST /api/projects/{p}/action-previs/{job_id}/cancel` / `retry` | 取消或按已审方案重试失败/需返修任务。 |

远端执行器使用独立 Bearer `ZLY_ACTION_PREVIS_WORKER_TOKEN`，通过 `POST /api/internal/action-previs/claim` 主动领取，`POST /{p}/{job_id}/heartbeat` 续租，`PUT /{p}/{job_id}/artifacts/{video|blend|contact_sheet|report}` 上传四种产物，再 `POST /{p}/{job_id}/complete` 回传质量报告；异常走 `fail`。后续接口前缀均为 `/api/internal/action-previs`。产物上传须带 `X-Action-Lease`，其他任务操作 body 须带 `lease_token`。旧租约无法覆盖新任务，取消后回传被拒绝。工作台不会把 LLM 生成的代码发送给 Blender。

动作方案 `version=1`、`fps=24`，包含 `frame_count`、`actors[A,B]`、连续无重叠的 `beats[{start,end,description,actions,contact}]` 和 `shots[{start,end,size,angle,move,subject,lens_mm}]`；帧 `end` 为开区间。完整枚举和约束以 `action_previs_schema.py` 为准。

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
# 2026-09-27 写稿合同 v3

现有工坊写稿 API 新建默认 `h3-skill-direct-v3`，`validation_policy=execution_only_v3`、`skill_revision=original`，system 为原始 Skill 全文。review 保留 `semantic_status=pending_human`、`media_status=not_reviewed`，无自动创作问题列表；并非对白质量通过。旧合同不迁移，regenerate 用当前来源新建 v3。请求路径和鉴权不变。[完整边界](导演台原始Skill执行校验-v3-2026-09-27.md)。
## 2026-09-28 可选二次 AI 审校

`POST /api/projects/{project}/episodes/{episode}/workshop/prompts` 新增 `review_enabled: boolean`（默认 false）、`review_author: {profile_id, model, reasoning_effort}`。仅整组 Director 写稿支持，单镜返修请求开启时返回参数错误。供应商地址由服务端配置解析，调用者提供的凭据不落库。

`POST .../workshop/jobs/{job}/actions` 新增 `action="review"`：携带 `expected_revision`、`expected_reference_fingerprint`、可选整组 `beat_ids` 和 `review_author`。只重跑审校，不重写作者稿；复用相同原稿/输入/Skill/模型配置的成功结果，失败可显式重试。模型配置变化会形成新审校证据，旧证据进入 `ai_review_history`。

`action="apply"` 新增 `version="original"|"reviewed"`，缺省 original。审校稿必须终态且 eligible；取消/审校失败仍允许采纳完整合法原稿。原稿 `candidates` 与 `common_prompt_candidates` 永不被审校替换；服务端只在采纳事务内使用审校版本投影。返回 `ai_reviews[group_id]` 的 status/result/issues/changes/diff/errors/eligible 与调用证据。status 为 running/unchanged/revised/needs_user_resolution/failed/cancelled；`media_status` 保持 not_reviewed。

本节更新覆盖历史文档中“不新增 Base64 图像”的旧限制：开启审校的新任务在作者调用证据保存冻结实际图像及 SHA-256；既有任务不回填伪造历史内容哈希。

整组写稿设置新增默认关闭的「二次审校」及独立审校模型。第一阶段仍使用原始 H3 Skill / h3-skill-direct-v3；第一稿持久化后，独立 h3-dialogue-review-v1 只调用一次，返回问题、理由与完整稿。审校失败保留原稿；可独立审校已有整组候选或重试失败审校，不重写第一稿。候选面板提供原稿、审校稿、实际差异、证据以及明确的整组版本采纳，正文和公共设定在现有事务内一起更新。模型审校不等同成片验收，也不自动出片。

- 原因：识别虚构参考音频、发声要求冲突与对白拥挤等语义风险，保留创作者选择。
- 受影响文件：`skills/h3-dialogue-review/SKILL.md`、`workshop_ai_review.py`、`workshop_service.py`、`workshop_group_prompts.py`、`llm_service.py`、`llm_image_transport.py`、`UnifiedWorkshopPane.tsx`、`WorkshopPromptCandidates.tsx`、`workshop-api.ts` 及对应测试。
- 兼容性：任务 payload 增加可选 `review_config`、`ai_reviews`、`ai_review_history`、`adopted_versions`、`run_id`，无新表、端口、ComfyUI 节点或实例变化。旧任务缺字段视为未开启。开启的新任务冻结实际发送图片与内容哈希供两阶段共用；旧任务无法回溯当时图像字节，界面明确提示该证据限制。失败、取消及新执行的迟到响应受状态和执行标识保护。
- 验证命令：`python -X utf8 -m unittest discover -s backend/tests -q`、`pnpm --dir frontend build`、`git diff --check`。真实成片效果与工程验证分开记录，详见 `docs/导演台二次AI审校实施记录-2026-09-28.md`。
- 回滚：关闭二次审校或停用新入口；回退上述代码时保留任务 payload、原稿、审校证据及媒体。不得通过删除任务回滚。默认值是否开启由后续对照验收决定。
## 2026-09-28 H3 确认后二采

新增创作任务 `/api/jobs/{job_id}/refine` 与导演任务 `/api/projects/{project_id}/jobs/{job_id}/refine`：GET 读取来源与版本列表；POST 携带 `refine_quality`（1/2）、`source_revision`、`request_id` 创建幂等子任务。来源冲突为 409，阶段、参数或实例不符为 422。原片任务不变。

`POST .../refine/preview` 明确新建一采，导演台 `POST .../refine/cancel` 取消二采；创作页取消及两侧失败重试沿用已有 cancel/retry。写接口沿用会话与 CSRF。完整协议、限制与回滚见 [接入记录](H3确认后二采业务接入-2026-09-28.md)；未通过桌面验收前新目录入口保持隐藏。
