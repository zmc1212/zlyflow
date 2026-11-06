# ZLY AI Video Studio API 文档

## 2026-11-06 删除任务级联清理云端产物

- `DELETE /api/jobs/{job_id}` 仍使用登录会话、归属校验与 `X-CSRF-Token`，成功返回 `200 {"id":"..."}`。删除前聚合任务镜像、全部轮次/生成项及二采预览中的云端输出，按 key 去重，清理成功后才提交任务与轮次记录的删除。
- `409`：任务或生成项仍排队/运行；媒体被其他任务、导演资产、画布（含历史版本）、智能剪辑、精选或灵感示例引用；当前非七牛存储、历史产物缺少稳定云 URL，或 URL 与当前存储不匹配。此时不删除任何对象或记录，不自动切换供应商。
- `502`：七牛删除失败，保留任务记录与 key 供重试；先前成功清理的对象不能回滚。七牛 `612`（对象不存在）视为成功，因此可重试完成。鉴权失败仍为 `401/403/404`。
- 本地下载、上传参考素材、ComfyUI 原始文件不清理；不追溯清理此前已删除任务留下的孤儿对象。引用检查按现有持久化媒体字段执行，不是全库自动垃圾回收。
- 实现、验证命令、并发边界与回滚见 `docs/ARCHITECTURE.md` 同日「删除任务级联清理云端产物」章节；无需表结构迁移。

## 2026-11-06 GRS 生图模型消耗积分与能力描述

- 变更原因：GRS 只在价目接口里给出每个模型的单次消耗积分，创作页此前既不显示价格，下拉也只有一行模型名；同时目录里历史入库的描述长句（「使用 GRS GPT Image 2.5 生成图片…」）会把平台已有的 `gpt-image-2.6` 写成 2.5，描述与实际能力（直出 GIF）对不上。
- 上游接口（非本工作台 API）：`POST {base_url}/client/openapi/getModelList`，请求体 `{"apiKey": "..."}`，响应 `data.list[]` 每项 `{ name, type, cost, costType, group, ... }`；`GrsClient.model_costs()` 只取 `type == "image"` 的行，返回 `{ provider_model: 单次积分 }`，`code != 0`、缺 `data.list` 或非正整数 `cost` 分别按 `GrsError` / 跳过处理。
- `GET /api/modes`：生图条目新增 `credit_cost`（`ModeResponse` 显式声明，整数 = 平台标价积分/张；价格接口失败或该模型未标价时为 `null`）。**纯展示字段，不进入 `POST /api/jobs` 的提交参数**。
- `GET /api/admin/providers/grs/models`：`models[]` 每项新增 `credit_cost`（同上，可为 `null`）；`description` 改为「当前能力文案」——库里存的是历史自动长句或空串时由后端按能力档现算，管理员自己写过的描述原样返回。
- `POST /api/admin/providers/grs/models/fetch`：`models[]` 每项新增 `credit_cost`（本次价目快照，取不到时回落库里旧值）与 `description`（同上口径）。
- `POST /api/admin/providers/grs/models/import`：请求体每项可选 `description`（≤200 字）与 `credit_cost`（1–100000）；省略时分别取平台条目文案与本次价目快照。入库后强制刷新一次价目（`refresh_model_costs(force=True)`），保证新行立刻带上标价。
- `PUT /api/admin/providers/grs/models`：不变，仍只更新 `display_name`/`enabled`/`sort_order`/`is_default`，因此保存顺序不会冲掉 `credit_cost`。
- 数据：`grs_image_models` 新增 `credit_cost INTEGER NULL`，走 `storage.ensure_column`（共享库，不写一次性 ALTER）。积分刷新随余额快照限频 6 小时（`GRS_COSTS_REFRESH_SECONDS`），上游失败静默保留旧值，绝不阻塞出图。
- 兼容性：`credit_cost` 为增量只读字段，旧客户端忽略即可；未配置 GRS Key、离线部署或价目接口下线时字段为 `null`，界面显示「未取到」而不是 0。能力文案的唯一来源改为 `grs_catalog.PROFILE_CAPABILITIES` / `MODEL_CAPABILITY_NOTES`，`PROFILE_DESCRIPTIONS` 已删除，其历史文本保留在 `LEGACY_AUTO_DESCRIPTIONS` 中仅用于识别「这不是管理员自己写的」。
- 受影响文件：`backend/app/{grs_client,grs_catalog,grs_provider,storage,workflow_registry,models,api_documentation}.py`、`frontend/src/{App.tsx,index.css,admin/GrsProviderSettings.tsx}`、`backend/tests/test_grs_model_costs.py`。
- 验证与回滚见 `docs/ARCHITECTURE.md` 与《功能说明与扩展指南》同日章节。

## 2026-11-06 GRS 生图目录排序与「默认模型」解耦

- 变更原因：`sort_order` 与 `is_default` 此前共同决定创作页生图列表顺序（默认模型被钉在首位），管理员无法自定义显示顺序。现在 `sort_order` 是唯一显示键，`is_default` 只是标记。
- `GET /api/modes`：生图条目新增布尔字段 `is_default`（`ModeResponse` 显式声明，未标记为 `false`）。列表顺序 = 目录中 `enabled` 行按 `(sort_order, display_name)` 的顺序，**不再保证默认模型在首位**；需要「默认模型」的消费方必须读 `is_default`。响应其余字段与视频工作流不变。
- `GET /api/admin/providers/grs/models`：`models` 数组改为严格按 `sort_order ASC, display_name ASC` 返回（此前默认行会被排到最前）。每项字段不变，含 `sort_order`、`is_default`、`builtin`。
- `PUT /api/admin/providers/grs/models`：请求体与语义不变（整份目录 `{ models: [...] }`，只更新 `display_name`/`enabled`/`sort_order`/`is_default`，未知 `workflow_id` **409**），审计仍为 `update_grs_image_models`。管理后台拖动行首手柄即重写密集 `sort_order`（10、20、30…）后调用本接口保存；若请求里没有任何 `is_default=true`，服务端仍把第一个启用行设为默认（原兜底逻辑保留）。
- `POST /api/admin/providers/grs/models`（手填）与 `POST …/models/import`（平台导入）：新增行在未显式传 `sort_order` 时取 `MAX(sort_order)+10` 追加到目录末尾，不再固定为 300，避免与已有行同序号后按显示名乱序。其余校验与响应不变。
- 导演台侧行为：`default_image_workflow_id()` 与助手可见模型清单按 `is_default`/`sort_order` 取值，复合工作流回落（`resolve_composite_model`）行为不变。
- 兼容性：无表结构与新增接口；`grs_image_models` 列不变。历史任务按 `workflow_id` 记录，顺序调整不影响复现。
- 受影响文件：`backend/app/grs_provider.py`、`backend/app/storage.py`、`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/director_jobs.py`、`backend/app/director_assistant/actions.py`、`frontend/src/admin/GrsProviderSettings.tsx`。
- 验证：`python -m unittest backend.tests.test_ai_studio`（46 项，含排序与默认互不影响、新模型追加在末尾两项新增用例）；项目根 `python -m unittest discover -s backend/tests -t .`（1721 项 OK，1 skipped）；5173 桌面端无头 Chrome 实测拖动保存后 `/api/modes` 顺序同步、默认标记不变。
- 回滚：还原上述文件即恢复「默认模型钉在首位」的旧排序；已写入的 `sort_order` 数值可保留，无需迁移。界面与实现基线见 `docs/ARCHITECTURE.md`、《功能说明与扩展指南》同日章节。

## 2026-11-06 GRS 生图模型改为从平台动态拉取（fetch / import）

- 变更原因：生图模型目录此前只有内置硬编码常量与管理员手填模型 ID 两条来源，上游新增模型界面完全感知不到，内置表里还留着平台已不返回的模型。现在以平台 `GET /v1/models` 为在售清单来源。
- `POST /api/admin/providers/grs/models/fetch`（新增，**只读**）：超级管理员 + `X-CSRF-Token`。请求体可省略，或复用测试连接的 `{ base_url, api_key }`（允许用未保存的输入探测上游）。响应 `{ models, off_platform, total, fetched_at, message }`：`models` 为过滤掉对话模型后的生图清单，每项 `{ provider_model, workflow_id, display_name, profile, resolutions, profile_source, in_catalog, enabled, is_default }`，`profile_source` 取 `builtin`（沿用内置能力档与分辨率/画质）或 `guess`（按命名家族推断，需管理员确认）；`off_platform` 是本地目录里有、但本次平台清单没有的模型；`total` 为上游返回的模型总数（含对话模型）；清单为空时 `message` 给出原因。上游异常统一 502，失败另写 `fetch_grs_platform_models_failed` 审计。
- `POST /api/admin/providers/grs/models/import`（新增）：超级管理员 + `X-CSRF-Token`，请求体 `{ models: [{ provider_model, display_name?, profile?, resolutions?, enabled }] }`（1–60 项）。`display_name`/`profile`/`resolutions` 省略时按平台条目回退；`profile` 不在六个能力档内 **409**。响应 `{ created, skipped, models, profiles }`，`created` 为新增 `workflow_id`，已在目录中的模型进 `skipped` 且不覆盖既有显示名、启用与默认配置。审计 `import_grs_platform_models`。
- 兼容性：`GET/PUT/POST /api/admin/providers/grs/models` 与 `POST …/models/sync` 行为不变，手填与内置补种保留为备用路径；`grs_image_models` 表结构不变，导入行 `builtin=0`；创作页工作流列表仍只来自目录中 `enabled` 的行。目录没有删除接口，误导入需管理员停用。
- 受影响文件：`backend/app/grs_client.py`、`backend/app/grs_catalog.py`、`backend/app/grs_provider.py`、`backend/app/models.py`、`backend/app/main.py`、`frontend/src/admin/GrsProviderSettings.tsx`、`backend/tests/test_grs_platform_models.py`。
- 验证：`python -m unittest tests.test_grs_platform_models`（12 项通过）；项目根 `python -m unittest discover -s backend/tests -t .`（1719 项 OK，1 skipped）；`pnpm --dir frontend build` 通过；真实上游 `https://grsai.dakka.com.cn/v1/models` 实测返回 32 个模型、识别 17 个生图模型、3 个需确认能力档；5173 桌面端无头 Chrome 实拍弹窗与导入回执。
- 回滚：还原上述文件即可退回手填/内置补种路径；已导入的 `builtin=0` 目录行保留并停用不影响内置种子与历史任务。

## 2026-11-04 剧本资产拆解改为后台任务（SSE 进度 + 两遍法）

- 变更原因：内容库「拆解资产」此前是同步请求，界面只有一个 Loading，用户无法判断是否仍在运行；一次性单次 LLM 输出全部资产，任何名称幻觉都会整单失败（「资产拆解包含原文未出现的名称，请重试」），失败后整段重跑。
- `POST /api/projects/{project_id}/documents/{doc_id}/asset-extraction`（新增，**202**）：入队 `asset_extraction` 后台任务，返回 `{ job_id, document_id, status }`。同一文档已有 queued/preparing/running 任务时返回原 `job_id` 并标 `duplicate=true`，不重复入队。文档不存在或正文为空 **400**。任务成功后按 `append` 语义写入资产库，重复点击只补新增资产。
- `GET /api/projects/{project_id}/jobs/{job_id}/events` 支持 `asset_extraction`：`status`（`phase` = `prepare` / `extract` / `describe` / `save`、`message`、`chars` 已接收字符数）、`done`（`document_id`、`transferred={characters,scenes,props}`、`total`、`skipped`、`skipped_count`）、`error`，空闲时推送 `keep-alive`。可用 `since` / `Last-Event-ID` 续传；订阅时任务已终态则直接返回 `done` 或 `error`。
- 任务行：`job_type=asset_extraction`，`payload` 含 `document_id` / `filename` / `phase` / `message` / `chars` / `transferred` / `total` / `skipped`（最多 50 条）/ `skipped_count`。`GET /api/projects/{project_id}/jobs` 瘦列表保留这些汇总字段（`stream` 只留阶段、消息与字符数），供内容库恢复进度和任务中心回显，不返回草稿与 `request_body`。
- 两遍法拆解（`LlmService.extract_script_assets`）：第一遍只从原文确定名称（每个名称必须能在剧本原文逐字命中，证据字段同源），程序再做确定性地名/道具提示并冻结名单；第二遍按角色 / 场景 / 道具三组分别整理描述与造型提示，只允许使用冻结名单，组内逐项校验并单组重试。未通过项进入 `skipped` 不影响其他资产落库，不再整单失败。
- 同步端点保持：`POST /api/projects/{project_id}/documents/{doc_id}/transfer-assets` 仍按 `mode=merge|append` 同步执行，供 MCP / 脚本调用；响应新增 `total`、`skipped`、`skipped_count`（原有 `transferred` 结构不变）。该端点内部同样走两遍法与增量回执，重复同稿不重复调用大模型。
- 兼容性：无表结构、端口、工作流与 ComfyUI 配置变更；`asset_extraction` 是新增的 `ai_project_jobs.job_type`，历史任务行不受影响。服务重启时进行中的拆解任务标记为失败并提示重新拆解。
- 受影响文件：`backend/app/media_studio/services/{asset_extraction_job_service,asset_extraction_skills,script_asset_extraction,llm_service,project_detail_service,job_payload}.py`、`backend/app/media_studio/routers/project_router.py`、`backend/app/main.py`、`frontend/src/director2/{api.ts,asset-extraction-live.ts,director2-job-types.ts}`、`frontend/src/director2/panes/{ScriptWorkspace,JobsCenterPane}.tsx`、`backend/tests/{test_asset_extraction_job,test_script_asset_extraction,test_job_list_payload}.py`、`frontend/src/director2/{asset-extraction-live,director2-job-types}.test.ts`。
- 验证：`python -X utf8 -B -m unittest discover -s backend/tests -t .` 全量通过；`npx vitest run`（117 文件 / 776 项）与 `npx tsc -b --force` 通过；5173 桌面端实测剧本页拆解全程进度、完成后自动进入制作资产库，任务中心「资产拆解」页签与详情抽屉回显 22 项资产（8 角色 / 3 场景 / 11 道具，0 跳过）。
- 回滚：删除 `asset_extraction_job_service.py` 与新增端点，恢复 `ScriptWorkspace.tsx` 的同步 `transfer-assets` 调用即可；已写入资产与历史 `asset_extraction` 任务行可保留，无需迁移。

## 2026-11-04 导演台项目按账号隔离

- 变更原因：导演台「我的短剧」列表未按登录账号过滤，换账号后仍能看到其他账号的工程，跨账号访问项目详情与子资源也没有拦截。
- 数据模型：`ai_projects` 新增 `owner_user_id VARCHAR(64) NULL` 与索引 `idx_ai_projects_owner_updated (owner_user_id, updated_at)`。启动时 `ensure_schema()` 通过 `ensure_column` / `ensure_index` 幂等补齐，已有历史 `NULL` 归属一次性归给最早创建的活跃超级管理员（沿用 `assign_unowned` 先例），迁移后生产数据不再有 `NULL`。
- REST 行为：`GET /api/projects` 只返回 `owner_user_id` 等于当前登录账号的项目；`POST /api/projects` 写入当前账号；`/api/projects/{project_id}/...` 由 ASGI 中间件 `ProjectAccessMiddleware` 统一校验归属，跨账号与不存在的项目一致返回 404 `{"detail":"项目不存在"}`。`ProjectItem.owner_user_id` 使用 `Field(exclude=True)`，仅服务端使用，不出现在响应中。
- MCP 行为：`studio_list_projects`、`studio_list_edit_projects` 只列出当前授权账号名下的项目；`studio_create_project`、`studio_prepare_edit_episode` 新建的工程归属当前账号。同名剧目在不同账号下互不可见，工具描述与 server instructions 同步改为账号隔离。
- 兼容性：无新增 HTTP 端点；未登录请求仍由各路由原有鉴权拒绝，中间件在无 `auth_store` 的测试环境自动放行。历史项目归最早超管后，其他账号需要自行新建工程。
- 受影响文件：`sql/013_media_studio_init.sql`、`backend/app/media_studio/db.py`、`backend/app/media_studio/models.py`、`backend/app/media_studio/services/project_service.py`、`backend/app/media_studio/routers/project_router.py`、`backend/app/main.py`、`backend/app/mcp_gateway/director_service.py`、`backend/app/mcp_gateway/editing_service.py`、`backend/app/mcp_gateway/routes.py`、`backend/tests/test_project_ownership.py`（新增）、`backend/tests/test_director_project_info.py`、`backend/tests/test_local_drama_mcp.py`。
- 验证：`python -m pytest backend/tests/test_project_ownership.py backend/tests/test_director_project_info.py backend/tests/test_local_drama_mcp.py -q`（21 项通过）；`python -m pytest backend/tests -q` 全量回归（1604 passed / 1 skipped）。真实接口以 zlyadmin 登录创建临时工程验证：归属写入当前账号；改成其他归属后列表不再返回、直接访问返回 404 `{"detail":"项目不存在"}`；验证后已删除临时工程。
- 回滚：还原上述文件并删除 `owner_user_id` 列与索引即可；历史项目归属列可保留不影响旧代码。

## 2026-11-04 精选作品（首页展示位，管理员发布 / 全员只读）

- 定位：独立于 `ai_projects` 的只读展示快照。发布时冻结项目、文档、分集、分镜与资产；普通成员无需拥有原工程即可查看，且不能通过该接口编辑原工程。当前不含复制/克隆接口。
- `GET /api/featured-works`：登录用户。返回已发布列表，按 `sort_order ASC, published_at DESC`。每项字段：`id`、`project_id`、`title`、`summary`、`cover_url`、`episode_count`、`shot_count`、`sort_order`、`published_at`、`updated_at`（不含 `snapshot_json`）。
- `GET /api/featured-works/{featured_id}`：登录用户。返回列表字段 + `published_by` + `snapshot`（项目 / 文档 / 分集 / 资产）。不存在或已下架返回 404 `{"detail":"精选作品不存在或已下架"}`。
- `POST /api/admin/featured-works`：管理员（`mutating_admin_user`，需 CSRF）。请求体：
  - `project_id`（必填）：要发布的短剧工程。
  - `title`（可选，≤255）：缺省用工程名。
  - `summary`（可选，≤280）：缺省用工程简介；显式传空串可清空。
  - `cover_url`（可选）：仅接受 `http(s)://` 或 `/` 开头且 ≤2048 字符；缺省依次回退工程封面 → 角色 → 场景 → 道具 → 首个分镜图。
  - `sort_order`（可选，0–999，缺省 0）：数字越小越靠前。
  - 同 `project_id` 重复发布执行更新并保留首次 `published_at`；工程不存在或没有可展示剧本时返回 400。成功返回与详情接口相同结构。
- `DELETE /api/admin/featured-works/{featured_id}`：管理员（`mutating_admin_user`，需 CSRF）。删除展示行（短剧本身不受影响），返回 `{"status":"ok","id":"..."}`；不存在返回 404。
- 快照字段：`snapshot.project`（id/name/description/cover_url）、`snapshot.documents[]`（filename/raw_text）、`snapshot.episodes[]`（id/number/title/status/script_text/summary/episode_video_url/beats）、`snapshot.assets[]`（kind/name/role/description/image_url）。分镜仅保留展示字段与安全的 `image_url` / `video_url` / `duration`；非法媒体地址置空，全空分镜丢弃。
- 兼容性：新增独立表 `ai_featured_works` 与独立路由，不影响既有 `/api/projects`、任务、工作流与媒体接口。
- 验证：`python -X utf8 -B -m unittest backend.tests.test_featured_works -q`（9 项）；5173 桌面端发布/详情/下架链路实测。

## 2026-11-04 MCP 资产出图缺省出造型卡 + 纯文本集标题解析

- 变更原因：MCP 全流程实测（2026-11-04 会话）发现两处坑。① `studio_generate_asset_image` 角色缺省生成 avatar 头像，但出片前置检查只认 identity 造型卡（出片参考图=造型卡+场景主图），客户端按缺省走完仍被「缺少造型图」拦下；② 剧本解析器的集标题正则强制 markdown `#` 前缀，纯文本「第一集 xxx」整篇解析为 0 集，无法拆解。
- MCP 缺省变化（`mcp_gateway/director_service.py`）：角色资产缺省改为生成首个还没有图的造型卡（identity），不传 `identity_id` 自动解析该造型，已全部出图则重生成第一个；角色没有造型槽位时仍回落 avatar。响应 `note` 按目标类型说明出片语义（identity/scene_master 是出片参考图；avatar 仅用于界面展示并提示改用 `target_type=identity`）。工具描述同步更新（`routes.py`）。显式传参行为不变；工作台 UI 与 HTTP API 不受影响（按钮均显式传 target_type）。
- 解析器变化（`media_studio/services/script_parser.py`）：新增 `PLAIN_EPISODE_LINE`，仅在 `script_episode_spans` 找不到任何 markdown 集标题时，把严格形如「第X集」的行（集号后到行尾或跟空白/全半角标点/`**`）提升为 `# 第X集` 标题再走标准解析；「第一集就要上线了」这类无分隔的句子不会误判。已有 markdown 剧本零行为变化。
- 受影响文件：`backend/app/media_studio/services/script_parser.py`、`backend/app/mcp_gateway/director_service.py`、`backend/app/mcp_gateway/routes.py`、`backend/tests/test_standard_script_parser.py`（+3 例）、`backend/tests/test_mcp_gateway.py`（+1 例）、本快照、`docs/API.md`、`功能说明与扩展指南.md`。
- 兼容性：无表结构、端口、任务队列变更；markdown 剧本解析不变（提升仅在 0 集时触发）；MCP 工具签名不变，仅缺省行为与 note 文案变化；旧 MCP 客户端无需重新授权，重新发现工具即可拿到新描述。
- 验证：`python -X utf8 -B -m unittest backend.tests.test_standard_script_parser backend.tests.test_director_compact_script backend.tests.test_director_bracketed_script backend.tests.test_script_asset_extraction backend.tests.test_mcp_gateway -q`（46+37 项通过）；后端全量 `python -X utf8 -B -m unittest discover -s backend -t . -p "test_*.py"`。
- 回滚：还原上述三个源文件与两处测试即可，无迁移。


## 2026-11-03 H3 动作迁移 · 多人参考视频版（minimax-h3-motion-ref-video）

- `GET /api/modes` 新增 `minimax-h3-motion-ref-video`（「H3 动作迁移 · 多人参考视频版」，catalog_group=official_h3）：`accepts_video_reference=true`，min/max references = 2/7，`reference_slots=["image"×6,"video"]`。`reference_slots` 是模式条目新增字段：按最大槽位数声明类型序列，实际提交数少于声明槽位时末位按尾槽类型（video）、其余按 image（`WorkflowDefinition.reference_kind(index, count)`）。reference_labels 为「角色形象图 1-6 / 动作参考视频」。旧骨架版 `minimax-h3-motion-transfer` 条目与行为不变。
- `POST /api/jobs`：`mode=minimax-h3-motion-ref-video`，重复 multipart `references` 共 2-7 项：前 1-6 项角色形象图（`<Picture n>` 与上传顺序对应，第 n 张绑定视频第 n 位表演者）、末项动作参考视频（每项 ≤50 MiB；视频须覆盖所选时长，否则入队前 422）。`prompt` 可留空（回落内置默认；已含 `<Picture/<Video 1>/<Subject>` 结构时原样透传）。options：primary 为 `aspect_ratio=16:9|9:16|1:1`（默认 9:16）、`duration=5s|10s|15s`；advanced 为 `preserve_audio`（默认 true，仅原片实测有音轨才保留）、`render_quality=preview|standard|fine`、`seed`；尺寸/帧数/fps/模型等为 internal。追加轮次可省略 references 复用上一轮。
- 任务/轮次回显 `references[].kind` 按实际素材数判定（末位 video）；输出为带音轨（如保留）的视频成片，历史恢复节点 `58`，与其它 H3 模式一致。MCP 网关沿用「含 video/audio 槽位不进工具目录」规则，新工作流自动不暴露给 `/mcp`。无新增端点、无表结构变更；实现与回滚见架构快照同日章节。

## 2026-11-03 MCP 导演台全流程工具

MCP 工具 24 → 44，作用域不变（读用 `studio:read`，导演台写入用 `studio:generate`），已连接客户端重新发现工具即可，无需重新授权。无新增 HTTP 端点、无表结构变更。**2026-11-04 更新**：`studio_generate_storyboard` 已随镜头三联关键帧下线移除，工具总数 44 → 43；分镜直接从 `studio_update_beat` 走到 `studio_generate_beat_prompt`。

- 读取：`studio_list_projects(limit)`、`studio_get_project(project_id)`、`studio_get_script(project_id, document_id)`、`studio_get_episode(project_id, episode_id)`、`studio_get_dubbing(project_id, episode_id)`、`studio_list_project_jobs(project_id, job_id?, limit)`。项目与文档列表不带正文（给 `raw_chars`、拆解摘要、资产造型 `has_image`、每集 `beat_count`/`video_ready_beats`）；正文只在 `studio_get_script` 返回并同时回显 `base_raw_text`；任务返回带 `next_poll_seconds`（活跃 2 秒，空闲 0），不返回 `output_path` 绝对路径。
- 写入：`studio_create_project(name, description?)`、`studio_save_script(project_id, raw_text, document_id?, base_raw_text?, filename?, episode_num?)`、`studio_plan_script(project_id, document_id, aspect_ratio?)`、`studio_extract_script_assets(project_id, document_id, mode=merge|append)`、`studio_apply_script_episodes(project_id, document_id, mode=overwrite|append)`、`studio_create_asset(project_id, name, kind, role?, description?, visual_prompt?)`、`studio_generate_asset_image(project_id, asset_id, target_type?, prompt?, identity_id?)`、`studio_update_beat(project_id, episode_id, beat_id, patch)`、`studio_generate_storyboard(project_id, episode_id, beat_ids?, visual_style?, ethnicity?)`、`studio_generate_beat_prompt(project_id, episode_id, beat_id, merge_as_one?)`、`studio_generate_episode_video(project_id, episode_id, beat_ids?, force?, workflow?, options?)`、`studio_confirm_project_refine(project_id, job_id)`、`studio_skip_project_refine(project_id, job_id)`、`studio_generate_dubbing(project_id, episode_id, line_ids?)`。
- 并发与前置：整篇改写缺 `base_raw_text` 直接拒绝；`episode_num` 走与 `PUT /api/projects/{pid}/documents/{doc_id}` 相同的按集编辑分支，锁定集返回冲突不落库。出片前置不足（缺主角、场景主视图、造型图、运镜或 H3 提示词）、同集已有整集/合成任务、勾选镜头都在生成中等，均由 `EpisodeVideoService` 原样返回中文原因；`options` 只接受注册表 `primary`/`advanced` 创作参数，`internal` 键在入队前拒绝。
- 二采分两套：生成页任务用 `studio_confirm_refine` / `studio_skip_refine`（`jobs` 表）；工坊任务在 `ai_project_jobs`，必须用 `studio_confirm_project_refine` / `studio_skip_project_refine`（`project_id` + `job_id`）。
- 出口与边界：MCP 不暴露整集合成与任何删除操作；整集拼接沿用智能剪辑链路 `studio_prepare_edit_episode` → `studio_preview_edit` → `studio_confirm_edit` → `studio_export_edit`，素材来源仍是 beats 的 `upscaled_video_url`/`video_url`/配音。导演台项目库与 Web 一致按 `project_id` 全局可见（表内无 owner 列），MCP 未新增隔离。参考素材仍只接受图片，需要视频/音频槽位的工作流不进 MCP 目录。
- 实现与验证：`backend/app/mcp_gateway/director_service.py`、`routes.py`、`backend/tests/test_mcp_gateway.py`；详见架构快照同日「MCP 接入导演台全流程」。

## 2026-11-03 MCP 二采确认与图片参考边界

- MCP 新增 `studio_confirm_refine(job_id)` 与 `studio_skip_refine(job_id)`，作用域 `studio:generate`，与 HTTP `/api/jobs/{job_id}/refine/confirm|skip` 复用同一实现，不另建状态机。仅任务处于 `awaiting_refine` 时可调用，否则返回 409「当前任务没有待确认的一采预览」；非本人任务返回 404「任务不存在」。工具总数 24，作用域集合未变，已连接客户端重新发现工具即可使用，无需重新授权。
- `studio_list_workflows` 与 `studio_get_workflow` 只覆盖图片参考的工作流：`WorkflowDefinition.reference_kind()` 中出现 `video` 或 `audio` 槽位时（`minimax-h3-motion-transfer`、`minimax-h3-inpaint`、`minimax-h3-depth`、`minimax-h3-avatar`）从列表移除，直接查询或创建返回 422 并写明第几项需要视频/音频素材。判定取自工作流注册表，网关不硬编码 ID；HTTP `/api/modes` 与工作台界面不受影响。
- `studio_get_job` / `studio_get_results` 响应结构不变，二采任务状态仍为 `awaiting_refine`（阶段文案「一采预览待确认」）。验证：`python -X utf8 -B -m unittest backend.tests.test_mcp_gateway`（30 项通过）；实现、兼容性与回滚见架构快照同日章节。

## 2026-11-03 工坊批量删除片段

`DELETE /api/projects/{project_id}/episodes/{episode_id}/beats` 沿用项目会话和 `X-CSRF-Token`，JSON 请求 `{ "beat_ids": ["beat-a", "beat-b"] }`，响应 `{ "status": "ok", "deleted_beat_ids": ["beat-a", "beat-b"], "beats": [...] }`。删除 ID 去重并按原分集顺序返回；`beats` 为事务读取的最新剩余列表。空/无效选择、列表已变化或删除全部返回 400；选中片段或本集正在生成/合成返回 409。

服务端至少保留 1 个片段；保留其他片段的正文、顺序与媒体，更新片段数量并清除过期整集视频绑定。原剧本、资产、云端文件与历史任务保留。无需数据库迁移；回滚方式见架构快照同日章节。

## 2026-11-03 剧本分集菜单与锁定补充

- GET /api/projects/{project_id}/documents 的各文档增加 locked_episode_nums: number[]、episode_lock_reasons: Record<string,string>。锁定来自已拆解标记或对应制作分集；追加集号不锁定其他集。
- POST /api/projects/{project_id}/documents/{doc_id}/episodes：会话与 CSRF 沿用项目接口，请求 {base_raw_text:string}，响应 {document_id,episode_num}。创建最大集号加一的大纲占位，不创建制作分集；原正文不变，旧稿存入 script_revision。
- DELETE /api/projects/{project_id}/documents/{doc_id}/episodes/{episode_num}：请求 JSON {base_raw_text:string}，响应 {document_id,episode_num,status:"deleted"}。移除本集正文和大纲，保留其余集、资产、成片及旧稿，不重排编号。集号范围 1–1000；已锁定或过期版本 409，不存在 400，目标文档不属于项目 404。
- PUT 原文档接口的 episode_num 同时支持填写已有大纲占位正文，须使用唯一明确集标题；已锁定集修改返回 409。全文编辑亦保护锁定集，并对编辑前 raw_text 与 analysis_json 同时校验，避免覆盖并发拆解标记。助手预览/采纳分别重查锁定。
- 原资产 transfer-assets 的 append 接口保持；成功后在 analysis.assets_extracted_episode_nums 标记当前正文集号。JSON_SET 保留其他分析字段，并以原文校验并发变化；重复同稿标记兼容 MySQL 未修改行计数为零。仅表示资产已整理，不承诺自动生成图片。
- 无表结构、工作流或端口迁移；验证与回滚见架构快照「剧本阅读、分集菜单与提取说明」。

## 2026-11-03 关键帧叙事（minimax-h3-keyframe）

- `GET /api/modes` 新增 `minimax-h3-keyframe`：min/max references = 2/4 且全部为图片，reference_labels 为「开场关键帧 / 关键帧 2 / 关键帧 3 / 关键帧 4」；工作流归属 catalog_group=official_h3，占用串行视频 worker（`is_local_comfy_job`）。
- `POST /api/jobs`：`mode=minimax-h3-keyframe`，multipart `references` 按叙事顺序上传 2-4 张关键帧图片（每张 ≤50 MB），`prompt` 必填（描述关键帧之间的叙事过渡），缺失返回 422。options：primary 为 `aspect_ratio=16:9|9:16|1:1`、`duration=5s|10s|15s`、`anchor_seconds`；advanced 为 `steps=4..40`（默认 20）与 `seed`（0 表示随机）。width/height/length/fps 等为 internal，由注册表按比例与时长解析（5/10/15 秒 = 124/243/362 帧，17n+5 网格，24fps）。
- `anchor_seconds` 语义：第 2~N 张关键帧的画面出现时间，逗号分隔秒数（如 `2.5,8`）；负数沿用 AddGuide 语义从末尾计数（`-1` 为末帧）；留空表示均匀分布（首帧锚 0、末张锚末帧、其余均分）。非法输入（数量与关键帧数不匹配、超出时长、非递增、非数字）在入队前返回 422。
- 输出为 H3 原生音画一体成片；任务回显、恢复（completed_outputs 节点 `30`）与既有 H3 工作流一致。旧客户端与其他模式不受影响。

## 2026-11-02 动作迁移混合参考素材

- `GET /api/modes` 的动作迁移条目声明 `accepts_video_reference=true`、`default_prompt` 及 references 的 `content_type=image/*,video/*`。所有字段来自工作流注册表；其它工作流的能力边界不变。
- `POST /api/jobs`：`mode=minimax-h3-motion-transfer`，重复 multipart 字段 references **恰好两项**，按顺序上传角色形象图和动作参考视频（MP4/MOV/WebM 等），每项 ≤50 MiB。prompt 可省略/留空，后端保存实际默认提示词；其它模式仍要求提示词。视频须覆盖所选时长，错误类型、损坏、过短或超限会在入队前返回 422/413 并清理部分文件。追加轮次接口支持相同混合素材，也可省略 references 复用上一轮。
- 创作参数：`control_strength=0.1..1.0`、`aspect_ratio=16:9|9:16|1:1`、`duration=5s|10s|15s`；advanced 为 `render_quality=preview|standard|fine`（8/20/30 步）和 `seed=0..2147483647`，0 表示本次随机。steps、尺寸、帧数、帧率为内部参数，创建 UI 不显示；生效快照包含实际 seed/width/height/length/fps/steps，`request_parameters` 的技术项为 internal。
- 任务/轮次的 references 增量提供 kind/label。原鉴权参考图接口也用于参考视频，返回 video/* 并支持播放器请求；URL、账号隔离、uploads 目录校验不变。旧客户端可忽略新字段。没有新的公开上传接口或数据库迁移。
- 不经过云端视频 API，仍使用当前配置的 ComfyUI。输出时长受 H3 帧网格影响：5/10/15 秒为 124/243/362 帧、24fps；输出音频由 H3 生成，不是源视频的音乐。验收与回滚见 `ARCHITECTURE.md` 同日最新链路记录。

## 2026-10-31 游客工作流预览

`GET /api/modes` 现在允许匿名只读：未登录返回工作流名称、参考图约束、primary/advanced 创作选项及静态提示词预设；内部参数和供应商运行状态不公开。已登录响应保持完整注册表。`GET /api/modes/{mode_id}`、任务/素材/管理接口及全部写入继续沿用原登录、角色和 CSRF 验证。此变更只支持游客浏览和本地草稿，不授予生成权限。实现和验证见 `ARCHITECTURE.md` 同日期「游客生成首页与按需登录弹窗」。


## 2026-10-27 二采清晰度策略

H3 二采新增可选字段 `refine_quality_mode`：`auto`（默认）按片长×目标像素约 200 封顶并自动降档；`force` 严格按 `refine_quality` 输出，长片显著变慢并可能因显存不足失败。非法值返回 400「清晰度策略请选择自动或强制高清。」，缺省按 `auto` 处理，旧客户端与旧任务行为不变。实际生效像素写入任务运行参数的 `refine_megapixels`，`refine_quality` 保留为用户选择的上限值。

## 2026-10-27 二采固定先预览一采

H3 二采任务中 `refine_preview` 由平台托管：`refine_enabled=true` 时固定为 `true`，任务先完成 0.4 MP 一采并停在 `awaiting_refine`，请求显式传 `false` 也会被忽略；`refine_enabled=false` 时固定为 `false`。旧任务没有该字段时继续按关闭处理。整集直出（`render_scope=episode`）无法暂停，提交时后端把 payload 中的 `refine_preview` 强制为 `false` 并连续跑完两段式，不再返回 400。API/MCP 自动化提交二采任务时需处理 `awaiting_refine` 状态并调用确认或保留接口（HTTP `/api/jobs/{job_id}/refine/confirm|skip`；MCP 为 `studio_confirm_refine` / `studio_skip_refine`，见 2026-11-03 章节）。

## 2026-10-24 二采先预览一采

开启 H3 的 `refine_enabled` 与 `refine_preview` 后，任务先完成 0.4 MP 一采并停在 `awaiting_refine`，`result_url` 指向可播放的一采预览。确认与保留使用以下接口，均要求现有登录权限：

| 接口 | 说明 |
|---|---|
| `POST /api/jobs/{job_id}/refine/confirm` | 创作任务：校验唯一生成项处于 `awaiting_refine` 且保存了续跑工作流，改回 `queued`（阶段「等待二采精修」），用同一 seed 只跑二采。返回 202 `JobResponse`；状态不符或工作流缺失返回 409。 |
| `POST /api/jobs/{job_id}/refine/skip` | 创作任务：把一采输出直接作为最终结果，状态改为 `succeeded`，清理续跑状态。返回 202 `JobResponse`。 |
| `POST /api/projects/{project_id}/jobs/{job_id}/refine/confirm` | 工坊逐镜/选中镜：原子校验并提交 `refine_continuation` 中保存的续跑工作流，避免重复点击。 |
| `POST /api/projects/{project_id}/jobs/{job_id}/refine/skip` | 工坊逐镜/选中镜：把预览写为镜头成片并结束任务。多段预览未合并时先合并；无法合并且未配置七牛云时返回 400。 |

`awaiting_refine` 任务可取消，但不会在 worker 启动时自动恢复。确认二采后续跑状态标记为 `confirmed`，worker 只在该状态下复用续跑图；一采失败、取消或中断后的重试仍从一采预览开始。整集直出（`render_scope=episode`）不支持先预览，提交时后端自动连续跑完两段式（2026-10-27 起不再返回 400）。外部响应不包含内部 `refine_state`；旧任务没有 `refine_preview` 时按关闭处理。

## 2026-10-23 MCP 本地剧目接入

以下工具使用现有 Streamable HTTP `/api/mcp` 和 OAuth `studio:edit`，不是新增匿名 HTTP 接口。

| 工具 | 参数 | 返回与边界 |
|---|---|---|
| `studio_prepare_edit_episode` | `project_name, episode_code, title?, version="v001", script_text?` | 唯一准确剧名的 `project_id` 与按集号/版本隔离的 `sequence_id`；缺失时创建，存在时复用，不覆盖旧剧本；同名歧义报错 |
| `studio_import_edit_media` | `project_id, sequence_id, paths[], revision, document_name?` | 仅引用明确本机文件，返回按输入顺序排列的 `asset_ids`、新 `revision`、新增/复用数量；保留现有片段，任一文件失败不保存，CAS 冲突 409 |

接续调用：读取时间线 → 导入清单 → 预览 `video_arrange(asset_ids=...)` → 确认 → 可选精剪/真实音轨字幕 → `studio_export_edit(output_dir=...)` → 查询成功导出。目录权限、账号隔离与既有本机素材规则一致。

## 2026-10-23 MCP 智能剪辑工具

在既有生成能力上新增 `studio:edit` 作用域和 11 个剪辑/导出工具，MCP 客户端可读取导演台工程/分集、预览并确认自动铺轨、自动字幕、对白精剪、成片速剪、高光合集、引流剪辑，查询或提交音轨转写，向文字轨添加标题/字幕，并把成片导出到指定本机目录。工具总数 20；旧的只含 `studio:read studio:generate` 的授权需重新授权才能获得剪辑权限。

| 工具 | 作用域 | 参数与说明 |
| --- | --- | --- |
| `studio_list_edit_projects` | `studio:read` | 列出可剪辑的导演工程；每个工程返回 `main`（自由剪辑）和分集 `sequence_id`。 |
| `studio_get_timeline` | `studio:read` | `project_id,sequence_id`；返回 `revision`、名称、设置、总时长、素材、片段和 `analysis`（画面与音轨摘要）。预览/确认前必须先读取。 |
| `studio_get_transcript` | `studio:read` | `project_id,sequence_id`；返回音轨转写状态、带时间戳段落和摘要，不发起转写。 |
| `studio_start_transcript` | `studio:edit` | `project_id,sequence_id`，可选 `force`；提取有声素材并提交异步转写，按音频秒数消耗转写服务，调用前需用户同意。 |
| `studio_preview_edit` | `studio:edit` | `project_id,sequence_id,operation`，可选 `revision,asset_ids,strategy`；生成待确认方案，不写时间线。`operation` 同内置助手：`video_arrange`、`subtitle_arrange`、`audio_subtitle`、`dialogue_cut`、`quick_cut`、`highlight_cut`、`hook_cut`；`asset_ids` 仅用于 `video_arrange`，`strategy` 仅用于 `hook_cut`（`conflict_3s`、`climax_only`、`quote_open`、`ending_hook`、`trailer`）。 |
| `studio_get_edit_action` | `studio:read` | `project_id,sequence_id,action_id`；查询方案清单、状态与结果，仅限本人创建的动作。 |
| `studio_reorder_edit` | `studio:edit` | `project_id,sequence_id,action_id,asset_ids`；按新顺序调整待确认的智能铺轨清单，不写时间线。 |
| `studio_confirm_edit` | `studio:edit` | `project_id,sequence_id,action_id`；原子执行方案并写入自己的时间线；幂等，重复确认返回同一结果。 |
| `studio_add_text` | `studio:edit` | `project_id,sequence_id,text`，可选 `preset`（`title`/`subtitle`）、`start`、`duration`、`font_size`、`color`、`x`、`y`；直接写入文字轨。文字最多 1000 字，时间与颜色会校验，文字轨时间重叠返回冲突；不改动画面和音频。 |
| `studio_export_edit` | `studio:edit` | `project_id,sequence_id`，可选 `output_dir`、`quality`（720/1080，默认 1080）；把已保存的时间线导出为 MP4。`output_dir` 为服务器本机绝对文件夹路径，留空写入 `data/exports/smart-edit/`；管理员/超管可写任意可创建目录，员工仅限 `ZLY_AI_VIDEO_STUDIO_LOCAL_MEDIA_ROOTS` 内。返回 `{ id, status, progress, output_path, download_url }`，异步执行。 |
| `studio_get_edit_export` | `studio:read` | `project_id,job_id`；查询导出进度、成片本机路径 `output_path`、`download_url` 与错误；仅任务所属账号可读。 |

行为与错误：

- 时间线按账号隔离；工程和分集本身沿用导演台的共享可见性，但方案、动作和文字修改只属于当前令牌绑定的账号。其他账号的动作按不存在处理（404）。
- `studio_preview_edit` 与 `studio_reorder_edit` 不修改时间线；只有 `studio_confirm_edit` 会执行方案。`studio_add_text` 是直接写入，不经过预览。
- 写入使用工程行锁、时间线行锁和 revision CAS；时间线已被其他操作推进时返回 409，需重新读取后再操作。
- 参数错误返回 400，方案/工程/动作不存在或无权访问返回 404，状态冲突（过期、已执行、运行中）返回 409；智能剪辑助手或 ASR 未启用返回 503。
- 音轨转写是显式外发与计费动作，MCP 客户端应先向用户说明并取得同意；`studio_get_transcript` 只读，不会触发费用。
- 导出使用已保存的时间线快照，不修改工程；指定 `output_dir` 时必须是服务器本机绝对路径，路径不存在会自动创建，文件名由工程名 + 时间戳 + 任务号后缀组成，避免覆盖。目标目录需可写；非管理员越出允许目录返回 400。

## 2026-10-21 MCP 连接（Codex / Cursor）

MCP 服务地址为 `<对外 origin>/api/mcp`，使用无状态 Streamable HTTP（JSON 响应），鉴权为 OAuth 2.1 Bearer Token。MCP 客户端先在 `/.well-known/oauth-protected-resource/api/mcp` 与 `/.well-known/oauth-authorization-server/api/mcp/oauth` 读取发现元数据，再经动态注册、PKCE(S256) 授权码和令牌交换接入。所有工具调用只作用于令牌绑定账号自己的数据；管理员也没有跨账号能力。

| 方法与路径 | 行为 |
| --- | --- |
| `GET /.well-known/oauth-protected-resource/api/mcp` | 返回 `resource`、授权服务器、`studio:read` / `studio:generate` 作用域和 Bearer 头方式。 |
| `GET /.well-known/oauth-authorization-server/api/mcp/oauth` | 返回授权、令牌、注册、撤销端点及能力；允许匿名客户端和 `client_secret_post/basic`。 |
| `POST /api/mcp/oauth/register` | 动态客户端注册；回调地址必须是 HTTPS 或 `127.0.0.1`/`localhost`/`::1` 回环 HTTP，最多 10 个。 |
| `GET/POST /api/mcp/oauth/authorize` | 创建授权请求并跳转工作台 `/mcp/authorize?request_id=...` 等待账号确认；`resource` 必须等于当前 MCP 地址。 |
| `POST /api/mcp/oauth/token` | `authorization_code` 或 `refresh_token` 换取令牌；刷新每次轮换，重用旧刷新令牌会撤销整个授权。 |
| `POST /api/mcp/oauth/revoke` | 按 RFC 7009 撤销访问或刷新令牌，并撤销其授权连接。 |
| `POST /api/mcp` | MCP JSON-RPC 入口；`Authorization: Bearer <access_token>`。 |

浏览器侧接口沿用登录 Cookie，写操作需 `X-CSRF-Token`：

| 方法与路径（前缀 `/api/mcp`） | 行为 |
| --- | --- |
| `GET /info` | 返回 MCP 是否启用、对外地址、传输方式和作用域；未配置地址时含可读原因。 |
| `GET /connections` | 列出自己的授权连接：客户端名、作用域、创建/最近使用/过期时间和状态。 |
| `DELETE /connections/{id}` | 撤销自己的授权连接；不存在或非本人返回 404。 |
| `GET /authorization-requests/{request_id}` | 授权页读取客户端、账号、回调和作用域；过期/已用返回 410，绑定其他账号返回 403。 |
| `POST /authorization-requests/{request_id}` | JSON `{allow:boolean}`；允许后返回带 `code` 的客户端回调地址，拒绝返回 `error=access_denied`。 |
| `GET/POST /references` | 列出或上传参考图；POST 为 multipart `file`，仅 PNG/JPEG/WebP，单张 ≤ 50 MB，返回 201。 |
| `GET /references/{id}/preview` | 返回自己的参考图二进制，禁止缓存。 |
| `DELETE /references/{id}` | 删除自己的上传参考图；正在提交到任务时返回 409。 |
| `GET /generated-images` | 列出自己最近任务中可复制的生成图片，最多 100 张。 |
| `POST /references/from-output` | JSON `{job_id,generation_item_id,output_index}`，把自己的生成图片复制为参考图，返回 201。 |

工具：

| 工具 | 作用域 | 参数与说明 |
| --- | --- | --- |
| `studio_list_workflows` | `studio:read` | 可选 `media_type=image\|video`；只返回工作流摘要。 |
| `studio_get_workflow` | `studio:read` | `workflow_id`；返回公开参数、默认值、约束、参考图数量与顺序。 |
| `studio_list_reference_assets` | `studio:read` | 列出自己的参考图 ID、名称、尺寸和预览地址。 |
| `studio_create_image` | `studio:generate` | `workflow_id,prompt,request_id`，可选 `options,reference_asset_ids,negative_prompt,image_size,title`；返回任务摘要。 |
| `studio_create_video` | `studio:generate` | `workflow_id,prompt,request_id`，可选 `options,reference_asset_ids,title`；任务异步执行。 |
| `studio_list_jobs` | `studio:read` | `limit` 默认 20，最大 100；只返回自己的任务。 |
| `studio_get_job` | `studio:read` | `job_id`；返回状态、阶段、进度、生成项和创作参数。 |
| `studio_get_results` | `studio:read` | `job_id`；返回成功输出与 5 分钟下载链接，部分失败也会返回成功项；过期后重新调用。 |
| `studio_cancel_job` | `studio:generate` | `job_id`；停止自己的排队中/生成中任务。 |

`request_id` 为 1–128 字符的客户端幂等键。同一账号用相同 `request_id` 和相同参数重试返回原任务；参数不同返回 409。`options` 只接受 `studio_get_workflow` 返回的参数，内部参数会被拒绝。参考图顺序对应提示词中的 `<Picture n>`，提交时复制为任务快照。

令牌时效：授权码 5 分钟、待确认请求 10 分钟、访问令牌 1 小时、刷新令牌 30 天。授权码与令牌在库中只存 SHA-256 指纹；撤销连接、禁用账号或账号仍要求修改初始密码时，访问立即失效。

## 2026-10-20 剧本诊断 V1

所有接口要求登录，POST/DELETE还要求`X-CSRF-Token`。诊断记录仅发起账号可读写，越权和不存在均为404；输入错误400/422，状态冲突409。来源项目沿用既有共享项目权限，但必须校验文档归属；不创建工程或修改剧本文档。

| 方法 | 路径（前缀 `/api/script-diagnoses`） | 行为 |
| --- | --- | --- |
| GET | `/capabilities` | 返回后端支持扩展名、最多10份、20MB/份、100000字符、LLM可用状态、默认模型和五项维度；不含凭据 |
| GET | `/source-document?project_id=&document_id=` | 只读来源预览，返回`title,sources`，不发起模型请求 |
| POST | `/extract` | multipart多项`files`，返回按上传顺序的`sources:[{name,text}|{name,error}]`；不发起模型请求或保存二进制 |
| POST | 空路径 | JSON `client_request_id,title,sources:[{name,text}]`，或`client_request_id,title,project_id,document_id`（二者互斥）；返回202和完整任务，原子保存输入快照，账号内同幂等键返回同一记录 |
| GET | `?offset=0&limit=30&document_id=` | 返回`items,total`；可按来源文档筛选，列表不带原文和报告大字段 |
| GET | `/{id}` | 返回任务状态、阶段、片段数、来源快照、模型、错误及可选报告 |
| POST | `/{id}/cancel` | 取消排队/执行中的诊断；已结束记录保持原状态 |
| POST | `/{id}/retry` | JSON `client_request_id`；失败/中断/取消记录用原快照创建新记录，旧来源被删除也可重试 |
| DELETE | `/{id}` | 删除已结束记录及其快照/报告；活动记录409，须先取消 |

来源快照为`{id,name,text}`数组，文本统一换行并移除首尾空白。报告`schema_version=1`，包含`summary`、`duration`（秒数区间、依据及分集/分段估算）、五项`dimensions`和最多三项`priorities`。维度key为`duration/novelty/pacing/emotion/risk`；问题包含`title,priority,explanation,suggestion,evidence`，优先级为`high/medium/low`。每条引用包含`source_id,block_id,quote,start,end`；偏移是快照正文中的Unicode字符索引，前端须按code point切分，不得按UTF-16直接slice。

状态为`queued/running/succeeded/failed/cancelled/interrupted`。阶段为`queued/analyzing/summarizing`及对应终态；`completed/total`表示已审阅片段数，汇总结束前不标成功。只使用当前已保存的默认LLM，不保存或返回密钥。复制和Markdown导出由前端对同一完整报告生成。

## 2026-10-20 智能剪辑

前缀 `/api/projects/{project_id}/smart-edit`，实现为 `backend/app/media_studio/routers/smart_edit_router.py`。读接口沿用登录，所有写接口必须带 `X-CSRF-Token`。剪辑文档与导出状态按当前账号隔离；单个工程最多 300 素材、200 片段和 30 分钟。`sequence_id=main` 表示自由剪辑，其余使用分集 ID。

| 方法与相对路径 | 请求与响应 |
| --- | --- |
| `GET /{sequence_id}` | `{ revision, document, updated_at, draft_key }`；未保存时 revision=0，返回空工程。draft_key 用于账号隔离的浏览器草稿恢复。 |
| `PUT /{sequence_id}` | `{ revision, document }`；条件更新返回新版本，旧版本或重复首次保存返回 409，不覆盖新内容。 |
| `GET /{sequence_id}/sources` | 本集采用版视频（优先超分）、无视频时的分镜图、配音，以及项目图片列表。素材 ID 含 Take 地址摘要，避免更新原片时替换旧剪辑。 |
| `POST /{sequence_id}/upload` | multipart `file`；读取实际时长/宽高/音轨并上传七牛云。单文件 512 MB，超限 413；类型/解码失败 400。 |
| `POST /{sequence_id}/import-local` | `{ path: string, recursive?: boolean }`；直接引用服务器本机绝对路径的文件或文件夹，不复制、不上传。管理员可导入任意可读路径；员工仅限 `ZLY_AI_VIDEO_STUDIO_LOCAL_MEDIA_ROOTS` 列出的目录（`;` 分隔），且 `project_id` 仍校验归属。返回 `{ path, assets[], skipped[] }`，素材 `url` 为 HMAC 签名的 `/api/local-media/{token}`，并附 `local_path/duration/width/height/has_audio/has_video`。单次最多 200 个文件，按自然顺序；不支持的类型/解码失败进入 `skipped` 并说明原因。 |
| `GET /api/local-media/{token}` | 按签名地址播放本机引用素材，需登录。令牌绑定绝对路径与服务器凭证密钥，篡改、越界或文件不存在返回 404；`FileResponse` 支持 Range（206）与拖动播放。该地址不能跨实例复用；更换 `credential.key` 后旧地址失效，需重新导入。 |
| `GET /{sequence_id}/understanding` | 当前账号的视频画面理解记录 `{status,model,progress,message,items[],summary,video_count,analyzed_count,stale,updated_at,finished_at}`；未开始返回 `status=missing`。`items[]` 含 `beat_id/asset_id/name/duration/status/description/camera/subjects/frames/detected_count/sampled_count/shots[]/error`；`shots[]` 为内部镜头，含 `index/start/end/duration/status/description/camera/subjects/frames/error`。`summary` 含 `video_count/analyzed_count/failed_count/detected_shot_count/shot_count/shot_analyzed_count/shot_failed_count`。源视频或时间线变化后 `stale=true`，旧条目不再作为证据。 |
| `POST /{sequence_id}/understanding` | `{force?:boolean}`；显式触发镜头检测、关键帧抽取与 VLM 画面理解，返回同一记录。FFmpeg 场景阈值 0.32、最短镜头 0.8 秒，检测异常回退整段素材；每条素材最多采样 4 镜、全时间线最多 40 镜，每个采样镜头抽 2 帧（0.2 秒与中点）。逐镜失败隔离并重试 2 次；状态 `running/succeeded/partial/failed/empty`，同范围运行中重复触发 409。需默认 VLM、可下载媒体与服务器 FFmpeg。 |
| `GET /{sequence_id}/transcript` | 当前账号的音轨转写记录 `{status,model,progress,message,items[],summary,stale,updated_at,finished_at}`；未开始返回 `status=missing`。`items[]` 含 `asset_id/beat_id/name/kind/duration/timeline_start/spans[]/status/segments[]/segment_count/audio_seconds/language/error`；`segments[]` 为 `{id,start,end,text}` 段级时间戳（源素材秒，供应商不提供词级时间戳），`spans[]` 记录该素材在时间线上的 `clip_id/timeline_start/timeline_duration/in_point/speed` 映射。`summary` 含 `media_count/transcribed_count/failed_count/skipped_count/segment_count/audio_seconds`（`audio_seconds` 即按音频秒计费口径的合计）。源视频或时间线变化后读取时置 `stale=true`，旧段落不再作为字幕证据；遗留 running 超过 15 分钟在读取时判为失败。纯静音或无语音为 `status=empty`、`segments=[]`，不回退剧本对白。 |
| `POST /{sequence_id}/transcript` | `{force?:boolean}`；显式下载时间线上仍在发声的素材（跳过静音与音量≤0 片段）、FFmpeg `-vn -ac 1 -ar 16000` 提取 16k 单声道 WAV 并调用转写，返回同一记录。单次最多 40 个素材、600 秒音频，超限素材标 `skipped` 并说明原因；每素材最多 200 段、200 条 span、单段 400 字；逐素材失败隔离，临时音频用后即删。模型取环境变量 `ZLY_AI_VIDEO_STUDIO_ASR_MODEL`（缺省 `XingChenAGI/XingChenASR-V3.2-Ultra`），复用大模型供应商的 base_url 与 API Key，超时 300 秒。状态 `queued/running/succeeded/partial/empty/failed`，同范围运行中重复触发 409；签名与模型未变且已完成时直接复用旧记录，`force=true` 强制重转。需服务器 FFmpeg/ffprobe 与已启用的大模型凭据。 |
| `POST /exports/mp4` | `{ document, quality:720\|1080, output_dir?:string }`；202 返回 `{ id, status, progress, output_path }`，完整快照另存于账号隔离文档表。需要 FFmpeg、ffprobe 与中文字体；不再要求七牛云。`output_dir` 留空时保存在服务器 `data/exports/smart-edit/{job_id}.mp4`；指定时必须为服务器本机绝对文件夹路径，自动创建目录并使用工程名 + 时间戳命名。管理员/超管不限目录，员工仅限 `ZLY_AI_VIDEO_STUDIO_LOCAL_MEDIA_ROOTS`。任务记录的 `result_url` 为账号隔离的下载地址。 |
| `GET /exports/{job_id}` | `{ id, status, progress, result_url, output_path, error_message }`；queued / running / completed / failed。`output_path` 为成片在服务器本机的绝对路径。服务重启中断的遗留任务标记失败，用户可重新导出。 |
| `GET /exports/{job_id}/file` | 下载已完成的本机导出 MP4，仅任务所属账号可访问；未完成 409，非本人 404。 |
| `POST /exports/bundle` | `{ document, format:"json"\|"xml"\|"otio"\|"jianying", include_media:boolean }`；返回 ZIP，始终附 `project.zly.json` 和说明；可选打包已用素材，上限 2 GB。 |

工程 `version=1`，`settings` 含 ratio / fps / background，`assets` 含 id / name / kind / url / duration，`clips` 含 id / track / asset_id / start / duration / in_point / speed / volume / muted / opacity / scale / x / y / rotation / effect / fade_in / fade_out / text / color / font_size。track 为 video / audio / text；同轨不得重叠。start 和 duration 为输出秒，须按 fps 对齐；in_point 是原片秒，源区间长度为 duration×speed。详细合法值见后端 `smart_edit_document.py`，服务器拒绝 NaN、Infinity、失效素材引用和超出原片范围。

完整效果以 MP4 / JSON 为准；XML / OTIO 和剪映基础草稿交换基础剪辑，外部软件需重新调整部分文字与特效。素材下载仅限管理员配置的当前媒体域名或本机签名引用，不能利用工程 JSON 访问任意服务或本地文件；bundle 的 `include_media` 内联读取本机文件，导出 MP4 同理，不会把本机路径写入通用任务 payload 之外的响应。

## 2026-10-19 导演台智能助手 V2

新增前缀`/api/director-assistant`，沿用登录与写入CSRF，个人内容按账号校验，内置资源共享。旧AI操作接口不变。实现位于`backend/app/director_assistant/`，增量存储为`sql/015_director_assistant.sql`。

| 路径（相对前缀） | 功能 |
| --- | --- |
| `GET /catalog` | 开关、资源、知识库及可选模型 |
| `GET/POST /sessions`、`GET/PATCH /sessions/{id}` | 会话列表/创建、完整快照/配置更新；PATCH带version |
| `POST /sessions/{id}/messages` | text、client_message_id；question_id/answer_values/skip可选；按提交标识幂等 |
| `GET /runs/{id}`、`GET /runs/{id}/events?since=N` | 运行状态、顺序SSE，支持Last-Event-ID |
| `POST /runs/{id}/cancel`、`POST /runs/{id}/retry` | 停止、重试；重试带新client_message_id |
| `POST /resources`、`PUT/DELETE /resources/{id}` | 个人资源及不可变版本 |
| `PUT /resources/{id}/favorite` | 收藏enabled状态 |
| `POST /resources/import-preview`、`GET /resources/{id}/export` | multipart导入预览、ZIP导出 |
| `POST /knowledge`、`DELETE /knowledge/{id}` | 知识库创建、删除 |
| `POST /knowledge/{id}/documents` | multipart上传并异步解析 |
| `POST /knowledge/documents/{id}/retry`、`DELETE /knowledge/documents/{id}` | 解析重试、移除资料 |
| `POST /artifacts/{id}/preview` | project_id、mapping生成变更清单，不写工程 |
| `POST /applications/{id}/apply` | 原子、幂等采纳，并发冲突409 |
| `GET /artifacts/{id}/export` | 完整Markdown |
| `POST /media/{id}/confirm` | 明确确认后提交，重复确认返回同一记录 |

选择项`selections`包含skill_id/expert_id（资源版本ID）、knowledge_ids及model_id。消息块为markdown/tool/question/citations/artifact/approval；问题块结构`{type:"question",question:{id,title,type,options,allow_custom}}`，题型single/multiple/text，选择题options为2–4项、每项可带description（2026-10-29）。SSE包含status/text/snapshot/done/terminal，带递增seq。账号外内容404、无效输入400、并发冲突409。LLM管理配置新增可选assistant_models，省略保留已有目录，空列表回退默认模型。

模型能力（2026-10-29）：`GET /catalog` 的每个模型新增 `capabilities`（`provider`、`native_tools`、`structured_output`、`prompt_cache`、`web_search`、`usage_reporting`、`degraded`）。`selections` 新增可选 `web_search`，缺省 `false`；仅当所选模型 `web_search=true` 时本轮请求才带 `enable_search`。消息块新增 `{"type":"usage","usage":{"prompt_tokens","completion_tokens","total_tokens","cached_tokens","requests"}}` 与 `{"type":"web_search","results":[{"title","url","site"}]}`，均附在 Markdown 之后。支持原生工具的模型直接使用 functions / tool 消息，`ask_question` 与 `cite_sources` 归一为既有问题块与引用块；不支持或上游拒绝时自动回退原 JSON envelope，接口语义不变。

每轮`run.production_recipe`独立冻结工程制作配方；结构化动作`project_read`可带`stage`读取对应规范。绑定了阶段规范时，`create_draft`必须在读取该阶段后执行。它与`selections.skill_id`互不替代，不改变旧制作配方配置。

验证：`python -m unittest backend.tests.test_director_assistant`及前端构建/5173桌面回归。回滚：关闭`ZLY_AI_VIDEO_STUDIO_DIRECTOR_ASSISTANT_V2`并重启，不删数据。详见[助手说明](导演台智能助手V2.md)。

更新日期：2026-10-21（MCP 连接 V1；旧接口章节保留原基线）

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
- 除 `/api/health`、`/api/auth/status`、`/api/auth/setup` 和 `/api/auth/login` 外，业务接口都需要 `zly_ai_video_studio_session` HttpOnly Cookie。所有写操作还需要登录响应中的 `csrf_token`，通过 `X-CSRF-Token` 请求头提交。例外是 MCP 协议端点：`/api/mcp` 使用 OAuth Bearer Token，`/api/mcp/oauth/*` 与 `/.well-known/oauth-*` 按 OAuth 规范匿名访问；`/api/mcp/info`、连接管理、参考图和授权确认仍走登录 Cookie + CSRF。
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
| `PATCH` | `/api/auth/profile` | 修改当前账号的显示姓名；登录账号与会话不变。 |
| `GET/POST` | `/api/admin/users` | 管理员读取或创建员工账号。 |
| `PATCH` | `/api/admin/users/{user_id}` | 调整姓名、角色或启停账号；角色与启停仍按管理范围限制。 |
| `POST` | `/api/admin/users/{user_id}/reset-password` | 重置初始密码并撤销该用户会话。 |
| `GET/PUT` | `/api/admin/providers/comfy` | 超级管理员读取或保存 ComfyUI 连接地址。 |
| `POST` | `/api/admin/providers/comfy/test` | 超级管理员测试当前输入的 ComfyUI 地址，不必先保存。 |
| `GET` | `/api/modes` | 获取工作流能力注册表、图片尺寸和提示词预设。 |
| `GET` | `/api/modes/{mode_id}` | 获取一个工作流在 `POST /api/jobs` 中的完整参数契约。 |
| `POST` | `/api/jobs` | 提交一个生成任务。 |
| `POST` | `/api/jobs/{job_id}/upscale` | 旧生成页的独立 VSR 超分入口，已下线（导演台改用「智能超清」）；接口与 `nvidia-rtx-vsr` / `seedvr2-upscale` 工作流暂保留给历史任务，前端不再调用。 |
| `GET` | `/api/upscale/capabilities` | 查询当前 ComfyUI 可用的旧超分引擎（RTX VSR / SeedVR2 节点与模型），缓存 30 秒；前端已不再调用。 |
| `GET` | `/api/jobs` | 按创建时间倒序读取任务列表。 |
| `GET` | `/api/jobs/{job_id}` | 查询单个任务的进度、状态和输出。 |
| `POST` | `/api/jobs/{job_id}/cancel` | 停止排队中、生成中或已中断的任务。 |
| `GET` | `/api/library` | 列出当前用户已成功生成的资源元数据（数组，兼容旧调用；最多读取最近 500 个任务）。 |
| `GET` | `/api/library/query` | 分页检索作品库媒体：`q`、`kind`、`limit`、`offset` 与精确 `job_id`/`generation_item_id`/`output_index`；返回 `items/total/has_more/counts`。 |
| `POST` | `/api/mcp` | MCP Streamable HTTP 入口，使用 OAuth Bearer Token；提供 20 个 `studio_*` 工具（含剪辑与成片导出）。 |
| `GET/POST` | `/api/mcp/oauth/{authorize,register,token,revoke}` | OAuth 2.1 + PKCE 授权、动态注册、令牌与撤销端点；发现元数据见 `/.well-known/oauth-*`。 |
| `GET` | `/api/mcp/info` | 读取 MCP 启用状态、对外地址、传输方式和作用域。 |
| `GET/DELETE` | `/api/mcp/connections[/{id}]` | 列出或撤销自己的 MCP 授权连接。 |
| `GET/POST` | `/api/mcp/references` | 列出或上传自己的 MCP 参考图；单张 ≤ 50 MB。 |
| `GET/POST` | `/api/mcp/authorization-requests/{request_id}` | 授权页读取待确认请求并提交允许/拒绝。 |
| `GET` | `/api/admin/providers/model-presets` | 超级管理员读取统一的官方服务预设，无需供应商 Key。`presets` 提供地址、Key/价格来源链接、核对日期及独立的 `chat_models` / `vision_models`，型号 `free=true/false/null` 对应免费/付费/价格未知；当前包含智谱官方。 |
| `POST` | `/api/admin/providers/llm/models` | 超级管理员向上游拉取模型目录；硅基流动对照模型广场价格 0 / Free 筛选免费模型。智谱官方准确型号可回退到已核对价格，上游明确付费优先；输入和输出同时为零才据价格判为免费。 |
| `GET` | `/api/admin/providers/vlm` | 超级管理员读取 VLM 视觉模型配置。可选 `llm_base_url` 表示复用开关开启后将使用的 LLM 地址，不含密钥；`base_url` 仍是当前生效地址。 |
| `PUT` | `/api/admin/providers/vlm` | 超级管理员保存 VLM 视觉模型配置。可选 `use_llm_credentials` 复用 LLM 页 Base URL / Key，模型名仍在本页。 |
| `POST` | `/api/admin/providers/vlm/test` | 测试 VLM 视觉模型连接。 |
| `POST` | `/api/admin/providers/vlm/models` | 拉取上游目录并筛选名称含 VL/Vision 的视觉模型。 |
| `GET` | `/api/vlm/status` | 查询视觉模型是否可用及当前模型名。 |
| `GET` | `/api/llm/status` | 查询文本大模型是否可用。`supports_vision` 表示写稿路径能否附图；`authoring_vision` / `analysis_vision` 分别给出写稿与反推/拉片路由。 |
| `POST` | `/api/llm/optimize-prompt` | 按工作流/H3 风格技能/可选技能包优化提示词，不创建生成任务。服务端按 `workflow_id` 的参考图模式与数量选择 T2VA / I2VA / FL2VA / Ref2VA；R2V 输出官方六段式。可选 `duration_seconds`（1-60，缺省 5 秒）用于时间码与首尾帧对齐。可选 `skill_pack_id`（须为 `GET /api/skill-packs` 中的 id）。可选 `image_urls`（最多 8 张）；解析器可看图时带图优化，否则只写张数。视频响应含 `optimized_prompt`（英文，用于生成）与 `optimized_prompt_zh`（中文对照，仅展示；译文缺字段时自动重试一次，仍不完整或翻译失败为空串）。模型输出中的思维链不会进入 `optimized_prompt`，无法提取完整 H3 提示词时接口报错。 |
| `GET` | `/api/skill-packs` | 列出导演台技能包配方（含空 id 的默认配方「H3 官方六段式」，含 `summary` / `author` / `cover`）。空 id 表示不绑定 Plaza 配方，工坊写稿直接按官方 H3 Skill 用大模型装箱。`cover` 仅为 http(s) 地址，选择页热链播放。首页新建与项目顶栏用此列表绑定 `extra.skill_pack_id`。Plaza 短剧模板不是生成页 H3 风格芯片。 |
| `POST` | `/api/llm/analyze-subject` | 上传主体参考图提取外貌描述。默认走 VLM；VLM 未开且 LLM 可看图时回退 LLM。 |
| `POST` | `/api/llm/reverse-prompt` | 提示词反推：上传一张参考图（multipart `image`，≤8MB），按 `media_type`（`video` / `image`，缺省 `video`）反推出可直接用于生成的提示词，返回 `chinese_prompt` 与 `english_prompt`（二者互为回退，不会同时为空）。可选 `hint`（≤200 字）补充反推侧重点。看图路由与主体分析一致（VLM 优先，可看图 LLM 兜底）；未配置看图模型返回 **503**，非图片或超限返回 **422**。由「AI 工具 → 提示词反推」工具页调用，结果可一键填入生成页创作框。 |
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
| `PUT` | `/api/projects/{project_id}` | 更新导台2项目。可单独提交 `extra` 合并进 `settings.extra`；只改 `settings` 时保留已有 extra。 |
| `GET` | `/api/projects/{project_id}/documents` | 列出内容库文档。`analysis.episodes[]` 含程序切集结果：`episode_num`、`body`（本集 Markdown）、`shots`（出片镜，含 `duration_sec`）、规划成功时 `shots_source=llm`。进行中的镜头规划带 `shot_plan_job_id`，文档 `status` 为 `planning`。导入后未确认画幅时 `status` 为 `awaiting_aspect`，并带 `aspect_hint`（`suggested` / `hits` / `conflicts`）。 |
| `POST` | `/api/projects/{project_id}/documents` | 导入或粘贴剧本文档。JSON：`raw_text`，可选 `filename` / `spine_template` / `visual_style` / `input_mode`（缺省 `paste`）。程序按 `# 第N集` 切集（不改集号），每集写入 `body` 后立刻返回 200，**不**自动入队 `shot_plan`。需要规划时文档 `status=awaiting_aspect`，响应带 `aspect_hint` 与 `needs_shot_plan`。`input_mode=ai_pipeline` 不规划。 |
| `POST` | `/api/projects/{project_id}/documents/{doc_id}/shot-plan` | 确认成片画幅后入队 `shot_plan`。JSON 可选 `aspect_ratio`，写入 `settings.extra.workshop_aspect_ratio` 并作为规划权威画幅。**202** 返回 `job_id`。AI 流水线或已全部 `shots_source=llm` 返回 400；已有进行中任务返回原 `job_id` 并标 `duplicate`。 |
| `POST` | `/api/projects/{project_id}/documents/{doc_id}/asset-extraction` | 2026-11-04 新增：入队 `asset_extraction` 后台拆解任务，**202** 返回 `{ job_id, document_id, status }`。同一文档已有进行中任务返回原 `job_id` 并标 `duplicate=true`；文档不存在或正文为空 **400**。进度订阅 `GET …/jobs/{job_id}/events`；拆解完成后按 `append` 语义写入资产库。同步版 `POST …/documents/{doc_id}/transfer-assets` 保留，响应含 `transferred` / `total` / `skipped` / `skipped_count`。 |

| `GET` | `/api/projects/{project_id}/jobs` | 列出项目任务；多段渲染的瘦列表含 `render_progress={total,completed,current}`，不展开完整 graph 或草稿。任务类型包括 含 `image_generation` / `video_generation` / `h3_prompt` / `shot_plan` / `asset_extraction` / `ai_pipeline` / `tts_generation`。列表 `payload` 只保留工坊/表格需要的字段（镜号、状态、结果 URL、资产节点 `asset_id` / `target_type` / `identity_id`、精简 `shots`/`stream`），不含草稿、`request_body`、原始 `payload_json`。`asset_extraction` 额外保留 `document_id` / `filename` / `phase` / `message` / `chars` / `transferred` / `total` / `skipped` / `skipped_count` 供剧本页恢复进度与任务中心回显。`prompt_source=program_preview` 的程序装箱预览任务额外保留 `prompt_warning` 与 `shots[].sequence` / `shots[].prompt`，供工坊素材组回显本次提示词；其他任务（含已保存 H3 提示词）的列表 `shots` 仍不含提示词文本。`shot_plan` 的 `payload.document_id` 用于跳回内容库该文档。 |
| `GET` | `/api/projects/{project_id}/jobs/{job_id}` | 读取单条任务的完整 `payload`（含草稿、提示词、`request_body`）。不存在 **404**。 |
| `GET` | `/api/voice-bank` | 读取内置短剧配音声线目录（IndexTTS 官方示例）。 |
| `GET` | `/api/voice-bank/{preset_id}/audio` | 读取内置声线 wav。未知 id **404**。 |
| `POST` | `/api/projects/{project_id}/assets/{asset_id}/generate` | 资产生图。JSON `target_type`：`identity` 为角色设定板（16:9、2K、`2048x1152`），不要求已有头像；无外观描述且无原片参考图时 **400**。参考图顺序：原片 > 其他已出图造型（排除当前 look）> 仅当两档都没有时才用旧 `avatar_url`。`avatar` 仍可用但不在界面露出。头像 / 场景 / 道具分辨率仍为 1K。 |
| `POST` | `/api/projects/{project_id}/assets/{asset_id}/images` | 2026-11-03 新增制作图上传；multipart `file`、`target_type`、可选 `identity_id`。target 为 identity / scene_master / scene_reverse / scene_pano / prop_reference / prop_turnaround / prop_detail。返回完整资产；先校验资产类型及身份，再校验真实 JPEG/PNG/WebP/GIF 且非空、≤10 MiB，不合法 **400**。只更新指定制作槽位，首造型或主图时同步 image_url；不添加 source_references。沿用 mutating_user / 七牛存储。 |
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
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/generate-video` | 按工作流入队整集或逐镜视频。JSON 可带注册表 options，除数字人口播（`minimax-h3-avatar`）外的 H3 工作流支持 `refine_enabled`（开启后一采 0.4 MP）、`refine_quality`（`1.0` / `2.0` MP，默认 `1.0`）、`refine_quality_mode`（`auto` 默认自动降档 / `force` 强制目标清晰度）与 `refine_preview`（平台托管：开启二采固定先预览，显式传 `false` 会被忽略；整集直出强制连续两段式，不再返回 400）。`prompt_mode` 默认 `h3`：优先复用有效提示词，缺失、失效或过薄时由同一个视频任务自动准备正式 H3 指令后继续生成；不静默回退程序装箱；`program` 仅用于程序装箱预览（不调用大模型）。历史 `prepare_keyframes` 已移除，传入会被当作未知选项忽略。数字人口播（`minimax-h3-avatar`）是单段音驱管线，二采改走 Director 图会脱离口播音频，因此提交任一 `refine_*` 参数返回 422。`upscale_after` 已停用并被忽略，不再自动超分。**202** 返回 `job_id`。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-video` | 单镜入队。可带 `refine_enabled` / `refine_quality` / `refine_quality_mode` / `refine_preview`，两段式在同一个任务内完成；`refine_preview` 由平台托管，开启二采固定先预览。`prompt_mode` 默认 `h3`，该镜没有合格指令时异步自动准备后出片；`program` 为预览路径。成功后原片写入 `video_url` 并归档到 `video_takes`（默认采用最新）。**202**。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/compose` | 拼接各镜 `video_url` 为分集成片。JSON 可选 `mix_dubbing`（缺省 true）：内心/旁白叠到对应镜，`mix=replace` 的开口句静音该镜 H3 原声。半解说包旁白未配音 **400**。**202** 返回 `job_id`。拼接片不套用生成期二采，也不自动超分。 |
| `GET` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/video-takes` | 只读列出本镜真实成功版本，返回 `{ takes, adopted_id, adopted_url }`。合并 Beat 已归档版本与本镜 `shot`/`selection` 成功任务；`takes[]` 包含 `id / url / upscaled_url / created_at / job_id / scope`。排除整集直出、合成与独立超分任务，不写库、不生成。预览不改变采用版。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/video-takes/adopt` | 采用本镜一条成功成片为正式原片。JSON `{ url }` 或 `{ job_id }`。校验确属本镜 `shot`/`selection` 成功抽卡后写 `video_url`；该 Take 已有 2x 则同步 `upscaled_video_url`，否则清空。采用的那条留在 `video_takes`。不属于本镜 **400**。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/upscale` | **智能超清**：复放本镜留存的一采生成图（同一 seed / 提示词快照 / 时间线），只在 Director 图上追加二采节点重跑，不做独立的 VSR 放大。JSON body 忽略 `engine` 与请求里的 `refine_*`，二采画质与 `upscale_method` 一律取本镜生成任务的快照，保证同一镜头反复超清得到同一画幅。原片 `video_url` 不变，结果写入 `upscaled_video_url` 并挂到当前采用 Take，超清结果不单独成 Take。**409** 同一成片已有在跑的超清；**422** 的中文原因包括：整集直出/拼接片没有可复放的分镜生成图、原任务未留存生成图（多段切分或旧任务）、数字人口播镜头、本镜生成时已开启二采精修、找不到原始生成任务。**202** 返回 `job_id`。 |
| `POST` | `/api/projects/{project_id}/jobs/{job_id}/upscale` | 对导演台2「全部任务」里已成功的视频生成任务提交**智能超清**，语义与上一致（复放生成图只跑二采）；JSON body 忽略 `engine`。用该任务 `result_url` 作原片；有关联单镜则写回 Beat，结果写 `payload.upscaled_video_url`。**422**：超清任务本身 / 未完成 / 多镜 selection / 整集直出与拼接片 / 无可复放生成图；**409**：同一成片进行中超清。**202**。 |
| `POST` | `/api/projects/{project_id}/documents/{doc_id}/transfer-episodes` | 把内容库该文档的分集/出片镜头写入剧集工坊。JSON `{ mode }`：`overwrite`（缺省）按本剧本重写已有集的 `data_json.beats` 并删除剧本里没有的旧集；`append` 跳过已有集号只补新集。只拷贝文档里已有的出片镜，同步时不再调大模型规划。成功返回 `mode`、`replaced_episodes`、`created_episodes`、`skipped_episodes`、`deleted_episodes`、`transferred_shots`。未知 mode 或未识别到分集返回 400。 |
| `PUT` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}` | 更新单条 Beat。可写 `h3_prompt` 与 `h3_prompt_source`（`manual` / `generated`），以及 `timestamped_zh_prompt`。手动保存的六段出片按原文使用。服务端可写 `video_takes`；前端选用成片请走 `…/video-takes/adopt`，不要直接改 `video_url`。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/h3-prompt` | 剧集工坊素材组：为当前分镜入队 **一个** `h3_prompt` 任务，不再按口型/内心/近景规则拆镜。JSON 可选 `aspect_ratio`，写入 `beat_info` 作为写稿权威画幅（否则读 `extra.workshop_aspect_ratio` / 配方缺省）。未绑技能包时程序从本镜动作/运镜/台词编译六段 Ref2VA。绑定半解说包时由 LLM 一次写出中文八块分秒稿（时间码从本镜 `00:00` 起；可看图时看角色卡/场景卡）和英文六段；配方临时 `skip_program_pack=true` 时出片英文用 GPT 六段原文（规范化 `<Picture>` / `<Subject>`、六段 `name:` 标题，并在 `detailed_description` 补 `[Shot 1]`；内心改成官方 `says in an off-screen voiceover` 且 `</d>` 后闭嘴），不再程序灌水、中文时间码或轿厢句，也不走第二次装箱 LLM；写稿合同写清开口 / 角色内心 / 第三人称旁白三通道与编号表演顺序，无旁白时禁止用内心或开口句充数，也不再把内心折进旁白原文交给模型；内心挂在触发画面时段，表演顺序第 1 句不是内心时禁止写在 00:00 起幅；中文分秒接受小数时间码与标题首字乱码，英文 `<d>` 可省略 `[Chinese]`；同一人连续多句按问号/句号切开后逐字校验；内心口型同步 `says:` 会先修补再校验；半解说包另校验台词去重与 `<d>` 表演顺序；中文分秒仍写入 `timestamped_zh_prompt`。说明句 stub（例如只回「官方八块中文分秒稿与」）会打回重写，失败文案不再展开缺标题清单。看图写作对 GPT-5 / o 使用 `reasoning_effort=none`、`max_tokens=16000`。中文或英文未通过校验则任务 `failed`，`payload` 含 `author_errors` / `vision_*` / `author_raw_draft` 与残稿，不覆盖 Beat，不回退无时间码骨架。R2V 参考图为角色设定板 + 场景卡，不再追加任何分镜关键帧或其裁切格（2026-11-04 三联关键帧下线）。设定板只锁身份/发型/服装，禁止把分格、白底、重复小人带进镜头。工坊若已有拆开的出片镜，`payload.merge_as_one=true` 则合并回一条再生成。`h3_prompt_source=manual` 的镜按原文出片。**202** 返回 `job_id`。生成过程可通过 `GET /api/projects/{project_id}/jobs/{job_id}/events` 直播思考与正文。 |
| `GET` | `/api/projects/{project_id}/jobs/{job_id}/events` | 按 `job_type` 订阅任务 SSE。`h3_prompt`：`status` / `reasoning` / `delta` / `done` / `error`。`shot_plan`：另有 `episode_done`（该集 `shots` 已写入 `analysis_json`），`status` 含第几集/共几集。`asset_extraction`：`status`（`phase` / `message` / `chars`）、`done`（`transferred` / `total` / `skipped` / `skipped_count`）、`error`，空闲时 `keep-alive`。可用 `since` 或 `Last-Event-ID` 续传。 |
| `POST` | `/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-triptych` | **已删除（2026-11-04 镜头三联关键帧整体下线）**。同批删除的还有本集批量入队 `POST /api/projects/{project_id}/episodes/{episode_id}/generate-images`，以及 2026-11-03 已下线的 `.../generate-sketch` 与 `.../generate-render`；分镜级生成路由只剩 `h3-prompt` 与 `generate-video`。历史 `beat_sketch` / `beat_render` / `beat_triptych` 任务行仍可回显，点「重试」统一返回「镜头生图（草图 / 渲染图 / 三联关键帧）已下线，请直接为本镜生成 H3 提示词后用角色卡与场景卡出片。」 |
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

2026-11-03：上述 Beat 更新接口支持 `workshop_prompt_document`，为仅含 `paragraph`、`text`、`hardBreak`、`assetReference` 的 Tiptap JSON 文档。引用 attrs 为 `{ id, lookId, label, kind }`；服务端按本工程真实资产和造型校验，派生绑定及 `video_prompt_zh`，按“对白：”“镜头：”段回写对白和镜头，其余正文回写动作。一个片段绑定一个场景、一个角色只用一个造型，冲突返回 400；内容或引用变化会清空旧 H3 提示词与校验状态，保留已有视频。`null` 清除该文档供旧表单编辑兼容。原有 JSON 行锁合并方式、鉴权及 CSRF 规则不变。

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

生图条目（`media_type=image` 且 `id` 以 `grs-` 开头）另含 `is_default`：列表顺序完全等于管理员在「GRS 图片供应商」目录里的排序，`is_default=true` 的那一项才是创作页预选与导演台自动出图使用的模型，消费方不得把首位当默认。同批条目还含 `credit_cost`（GRS 平台标价的单次消耗积分，整数；未取到价格时为 `null`），只用于展示，不属于 `POST /api/jobs` 的提交参数。

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
| `prompt` | string | 是 | 创作提示词；H3 视频须使用英文并直接提交生成。 |
| `display_prompt` | string | 否 | 中文展示提示词；与 `prompt` 不同时随轮次保存，`GET /api/jobs/{job_id}` 在轮次中回显。仅影响界面展示，不参与生成；轮次接口同样支持。 |
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

### `POST /api/jobs/{job_id}/upscale`（旧生成页，已下线）

导演台2 的「智能超清」（`POST /api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/upscale`）改用复放生成图只跑二采以后，前端不再调用本接口。接口本身保留，仍会新建一条独立的 VSR 超分任务，供历史任务与外部调用：JSON body 可选 `{"engine":"rtx"}`（缺省）或 `{"engine":"seedvr2"}`：

- `rtx`：`nvidia-rtx-vsr` 任务（RTXVideoSuperResolution，固定 2x / ULTRA，秒级）。按原片宽×高×帧数预估显存，与当前连接 ComfyUI `/system_stats` 的总显存比较，过大时返回 `422`（读不到显存则不编造限额）。当前连接的 ComfyUI 若未安装 `RTXVideoSuperResolution`（包名 `Nvidia_RTX_Nodes_ComfyUI`）也返回 `422`。实测对 H3 成片的细节提升有限，2026-11-02 起不再是「智能超清」的实现方式。
- `seedvr2`：`seedvr2-upscale` 任务（ComfyUI 原生 SeedVR2 3B Int8，生成式 2x 高清增强，分钟级）。不套用 RTX 显存门槛，由节点按当前显存自动切分 latent；当前实例缺少 SeedVR2 节点、`seedvr2_3b_int8_convrot.safetensors` 或 `seedvr2_ema_vae_fp16.safetensors` 时返回 `422`。

原片任务不变；超分结果是新任务的输出。同一原片已有排队中、生成中或已中断的超分时返回 `409`。不要通过 `POST /api/jobs` 直接创建 `nvidia-rtx-vsr` / `seedvr2-upscale`（两个工作流均 `hidden_from_catalog`）。这是针对已成功成片的手动后处理；H3 生成参数不再提供自动超分开关，`refine_enabled` / `refine_quality` 是生成期二采，不创建独立的超分任务。

```powershell
Invoke-RestMethod -Method Post `
  -Headers @{"X-CSRF-Token" = "<login response csrf_token>"} `
  -ContentType "application/json" `
  -Body '{"engine":"seedvr2"}' `
  http://127.0.0.1:7865/api/jobs/WvhSEuCWne1d/upscale
```

### `GET /api/upscale/capabilities`（旧生成页，前端已不调用）

返回 `{ engines: [{ id, label, available, reason }], default: "rtx" }`。`rtx` 探测 `RTXVideoSuperResolution` 节点；`seedvr2` 探测 5 个 SeedVR2 原生节点、UNETLoader 的扩散模型枚举与 VAELoader 的 VAE 枚举。结果缓存 30 秒。智能超清不再需要引擎能力探测，因此前端不再请求该接口。

## 导台2 项目内容库（`/api/projects`）

导演台2 内容库走 `POST /api/projects/{project_id}/documents`，不是 `/api/xiaji/documents`。集边界只认台本 `# 第N集`（无集头则整篇第 1 集）；剧本里的 `### 镜头` 只当素材。粘贴/文件导入立刻落库并扫描 `aspect_hint`，文档 `status=awaiting_aspect`，**不**自动入队 `shot_plan`。确认成片画幅后 `POST …/documents/{doc_id}/shot-plan`（JSON 可选 `aspect_ratio`）写入 `settings.extra.workshop_aspect_ratio` 再逐集规划（H3 合同 5–15 秒），成功则 `shots_source=llm`。规划 prompt 以确认画幅为权威。过程通过 `GET …/jobs/{job_id}/events` 直播；内容库按集显示瘦进度，当前集用残缺 JSON 解析出的镜头卡逐张出现（思考默认折叠，不展示 JSON），`episode_done` 后换成归一化结果，规划中禁止同步工坊。全部任务有「镜头规划」Tab，可按 `payload.document_id` 跳回 `/director2/projects/:id/content?mode=manual&doc=:docId&tab=episodes`。AI 流水线回写的文档（`input_mode=ai_pipeline`）不二次规划。`POST …/transfer-episodes` 把文档已有出片镜写入剧集工坊，同步时不再调大模型。`POST …/h3-prompt` 点哪条入队一个任务，不再按口型/内心/近景规则改镜头列表。工坊 `POST …/generate-video` 可带 `options.refine_enabled` / `options.refine_quality` / `options.refine_quality_mode`：除数字人口播外的 H3 工作流开启后一采 0.4 MP、二采按策略输出（`auto` 默认降档，`force` 严格 1.0 / 2.0 MP）；`options.prompt_mode` 默认 `h3`，缺少或失效的正式指令在同一视频任务内自动准备（分镜生图链路已于 2026-11-04 全部下线，出片参考图只有角色卡与场景卡）；`program` 仅作程序装箱预览；`upscale_after` 已停用，`POST …/compose` 不套用二采也不自动超分。逐镜/选中镜成功后把旧原片归档进 `video_takes`，`video_url` 默认采用最新；成片 Tab 用 `POST …/beats/{beat_id}/video-takes/adopt` 选用历史抽卡。已出片镜头可 `POST …/beats/{beat_id}/upscale` 做**智能超清**：复放本镜留存的生成图、只追加二采节点重跑，结果写入 `upscaled_video_url` 并挂到当前采用 Take；整集直出、拼接片、多段切分与数字人口播镜头没有可复放的分镜生成图，返回 422。全部任务已成功视频可 `POST …/jobs/{job_id}/upscale`，同一语义。

## 导台2 内容库与资产库

导台2 以项目为容器。先 `POST /api/xiaji/projects` 再建内容库和资产。列表、上传、粘贴、同步、新建资产均需 query `project_id`，且项目必须属于当前登录用户。文稿与章节按项目隔离。`POST /api/xiaji/documents` 为 `multipart/form-data`（`file` 必填，可选 `title`、`art_style_id`、`replace`）。`POST /api/xiaji/documents/paste` 为 JSON（`text` 必填，可选 `title`、`art_style_id`、`replace`）。`replace=true` 时先清空本项目内容库、资产、剧集和大模型任务，再写入新文稿。二者都同步规则切分章节、调用已配置 LLM 分析，并在成功后写入**同一项目**的资产库。无章节标题时整篇为一章且状态为 `review_required`，否则 `indexed`/`ready`。精品剧识别「第X集 / Episode N」为剧集边界（与「第N段」相同，优先于按字数估算），正文按一行一个镜头进入后续脚本 Beat；对白行「角色：台词」、画面行各占一行。`PUT .../chapters` 整表替换章节顺序与正文。项目 `settings.art_style_id` 与内容库所选画风共用导演台 `GET /api/director/art-styles` 目录，可为空。`settings.visual_style` 为 sourceXd 六项风格（默认 `chinese_period_drama`），资产生图、镜头草图/精绘和视频提示词始终写入对应风格说明；仅在选择画风时附加目录 `promptPrefix` 与预览参考图。新建项目会预填 `GET /api/xiaji/art-style` 的用户默认画风。

资产库 `xiaji_assets` 按项目隔离（唯一约束 `project_id + kind + name`），类型为 `character` / `scene` / `prop` / `voice`。角色含面部提示词、造型列表和五档声线槽位；场景含环境提示词，并按 `scene_view=master|reverse|panorama` 分别生成正面源图、背面和 2:1 的 360 全景（提示词对齐虾塘场景合同，背面/全景不覆盖正面 `image_job_id`）。生成背面时把正面源图作为 `jobs.references` 第 1 张（REFERENCE 1）；生成 360 时按顺序传入正面、已有背面。无正面源图时背面和 360 入队均 **422**。道具按 `prop_view=master|turnaround|detail` 分别生成主视图、1x3 转面三视图和细节特写（提示词与画幅对齐 sourceXd `nanobanana_prop.py`：16:9、产品摄影白底、转面为 FRONT/SIDE/BACK 三面板；工作台 GRS 分辨率用 1K。转面/特写必须已有主视图，把它作为 REFERENCE 1，且不覆盖主视图 `image_job_id`；无主视图时 **422**）。`voice` 名称为「解说」表示旁白。`POST /api/xiaji/assets/{id}/generate-image` 校验已启用 GRS 工作流后写入 `jobs` 与 `xiaji_asset_media`（`media_kind` + `slot` + `job_id`）并返回 **202** `{ ok, job_id, status: "generating", asset }`（`model` 为空则取默认启用项；请求体可带 `style` / `art_style_id`、`ethnicity`、`look_id`、`scene_view`、`prop_view`）。画风解析为请求 `art_style_id`/`style` → 资产 `definition.art_style_id` → 项目 `settings.art_style_id`；命中目录后把 `promptPrefix` 写入生图提示词，并写回资产 `art_style_id`。角色肖像还会把画风 JPEG 预览作为 `jobs.references` 第 1 张；预览加载失败则 **422**。新建资产与内容库 sync 只给空的 `art_style_id` 写入导入/项目画风，不覆盖已保存画风。旧 `visual_style` 粗粒度代码不再作为生图前缀。角色造型对齐 sourceXd 身份图：必须已有肖像并作为第 1 张参考图（身份锚点），options 为 16:9 / 1K，提示词为四面板 Identity Lock；无肖像或无服装外观描述时 **422**。造型只更新该 look 的 `job_id` 和 media 行，不覆盖肖像 `image_job_id`。请求内不提交、不等待 GRS；worker 在 `BackgroundTasks` 中 `enqueue_generation`。前端用 `GET /api/jobs/{job_id}` 查终态，再 GET 资产列表由 `_hydrate_asset` 按 media 槽位写回：`portrait`/`master` → `image_url`，`look` → 对应造型 `image_url`，分视角写入 `back_image_url` 等字段。资产生图回填按 `xiaji_asset_media` 槽位进行。`GET /api/xiaji/jobs?project_id=` 列出该项目全部任务：资产生图（肖像/造型/分视角）、镜头草图/精绘/视频，以及大模型调用（内容导入分析、生成脚本、声线定义）。生图任务含状态、提示词、参考图、options 与回调 URL；LLM 任务含系统/用户提示词、完整 `messages`、模型与采样参数、业务入参和模型输出。删除项目时同时删除 `xiaji_llm_jobs`。

## 导演台工程

导演工程与生成任务隔离，员工只能读写自己的记录。`POST /api/llm/split-script` 只即时返回分镜 JSON，不入库；前端把原文 `source_script` 与 shots 一并 `POST`/`PUT` 到 `/api/director/projects`。列表接口只返回 `has_source_script` 与 `kind`，不回传全文。手改空文案后 `PUT source_script` 仍会落盘。

`GET /api/director/art-styles` 返回 9 类 34 条画风（`id`、`name_zh`、`name_en`、`category`、`description`、`promptPrefix`、`imageUrl`、`keywords`）。`promptPrefix` 与 OpenDirector 公开种子一致。`imageUrl` 一律为同源 `/api/director/art-styles/{id}/preview`，浏览器不直连 `files.seme.cc`。`GET /api/director/art-styles/{style_id}/preview` 需要登录，优先返回本地缓存 JPEG；缺失时由服务端从 OpenDirector CDN（`style_01.jpg`–`style_34.jpg`）拉取并写入 `backend/app/director_catalog/previews/`。未知 id 返回 404。Recipe payload 的 `artStyle` 必须使用目录中的 id；保存时服务端用目录覆盖名称、`promptPrefix` 与预览地址，禁止自造风格。

`payload.kind`：缺省或旧数据为时间轴；`director_recipe` 含 `script`（title/summary/fullStory）、`artStyle`、`characters`、`locations`、`scenes[].shots`、`agentStatus`；`batch_run` 为批量主题裂变；`shot_replication` 为 VACE 参考片复刻。`POST /api/director/projects/{project_id}/convert-to-recipe` 把时间轴 shots 映射为 scenes，不自动改写未请求转换的旧工程。

导演主路径不再走 `POST /api/llm/split-script`（该接口仍保留给兼容/测试，拆分时同样读取 MiniMax H3 官方 `h3-prompt-writing` 原文）。`POST /api/director/recipes/run` 顺序调用研究/脚本/画风/分镜/角色/场景/配音/配乐/媒体 9 个 Agent，复用现有 LLM Provider；可选 `agents` 只跑指定步骤（例如 `["script","storyboard"]` 按剧本一次生成全部分镜；该子集里脚本失败仍会继续拆镜，但上游余额不足/欠费会立即停止并返回 HTTP 502，`detail` 含上游原文）。分镜 Agent 必须覆盖完整剧本，通常一次输出 8–24 个独立镜头，失败时不再回退成单条「主镜头」。模型若返回 `[Shot n]` 散文也会拆成镜头。分镜 Agent 读取官方 skill 与 `base-en.txt`，同时生成中文 `description`（界面展示）和英文 `promptText`（官方镜头正文）。点击导演台左栏「镜头设计」（阶段内「设计 / 制作」切换）时，若还没有真实镜头列表，前端会自动按剧本调用上述子集。当前任务写在 `/director/:projectId?stage=`，桌面视图写在 `?view=plan|timeline`（默认方案；手机锁定方案视图），刷新与后退保持位置。桌面剪辑视图读写同一份 `director_recipe`，镜头轨与刻度直接按 `scenes[].shots[].durationSec` 铺开（不先转旧时间轴 shot），出片/静帧/配音/成片仍走现有 `render-shots` / `stills` / `tts` / `mux`，不新增 payload kind。媒体编译把 T2V/I2V 写成 `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`，把 R2V 写成 Ref2VA 六段式。画风只能选自目录。每个 Agent 开始时把 `payload.agentStatus` 写成 `running` 并落盘，因此运行中 `GET /api/director/projects/{id}` 可看到当前步；整次 POST 仍等全部 Agent 结束后才返回。`agentStatus[].message` 是给人看的阶段（例如「正在读剧本」「正在写分镜（已收到 1200 字）」「已写出 12 个镜头」），不是模型 token 或思考过程。`payload.pipelineRun` 记录本次实际跑的 `agents` 与是否仍在运行，供前端按子集计算进度（只跑 script+storyboard 时分母是 2 而不是 9）。思考模式保持关闭。导演对话走 SSE 流式读取：连接超时 20 秒，分块空闲 300 秒，完整分镜可超过原先 180 秒整段超时。分镜生成中 `agentStatus.message` 会更新为「正在写分镜（已收到 N 字）」，不回传原文。`generate-assets` 为角色和场景提交 GRS 生图任务；运行中 `GET /api/jobs` 的 `progress` 按约 2 分钟预期映射到 12–90%，完成时 100%。启用七牛云时，定妆输出会转存对象存储，任务带稳定 `cloud_url`（不含过期签名），并写入 Recipe 的 `imageUrl`；`download_url` 仍为同源 `/api/jobs/.../download`。`render-shots` 把本镜用到的定妆图编成最多 9 张 `<Picture n>` 参考图，再按 Recipe 的 `videoWorkflowFamily` 提交该族 T2V/I2V/R2V（缺省 `official_h3`；有人物/场景定妆走该族 R2V，仅有首帧/上一镜尾帧走该族 I2V，都没有走该族 T2V）；云端定妆会先拉到暂存再作为参考。配置了 LLM 时，入队前会先把镜头标为 `queued` 并调用大模型润色最终 H3 提示词，因此 `GET /api/director/projects/{id}` 在 `render-shots` 尚未返回时也能看到排队；未知 `shot_ids` 返回 422。勾选 `usePreviousEndFrame` 时编译器把上一镜 `endFrameUrl`（没有则用上一镜静帧）接到本镜首帧。`POST .../generate-stills` 复用定妆同一 GRS 通道，prompt 为本镜描述 + 画风 + 角色/场景图，结果写入 `stillJobId`/`stillUrl`。`POST .../frames` 保存首尾帧到 `data/uploads`。员工级资产库 `GET/POST /api/director/library-assets` 保存人物/场景/道具（图 + prompt），按登录用户隔离；`POST .../from-recipe` 从当前 Recipe 快照入库，`POST .../insert-library-assets` 复制进 `characters`/`locations` 并写 `libraryAssetId`。不引入系列/分集层级。`POST /api/director/batches` 把主题裂变成多条脚本并并行排队所选工作流族的文生（`video_workflow_family`，缺省官方 H3），不强制角色参考。`POST /api/director/batches/{project_id}/render` 对已有批量条目重新排队；`item_ids` 为空时提交全部条目。

导演台提交 `POST /api/jobs` 时：预览/成片各自读取工程 payload 的 `previewQuality`/`previewSpeed` 与 `finalQuality`/`finalSpeed`。默认预览 `quality=0.4`、`speed=fast`；默认成片 `quality=1.0`、`speed=balanced`。可选 MP 为 0.4 / 0.7 / 1.0 / 2.0，速度为 fast（4 步）/ balanced（8 步）/ quality（20 步）。工程级 `weightProfile`（`full` / `pruned`，默认 `full`）写入 `options.weight_profile`，预览与成片共用。旧工程无新字段时，成片 MP 仍跟 `canvasTier`，模型体积仍为完整权重。批量接龙与整段提交使用成片档。Recipe 分镜保存时始终规范化 `camera`（缺省中景前推）并保留 `error`；`POST .../render-shots` 按请求的 `render_pass` 入队，并把该档写入 `takes[].renderPass`。手改后的 `description` 进入编译 prompt（无 `promptText` 时回退 `description`）。检查器文案 Tab 的「中文镜头正文」即镜头中文 `description`（同时是静帧提示与编译回退来源），与「英文镜头正文」一一对应；`POST /api/director/recipes/{project_id}/shots/{shot_id}/translate-prompt` 用已配置 LLM 把它（或请求体 `text`；兼容字段 `promptTextZh` 优先于 `description`）按官方 skill 翻译成英文 `promptText`（对白/画面文字保留原语言、人名不翻译），只返回 `{promptText}` 由前端写回；LLM 未配置返回 503。

Recipe 第三版声音层：`payload.audio`（配乐 URL/音量/淡入淡出）、`payload.subtitles`（位置/字号/描边）、`payload.export`（mux 状态与时长）。`POST .../tts` 按分镜对白调用独立 TTS（OpenAI 兼容 `/audio/speech`，可复用 LLM 凭据），结果写入 `shots[].ttsStatus`/`ttsUrl`，不是 SQLite jobs。`POST .../mux` 只拼接失败/中断/停止之外的镜头，优先 `approvedTakeId`；本机未找到 ffmpeg/ffprobe 时返回 503。剪映草稿接口不变。`GET .../export.fcpxml` 与 `export.edl` 由镜头入出点、对白和音频轨生成。

## 作品库与媒体

### `GET /api/library`

返回完成任务的输出，并补充 `results` 中尚未写入任务记录的历史文件。每项包含 `kind`、`path`、`label`、`job_id`、`job_title` 与 `created_at`；历史文件的 `job_id` 为 `null`。响应仍是数组，供旧调用方兼容；画布素材面板已改用下面的分页接口。

### `GET /api/library/query`

分页检索当前账号可用的图片/视频产物。查询参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `q` | string，≤100 | 大小写不敏感的包含匹配，覆盖任务标题、任务提示词、素材标签、素材路径、任务号与生成项号 |
| `kind` | `image` / `video` | 只返回指定类型；省略时返回全部 |
| `limit` | int，1–100，默认 40 | 每页数量 |
| `offset` | int，0–1,000,000，默认 0 | 分页偏移 |
| `job_id` | string，≤120 | 精确匹配来源任务号 |
| `generation_item_id` | string，≤120 | 精确匹配生成项 |
| `output_index` | int，0–999 | 精确匹配生成项输出序号 |
| `user_id` | string | 仅管理员可用；`all` 表示全部账号 |

返回：

```json
{
  "items": [
    {
      "kind": "image",
      "path": "seed-img-001.png",
      "label": "",
      "delivery_status": "pending",
      "download_url": "/api/jobs/job-1/generations/item-1/outputs/0/download",
      "job_id": "job-1",
      "job_title": "示例任务",
      "generation_item_id": "item-1",
      "output_index": 0,
      "created_at": "2026-10-24 10:00:00"
    }
  ],
  "total": 55,
  "limit": 40,
  "offset": 0,
  "has_more": true,
  "counts": { "image": 55, "video": 8 }
}
```

`counts` 在 `kind` 过滤前统计，因此两个分类标签可同时显示总数。`delivery_status` 为 `local` 或 `expired` 的产物不会返回；结果按 `created_at` 倒序稳定排序。接口要求登录，普通员工只能读取自己的作品库。

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

任何已登录账号都可调用 `PATCH /api/auth/profile`（body `{"display_name":"新姓名"}`）修改自己的显示姓名，响应与登录一致并回传最新 `user` 与 `csrf_token`。管理员和超级管理员也可通过 `PATCH /api/admin/users/{user_id}` 修改任意账号的姓名；角色与启停仍按原有管理范围限制（管理员只能调整员工）。姓名只影响展示，登录账号、密码和会话均不变。

任务的每个 `outputs[]` 包含 `delivery_status`。只要输出尚未本地交付（`pending` 或 `cloud`），就会返回短路径 `download_url`，包括部分完成或失败但已落盘的图片；启用七牛云时另有稳定 `cloud_url`（对象域名+键，不含过期签名）。浏览器将响应体写入员工授权目录后调用：

```text
POST /api/jobs/{job_id}/outputs/{output_index}/delivered
X-CSRF-Token: <login response csrf_token>
```

回执成功后 `delivery_status` 变为 `local`，`download_url` 变为 `null`，`data/staging` 暂存和固定 ComfyUI `output` 中记录的原始输出会同时删除。ComfyUI 清理目标必须是 `type=output` 且解析路径位于固定 `Comfyui/output` 根目录，否则回执失败并保留 ZLY AI Video Studio 暂存供重试。该操作表示调用方已经可靠落盘，不可在下载开始前提前调用。未来七牛云 provider 继续使用相同任务输出状态，云端对象定位由 provider 负责，不把七牛 SDK 参数暴露到任务接口。

## 2026-10-20 智能剪辑动作（铺轨 / 精剪 / 引流）

前缀：`/api/projects/{project_id}/smart-edit/{sequence_id}/actions`，sequence_id为分集ID或`main`。当前账号登录必需，POST沿用CSRF。

- `POST /preview`：`{operation:"video_arrange"|"subtitle_arrange"|"audio_subtitle"|"dialogue_cut"|"quick_cut"|"highlight_cut"|"hook_cut",revision:number,session_id?:string|null,strategy?:string|null,asset_ids?:string[]}`。先保存当前编辑，再以该revision生成清单；不修改时间线。`video_arrange`可用`asset_ids`指定顺序；`hook_cut`必须带`strategy`，取值为`conflict_3s`、`climax_only`、`quote_open`、`ending_hook`、`trailer`，其它操作不得携带。`audio_subtitle`不读取分镜对白，自由剪辑（`main`）同样可用。返回`id,status,operation,project_id,sequence_id,base_revision,items,count,append_at,total_duration,skipped_count,missing_video_count,dropped_count,trimmed_count`；`hook_cut`另返回`strategy,strategy_title,principle`；`audio_subtitle`另返回`inaudible_count,replaced_count`（`replaced_count`为被替换的上一次自动字幕数，`skipped_count`为与手工文字或其它文字片段重叠而未铺设的段落数）。剪辑类`items[]`含`asset_id,beat_id,name,start,duration,action`，并带可选`reason`（逐镜保留理由）；`audio_subtitle`的`items[]`含`asset_id,beat_id,segment_id,name,start,duration,reason,action`，`name`即字幕文本，`reason`记录「已按镜头边界收短」「长句已分行」等处理。`extra.understanding`回显理解状态、模型、素材数、`shot_count/shot_analyzed_count/shot_used_count`与`used_count`，供授权弹窗展示镜头级依据；`extra.transcript`回显`status/model/transcribed_at/transcribed_count/used_count/segment_count/audio_seconds`，供授权弹窗展示音轨依据。无转写证据时`audio_subtitle`按状态返回中文错误（未开始、已过期、无语音、失败），不会退回剧本对白。无可用结果时status=`empty`，否则`pending`。
- `GET /{action_id}`：查询账号隔离的清单及执行状态；完成后含`snapshot`，结构沿用剪辑GET的document/revision/draft_key/updated_at。
- `POST /{action_id}/reorder`：仅`video_arrange`，`{asset_ids:[...]}`按新顺序重生成待确认清单。
- `POST /{action_id}/confirm`：按预览的固定目标与版本执行，返回status=`succeeded`及snapshot；重复确认返回同一记录。文档与记录同一事务提交，版本变化409、目标不存在或非本人记录404、非法动作/策略400。

助手SessionCreate/AssistantSession新增可选`context:{kind:"smart_edit",sequence_id}`，project_id必填且与分集匹配；旧会话context为空。详情新增`edit_proposals`，消息新增`{type:"edit_action",action_id}`。LLM工具`editor_read {}`返回素材与`analysis`理解摘要（分集含对白镜头数、对白秒数、高光候选与理由；来自分镜/对白文本，非画面识别），并附用户显式触发后的`analysis.understanding`（状态、模型、素材级条目与内部镜头描述/机位/主体、`detected_shot_count/shot_count/shot_analyzed_count`；未触发或已过期时为空）与`analysis.transcript`（`status/model/transcribed_at/stale/message/media_count/transcribed_count/segment_count/audio_seconds/progress`；未转写时`status=missing`且段落数为0）。`propose_edit {operation,strategy?}`只在冻结的剪辑会话内可用；`hook_cut`必须由用户选定策略，工具不能直接执行授权。`hook_cut`/`highlight_cut`评分会并入已成功的画面理解，授权清单的`reason`带「画面理解：…」并显示理解依据；过期或失败的理解不参与加权。system prompt 规定：用户说「按真实声音/原声/配音上字幕」「音轨字幕」「按转写铺字幕」时用`audio_subtitle`，说「自动字幕」时仍用`subtitle_arrange`；`analysis.transcript.status`不是`succeeded`或`partial`不得声称有转写结果，也不得把剧本对白冒充音轨转写。执行记录不提供给其它账号，返回摘要不含内部完整计划。

## 2026-11-03：SCAIL-2 人物动作替换

`GET /api/modes/scail2-replacement` 返回专属动作迁移工具的参数契约；该工作流需点选人物，不在通用创作下拉中展示。`POST /api/jobs` 使用既有 multipart：`mode=scail2-replacement`，`references[0]` 为形象图、`references[1]` 为视频；`prompt` 可留空。

`options` 必须含 `source_points` 和 `reference_points`，两者均为 JSON 字符串，例如 `[{"x":0.3,"y":0.4,"exclude":false,"subject":0},{"x":0.8,"y":0.5,"exclude":false,"subject":1}]`。坐标按原始显示方向的图片/视频首帧归一化至 0–1；`subject_count` 为字符串 `1`（默认）或 `2`，标记 `subject` 为对应的整数 0/1，省略时兼容旧单人数据并取 0。两份素材中每组均须有正点，每个人最多 20 点。

`duration` 为 `5s`（默认）或 `full`；完整原片支持 1–30 秒。后端根据原视频计算目标帧数、补帧数、连续生成段数和画布，调用方不应自行计算或覆盖。`preserve_audio` 默认 true，`seed` 默认 0（归一化为随机正整数）。完整生效参数、内部模型与标记随任务/轮次保留，平台自行跟踪、连续生成、拼合与合成原音轨；已有再次生成与恢复取片接口沿用，不新增上传端点或表。实现、验证与兼容回滚见 ARCHITECTURE 同日 SCAIL-2 完整原片记录。


## 2026-11-03 H3 原生视频编辑试验

`POST /api/jobs` 的独立模式 `minimax-h3-video-edit` 接受恰好 1 段原片视频（references[0]，最大 50 MB），提示词必填。duration=5s/10s/15s，preserve_audio 默认 true，seed=0 时随机，固定非零种子保留；模型、采样与尺寸为 internal。平台按 H3 124/243/362 帧、24fps 对齐原片，控制视频参考像素预算，原声直接进入输出。返回、任务轮次、素材下载及云端归档协议不变；试验模式不进入通用模型列表，页面为 /tools/video-edit，完成片仍须视觉验收。

## 2026-11-03 主剧本与按集写入

- `POST /api/director-assistant/artifacts/{id}/preview`：原路径保留。script 默认写当前主稿，`mapping.script_action` 为 `append_episodes` 或 `update_episodes`；已有文档 ID 可通过 `mapping.document` 明确指定。续写/更新正文须带明确的 `# 第N集：标题`；已有集追加冲突返回 409。预览 changes 的 label 标明具体集数，新增元信息 `script_write_action`、`script_section` 不影响旧客户端读取。
- script 草稿 `data.section` 默认为 `body`，`setting` 表示全剧故事设定。episodes 草稿默认更新主稿的 `analysis.episode_outlines`，不创建制作工坊分集；storyboard 的制作分集协议保持。旧客户端显式 `episode:N` 映射与整份文档替换映射保留兼容。
- `POST /api/projects/{project_id}/script/consolidate`：沿用会话与 CSRF，请求 `{document_id: string, source_document_ids: string[]}`（1–100 项），响应 `{document_id, source_document_ids, status: "merged"}`。同项目分集稿按集号合并，冲突整批回滚；已合入相同主稿的来源可幂等重放。来源原文保留并标记 merged，列表不再返回归档来源。无效输入 400、目标/来源不属于该项目 404、集号或活动任务冲突 409。
- `PUT /api/projects/{project_id}/documents/{doc_id}`：新增可选 `episode_num`（1–1000）。传入时 raw_text 为该集完整正文，base_raw_text 仍为编辑开始时的整份主稿；服务端仅替换对应集，要求唯一匹配标题。集号错误 400、过期基线 409。不传 episode_num 保持全文编辑，主稿设定、大纲、来源索引和未修改集解析对象保留。
- 助手采纳、按集编辑及合并前的快照保存在既有 ai_assistant_records 的 script_revision；正常媒体和制作分集 API 不变。无表结构或工作流迁移；验证与回滚见架构快照同日期「主剧本与分集采纳」。
## 人脸高清修复（2026-11-03）

- `GET /api/face-restore/capabilities`：登录后检查当前生效 ComfyUI 的 `ZLYKeepFaceRestore` 与三个固定模型，返回 `available/name/engine/reason`；不切换渲染机。
- `GET /api/modes/keep-face-restore`：完整选项 schema 与素材顺序。`POST /api/jobs` 使用 `mode=keep-face-restore`，`references` 为待修复视频及可选的同片段高清前原片，每份最大 500 MB；两份视频须同比例、时长相符。原片只提供待修复人脸，输出画布与声音来自第一份视频。
- `options.target_point` 必须是 `{"x":0.37,"y":0.38}` 形式的 **JSON 字符串**（坐标各为 0–1 的有限数）；`duration` 为 `full`（默认）或 `5s`，`preserve_audio` 默认为 `true`。模型、时序窗口等内部参数均由注册表默认值托管，执行快照随任务和轮次保存。
- 从成片进入时可附带 `source_job_id/source_generation_item_id/source_output_index` 指向当前用户有权访问的确切视频输出，供来源导航与再次编辑使用；原有图片转视频的图片来源约束不变。重连、停止、历史轮次、输出下载与云端保存继续使用通用任务协议。
