# ZLY AI Video Studio 架构快照

更新时间：2026-08-30

## 组件关系

```text
React/Vite frontend
        -> FastAPI session + CSRF + RBAC
        -> SQLite users/sessions/audit_logs/jobs/director_projects/director_library_assets/tts_provider_settings
        -> 单任务 Worker
        -> ComfyUI API（默认 http://127.0.0.1:8188，管理后台可改）
        -> OpenAI 兼容 TTS（/v1/audio/speech，可复用 LLM 凭据或独立配置）
        -> 本机 ffmpeg/ffprobe（成片 concat / 混音 / 可选烧字幕）
        -> 保存 ComfyUI 输出文件引用与导演成片 MP4
        -> 浏览器 File System Access API -> 员工授权目录
        -> ZLYUN AI Tauri 客户端 -> 受限 Rust 写盘命令 -> 员工授权目录
        -> POST delivered 回执 -> 标记本机交付完成
```

Docker 部署：React 在镜像构建阶段生成 `frontend/dist`，运行阶段由同一 FastAPI 容器托管。Linux 服务器 Compose 使用 `host` 网络，FastAPI 仅监听 `127.0.0.1:18189`；Nginx 在 `https://comfyui.zlyun168.com/` 代理前端和 `/api` 后端。ComfyUI 不进入 Compose，也不向公网暴露路径；工作台通过服务器内部 `http://127.0.0.1:18188` 访问唯一实例，该地址可以是 FRP 映射到服务器回环地址的远端 ComfyUI。容器不挂载 ComfyUI `output`，已完成视频不写入服务器磁盘。

Windows 本地开发由 `启动本地视频工作台.bat` 同时启动 Vite（仅 `127.0.0.1:5173`）与 FastAPI（`0.0.0.0:7865`）。浏览器始终打开 Vite 地址（含 FastAPI 已在 7865 运行时的重复双击）；`/api` 由 Vite 代理到 FastAPI，以提供 React 热更新。FastAPI 由 `backend/dev_reloader.py` 在独立进程组中拉起 uvicorn（无 `--reload`），监视 `backend/app` 源码变更并在崩溃后重启；`frontend/dist` 继续仅用于 FastAPI 的生产静态托管、局域网访问和 Docker 镜像，启动脚本不再自动打开 7865。双击 `关闭本地视频工作台.bat` 结束 `5173` 与 `7865` 上的工作台进程树及启动控制台，不停止固定 ComfyUI `8188`。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| `frontend/src/Root.tsx` | 按 `/api/auth/status` 做鉴权闸门：初始化、登录、强制改密后进入创作台或管理设置 |
| `frontend/src/paths.ts` | 前端路径常量、管理 Tab 权限与登录回跳规则 |
| `frontend/src/router.tsx` | `BrowserRouter` 路由表：登录/改密、管理设置、创作台壳 |
| `frontend/src/auth/AuthScreens.tsx` | 登录、首次超级管理员初始化与强制改密界面 |
| `frontend/src/admin/AdminSettings.tsx` | 管理设置（账号 / AI 供应商 / LLM / 媒体存储） |
| `frontend/src/App.tsx` | 已登录创作台壳：由 URL 驱动生成/导演台/资产、图/视频与选中任务；工作流、参考图草稿仍在组件 state |
| `frontend/src/director/DirectorRecipeStudio.tsx` | 导演创作工作面：方案/剪辑双视图共用同一份 `director_recipe`；`?stage=` 与桌面 `?view=` |
| `frontend/src/director/components/DirectorStageNav.tsx` | 方案视图左栏四组任务导航（方案 / 镜头制作 / 声音 / 交付）与 readiness 徽标 |
| `frontend/src/director/components/DirectorTimelineView.tsx` | 桌面剪辑视图：素材栏 + 预览/串播 + 镜头轨 + Inspector |
| `frontend/src/director/types.ts` | Recipe 类型、`recipeReadiness` 派生、`?view=` / `?stage=` 解析 |
| `frontend/src/local-resource-store.ts` | 目录句柄/资源索引 IndexedDB 持久化及本地文件读写 |
| `desktop/client/` | ZLYUN AI 客户端本地启动页与品牌图标 |
| `desktop/src-tauri/` | Tauri Windows 壳、可信 origin capability 与受限本地资源命令 |
| `backend/dev_reloader.py` | 本机 Windows 开发监督器：无 `--reload` 拉起 uvicorn，源码变更或崩溃后重启 |
| `backend/app/main.py` | HTTP API、认证依赖、资源交付、上传和静态前端托管 |
| `backend/app/auth.py` | scrypt 密码、会话、用户、角色和审计数据访问 |
| `backend/app/resource_storage.py` | 可替换资源 provider 契约、browser-stream 引用实现与旧版 browser-local 暂存兼容 |
| `backend/app/workflow_registry.py` | 工作流能力、参考图上下限、H3 参数校验 |
| `backend/app/minimax_h3_workflow.py` | 根据上传参考图动态生成 H3 API graph |
| `backend/app/minimax_h3_t8_workflow.py` | 生成全能参考多速率与双时钟 T8 API graph |
| `backend/app/comfy_provider.py` | 超级管理员可配置的 ComfyUI 连接地址、连接测试与运行时解析 |
| `backend/app/comfy_service.py` | 上传素材、提交 ComfyUI prompt、轮询、下载结果；队列空闲时 `POST /free` 卸载模型 |
| `backend/app/director_compiler.py` | 导演台按 MiniMax H3 官方 skill 编译提示词、Recipe 参考图装箱，按所选工作流族自动路由 T2V/I2V/R2V |
| `backend/app/director_catalog/` | 9 类 34 条画风 JSON 种子与查询 |
| `backend/app/director_recipe.py` | Recipe / 批量 payload 规范化、画风目录校验、旧时间轴转 Recipe |
| `backend/app/director_library.py` | 员工级人物/场景/道具资产库规范化、从 Recipe 快照、插入工程 |
| `backend/app/tts_provider.py` | 独立 TTS 供应商（OpenAI 兼容 `/audio/speech`）；可复用 LLM 凭据；不绑定 Edge TTS |
| `backend/app/director_export.py` | 逐镜 TTS、BGM、ffmpeg 成片、FCPXML/EDL；失败镜头不进入成片 |
| `backend/app/director_agents.py` | 9 Agent 顺序调度；导演对话走 SSE 流式读取（连接 20 秒、分块空闲 300 秒）；分镜 Agent 读取官方 h3-prompt-writing 原文生成；配音/配乐写可播放媒体元数据 |
| `backend/app/llm_minimax_skills.py` | MiniMax H3 风格技能与官方 prompt-writing 加载器，供生成页优化和导演台分镜共用 |
| `backend/app/h3_prompt_writing/` | MiniMax 官方 `h3-prompt-writing` skill 原文（SKILL.md、T2VA/Ref2VA 参考） |
| `backend/app/director_jobs.py` | Recipe 定妆 GRS 入队、七牛地址回写、分镜/批量按所选工作流族入队 |
| `backend/app/storage.py` | SQLite 任务、owner、交付状态与导演工程元数据 |
| `backend/app/worker.py` | 单任务串行执行，避免显存并发；最后一条视频任务结束后请求 ComfyUI 释放显存 |
| `frontend/dist/` | FastAPI 生产环境托管的前端构建产物 |
| `Dockerfile` | 前端多阶段构建和 FastAPI 运行镜像定义 |
| `compose.yaml` | 工作台容器、数据卷及服务器本机 ComfyUI 地址配置 |
| `deploy-server-image.sh` | Linux 服务器离线 tar 镜像加载、容器重建和健康检查脚本 |
| `docker/nginx/zly-ai-video-studio.conf.example` | 同域名根路径、`/api` 后端代理与首次初始化访问限制示例 |

## 2026-08-12 本地 Vite 热更新启动

`启动本地视频工作台.bat` 不再按需构建并由 FastAPI 直接打开 `frontend/dist`，而是以独立终端启动 Vite 开发服务器并在确认 `5173` 端口已监听后打开它。重复双击时若 7865 已健康，脚本补齐或复用 Vite 后仍打开 `127.0.0.1:5173`，不再打开 7865 生产静态页。Vite 固定绑定回环地址、固定端口，并将 `/api` 代理到固定的工作台 FastAPI `7865`；前端修改因此可热替换。若设置了现有 SSL 证书环境变量，Vite 会读取同一证书并以 HTTPS 运行。

- 原因：本地开发修改 React、TypeScript 或 CSS 后无需手动停止、构建并重启工作台。
- 受影响文件：`启动本地视频工作台.bat`、`frontend/vite.config.ts`、`README.md`、`功能说明与扩展指南.md` 和本文件。
- 兼容性：FastAPI 仍监听 `7865`，ComfyUI 仍仅为 `127.0.0.1:8188`；`frontend/dist`、Docker 镜像和服务器部署路径不变。Vite 仅对本机开放，局域网客户端仍使用 FastAPI 的生产静态入口。
- 验证命令：`pnpm --dir frontend build`，然后双击启动脚本并访问 `http://127.0.0.1:5173`，修改 `frontend/src` 文件确认浏览器自动更新。
- 回滚方式：恢复启动脚本、Vite 配置和三份文档；重新构建 `frontend/dist` 后即可继续由 FastAPI 托管前端，无需迁移或清理数据库、任务、媒体或模型。

## 工作流协议

当前 `/api/modes` 注册以下视频工作流，并下发 `catalog_group` / `catalog_group_label` / `catalog_group_order` 供创作页分组：

- LightX2V：`minimax-h3-lightx2v-t2v`（0 张）、`minimax-h3-lightx2v-i2v`（1-2 张首尾帧）、`minimax-h3-lightx2v-r2v`（1-9 张参考图）。默认 1.0 MP、快速 4 步、euler 采样，加载 `G:\ComfyUI-Models\lightx2v` 下的 LightX2V LoRA；官方 H3 三个模式的节点 ID 不改动。
- 八步双加速：`minimax-h3-dual-accel-t2v`（0 张）、`minimax-h3-dual-accel-i2v`（1-2 张首尾帧）、`minimax-h3-dual-accel-r2v`（1-9 张参考图）。复用参考 JSON 的加速链：`LoraLoaderModelOnly`（`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`，强度 1.0）→ `PathchSageAttentionKJ`（`auto` / 禁止 compile）→ `MiniMaxH3MemoryEfficientSageAttentionPatch`，默认 0.4 MP、8 步 `res_multistep` 与 video/audio Shift 12/3。不接入 `MiniMaxH3Director` 节点；文生/首尾帧用全量 INT8 FL2VA，多参考用全量 INT8 Ref2VA。
- 官方 MiniMax H3：`minimax-h3-t2v`、`minimax-h3-i2v`、`minimax-h3-r2v`。动态 API graph 在既有节点 1–15 之后接入 `ReservedVRAMSetter`（预留 3 GB 并在采样前清缓存）与 `MiniMaxH3MemoryEfficientSageAttentionPatch`，避免 16GB 显卡在 `SamplerCustomAdvanced` 的 INT8 QKV 上 OOM。既有节点 ID 不变。
- 自定义：`minimax-h3-t8-all-reference`（0-9 张；无图 `T2VA`+FL2VA，有图 `Ref2VA`+Ref2VA，`MiniMaxH3MultiRateSamplerEXPT8`）、`minimax-h3-t8-dual-clock`（0-1 张；无图 `T2VA`，单图 `I2VA` 首帧，`MiniMaxH3DualClockSamplerT8`）。

H3 options 使用 JSON：`aspect_ratio`、`quality`、`duration`、`speed`、`weight_profile`，以及自定义时的 `custom_steps`。比例接受任意有限正数的 `宽:高` 格式；分辨率由注册表提供可用尺寸档位并映射到内部 `megapixels`。`speed` 为语义预设：`fast`（4 步加速）、`balanced`（8 步加速，默认）、`quality`（20 步、关闭加速 LoRA）、`custom`（1–40 步）。`weight_profile` 为 `full`（默认，约 32 GB 全量 INT8，可挂加速 LoRA）或 `pruned`（约 20 GB 精简 INT8，强制关闭加速 LoRA，步数仍由 `speed` 决定）。界面按当前比例显示实际输出尺寸，尺寸会按 32 的倍数计算并保持模型画布上限，时长为 2–15 秒，帧数按 H3 的 24fps、17n+5 时间网格对齐。

两个 T8 模式的 options schema 同样由 `workflow_registry.py` 提供，覆盖任务类型、比例、画质预设、内部像素、对齐倍数、时长、种子、音频策略、采样步数、video/audio shift、模型、LoRA、SageAttention、显存策略和 H.264 编码参数。每项使用 `ui_group=primary|advanced|internal` 声明产品可见性；前端只生成主参数与“更多设置”，内部参数由后端默认值托管。随机种子每次由后端自动生成，不接受用户指定。SQLite 保存标准化 options 与显式提交字段；`request_parameters` 返回当前生效的有效值和 `visibility`，并遵守 `ui_visible_when`（例如未选自定义时不回显 `custom_steps`），前端将内部值折叠到“运行参数”。输出文件前缀、`save_output=true` 与 graph 连线属于集成协议，不允许调用方覆盖。

## 2026-08-12 画质预设与随机种子产品化

- 原因：MP 和随机种子属于 ComfyUI 实现参数，直接展示会增加普通用户的理解成本。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/main.py`、`frontend/src/App.tsx`、`backend/tests/test_core.py`、`README.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`。
- 用户可见行为：画质只显示 `1K`、`2K`、`4K`，后端按工作流映射实际 MP；随机种子从创建表单和创作参数中隐藏，每次任务自动随机生成，仅在折叠的运行参数中保留。
- 兼容性：ComfyUI graph 仍接收 `megapixels` 和 `seed` 内部值；旧任务含 MP 的记录可按最近档位回显质量预设，API、SQLite、节点 ID 和固定端口不变。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：恢复上述代码和文档文件；无需迁移或清理 SQLite、媒体、模型和 ComfyUI。

## 模型路径

推荐将模型放在独立目录，并在固定 ComfyUI 的 `extra_model_paths.yaml` 中配置：

```yaml
minimax_h3:
  base_path: G:\ComfyUI-Models
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
  loras: lightx2v
```

H3 模型文件包括 `fl2va`、`ref2va`、`qwen3vl`、video VAE 和 audio VAE。LightX2V 加速 LoRA 位于 `G:\ComfyUI-Models\lightx2v`，由 `extra_model_paths.yaml` 的 `loras: lightx2v` 暴露给固定 ComfyUI。不要复制到工作台 `frontend` 或 `backend` 目录。

## 验证基线

```powershell
& "<ComfyUI Python>" backend\tests\test_core.py
npm --prefix frontend run build
Invoke-RestMethod http://127.0.0.1:7865/api/health
Invoke-RestMethod http://127.0.0.1:7865/api/modes
```

## 2026-08-05 迁移：移除旧版 Gradio 启动入口

React + FastAPI 工作台已成为唯一支持的启动路径，入口为 `启动本地视频工作台.bat`。已删除 `启动旧版Gradio工作台.bat`，以避免在同一 `127.0.0.1:7865` 端口误启动旧版 Gradio 界面。`local_video_studio.py` 暂时保留，未作为当前架构的一部分运行。

- 原因与影响：移除旧版用户启动入口；不修改 ComfyUI 实例、端口、任务数据库、工作流协议或现有结果目录。
- 兼容性：唯一支持的界面为 React + FastAPI 工作台，ComfyUI 仍固定在 `127.0.0.1:8188`。
- 验证：运行本节的后端测试和前端构建命令。
- 回滚：从 Git 历史恢复已删除的批处理脚本及其文档说明。

## 2026-08-11 启动时清理遗留 Gradio 服务

`启动本地视频工作台.bat` 发现 7865 已监听时，会读取监听进程的命令行。仅当命令行包含旧版入口 `local_video_studio.py`，脚本才会停止该 Gradio 进程并继续以 Uvicorn 启动当前 React + FastAPI 工作台。任何其他占用 7865 的程序均不会被停止，脚本会退出并提示用户释放端口。`local_video_studio.py` 仅作为现有工作流辅助函数的兼容模块，不能再直接启动 Gradio，且不再要求新版后端安装 Gradio。

- 原因：避免端口复用时把浏览器导向已遗留运行的旧 Gradio 页面。
- 受影响文件：`启动本地视频工作台.bat`、`local_video_studio.py`、`README.md`、`功能说明与扩展指南.md`。
- 兼容性：唯一支持的工作台仍为 `http://127.0.0.1:7865` 的 React + FastAPI 服务；ComfyUI 仍固定为 `http://127.0.0.1:8188`。
- 验证：运行 `& "<ComfyUI Python>" backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在存在旧 Gradio 监听进程时执行启动脚本。
- 回滚：恢复启动脚本端口占用的原有处理逻辑和上述文档记录；无需迁移或清理任何数据。

重大改动必须先更新本文件，再更新功能说明和 README。具体规则见根目录 `AGENTS.md`。
## 2026-08-05 任务进度同步基线

任务状态链路仍为 `React -> FastAPI /api/jobs -> SQLite JobStore -> 单任务 Worker -> ComfyUI 8188`。本次增加 `jobs.progress` 整数列（0-100）及 API 响应字段。Worker 在提交 ComfyUI graph 前建立 `ws://127.0.0.1:8188/ws?clientId=...` 连接，消费 `progress_state`，并将当前节点 `value/max` 映射到任务进度；HTTP `/history/{prompt_id}` 仍是完成与错误状态的最终来源。

- 兼容性：`JobStore.initialize()` 为既有数据库自动添加 `progress` 列，旧记录默认 0；WebSocket 不可用时任务仍可通过 HTTP 轮询完成。
- 多阶段映射：Flux 首帧 0-25%，LTX 2.3 视频 25-95%，Worker 完成时写入 100%。
- 受影响文件：`backend/app/comfy_service.py`、`backend/app/storage.py`、`backend/app/worker.py`、`backend/app/models.py`、`frontend/src/App.tsx`。
- 验证与回滚：运行 `<ComfyUI Python> backend/tests/test_core.py` 和 `pnpm --filter zly-ai-video-studio-webui build`；恢复上述文件即可回滚，新增列无需删除。

## 2026-08-06 API 文档基线

FastAPI 以当前路由、表单参数和 Pydantic 响应模型自动生成 OpenAPI 3.1 规范。服务端新增以下只读文档端点，均保持在工作台固定地址 `127.0.0.1:7865` 下：

- `/api/docs`：Swagger UI，用于本机交互调用。
- `/api/redoc`：ReDoc，用于阅读接口定义。
- `/api/openapi.json`：OpenAPI JSON；是接口定义的唯一来源，可导入 Apifox。

仓库内 `docs/API.md` 记录调用约定、参数限制与示例，但不能替代 OpenAPI schema。Apifox 仅作为可选的团队调试、测试和协作层，不得手工维护与后端脱节的接口副本，也不得为了 URL 导入而将仅本机监听的服务对外暴露。

- 原因：后端已采用 FastAPI，使用其内置 OpenAPI/Swagger UI/ReDoc 可避免新增文档服务和双份接口定义。
- 受影响文件：`backend/app/main.py`、`backend/app/models.py`、`backend/tests/test_core.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md`。
- 兼容性：不修改现有业务接口、ComfyUI 地址、任务协议或数据库；仅新增文档路由和响应模型声明。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`Invoke-RestMethod http://127.0.0.1:7865/api/openapi.json`。
- 回滚方式：恢复上述文件；无数据库迁移、工作流或媒体文件变更。

## 2026-08-06 局域网访问基线

工作台 FastAPI/Uvicorn 从 `127.0.0.1:7865` 改为监听 `0.0.0.0:7865`，因此保留本机回环访问，并允许可信局域网通过 `http://<本机IPv4>:7865` 访问同一服务。前端静态资源和 API 均为同源访问，不需要增加 CORS 配置。ComfyUI 不受影响，仍由后端通过固定 `http://127.0.0.1:8188` 调用，不对局域网暴露。

由于现阶段 API 无认证，局域网内能够访问该端口的设备可提交任务、读取任务记录和下载结果。Windows 防火墙规则只能开放 `7865/TCP` 给 `Private` 与 `Domain` 配置文件，不能开放给 `Public`；对外部署前必须先增加认证与访问控制。

- 原因：支持同一可信局域网设备使用现有工作台。
- 受影响文件：`启动本地视频工作台.bat`、`backend/app/main.py`、`backend/tests/test_core.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md`。
- 兼容性：`127.0.0.1:7865` 保持可用；ComfyUI 端口、数据库、任务队列和工作流协议均不变。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`Invoke-WebRequest http://<本机IPv4>:7865/api/health`。
- 回滚方式：恢复 Uvicorn 的 `--host` 值为 `127.0.0.1`，移除 `ZLY AI Video Studio Workbench LAN` 防火墙规则（如已创建），然后重启工作台。

## 2026-08-06 工作流参数接口基线

`workflow_registry.py` 除了模式能力、参考图数量和后端校验外，现负责生成该模式在 `POST /api/jobs` 中的 multipart 参数定义。`GET /api/modes` 的每个模式包含 `parameters`，`GET /api/modes/{mode_id}` 返回单模式详情；两者包含字段名、必填状态、枚举值、参考图上下限，以及 MiniMax H3 `options` 的 JSON schema。前端可以继续消费现有能力字段，外部客户端可直接消费参数 schema。

- 原因：让 API 调用方从后端注册表获得完整工作流参数契约，而不是依赖前端实现或手工文档。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/tests/test_core.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md`。
- 兼容性：不改变既有任务提交、ComfyUI、数据库和工作流协议；新增模式响应字段与只读详情端点。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`Invoke-RestMethod http://127.0.0.1:7865/api/modes/minimax-h3-r2v`。
- 回滚方式：恢复上述文件；无数据迁移或媒体清理操作。

## 2026-08-07 H3 自定义比例与任务回显

- 原因：H3 API 需要支持任意合法比例，且 API 创建的任务应在工作台显示参考图与实际参数。
- 变更：`options.aspect_ratio` 接受任意有限正数的 `宽:高` 字符串；尺寸仍按 32 对齐并受 H3 画布上限约束。任务响应新增 `references[]`，每项提供受控的 `/api/jobs/{job_id}/references/{reference_index}` 预览 URL。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/main.py`、`frontend/src/App.tsx`、`backend/tests/test_core.py`、`docs/API.md`、`README.md` 和 `功能说明与扩展指南.md`。
- 兼容性：既有 `16:9`、`9:16` 与 `1:1` 请求保持有效；新增响应字段不破坏旧客户端。上传素材路径仍不对外暴露。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：恢复上述文件；不需要数据库迁移、模型变更或修改 ComfyUI 节点。

## 2026-08-07 任务请求参数完整回显

- 原因：任务详情必须能核对 API 或工作台传入的全部公开参数，避免仅依赖为某个工作流硬编码的展示字段。
- 变更：`JobStore` 保存显式提交的 `options` 键；任务响应新增 `request_parameters[]`，由 `workflow_registry.py` 的参数定义生成标签和值。前端统一遍历该数组渲染请求参数，参考图继续使用受控预览 URL。
- 受影响文件：`backend/app/storage.py`、`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/main.py`、`frontend/src/App.tsx`、`backend/tests/test_core.py`、`docs/API.md`、`README.md` 和 `功能说明与扩展指南.md`。
- 兼容性：`request_parameters` 是新增响应字段；SQLite 启动时自动补充 `submitted_options_json` 和 `options_submitted`，历史任务保持可读。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`Invoke-RestMethod http://127.0.0.1:7865/api/jobs/<job_id>`。
- 回滚方式：恢复上述受影响文件；新增 SQLite 列无需删除。

## 2026-08-07 AI 工作台控件与参考图预览

- 原因：将工作台的选择控件和参考图确认体验对齐 `Smart-Floor-Planner` AI 创作区的成熟交互模式。
- 变更：前端新增 `StudioSelect`，为工作流、像素规格、时长和图片尺寸提供暗色浮层、选中标记及辅助说明；素材卡和历史任务参考图支持点击打开预览对话框。
- 受影响文件：`frontend/src/App.tsx`、`README.md`、`功能说明与扩展指南.md`。
- 兼容性：保持现有 API、SQLite、队列、ComfyUI 地址和工作流节点不变；该变更仅影响前端本地交互状态与呈现。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，以及 `http://127.0.0.1:7865` 的桌面/390px 视口检查。
- 回滚方式：恢复上述前端和文档文件；没有数据迁移或资源清理操作。

## 2026-08-07 ComfyUI 任务重启恢复

- 原因：ZLY AI Video Studio 进程重启后，ComfyUI 进程和其 `queue_running`、`queue_pending` 任务仍可能持续执行，原有初始化逻辑会丢失这层关联。
- 变更：SQLite 记录每个已提交工作流的 ComfyUI `prompt_id`、WebSocket `client_id` 和工作流阶段。工作台启动时读取固定 `http://127.0.0.1:8188/queue` 与 `/history/{prompt_id}`，将仍在队列、运行或已完成但未下载的任务重新入 worker 同步；队列中已不存在且历史也未保存的任务才标记为中断。
- 迁移：历史库自动新增 `comfy_prompt_id`、`comfy_client_id` 和 `comfy_phase` 三列。旧版本曾标记为“应用已重启”的 H3 任务会在提示词与创建时间和当前 ComfyUI 队列唯一匹配时自动重新关联。
- 受影响文件：`backend/app/storage.py`、`backend/app/comfy_service.py`、`backend/app/worker.py`、`backend/tests/test_core.py`、`README.md`、`功能说明与扩展指南.md`。
- 兼容性：不修改公开 API、工作流节点、队列端口或 ComfyUI 实例；任务响应继续仅返回受控媒体和参考图 URL。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并重启 `http://127.0.0.1:7865` 验证活动任务恢复。
- 回滚方式：恢复上述文件；三列 SQLite 元数据保留不会影响旧版本。

## 2026-08-11 账号边界与浏览器本地资源交付

认证链路采用同源服务端会话：随机会话 token 仅存于 `HttpOnly` Cookie，SQLite 只保存 token 的 SHA-256 摘要；写操作额外校验由会话 token 派生的 `X-CSRF-Token`。密码使用带随机 salt 的 `scrypt`。首次超级管理员只能从工作站回环地址初始化，新员工使用管理员分配的初始密码登录后必须改密。RBAC 为 `super_admin`、`admin`、`employee`，`jobs.owner_user_id` 是任务、参考图和结果授权的主边界。

资源链路为 `ComfyUI Save 节点 -> FastAPI 下载到 data/staging -> 受保护下载 URL -> 浏览器写入员工授权目录 -> delivered 回执 -> 删除 data/staging 副本与 ComfyUI output 原始输出`。ComfyUI 的 Save 节点仍会先在固定 ComfyUI 目录产生临时输出，这是现有工作流协议不可绕过的落盘；回执清理仅接受 `type=output`，并把解析后的目标严格限制在固定 `Comfyui/output` 根目录。ZLY AI Video Studio 不再把新结果长期归档到 `results`。浏览器在 IndexedDB 中按用户保存目录句柄和资源相对路径，不上传目录句柄或员工本地绝对路径。

`resource_storage.py` 定义 `store_bytes/resolve/delete` provider 边界和 provider 注册表，`ZLY_AI_VIDEO_STUDIO_RESOURCE_PROVIDER` 选择实现，当前为 `browser-local`；未知 provider 启动失败，不会静默回退。接入七牛云时应新增并注册 provider，将输出写入对象存储并返回受控下载定位；任务响应继续使用 `delivery_status` 和 `download_url`，不得让业务路由直接依赖七牛 SDK。File System Access API 仅在最新版 Chromium 的安全上下文可用，局域网员工端必须使用受信任 HTTPS；不支持时仅提供普通浏览器下载，无法保证自动回执和暂存清理。

- 原因：为企业员工提供账号隔离，并把生成资源最终落到员工电脑而非生成工作站长期保存。
- 受影响文件：`backend/app/auth.py`、`backend/app/resource_storage.py`、`backend/app/config.py`、`backend/app/storage.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/app/comfy_service.py`、`frontend/src/api.ts`、`frontend/src/local-resource-store.ts`、`frontend/src/Root.tsx`、`frontend/src/App.tsx`、`frontend/src/main.tsx`、`启动本地视频工作台.bat`、测试与文档。
- 兼容性：`7865`、固定 ComfyUI `8188`、工作流注册表、节点 ID 和单 worker 不变。SQLite 自动增加用户/会话/审计表及 `owner_user_id`；首次管理员接管无归属历史任务。旧 `results` 文件仅对有归属任务兼容读取。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并验证桌面与 390px 登录、管理员账号表、本地目录状态和资源交付回执。
- 回滚方式：恢复上述代码和文档；数据库新增结构可以保留。将未交付的 `data/staging` 文件迁回 `results` 可恢复旧式服务器作品库；已经交付并删除暂存的文件只能从员工授权目录恢复。

## 2026-08-11 MiniMax H3 T8 工作流接入

固定 ComfyUI 的两个前端格式工作流已转换为后端动态 API graph。`minimax-h3-t8-all-reference` 复用源工作流的 `ReservedVRAMSetter -> MiniMaxH3MemoryEfficientSageAttentionPatch -> MiniMaxH3MultiRateSamplerEXPT8` 链路；快速/均衡再接 `LoraLoaderBypassModelOnly`（文生用 FL2VA 全量 INT8，有图用 Ref2VA 全量 INT8）。`minimax-h3-t8-dual-clock` 使用 `LoraLoaderBypassModelOnly -> MiniMaxH3DualClockSamplerT8`。两者统一经 `MiniMaxH3AudioConditioningT8`、`MiniMaxH3AVDecodeT8` 和 `VHS_VideoCombine` 输出，后端固定输出节点为 `14`。Turbo LoRA 只挂在非 pruned 权重上；高质量关闭加速时改用 pruned INT8。

- 原因：源 JSON 是 ComfyUI 前端工作流格式，不能直接由 `/prompt` 提交，也无法自动向工作台公开参数。
- 受影响文件：`backend/app/models.py`、`backend/app/workflow_registry.py`、`backend/app/minimax_h3_t8_workflow.py`、`backend/app/main.py`、`backend/app/comfy_service.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx`、`docs/API.md`、`README.md` 和 `功能说明与扩展指南.md`。
- 兼容性：原有 `minimax-h3-t2v/i2v/r2v` graph 和节点 ID 不变；新模式复用固定 `8188` 实例中已安装的 T8、KJNodes、VideoHelperSuite 与 LoRA 节点。无数据库迁移，不修改 ComfyUI 源 JSON。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、对照 `http://127.0.0.1:8188/object_info` 静态验证新 graph，并在 `http://127.0.0.1:7865` 检查桌面和 390px 交互。
- 回滚方式：移除两个新模式与 T8 graph 构建器，恢复分发、动态控件、测试和文档；SQLite 中已保存的新模式任务可保留但旧代码无法再次执行这些任务。

## 2026-08-11 工作流参数产品化分层

`workflow_registry.py` 是参数契约与展示层级的唯一来源。所有 option 必须归入 `primary`、`advanced` 或 `internal`；`option()` 默认使用 `internal`，因此遗漏层级只会隐藏技术参数，不会扩大用户界面。创建页只消费前两层，任务提交与 graph 构建仍使用完整标准化 options。任务响应的 `request_parameters[].visibility` 复用同一元数据，并跳过当前不满足 `ui_visible_when` 的字段；详情页默认展示创作参数，并将内部有效参数放入折叠运行信息。

- 原因：将 ComfyUI 节点能力与普通用户的创作决策分离，同时保留任务复现和排障所需的完整参数快照。
- 受影响文件：`AGENTS.md`、`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/main.py`、`frontend/src/App.tsx`、`backend/tests/test_core.py`、`docs/API.md`、`README.md` 和 `功能说明与扩展指南.md`。
- 兼容性：既有 `POST /api/jobs` 参数、SQLite、ComfyUI graph、节点 ID、模型路径和固定端口不变；模式与任务响应仅增加展示元数据，旧客户端可以忽略。
- 验证命令：`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在桌面和 390px 视口验证参数层级与折叠回显。
- 回滚方式：恢复上述文件；不需要数据库迁移、任务清理或模型变更。

## 2026-08-11 密码可见性与重置解锁

登录失败窗口仍以 `来源 IP:标准化账号` 为键保存在进程内存中。管理员通过既有重置密码接口成功更新账号后，后端按标准化账号清除所有来源 IP 对应的失败记录；清除数量写入 `reset_password` 审计明细。失败记录的读取、追加和清除由同一进程锁保护。前端所有密码字段复用同一个可见性切换组件，按钮具备 `aria-label`、按压状态和键盘焦点样式。

- 原因：让密码重置真正恢复员工登录能力，并提供一致、可访问的密码录入交互。
- 受影响文件：`frontend/src/Root.tsx`、`backend/app/main.py`、`backend/tests/test_core.py`、`README.md` 和 `功能说明与扩展指南.md`。
- 兼容性：不改变 API schema、SQLite、Cookie、CSRF、RBAC、端口、任务队列或 ComfyUI 工作流；清理范围只覆盖被重置账号。
- 验证命令：`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并验证密码切换和跨 IP 失败记录清除。
- 回滚方式：恢复上述文件；现有账号、会话和数据库无需迁移。

## 2026-08-11 首次目录配置强制引导

首次改密成功后，`Root.tsx` 才会渲染工作台 `App.tsx`。`App.tsx` 在按当前 `user.id` 从 IndexedDB 恢复目录句柄及其权限状态前显示检查态；若没有已授权目录、目录权限失效、浏览器不支持 File System Access API 或用户拒绝授权，则以不可关闭的配置层覆盖工作台并禁止提交任务。用户选择并授予目录写入权限后，配置层自动消失；用户也可退出登录。目录选择仍通过用户手势触发，目录句柄与员工本地绝对路径不会发送到后端。

- 原因：保证员工首次完成账号安全设置后，先建立生成结果的本地交付位置，再使用任务创建能力。
- 受影响文件：`frontend/src/App.tsx`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：已有授权目录仍可自动恢复；未改动 `/api`、SQLite、资源回执、固定 ComfyUI 实例、工作流节点或端口。
- 验证命令：`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在 `http://127.0.0.1:7865` 的桌面和 390px 视口验证首次配置、权限失效重授和已授权回访。
- 回滚方式：恢复上述文件并重新构建前端；无需数据库迁移、任务清理或媒体恢复。

## 2026-08-11 ZLYUN AI Tauri 桌面客户端

首版客户端由 `desktop` 子工程构建，窗口与安装包显示名为 `ZLYUN AI`，图标来自 `desktop/client/zlyun-ai-mark.png` 和 `desktop/src-tauri/icons/icon.png`。客户端本身只提供静态启动页，然后打开 `WORKBENCH_URL` 指向的企业工作台 HTTPS origin；远程页面与浏览器版共用构建产物，因此 API、Cookie 与 CSRF 始终同源。

`desktop-workbench` capability 明确列出唯一可调用本机命令的远程 HTTPS origin。它不得配置通配域名，也不得使用普通 HTTP。Rust 端为每个 ZLY AI Video Studio `user_id` 持久化一个员工主动选择的根目录；`desktop_save_resource` 只允许单段文件名，固定写入该根目录的 `ZLY AI Video Studio/YYYY-MM` 子目录；`desktop_local_resource_path` 只接受相对路径并再次限定在该根目录内。网页通过已有 Cookie + CSRF 获取绑定用户、任务和输出、有效期 5 分钟的临时下载凭证，Rust 只接受同源且带凭证的下载地址并分块写入临时文件，成功后原子替换目标文件。服务端不接收目录路径。写入成功后，前端仍调用现有 `delivered` 回执，因此暂存清理规则没有变化。

- 原因：解除浏览器安全上下文对本地交付的限制，同时保持服务端集中调度和未来企业桌面能力的扩展点。
- 受影响文件：`desktop/`、`frontend/src/local-resource-store.ts`、`frontend/package.json`、`pnpm-workspace.yaml`、`.gitignore`、三份主文档。
- 兼容性：浏览器环境检测不变；不是 Tauri 时继续走 File System Access API。固定 `7865`、`127.0.0.1:8188`、工作流注册表、节点 ID、数据库和任务队列均不变。
- 验证：运行 `pnpm --filter zly-ai-video-studio-webui build`、`pnpm --dir desktop run build` 和后端测试；以受信任 HTTPS 访问桌面端，验证目录选择、视频写入、重启后的本地预览和交付回执。
- 回滚：停止安装包分发并恢复本地资源模块的浏览器实现；无需迁移数据库或清理媒体。

## 2026-08-11 MiniMax H3 参数组件化

- 原因：标准 H3 三种视频工作流的画面比例和时长曾使用原生文本/数字输入，无法与工作台选择控件保持一致。
- 受影响文件：`backend/app/workflow_registry.py`、`frontend/src/App.tsx`、`frontend/src/main.tsx`、`frontend/src/index.css`、`frontend/package.json` 与测试、文档。
- 当前基线：`workflow_registry.py` 可通过 `ui_control`、`ui_options` 提供展示元数据；前端使用开源 Ant Design 的 `Select`、`InputNumber`、`Switch` 按 schema 渲染控件，不按工作流 ID 或参数名分支。标准 H3 的预设比例仅约束工作台选择，API 仍可提交任意合法的有限正数宽高比。
- 兼容性：`POST /api/jobs` 的 `options` 格式不变，`GET /api/modes` schema 新增可忽略的展示元数据；无 SQLite 迁移、端口、节点 ID、模型路径和 ComfyUI 实例变更。
- 验证：`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，以及 `http://127.0.0.1:7865` 桌面与 390px 视口的选择/步进交互检查。
- 回滚：恢复本次注册表、Ant Design 前端接入、测试和本文档改动后重新构建前端；已有任务、媒体和数据库无需处理。

## 2026-08-11 Docker 服务器部署

- 原因：将 React 前端和 FastAPI 后端以可复现镜像部署到服务器，同时复用已经运行在 `https://comfyui.zlyun168.com`（服务器端口 `18188`）的唯一 ComfyUI 实例。
- 实现：新增多阶段 `Dockerfile`，Node 阶段构建 `frontend/dist`，Python 运行阶段安装工作台后端依赖并以非 root 用户运行；`compose.yaml` 挂载命名数据卷、ComfyUI `output` 和旧 Flux/LTX 工作流目录。容器仍在内部 `7865` 提供服务，Nginx 示例在服务器 `18189` 终止 TLS 并代理到回环地址，拒绝远程调用首次管理员初始化接口。`local_video_studio.py` 新增 `ZLY_AI_VIDEO_STUDIO_WORKFLOW_DIR`，保留本地 Windows 默认目录以兼容原有启动方式。
- 受影响文件：`Dockerfile`、`compose.yaml`、`.dockerignore`、`.env.example`、`.gitignore`、`docker/nginx/zly-ai-video-studio.conf.example`、`backend/requirements.txt`、`local_video_studio.py`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 兼容性：前端/API、SQLite schema、任务队列、工作流节点 ID 和容器内工作台端口 `7865` 均不变；ComfyUI 不被打包或另行部署。通过 `ZLY_AI_VIDEO_STUDIO_COMFY_URL` 指向既有 HTTPS 服务，旧本地启动仍使用原 Windows 工作流目录和固定 `127.0.0.1:8188`。
- 验证命令：`docker compose config`、`docker compose build`、`docker compose up -d`、`curl http://127.0.0.1:7865/api/health`、`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：执行 `docker compose down` 后使用上一镜像重新启动；不使用 `-v`，以保留 SQLite、上传素材和暂存结果。移除 Nginx 的 `18189` 虚拟主机并重载即可撤销公网 HTTPS 入口，不影响现有 ComfyUI。

## 2026-08-11 ZLY AI 视频创作平台同域名部署

- 原因：统一工作台的容器品牌为 `ZLY AI Video Studio`，将同域名根路径用于前端、`/api` 用于工作台后端，并收回 ComfyUI 的公网 API 暴露。
- 实现：Compose 项目、服务、镜像、容器和命名卷改为 `zly-ai-video-studio`。Linux Docker 使用 host network，Uvicorn 只监听 `127.0.0.1:18189`；Nginx 将 `https://comfyui.zlyun168.com/` 及 `/api` 代理到该端口。唯一 ComfyUI 保持 `127.0.0.1:18188`，工作台直接访问它而不经过 Nginx。生产环境仍使用 `/api`，`ZLY_AI_VIDEO_STUDIO_PUBLIC_API_PREFIX` 默认为同一路径，确保任务参考图、下载 URL 与 OpenAPI 保持同源。
- 受影响文件：`Dockerfile`、`compose.yaml`、`.env.example`、`docker/nginx/zly-ai-video-studio.conf.example`、`docker/nginx/zly-ai-video-studio.conf.example`、`backend/app/config.py`、`backend/app/comfy_service.py`、`backend/app/main.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx`、`frontend/src/Root.tsx`、`desktop/src-tauri/src/lib.rs`、`desktop/src-tauri/capabilities/desktop-workbench.json`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 兼容性：本地 Windows 启动维持 `127.0.0.1:7865`、`/api` 和固定 `127.0.0.1:8188`；服务器 Docker 部署改为私有 `18189` 工作台端口与私有 `18188` ComfyUI 端口。SQLite schema、任务队列、节点 ID、模型路径与 API 请求格式不变。
- 验证命令：`docker compose config`、`docker compose build`、`curl http://127.0.0.1:18189/api/health`、`curl -I https://comfyui.zlyun168.com/api/health`、`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：执行 `docker compose down`，恢复旧的 `zly-ai-video-studio-workbench` Compose/Nginx 配置和镜像；不使用 `-v`。新命名卷不会自动迁移旧 `zly-ai-video-studio-data` 卷，回滚前应保留该卷备份。

## 2026-08-11 移除旧 Flux、LTX 与 Wan VACE 工作流

- 原因：服务器部署仅保留 MiniMax H3 系列视频创作能力，避免为已不再使用的 Flux、LTX 和 Wan VACE 模式维护 ComfyUI API 模板、节点映射与工作流目录挂载。
- 实现：`workflow_registry.py` 移除 `image`、`ltx-video`、`vace-video` 注册项，`GET /api/modes` 因而只返回五个 `minimax-h3-*` 模式；Docker Compose、镜像环境与 `.env.example` 删除 `ZLY_AI_VIDEO_STUDIO_WORKFLOW_DIR` 和 `/workflows`。后端拒绝创建已移除模式的任务，并在启动恢复时将未完成旧任务标记为失败；已完成历史任务仍可读取。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/main.py`、`backend/app/worker.py`、`backend/app/models.py`、`backend/tests/test_core.py`、`frontend/index.html`、`frontend/src/App.tsx`、`Dockerfile`、`compose.yaml`、`.env.example`、`.dockerignore`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 兼容性：API 路径、SQLite schema、任务记录、ComfyUI 地址与 H3 graph 均不变；旧模式的已完成任务可继续查看和下载，但排队或运行中的旧任务无法在新版本恢复。
- 验证命令：`docker compose --env-file .env.example config`、`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`docker compose build`、`curl http://127.0.0.1:18189/api/health`。
- 回滚方式：停止容器并加载上一版镜像与 Compose 文件，恢复旧工作流挂载和 `.env` 的 `ZLY_AI_VIDEO_STUDIO_WORKFLOW_DIR` 后启动；不使用 `docker compose down -v`，以保留任务和账号数据。

## 2026-08-11 运行环境变量品牌迁移

- 原因：生产部署统一使用 `ZLY AI Video Studio` 品牌命名，避免运行配置继续沿用旧前缀。
- 受影响文件：`compose.yaml`、`.env.example`、`Dockerfile`、`backend/app/config.py`、`local_video_studio.py`、本地启动脚本、`README.md` 和 `功能说明与扩展指南.md`。
- 当前基线：服务器通过 `ZLY_AI_VIDEO_STUDIO_COMFY_URL=http://127.0.0.1:18188` 访问唯一 ComfyUI；工作台继续仅监听 `127.0.0.1:18189`，数据目录与容器内挂载路径不变。
- 兼容性：API、SQLite schema、任务队列、工作流节点 ID、模型路径与端口不变；旧环境变量不再被读取，部署配置必须同步更新。
- 验证命令：`docker compose --env-file .env.example config`、`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：恢复本次变更的配置、镜像和启动文件；无需迁移或清理数据库与媒体文件。


## 2026-08-11 品牌与运行数据迁移

- 原因：所有产品自有运行标识统一迁移为 `ZLY AI Video Studio`。
- 受影响文件：`backend/app/config.py`、`auth.py`、`main.py`、工作流构建器、`frontend/src/local-resource-store.ts`、`desktop/`、Docker、启动脚本、构建配置、工具脚本和三份文档。
- 当前基线：数据库文件为 `zly-ai-video-studio.db`，会话 Cookie 为 `zly_ai_video_studio_session`，ComfyUI 输出前缀、任务 worker、浏览器 IndexedDB 和桌面端交付子目录均使用产品名；固定 ComfyUI 目录通过工作台父目录计算，避免在产品代码中硬编码旧路径。
- 兼容性：启动时自动迁移旧数据库与 WAL/SHM 文件；旧浏览器本地资源记录会复制到新 IndexedDB；Cookie/CSRF 变更会使旧会话失效。API、SQLite schema、任务队列、模型与 ComfyUI 端口不变。
- 验证命令：`docker compose --env-file .env.example config`、`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`pnpm --dir desktop run build`。
- 回滚方式：恢复本次代码与配置；若已迁移数据库，停止服务后将新数据库及其 WAL/SHM 文件改回旧名称。不要删除上传素材或暂存文件。

## 2026-08-11 browser-stream 远端 ComfyUI 交付

`browser-stream` 是默认资源 provider。任务完成时，`ComfyService.download()` 校验并保存 ComfyUI `filename/subfolder/type=output` 引用，不请求 `/view` 的文件内容。`/api/jobs/{job_id}/outputs/{output_index}/download` 先执行既有会话或桌面临时凭证授权，再向 `ZLY_AI_VIDEO_STUDIO_COMFY_URL/view` 发起流式请求，并把响应块直接转发给员工浏览器或桌面客户端。响应不包含 ComfyUI URL、文件名或子目录。

服务器仅保存 SQLite、上传素材和极少数旧版/多阶段兼容文件；完成视频保留在远端 ComfyUI 电脑的 `output`。当服务器的 `127.0.0.1:18188` 是 FRP 到远端电脑的映射时，容器继续通过 host network 访问它，既不需要 `COMFY_OUTPUT_DIR`，也不需要向公网公开 ComfyUI `/view`。用户成功写入本机目录后，`delivered` 只标记交付完成；远端输出由 ComfyUI 电脑的保留策略清理。

- 原因：消除工作台服务器对视频成片的磁盘占用，同时保留工作台的用户授权边界。
- 受影响文件：`backend/app/resource_storage.py`、`backend/app/comfy_service.py`、`backend/app/main.py`、`backend/app/config.py`、`compose.yaml`、`.env.example`、`Dockerfile`、测试与三份主文档。
- 兼容性：`browser-local` 仍可显式配置并维持原暂存清理行为；旧暂存结果和 `results` 兼容读取。七牛云应作为另一 Provider 实现上传、私有签名 URL 与回收，业务路由继续仅使用统一资源契约。
- 验证：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`docker compose --env-file .env.example config`、`docker compose build`。
- 回滚：切回 `browser-local` 并恢复上一版带 `COMFY_OUTPUT_DIR` 的 Compose/镜像；SQLite、上传素材和已保存到员工电脑的文件不需要迁移。

## 2026-08-12 Nginx browser-stream 反向代理

`docker/nginx/zly-ai-video-studio.conf.example` 将 HTTP 重定向到 HTTPS，并仅代理工作台根路径和 `/api/` 至 `127.0.0.1:18189`。`/api/auth/setup` 仅允许服务器回环地址；不定义任何 ComfyUI location，因此 FRP 映射的 `127.0.0.1:18188`、`/view`、`/prompt`、`/history`、`/upload/image` 和 `/ws` 不会向公网暴露。

`/api/` 使用 `proxy_request_buffering off`、`proxy_buffering off` 和 `proxy_max_temp_file_size 0`，使 `browser-stream` 的输出流不被 Nginx 写入临时文件；读取和发送超时设为 600 秒以适配远端 ComfyUI 经 FRP 的大文件传输。

- 原因：避免反向代理默认缓冲破坏“完成视频不落服务器磁盘”的交付目标。
- 受影响文件：`docker/nginx/zly-ai-video-studio.conf.example`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：同源 Cookie、CSRF、工作台 API、容器端口与 ComfyUI FRP 映射不变；仅需按实际域名和证书路径替换 Nginx 配置占位值。
- 验证：`sudo nginx -t`、`sudo systemctl reload nginx`、`curl -I https://<工作台域名>/api/health`；确认 `ss -lntp` 中的 18188/18189 仅监听回环地址。
- 回滚：移除 `/etc/nginx/conf.d/zly-ai-video-studio.conf` 并重载 Nginx，或恢复上一版虚拟主机；不会影响 Docker 数据卷、ComfyUI 或员工本地文件。

## 2026-08-12 Docker 配置模块启动修复

- 原因：运行镜像内的工作台目录为 `/app`。旧的本地 ComfyUI 默认目录使用固定祖先索引，在容器导入 `backend.app.config` 时越界，导致 FastAPI 在绑定 `127.0.0.1:18189` 前退出。
- 受影响文件：`backend/app/config.py`、`backend/tests/test_core.py`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 当前基线：默认本地 ComfyUI 根目录由工作台目录的父级推导；Docker 保持通过 `ZLY_AI_VIDEO_STUDIO_COMFY_URL=http://127.0.0.1:18188` 调用服务器已有的唯一 ComfyUI，不挂载其 `output` 目录。
- 兼容性：`18189`、`/api`、SQLite、任务队列、工作流协议和节点 ID 均不变。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`docker compose build`、`docker compose up -d`、`curl http://127.0.0.1:18189/api/health`。
- 回滚方式：恢复上述配置、测试和文档文件，重新构建并启动上一镜像；不使用 `docker compose down -v`，以保留数据卷。

## 2026-08-12 tar 镜像一键部署脚本

- 原因：标准化离线镜像更新并避免手动命令遗漏健康验证或误用会删除数据卷的 Compose 参数。
- 受影响文件：`deploy-server-image.sh`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 当前基线：脚本默认加载项目目录内 `packages/zly-ai-video-studio_latest.tar`，并回退兼容项目目录内同名 tar；使用 `docker compose up -d --no-build --force-recreate zly-ai-video-studio` 重建容器，并在 30 秒内轮询 `127.0.0.1:18189/api/health`。失败时输出最近 100 行容器日志。
- 兼容性：不执行 `docker compose down`，不删除命名卷；端口、API、ComfyUI 连接和数据存储不变。
- 验证命令：`bash deploy-server-image.sh`。
- 回滚方式：将上一版镜像归档作为第一个参数重新执行脚本；不使用 `docker compose down -v`。

## 2026-08-12 首位管理员容器初始化命令修正

- 原因：部署文档使用 `python - <<'PY'` 向解释器传递脚本，该形式占用标准输入，导致脚本中的 `input()` 和 `getpass()` 无法从 SSH 终端读取账号资料并报 `EOFError`。
- 受影响文件：`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 当前基线：服务器管理员在 `docker compose exec zly-ai-video-studio sh` 后使用 `python -c` 执行初始化请求；Python 代码通过命令参数传递，标准输入继续连接容器终端。`/api/auth/setup` 仍仅接受容器回环地址 `127.0.0.1:18189`。
- 兼容性：账号模型、SQLite、会话、Nginx 回环限制、容器端口与公网 API 均不变。已成功初始化的环境无需执行此操作。
- 验证命令：在未初始化环境中执行 README 的初始化命令，确认返回认证状态 JSON；随后访问 `https://<工作台域名>/api/auth/status`，确认 `setup_required` 为 `false`。
- 回滚方式：恢复三份文档中原有命令；该变更不修改容器、镜像、数据库或用户数据。

## 2026-08-12 browser-stream ComfyUI 宿主机直连

- 原因：当员工浏览器与远端 ComfyUI 位于同一宿主机时，原有链路会将视频从该主机经 FRP 传至工作台服务器，再回传至同一浏览器，产生不必要的网络传输。
- 当前基线：`GET /api/jobs/{job_id}/outputs/{output_index}/browser-direct` 仅在既有会话鉴权、任务归属校验、任务成功和 `browser-stream` 输出引用有效后，返回固定回环地址 `http://127.0.0.1:8188/view` 的受控查询地址。浏览器在写入已授权目录前先尝试该地址，并以 `ReadableStream` 分块写盘；本机没有目标 ComfyUI、CORS 不允许、文件不可读或其他直连失败时，自动回退已有的 `/download` 服务器流式交付。任务列表和媒体 API 继续隐藏 `_comfy_source`。
- 运行要求：ComfyUI 宿主机必须以 `--enable-cors-header <实际工作台 HTTPS Origin>` 启动，例如 `Start-ComfyUI.cmd --enable-cors-header https://comfyui.zlyun168.com`。禁止无参数或 `*` CORS；ComfyUI 继续只监听 `127.0.0.1:8188`，不新增端口、代理或第二套实例。
- 受影响文件：`backend/app/main.py`、`backend/app/models.py`、`frontend/src/local-resource-store.ts`、`backend/tests/test_core.py`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：既有 `/download`、桌面客户端、SQLite、任务队列、资源 Provider、ComfyUI 节点 ID、模型路径、FRP 和端口均不变；未配置 CORS 或非宿主机浏览器无感回退。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`docker compose build`；在 ComfyUI 宿主机以 Chrome/Edge 验证文件直接写入，且 DevTools Network 中视频字节来自 `127.0.0.1:8188`，再在非宿主机验证回退 `/api/jobs/.../download`。
- 回滚方式：恢复本次后端、前端和文档变更后重新构建镜像；或停止使用 `--enable-cors-header` 并重启 ComfyUI，浏览器将自动仅使用原服务器流式交付，不涉及数据库或媒体迁移。
## 2026-08-12 ComfyUI/FRP 断线队列恢复

- 原因：ComfyUI 崩溃或 FRP 重启会丢失运行中的 `prompt_id`；旧 worker 会在 `/history` 无限等待至总超时，阻塞后续串行任务，迫使运维人员重启工作台。
- 实现：`ComfyService` 对提交、上传和已提交任务轮询识别 ComfyUI/FRP 不可达；连续 30 秒无响应，或 ComfyUI 恢复响应后连续 30 秒查不到原 `prompt_id`，抛出可恢复中断。`JobWorker` 将当前任务标为 `interrupted` 并清除执行标识，随即继续队列；其他安全失败的 H3 任务也可显式重试。`POST /api/jobs/{job_id}/retry` 仅允许任务所有者或管理员将已中断或已失败且无执行标识的 H3 任务重新入队；前端任务详情提供“重新提交”按钮。
- 兼容性：端口、FRP 映射、ComfyUI 节点、数据库 schema 和既有创建任务接口不变。任务不会自动重复提交，以免 ComfyUI 实际仍在执行时重复生成；仅用户显式重新提交才会创建一次新的 ComfyUI `prompt_id`。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：恢复 `backend/app/comfy_service.py`、`worker.py`、`storage.py`、`main.py`、`frontend/src/App.tsx` 及本记录的上一个版本；无需迁移或清理 SQLite、上传素材和 ComfyUI 输出。

## 2026-08-12 工作流参数视觉控件元数据

- 原因：动态工作流注册表需要支持图标化画面比例、同弹层分辨率和可输入时长滑杆，而不让前端根据参数名分支。
- 当前基线：`workflow_registry.py` 通过 `ui_control="visual-settings"` 和 `ui_companion="quality"` 声明画面设置组合控件，通过 `ui_control="duration-slider"` 声明数值滑杆。前端只按这些元数据渲染；比例、分辨率和时长的实际校验与 ComfyUI graph 映射不变。
- 受影响文件：`backend/app/workflow_registry.py`、`frontend/src/App.tsx`、`frontend/src/index.css`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：`GET /api/modes` 的 schema 增加可忽略的展示字段；`POST /api/jobs` 的 options 结构、SQLite、任务队列、节点 ID、模型路径、固定 `7865`/`8188` 端口均不变。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：恢复本次注册表、前端、测试和文档；不涉及数据库、任务或媒体迁移。
## 2026-08-13 生图/生视频统一创作工作台

- 原因：将受管 GRS 图片执行器与既有 ComfyUI 视频执行器纳入同一任务聚合、轮次、生成项和本地交付架构。
- 当前基线：`workflow_registry.py` 声明 `media_type`、`executor`、完整 options schema、UI 层级和条件显示；视频走单一串行 ComfyUI queue，图片走最多 4 个并发 generation item。`jobs` 是任务聚合并镜像最新轮次，`job_rounds` 保存每轮参数和引用，`generation_items` 保存执行器、远端任务 ID、状态与输出。GRS 配置是单行表，API Key 使用 Fernet 加密。
- 恢复语义：有 `remote_task_id` 的 GRS 运行项在重启后继续轮询；运行中但缺少远端 ID 的项标记中断，禁止自动重提以避免重复扣费。视频继续使用既有 Comfy prompt 恢复规则。旧 `jobs` 在幂等迁移中原地生成第 1 轮与第 1 项，原 job ID、输出、交付和 Comfy 标识保留。
- 资源边界：GRS URL 仅允许 HTTPS 公网目标，每次重定向重新校验 DNS/IP，并校验图片 MIME、签名和 50 MB 上限。图片存入现有 staging provider，员工本地写入成功后删除；图片转视频由前端从已授权本地目录读取原图并重新上传，服务端不延长留存。
- 受影响文件：后端模型、注册表、SQLite、GRS 客户端/凭证服务、双通道 worker、API、前端懒加载媒介模块、管理设置、本地交付与部署配置。
- 兼容性：保留数据库文件名、`ZLY_AI_VIDEO_STUDIO_*` 前缀、包名、顶层 JobResponse、旧输出路由、固定 `7865`/`8188` 和已有 Comfy graph/节点 ID。旧 Flux 图片任务标记只读。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --filter zly-ai-video-studio-webui build`、`docker compose --env-file .env.example config`、桌面和 `390×844` 浏览器回归。
- 回滚方式：停止服务并恢复上一镜像；使用迁移前自动生成的 `*.pre-ai-studio-migration.bak` 恢复 SQLite。员工本地作品、上传素材和 ComfyUI 输出无需删除。

## 2026-08-13 图片参数弹窗选择

- 原因：图片生成的比例和分辨率需要与视频工作台采用同一套参数选择体验。
- 当前基线：两个 GRS 图片工作流的 `aspect_ratio` 在注册表中声明 `ui_control="visual-settings"`、`ui_companion="resolution"` 和比例 `ui_options`；前端继续完全依据注册表元数据复用现有 Ant Design Popover 控件。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：`POST /api/jobs` options、GRS 映射、SQLite、任务队列、ComfyUI 节点、模型路径和固定 `7865`/`8188` 端口不变。旧客户端可忽略新增展示元数据。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在桌面与 `390×844` 视口检查弹窗。
- 回滚方式：恢复本次注册表、测试和文档修改；无需迁移或清理 SQLite、任务或媒体。

## 2026-08-13 GRS 本地凭证启动与连接测试修复

- 原因：本地启动脚本未设置 Fernet 主密钥，且连接测试只读取已保存凭证，导致管理员输入正确 Key 后仍在访问上游前收到“GRS API Key 不可用”。
- 当前基线：Windows 启动脚本通过 `backend.app.local_credential_key` 首次创建并持续复用 `data/credential.key`，显式环境变量仍优先；连接测试请求可携带当前 Base URL/API Key，旧的无请求体调用继续测试已保存配置。GRS 余额请求与 Smart-Floor-Planner 一致，只在 JSON body 发送 `apiKey`，不附加 Bearer 头。
- 受影响文件：`启动本地视频工作台.bat`、`backend/app/local_credential_key.py`、`models.py`、`grs_provider.py`、`grs_client.py`、`main.py`、`frontend/src/admin/GrsProviderSettings.tsx`、测试和主文档。
- 兼容性：SQLite schema、已保存密文、任务/轮次、固定端口、ComfyUI 和 GRS 生成协议不变；服务器仍可通过 `ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY` 管理主密钥。测试接口无请求体的旧调用保持可用。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --filter zly-ai-video-studio-webui build`，并在管理页验证凭证状态和测试交互。
- 回滚方式：恢复上述文件并重启工作台；保留 `data/credential.key` 不影响旧版本，删除它前必须确认数据库中没有需要继续解密的 GRS 凭证。

## 2026-08-14 七牛云持久媒体存储

- 原因：完成结果需要在图片和视频两条执行链路中统一落到可持久化的对象存储。
- 受影响文件：`backend/app/qiniu_storage.py`、`qiniu_provider.py`、`resource_storage.py`、`storage.py`、`main.py`、`models.py`，以及 `frontend/src/admin/QiniuStorageSettings.tsx`、`Root.tsx`。
- 当前基线：SQLite 的 `qiniu_provider_settings` 保存启用状态、Bucket、区域、HTTPS 域名、对象前缀和加密后的 AK/SK；启用时运行中的 `ResourceStorage` 切换到 Qiniu。ComfyUI 和 GRS 输出都会先通过该存储上传，任务仅持久化对象键；下载 API 以 307 跳转至五分钟私有签名链接。
- 运行要求：Docker 由 `backend/requirements.txt` 安装 `qiniu==7.16.0`；本地 Windows 启动脚本会检查内置 Python 的 SDK 并在缺失时安装。
- 兼容性：未启用七牛云时仍使用环境变量指定的 `browser-stream` 或 `browser-local` 存储。已有任务继续按原路径读取，且不会被自动迁移或删除。
- 验证：`python -m unittest discover -s backend/tests -v`、`pnpm --dir frontend build`。
- 回滚：关闭管理端开关恢复本地存储；如需移除代码，恢复上述受影响文件和 `qiniu==7.16.0` 依赖，不执行批量对象删除。

## 2026-08-14 GRS 余额快照创作页展示

- 原因：让员工在图片生成前直接看到管理员最近成功查询的 GRS 上游余额。
- 当前基线：超级管理员继续通过 `POST /api/admin/providers/grs/balance` 手动查询上游并写入 SQLite；所有已登录用户可通过 `GET /api/providers/grs/balance` 获取受控刷新后的 `credits` 和 `queried_at`。图片生成页生成期间每 5 秒轮询、空闲时每 15 秒轮询；服务层以 10 秒缓存合并请求，并在每张图片成功后异步刷新。浏览器不接触 API Key。
- 受影响文件：`backend/app/models.py`、`backend/app/grs_provider.py`、`backend/app/main.py`、`frontend/src/App.tsx`、`backend/tests/test_ai_studio.py`、`backend/tests/test_core.py` 及三份主文档。
- 兼容性：数据库 schema、GRS API、任务队列、ComfyUI 节点、模型路径、端口与已有管理员查询接口均不变；未更新的客户端不受影响。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`，并在桌面及 `390×844` 视口验证图片模式中的余额展示。
- 回滚方式：恢复上述变更并重启工作台；无需删除或迁移 SQLite 中的余额快照。

## 2026-08-14 即梦式任务会话栏与任务元数据

- 原因：任务列表需要直接呈现结果封面，并提供置顶、重命名、删除等会话管理能力；图片/视频切换需要与即梦创作面板保持一致。
- 实现：`jobs.pinned` 作为 SQLite 兼容新增字段；`PATCH /api/jobs/{job_id}` 更新标题或置顶状态，`DELETE /api/jobs/{job_id}` 删除已结束任务记录；`GET /api/jobs` 按置顶优先、创建时间倒序返回。前端任务行读取结果/参考图封面并通过 Ant Design `Dropdown` 暴露菜单。
- 受影响文件：`backend/app/models.py`、`backend/app/storage.py`、`backend/app/main.py`、`backend/tests/test_ai_studio.py`、`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/DESIGN.md`。
- 兼容性：既有任务自动补齐 `pinned=0`；生成中的任务拒绝删除；ComfyUI graph、工作流节点 ID、媒体路径和端口不变。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`，并在已登录 Chrome 中检查任务行 DOM、悬浮菜单和生成类型下拉。
- 回滚方式：恢复上述后端、前端和文档文件并重启工作台；无需清理 SQLite，既有任务数据可继续保留。

## 2026-08-14 即梦式右侧创作工作台

- 原因：右侧生成区需要与即梦的创作面板保持一致，减少参考图、提示词和生成参数之间的视觉跳跃。
- 实现：保留现有工作流和参数协议，将生成表单整理为白色圆角创作卡；参考图槽位固定为 106px 高度，底部工具栏使用 36px 控件并按生成类型、工作流、画面设置、时长和提交动作排列；图片/视频切换仍由 Ant Design `Select` 驱动。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/DESIGN.md` 及三份主文档。
- 兼容性：不改变 `/api/modes`、任务提交字段、ComfyUI graph、节点 ID、模型路径和固定端口；图片与视频模式继续复用同一工作流注册表。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`，并在已登录 Chrome 中检查创作卡、参考槽位、工具栏尺寸及图片/视频切换。
- 回滚方式：恢复上述前端和文档文件并重新构建；无需迁移或清理 SQLite。

## 2026-08-14 即梦式媒体图标与视频参数栏修复

- 原因：媒体切换缺少即梦式图标，视频模型下拉触发器与菜单过窄，时长文本在窄按钮中折行，分辨率按钮的非选中态文字对比度不足。
- 实现：图片/视频选项增加 Lucide 图标；视频工作流控件扩展为 220px、菜单扩展为 248px 并取消横向溢出；时长控件扩展为 76px 并保持单行；Popover 内分辨率按钮统一浅色 hover 和可读文字颜色。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css` 及三份主文档。
- 兼容性：不改变媒体类型值、工作流注册表、参数提交和任务协议；仅调整前端控件展示。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`，并在 Chrome 中检查菜单宽度、图标节点和分辨率 computed style。
- 回滚方式：恢复上述前端和文档文件并重新构建；无需迁移或清理 SQLite。

## 2026-08-14 即梦式下拉与比例弹层细节修复

- 原因：Ant Design portal 弹层和新版 Select 根节点样式未被浅色主题完全覆盖，导致控件出现双层边框、模型名称截断和比例弹层对比度不足。
- 实现：压平创作工具栏内 `.ant-select` 根节点为 36px 无边框内容层；工作流下拉菜单扩展到 224px 以上并取消选项文本省略；Popover 改用 portal-safe 的白色表面、深色文字和蓝色选中态。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css` 及三份主文档。
- 兼容性：不改变 Select 值、工作流 ID、参数提交和任务协议；所有修复仅作用于创作工作台视觉层。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`，并在 Chrome 中读取 Select/Popover 的 computed style。
- 回滚方式：恢复上述前端和文档文件并重新构建；无需迁移或清理 SQLite。
## 2026-08-14 白色主题文字对比度与模型触发器修复

- 原因：白色创作工作台切换后，视频模型默认选择器和时长弹层沿用了过窄容器或深色主题的低对比样式，导致名称截断及刻度难以辨认。
- 当前基线：视频模型选择器的桌面宽度为 248px，触发器与下拉菜单使用相同的最小宽度；时长弹层的刻度、输入数字和滑轨在 portal 渲染时也统一使用深色文字与清晰的蓝色选中态。白色顶栏只将精确的 `.text-white` 作为白字处理，避免把 `hover:text-white` 误应用到默认状态。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/DESIGN.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改变 `/api/modes`、`POST /api/jobs`、任务数据、ComfyUI 节点、模型路径或固定 `7865`/`8188` 端口。
- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`，并在 `http://127.0.0.1:7865` 的 Chrome DOM 中检查模型文字没有溢出、时长弹层刻度和数值的计算颜色。
- 回滚：恢复上述前端样式、组件与三份文档的本次变更后重新构建前端；不涉及 SQLite、任务或媒体迁移。
## 2026-08-14 创作工具栏控件防压缩修复

- 原因：窄桌面或较长模型名称下，创作工具栏的 flex 子项允许收缩，导致模型选择器被挤压或仅剩空白区域。
- 实现：白色主题工具栏的业务控件统一禁止 flex-shrink；空间不足时依靠已有 flex-wrap 换行，模型名称、比例和时长控件保持注册表定义的可用宽度。
- 受影响文件：`frontend/src/index.css`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改变工作流注册表、任务接口、SQLite、ComfyUI 节点或固定端口。
- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`、Impeccable detector。
- 回滚：恢复本次前端样式和文档变更并重新构建前端。
## 2026-08-14 媒体类型下拉菜单宽度修复

- 原因：图片/视频生成下拉菜单按选项内容自适应时只有 100px，窄于媒体触发器，打开后产生压缩感。
- 实现：媒体 Select 使用独立的 `studio-media-select-popup` 样式，菜单最小宽度与触发器统一为 140px；模型选择器继续保持 248px。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改变生成类型、工作流注册表、任务接口或后端协议。
- 验证：Chrome DOM 计算宽度、`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚：恢复本次前端样式与文档变更并重新构建前端。

## 2026-08-15 图片联合参数选择器

- 原因：图片生成工具栏曾在比例与分辨率联合控件之后重复展示分辨率、生成数量，且浅色主题会让参考图上传图标使用不可见的白色前景。
- 受影响文件：`backend/app/workflow_registry.py`、`frontend/src/App.tsx`、`frontend/src/index.css`、`backend/tests/test_ai_studio.py`、`README.md` 与 `功能说明与扩展指南.md`。
- 当前基线：`visual-settings` 可通过可选的 `ui_companions` 数组声明其嵌入式参数；前端仅渲染未嵌入的 `primary` 参数，并从 schema 生成比例、分辨率与数量分组。`POST /api/jobs` options 和 GRS 请求映射保持不变。
- 兼容性：旧客户端可以忽略 `ui_companions`；无需数据库迁移，不改变端口、ComfyUI 实例或节点 ID。
- 验证：运行 `pnpm --dir frontend build` 和 `<ComfyUI Python> -m unittest backend.tests.test_ai_studio`，在 `http://127.0.0.1:7865` 的桌面及 `390x844` 视口打开图片参数弹层，确认工具栏只有一个摘要控件且上传图标可见。
- 回滚：恢复上述注册表、前端、测试和文档文件后重新构建前端；不需要清理任务、媒体或数据库。

## 2026-08-17 即梦式生成与资产任务栏

- 当前基线：`frontend/src/App.tsx` 以 `workspaceView` 管理“生成”和“资产”两个工作区；生成工作区的任务栏固定在全局导航右侧，分为“当前创作”和“最近”，`taskRailCollapsed` 控制其收起状态。资产条目从任务轮次输出构建，旧任务没有轮次输出时回退读取顶层 `outputs`。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`README.md`、`功能说明与扩展指南.md`。
- 兼容性：仅改变前端展示与导航状态，不改变后端 API、任务队列、SQLite schema、工作流 graph、ComfyUI 节点、模型路径或固定端口。
- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`，并在 Chrome 桌面与 `390x844` 视口完成布局和资产跳转检查。
- 回滚：恢复上述前端与文档变更并重建前端；无需数据迁移。

## 2026-08-17 即梦式资产媒体库

- 当前基线：资产工作区在 `workspaceView === "assets"` 时隐藏会话任务栏，只保留全局导航；`assetSection`、`assetMediaFilter` 和 `assetSearch` 仅管理本地展示状态。任务输出按 `job.created_at` 分组，并从既有输出数据构建图片/视频缩略图。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`README.md`、`功能说明与扩展指南.md`。
- 兼容性：不改变 `/api/jobs`、SQLite schema、任务队列、工作流 graph、ComfyUI、媒体交付或固定端口。
- 验证：`pnpm --dir frontend build`、`python -m unittest discover -s backend/tests -p "test*.py"`，并在 Chrome 桌面和 `390x844` 视口检查筛选、标签、日期网格与无横向溢出。
- 回滚：恢复上述前端和文档变更并重建前端；无需数据迁移。

## 2026-08-17 LLM 大模型服务与提示词智能优化

- 原因：工作台创作者需要对粗糙简短的提示词进行电影级运镜、动态细节与艺术构图扩写优化；支持通用 OpenAI 兼容协议与 ModelScope（魔搭社区）等平台免费大模型。
- 当前基线：
  - 后端提供通用 `OpenAICompatibleClient`，通过 `/chat/completions` 标准接口进行通信；
  - `LlmProviderService` 管理启闭状态、Base URL、Model 名称与 Fernet 加密存储的 API Key / Token；
  - SQLite 数据库通过 `llm_provider_settings` 表持久化配置，预设 ModelScope 免费模型（`Qwen/Qwen2.5-72B-Instruct`）；
  - 提供 `/api/admin/providers/llm`（管理员配置与连通性测试）与面向创作者的 `/api/llm/optimize-prompt`（提示词优化）；
  - 前端超级管理员设置提供“LLM 大模型”配置页，创作者输入框提供一键“AI 优化”按钮与动画状态。
- 受影响文件：`backend/app/llm_client.py`、`backend/app/llm_provider.py`、`backend/app/models.py`、`backend/app/storage.py`、`backend/app/main.py`、`backend/tests/test_llm.py`、`frontend/src/admin/LlmProviderSettings.tsx`、`frontend/src/Root.tsx`、`frontend/src/App.tsx`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：新增独立的 Provider 表和 API 接口，完全向下兼容已有的任务数据、ComfyUI 实例与 GRS 服务；若未配置或未启用 LLM，工作台提示词输入保持原有手动编辑行为。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码与文档文件，重新执行前端 build 即可；数据库表无破坏性改动。

## 2026-08-17 管理设置白色系高对比度视觉重构与本地凭据回退

- 原因：管理后台此前沿用暗黑背景与低对比度文字，导致 Ant Design 警告框（Alert）和文本在暗色底上严重看不清；本地未设置环境变量时凭证主密钥未自动加载。
- 当前基线：
  - 管理设置（账号管理、AI 供应商、LLM 大模型、媒体存储）全面重构为纯白/浅灰（Light Theme）现代卡片布局（`#f8f9fa` 底色、`#ffffff` 卡片面板、`#111827`/`#4b5563` 高对比度正文与 Label）；
  - `backend/app/config.py` 中的 `credential_key` 在环境变量未传入时自动从 `data/credential.key` 加载/确保本地 Fernet 主密钥，解决本地开发时主密钥不可用的问题；
  - 视觉规范已正式写入 `AGENTS.md`。
- 受影响文件：`backend/app/config.py`、`frontend/src/Root.tsx`、`frontend/src/admin/LlmProviderSettings.tsx`、`frontend/src/admin/GrsProviderSettings.tsx`、`frontend/src/admin/QiniuStorageSettings.tsx`、`AGENTS.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：不改变接口路由与数据库结构，纯视觉与配置加载优化。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复对应前端与配置文件后重新构建。

## 2026-08-17 MiniMax H3 官方提示词技能体系与通用大模型深度融合

- 原因：为了充分发挥 MiniMax-H3 视频大模型对多模态时间线（`integrated_multimodal_description`）、环境音效（`overall_soundscape`）、非剧情音乐（`non_diegetic_music`）、三维运镜语法及细分风格（产品广告、3D动画、纸艺定格、手绘实景等）的视听生成能力，将官方开源技能规范与工作台通用 LLM 优化器深度整合。
- 当前基线：
  - 后端新增 `backend/app/llm_minimax_skills.py` 技能知识库，内置 9 款官方风格技能（通用电影级、极简电商广告、3D风格化动画、立体纸艺定格、品牌宣传片、音乐短片与字效、双人游戏片头、纸拼贴定格、手绘发光实景混合）；
  - `build_h3_system_prompt` 自动识别工作流模式与参考图数量（0张 T2VA、1张 I2VA、多张 Ref2VA），自动组织 `<Picture 1>` 到 `<Picture N>` 引用与对齐标号；
  - 提供 `GET /api/llm/skills` 接口与扩展的 `POST /api/llm/optimize-prompt` 接口（支持 `skill_id`、`reference_count`、`workflow_id`）；
  - 前端输入框工具栏集成 Ant Design `Dropdown` 技能选择菜单，支持一键默认优化或快捷选择细分 MiniMax 风格技能。
- 受影响文件：`backend/app/llm_minimax_skills.py`、`backend/app/llm_client.py`、`backend/app/llm_provider.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/tests/test_llm.py`、`frontend/src/App.tsx`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：完全向下兼容，未选择特定技能时默认使用电影级通用结构；图片工作流自动适配图像模型提示词优化规则。
- 验证命令：`pytest backend/tests/test_llm.py`、`npm run build`。
- 回滚方式：恢复上述后端与前端代码，重新执行前端构建即可。

## 2026-08-21 MiniMax H3 本地输出尺寸预设

- 原因：本地 H3 的旧 `1K/2K/4K` 选项是内部 MP 档位的错误命名，无法反映实际 ComfyUI 输出尺寸。
- 当前基线：`workflow_registry.py` 是唯一的本地 H3 分辨率能力来源。标准 H3（T2V/I2V/R2V）依照 MiniMax `ResolutionSelector` 的 `MP×1024²` 和 32 像素对齐规则提供 `.2` 至 `2.0 MP` 档位，16:9 的最高值为 `1920×1088`；不再应用工作台自定义的 `1344×768` 限制。T8 全能参考和双时钟因其自定义节点明确限制像素面积，仍只提供 `.2` 至 `.98 MP`。前端完全按 `/api/modes` 动态呈现：MP 不作为主选择文案，而是根据当前画面比例计算并显示实际输出尺寸。
- 兼容性：历史明确传入的 `1K/2K/4K` 仍会保留原有 `0.2/0.3/0.5 MP` 的执行映射；已保存任务保持其 MP 参数。ComfyUI 节点 ID、模型路径、任务队列、SQLite、端口和媒体交付不变。
- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`；桌面和 `390×844` 视口验证标准 H3 可到 `1920×1088`，且 T8 不出现超过自身像素面积上限的档位。
- 回滚：恢复注册表、测试和三份文档并重建前端；不需要数据迁移或清理媒体。

## 2026-08-24 局域网 IP 访问与七牛云直链交付

- 原因：局域网 IP 的 HTTP 页面不能使用浏览器 File System Access API，原有全局强制目录设置会阻塞员工使用工作台。
- 当前基线：`frontend/src/App.tsx` 会识别非回环 IPv4/IPv6 地址；该来源不请求或强制要求本地目录，任务可直接提交。`GET /api/storage` 的 `requires_local_directory` 依据当前存储 provider 下发：七牛云持久存储为 `false`，本地暂存/流式交付为 `true`。七牛云启用后新生成的输出会标记为 `cloud`，`public_job` 与 `/api/library` 对该状态直接返回短期私有签名 URL；历史本地/流式输出仍使用原受保护下载路由，前端可直接将链接作为媒体播放地址。
- 受影响文件：`frontend/src/App.tsx`、`backend/app/main.py`、`backend/app/models.py`、`backend/app/comfy_service.py`、`backend/app/worker.py`、`backend/tests/test_core.py`、`README.md` 和 `功能说明与扩展指南.md`。
- 兼容性：SQLite、任务队列、ComfyUI 节点、模型路径、固定 `7865`/`8188` 端口和既有下载路由均不变；`127.0.0.1` 的本地目录工作流保持不变。
- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`；使用局域网 IP、`127.0.0.1` 和启用七牛云的任务结果分别验证。
- 回滚：恢复上述代码和文档后重新构建前端、重启工作台；不删除任何云端对象或 SQLite 数据。

## 2026-08-24 七牛云视频上传可靠性修复

- 原因：ComfyUI 已成功生成视频后，七牛云一次性表单上传遇到 `RemoteDisconnected` 会被 worker 当作整个任务失败。
- 当前基线：`backend/app/qiniu_storage.py` 对超过 8 MiB 的媒体使用七牛 v2 分片上传（`qiniu==7.16.0` 通过 `put_stream(..., version="v2")`，新版 SDK 通过 `put_stream_v2`）；所有可识别的连接中断、超时、HTTP 408/429/5xx 和 SDK `status_code=-1` 失败最多指数退避重试 3 次，并保留原对象键以便安全重试。上传成功后任务协议、云端签名交付和 ComfyUI 节点不变。
- 受影响文件：`backend/app/qiniu_storage.py`、`backend/tests/test_ai_studio.py`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：不改变数据库、API 字段、端口、ComfyUI 实例、节点 ID 或模型路径；未启用七牛云的本地/流式存储不受影响。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述后端、测试和文档文件并重启工作台；无需删除七牛云对象或迁移数据库。

## 2026-08-25 MiniMax H3 Web AI 导演台（Director Studio）系统

- 原因：为用户提供对标开源社区标杆（`NickPittas/DirectorsConsole`、`seesee75-Director`、`oh-my-minimaxh3-director` 与 `AIMixer`）的一站式影视级分镜编排、运镜调度、角色一致性绑定、镜头连续性接龙与成片串播系统。
- 当前基线：
  - 前端左侧全局导航新增 **【🎬 导演台】**，与“生成”和“资产”并列，采用统一的白色系高对比度（Light Theme）视觉标准；
  - 模块 `frontend/src/director/` 提供故事板、机位与运镜（`CameraControlModal`）、AI 剧本拆解（`ScriptSplitModal`）、成片串播（`SequencePlayerModal`）及主体参考槽（`<Picture 1>`~`<Picture 9>`）；
  - 后端新增 `POST /api/llm/split-script` 接口，结合内置大模型将自然语言剧本按电影工业视听语言精准拆解为结构化分镜头脚本；
  - 分镜任务完全复用固定 ComfyUI 8188 实例的 MiniMax H3 动态 Graph（T2V/I2V/R2V）、任务排队机制与本地目录自动交付。
- 受影响文件：`backend/app/models.py`、`backend/app/llm_client.py`、`backend/app/llm_provider.py`、`backend/app/main.py`、`backend/tests/test_director.py`、`frontend/src/director/*`、`frontend/src/App.tsx`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：完全向下兼容，不破坏原有任务、数据库结构、ComfyUI 实例、节点 ID 或工作流协议；导演工程在前端持久化管理并与后端任务引擎无缝同步。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码和文档后重新构建前端；无需数据库迁移。

## 2026-08-25 云端媒体下载改为同源代理流

- 原因：启用七牛云后，下载 API 对对象存储返回 HTTP 307。Toonflow 等不自动跟随 307 的客户端会把该状态当成失败（`Toonflow video download failed: HTTP 307`），无法拿到视频字节。
- 当前基线：任务 JSON 仍返回稳定的同源 `/api/jobs/.../download`，避免轮询时签名 URL 变化导致视频闪烁。下载与媒体预览接口由后端跟随五分钟私有签名链接并流式转发对象字节，响应为 200（Range 请求可为 206），不再 307 跳转到七牛云。本地文件与 ComfyUI `browser-stream` 路径不变。
- 受影响文件：`backend/app/main.py`、`backend/tests/test_core.py` 及三份主文档。
- 兼容性：SQLite、任务协议、七牛云上传、ComfyUI 节点/端口和 `download_url` 路径不变；已能跟随 307 的浏览器与桌面客户端仍可下载，只是改为接收同源字节流。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台；无需迁移数据库或删除云端对象。

## 2026-08-25 ComfyUI 重启后自动接回或重提中断视频任务

- 原因：ComfyUI 卡死、关机或进程重启会清空内存中的 `/queue` 与 `/history`。工作台原先把进行中任务标为中断后不再侦听，必须手动点“重新提交”；显存中的半成品推理本身也无法续跑。
- 当前基线：`JobWorker` 每 8 秒核对固定 `http://127.0.0.1:8188` 的队列与历史。原 `prompt_id` 仍在运行或已完成则接回并下载；ComfyUI 已恢复但任务丢失时，按 SQLite 中的原参数自动重新提交（最多 3 次）。ComfyUI 不可达时不重提，避免重复生成。正在提交、尚无 `prompt_id` 的在途任务不会被抢占。工作流错误的 `failed` 任务仍需手动重试。
- 受影响文件：`backend/app/worker.py`、`backend/app/comfy_service.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx`、`README.md`、`docs/API.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不修改 SQLite schema、ComfyUI 节点、模型路径、固定 `7865`/`8188` 端口或创建任务接口。手动 `POST /api/jobs/{job_id}/retry` 仍可用。图片 GRS 任务不自动重提。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台；无需迁移数据库或清理 ComfyUI 输出。

## 2026-08-25 GRS 生图模型可配置目录

- 原因：生图工作流写死为 GPT Image 2 / VIP，无法配置 GRS 平台已有的 Nano Banana 等模型。
- 当前基线：SQLite `grs_image_models` 保存可启用的生图模型（`workflow_id`、`provider_model`、显示名、能力档、分辨率覆盖、默认项）。`GET /api/modes` 对已启用目录项动态生成图片工作流；H3 视频工作流仍由 `workflow_registry.py` 静态注册。能力档 `gpt_image_2` / `gpt_image_2_vip` / `nano_banana` / `nano_banana_2` 决定比例、分辨率和 `grs_request_size` 映射。任务 `mode` 为字符串，历史 `grs-gpt-image-2` / `grs-gpt-image-2-vip` 继续有效。GRS 没有模型列表 API，内置种子来自 Apifox 文档，管理员可添加自定义 ID 并「同步内置目录」补齐新种子。
- 受影响文件：`backend/app/grs_catalog.py`、`backend/app/workflow_registry.py`、`backend/app/storage.py`、`backend/app/grs_provider.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/app/worker.py`、`frontend/src/admin/GrsProviderSettings.tsx`、测试与三份主文档。
- 兼容性：`POST /v1/api/generate`、ComfyUI 端口/节点、任务轮次协议不变；旧逗号分隔 `models`/`vip_models` 在首次迁移时写入目录。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台；新表可保留，旧版本忽略它。

## 2026-08-25 GRS 生图接回已出图结果

- 原因：真人参考图易触发 GRS `violation` / HTTP 400；工作台原先把 400 当无效响应、成功后仍可能回写成失败，且失败任务不暴露 `download_url`，导致员工目录有图而界面显示失败。
- 当前基线：`/v1/api/result` 解析 4xx JSON，保留结果 URL；`succeeded` 暂无 URL 时继续轮询。Worker 按 URL 列表尝试下载，落盘后不得回退为失败；`violation` 无图时给出审核说明。轮次聚合：任意生成项已有 outputs 时终态至少为 `partial`。`public_job` 与下载/交付接口按输出是否可下载授权，不再只看 `succeeded`。
- 受影响文件：`backend/app/grs_client.py`、`backend/app/worker.py`、`backend/app/storage.py`、`backend/app/main.py`、`frontend/src/App.tsx`、`frontend/src/index.css`、测试与三份主文档。
- 兼容性：SQLite schema、ComfyUI 节点/端口、GRS 提交协议不变。历史失败但带 outputs 的任务会在刷新后显示为 `partial` 并可下载。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台；无需迁移数据库。

## 2026-08-25 导演台编译器对齐现有 H3 T2V/I2V/R2V

- 原因：导演台原先提交单镜中文机位前缀而不是编译结果，参考图顺序与 `<Picture n>` 错位，批量渲染不等成功就丢进队列，Analyze 只发文字假装看图。
- 当前基线：
  - `frontend/src/director/prompt-compiler.ts` 与 `backend/app/director_compiler.py` 以纯函数锁定参考图计划、时长 2–15 秒吸附、17k+5 帧对齐、单镜编译与 ≤15s 整段 storyboard。
  - 单镜提交走现有 `/api/jobs`：无图 T2V、首/尾帧 I2V、主体参考 R2V；`mode`/`references`/`options`（`aspect_ratio`/`quality` 1K·2K·4K/`duration`）对齐注册表。
  - 批量渲染改为串行接龙：等待 succeeded 后抽尾帧写入下一镜首帧再提交。
  - 检视器显示即将提交的提示词；手动覆写只覆盖这一条。
  - Analyze 仅在当前 LLM 支持视觉时带图调用 `POST /api/llm/analyze-subject`，否则禁用。成片可导出已有剪映草稿。导演工程仍保存在浏览器 localStorage，保存前剥离 `File`，仅保留 `data:` 预览。
  - 不安装第三方导演自定义节点，不改已接入 H3 节点 ID，ComfyUI 仍为 `127.0.0.1:8188`。
- 受影响文件：`frontend/src/director/*`、`backend/app/director_compiler.py`、`backend/app/llm_client.py`、`backend/app/llm_provider.py`、`backend/app/main.py`、`backend/app/models.py`、`backend/tests/test_director.py`、`docs/API.md` 与三份主文档。
- 兼容性：不改 SQLite schema、ComfyUI 节点/端口或 `POST /api/jobs` 字段；导演工程仍保存在浏览器 localStorage。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端；无需数据库迁移。

## 2026-08-25 Docker 构建先升级 pip 并钉死 pydantic-core

- 原因：`python:3.11-slim-bookworm` 自带 pip 24.0。安装 `pydantic==2.13.4` 时若 `pydantic-core==2.46.4` 的 PyPI 索引拉取失败，解析器会报 `No matching distribution found for pydantic-core==2.46.4 (from versions: none)`，整次镜像构建退出。
- 当前基线：运行阶段先 `pip install --upgrade pip`，再用 `--prefer-binary` 与 10 次重试安装依赖；`requirements.txt` 显式钉死 `pydantic-core==2.46.4`。构建默认使用清华 PyPI 镜像与 npmmirror，可通过 `PIP_INDEX_URL`、`NPM_CONFIG_REGISTRY` 覆盖。
- 受影响文件：`Dockerfile`、`compose.yaml`、`.env.example`、`backend/requirements.txt`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：运行时 Python 包版本与本地开发一致；不改端口、SQLite、ComfyUI 或 API。
- 验证命令：`docker compose build`、`python -m unittest discover -s backend/tests -p "test*.py"`。
- 回滚方式：恢复上述文件后重新构建镜像；无需迁移数据库。

## 2026-08-25 Ollama 本地连接测试等待模型加载

- 原因：Ollama 已启动且模型已拉取时，连接测试仍用 15 秒 `chat/completions` 超时。7B 模型首次装入显存经常超过 15 秒，界面显示 Read timed out，被误判为连接失败。
- 当前基线：本地 Base URL（`127.0.0.1` / `localhost`）连接测试等待 90 秒；云端仍为 15 秒。测试前先拉 `/v1/models`，模型名不一致时直接列出本机已安装名称。Ollama 预设补充 `qwen2.5:7b-instruct` 推荐项，并说明本地 Token 可留空。
- 受影响文件：`backend/app/llm_client.py`、`backend/app/llm_provider.py`、`backend/tests/test_llm.py`、`frontend/src/admin/LlmProviderSettings.tsx`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改数据库、端口、ComfyUI 或云端 LLM 协议；仅放宽本机探测超时并改善错误文案。
- 验证命令：`python -m unittest backend.tests.test_llm`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-25 魔搭 LLM 按魔粒计费说明

- 原因：界面把魔搭标成「免费额度」，但平台已改为按魔粒扣账户余额；DeepSeek-V4 默认思考会额外消耗。
- 当前基线：LLM 设置页明确提示魔搭扣魔粒，并推荐硅基流动免费 7B / 本机 Ollama 作为零云端消耗方案。`OpenAICompatibleClient` 对 DeepSeek-V4 发送 `thinking.type=disabled`，Qwen 仍用 `enable_thinking=False`。
- 受影响文件：`backend/app/llm_client.py`、`backend/tests/test_llm.py`、`frontend/src/admin/LlmProviderSettings.tsx`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 SQLite、端口、ComfyUI 或已保存的 LLM 配置；仅纠正计费说明并降低 V4 思考消耗。
- 验证命令：`python -m unittest backend.tests.test_llm`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-25 LLM 后台拉取官方免费模型

- 原因：LLM 设置页只有硬编码推荐模型，无法跟随硅基流动官方免费目录变化。
- 当前基线：`POST /api/admin/providers/llm/models` 向上游 `GET /v1/models` 拉全量目录。硅基流动官方接口不含 Free 字段，因此再读取公开模型广场 `cloud.siliconflow.cn/open/models`，按价格为 0 / Free 标记筛选，并与账号可调用 ID 求交。管理后台用 AutoComplete 下拉选择。
- 受影响文件：`backend/app/llm_client.py`、`backend/app/llm_provider.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/tests/test_llm.py`、`frontend/src/admin/LlmProviderSettings.tsx`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 SQLite、端口或 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_llm`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-25 硅基流动免费模型对照模型广场价格

- 原因：官方 `GET /v1/models` 只有 `id` / `owned_by`，控制台 Free 徽章不在该接口里，按文字筛选会得到空列表。
- 当前基线：先拉账号可调用对话模型，再读取公开模型广场，把 `pricing.price=0` 或 Free 徽章的模型标为免费；排除 `Pro/`、停用模型以及 OCR / 嵌入 / 语音等非对话模型。设置页下拉框在已选中一项时仍展示全部已加载选项。
- 受影响文件：`backend/app/llm_client.py`、`backend/tests/test_llm.py`、`frontend/src/admin/LlmProviderSettings.tsx`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 SQLite、端口或 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_llm`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-25 导演台融合版界面冻结与实现

- 当前基线：导演台桌面端固定为镜头列表、中央预览/故事板、右侧镜头检视器、底部多轨时间轴；完整编译提示词与运行参数在折叠区回显。移动端通过 `studio-mobile-nav` 提供生成/导演台/资产切换，导演台内部使用横向镜头条和固定底部主操作。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/src/director/DirectorStudioModule.tsx`、`frontend/src/director/components/ScriptSplitModal.tsx`。
- 协议边界：不改变 `/api/jobs`、LLM 拆剧本、剪映导出接口，不改变 SQLite、localStorage 导演工程结构、H3 动态 graph、ComfyUI `127.0.0.1:8188` 或 `<Picture n>` 编译协议。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`；使用 Playwright 完成 1440×900 桌面和 390×844 移动端截图回归。
- 回滚方式：恢复上述前端文件并重新构建；无需迁移数据库或清理 ComfyUI 输出。

## 2026-08-26 工作台手动停止生成

- 原因：用户在 ComfyUI 任务历史删除执行中任务后，工作台会把丢失的 `prompt_id` 当成可恢复中断并自动重提；需要工作台侧的明确停止，且停止后禁止自动重提。
- 当前基线：`POST /api/jobs/{job_id}/cancel` 将最新轮次中排队/运行/中断的生成项标为 `cancelled`。视频执行器对固定 `http://127.0.0.1:8188` 调用 `/interrupt`（仅当该 `prompt_id` 在 `queue_running`）或 `POST /queue` 删除排队项。`JobWorker.recover()` 跳过已停止任务，最多 3 次的自动重提不作用于 `cancelled`。图片 GRS 只停止本地轮询。前端任务详情、任务列表和导演台提供「停止生成」。
- 受影响文件：`backend/app/models.py`、`backend/app/storage.py`、`backend/app/comfy_service.py`、`backend/app/worker.py`、`backend/app/main.py`、`backend/app/api_documentation.py`、测试、`frontend/src/App.tsx`、`frontend/src/director/*`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：`generation_items.cancel_requested` 为 SQLite 兼容新增列；不改节点 ID、模型路径、固定 `7865`/`8188` 端口或 `POST /api/jobs`。`interrupted` 语义不变。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台；新增列可保留。

## 2026-08-26 视频时长下限改为 2 秒

- 原因：T8 工作流 schema 已允许 2–15 秒，但标准 H3 仍校验 5–15 秒，导演台把低于 5 秒的值静默吸附到 5 秒，导致用户传入 2 秒不生效。
- 当前基线：全部 MiniMax H3 / T8 视频工作流的 `duration` 为 2–15 秒。`h3_length()` 将秒数映射到 24fps、17n+5 帧网格（2 秒 → 56 帧）。导演台 `snapH3DurationSec` 下限同步为 2 秒，不再把 2–4 秒抬到 5 秒。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/director_compiler.py`、`frontend/src/director/prompt-compiler.ts`、导演台时长输入、测试、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或 `POST /api/jobs` 字段；5–15 秒旧任务与默认值不变。1 秒及以下仍拒绝。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 导演台生成状态左右对齐

- 原因：导演台镜头列表按 `queued` 显示「排队中」，中央预览把排队态硬编码为「生成中」；`POST /api/jobs` 返回 `store.create()` 的入队快照，worker 已领取后前端仍可能停在排队。
- 当前基线：创建任务/下一轮返回 `store.get()` 的当前快照。导演台用 `shotStatusFromJob` 把任务状态映射到镜头；提交后立即轮询 `GET /api/jobs/{job_id}`；已是 `running` 的镜头不会被过期的 `queued` 列表回退。左侧、中央预览和时间轴共用排队中/生成中文案。
- 受影响文件：`backend/app/main.py`、`backend/tests/test_director.py`、`frontend/src/director/DirectorStudioModule.tsx`、`frontend/src/director/director-submit.ts`、`frontend/src/director/components/TimelineTrackMain.tsx`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或 `POST /api/jobs` 字段；`202` 仍表示已入队。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 视频生成速度预设与自定义步数

- 原因：标准 H3 固定 20 步且未加载加速 LoRA，生成偏慢；T8 虽已挂 Turbo LoRA，但步数仍是内部参数，用户无法在 4 / 8 / 20 步之间切换。
- 当前基线：全部 MiniMax H3 / T8 工作流新增 `speed`：`fast` 4 步加速、`balanced` 8 步加速（默认）、`quality` 20 步关闭加速、`custom` 再填 `custom_steps`（1–40）。4–8 步加载 `minimax_h3_turbo_4STEPS_comfyui.safetensors`；超过 8 步关闭加速。全能参考把视频/音频采样都映射为同一自定义步数；均衡预设仍为视频 8 / 音频 10。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_workflow.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口或 SQLite。旧任务没有 `speed` 时详情不回显该字段；新任务默认均衡 8 步。API 仍可显式传 `video_steps` / `audio_steps` / `steps` 覆盖预设。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 生成页管理员切换用户查看任务

- 原因：管理员只能在资产页切换用户，生成页任务栏看不到指定员工的创作记录。
- 当前基线：`GET /api/jobs?user_id=` 仅 `admin` / `super_admin` 有效，`all` 查看全部，员工传入该参数仍只返回自己的任务。生成页任务栏与资产页共用同一用户筛选；切到具体他人时隐藏创作表单和继续生成操作，新建任务仍归属当前管理员。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/media/ImageStudioModule.tsx`、`frontend/src/index.css`、`backend/tests/test_ai_studio.py`、`backend/app/api_documentation.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite、工作流协议或 `owner_user_id` 写入规则。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端。

## 2026-08-26 全能参考有图时切换 Ref2VA 权重

- 原因：T8 全能参考在上传参考图后仍加载 FL2VA，参考图条件进了 graph，但扩散权重按文生/首尾帧训练，成片几乎不跟随参考图。同时 H3 提示词仍走旧版 `@图n` 替换，会把源工作流常用的 `@图片1` 改成无效文案。
- 当前基线：全能参考无图仍为 `T2VA` + FL2VA；有图为 `Ref2VA` + `minimax_h3_ref2va_pruned_int8_convrot.safetensors`，LoRA 加载器按实际权重选择。H3/T8 把 `@图片n` / `@图n` 转成 `<Picture n>`；有图但未写标签时自动补上引用。
- 受影响文件：`backend/app/minimax_h3_t8_workflow.py`、`backend/app/comfy_service.py`、`backend/tests/test_core.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或创建任务字段。无图任务仍走 FL2VA。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 双时钟单图改为 I2VA 首帧

- 原因：双时钟单图误走 Ref2VA autogrow，T8 条件节点执行时报 `name 'task_type' is not defined`，且 pruned Ref2VA 不能完整加载 Turbo LoRA。
- 当前基线：`resolve_t8_task_type()` 始终返回节点 Combo 合法值。双时钟 `auto` 无图为 `T2VA`，单图为 `I2VA` 并连接 `first_frame`，UNet 保持 FL2VA。全能参考有图仍为 `Ref2VA`。
- 受影响文件：`backend/app/minimax_h3_t8_workflow.py`、`backend/tests/test_core.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或创建任务字段。显式 `task_type=Ref2VA` 仍连接 `ref_images`。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 pruned Ref2VA 不再加载 Turbo LoRA

- 原因：全能参考有图后加载 `minimax_h3_ref2va_pruned_int8_convrot.safetensors` 仍挂 Turbo LoRA。LoRA 的 `adaIn_proj.linear.weight` 按 2688 维 AdaLN 写入，pruned 权重实际为 `[96768, 8]`，ComfyUI 在 Model Initializing 阶段报 `shape '[96768, 8]' is invalid for input of size 260112384`。
- 当前基线：`h3_turbo_lora_compatible()` 拒绝文件名含 `pruned` 的 UNet。T8 全能参考有图、标准 H3 R2V 均跳过 LoRA 节点，仍按所选速度步数采样；无图 T8 / 文生 / 首尾帧继续对 FL2VA 全量权重使用 Bypass LoRA。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_t8_workflow.py`、`backend/app/minimax_h3_workflow.py`、`backend/tests/test_core.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或创建任务字段。速度预设仍写入 `lora_strength`，graph 构建时对 pruned 权重强制不挂 LoRA。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 导演台项目库与 SQLite 工程文档

- 原因：导演台直接进入时间轴，工程切换入口不可见，刷新不记得工程，AI 拆分的剧本原文只留在弹窗里。需要对齐「先项目库、剧本是一等文档」的产品流。
- 当前基线：SQLite `director_projects` 保存员工隔离的工程（标题、梗概、`source_script`、风格、期望镜数与时间轴 `payload_json`）。服务端剥离 `data:` 预览，参考图仍走 `data/uploads`。API：`GET/POST /api/director/projects`、`GET|PUT|DELETE /api/director/projects/{project_id}`、`POST .../copy`、`POST .../migrate`。首次打开会把浏览器 `zly_ai_director_projects_*` 迁入 SQLite 并打标防重复。进入导演台默认项目库（列表 / 新建空白 / 从剧本创建 / 复制 / 删除）；空状态提供「用示例创建」，空白工程不再预置 3 条演示分镜。打开工程后顶栏「返回项目库」；时间轴编辑防抖 PUT（约 800ms）。拆分仍用 `POST /api/llm/split-script`，前端把原文与 shots 一并写入工程。不改 H3 节点 ID，不装第三方导演节点。
- 受影响文件：`backend/app/storage.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/app/api_documentation.py`、`backend/tests/test_director.py`、`frontend/src/director/*`、`frontend/src/index.css`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 ComfyUI 端口/节点、`POST /api/jobs` 或任务表。新增表可保留；回滚后旧前端忽略该表。localStorage 在迁库后仍可作为只读备份。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；可保留 `director_projects` 表。

## 2026-08-26 导演台剧本文档与拆分确认

- 原因：项目库落盘后，已打开工程再拆仍会直接覆盖 shots；原文没有独立回看入口；移动端旧切换入口曾误绑到改标题。
- 当前基线：`TimelineProject.sourceScript` 与 SQLite `source_script` 同步。项目库「从剧本创建」新建工程。工作区内再拆弹出确认：替换当前分镜，或另存为新工程（有已生成 Take 时默认另存）。剧本文档抽屉可回看/手改原文，空文案也可 `PUT` 保存。移动端顶栏返回项目库，标题不再承担切换。
- 受影响文件：`frontend/src/director/DirectorStudioModule.tsx`、`frontend/src/director/components/ScriptDocumentDrawer.tsx`、`frontend/src/director/components/ScriptSplitModal.tsx`、`frontend/src/director/types.ts`、`frontend/src/index.css`、`backend/tests/test_director.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、`POST /api/jobs` 或 `director_projects` 表结构。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端。

## 2026-08-26 多参考加速改用全量 Ref2VA INT8

- 原因：本机已具备 `minimax_h3_ref2va_int8_convrot.safetensors`。原先有图任务强制 pruned Ref2VA，Turbo LoRA 因 AdaLN 维度被跳过，导演台多参考和全能参考无法走 4/8 步加速。
- 当前基线：快速/均衡在 R2V 与 T8 全能参考有图时加载全量 Ref2VA INT8 + `LoraLoaderBypassModelOnly`。高质量仍用 pruned 且不挂 LoRA。`h3_turbo_lora_compatible()` 继续拒绝 pruned。不引入 0.4→2.0 二采，也不改双时钟节点。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_workflow.py`、`backend/app/minimax_h3_t8_workflow.py`、`backend/tests/test_core.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或 `POST /api/jobs` 字段。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 导演台预览/成片两档渲染

- 原因：导演台原先只提交旧 `1K/2K/4K`（实际落到 0.2/0.3/0.5 MP），无法做低成本打样；预览应独立于成片分辨率。
- 当前基线：预览/成片各自可选 MP（0.4 / 0.7 / 1.0 / 2.0）和速度（4 步 + LoRA / 8 步 + LoRA / 20 步）。默认仍是预览 0.4 MP + 4 步、成片 1.0 MP + 8 步。批量接龙与整段提交走成片档。Take 记录 `renderPass`。不引入 0.4→2.0 二采。
- 受影响文件：`frontend/src/director/*`、`frontend/src/index.css`、`backend/app/director_compiler.py`、`backend/tests/test_director.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或 `POST /api/jobs` 字段；导演台现在额外传 `speed`。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-26 导演台预览/成片步数与 MP 可调

- 原因：预览 4 步在标准 H3 上容易出现彩斑；成片步数此前写死 8 步，用户无法按镜头改 MP 和步数。
- 当前基线：工程 payload 保存 `previewQuality` / `previewSpeed` / `finalQuality` / `finalSpeed`。导演台设置条用 Ant Design Select 修改。提交仍走既有 `quality` + `speed`。旧工程无新字段时，预览默认 0.4/fast，成片 MP 仍跟 `canvasTier`。
- 受影响文件：`frontend/src/director/*`、`frontend/src/index.css`、`backend/app/director_compiler.py`、`backend/tests/test_director.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 表结构或 `POST /api/jobs` 字段。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 未生效的条件参数不再进入任务详情

- 原因：创建页按 `ui_visible_when` 隐藏「自定义步数」，但任务详情仍把未选自定义时的默认 `custom_steps=8` 当成创作参数回显，和实际采样步数冲突。
- 当前基线：`request_parameters` 跳过当前不满足 `ui_visible_when` 的 option；快速/均衡/高质量不回显自定义步数，仅自定义回显。VIP 自定义宽高同样只在分辨率选 CUSTOM 时出现。创建提交也不再带上隐藏字段。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/main.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或 `POST /api/jobs` 字段。已有任务刷新详情即可，无需迁移。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-27 本机 Windows 后端热更新与可关闭控制台

- 原因：本地 `uvicorn --reload` 在 Windows 上走 StatReload，文件变更时把 `CTRL_C_EVENT` 发给整个控制台进程组，监督进程随 worker 一起退出，表现为改代码后服务挂掉且无法热更新。关闭 CMD 时 worker 卡在 `Waiting for application shutdown`（ComfyUI 轮询线程非 daemon），窗口关不掉。
- 当前基线：`启动本地视频工作台.bat` 直接运行 `backend/dev_reloader.py`（整合包 Python 的 `python310._pth` 隔离 `sys.path`，不能 `python -m backend.dev_reloader`）。监督器在独立进程组、无控制台事件的子进程中启动 uvicorn（无 `--reload`，并传 `--app-dir`），监视 `backend/app` 的 `.py` 变更后 `taskkill /F /T` 重启；崩溃也会退避重启。启动时关闭 CMD QuickEdit，避免鼠标点选把进程暂停；点击关闭或 Ctrl+C 立即杀掉子进程树并退出。若 7865 上已有本工作台进程但不响应 `/api/health`，启动脚本会强制结束后再拉起。Docker / 生产仍直接运行 uvicorn，不启用监督器。
- 受影响文件：`backend/dev_reloader.py`、`backend/app/worker.py`、`backend/tests/test_dev_reloader.py`、`backend/requirements.txt`、`启动本地视频工作台.bat`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 ComfyUI 节点、端口、SQLite 或 `POST /api/jobs`。`7865` / `8188` 不变。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_dev_reloader.py"`、`python -m unittest discover -s backend/tests -p "test*.py"`。
- 回滚方式：恢复上述文件；启动脚本改回 `uvicorn ... --reload --reload-dir backend`。

## 2026-08-27 LightX2V 工作流接入与创作页分组

- 原因：本机已下载 LightX2V MiniMax H3 加速 LoRA 与前端格式工作流；官方 H3 四步在 0.2 MP + `res_multistep` 上观感差，需要独立 1.0 MP / euler 路径，且工作流下拉需要按家族分组。
- 当前基线：新增 `minimax-h3-lightx2v-t2v` / `i2v` / `r2v`，动态 API graph 使用 euler、`LoraLoaderModelOnly`、`MiniMaxH3SigmaShift` 和 SageAttention。默认 1.0 MP、快速 4 步；文生/首尾帧加载 `minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors`，均衡改 8 步 LoRA；多参考加载 `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`。基模仍用工作台既有全量 INT8 FL2VA/Ref2VA，不接入源 JSON 里的 BF16/experimental UNET、未审查 CLIP 或 RTX 二倍超分。`GET /api/modes` 下发 `catalog_group`，创作页分为 LightX2V、官方 MiniMax H3、自定义（T8）。固定 ComfyUI `extra_model_paths.yaml` 增加 `loras: lightx2v`。官方三个 H3 与 T8 的节点 ID 不变；导演台仍只走官方 T2V/I2V/R2V。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_lightx2v_workflow.py`、`backend/app/models.py`、`backend/app/comfy_service.py`、`backend/app/api_documentation.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx`、`frontend/src/index.css`、固定 ComfyUI `extra_model_paths.yaml`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改已有工作流节点 ID、端口、SQLite 或 `POST /api/jobs` 字段；新 mode 为增量 ID。改 `extra_model_paths.yaml` 后需重启 ComfyUI 才能列出 LightX2V LoRA。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台与 ComfyUI；已创建的 LightX2V 任务记录可保留为历史。

## 2026-08-27 LightX2V 前端工作流写入 ComfyUI 工作流库

- 原因：工作台接入的是动态 API graph，ComfyUI 侧边栏「工作流」只扫描 `user/default/workflows`，因此下载目录里的 LightX2V JSON 不会出现在 MiniMax H3 旁边。
- 当前基线：把源 JSON 复制到固定 ComfyUI 的 `user/default/workflows/LightX2V/`，文件名为「LightX2V 文生视频」「LightX2V 首尾帧视频」「LightX2V 多参考加速」。首尾帧由文生 JSON 接上 `first_frame`/`last_frame` 两个 LoadImage 得到。LoRA 控件改为 `extra_model_paths` 能解析的文件名。源文件仍留在 `G:\ComfyUI-Models\lightx2v`。工作台 API graph 与官方三个 H3 JSON 不改。
- 受影响文件：固定 ComfyUI `user/default/workflows/LightX2V/*.json`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或 `POST /api/jobs`。侧边栏点刷新即可看到新分组；`extra_model_paths.yaml` 的 `loras: lightx2v` 仍需重启 ComfyUI 后 LoRA 才进模型列表。
- 验证命令：确认该目录存在三份 JSON；ComfyUI 工作流浏览出现 LightX2V 分组。
- 回滚方式：删除 `user/default/workflows/LightX2V` 目录。

## 2026-08-27 LightX2V ComfyUI JSON 对齐本机模型名

- 原因：侧栏三份 LightX2V JSON 仍使用源作者机器上的 `MiniMax-H3\` 前缀、experimental w4a8 UNET、未审查 CLIP、BF16 Ref2VA，以及本机 `vae_approx` 没有的 `taeh3.safetensors`，ComfyUI 显示模型找不到。
- 当前基线：三个 JSON 的加载器改为与工作台 / 官方 H3 相同的无前缀文件名。文生与首尾帧使用全量 INT8 FL2VA + FL2V 4 步 LoRA + nvfp4 CLIP；多参考使用全量 INT8 Ref2VA + Ref2V 4 步 LoRA。VAE 去掉目录前缀。`ModelPreviewOverrideKJ` 的 tiny VAE 改为 `none`。工作台 API graph 与官方三个 H3 JSON 不改。
- 受影响文件：固定 ComfyUI `user/default/workflows/LightX2V/*.json`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点 ID、端口、SQLite 或 `POST /api/jobs`。已在画布里打开的旧图需重新从侧栏打开才会读到新文件名。
- 验证命令：`GET http://127.0.0.1:8188/object_info` 中 UNET/CLIP/VAE/LoRA 下拉已包含上述文件名。
- 回滚方式：从 `G:\ComfyUI-Models\lightx2v\工作流` 重新复制源 JSON。

## 2026-08-27 LightX2V 侧栏 JSON 去掉本机没有的自定义节点

- 原因：文生/首尾帧 JSON 启用了 `RAMCleanup`（包名 `Comfyui-Memory_Cleanup`），固定 ComfyUI 未安装该包，打开工作流报缺失节点。多参考图里还有已 bypass 的 `RTXVideoSuperResolution`，同样不在本机。
- 当前基线：从三份 JSON 删除 `RAMCleanup`；多参考同时删除未启用的 RTX 超分链路（节点 143/144/148/150）。保存视频仍走原有 `SaveVideo`。不向固定 ComfyUI 安装新 custom_nodes。
- 受影响文件：固定 ComfyUI `user/default/workflows/LightX2V/*.json`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改官方 H3 JSON、节点 ID、端口或工作台 API。需从侧栏重新打开工作流。
- 验证命令：对 `GET http://127.0.0.1:8188/object_info` 比对三份 JSON 的 `type`；除画布说明用的 `MarkdownNote` 外均已安装。
- 回滚方式：从 `G:\ComfyUI-Models\lightx2v\工作流` 重新复制源 JSON。

## 2026-08-27 安装 LightX2V 缺失节点并恢复原版侧栏 JSON

- 原因：用户要求补齐刚才删掉的缺失节点包，并把三份 LightX2V 工作流恢复为源 JSON。
- 当前基线：固定 ComfyUI `custom_nodes` 增加 `Comfyui-Memory_Cleanup` 与 `Nvidia_RTX_Nodes_ComfyUI`；ComfyUI Python 已安装 `nvidia-vfx 0.1.0.1`（模块名 `nvvfx`）。侧栏三份 JSON 从源文件恢复图结构（含 `RAMCleanup` / RTX 超分），加载器改回本机无前缀 INT8 UNET、nvfp4 CLIP、VAE 和 LightX2V LoRA，预览 tiny VAE 为 `none`。工作台 API graph 不改。
- 受影响文件：固定 ComfyUI `custom_nodes/Comfyui-Memory_Cleanup`、`custom_nodes/Nvidia_RTX_Nodes_ComfyUI`、Python `site-packages/nvvfx`、`user/default/workflows/LightX2V/*.json`、`G:\ComfyUI-Models` 下若干硬链接、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改官方 H3 JSON 节点 ID、端口或 `POST /api/jobs`。必须重启 ComfyUI 后新节点才会出现在 `object_info`。
- 验证命令：重启后 `GET http://127.0.0.1:8188/object_info` 含 `RAMCleanup` 与 `RTXVideoSuperResolution`。
- 回滚方式：删除上述两个 custom_nodes 目录并卸载 `nvidia-vfx`。

## 2026-08-27 LightX2V 原版图结构保留本机模型路径

- 原因：从源 JSON 整份拷回后，加载器又变成别人机器上的 `MiniMax-H3\` 前缀、experimental w4a8、未审查 CLIP、BF16 Ref2VA 和 `taeh3`，本机 `extra_model_paths` 只暴露无前缀文件，再次报模型找不到。
- 当前基线：三份侧栏 JSON **保留** 已安装的 `RAMCleanup` / RTX 节点；UNET/CLIP/VAE/LoRA/tiny VAE 改回与工作台相同的本机文件名。文生/首尾帧用全量 INT8 FL2VA + FL2V 4 步 LoRA；多参考用全量 INT8 Ref2VA + Ref2V 4 步 LoRA。
- 受影响文件：固定 ComfyUI `user/default/workflows/LightX2V/*.json`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改官方 H3 JSON、节点 ID、端口或工作台 API。已打开的画布需从侧栏重新打开。
- 验证命令：JSON 中加载器 widgets 不含 `MiniMax-H3\` / `w4a8` / `taeh3`；`GET http://127.0.0.1:8188/object_info` 下拉含上述本机文件名。
- 回滚方式：仅恢复模型控件时可再从 `G:\ComfyUI-Models\lightx2v\工作流` 拷源 JSON，但会重新出现找不到模型。

## 2026-08-27 视频任务空闲后释放 ComfyUI 显存与内存

- 原因：ComfyUI 默认在 prompt 结束后把 UNET/CLIP/VAE 留在显存和内存里，方便下一次更快加载。工作台动态 API graph（官方 H3、LightX2V、T8）都不含 `VRAMCleanup`/`RAMCleanup`，Worker 也从未调用 `POST /free`，所以工作台显示“没有正在生成的任务”时显存/内存仍接近满载。
- 当前基线：Worker 在启动时（无待恢复视频任务）以及每条本地视频任务结束（成功、失败或停止）后，若工作台已无排队/运行中的 H3 任务、且固定 ComfyUI `/queue` 为空，则 `POST /free`（`unload_models=true`、`free_memory=true`），并提交仅含 `VRAMCleanup` + `RAMCleanup` 的短 prompt（不改生成图节点 ID；`RAMCleanup` 不扫描其他进程）。`/free` 只是标志位，空闲时 prompt worker 最长可能 1000 秒才处理；短 prompt 用于立刻唤醒并卸载。队列里还有下一条视频时不卸载。图片/GRS 任务不占用本机 ComfyUI 显存。
- 受影响文件：`backend/app/comfy_service.py`、`backend/app/worker.py`、`backend/tests/test_core.py`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 ComfyUI 节点、端口、SQLite 或 `POST /api/jobs`。下一条视频仍会重新装模，首包会比“热模型”慢。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`。
- 回滚方式：恢复上述文件并重启工作台；无需迁移数据库或模型。

## 2026-08-27 八步双加速工作流分组

- 原因：用户提供的 ComfyUI 前端 JSON「minimax_h3八部双加速」用 8 步 FL2V Turbo LoRA 串联 `PathchSageAttentionKJ` 与 `MiniMaxH3MemoryEfficientSageAttentionPatch`。该加速链与官方 H3 / LightX2V / T8 均不同，需要独立分组，且不能把 `MiniMaxH3Director` 前端节点提交到 `/prompt`。
- 当前基线：新增 `minimax-h3-dual-accel-t2v` / `i2v` / `r2v`。动态 API graph 为全量 INT8 FL2VA/Ref2VA → `LoraLoaderModelOnly`（`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`，强度 1.0）→ `PathchSageAttentionKJ`（`sage_attention=auto`，`allow_compile=false`）→ `MiniMaxH3MemoryEfficientSageAttentionPatch` → `MiniMaxH3SigmaShift`(12/3) → 标准 `MiniMaxH3ImageToVideo` / `MiniMaxH3ReferenceToVideo`。默认 0.4 MP、8 步 `res_multistep`。高质量 20 步关 LoRA、改 pruned。源 JSON 里的 pruned UNET + Turbo LoRA 不采用（AdaLN 维度不兼容）。官方三个 H3、LightX2V、T8 节点 ID 不变；导演台仍只走官方 T2V/I2V/R2V。
- 受影响文件：`backend/app/models.py`、`backend/app/workflow_registry.py`、`backend/app/minimax_h3_dual_accel_workflow.py`、`backend/app/comfy_service.py`、`backend/app/api_documentation.py`、`backend/tests/test_core.py`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改已有工作流节点 ID、端口、SQLite 或 `POST /api/jobs` 字段；新 mode 为增量 ID。LoRA 已在 `extra_model_paths.yaml` 的 `loras: lightx2v`。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台；已创建的八步双加速任务记录可保留为历史。

## 2026-08-27 ComfyUI 连接地址可配置

- 原因：视频后端地址原先只读启动时的 `ZLY_AI_VIDEO_STUDIO_COMFY_URL`，改端口或 FRP 映射必须改环境变量并重启，管理后台也无法查看或测试当前目标。
- 当前基线：SQLite `comfy_provider_settings` 保存生效地址。首次启动用环境变量（缺省 `http://127.0.0.1:8188`）播种。超级管理员在「管理设置 → AI 供应商」读写 `/api/admin/providers/comfy`，测试走 `/system_stats`，不必先保存。`ComfyService` 经 `url_resolver` 读取当前地址，保存后立即用于后续提交/轮询/中断。工作台同一时间仍只连接一个实例。宿主机浏览器直连交付继续固定 `http://127.0.0.1:8188/view`。
- 受影响文件：`backend/app/comfy_provider.py`、`backend/app/comfy_service.py`、`backend/app/storage.py`、`backend/app/main.py`、`backend/app/models.py`、`backend/app/api_documentation.py`、`backend/tests/test_comfy_provider.py`、`frontend/src/admin/ComfyProviderSettings.tsx`、`frontend/src/Root.tsx`、`AGENTS.md`、`README.md`、`功能说明与扩展指南.md`、`docs/API.md` 和本文档。
- 兼容性：不改节点 ID、工作台 `7865`、`POST /api/jobs` 或浏览器直连协议。已有数据库启动时自动建表播种。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_comfy_provider.py"`、`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台；新表可保留。

## 2026-08-27 导演台画风目录与 Recipe payload

- 原因：导演台要对标对话导演 → Recipe 方案，时间轴 payload 无法表达剧本/画风/人物/场景；画风不能由模型随意发明名称。
- 当前基线：JSON 种子 `backend/app/director_catalog/art_styles.json` 提供 9 类 34 条画风（电影感/商业/未来感/复古/动漫/3D/插画/写实/实验性），`id`/`name_en`/`promptPrefix`/`keywords` 对齐 OpenDirector 的 `art_styles` 种子（`as_1001`–`as_1034`）。种子里的 `imageUrl` 仍指向 `files.seme.cc/styles/style_01.jpg`–`style_34.jpg`；对外 API 的 `imageUrl` 改写为同源 `/api/director/art-styles/{id}/preview`。`GET /api/director/art-styles` 登录后返回目录。`director_projects.payload_json` 以 `kind` 区分：缺省为旧时间轴；`director_recipe` 含 `script` / `artStyle` / `characters` / `locations` / `scenes`（场内 `shots`）/ `agentStatus`；`batch_run` 为批量裂变。Recipe 的 `artStyle` 必须选自目录，保存时覆盖名称与 `promptPrefix`。旧工程可只读打开，或 `POST /api/director/projects/{id}/convert-to-recipe` 把时间轴 shots 映射为 scenes、主体槽映射为人物/场景。生成进度统计 Recipe 场内镜头。不改表结构、节点 ID 或 `POST /api/jobs`。
- 受影响文件：`backend/app/director_catalog/`、`backend/app/director_recipe.py`、`backend/app/storage.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/app/api_documentation.py`、`backend/tests/test_director.py`、`frontend/src/director/types.ts`、`frontend/src/director/director-api.ts`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：旧时间轴 payload 无 `kind` 时仍按时间轴读写；不自动转换。不改 ComfyUI 端口/节点。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；已写入的 Recipe payload 回滚后旧前端可忽略未知字段。

## 2026-08-27 导演台双引擎（Recipe + 短视频批量）

- 原因：时间轴与 9 槽参考图不适合人物/场景定妆和批量短视频；要对标对话导演 → Recipe → 出片，同时媒体层继续走 GRS 与固定 `127.0.0.1:8188` MiniMax H3。
- 当前基线：导演台首页为「导演创作 / 短视频批量」双卡片。导演创作：一句话经 Python 9 Agent（研究可跳过、脚本、画风、分镜、角色、场景、配音、配乐、媒体编译）写入 Recipe；人物/场景卡提交 GRS 定妆；分镜卡片墙提交 H3，参考图在编译时自动装箱 ≤9 张 `<Picture n>`，无图 T2V、有图 R2V。短视频批量：主题裂变多脚本并并行 `minimax-h3-t2v`。不引入 LangGraph / WaveSpeed / Pexels / Edge TTS。旧时间轴工程打开时转为 Recipe。`POST /api/llm/split-script` 仍保留。
- 受影响文件：`backend/app/director_agents.py`、`backend/app/director_jobs.py`、`backend/app/director_compiler.py`、`backend/app/director_recipe.py`、`backend/app/llm_provider.py`、`backend/app/main.py`、`backend/app/models.py`、`backend/tests/test_director.py`、`frontend/src/director/DirectorStudioModule.tsx`、`DirectorHome.tsx`、`DirectorRecipeStudio.tsx`、`DirectorBatchStudio.tsx`、`director-api.ts`、`types.ts`、`frontend/src/index.css`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 ComfyUI 节点 ID、端口 7865/8188、`POST /api/jobs` 字段或员工隔离。旧时间轴 payload 仍可读，打开时转换。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；已生成的 GRS/H3 任务记录可保留。

## 2026-08-27 导演流水线进度条实时刷新

- 原因：研究步可跳过，进度会立刻停在 11%；后续脚本等 Agent 在等大模型时只写内存 `running`，要等整次 `POST /api/director/recipes/run` 返回后界面才跳变，看起来像卡住。
- 当前基线：每个 Agent 开始时把 `agentStatus=running` 写入 SQLite；运行中前端每 1.5 秒 `GET` 当前工程。进度条按已完成步数 + 半步进行中计算，文案显示「正在运行：脚本」。单步 `/step` 在调用大模型前同样落盘 running。不改端口、节点或 `POST /api/jobs`。
- 受影响文件：`backend/app/director_agents.py`、`backend/app/main.py`、`backend/tests/test_director.py`、`frontend/src/director/DirectorRecipeStudio.tsx`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：Recipe payload 字段不变；旧工程无 running 快照时行为与原先一致。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；无需迁移数据库。

## 2026-08-27 导演定妆与场景卡实时进度

- 原因：人物/场景定妆提交 GRS 后卡片只有按钮，任务进度只在任务列表里，界面看起来没动；GRS 进度还按 12 小时超时映射，会长期停在约 12%。
- 当前基线：人物卡与场景卡各自显示该条 GRS 任务进度条与文案（排队/生成中 xx%）。任务列表仍 1.6 秒轮询。GRS 生图进度按约 2 分钟预期映射到 12–90%，完成时 100%；超时仍为 12 小时。不改端口、节点或 `POST /api/jobs`。
- 受影响文件：`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/director-submit.ts`、`frontend/src/director/prompt-compiler.contract.ts`、`frontend/src/index.css`、`backend/app/worker.py`、`backend/tests/test_core.py`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：Recipe payload 字段不变；图片任务仍走现有 GRS Worker。
- 验证命令：`python -m unittest backend.tests.test_core.WorkerTests.test_grs_image_progress_moves_within_two_minutes`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；无需迁移数据库。

## 2026-08-27 导演分镜卡实时进度

- 原因：分镜墙提交 H3 后只有英文 status 和按钮 loading，进度只在任务列表；「全部出片」时排队中的镜头完全没有进度反馈。
- 当前基线：每张分镜卡显示独立进度条。排队显示「排队等待出片」，正在跑的镜头跟 ComfyUI `jobs.progress` 显示「出片中 xx%」。任务列表仍 1.6 秒轮询。不改端口、节点或 `POST /api/jobs`。
- 受影响文件：`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/director-submit.ts`、`frontend/src/director/prompt-compiler.contract.ts`、`frontend/src/index.css`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：Recipe payload 已有 `progress`/`jobId`；视频任务仍走现有 H3 Worker。
- 验证命令：`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；无需迁移数据库。

## 2026-08-27 关闭本机前后端端口脚本

- 原因：`启动本地视频工作台.bat` 把 Vite 放在独立控制台，FastAPI 由 `dev_reloader.py` 以新进程组拉起；只关其中一个窗口时，`5173` 或 `7865` 仍可能被占用。
- 当前基线：根目录 `关闭本地视频工作台.bat` 结束监听 `5173` 的 Vite/Node 进程树、监听 `7865` 且命令行匹配工作台（`backend.app.main:app` / `dev_reloader` / `uvicorn` / 旧 Gradio）的进程树、残留 `dev_reloader.py`，以及标题为 `ZLY AI Video Studio` / `ZLY AI Video Studio Vite` 的控制台。不处理 `8188`。无关占用只提示。
- 受影响文件：`关闭本地视频工作台.bat`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改工作台端口、API、SQLite 或 ComfyUI。
- 验证命令：双击脚本后 `netstat -ano | findstr ":5173 :7865"` 无 LISTENING。
- 回滚方式：删除该批处理并恢复本节文档。

## 2026-08-27 GRS 定妆结果允许 *.aitohumanize.com

- 原因：GRS 结果 CDN 从 `file1.aitohumanize.com` 扩到 `file8` 等子域，仍解析到 RFC 2544 `198.18.0.0/15`。下载只放行 file1，已成功的场景图被拒绝；「generate image failed」原文也不好懂。
- 当前基线：`*.aitohumanize.com` 在解析到 `198.18.0.0/15` 时允许下载，其他主机仍禁止非公共 IP。上游 `generate image failed` 显示为「上游生图失败，请重新生成」。不改端口、节点或 `POST /api/jobs`。
- 受影响文件：`backend/app/grs_client.py`、`backend/tests/test_ai_studio.py`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：既有 file1 路径不变；其他域名的 SSRF 拦截不变。
- 验证命令：`python -m unittest backend.tests.test_ai_studio.GrsClientTests.test_download_allows_grs_benchmark_cdn_only`。
- 回滚方式：恢复上述文件并重启工作台；无需迁移数据库。

## 2026-08-27 导演定妆转存七牛并保存对象地址

- 原因：GRS 定妆完成后工程只记下同源 `/api/jobs/.../download`，未把七牛对象地址写入 Recipe；云存储上的图也无法作为 H3 参考图落盘。
- 当前基线：启用七牛云时 GRS/ComfyUI 输出写入对象键，并保存不含过期签名的 `cloud_url`（`https://域名/对象键`）。定妆任务成功后把该地址写进对应人物/场景的 `imageUrl`；打开工程时若任务已成功也会补写并落盘。任务 JSON 的 `download_url` 仍为同源下载路径，卡片预览走该路径以免私有空间直链打不开。提交分镜时若本地没有定妆文件，会按签名链接把对象拉到 `staging/director-plates` 再作为 R2V 参考。不把过期签名 URL 写入数据库。
- 受影响文件：`backend/app/qiniu_storage.py`、`resource_storage.py`、`worker.py`、`comfy_service.py`、`director_jobs.py`、`main.py`、`models.py`、`frontend/src/director/DirectorRecipeStudio.tsx`、`director-submit.ts`、测试与三份主文档。
- 兼容性：未启用七牛云时 `imageUrl` 仍为同源下载路径。已有任务不自动迁移对象；打开工程时若输出已是 `cloud` 会补写对象地址。不改节点、端口或 `POST /api/jobs` 字段。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorAssetCloudTests backend.tests.test_director.DirectorProjectApiTests.test_get_recipe_persists_qiniu_image_url backend.tests.test_ai_studio.QiniuStorageTests.test_object_url_is_canonical_https_path_not_signed`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；无需删除七牛对象或迁移数据库。

## 2026-08-27 导演台画风预览同源代理

- 原因：画风卡片把 OpenDirector CDN 当 `<img src>`，浏览器拿不到图时整卡显示「无预览」；目录接口也不应把外链交给前端。
- 当前基线：`GET /api/director/art-styles` 的 `imageUrl` 固定为 `/api/director/art-styles/{id}/preview`。该预览接口需登录，命中 `backend/app/director_catalog/previews/{id}.jpg` 缓存，否则服务端从 `files.seme.cc/styles/style_NN.jpg` 拉取 JPEG 再返回。前端按 style id 组装同源地址，加载失败才显示「无预览」。不改表结构、节点 ID 或 `POST /api/jobs`。
- 受影响文件：`backend/app/director_catalog/__init__.py`、`backend/app/main.py`、`backend/app/api_documentation.py`、`backend/tests/test_director.py`、`frontend/src/director/types.ts`、`DirectorRecipeStudio.tsx`、`DirectorBatchStudio.tsx`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：种子 JSON 仍保存 CDN 原址；已保存 Recipe 里的外链 `imageUrl` 会被目录覆盖为同源预览路径。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；可删除 `previews/*.jpg` 缓存。

## 2026-08-27 GRS 连接超时不再误报扣费风险

- 原因：导演台定妆在连不上 `grsai.dakka.com.cn` 时把 `ConnectTimeout` 原文写进任务，并一律标成「提交结果不确定、可能重复扣费」。TCP 未建立时请求并未发出。本机 Clash 假 IP（`198.18.0.0/15`）对该国内节点也不稳定。
- 当前基线：GRS 提交/查询连接超时 12 秒、读超时 60 秒；连接失败自动重试一次。未发出请求时任务为失败，提示可改用国际节点 `https://grsaiapi.com`，不提示扣费。仅在已发出但等不到响应时才要求显式重试。管理后台 Base URL 旁说明国内/国际节点。
- 受影响文件：`backend/app/grs_client.py`、`backend/app/worker.py`、`frontend/src/admin/GrsProviderSettings.tsx`、`backend/tests/test_ai_studio.py`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：`POST /v1/api/generate`、ComfyUI 节点/端口、任务字段不变。已保存的 GRS Base URL 不会自动改写。
- 验证命令：`python -m unittest backend.tests.test_ai_studio.GrsClientTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；无需迁移数据库。

## 2026-08-27 前端 BrowserRouter 鉴权路由

- 原因：页面身份原先在 `Root` / `App` 的 React state 中，URL 恒为 `/`，刷新丢失当前页，管理 Tab 无法直达。
- 当前基线：`frontend/src/main.tsx` 使用 `BrowserRouter`。`frontend/src/paths.ts` 集中声明路径；`frontend/src/router.tsx` 声明 `<Routes>`。`Root.tsx` 仍用 `/api/auth/status` 做闸门（不引入 router loader）：`setup_required` → `/setup`，未登录 → `/login`（记下原路径），`must_change_password` → `/password`，员工访问 `/admin/*` → `/generate/video`。`/` 与未知路径在已登录时去 `/generate/video`。管理设置抽出为 `AdminSettings`，Tab 受控于 `useParams().tab` 并 `navigate`。创作台 `App` 作为已登录壳挂在生成/导演/资产路径下，避免这些路径互切时卸载；进入 `/admin/:tab` 仍卸载 `App`。登出 `queryClient.clear()` 后硬跳 `/login`。FastAPI `GET /{path:path}` 回退 `index.html`（无构建产物时 404），`/assets/{file}` 提供打包静态资源，精确路径 `/assets` 仍回退 SPA。无需改 Nginx。
- 受影响文件：`frontend/package.json`、`frontend/src/main.tsx`、`frontend/src/Root.tsx`、`frontend/src/router.tsx`、`frontend/src/paths.ts`、`frontend/src/auth/AuthScreens.tsx`、`frontend/src/admin/AdminSettings.tsx`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 API、SQLite、ComfyUI 节点或端口。
- 验证命令：`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端；无需数据库迁移。

## 2026-08-27 创作台与导演台 URL

- 原因：鉴权路由落地后，生成/导演台/资产与选中任务仍在组件 state，刷新会丢当前页，无法收藏或分享具体任务和导演工程。
- 当前基线：创作台左侧「生成 / 导演台 / 资产」为 `NavLink`。`workspaceView`、`mediaType`、`selectedJobId` 只从 URL 读取：`/generate/image|video/:jobId?`、`/director`、`/director/:projectId`、`/director/batch/:projectId`、`/assets`。切图/视频时先写入 `draftsRef` 再 `navigate`；提交、选任务、新建对话、从图做视频都会改路径。URL 上的任务与媒介不一致时按任务真实 `media_type` 纠偏。导演台创建/打开/删除当前工程走对应路径，返回列表到 `/director`。提示词草稿、任务栏折叠、资产筛选仍用组件 state。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/paths.ts`、`frontend/src/router.tsx`、`frontend/src/director/DirectorStudioModule.tsx`、`frontend/src/index.css`、`backend/app/main.py`、`backend/tests/test_ai_studio.py`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 API、SQLite、ComfyUI 节点或端口。旧书签仍是 `/`，会重定向到 `/generate/video`。
- 验证命令：`python -m unittest backend.tests.test_ai_studio.FrontendSpaFallbackTests`、`pnpm --dir frontend build`；桌面 1440 与移动 390 检查刷新、进退与导演工程直达。
- 回滚方式：恢复上述文件并重新构建前端；无需数据库迁移。

## 2026-08-27 启动脚本始终打开 5173

- 原因：FastAPI 已在 7865 健康运行时，启动脚本会直接打开 `127.0.0.1:7865` 的 `frontend/dist`，开发改动不可见。
- 当前基线：`启动本地视频工作台.bat` 始终打开 `http://127.0.0.1:5173`。7865 已健康时补启或复用 Vite 后仍打开 5173，并退出而不重复拉起 uvicorn。5173 已被 Vite/pnpm/node 占用时复用。局域网与生产仍通过 7865 访问静态构建。
- 受影响文件：`启动本地视频工作台.bat`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 API、SQLite、ComfyUI 或端口号。
- 验证命令：双击启动脚本，确认浏览器打开 `http://127.0.0.1:5173`；7865 已运行时再双击仍打开 5173。
- 回滚方式：恢复启动脚本与三份文档。

## 2026-08-27 官方 H3 预留显存并启用 Sage

- 原因：官方 MiniMax H3 首尾帧在 16GB 显卡的 `SamplerCustomAdvanced` 上 CUDA OOM（已占用 12.51 GiB，再申请 2.56 GiB INT8 QKV）。官方 API graph 原先没有显存预留和 H3 Sage。
- 当前基线：官方 `minimax-h3-t2v/i2v/r2v` 在节点 15（可选 LoRA）之后接入 `ReservedVRAMSetter`（预留 3 GB、`clean_gpu_before=true`）和 `MiniMaxH3MemoryEfficientSageAttentionPatch`。节点 1–15 ID 不变。内部 `use_sage_attention` 默认开启。导演台仍走官方三个模式。
- 受影响文件：`backend/app/minimax_h3_workflow.py`、`backend/app/workflow_registry.py`、`backend/tests/test_core.py`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改端口、SQLite 或 `POST /api/jobs` 外部字段。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-27 导演台分镜页可改分辨率

- 原因：Recipe 成片默认 1.0 MP，分镜页没有分辨率控件，16GB 出片 OOM 后无法在当页改画质。
- 当前基线：分镜预览栏提供画面比例、分辨率（0.4 / 1.0 / 2.0 MP）和生成速度；写入 `aspectRatio` / `finalQuality` / `finalSpeed` / `canvasTier`。点「全部出片」或「生成这一镜」前先保存。后端仍按 Recipe 字段编译官方 H3。
- 受影响文件：`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/types.ts`、`frontend/src/director/prompt-compiler.contract.ts`、`frontend/src/index.css`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`pnpm --dir frontend build`；桌面 1440 与移动 390 检查分镜下拉与出片。
- 回滚方式：恢复上述文件并重新构建前端。

## 2026-08-27 导演台失败信息不撑破卡片

- 原因：任务 `error` 含 ComfyUI traceback 时，分镜卡片按原文渲染会撑破 `auto-fill` 网格。
- 当前基线：`summarizeJobError` 把 OOM / execution_error 收成短摘要；卡片只显示摘要，「查看详情」弹层展示完整日志。卡片 `min-width: 0`、`overflow-wrap: anywhere`。
- 受影响文件：`frontend/src/director/director-submit.ts`、`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/prompt-compiler.contract.ts`、`frontend/src/index.css`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`pnpm --dir frontend build`；桌面 1440 与移动 390 检查失败卡片。
- 回滚方式：恢复上述文件并重新构建前端。

## 2026-08-27 导演台 Recipe/批量移动端出口与中文状态

- 原因：手机上 `director-topbar` 被隐藏后，Recipe/批量没有返回工程库的头栏和主按钮；批量卡片直接显示英文 `status`；首页工程卡主体是不可聚焦的 `div`。
- 当前基线：Recipe/批量在 ≤767px 显示与首页同结构的移动端头栏（返回工程库、标题、溢出菜单）和 44px 高底部主按钮。Recipe 主按钮随 Tab 变化（故事/画风=运行流水线，定妆=全部定妆，分镜=全部出片）。镜头/批量条目使用中文状态（排队中/生成中/已完成/失败/已中断/已停止）；失败显示错误摘要和「重试这一项」。分镜区另有「仅重试失败项」。首页工程卡主体为可聚焦 button，Enter/Space 打开。`POST /api/director/batches/{project_id}/render` 按 `item_ids` 重提交批量条目。
- 受影响文件：导演台前端 Recipe/Batch/Home、`status-labels.ts`、`index.css`、`director_jobs.py`、`director_recipe.py`、`main.py`、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs` 外部字段。桌面顶栏仍在 ≥768px 显示。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorDualEngineApiTests.test_batch_render_retries_only_requested_item`、`pnpm --dir frontend build`；1440×900 与 390×844 检查返回、底部主按钮、中文状态与键盘打开工程。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 分镜出片先等切换工作流

- 原因：加载器节点的 `progress_state` 会被当成出片百分比，分镜卡在 UNET 仍在加载时显示「出片中 75%」。
- 当前基线：提交 H3 graph 后 `stage` 先为「正在切换工作流」。`interpret_comfy_progress` 按节点 `class_type` 区分加载器 / 采样器 / 导出。分镜卡显示 `jobs.stage`，准备阶段不再把进度抬到 8% 并写成「出片中」。
- 受影响文件：`backend/app/comfy_service.py`、`frontend/src/director/director-submit.ts`、`frontend/src/director/prompt-compiler.contract.ts`、`backend/tests/test_core.py`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_core.WorkerTests.test_comfy_loader_progress_waits_for_workflow_switch`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 分镜生成可选择工作流

- 原因：分镜出片原先锁死官方 MiniMax H3，无法像生成页那样改用 LightX2V、八步双加速或 T8。
- 当前基线：Recipe / 时间轴 / 批量 payload 保存 `videoWorkflowFamily`（`catalog_group` 或独立工作流 id）。`resolve_director_workflow` 是提交权威；T2V/I2V/R2V 仍按镜头参考图自动路由。缺省 `official_h3`。分镜栏与批量表单用 Ant Design Select，选项来自 `/api/modes`。
- 受影响文件：`backend/app/workflow_registry.py`、`director_compiler.py`、`director_jobs.py`、`director_recipe.py`、`models.py`、`main.py`、导演台前端、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs` 外部字段。旧工程未写该字段时仍走官方 H3。
- 验证命令：`python -m unittest backend.tests.test_core.WorkflowTests.test_resolve_director_workflow_uses_family_then_route backend.tests.test_director.DirectorCompilerTests.test_workflow_family_routes_lightx2v_and_dual_accel backend.tests.test_director.DirectorDualEngineApiTests.test_batches_enqueue_selected_workflow_family`、`pnpm --dir frontend build`；桌面 1440 与移动 390 检查分镜下拉。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演分镜按 MiniMax H3 官方 skill 生成

- 原因：自动分镜原先用通用影视枚举和中文机位前缀，提交给 H3 的提示词不符合官方 `h3-prompt-writing`，成片质量不稳定。
- 当前基线：分镜 Agent 同时写中文 `description`（卡片展示）和英文 `promptText`（提交 H3）。编译器把 T2V/I2V 写成 `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`，I2V 带官方首帧/首尾帧对齐句；R2V 写成 Ref2VA 六段式。卡片上的景别/运镜枚举仍可手改。
- 受影响文件：`backend/app/llm_minimax_skills.py`、`director_agents.py`、`director_compiler.py`、`llm_client.py`、导演台 `prompt-compiler.ts` / `types.ts`、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。旧工程手改中文描述仍可出片，编译时补上官方字段与英文运镜句。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorCompilerTests backend.tests.test_director.DirectorAgentPipelineTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演分镜对用户显示中文、提交仍用英文

- 原因：官方 skill 英文镜头正文被直接画在分镜卡上，用户读起来不像分镜脚本。
- 当前基线：卡片展示 `description`（中文）；出片编译优先 `promptText`（英文 H3）。人物/场景卡展示中文 `description`，定妆仍走英文 `promptText`。批量卡展示中文 `description`，提交仍走 `script`。
- 受影响文件：`director_agents.py`、`director_recipe.py`、`director_compiler.py`、`main.py`、导演台 Recipe/批量卡片、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。无 `promptText` 的旧分镜仍用 `description` 编译。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorAgentPipelineTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演分镜直接使用官方 h3-prompt-writing 原文

- 原因：原先把官方 skill 缩成中文摘要再喂给大模型，少了官方示例和完整运镜/对白规范，模型不如直接读 skill 稳。
- 当前基线：`backend/app/h3_prompt_writing/` 保存 MiniMax 官方 SKILL.md、`base-en.txt`、`ref-en.txt`。分镜/拆剧本/批量裂变和生成页优化把官方原文放进 system prompt；导演台另附短 adapter，卡片仍用中文 `description`，出片仍用英文 `promptText`。多参考优化额外附上 `ref-en.txt`。
- 受影响文件：`backend/app/h3_prompt_writing/`、`llm_minimax_skills.py`、`director_agents.py`、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。JSON 字段不变。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorRecipeModelTests.test_official_h3_prompt_writing_skill_is_vendored backend.tests.test_director.DirectorAgentPipelineTests.test_storyboard_agent_follows_h3_official_skill backend.tests.test_llm.LLMProviderTests.test_optimize_prompt_video`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-27 Recipe 分镜 Inspector、预览默认与画风渐进披露

- 原因：分镜还是卡片墙，改不了机位/对白/时长；出片写死终稿；画风一次摊开 34 张；保存没有状态。
- 当前基线：分镜 Tab 桌面为左镜头列表 + 右 Inspector，手机为横向镜头条 + Drawer。可编辑标题、描述/提示词、对白、时长（2–15 秒吸附）、角色、场景、景别/运镜/机位/布光；参考图只读展示本镜将装箱的定妆。`_normalize_shot` 始终保留 `camera`（缺省中景前推）和 `error`。出片默认预览档，顶栏与分镜区可切预览/终稿；Take 标记 `renderPass`。标题旁显示保存中/已保存/保存失败（约 800ms 防抖 PUT，一句话创意同步落盘）。画风默认 6 张推荐，其余进「浏览全部」。9 Agent 收进折叠的「AI 运行详情」。不改端口、节点或 `POST /api/jobs`。成片交付仍是串播 + 剪映。
- 受影响文件：`director_recipe.py`、`director_compiler.py`、`director_jobs.py`、`backend/tests/test_director.py`、`DirectorRecipeStudio.tsx`、`RecipeShotInspector.tsx`、`ShotCameraFields.tsx`、`types.ts`、`index.css`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：旧分镜无 `camera` 时补默认机位；已有 camera 转换后不丢。API 默认 `render_pass` 仍为 `final`，界面默认发 `preview`。
- 验证命令：`python -m unittest backend.tests.test_director`（49 项通过，含 `_normalize_shot` 补默认 camera、已有 camera 转换不丢、`render_pass=preview` 入队 0.4 MP / fast）、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后 1440×900 与 390×844：返回工程库、运行导演流水线、生成这一镜 / 全部预览、标题旁保存中/已保存、画风默认 6 卡、工程卡可聚焦打开；手机头栏 44×44、底栏主按钮、分镜 Drawer。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 Recipe 首尾帧承接、静帧分镜与 Take A/B

- 原因：Recipe 规范化丢掉首尾帧，出片无法走 I2V 承接；分镜没有静帧预览和 Take 对比，失败项只能逐个点。
- 当前基线：`RecipeShot` 保留 `firstFrameUrl`/`endFrameUrl`/`usePreviousEndFrame`/`stillUrl`/`takes`/`approvedTakeId`。打开旧时间轴时保留首尾帧与承接开关。编译时勾选「用上一镜尾帧」把上一镜尾帧（或静帧）接到本镜首帧，提交走已有 I2V/R2V。分镜可先走 GRS 静帧（与定妆同一图片通道），再设为首帧出视频。工作面区分静帧 / 视频预览 / 终稿。每次视频渲染写入 `takes[]`，Inspector 可切换、批准，桌面支持 A/B 并排。镜头列表可多选：生成选中、仅重试失败、取消选中（`POST /api/jobs/{id}/cancel`）。不改端口、节点或 `POST /api/jobs` 契约。成片交付仍是串播 + 剪映。
- 受影响文件：`director_recipe.py`、`director_compiler.py`、`director_jobs.py`、`main.py`、`models.py`、`backend/tests/test_director.py`、导演台 Recipe 工作面、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：旧分镜无连续性字段时视为未勾选、无静帧；已有 camera/takes 不丢。新增静帧与帧上传接口，旧客户端可忽略。
- 验证命令：`python -m unittest backend.tests.test_director`（56 项通过，含首尾帧规范化、上一镜尾帧/静帧承接编译为 I2V、静帧任务回写）、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后 1440×900 与 390×844：分镜可切静帧/预览/终稿、勾选上一镜承接、Take 切换与批准、多选生成/取消。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 员工级人物/场景/道具资产库

- 原因：定妆只存在单个 Recipe 工程里，跨工程无法复用人物、场景和道具；计划明确不做系列分集树。
- 当前基线：SQLite 表 `director_library_assets` 按员工隔离，保存 kind（character/scene/prop）、名称、说明、提示词和参考图。`GET/POST /api/director/library-assets` 管理库；`POST .../from-recipe` 把当前工程人物/场景/道具快照写入库（道具对应 Recipe `type=object`）；`POST .../insert-library-assets` 复制进工程并写 `libraryAssetId`。创作台 `/assets` 的「主体」Tab 管理库；Recipe 定妆区可「从库插入」「存入资产库」。继续用工程 + `scenes[].shots[]`，不建系列/分集。出片时库内上传图可作为定妆参考。不改端口、节点或 `POST /api/jobs`。
- 受影响文件：`director_library.py`、`storage.py`、`main.py`、`models.py`、`director_recipe.py`、`director_jobs.py`、`director_compiler.py`、导演台前端、`App.tsx`、测试与三份主文档。
- 兼容性：旧工程无 `libraryAssetId` 时行为不变。新增表与接口，旧客户端可忽略。
- 验证命令：`python -m unittest backend.tests.test_director`（含资产库 CRUD、员工隔离、from-recipe 道具映射、插入 Recipe、库图作为定妆参考）、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后 1440×900 与 390×844：`/assets` 主体新建人物、Recipe 定妆从库插入、存入资产库。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；新表可保留，不影响旧工程。

## 2026-08-28 Recipe 资产别名解析与独立镜头时间基准

- 原因：9 Agent 顺序中 storyboard 早于 characters / locations；大模型可能把 `李明`、`公司办公室` 写成 `Li Ming`、`Tech company office`。原编译器只做完全相等匹配，匹配失败后又装入全部场景图，造成角色定妆缺失和无关场景污染。Storyboard 还可能把整片累计时间码写进逐镜提交的 `promptText`，例如 7 秒任务从 `00:11` 开始。
- 当前基线：`recipe_assets_as_slots()` 先做大小写/标点无关的精确匹配，再在历史工程全部未匹配项与剩余资产数量一一对应时按首次出现顺序建立只读别名；每镜只装入命中的人物与一个命中场景，显式名称未命中时不再任意回退场景。`normalize_independent_shot_prompt()` 只清理单镜正文开头的 `[Shot n]`、累计 `At HH:MM.mmm` 和紧随其后的 cut 连接语，正文内部的局部时间事件不动；编译器随后统一写 `[Shot 1]`。Director adapter 同时要求保留剧本专名原文并使用从 `00:00` 开始的局部时间线。
- 受影响文件：`backend/app/director_compiler.py`、`backend/app/llm_minimax_skills.py`、`backend/tests/test_director.py`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改端口、API、数据库、工作流 ID、ComfyUI graph 节点或参考图上限。旧 Recipe 无需写回迁移，下一次预览/终稿提交即按新编译规则运行；已生成的历史任务提示词与视频保持不变。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorCompilerTests backend.tests.test_director.DirectorAgentPipelineTests`、`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`；使用《代码与咖啡》快照复核五镜分别装箱正确人物与单一场景，且无 `00:06/11/18/24` 累计时间码。
- 回滚方式：恢复上述三个代码/测试文件并重启工作台；文档记录可随代码一起回退，SQLite 与媒体无需处理。

## 2026-08-28 导演台第三版：真实声音层与工作台内成片

- 原因：前两版成片交付仍是串播 + 剪映；配音/配乐 Agent 只写文案；仓库内没有 ffmpeg；架构写明不引入 Edge TTS。第三版是新产品线：可播放的 TTS/BGM/字幕、本机 ffmpeg 合成 MP4、FCPXML/EDL，剪映草稿并行保留。
- 当前基线：
  - TTS 走 OpenAI 兼容 `POST {base}/audio/speech`（独立 `tts_provider_settings`，可勾选复用 LLM 凭据）。不绑定 Edge TTS，不把 ComfyUI 暴露到新端口。
  - Recipe 保存角色 `voiceId`、逐镜 `speakerName`/`ttsStatus`/`ttsUrl`、工程级 `audio`（BGM 地址、音量、淡入淡出）与 `subtitles`（开关、位置、字号、描边）。Voice/Music Agent 输出这些可播放媒体元数据，不直接生成音频文件。
  - `POST /api/director/recipes/{id}/tts` 按对白调用上游 TTS，落盘 `data/uploads/{user}/{project}/tts/`。角色试听写入 `voicePreviewUrl`。
  - `POST /api/director/recipes/{id}/bgm` 上传配乐。串播预览叠字幕样式；成片可选烧字幕。
  - `POST /api/director/recipes/{id}/mux` 用本机 `ffmpeg`/`ffprobe` 按镜头顺序 concat 已批准（或成功）视频，混 TTS 与 BGM。失败、中断、停止镜头不进入成片。成片写入 `data/staging/director-mux/`，`export.muxDurationSec` 来自 ffprobe。未安装 ffmpeg 时返回 503。
  - `GET .../export.fcpxml` 与 `GET .../export.edl` 由镜头入出点、对白、音频轨生成。剪映草稿与串播保留为并行导出。
  - 不改 ComfyUI 节点 ID、工作台 `7865`、ComfyUI `8188` 或 `POST /api/jobs` 外部字段。
- 依赖：本机 PATH 或常见安装路径中的 `ffmpeg` 与 `ffprobe`。Docker/服务器镜像不内置 ffmpeg 时，mux 接口会明确提示。
- 受影响文件：`tts_provider.py`、`director_export.py`、`director_recipe.py`、`director_agents.py`、`llm_client.py`、`storage.py`、`models.py`、`main.py`、`api_documentation.py`、导演台前端、管理后台 LLM 页、测试与三份主文档。
- 兼容性：旧 Recipe 无音频字段时视为未配 TTS/BGM、字幕默认关闭。新增 TTS 表与接口，旧客户端可忽略。剪映导出不变。
- 验证命令：`python -m unittest backend.tests.test_director`（含 TTS 任务状态、mux 输出时长、FCPXML 镜头数）、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后走导演台「导出成片」。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；新表可保留。成片文件可删 `data/staging/director-mux/`。

## 2026-08-28 点击分镜按剧本一次生成全部镜头

- 原因：分镜 Tab 不触发生成；Agent 在 JSON 失败或官方 skill 顶层格式冲突时回退成单条「主镜头」，用户看不到按剧本拆出的镜头列表。
- 当前基线：分镜 Agent 以 JSON 合约为优先输出，官方 `h3-prompt-writing` 只约束每镜 `promptText`。一次覆盖完整剧本，通常 8–24 个独立镜头，上限 32。截断 JSON 会补全括号；模型若只吐 `[Shot n]` 散文也会拆成镜头。空结果或「主镜头」占位则标 failed，不写假镜头。`script`+`storyboard` 子集中脚本失败仍继续拆镜。`POST /api/director/recipes/run` 可选 `agents`；前端点「分镜」时先落盘再跑，生成中不会用旧稿覆盖镜头。
- 受影响文件：`director_agents.py`、`llm_minimax_skills.py`、`models.py`、`main.py`、`api_documentation.py`、导演台 Recipe 工作面、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。不传 `agents` 仍跑完整 9 步。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorAgentPipelineTests backend.tests.test_director.DirectorDualEngineApiTests.test_recipes_run_accepts_script_and_storyboard_subset`、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后点「分镜」，应列出按剧本拆出的多条镜头。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 大模型余额不足返回上游错误日志

- 原因：上游 LLM 欠费/余额不足时，分镜生成把错误吞成空列表，用户看不到供应商原文。
- 当前基线：`LlmBillingError` 识别 402 与余额/quota/欠费文案（含 HTTP 429 额度耗尽）。错误信息包含 HTTP 状态和上游返回正文。导演 `POST /api/director/recipes/run` 对此返回 502；分镜页展示摘要，详情可查看上游日志。余额不足不再重试、不再继续拆镜。
- 受影响文件：`llm_client.py`、`director_agents.py`、导演台 Recipe 工作面、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_llm.LlmBillingErrorTests backend.tests.test_director.DirectorAgentPipelineTests.test_pipeline_raises_billing_error_with_upstream_log`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 分镜生成展示阶段与镜头占位，不展示思考原文

- 原因：分镜等待只有空状态；子集运行仍按 9 步显示「脚本 7/9」；主画布流式打模型原文不符合短剧生产台。
- 当前基线：`payload.pipelineRun` 记录本次 `agents`。`agentStatus[].message` 为人话阶段（读剧本 / 整理镜头 / 已写出 N 个镜头），思考模式保持关闭，不把 token 推到前端。前端进度按本次步骤计数；分镜 Tab 生成中显示占位镜头卡。「AI 运行详情」折叠展示阶段与最近一次分镜摘要。
- 受影响文件：`director_recipe.py`、`director_agents.py`、`llm_provider.py`、`main.py`、导演台 Recipe 工作面、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。旧 payload 缺字段时行为与原先一致。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorRecipeModelTests.test_normalize_keeps_agent_stage_and_pipeline_run backend.tests.test_director.DirectorAgentPipelineTests.test_pipeline_subset_tracks_active_run_and_stage_messages`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 视频工作流可切换精简 UNET

- 原因：32 GB 内存加载全量 MiniMax H3 INT8 UNET（约 32 GB）时 Windows 报 1455。原先只有高质量/自定义超过 8 步才会改走 pruned。
- 当前基线：所有 H3 视频工作流（官方、LightX2V、八步双加速、T8）增加 primary `weight_profile`：`full`（默认）或 `pruned`。`pruned` 关闭加速 LoRA 并加载精简 UNET，不改变所选步数。创建栏与导演台分镜栏直接显示，不放进「更多设置」。导演 Recipe / 批量 payload 增加 `weightProfile`，提交任务时写入 `options.weight_profile`。T8 文生也按 `lora_strength` 选择 FL2VA pruned/full，不再在高质量时误用全量 `unet_name`。
- 受影响文件：`workflow_registry.py`、`minimax_h3_t8_workflow.py`、导演编译/入队/Recipe、导演台界面、测试与三份主文档。
- 兼容性：不改节点 ID、端口。缺省 `weight_profile` 仍为完整权重。
- 验证命令：`python -m unittest backend.tests.test_core.WorkflowTests.test_weight_profile_pruned_keeps_steps_and_skips_turbo_lora backend.tests.test_director.DirectorCompilerTests.test_canvas_quality_maps_to_registry`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 导演台 H3 最终提示词润色分层

- 原因：`Recipe` 的分镜 Agent 必须输出可编辑的独立 `promptText`，而实际首帧、尾帧和角色/场景定妆的上传顺序只有在提交前的参考图装箱阶段才确定；因此不能由早期 Agent 固化最终的 H3 参考标签。
- 当前基线：`director_compiler.h3_prompt_mode()` 根据提交计划选择官方 H3 写作模式：T2VA、I2VA、FL2VA、L2VA 或 Ref2VA。`LlmProviderService.polish_director_h3_prompt()` 在图像装箱完成后读取内置官方 `h3-prompt-writing` 的对应 guide，以最终 draft 和真实标签调用配置的大模型。对 Ref2VA，编译器只验证六段格式、标签编号和 `<Subject N>` 在定义/摘要/保留分析/正文中的存在性；不进行角色名到标签的机械替换。对基础模式，校验三核心字段及必要的图像对齐首行。润色结果通过才入队；无可用 LLM 时，直接沿用既有编译产物。
- 受影响文件：`llm_minimax_skills.py`、`llm_provider.py`、`director_compiler.py`、`director_jobs.py`、`main.py`、`director_agents.py`、`director_recipe.py`、前端导演编译器与类型、测试及主文档。
- 兼容性：不改 ComfyUI graph、节点 ID、工作流模式 API、端口或数据库迁移。原有的 T2V/I2V/R2V 产品路由仍由 `workflow_registry.py` 决定；H3 写作模式仅描述最终提示词的参考关系。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复本节列出的文件、重新构建前端并重启服务；历史任务的提示词快照和媒体文件无需迁移或清理。

## 2026-08-28 分镜读剧本不再因 180 秒整段超时失败

- 原因：分镜 Agent 一次要生成全部镜头 JSON（最多 8192 token）。旧客户端用非流式 POST、整段 180 秒超时；模型还在写就会报「等待 180 秒仍无响应」，超时还会再打一遍同样的请求。
- 当前基线：导演对话与 H3 最终润色改为 SSE 流式读取，按 UTF-8 解码（避免 `text/event-stream` 默认 Latin-1 把中文解成乱码）。连接超时 20 秒；读超时是分块空闲 300 秒。分镜生成中 `agentStatus.message` 会更新为「正在写分镜（已收到 N 字）」。读取已保存的 Recipe 时会尝试修复这类乱码；对话字段会去掉误写入的 `<d>` 标签。
- 受影响文件：`llm_client.py`、`director_agents.py`、`llm_provider.py`、`api_documentation.py`、测试与三份主文档。
- 兼容性：不改节点、端口、`POST /api/jobs` 或数据库。短对话（连接测试、提示词优化）仍为非流式。
- 验证命令：`python -m unittest backend.tests.test_llm.ChatCompletionTimeoutAndStreamTests backend.tests.test_director.DirectorAgentPipelineTests.test_chat_text_does_not_retry_timeout backend.tests.test_director.DirectorAgentPipelineTests.test_chat_text_retries_connection_error`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 生成这一镜在润色提示词期间立即显示提交中

- 原因：`POST .../render-shots` 会先调用大模型润色最终 H3 提示词，接口可能几十秒到几分钟才返回；按钮 loading 只看已有 `jobId`，点击后页面看起来完全没反应。
- 当前基线：点击后立即显示「正在润色提示词并提交…」，并轮询工程。润色开始前把该镜标为 `queued` 并落盘。找不到指定镜头时返回 422，不再空成功。
- 受影响文件：`director_jobs.py`、`main.py`、导演台 Recipe 工作面、测试与三份主文档。
- 兼容性：不改节点、端口、`POST /api/jobs`。无 LLM 时仍直接入队。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorDualEngineApiTests.test_recipes_run_and_render_shots_enqueue_t2v`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-30 导演台方案/剪辑双视图 URL

- 原因：一份 `director_recipe` 要同时服务方案任务区和桌面剪辑台，视图状态必须写在 URL，且手机不能进入剪辑台。
- 当前基线：`/director/:projectId?view=plan|timeline`，默认 `plan`。桌面顶栏 `Segmented`「方案 | 剪辑」写入查询参数；切到剪辑时带上 `stage=shots`。左栏「镜头生成」在桌面进入剪辑视图。「分镜设计」仍留在方案视图。`?stage=` 仍只表示方案视图当前任务。手机 `useIsMobile` 把视图锁定为方案，并把 `view=timeline` 从地址栏替换掉。不新增 payload kind 或后端字段。
- 受影响文件：`frontend/src/director/types.ts`、`DirectorRecipeStudio.tsx`、`director-recipe-view.contract.ts`、`frontend/src/index.css`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：旧工程无损打开；无 `?view=` 时仍是方案视图。路由仍是 `/director/:projectId`。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后导演工程桌面 1440：顶栏切换、`?view=` / `?stage=` 刷新恢复；手机 390×844：无剪辑开关、时间轴不出现。
- 回滚方式：恢复上述前端与文档并重新构建前端。

## 2026-08-30 导演台生成创作方案与重资源动作语义

- 原因：用户把 9 Agent 流水线当成一键出片；`agentStatus=completed` 对 voice/music/media 也不等于拿到音频或成片。
- 当前基线：顶栏主操作为「生成创作方案」，只跑 LLM 写出剧本/画风/分镜/人物场景/声音方案，不提交 GRS、H3、TTS 或 mux。各任务区保留「全部定妆 / 全部出片 / 生成全部配音 / 导出成片」，按钮显示数量，提交前 `Modal.confirm` 写明 N 个定妆、N 镜和预计消耗。单镜、单角色、试听不确认。手机 `DirectorMobileBottomBar` 仍按当前 `?stage=` 切换主按钮，不做九步横条。`AGENT_DONE_MESSAGES` 改为不撒谎（如 voice：「配音方案已写好，音频待生成」）。`AGENT_IDS`、`agentStatus` 结构和所有 API 不变。
- 受影响文件：`backend/app/director_recipe.py`、`backend/tests/test_director.py`、`frontend/src/director/action-copy.ts`、`action-copy.contract.ts`、`DirectorRecipeStudio.tsx`、`components/DirectorExportPanel.tsx`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：旧工程零迁移。历史 `agentStatus.message` 原样保留，重新跑对应 Agent 后换成新文案。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后导演工程桌面 1440 与手机 390×844：生成创作方案提示、四组导航、重资源确认、`?stage=` 刷新/后退。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-30 导演台方案视图任务导航与 readiness 派生

- 原因：方案视图把 9 Agent 执行日志和用户任务（剧本/定妆/出片/成片）混在同一层级，`agentStatus=completed` 不等于用户拿得到产物。
- 当前基线：`recipeReadiness(recipe)` 纯前端从 payload 现有字段派生 `empty | draft | partial | ready`（`script.fullStory`、`artStyle`、非占位分镜、定妆 `imageUrl`、`shotIsMuxable`、对白 `ttsStatus`、`audio.bgmUrl`/`globalMusic`、`export.muxStatus`），不新增后端字段、不迁移数据。左栏改为四组折叠导航（方案 / 镜头制作 / 声音 / 交付），右侧只渲染当前任务；`?stage=` 写入当前任务，路由仍是 `/director/:projectId`。9 Agent（含 `research`/`media`）只出现在「AI 运行详情」。人物/场景拆成两个工作区；分镜拆成「分镜设计」和「镜头生成」入口（桌面「镜头生成」进入剪辑视图）。
- 受影响文件：`frontend/src/director/types.ts`、`DirectorRecipeStudio.tsx`、`components/DirectorStageNav.tsx`、`components/DirectorExportPanel.tsx`、`recipe-readiness.contract.ts`、`frontend/src/index.css`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 API、`agentStatus` 结构或旧 Recipe；无 `?stage=` 时默认剧本任务。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后导演工程桌面 1440 与手机 390×844：四组导航、`?stage=` 刷新/后退、AI 运行详情仍含 9 Agent。
- 回滚方式：恢复上述前端与文档并重新构建前端。

## 2026-08-30 导演台剪辑视图时间轴

- 原因：方案视图能写剧本和定妆，但不能按时间轴选镜、装箱、串播已生成 Takes。剪辑台必须读写同一份 `director_recipe`，不能另起一套引擎。
- 当前基线：桌面 `?view=timeline` 渲染 `DirectorTimelineView`：左栏已定妆角色/场景一点加入本镜 `characterNames`/`locationName`（装箱仍走 `recipePackedPlates`，超过 9 张拒绝）；中上预览当前镜 Take/静帧，串播用 `recipePlayableShots` 把 playhead 扫过已生成镜头；中下 `TimelineRuler` + `TimelineTrackMain` 直接吃 `RecipeShot[]`（`recipeTrackLayout` / `recipeRulerTicks` 按 `durationSec` 铺开），中文状态、拖选、右键复制/删除，时长拖动仍 `snapH3DurationSec`（2–15 秒）；右侧直接复用 `RecipeShotInspector`。出片/静帧/TTS/mux 仍走现有接口。手机继续锁定方案视图。
- 受影响文件：`frontend/src/director/types.ts`、`DirectorRecipeStudio.tsx`、`components/DirectorTimelineView.tsx`、`TimelineTrackMain.tsx`、`TimelineRuler.tsx`、`director-timeline.contract.ts`、`frontend/src/index.css`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 API、`agentStatus`、payload kind 或旧 Recipe。无 `?view=` 仍是方案视图；旧工程无损打开。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后导演工程桌面 1440：`?view=timeline` 刷新恢复、轨道点选/拖选、素材加入本镜、串播扫 playhead、Inspector 生成这一镜；手机 390×844 无剪辑台。
- 回滚方式：恢复上述前端与文档并重新构建前端。

## 2026-08-30 剪辑轨适配 RecipeShot

- 原因：镜头轨仍按旧 `DirectorShot` 排版，剪辑视图要先 `recipeShotsToPlayer` 转一层，角色/场景和首尾帧对不上 Recipe 字段。
- 当前基线：`TimelineTrackMain` / `TimelineRuler` 直接读写 `RecipeShot[]`。轨道用 `recipeTrackLayout` 按 `durationSec` 铺开，拖选返回镜头 id，状态/角色场景/首尾帧读本镜字段（`stillUrl` 算首帧已设）。刻度用 `recipeRulerTicks`，镜头边界用 `recipeRulerShotEdges`，点击吸附 `recipeRulerSeekSec`。`recipeShotsToPlayer` 只留给串播/预览弹层。不新增 payload kind 或后端字段。
- 受影响文件：`frontend/src/director/types.ts`、`TimelineTrackMain.tsx`、`TimelineRuler.tsx`、`DirectorTimelineView.tsx`、`director-timeline.contract.ts`、`frontend/src/index.css`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 API、`agentStatus`、payload kind 或旧 Recipe。旧时间轴 payload 不复活。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后导演工程桌面 1440：`?view=timeline` 轨道按时长铺开、点选/拖选、右键复制删除、刻度与 playhead；手机 390×844 无剪辑台。
- 回滚方式：恢复上述前端与文档并重新构建前端。

## 2026-08-30 导演台双模式二期验证

- 原因：方案任务导航与桌面剪辑时间轴已落地，需要按 AGENTS.md 把二期基线写入三份主文档，并完成测试构建与桌面/移动回归。
- 当前基线：一份 `director_recipe` payload、两套视图。方案视图左栏四组任务（方案 / 镜头制作 / 声音 / 交付），右侧只渲染当前任务，`?stage=` 刷新/后退保持位置；任务徽标由前端 `recipeReadiness()` 从现有产物字段派生，不看 `agentStatus`。桌面顶栏 `Segmented`「方案 | 剪辑」写入 `?view=plan|timeline`（默认方案）；剪辑视图是素材栏 + 预览/串播 + `TimelineRuler`/`TimelineTrackMain` + `RecipeShotInspector`，直接读写同一 Recipe。出片/静帧/TTS/mux 仍走现有接口。手机锁定方案视图（镜头横条 + 抽屉），`view=timeline` 会被清掉。9 Agent 只在折叠的「AI 运行详情」。不新增 payload kind、后端字段或九步向导。
- 受影响文件：`frontend/src/director/types.ts`、`DirectorRecipeStudio.tsx`、`director-recipe-view.contract.ts`、`director-timeline.contract.ts`、`recipe-readiness.contract.ts`、`components/DirectorStageNav.tsx`、`DirectorTimelineView.tsx`、`TimelineTrackMain.tsx`、`TimelineRuler.tsx`、`RecipeShotInspector.tsx`、`frontend/src/index.css`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改 API、`AGENT_IDS`、`agentStatus` 结构、SQLite schema 或旧 Recipe。带旧 `agentStatus` 的工程无损打开；无 `?view=` 仍是方案视图，无 `?stage=` 默认剧本。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后导演工程：桌面 1440 检查四组导航、`?stage=`/`?view=` 刷新恢复、剪辑轨道点选与 Inspector；手机 390×844 只保留方案视图。
- 回滚方式：恢复上述前端与文档并重新构建前端；无需回滚数据库或媒体。
