# ZLY AI Video Studio 架构快照

## 2026-11-10：新增 RelayVSR 细节超分引擎（2x，社区节点）

- 变更原因：希望给「视频超清」补一个介于 RTX（秒级、纯放大）与 SeedVR2（生成式、分钟级）之间的细节重建引擎。先在远端只读探测：`192.168.10.54:8188` 已装 bbaudio 的 Comfyui-Relay-VSR（`RelayVSRModelLoader` / `RelayVSRUpscale` / `RelayVSRUpscaleStreaming`）且 `RelayVSR_X2` 权重就位；`RelayVSR_X4` 与 FL-RelayVSR（要求 Python 3.11+，远端为 3.10.11）不可用。
- 实测边界（RTX 4080 16 GB，2026-11-10）：864×486 / 121 帧整段超分成功，约 75 秒出 1728×972；64×64 / 1 帧 16 秒成功；1920×1080 / 224 帧在 `RelayVSRUpscale` 处 OOM（帧张量约占 26 GB），`RelayVSRUpscaleStreaming` 同样 OOM。因此接入时必须做提交前显存预检，不能把 1080p 长片直接送进节点。
- 当前基线：
  - 新引擎 `relayvsr`：`JobMode.RELAYVSR_UPSCALE = "relayvsr-upscale"`，工作流注册表新增 `RELAYVSR_UPSCALE_WORKFLOW_IDS` 并已并入 `UPSCALE_WORKFLOW_IDS`，`hidden_from_catalog=True`（只出现在超分入口，不进创作页模型列表）。`UpscaleJobRequest.engine` 增 `"relayvsr"`，`UPSCALE_ENGINES` 增「RelayVSR 细节超分」。
  - Graph（`backend/app/relay_vsr_workflow.py`）：`LoadVideo → GetVideoComponents → RelayVSRModelLoader(RelayVSR_X2 / bf16 / offload=true) → RelayVSRUpscale(sr_ratio=2, chunk_len=16, seed=0) → CreateVideo(images, audio, fps) → SaveVideo`。刻意不用 `RelayVSRUpscaleStreaming`：流式节点只输出无声视频文件，整段路径才能把原音轨交回 `CreateVideo`。节点编号 50–55，避开 H3(14)、RTX VSR(20–24)、SeedVR2(30–44)。
  - 预检：`relay_vsr_memory_rejection(width, height, frames)` 按 `frames × pixels × (1 + sr_ratio²) × 3 × 4` 估算显存，额度为 `vram_total − 2 GB`；`comfy_service.reject_relay_vsr_memory()` 与 `/api/jobs/{id}/upscale` 都会先拦截（422），`append_upscale_if_requested` 自动接跑时则跳过并提示。读不到显存时不设限（与 RTX VSR 一致）。
  - 能力探测：`ComfyService.require_relay_vsr()` 校验两个节点存在且 `RelayVSRModelLoader.bundle` 含 `RelayVSR_X2`，失败信息给出安装路径与 Python 版本要求；`/api/upscale/capabilities` 返回三引擎及各自 `reason`。
  - 前端：`UPSCALE_ENGINE_RELAYVSR = "relayvsr-upscale"`；超分工具三选一（RTX / RelayVSR / SeedVR2），版本标签「2× 细节超分」，`/tools/video-upscale?job=` 恢复时按 `round.mode` 回填引擎；悬浮工具条的「视频超清」入口把新引擎计入可用性判定。
- 受影响文件：新增 `backend/app/relay_vsr_workflow.py`、`backend/tests/test_relay_vsr.py`；`backend/app/{models,workflow_registry,seedvr2_upscale_workflow,comfy_service,main}.py`、`backend/tests/test_rtx_vsr.py`；`frontend/src/{generation/upscale.ts,video-upscale.ts,media/media-actions.ts,tools/VideoUpscaleTool.tsx}` 及对应测试。
- 兼容性：纯新增引擎，RTX / SeedVR2 的 graph、端点语义与历史任务不受影响；未装节点或 2x 权重时该引擎在能力接口里为 `available=false` 并带原因，其余引擎照常。输出标签新增「2x 细节超分」，旧标签判定保留。
- 验证命令：`python -X utf8 -B -m unittest backend.tests.test_relay_vsr backend.tests.test_rtx_vsr`；远端实测脚本见 `tmp/relayvsr-sample/`（验证后清理）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend exec vitest run src/video-upscale.test.ts src/tools/video-upscale-tool.test.tsx src/media`。
- 回滚方式：删除 `relay_vsr_workflow.py`、注册表与枚举中的 relay 分支、前端三处引擎常量与选项即可；无数据库与任务链路迁移，已生成的「2x 细节超分」输出保留为普通视频。

## 2026-11-10：修复超分上传入口（工具页三引擎恢复可用）

- 变更原因：`AI 工具 → 视频超分` 提交的是 `POST /api/jobs`（multipart，1 条原片视频），但 `submit_generation` 仍保留“只要 `is_upscale_workflow(mode)` 就 422”的旧拦截，导致工具页三个引擎都无法提交；而 `/api/jobs/{id}/upscale` 只能接主任务库的成片，导演台镜头任务在 `ai_project_jobs`（`job-xxxxxxxx`）里，查主库是 404，所以无法用导演台镜头做 RelayVSR 验证。
- 当前基线：
  - `main.submit_generation`：超分工作流仅在“参考素材不是恰好 1 条”时返回 422；有 1 条原片时继续走通用创建链路（`references[0]` 即超分源），与 `POST /api/jobs/{id}/upscale` 成片接跑并存。
  - `main._prepare_uploaded_upscale(mode, options, source_path)`：上传落盘后先 `probe_video` 读宽高/帧率/时长，写入 `options.width/height/frames`，再调用 `reject_relay_vsr_memory` / `reject_vsr_memory` 与 `require_relay_vsr` / `require_seedvr2` / `require_rtx_vsr_node`；不满足直接 422 并带中文原因。
  - `workflow_registry`：三个超分定义补 `reference_slots=("video",)`；`main.public_reference` 对声明了 `reference_slots` 的工作流不再早退，任务详情里的原片显示 `kind=video`、`label=原片`。
- 受影响文件：`backend/app/main.py`、`backend/app/workflow_registry.py`、`backend/tests/test_relay_vsr.py`。
- 兼容性：成片接跑端点、RTX/SeedVR2 graph、历史任务与数据库结构不变；无原片的超分创建仍 422。
- 验证命令：`python -X utf8 -B -m unittest backend.tests.test_relay_vsr backend.tests.test_rtx_vsr`（29 项通过）；实测导演台镜头（864×480、294 帧、12.25s）经上传入口提交 RelayVSR，208 秒出 1728×960、保留原音轨。
- 回滚方式：恢复 `submit_generation` 的无条件 422、删除 `_prepare_uploaded_upscale` 与三处 `reference_slots`、还原 `public_reference` 早退条件；已生成任务与产物保留。

## 2026-11-07：修复音乐「测试连接」响应模型漏字段（把成功误报成「未知原因」）

- 变更原因：`/api/admin/providers/music/test` 声明 `response_model=MusicProviderResponse`，而该模型缺 `available` / `unavailable_reason`，FastAPI 会按模型裁剪响应体；前端 `MusicProviderSettings.tsx` 依赖 `data.available` 判定成败，拿不到就永远走 `else`，弹「连接失败：未知原因」。线上工作台因此把探活成功误报为失败，用户误以为 FRP/地址配错。
- 当前基线：`MusicProviderResponse`（`backend/app/models.py`）新增 `available: bool = False` 与 `unavailable_reason: str | None = None`，与 `TtsProviderResponse` 对齐；`MusicJobService.test()` 原本就返回这两个字段（并写回 `last_test_*`），现在能原样透出。前端逻辑不变。
- 受影响文件：`backend/app/models.py`、`backend/tests/test_music_provider.py`（新增 `test_test_endpoint_reports_available_flag`）。
- 兼容性：仅新增两个带默认值的响应字段；不改路由、请求体、数据库、任务队列与既有字段语义。`GET/PUT /api/admin/providers/music` 新增字段默认 `available=false`，前端配置回显不读取它。
- 验证命令：`python -m unittest backend.tests.test_music_provider`（28 项通过）；本地与线上各实测一次 `测试连接`，响应含 `available` 且成功时为 `true`。
- 回滚方式：移除模型中的两个字段与新增测试；本地重启后端、线上重新部署镜像生效。

## 2026-11-07：新增 Gitea CI/CD 部署基线（构建 → 镜像仓库 → SSH 部署/回滚）

- 原因：替代人工 tar 上传部署，建立可复用到其他项目的持续集成基线；目标服务器可出网，走 Gitea 自带镜像仓库而非每次打包 GB 级 tar。
- 设计要点：`.gitea/workflows/deploy.yml` 在 push master / `v*` 标签 / 手动触发时运行；job 使用 `container: docker:27-cli` 并挂载宿主机 `/var/run/docker.sock`（runner 配置 `valid_volumes` 白名单放行）直接 `docker build/push`，零第三方 action（仅 apk/git/ssh），兼容国内网络。镜像 tag `<sha8>` + `latest` 推到 Gitea Registry（`124.70.90.30:3080/<org>/zly-ai-video-studio`）。部署侧 `ops/deploy/deploy.sh` 与项目无关：登录 registry → `docker pull` 指定 tag → `docker tag` 回 compose 固定的 `zly-ai-video-studio:latest` → `compose up -d --no-build --force-recreate` → `/api/health` 60 秒检查，失败自动回滚 `.deploy-history` 上一版；`rollback.sh --list/--to N` 手动回滚。CI 每次部署先把仓库内 `ops/deploy/*.sh` scp 覆盖到服务器，保证脚本与提交版本一致。
- GitBlit 无感接入:开发机继续 push 老 GitBlit 地址,`ops/gitea/gitblit-sync.sh` + systemd timer(`ops/gitea/systemd/`)每分钟把增量以真实 `git push --mirror` 同步到 Gitea(仓库名配在 `.env` 的 `SYNC_REPOS`,缺仓自动创建),真实 push 事件确保 Actions 必触发;刻意不用 Gitea 自带 pull 镜像(镜像同步不触发 push 钩子/Actions)。CI 触发延迟 ≤ 同步周期(默认 1 分钟)。
- 受影响文件：新增 `.gitea/workflows/deploy.yml`、`ops/gitea/{docker-compose.yml,.env.example,runner-config.default.yaml,setup.sh,gitblit-sync.sh,systemd/gitblit-sync.{service,timer}}`、`ops/deploy/{deploy.sh,rollback.sh}`、`docs/CI-CD-Gitea部署指南.md`；`.gitignore` 追加 `ops/gitea/runner-config.yaml`、`.deploy-history`。未改动 `Dockerfile`、`compose.yaml`、`deploy-server-image.sh`。
- 兼容性：不动现有手工部署链路（`导出服务器部署镜像.bat` / `deploy-server-image.sh`）与任何运行时行为；Gitea 侧要求 CI 机与部署服务器 Docker 配置 `insecure-registries: ["124.70.90.30:3080"]`。
- 验证命令：CI 服务器 `bash ops/gitea/setup.sh`；推送 master 后在 Gitea Actions 观察两阶段日志；服务器 `bash ops/deploy/rollback.sh --list`。
- 回滚方式：删除 `.gitea/` 与 `ops/` 即回到纯手工部署；已部署服务器用 `ops/deploy/rollback.sh` 回退旧镜像。

## 2026-11-07：音乐播放器同步歌词

- 原因：音乐试听需要逐句跟随和歌词跳播。右侧面板采用 [A 版封面取色](design-ref-music/lyrics-20261107/music-lyrics-dark-ab-v002.png)，复用展示封面与浅暗主题，当前句 24px、邻句 18px，写歌和曲库在左侧继续可用。
- 播放：用户点播放时默认展开右侧面板，播放条的「歌词」可收起或再次打开。面板跟随当前曲目，直接读取同一个 HTMLAudioElement 的时间与暂停状态。拖进度或点歌词更新播放位置，手动滚动暂停跟随。「回到当前」恢复居中。历史、对齐中和纯音乐均有对应显示，静态歌曲详情仍从曲库菜单进入。
- 时间轴：`GET/POST /api/music/jobs/{job_id}/lyrics` 按任务所有者隔离，提交需要 CSRF。首次打开有人声歌词的成品时后台准备，优先匹配 YuE2 已保存的 `metadata.lrc`，其余用本机 faster-whisper 从转存后的成品识别带时间的词，再按顺序匹配原歌词。中文识别结果用拼音辅助匹配同音字和繁简字形，展示原词。无法可靠匹配的行保留为静态文本。识别器优先使用 `ZLY_AI_VIDEO_STUDIO_MUSIC_ASR_MODEL_DIR` 指定的本机模型目录，也可复用 Hugging Face 缓存中的 medium 或 small，使用 CPU int8 与本地文件模式。
- 兼容性：新增 `music_job_lyrics` 缓存表，MySQL 与 SQLite 启动时建表。时间轴与原生成记录分开，歌曲无需重生成。每个后端最多处理一首，数据库用带期限的认领令牌避免重复处理，旧认领无法覆盖新结果。删除歌曲联动清理时间轴。
- 受影响文件：`backend/app/{music_lyrics,music_yue2_client,main,models,storage}.py`、`backend/requirements.txt`、`sql/024_music_lyrics.sql`、`frontend/src/music/` 与专项测试。
- 验证命令：`python -X utf8 -B -m pytest backend/tests/test_music_provider.py -q`、`pnpm --dir frontend build`。桌面端使用 5173 检查成品对齐、滚动、高亮、暂停跳播、切歌和双主题。
- 回滚：撤销上述播放器面板、同步接口和存储改动，按 `pnpm --dir frontend build` 重新构建部署产物。可以保留时间轴缓存表，歌曲与原歌词继续使用原有记录。

## 2026-11-07：音乐创作室双主题还原（当前基线）

- 变更原因：按确认的[音乐页设计稿](design-ref-music/suno-20261107/music-studio-dark-v001.png)还原 `/music`。延续全局导航和页头，创作面板、四列氛围卡、曲库、当前歌曲详情和固定播放器使用同一桌面栅格。
- 创作状态：默认灵感生成、人声歌曲、3 分钟；氛围模板填入描述及歌曲类型，时长支持预设与 10–600 秒自定义。高级创作首次打开后保留草稿，继续提交风格、歌词、时长、输出格式及可用风格预设。采样步数、种子和推理模式使用现有服务默认值，不放到创作界面。
- 曲库与播放：筛选、搜索、视图、详情选择与播放器当前歌曲分别管理；筛选不会中断正在试听的歌曲。单个原生音频元素负责播放、上一首/下一首、暂停后定位及音量；已完成曲目可预选但不自动播放。曲风已匹配的歌曲使用 `frontend/public/music-art/` 中的展示封面，其余使用原封面或默认图；原 `cover_url` 保留并在详情中提供入口。歌曲详情和歌词直接读取现有列表数据。
- 双主题：继承根 `StudioThemeProvider`、Ant Design 主题与 `--studio-*` 语义色。页头在音乐页复用 `/api/music/status` 查询，只显示配置状态。曲库轮询、生成/删除接口、音频及原封面存储均保持原样。
- 受影响文件：`frontend/src/music/`、`frontend/public/music-art/`、`frontend/src/App.tsx`、`frontend/src/components/StudioHeader.tsx`。兼容性：无路由、API、数据库、任务队列或远端服务配置迁移。
- 验证：`pnpm --dir frontend build`（877 项前端测试、TypeScript、Vite 构建），`python -X utf8 -B -m pytest backend/tests/test_music_provider.py -q`（21 项）。5173 桌面 1920×1200 实查双主题、草稿、氛围模板、筛选、歌词、实际音频播放、切歌及暂停后定位；[实拍与验收数据](design-ref-music/suno-20261107/implementation-20261107/)。
- 回滚：撤销本节列出的音乐界面和页头接线，移除本轮的配图及曲库测试；保留现有音乐接口、配置和任务数据。

## 2026-11-07：新增顶层「音乐」模块（远端 YuE2 Studio 音乐生成）

- 变更原因：远端电脑（192.168.10.54，RTX 4080）已部署本地音乐生成程序 YuE2 Studio v3.8.3（Rust 便携版，REST `/v1/music/jobs` 提交 → 轮询 → 曲库 FLAC 48kHz/24bit，全部接口需 `Authorization: Bearer <access_key>`），工作台需要为其提供产品化入口。
- 机制基线：顶层菜单第 7 项「音乐」（`/music`，位于灵感与导演台之间）→ 新工作区 `frontend/src/music/`，Suno 式创作页布局：左侧粘性创作面板（标题/风格描述 + 「风格灵感」英文曲风胶囊点击追加 + 歌词 + 分节标签速插胶囊 + 时长 Segmented 预设（30秒/1分钟/3分钟/3.5分钟/自定义，`duration_seconds` 字段常驻注册保证提交值正确）+ 输出格式；更多设置收进 steps、seed/lm_seed、CoT、LoRA 适配器；渐变主按钮）；右侧无边框曲库列表（`useQuery` 轮询活跃 4s/空闲 15s）：播放行封面即播放键（悬停浮现播放/暂停圆钮，播放中卡片主色描边 + 标题前均衡器动效）、单例 `Audio` 串播放态、antd Slider 迷你进度条 + 时间码、生成中封面微光 shimmer + Progress、失败原因块、下载/删除。后端 `/api/music/*`（列表/创建/详情/删除 + `/api/music/status`、`/api/music/config`）由 `MusicJobService`（`backend/app/music_job_service.py`，线程池 max_workers=1 串行，状态机 queued→running→succeeded/failed，完成时写 result_url/duration_seconds，lifespan 恢复中断任务）执行：`YuE2Client`（`backend/app/music_yue2_client.py`，纯 REST，控制面 POST/GET `/v1/music/jobs*`、媒体面 GET `/v1/library/media/{song_id}` 与 `/v1/library/songs/{id}/cover`）→ 音频/封面上传七牛 → `result_url`/`cover_url` 写回 `music_jobs` 表（DDL：`sql/023_music_generation.sql` + storage.py SQLite 分支；`music_provider_settings` 存 base_url 与加密访问密钥，默认值可被 `ZLY_AI_VIDEO_STUDIO_MUSIC_URL` 覆盖）。管理设置「AI 供应商」tab 追加「音乐生成（YuE2 Studio）」卡片（`frontend/src/admin/MusicProviderSettings.tsx`，三端点 `/api/admin/providers/music` GET/PUT/test，密钥 CredentialManager 加密、不回显）。曲库范围只含工作台创建的任务；不与资产库联动（后续再打通）。
- 受影响文件：新增 `sql/023_music_generation.sql`、`backend/app/music_yue2_client.py`、`backend/app/music_job_service.py`、`backend/tests/test_music_provider.py`、`frontend/src/music/`（api.ts / MusicWorkspace.tsx / MusicCreateForm.tsx / MusicJobList.tsx / music.css）、`frontend/src/admin/MusicProviderSettings.tsx`；修改 `backend/app/storage.py`（建表 + JobStore music 方法 + 播种）、`backend/app/config.py`（`music_url`）、`backend/app/models.py`（Music* 请求/响应模型）、`backend/app/main.py`（导入、lifespan configure/recover、9 个路由）、`frontend/src/paths.ts`（`PATHS.music` + `STUDIO_ROUTE_PATHS` + `StudioWorkspace` + `studioWorkspaceFromPath`）、`frontend/src/App.tsx`（懒加载、双导航 NavLink、workspace 分支）、`frontend/src/components/StudioSymbols.tsx`（music 符号）、`frontend/src/admin/AdminSettings.tsx`（providers tab 追加卡片）。
- 兼容性：纯新增模块，不改已接入工作流协议、`jobs`/`ai_project_jobs` 表、`JobMode` 枚举与既有路由；`music_*` 两张新表 `CREATE TABLE IF NOT EXISTS`，MySQL 由 `mysql_schema_sql()` 自动合并、SQLite 走 storage.py 同构 DDL，老库启动时自动建表并播种默认行。音乐任务不占用主 worker（独立线程池），不影响现有任务串行队列。未配置服务时 `/music` 页面展示引导横幅、创建接口返回 503。
- 验证命令：`python -m pytest backend/tests/test_music_provider.py -q`（15 项：存储 CRUD、配置加密、状态机成功/失败/恢复、端点权限与 CSRF、参数校验）；前端 `pnpm exec tsc -b`；桌面端在 5173 用真实远端实例走通「配置 → 测试连接 → 提交 → 轮询 → 试听/下载」。
- 回滚方式：前端从 `App.tsx` 双导航与 workspace 分支移除音乐项、`paths.ts` 移除 `PATHS.music` 即隐藏入口（`music_jobs` 数据保留无副作用）；后端删除 9 个 `/api/music*` 路由与 `music_job_service`/`music_yue2_client` 两个文件；两张表无需回滚（`DROP TABLE music_jobs, music_provider_settings` 可选）。

## 2026-11-07：音乐模块升级为 Suno 式 vibe 生成（一句话描述 → 大模型扩写 → 出片）

- 变更原因：参考 Suno 首页与导演台首页创作面板，把「音乐」从表单式创作升级为 vibe 体验：用户用一句自然语言描述想要的歌，大模型自动扩写成 YuE2 引擎所需的英文风格标签串与分节歌词后直接入队，无需理解引擎参数。
- 机制基线：`POST /api/music/vibe`（`MusicVibeRequest`：description ≤1000 字 + duration_seconds 10-600 + instrumental）→ `MusicJobService.create_from_vibe()` 用 `LlmProviderService.chat_json()`（新增的通用一次性 JSON 对话方法，走默认大模型端点）按「YuE2 写作指南」扩写为 `{title, style, lyrics}`：style 为英文标签串（语言→曲风→人声→乐器→情绪→BPM），lyrics 为分节标签结构（纯音乐为空），校验后走既有 `enqueue()` 入队；LLM 失败透传 `LlmError` 由路由映射 502（区别于服务未配置的 503）。前端 `/music` 重构为 Suno 首页式：居中 hero「来写首歌吧」+ 双模式创作面板（Segmented「灵感生成 / 高级创作」，对齐导演台首页 `dh-create-*` 视觉：无边框输入器 + 底部工具条 + 圆形发送键，灵感工具条含「纯音乐」开关与「时长」预设 Popover，Ctrl+Enter 提交）+ 曲库卡片网格（封面即播放键、悬停浮现播放/下载/删除、生成中微光+进度、播放中主色描边）+ 底部粘性迷你播放条（单例 Audio，进度 Slider + 时间码）；原「高级创作」表单（风格胶囊/段落速插/时长预设/LoRA）整体内嵌进高级模式面板。
- 受影响文件：`backend/app/llm_provider.py`（新增 `chat_json`）、`backend/app/music_job_service.py`（`MUSIC_VIBE_SYSTEM_PROMPT` + `create_from_vibe`）、`backend/app/models.py`（`MusicVibeRequest`）、`backend/app/main.py`（`/api/music/vibe` 路由）、`frontend/src/music/`（api.ts / MusicWorkspace.tsx / MusicJobList.tsx 重构 + music.css 重写）、`backend/tests/test_music_provider.py`（新增 6 个 vibe 用例）。
- 兼容性：`POST /api/music/jobs` 高级创作接口与既有任务链路不变；`chat_json` 为新增公开方法不改既有 LLM 调用；前端仅音乐模块内部重构，不影响其它工作区。灵感生成依赖大模型服务已启用（未启用时报 502 并提示）。
- 验证命令：`python -m pytest backend/tests/test_music_provider.py -q`（21 项全过）；`pnpm exec tsc -b` 与 `pnpm build`；桌面端真实链路：5173 输入「写给海子的一首民谣，男声，木吉他，忧伤但温暖，提到德令哈和麦地」→ 大模型扩写出《德令哈的麦地》（Mandarin folk + 口琴/弦乐、82 BPM、分节歌词）→ 远端出片 3:02 FLAC → 播放条试听正常，双主题已截图核对。
- 回滚方式：前端还原 MusicWorkspace/MusicJobList/music.css，后端移除 `/api/music/vibe` 路由与 `create_from_vibe`/`chat_json` 即回到高级创作单模式；music_jobs 数据与既有播放链路不受影响。

## 2026-11-07：导演台 Skill Pack 新增「电影感Vlog双轨导演」配方（cinematic-vlog-ab-director）

- 变更原因：`vlog-ab-director`（MiniMax Hub 社区 Skill）已用真实 MiniMax H3 R2V 跑通一条电影感 Vlog 单片（任务 `l4YXI85nCme`，16:9、15s、960×544、succeeded），用户确认效果良好并要求沉淀为导演台可选「制作配方」。
- 机制基线：导演台「制作配方」= Skill Pack（`GET /api/skill-packs`，工程 `extra.skill_pack_id`），由 `skill_packs/recipe.py.scan_pack_recipes()` 扫描 `backend/app/skill_packs/<id>/` 自动发现（跳过 `.`/`_` 前缀目录），`default_recipe()`（空 id「H3 官方六段式」）恒为 `list_pack_catalog()[0]`。新配方为纯配置目录 `cinematic-vlog-ab-director/`（`meta.yaml`/`SKILL.md`/`references/h3-video-prompt-template.md`/`SOURCE.md`），不新增 handler、不改注册表代码。
- 配方语义：整条 Vlog 视为一个 Beat（单片一次出片、内部按 2.5 秒节拍器恒切多镜、A/B 机位交替），画幅不写死跟随项目/工坊，`confirm_format` 仅约束 `duration_min=5/duration_max=15`；`workshop_shot` 复用 `write_timestamped_zh_prompt → polish_ref2va → bind_r2v_slots`；`packing_overrides.skip_program_pack=true` 让工坊直接采用大模型产的英文六段；`r2v_slots = characters(subject) + scene`，与 `<Picture 1>`/`<Picture 2>` 上传顺序一致。
- 校验对齐：装箱模板 `references/h3-video-prompt-template.md` 保留 `handlers._OFFICIAL_BLOCK_TITLES` 要求的八块字面标题（含「按旁白和画面内容切镜」，A/B 节拍器语义写入其后括号与正文），使工坊产的中文八块可通过 `validate_timestamped_zh_prompt`（八块齐全、时间码覆盖总时长、`<Picture n>` 与 r2v slot 对应、台词逐字）。
- 受影响文件：新增 `backend/app/skill_packs/cinematic-vlog-ab-director/`（四文件）；`backend/tests/test_skill_packs.py` 新增 `SkillPackCinematicVlogTests`（发现/注册步骤/catalog/overrides/r2v_slots/八块标题/Vlog 中文稿零校验错误）。
- 兼容性：不改 API 契约、数据库、端口、`workflow_registry`、ComfyUI 节点或已注册步骤实现；默认与半解说配方行为不变。源 Skill 的 30s 两段接力模板未纳入本单片配方。
- 验证命令：`python -X utf8 -B -m unittest backend.tests.test_skill_packs`（新增 5 项全绿）；后端全量与前端构建见同日回归。
- 回滚方式：删除 `backend/app/skill_packs/cinematic-vlog-ab-director/` 与测试类即恢复原配方列表，`scan_pack_recipes()` 自动不再发现，无数据迁移。

## 2026-11-06：无限画布节点/端口/连线对齐资产画布 v006

- 变更原因：延续「以资产画布为基准」的方向，把无限画布的节点外壳、端口、连线也统一到资产画布 v006 风格。
- 改动：`frontend/src/canvas/canvas-node-shared.css` 取值改为资产画布 v006——节点：无描边、10px 圆角、`outline` 选中（hover `--studio-border-strong`；选中 `--studio-text-secondary`、offset 5、`0 0 0 1px var(--studio-border)`）；端口：26px 圆形、`1px solid var(--studio-text-secondary)` 描边、`--studio-canvas` 底色、hover 变 `--studio-text` + `0 0 0 4px var(--studio-hover)`；连线：`#555c68`、`opacity .65`（浅色 `#a9afb9`），选中 `#82b8f3`（浅色 `#3279ba`）、`opacity 1`，拖拽线 1.5px，并隐藏无限画布特有的流动光效 `.canvas-flow-edge-light`。`canvas.css` 移除 `.canvas-stage` 下的连线/选中/拖拽线规则，改由共享层统一。
- 兼容性：纯前端样式；无接口、数据、路由变更。**资产画布未改动**（仍用自身 v006 规则，取值与共享层一致）。
- 已知差异（未对齐）：资产画布端口是「点击开连线菜单」，无限画布端口仍是拖拽连线，未加 `+` 图标；资产画布端口悬停才出现，无限画布端口常显（受连线模式设置控制）。
- 验证命令：`pnpm --dir frontend build` 通过；视觉需硬刷新确认。
- 回滚方式：还原 `canvas-node-shared.css` 与 `canvas.css` 两处即可；无数据影响。
- 待定：是否把资产画布也接到这份共享层（外观不变，从而严格做到「改一处」）。

## 2026-11-06：删除任务级联清理云端产物

- 原因：`DELETE /api/jobs/{job_id}` 原先只删记录，七牛云产物成为孤儿；直接按最新输出删除又会漏历史轮次、二采预览，且可能破坏复用同一地址的资产。
- 当前契约：沿用登录、CSRF 与任务归属校验；在 `JobStore.delete(before_commit=...)` 内读取锁定任务快照（MySQL 父行 `FOR UPDATE`；SQLite `BEGIN IMMEDIATE`），先执行但不提交任务及外键子行的 SQL 删除，确保级联锁冲突发生在云端清理之前。提交前回调检查快照，任何生成项排队/运行时拒绝；收集任务镜像、所有轮次生成项和 `refine_state.preview_outputs` 的云端产物，全部验证保存的稳定 URL 与当前七牛对象 URL 一致（忽略签名 query/fragment），再检查引用并按 key 去重清理；全部成功才提交记录删除，校验或云端失败均回滚 SQL。
- 引用保护：`JobStore.job_media_in_use` 查询其他任务/轮次/生成项、导演工程与素材库、导演操作、画布草稿与历史版本、导演项目/资产/分集/任务、智能剪辑、精选与灵感示例中的已知持久媒体字段；匹配 key（原文、URL 编码、JSON Unicode/斜线转义）与任务 ID，跨账号检查。匹配时整次返回 409，不删云对象或记录；历史快照及已软删但可恢复的画布也保留引用，不自动重写链接或跳过引用校验。
- 失败语义：存储未启用、切换到其他存储、缺少原稳定云 URL 或 URL 不匹配时返回 409；不猜原 Bucket、不按任意外部 URL 删除。七牛失败/返回 False 为 502，数据库事务回滚，记录保留以便重试；已经删除的对象无法随 SQL 回滚，七牛 612（对象不存在）视为成功。成功仍返回 `{"id":"..."}`。
- 范围与边界：只清理任务的云端输出，不删除上传参考素材、本地下载、ComfyUI 原始文件，不处理此前已删记录的孤儿对象；不是后台 GC。当前历史输出未记录 Bucket 身份，因此以保存的云 URL 和当前域名/key 一致为必要条件，不能据此跨 Bucket 追溯。父任务锁串行化删除和受外键约束的新轮次；JSON 媒体引用写入未统一纳入此锁，检查与删除间仍有跨模块并发写入窗口，删除期间应避免在其他窗口新增该产物引用。
- 界面：单项与批量确认框明确提示云端永久删除、本地文件保留、引用冲突会阻止删除；沿用原 mutation 与失败反馈，无布局改动。
- 受影响文件：`backend/app/{main,storage,api_documentation}.py`、`backend/tests/test_ai_studio.py`、`frontend/src/App.tsx`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md`。无表结构、端口、工作流与供应商配置迁移。
- 验证：`python -X utf8 -B -m unittest backend.tests.test_ai_studio`（62 项通过，含级联 SQL 锁冲突先于云端操作、失败回滚与 612 重试）；`python -X utf8 -B -m unittest discover -s backend/tests -t .` 全量运行 1748 项，1 项跳过，其余通过。`pnpm --dir frontend build` 通过（内含 125 文件 / 851 项前端测试）。5173、1440×1000 桌面实拍单项/批量确认框的浅暗双主题与取消；浏览器拦截 DELETE 模拟 409，批量正确提示「已删除 0 个任务，1 个失败」，涉及的两个任务 GET 均仍为 200。破坏性行为仅用临时 SQLite、七牛替身和浏览器拦截验证，没有真实云端删除。
- 回滚：仅撤回上述删除清理、引用检查、确认文案及对应测试/文档增量，保留同文件其他未提交工作；回退后恢复只删记录。已删云对象不能通过代码回滚恢复，需要独立备份。

## 2026-11-06：AI 工具中心首页对齐即梦（容器宽度、分组间距、一句话副标题、悬浮「去使用」）

- 变更原因：工具中心卡片按内容自然高度渲染，长描述（最多 4 行）与短描述混排导致同行底边参差；同时容器宽度、标题与分组字号、chips 形态与即梦 AI 工具页差距明显，卡片缺少可用的行动入口。本轮把首页改为即梦式紧凑卡片墙。
- 当前基线：
  - 容器：`App.tsx` 的 `<main>` 仅在 `workspaceView === "tools" && location.pathname === PATHS.tools` 时用 `max-w-[1680px]`，其余视图与工具子页仍为 `max-w-[1180px]`；`.studio-tools-main:has(.studio-motion-tool)` 的 1302px 覆盖不变，工具页宽度不受影响。1920/2560 视口实测内容 1616px、四列卡片 386px、封面 384×216（16:9）。
  - 排版间距：标题 30px/700；分类 chips 左对齐、去边框、圆角 10px、高 36px，选中态仍用 `--studio-primary` 实底（即梦为中性灰，此处保留工作台品牌色）；分组标题 18px/600 + 下距 18px；网格间距 16px → 24px；卡片圆角 16px → 14px，正文 `14px 16px 16px`、标题 16px。
  - 文案来源：卡片副标题由 `tool.description` 改为 `tool.tagline`（注册表本就注明 tagline 供「首页多功能墙与工具中心卡片」使用，`description` 面向接口），`white-space: nowrap` + 省略号兜底；完整 `description` 保留在卡片 `aria-label`，屏幕阅读器与工具页文案不受影响。
  - 交互：可用卡片封面右下角新增悬浮「去使用」胶囊（`.studio-tool-card-v2-cta`，`pointer-events: none`，整卡仍是唯一链接），封面缩放由 `scale(1.03)/360ms` 提到 `scale(1.07)/620ms`；规划中/即将上线卡片不出现该胶囊。
  - 等高：`.studio-tool-card-slot` 改为 flex 容器、卡片 `flex: 1 1 auto`、正文 `flex: 1 1 auto`，网格行高传递给卡片，1920/1280/960/760 四档实测每行高度差为 0。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/tools/ToolsHome.tsx`、`frontend/src/tools/tools.css`。
- 兼容性：纯前端展示层，无接口、数据库、路由与工作流协议变更；`/tools/:id` 各工具页未改动。
- 验证命令：`pnpm --dir frontend build`（vitest + `tsc -b` + vite 通过）；5173 桌面端无头 Chrome + CDP 实拍浅暗双主题与 1920/2560/1280/960/760 视口，量测 `main` 宽度（工具首页 1680、`/tools/stem-split` 1302、`/tools/prompt-reverse` 1180）、23 张卡片 tagline 无一处省略号截断、悬浮态 `ctaOpacity 0→1` 且封面 `transform: matrix(1.07,...)`。未做移动端检查。
- 回滚方式：还原上述三个文件即可退回多行描述 + 1180px 容器的版本；无数据迁移。

## 2026-11-06：结果媒体动作三层契约（交接定位符 → 动作注册表 → 两个消费面）

- 变更原因：工具首页的能力已经成规模，但创作结果与工具之间没有通路——要把某张成片拿去扩图/重拍/去背景，只能下载后重新上传；同时卡片悬浮条与全屏预览侧栏各自硬编码按钮，同一动作在两处判定不一致。现在把「这条结果能做什么」抽成三层，两个入口共用一份数据。
- 第一层 `frontend/src/media-handoff.ts`（新增）：媒体定位符 `MediaHandoffSource = { jobId, generationItemId, outputIndex, kind }` 是唯一寻址方式，URL 形态 `?sourceJob=&generation=&output=&kind=` 由 `mediaHandoffPath()` 生成、`readMediaHandoff()` / `isMediaHandoffSource()` 解析，`outputDownloadUrl()` 拼既有下载路由，`fetchHandoffFile()` 用 `GET /api/jobs/{job}/generations/{item}/outputs/{index}/download` 取回字节并按 magic bytes 判定 MIME 后包成 `File`。不新增后端接口，不引入新的 ID 体系。
- 第二层 `frontend/src/media/media-actions.ts`（新增）：`DEFINITIONS` 声明顺序即展示顺序，每项标注 `kind`、`slot`（`bar`/`more`）、可选 `toolPath`（工具页交接链接）或 `native`（宿主站内动作开关）、`ownerOnly`。`mediaActions()` 输出的 `MediaActionItem[]` 是唯一真相：工具页动作要求该工作流在 `/api/modes` 里存在且 `available !== false`；站内动作要求宿主显式打开对应 `host` 开关；`inspectingOtherUser` 会收起 `ownerOnly` 与定位符缺失的动作；超出 `MEDIA_ACTION_BAR_LIMIT = 5` 的 `bar` 项按声明顺序降级为 `more`（只统计真正出现的项）。`nvidia-rtx-vsr`、`seedvr2-upscale`、`keep-face-restore`、`minimax-h3-lip-sync` 属 `hidden_from_catalog`，`/api/modes` 不返回，由 `HIDDEN_TOOL_WORKFLOWS` 维持与工具首页一致的「已上线」判定，引擎级不可用仍由工具页报告。
- 第三层消费面：`ImageStudioModule` / `VideoStudioModule` 的结果卡片通过 `resolveActions(source)` 向宿主取表、`onAction(item, result)` 落地，`mediaActionBar()` 渲染图标、`mediaActionMenu()` 渲染「更多」；`App.tsx` 的 `runMediaAction()` 是两处共用的唯一落地实现（href → `navigate`，`reference` → `useMediaAsReference()`，`to-video` → `createVideoFromImage()`，`canvas` / `jianying` / `params` / `remove` → 各自站内状态），`previewMediaActions()` 把同一张表喂给 `MediaPreviewModal` 的 `actions`，因此预览侧栏与卡片不可能漂移。`MediaPreview` 新增 `source` / `roundId`，输出记录由 `findJobOutput()` 按定位符从 `job.rounds[].generation_items[]` 回查，保证与卡片取到同一条 `Output`。
- 工具页接收：`frontend/src/media-handoff-prefill.ts`（新增）的 `useMediaHandoffPrefill(params, onFile)` 在挂载时读回 `File` 并交给页面既有的上传入口，因此校验、预览与后续行为等同手动上传；已接入 `PhotoEditTool`、`MaskedImageToolPage`（局部重绘/消除笔）、`ImageOutpaintTool`、`ImageBgRemoveTool`、`ImageLayerSplitTool`、`VideoUpscaleTool`、`PartialRetakeTool`、`LipSyncTool`，`FaceRestoreTool` 直接调 `readMediaHandoff()`。
- 受影响文件：新增 `frontend/src/media-handoff.ts`、`frontend/src/media-handoff-prefill.ts`、`frontend/src/media/media-actions.ts`（+ `media-actions.test.ts`、`media-handoff.test.ts`、`media/video-results.test.tsx`）；修改 `frontend/src/App.tsx`、`frontend/src/media/{ImageStudioModule.tsx,VideoStudioModule.tsx,video-results.css,image-results.css,image-results.test.tsx}` 与上述工具页。`MediaPreviewModal` 的 `actions` 契约本身未改，只是第一次由注册表供数。
- 兼容性：纯前端，无接口、表结构、端口与工作流协议变更。`createVideoFromImage` 入参从 `ImageResult` 放宽为 `{ jobId?, generationItemId, outputIndex }`。视频卡片静音按钮从工具条移入播放行，`.studio-video-quick-tools` 在无动作时不再渲染空胶囊。导演台预览未接入：`Director2Job` 与资产记录只持有 `result_url`，`ai_project_jobs` 没有 `generation_item_id` / `output_index`，交接契约无法寻址，接入需后端先给出可定位的输出记录。
- 验证命令：`pnpm exec tsc -b`；`pnpm --dir frontend exec vitest run`（125 文件 / 851 项通过）。5173 桌面端无头 Chrome + CDP 实拍：图片卡片悬浮条 `["用作参考图生成图片","图片编辑生成图片","局部重绘生成图片","去背景生成图片","生成视频生成图片"]` +「更多图片操作」，点「用作参考图」后创作台显示「已添加 1 / 10 张」并插入 `<Picture 1>`；视频卡片在「H3 动作迁移」下 5 图标含「用作参考视频」，在「H3 Director 加速版」下该按钮不出现，量测工具条 168px 单行 / 播放行 124px 单行（卡片 194px）；预览侧栏图片 10 项、视频 9 项，点「局部重绘」跳 `/tools/image-inpaint` 且预览已关闭，点「导出剪映」弹出导出对话框。未做移动端检查。
- 回滚方式：还原上述修改文件并删除新增的 `media-handoff.ts`、`media-handoff-prefill.ts`、`media-actions.{ts,test.ts}`、`media/video-results.test.tsx`，即退回「卡片只有下载/预览、预览侧栏只有打开关联任务」；无数据迁移。

## 2026-11-06：GRS 生图目录支持拖拽排序，「默认模型」与显示顺序解耦

- 变更原因：创作页「选择工作流」里生图模型的顺序此前由 `is_default DESC, sort_order` 共同决定——默认模型被钉在首位，管理员无法把常用模型（如 `gpt-image-2.6`）排到前面，一个字段同时承担「谁排第一」和「哪个是默认」两件事。现在 `sort_order` 只管显示顺序，`is_default` 只管预选与自动出图。
- 后端契约：`GrsProviderService.enabled_image_workflows()` 只按 `(sort_order, display_name)` 排序，不再把默认模型提前；`WorkflowDefinition` 新增 `is_default: bool = False`，`image_workflow_from_catalog()` 从目录行透传，`ModeResponse` 同步声明该字段（否则 pydantic 会在 `/api/modes` 响应里剥掉）。`storage.list_grs_image_models()` 的 SQL 改为 `ORDER BY sort_order ASC, display_name ASC`；`add_grs_image_model()` 未显式给 `sort_order` 时取 `MAX(sort_order)+10` 追加到目录末尾，不再共用常量 300（避免新导入的模型和已有行并列后按显示名乱序）。
- 消费方改造：`director_jobs.default_image_workflow_id()` 显式读 `is_default`（字典与工作流对象两种入参都支持），只在目录未标记默认时回落首位；`resolve_composite_model()` 原本就按 `is_default` 取，行为不变。`director_assistant/actions.py` 里给助手看的模型清单 SQL 改为 `ORDER BY sort_order`，而「取默认模型」那条查询保留 `ORDER BY is_default DESC, sort_order` + `rows[0]`，因为它就是在选默认。
- 前端契约：`/api/modes` 顺序即管理员顺序，`groupedWorkflowOptions` 保持服务端顺序不重排。`App.tsx` 的 `preferredDefaultWorkflow()` 与切工作流回落改为 `is_default` 优先、其次首位；`photoEditWorkflowChoices()` 输出 `isDefault`，`PhotoEditTool` 按它预选。管理后台目录表新增行首拖拽手柄列（原生 HTML5 dnd，手柄 `draggable`、整行作为放置目标，不引入 dnd 依赖），落点由 `grs-catalog-order.ts` 的 `reorderCatalogRows()` 计算并按新顺序重编密集 `sort_order`（步长 10，给后续导入留空隙）；表格标题在有未保存改动时显示「有未保存的改动」标签并把「保存目录」升级为主按钮，保存仍走原 `PUT /api/admin/providers/grs/models`。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/grs_provider.py`、`backend/app/storage.py`、`backend/app/director_jobs.py`、`backend/app/director_assistant/actions.py`、`backend/app/api_documentation.py`、`frontend/src/App.tsx`、`frontend/src/generation/image-edit.ts`、`frontend/src/tools/PhotoEditTool.tsx`、`frontend/src/admin/GrsProviderSettings.tsx`、`frontend/src/admin/grs-catalog-order.ts`（新增）、`frontend/src/admin/grs-catalog-order.test.ts`（新增）、`backend/tests/test_ai_studio.py`、`frontend/src/generation/image-edit.test.ts`。
- 兼容性：无表结构、端口与新增接口变更；`PUT /models` 仍只更新 `display_name/enabled/sort_order/is_default`，未标记默认时服务端把第一个启用行设为默认（原逻辑保留）。历史任务按 `workflow_id` 记录，不受顺序影响。任何把「列表首位」当默认模型的外部消费方需要改读 `is_default`——`/api/modes` 已带该字段。
- 验证命令：`python -m unittest backend.tests.test_ai_studio`（46 项）与项目根 `python -m unittest discover -s backend/tests -t .`（1721 项 OK，1 skipped）；`npx vitest run src/admin/grs-catalog-order.test.ts src/generation/image-edit.test.ts`（11 项）。5173 桌面端无头 Chrome + CDP 实拍：拖动 `gpt-image-2.6` 到 `gpt-image-2-vip` 前 → 出现「有未保存的改动」且「保存目录」变主按钮 → 保存后 `sort_order` 落库为 10…190、`/api/modes` 与创作页下拉同步变成 2.5 / 2.5 Flare / 2.5 Sunburst / 2 / **2.6** / VIP / Nano Banana 2.1，`is_default` 仍在 2.5；再把默认切到排序第 5 的 VIP，创作页预选变为「GPT Image 2 VIP」而下拉顺序不变，证明两者解耦；两轮验证后已按原始快照 `PUT` 恢复（默认 2.5，顺序回到 5/6/7/10/20/…/300 基线）。未做移动端检查。
- 回滚方式：还原上述后端与前端文件、删除 `grs-catalog-order.{ts,test.ts}`，`enabled_image_workflows()` 恢复 `is_default` 优先排序即可；`sort_order` 数值本身可保留（历史值与新密集值都只是显示键），无需数据迁移。

## 2026-11-06：GRS 生图模型目录改为从平台 `/v1/models` 动态拉取

- 变更原因：生图模型目录此前只有两条来源——`grs_catalog.BUILTIN_MODELS` 硬编码常量和管理员手填模型 ID。平台在售清单变化时界面完全不知道（实测上游已有 `gpt-image-2.6`、`nano-banana-2-lite`、`nano-banana-2.1`，内置表里都没有），每上一个新模型都要人抄一次模型名；反过来内置表还留着平台已不再返回的 `nano-banana`、`nano-banana-pro-vt`，管理员无法判断哪些是真在售的。
- 后端能力：`GrsClient.list_models()` 走上游 OpenAI 兼容 `GET {base_url}/v1/models`（`GRS_MODELS_TIMEOUT` 10/20s，带 Bearer 头）；`grs_catalog.py` 新增 `is_image_model_id()`（按命名家族过滤掉对话模型，新家族需在 `IMAGE_MODEL_PREFIXES` 登记）、`guess_profile()`（家族 → 六个既有能力档）、`title_from_model_id()`、`platform_entry()`（命中内置表沿用其能力档/分辨率/画质，未命中标 `profile_source="guess"`）；`GrsProviderService.fetch_platform_models()` 把平台清单与 `grs_image_models` 对齐成 `models/in_catalog`、`off_platform`、`total`，`import_platform_models()` 批量入库、已存在只跳过不覆盖既有显示名与开关。
- HTTP 接口：新增 `POST /api/admin/providers/grs/models/fetch`（只读，可带未保存的 `base_url`/`api_key`，与「测试连接」一致）和 `POST /api/admin/providers/grs/models/import`；两者要求超级管理员 + `X-CSRF-Token`，并写 `fetch_grs_platform_models` / `import_grs_platform_models` 审计。原 `POST …/models`（手填）与 `POST …/models/sync`（内置补种）保留为备用路径。
- 界面基线：管理设置 → GRS 图片供应商的目录区主按钮改为「从平台拉取模型」，弹窗按平台清单逐行勾选导入（新模型给可改的显示名、能力档下拉、启用开关；已在目录的行禁选并标「已在目录」，推断能力档的行标「需确认能力档」）；目录表在「上游模型 ID」列加「平台未上架」标记，并在表格上方汇总提示哪些模型不在本次平台清单里；「手动添加」降为备用入口，「同步内置目录」改名「补充内置目录」。
- 受影响文件：`backend/app/grs_client.py`、`backend/app/grs_catalog.py`、`backend/app/grs_provider.py`、`backend/app/models.py`、`backend/app/main.py`、`frontend/src/admin/GrsProviderSettings.tsx`、`backend/tests/test_grs_platform_models.py`（新增）。
- 兼容性：无表结构与端口变更，导入行 `builtin=0`；能力档仍只有 6 个 profile，平台出现新命名家族时必须先由管理员确认能力档才能入库，不做静默猜测上线；离线安装与无网络环境继续走原内置种子路径。目录没有删除接口，误导入的模型只能停用（`enabled=0` 即从创作页消失，历史任务与 `grs_image_models` 其他行不受影响）。
- 验证命令：`python -m unittest discover -s backend/tests -t .`（1719 项 OK，1 skipped），含新增 `backend/tests/test_grs_platform_models.py` 12 项；`pnpm --dir frontend build`；真实上游探针 `GET https://grsai.dakka.com.cn/v1/models` 返回 32 个模型、识别出 17 个生图模型、其中 3 个需确认能力档；5173 桌面端无头 Chrome + CDP 实拍拉取弹窗与导入回执（暗色主题）。未做移动端检查。
- 回滚方式：还原上述 5 个后端文件与 1 个前端文件、删除新增测试文件即可，接口与页面退回手填/内置补种路径；已导入的 `builtin=0` 目录行可保留并停用，不影响内置种子与历史任务。

## 2026-11-05：按 v006 落地通用资产画布

原因：采用已确认的即梦参考 v006 设计，让导演资产与文本、图片、视频、音频、剪辑工程在同一画布组合。保留已有资产 ID、媒体与用户布局；新增节点默认宽度按类型恢复，避免刷新后被内容撑窄。

- 界面：56px 页头与窄项目导航、可收起素材库（素材 / 图层 / 历史）、轻分组、方形角色 / 场景卡、节点附近的选中工具条、底部创作面板、缩放 / 小地图 / 抓手 / 快捷键。角色比场景多音色与信息入口；生成使用圆形发送按钮，「进入分镜」使用黑白主按钮，「打开智能剪辑」使用中性描边。
- 连线：默认端口隐藏，悬浮与选中显示；右侧 `+` 可点击或拖出，空白松手保留临时曲线并打开下游菜单，Esc 取消。角色为图片 / 视频 / 音频 / 角色 / 文本五项，场景为图片 / 视频 / 场景 / 文本四项；另可连接已有节点。拒绝重复、自连和循环引用。创作引用与原资产分别保存，删除通用节点不删除导演资产。
- 生成：所有模式和 primary / advanced / internal 层级继续来自 `/api/modes`，参数控件复用 `GeneratorOptionField`；图片与视频生成、状态轮询、停止 / 一采精修确认、历史版本沿用现有任务服务。文字合入提示词；媒体顺序按边的顺序与 `reference_slots` 校验，不支持的类型与空媒体不会被静默忽略。导演角色仍输出平台既有 16:9 角色设定板，界面如实回显固定比例。
- 风格与角色设计：`CreativeStylePicker.tsx` 与首页共用同一份 101 项目录、搜索、分类、缩略图和自定义风格；调用者各自保存值。角色设计包括基础、妆容与穿搭、五官、体型、发型、风格六页、22 组字段，支持地区联动、自定义色、内部滚动、跨页草稿、取消与保存。配置写入 `asset.extra.canvas_settings[targetKey]`，生成时编译进提示词，不隐式覆盖项目风格；有原片参考时继续遵守既有保真约束。地区项为平台可选项，除实采的撒哈拉以南非洲菜单外不声称逐项等同即梦。
- 剪辑：媒体导入复用原上传接口；剪辑节点使用独立 `canvas-<nodeId>` 序列，加入引用素材与片段，按 URL 去重，保留已编辑时间线；预览相对地址先解析生成任务的七牛原片地址，必要时通过既有上传服务导入。剪辑页提供「返回创作画布」，返回分镜时不会把画布序列当作分集。`/canvas/:id` 打开 linked 画布时重定向回对应导演画布，避免普通编辑器误读资产草稿。

状态 / 协议：`asset-canvas-sync.ts` 草稿 `schemaVersion=2`，保留旧 v1 的 asset / generator / video，并增加 image / text / audio / editor；资产节点只存 `{assetId,key,target}` 引用，用户引用边（含资产到资产）持久化，投影内部边仍按资产重算；新节点默认宽度 text 320、image 360、其他 380。无新增端口、HTTP 路由、数据库表、ComfyUI 节点或供应商切换。后端 `asset_image_prompts.py` 修正显式 prompt 的优先级，确保当前画布设计不被已有形象描述遮蔽；请求草稿不反写原形象文字。

受影响文件：`frontend/src/director2/{CreativeStylePicker,HomeCreativeOptions,asset-canvas-creative,asset-canvas-model,paths,ProjectFlowShell}`，`panes/{AssetCreationCanvas,AssetCanvasNodes,asset-canvas-context,asset-canvas-workspace.css,AssetsLibraryPane}`，`panes/assets/{CharacterDesignModal,character-design.css}`，`character-design-presets.json`，`smart-edit/SmartEditPane.tsx`，`frontend/src/canvas/{asset-canvas-sync,canvas-generation,canvas-model,CanvasWorkspace}`，`backend/app/media_studio/services/asset_image_prompts.py` 与相应测试。

验证：`python -X utf8 -B -m unittest discover -s backend/tests -t . -p "test_*.py"`：1702 项通过，跳过 1 项；`pnpm --dir frontend build`：120 个测试文件 / 819 项通过，TypeScript 与生产构建通过。5173 桌面浅暗主题验证了六页角色设计、五官滚动、地区联动、取消丢弃、101 项风格库与搜索、角色 / 场景菜单、真实端口拖出与空白落点、创建五类节点、引用、撤销 / 重做、保存刷新、成片进入剪辑及返回。未发起付费生成、导出或移动端检查；本轮 5 个临时通用节点均已清理，原工程仍为 71 个业务节点。剪辑验证仅写入独立画布序列，未覆盖 main 或分集剪辑。截图与设计核对见 `docs/design-ref-director/jimeng-asset-canvas-20261105/implementation-20261105/`。

兼容与回滚：已有资产媒体、ID、造型、项目风格、任务与用户布局保留，旧 v1 草稿可继续读取。回退 UI 时先备份当前 schema v2 草稿，并保留新增类型的解析与 linked 画布重定向；旧编辑器不能直接覆盖包含新类型的草稿。按本节受影响文件撤回本轮交互与样式即可，无数据库或供应商回滚；不要覆盖同文件中用户已有未提交改动。

## 2026-11-05 导演台资产画布统一到无限画布真引擎（一期）

- 变更原因：导演台资产画布原先是「每资产一份 `extra.creation_canvas` 碎片布局 + 只读投影」的伪画布——节点被 `extent:"parent"`/`dragHandle`/body 级 `nodrag` 三重锁死无法拖动，且每次 assets 变更都按投影重建 position 导致拖完回弹；布局无法跨资产连成一张、也不接生成管线。对齐即梦模型：一个画布实体（canvasId）+ 节点按 ID 寻址 + 资产与画布互引 + 一套生成管线，但保留用户偏好的 ac-* 资产画布皮肤（二期再统一双皮肤）。
- 当前基线（后端 · 绑定与存储分工）：`canvas_projects` 增加 `linked_director_project_id TEXT NULL` + 部分唯一索引（MySQL `sql/019_canvas.sql` 带列与 `UNIQUE KEY`；`storage.py` 两个方言分支均 `_ensure_column`/`_ensure_unique_index` 幂等补列补索引，旧库无需迁移脚本）。`canvas_store.create_project` 接受可选 `linked_director_project_id`；新增 `get_or_create_linked(owner_user_id, director_project_id, title)` 幂等获取或创建（同 owner+项目命中已有未删除画布直返，含 version/checksum/content；`IntegrityError` 竞态兜底再查一次；空 `director_project_id` 抛 `CanvasValidationError`）。新增 `POST /api/canvas/linked`（登录 + CSRF，body `{director_project_id, title?}`，返回与 `GET /api/canvas/projects/{id}` 同构的 `CanvasProjectResponse`）；`ProjectService.allows_user` 不通过（项目不存在/非本人）返回 404，标题超长 422，写审计 `ensure_linked_canvas_project`。`get_project`/`list_projects` SELECT 均带出 `linked_director_project_id`，linked 画布会出现在 `/api/canvas/projects` 列表（视为特性：一套画布跨处续作）。数据分工不变：资产媒体（图）真相仍在 director 资产表（分镜下游零改动），布局/连线/generator/视频结果节点真相迁到画布草稿（canvas draft）。
- 当前基线（前端 · 引擎切换）：新模块 `frontend/src/canvas/asset-canvas-sync.ts`（纯函数 + 单测）：`migrateLegacyLayout` 把旧 `extra.creation_canvas` 碎片位置合成初始草稿（只带位置不带媒体，迁移后不再读旧字段但数据保留可回滚）；`mergeProjection` 以草稿 position 覆盖投影默认位、剔除已消失资产节点、保留 generator/视频节点常驻；`serializeAssetCanvasDraft`/`assetCanvasDraftContent` 落盘时资产节点 data 收缩为 `{origin:"asset",assetId,key,target?}` 引用（不复制 URL/base64，规避 8MB 上限），只持久化连到 canvas 侧节点的用户边；`parseAssetCanvasDraft` 异常退化空草稿并剪悬空边、限 3000 节点/6000 边。`canvas-api.ts` 新增 `ensureLinkedCanvas`。`AssetCreationCanvas.tsx` 挂载时 `ensureLinkedCanvas`（title=`资产画布 · {项目名}`）读草稿、空草稿且有旧碎片时写入迁移结果，此后以本地 `nodes/edges` state 为唯一真相；`asset-canvas-model.ts` 的 `buildAssetCanvas` 移除 group `dragHandle` 与子节点 `extent:"parent"`/`dragHandle`；删除「按 graph 重建 position」的旧 effect，assets 更新只 merge 节点 `data` 与新增节点默认位、绝不重置已有位置；`ReactFlow` 设 `nodeDragThreshold=4`，卡片 body 级 `nodrag` 撤下只留可滚动参考图网格与按钮。持久化统一走 `saveCanvasDraft`+`createCanvasSaveQueue`+409 冲突重载（复用 `canvas-save.ts`，本地优先重试），替换旧的 `actions.position` 写 `extra.creation_canvas` 链路；viewport 存 `draft.viewport`（onMoveEnd 入草稿）替代 localStorage；头部新增草稿保存态（saved/dirty/saving/conflict）。`AssetsLibraryPane.tsx` 退役 `position` 动作、`connect` 改写入草稿边。
- 当前基线（前端 · 出视频）：资产图片节点保留右侧 source Handle，可连新节点类型 `assetGenerator`（ac-* 皮肤，`asset-canvas-generator.css`）；模式取 `fetchCanvasModes` 的 video 模式，参数按 `ui_group` primary/advanced 展示（internal 不显示）。提交复用 `canvas-generation.ts`：`incomingGeneratorReferenceNodes`→`validateGeneratorInput`→`canvasImageNodeFile`→`submitCanvasJob`，2.5s 轮询 `fetchCanvasJob`，完成后写入 canvas 同款 `video` 结果节点（可预览/重生成，结果自动进作品库）。I2V 首帧与 R2V 多参考均由 modes 注册的参考图数量约束自动路由，前端不硬编码模型列表；不新增资产字段。
- 受影响文件：后端 `backend/app/{storage.py,canvas_store.py,main.py,models.py,api_documentation.py}`、`sql/019_canvas.sql`、`backend/tests/{test_canvas_store.py,test_canvas_linked_endpoint.py}`（新增）；前端 `frontend/src/canvas/{asset-canvas-sync.ts,asset-canvas-sync.test.ts,canvas-api.ts}`、`frontend/src/director2/{asset-canvas-model.ts,asset-canvas-model.test.ts}`、`frontend/src/director2/panes/{AssetCreationCanvas.tsx,AssetsLibraryPane.tsx,asset-canvas-generator.css}`、`frontend/src/director2/ProjectFlowShell.tsx`。
- 兼容性：`/api/canvas/projects`、`/api/canvas/projects/{id}`、`canvas-generation.ts` 全套生成管线、`director` 资产表与分镜下游、`/api/modes`、`/api/jobs`、`/api/library` 均零改动；`extra.creation_canvas` 旧数据保留不删（可回滚）；linked 列可空、`get_or_create_linked` 幂等，重复挂载不产生多份画布；`/api/canvas/linked` 走通用 CSRF 与审计，ComfyUI 实例/模式可用性以「管理设置」当前配置为准，本次不切换。
- 验证：`python -m unittest backend.tests.test_canvas_store`（24 通过，含 4 个 get_or_create_linked 幂等/归属/校验/列表列用例，临时 SQLite 建库即验证迁移列存在）；`backend.tests.test_canvas_linked_endpoint`（4 通过：404 越权、happy+审计、空标题回退默认、422）；`pnpm --dir frontend exec tsc -b --force` 通过；`vitest run src/canvas/asset-canvas-sync.test.ts src/director2/asset-canvas-model.test.ts`（16 通过）；5173 桌面端浏览器自查拖任意卡片不回弹、旧资产布局迁移、连线出 generator、真实提交 R2V 视频并回显。
- 回滚：保留 `extra.creation_canvas` 原数据不动；前端撤回本模块（`asset-canvas-sync.ts` + `AssetCreationCanvas.tsx`/`asset-canvas-model.ts` 增量 + `canvas-api.ensureLinkedCanvas`）即回到旧碎片投影；后端 linked 列可空、`/api/canvas/linked` 与 `get_or_create_linked` 删除即可，已建 linked 画布与草稿数据可保留（旧版本忽略该列），无需 DROP 列。

## 2026-11-05 本地启动入口确保局域网监听

- 变更原因：工作台启动时会复用已运行的服务；旧版 Vite 即使仅绑定 `127.0.0.1:5173` 也被误判为可用，启动窗口虽打印 LAN URL，同网设备仍无法连接。防火墙规则创建失败原先被静默忽略。
- 当前基线：`启动本地视频工作台.bat` 只复用属于当前 `frontend` 的 Vite，且监听地址含非回环 IPv4；仅监听回环地址时自动停止并以 `--host 0.0.0.0` 重启。健康的 FastAPI 如仅监听回环地址也会重启为 `0.0.0.0:7865`。缺少 `5173` / `7865` 入站规则时，脚本通过 UAC 请求管理员权限创建或修复 Private/Domain 规则，工作台本身仍以当前用户身份运行；授权被取消或失败时显示警告。
- 安全与兼容性：本机 `127.0.0.1:5173`、`127.0.0.1:7865` 与端口/API 均不变；防火墙规则仅放行 Private/Domain 配置文件，不开放 Public；ComfyUI `8188` 不变且不暴露。
- 受影响文件：`启动本地视频工作台.bat`、`README.md`、本文档、`功能说明与扩展指南.md`。
- 验证方式：启动后执行 `Get-NetTCPConnection -State Listen -LocalPort 5173,7865 | Select-Object LocalAddress,LocalPort`；确认两个端口监听 `0.0.0.0` 或本机 IPv4，再用同网设备访问启动窗口打印的 LAN URL。本次未重启当前运行实例或执行跨设备连接检查。
- 回滚方式：恢复启动脚本旧的 Vite/后端复用判断与防火墙配置逻辑；如需撤销创建的规则，以管理员 PowerShell 执行 `Remove-NetFirewallRule -DisplayName 'ZLY AI Video Studio LAN 5173','ZLY AI Video Studio LAN 7865'`。

## 2026-11-05 整集直出智能补跑（gap_fill 区间补跑 + continue 前缀续写，尾帧严格首帧锚定）

- 变更原因：整集直出（`render_scope=episode`）不检测已有成片，单独跑过的镜头会被无谓重跑；但组内连续生成又不能简单「跳过前 k 镜」（时间线分组以连续镜头为最小单位，乱序编组会污染组内连续性）。按 `docs/整集直出智能补跑开发计划.md` 交付三个增量：B1 提交检测与确认弹窗、B2 连续区间补跑、B3 续写式整集直出。
- 当前基线（策略路由）：`POST /api/projects/{pid}/episodes/{eid}/generate-video` 的 payload 新增可选 `strategy`（`gap_fill` | `continue`），仅整集模式（无 `beat_ids`）接受；勾选式 selection 与逐镜模式收到即忽略（旧前端兼容）；未知值 400。`EpisodeVideoService._submit_episode_fill_jobs` 为编排入口：`gap_fill` 用 `_compute_gap_segments(beats, active_beat_ids)`（后端唯一权威；前端 `computeEpisodeGapSegments` 只做预期展示）求最大连续「未出片且无进行中任务」区间，每区间建一个 `render_scope=selection` 任务，payload 附 `strategy/gap_fill/segment_index/segment_total/anchor_beat_id/anchor_source_url`；`continue` 用 `_submit_continue_job` 检测已出片是否恰好构成 sequence `1..k` 连续前缀（前缀外无散落成片、k≥1 且 k<N、剩余镜无进行中任务），命中则建一个 `scope_lock=True` 的 episode 任务（beat 子集但保持整集编排、收尾写 `episode_video_url`），payload 附 `strategy/anchor_beat_id/anchor_sequence/anchor_prefix_urls`；不构成前缀自动回退 `gap_fill`（响应 `strategy` 回显实际策略）；全部未出片回落普通整集直出（返回 None 走原路径）；全部已出片 400「无需补跑/续写」。响应新增 `strategy/segment_count/anchor_sequence` 字段与 `submitted/skipped` 口径。`create_job` 新增 `payload_extra/scope_lock/scope_label` 三个可选参数（默认关闭，既有调用方零改动）。
- 当前基线（锚定原语，B2/B3 共用）：`episode_video_service.extract_video_tail_frame(url)` 下载前置成片 → ffmpeg `-sseof` 抽最后一帧 PNG；`_prepare_anchor_frame(payload, comfy, shots, subfolder)` 上传 PNG（`ComfyVideoClient.upload_image_bytes`，与参考图同 subfolder）并把返回 `imageFile` 注入任务首镜 `anchor_image_file`、同步 `strip_picture_tags` 清掉 `<Picture n>` 悬空引用；失败降级为无锚定补跑（payload `anchor_warning`），不推翻任务。`ComfyVideoClient.build_timeline` 发现段带 `anchor_image_file` 时将该段 `taskType` 覆盖为 `fl2v — 首尾帧生视频(First-Last Frame)` 并写 `startImage.imageFile`——远端 MiniMaxH3Director 节点对 prompt_batch 时间线支持段级 taskType 覆盖（`_resolve_segment_task`），fl2v 段按官方 ImageToVideo 路径严格锁定首帧（B0 spike 实测：输出第 0 帧与锚定帧平均像素差 0.0217；fl2v 段不携带参考图，外观由锚定帧承载，结论存计划文档第 4.3 节）。
- 当前基线（B3 合并与并发）：`_publish_timeline_result` 发现 payload `anchor_prefix_urls` 时下载前缀已有成片字节，`_merge_chunk_videos(prefix_clips=…)` 前置参与 `ffmpeg_concat`，任一前缀下载失败直接失败任务（禁止拼出缺前缀的假整集）；assembly 记录 `prefix_clips` 数。并发口径不变：`_assert_can_enqueue` 未改动，disjoint 区间的多个 gap_fill selection 任务可同时排队（GPU 由 `occupy_gpu` 串行），episode/compose 运行中仍阻断一切补跑。
- 前端：`director2-video-settings.ts` 新增 `computeEpisodeGapSegments/computeEpisodeContinuePrefix/formatEpisodeGapConfirmText`，`formatEpisodeVideoSubmitMessage` 增加 gap_fill/continue 分支；`EpisodeWorkshopPane` 在「生成全片段视频」前插入三选一确认弹窗（整集重渲 / 只补跑未生成镜头（推荐）/ 从第 k+1 镜续写整集（推荐，前缀场景替换补跑推荐项）），全无/全有不成对弹窗，「整集重渲」维持原直提行为；`workshop-video-progress.ts` 把运行中的 gap_fill selection 任务映射为顶部横幅 `整集补跑中 · …`（`gapSegment` 显示区间位置），镜头卡逐镜回显沿用既有 stampShotBeats；`job_payload._JOB_LIST_KEYS` 白名单补 `strategy/gap_fill/segment_index/segment_total/segment_count/anchor_beat_id/anchor_sequence/anchor_prefix_urls/anchor_warning`。MCP `studio_generate_episode_video` 新增 `strategy` 参数透传（勾选 beat_ids 时忽略）。
- 受影响文件：`backend/app/media_studio/services/{episode_video_service,comfy_video_client,job_payload}.py`、`backend/app/mcp_gateway/{routes,director_service}.py`、`backend/tests/test_episode_gap_fill.py`（新增 34 项）；`frontend/src/director2/{director2-video-settings,workshop-video-progress}.ts(.test.ts)`、`frontend/src/director2/panes/EpisodeWorkshopPane.tsx`；`docs/整集直出智能补跑开发计划.md`（spike 结论与进度表）。
- 兼容性：无新表/新列；`ai_project_jobs.payload_json` 只增可选键，旧任务 payload 无这些键时全部走现有分支；逐镜模式、勾选 selection、compose、一采二采、超清、`previous_chunks` 组级重试缓存语义均未改动；不新增工作流节点 ID（复用整集 timeline graph + 段级 taskType）；不新增第二套 ComfyUI，锚定帧走 `upload_image` 既有通道。锚定如实表述：fl2v 为严格首帧锁，但区间边界音频仍是独立生成。
- 验证：`python -m pytest backend/tests -q`（1685 passed + `media_studio_test_h3_video.py` 165 passed + `test_episode_gap_fill.py` 34 passed）；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend build` 通过，vitest 全量 118 文件 802 项通过；桌面端 5173 Playwright 自查 18/18（真实项目 proj-178e268edeea4680 前缀场景推荐续写、mock 交错场景推荐区间补跑、全部已出片仅整集重渲、取消不提交、补跑横幅文案；generate-video 全程拦截未产生真实 GPU 任务）。B0 远端冒烟：192.168.10.54:8188 2 段锚定时间线出片 112 帧，首帧锁定成立。
- 回滚：前端撤回弹窗与 strategy 提交即恢复「整集永远全渲」直提；后端入口对未知 strategy 拒绝即可切断新路径；payload 无迁移，已建任务（含锚定段）不受影响；`create_job` 三个新参数与 `_merge_chunk_videos` 新关键字参数默认关闭，逐文件还原上述 diff 即回到 2026-11-05 前行为。

## 2026-11-05 LLM 换端点前先把旧凭据回填 vault（修 2026-11-01 vault 档案的一个丢 Key 坑）

- 变更原因：`llm_provider.update()` 引入按服务保存 Key 的档案表后，仍存在一条漏路径——旧端点仅存在于主配置 `api_key_encrypted` 而从未进档案（升级前的历史配置，或用户直接在数据库里落盘的密文），换到新端点时主配置密文被覆盖，旧 Key 就此丢失。今天为避开阿里云 qwen 内容审核把 shot-plan 切到 InternAI `deepseek-v4-flash-0731` 时踩到该坑： vault 有 InternAI 档案，`elif changed_endpoint` 分支直接把 InternAI 密文写回主配置，旧阿里云 Key 无法通过 vault 找回，回滚时必须重新粘贴 `sk-...R0`。用户 2026-11-05 明确要求「把回填的坑修掉」。
- 当前基线：`backend/app/llm_provider.py::LlmProviderService.update()` 在 `changed_endpoint` 计算完成后、任何会覆盖 `api_key_encrypted` 的分支执行前，插入一段守卫——若旧端点 `previous_base_url` 非本机、主配置带密文、且档案表尚无该端点，则先 `upsert_llm_endpoint_credential(previous_base_url, previous["api_key_encrypted"], previous.model)` 补档。同端点保存不触发；首次配置（`previous_base_url` 空）不触发；本机端点无需 Key 不触发。三条会被覆盖的子路径都受保护：①带新 Key 切走并 upsert 新端点、②不提交 Key 但新端点已在档案（`stored` 命中）、③切到本机导致清空。后续若 `elif changed_endpoint` 抛 `ValueError`（新端点无档案且未提交 Key），主配置 UPDATE 不执行，但补档已生效——档案表本就与激活配置解耦，下次切换自动带上即可。
- 受影响文件：`backend/app/llm_provider.py`（`update()` 新增 6 行守卫 + `previous_base_url` 局部变量）、`backend/tests/test_llm_endpoint_credentials.py`（新增 3 个回归用例覆盖三条子路径）、`docs/ARCHITECTURE.md`、`docs/导演台流程与界面结构.md`（把 11-05 条目里的「已知坑」段落改为已修）。
- 兼容性：无接口/表/依赖变更；`PUT /api/admin/providers/llm` 请求与响应字段完全不变。VLM 设置页继续沿用「切端点即清 Key」的既有独立设计，不共用 vault，也不受本次影响。历史数据升级路径不变：同端点重存仍会走 `elif previous.get("api_key_encrypted")` 回填分支。
- 验证：`python -m pytest backend/tests/test_llm_endpoint_credentials.py -v`（11/11 通过，含 3 个新用例：`test_switch_away_with_key_backfills_missing_previous_endpoint` / `test_adopting_vault_key_on_switch_backfills_previous_endpoint` / `test_switch_to_local_backfills_previous_remote_endpoint`）；`python -m pytest backend/tests -q`（1629 passed / 1 skipped）。今天已把 LLM 切到 InternAI `deepseek-v4-flash-0731`，补跑 proj-055492fd2d34406b 的 shot-plan 得 11 镜并同步至工坊，实跑链路无回归。
- 回滚：删除 `update()` 内新增的 `previous_base_url` 变量与补档 if 块即可回到旧行为；测试文件的新增用例可撤回，其余既有测试保持通过。数据库无迁移。

## 2026-11-04 新增独立工具卡「视频换人」（前端注册表 + MotionTransferTool 锁定入口）

- **变更原因**：用户反馈「动作迁移」名称无法覆盖多人参考视频版换人能力，要求单独立卡；行业通用命名调研后定为「视频换人」（对齐阿里万相同名能力，最通用）。
- **当前基线（前端）**：新增工具卡 `character-replace`（`/tools/character-replace`，category=camera，status=available，icon 键 `Users`），在 `frontend/src/tools/tool-registry.ts` 注册、`paths.ts` 增加 `toolCharacterReplace` 并入 `STUDIO_ROUTE_PATHS`、`tool-icons.ts` 增加映射、`ToolsWorkspace.tsx` 路由渲染接入。页面复用 `MotionTransferTool`：新增两个可选 props —— `lockedWorkflow`（锁定单一迁移方式：mode 初值强制为该工作流、隐藏「迁移方式」下拉、工作流查询只拉该一条且 queryKey 追加后缀以隔离缓存）与 `copy`（覆盖 hero 标题/副标题与提交成功文案）。不传这两个 props 时组件行为与旧「动作迁移」完全一致（默认仍为三方式入口）。
- **后端/工作流**：完全复用既有 `minimax-h3-motion-ref-video`（`_run_motion_ref_video` + 润色改写层），无新接口、无 graph 变更、无数据库、无 ComfyUI 节点或模型路径变更。
- **兼容性**：历史任务、原动作迁移入口、再次生成/重新编辑回带逻辑均不变；新卡只是同一工作流的独立入口。工具卡已内置本次验证任务的左右对比示例（`tool-demos/character-replace.mp4`：左元华原片 / 右换上女主，1718×480、5 秒、静音循环，首次进入自动弹出）与专属封面（`character-replace.jpg` 取自换人帧）。该示例由任务 `MrcY7SVt1PxA` 的原片参考（`2_yuanhua_stairs_5s.mp4`）与成片左右拼接生成；封面为成片帧（960×540）。注册表 `demo` 字段驱动 `ToolDemoGate` 首次进入自动弹框。
- **验证**：`pnpm --dir frontend exec tsc -b` 通过；`pnpm --dir frontend test` 117 文件 / 776 项通过（新增 `tools.test.ts` 注册表断言与 `motion-transfer-tool.test.tsx` 锁定入口组件用例）。5173 桌面端实测卡片渲染与提交；元华下楼梯 5 秒翻滚片段 + 女主形象图、16:9 标准档任务 `MrcY7SVt1PxA` 出片，1s/2.5s/4s 三帧人物稳定替换、楼梯场景与运镜保留。
- **回滚**：撤回前端四处增量与 `MotionTransferTool` 的可选 props（默认不改变原行为），删除 `character-replace.jpg`；保留既有工作流、动作迁移入口与历史任务，无后端回滚。

## 2026-11-04 多人参考视频版自动 caption + 润色改写主语句 + DMAD 快速预览档

- 变更原因：`minimax-h3-motion-ref-video` 换人要求用户在描述段手写"中文外观主语紧贴动作"（成功样本 xbzyTzeDkK6S），不写长相就不换人。官方 Aiden 模板靠图内 ImageCaptionNode 自动化此步，但远端 ComfyUI 未安装该节点（/object_info NOT FOUND），故改为后端建图前 bake 方案。实测四代注入：v1 caption 只进绑定段、v2 描述段加"见上方 visual profile"间接消歧句、v3 英文 caption 内嵌描述段首句主语定义句，三组标准/预览档出片均不换人（QH6w76mxpYTj/BQtFNjs2346/F2PjgUwdXo5x，各抽 3 帧目视）；结论：模型不做跨段引用推理、不认长英文 caption 主语句，只认中文外观主语紧贴动作。最终采用润色改写层，实测标准档 ycKTeRtzG1f3 与 preview 档 AfcIzTKtRALJ 抽帧全部换人成功。
- 当前基线（caption）：`comfy_service._describe_motion_ref_characters` 自选视觉端点（仅 row 探针字段 `vision_capability=='supported'` 或 `model_supports_vision` 命中，不走全局 authoring 路由——免费 VLM qiniu/conatus-free 实测收不到图且 429），角色图 PIL 缩至长边 1024 JPEG q88 转 data URL（原图 base64 ~2MB 会撞 qwen3.7-flash 输入上限 983616），产出 40-80 字中文外观短语；英文占比 >0.6 视为答非所问丢弃，连续 2 张失败放弃余下角色补空串。
- 当前基线（润色改写）：`comfy_service._inject_appearance_into_prompt` 用 `complete_authoring`（MOTION_REF_POLISH_SYSTEM）把用户提示词+外观短语改写为描述段首句中文外观主语句；改写失败、产出可疑（含 subject_definitions/<picture/<video/character 1 模板标记、长度不足原文 50%、几乎无中文）或无 caption 时原样返回用户提示词降级，绝不阻断建任务；取消信号照常抛 ComfyCancelled。`compose_motion_ref_video_prompt` 描述段恢复纯透传，caption 仅保留在绑定段 `Visual profile of Character n` 作辅助锚定。
- 当前基线（preview 档）：builder 新增节点 "91" `LoraLoaderModelOnly`（`minimaxh3_turbo\minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors` @1.0，接节点 9 之后），turbo=True 时 Guider "50"/Scheduler "53" 改接 ["91",0]、"52" sampler 改 euler；`render_quality=preview` 映射 steps=8 + turbo，对齐官方 Aiden 模板主采样；standard/fine 不挂。实测 preview 出片 ~4.5 分钟 vs 标准 ~7.5 分钟，换人不衰减。
- 受影响文件：`backend/app/h3_motion_ref_video_workflow.py`（builder 签名 +character_captions/turbo、compose 回退纯透传）、`backend/app/comfy_service.py`（MOTION_REF_CAPTION_SYSTEM/MOTION_REF_POLISH_SYSTEM、_caption_image_data_url、_describe_motion_ref_characters、_inject_appearance_into_prompt、_run_motion_ref_video 接线）、`backend/app/workflow_registry.py`（preview 档位描述）、`backend/tests/test_h3_motion_ref_video.py`（30 项）。
- 兼容性：无数据库、接口、节点 ID 迁移；专家透传规则不变；历史任务回显不受影响，重跑按新链路（caption+润色+档位）执行；视觉/大模型配置缺失时全链路静默退化回旧行为。
- 验证：`python -m pytest backend/tests/test_h3_motion_ref_video.py -q` 30 passed；全量后端回归通过；任务 ycKTeRtzG1f3/AfcIzTKtRALJ 经远端 /api/queue 核验实际 graph（中文主语句已 bake、preview 含节点 91），成片各抽 3 帧目视验收换人生效。
- 回滚：还原上述四个后端文件即可（compose 恢复无 caption 辅助、builder 删节点 91 与 turbo 分支、comfy_service 删 caption/润色 helper 与接线）；远端 DMAD LoRA 文件仅 preview 档引用，可保留。

## 2026-11-04 导演台项目按账号隔离（ai_projects.owner_user_id）

- 变更原因：导演台「我的短剧」原先直接按 `updated_at` 列出整张 `ai_projects`，表内没有归属列，换账号后能看到并打开其他账号的工程，跨账号还能直接访问 `/api/projects/{id}/...` 子资源。本次补齐工程归属并同时收口列表、详情与创建链路。
- 数据与迁移：`sql/013_media_studio_init.sql` 的 `ai_projects` 增加 `owner_user_id VARCHAR(64) NULL` 与 `idx_ai_projects_owner_updated (owner_user_id, updated_at)`；`media_studio/db.py` 的 `ensure_schema()` 新增 `_ensure_project_owner`，用 `ensure_column` / `ensure_index` 幂等给已有 MySQL 库补列补索引，并把历史 `owner_user_id IS NULL` 的工程一次性归给最早创建的活跃超级管理员（与 `assign_unowned` 同一先例）。不写一次性 ALTER，新库由建表语句直接带列。
- 服务层：`ProjectService.list_projects(owner_user_id)` 按归属过滤；`ProjectService.create_project(payload, owner_user_id=...)` 写入归属；新增 `ProjectService.allows_user(project_id, owner_user_id)`（不存在返回 False，历史空归属仍放行以兼容旧数据/测试）。`ProjectItem.owner_user_id` 仅服务端使用，`Field(exclude=True)` 不序列化到响应。
- REST：`register_project_routes` 注册纯 ASGI 的 `ProjectAccessMiddleware`，对匹配 `^/api/projects/([^/]+)(?:/|$)` 的请求读取会话 Cookie 并校验归属，跨账号与不存在统一返回 404 `{"detail":"项目不存在"}`；没有 `app.state.auth_store` 的测试环境自动放行。`GET /api/projects` 传当前用户、`POST /api/projects` 写入当前用户。
- MCP：`DirectorService.projects/create_project` 与 `EditingService.projects/prepare_episode` 全部改为接收当前授权用户，列表按 owner 过滤、创建写入 owner；`routes.py` 四处工具调用同步传 `user`，server instructions 从「与工作台共享工作区」改为「按账号隔离」。
- 受影响文件：`sql/013_media_studio_init.sql`、`backend/app/media_studio/{db.py,models.py}`、`backend/app/media_studio/services/project_service.py`、`backend/app/media_studio/routers/project_router.py`、`backend/app/main.py`、`backend/app/mcp_gateway/{director_service.py,editing_service.py,routes.py}`、`backend/tests/test_project_ownership.py`（新增）、`backend/tests/test_director_project_info.py`、`backend/tests/test_local_drama_mcp.py`，以及 `docs/API.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：无端口、工作流、节点 ID 或任务队列改动；历史工程迁移后归最早超管，其他账号需要新建自己的工程。未登录请求仍由原有路由鉴权拒绝，中间件只做归属校验。`studio_list_projects` 与 `studio_list_edit_projects` 的工具签名不变，只是结果范围收窄。
- 验证：`python -m pytest backend/tests/test_project_ownership.py backend/tests/test_director_project_info.py backend/tests/test_local_drama_mcp.py -q`（21 项通过）；`python -m pytest backend/tests -q` 全量回归（1604 passed / 1 skipped）。真实接口以 zlyadmin 登录创建临时工程，确认 `owner_user_id` 写入当前账号；把该临时工程归属改为其他账号后，`GET /api/projects` 不再返回（仍 36 条），直接访问返回 404 `{"detail":"项目不存在"}`，本人工程的子资源仍 200；验证后已删除临时工程。
- 回滚：还原上述源文件与测试，并删除 `owner_user_id` 列与索引；保留归属列不影响旧代码读取。

## 2026-11-04 角色替换（换头修脸）下线 + 多人参考视频版换人修复（character_swap LoRA + ref_image_size=max）

- 变更原因：①换头修脸实测确认模板语义是"整段重生成→贴脸"，遮脸/多人帧残影明显，从入口下线；②多人参考视频版（`minimax-h3-motion-ref-video`）换人不生效，对照远端官方 Aiden 多人模板（`D:\动作迁移`）排查：builder 精简 graph 缺专用 LoRA（模板 LoRA 文件在 `D:\ComfyUI-Models\各种功能LORA`，`extra_model_paths.yaml` 仅映射 `loras: lightx2v` 故 ComfyUI 不可见），叠加 `ref_image_size="match"` 缩图毁身份、提示词误触发透传分支跳过绑定模板、提示词主语锚回原片人物四层问题。
- 当前基线：`h3_motion_ref_video_workflow.py` 新增节点 9 `LoraLoaderModelOnly`（`minimaxh3-other\minimax_h3_character_swap_v1.1_ref2va_fro.safetensors` @1.0，Guider 50/Scheduler 53 改接 9），`ref_image_size` 固定 `"max"`；不挂 DMAD 4-step（本链路 20 步）。提示词约束：用户描述不得含 `<picture`/`<video 1`/`subject_definitions` 子串（否则跳过绑定模板透传），主语须为图片角色。face-swap：后端 `hidden_from_catalog=True`（runner/历史保留），前端工具卡 `status: "coming_soon"`。
- 远端变更：复制 character_swap_v1.1_ref2va_fro 与 DMAD_4step 两文件到 `D:\ComfyUI-Models\lightx2v\{minimaxh3-other, minimaxh3_turbo}\`（原文件未动）；ComfyUI 可见 LoRA 10→12。
- 受影响文件：`backend/app/h3_motion_ref_video_workflow.py`（本轮）；`backend/app/workflow_registry.py`、`frontend/src/tools/tool-registry.ts`（face-swap 下线，前一轮已落代码本次补档）。
- 兼容性：无数据库、API、前端交互改动；旧任务重跑按新 graph 执行。验证：`pytest backend/tests -k motion` 49 过；任务 `xbzyTzeDkK6S` 经远端 `/queue` 核验 graph 后抽帧验收换人生效（原片中央人物完整替换为参考图角色，动作/道具/背景/队友保留）。回滚：还原 builder（删节点 9、model 改回 8、`ref_image_size` 回 match）；face-swap 恢复只需改回两个注册开关。

## 2026-11-04 `/mcp` 下线创作素材库区块、`studio_import_reference` 支持 base64 传图、平台胶囊换真实品牌 logo

- 变更原因：MCP 已具备完整传图通道（在线图用 url，本地图片转 base64 直传），`/mcp` 页的「创作素材库（MCP 参考图）」区块不再是参考图唯一入口，整块下线；页面前端不再提供上传/画廊/删除/复制 ID 交互。
- 参考图能力保留在后端：REST `/api/mcp/references*` 与 MCP 工具 `studio_list_reference_assets`/`studio_import_reference` 不变；工具新增 `image_base64` 参数（与 `url` 二选一，允许 `data:` 前缀，≤ 50 MB，非法编码 422），`service.py` 新增 `import_reference_from_base64` 与统一分发入口 `import_reference`（复用 `save_reference` 的 PIL 格式校验）；工具总数仍为 44。
- 平台图标：新增 `frontend/src/mcp/client-logos.tsx`，五个胶囊换为真实品牌内联 SVG（Codex、OpenAI、Claude 官方星芒 #D97757、Cursor、MCP 徽记；数据源 Simple Icons/LobeHub Icons），默认 `currentColor` 适配双主题，未新增 npm 依赖；`McpPage.tsx` 移除素材库 section、作品画廊 Modal 及 `McpReference`/`GeneratedImage` 类型，`mcp.css` 清理对应样式。
- 受影响文件：`frontend/src/mcp/{McpPage.tsx,mcp-client.ts,mcp.css,client-logos.tsx}`、`backend/app/mcp_gateway/{service.py,routes.py}`、`backend/tests/test_mcp_gateway.py`（新增 base64 校验/分发用例，42 通过）。
- 兼容性与回滚：已入库参考图与历史任务不受影响，Agent 侧仅参数扩展向后兼容；回滚还原上述文件即可。

## 2026-11-04 MCP 连接页多平台引导改版 + 新增 `studio_import_reference` 工具

- 变更原因：用户要求参考 WorkRally 连接页把 `/mcp` 的接入引导做得更全面，且每个平台的步骤文案有差异；同时澄清「参考图」区块的定位——MCP 工具参数是 LLM 生成的 JSON 文本，聊天里附的本地图片字节无法直接传入工具，因此需要带外素材库 + ID 引用；为减少传统上传依赖，新增由 Agent 直接拉取在线图片入库的 MCP 工具。
- 前端多平台引导：`frontend/src/mcp/mcp-client.ts` 新增 `McpClient = codex|chatgpt|claude|cursor|generic`、`CLIENT_ORDER` 与 `CLIENT_GUIDES`（每平台 step1/step2 标题、说明、配置形态 command|json|instruction、复制按钮文案、step2 动作 copy-prompt|link）；`connectionConfig` 统一输出带 `"type": "http"` 的 `mcpServers.zly-ai-studio` JSON（codex 为 CLI 命令，generic 为含 JSON 的自然语言安装指令）；Claude 的 step2 提供外链按钮直达 `https://claude.ai/customize/connectors`。`McpPage.tsx` 把 antd Tabs 换成 WorkRally 式胶囊切换行（`.mcp-clients`/`.mcp-client-chip`，role=tablist，双主题用 `--studio-*` 变量），步骤区改为 guide 驱动，代码块下新增主复制按钮（`.mcp-step-actions`）。
- 参考图区块定位重写：标题改为「创作素材库（MCP 参考图）」，说明写清「AI 客户端只能从这个库读取，本地图片需先上传/选取，`<Picture n>` 顺序由 AI 提交时的引用顺序决定」；删除选中→排序→复制引用顺序的伪交互（`selectedIds`、`mcp-reference-order`、`moveReference`、`referenceInstruction` 一并移除），保留上传、从我的作品导入、删除、复制素材 ID。
- 后端新工具：`mcp_gateway/routes.py` 注册 `studio_import_reference(url, name?)`（scope `studio:generate`，openWorldHint=True，MCP 工具总数 43→44）；`mcp_gateway/service.py` 新增 `CreativeService.import_reference_from_url`：`_safe_image_target` 校验 scheme 限 http/https、拒绝凭据、`socket.getaddrinfo` 解析后拒绝私网/回环/链路本地/保留/组播地址（含 IPv4-mapped IPv6），逐跳手动跟随重定向（≤3 次、每跳重新校验），流式下载上限 50 MB，最终复用 `save_reference` 做 PIL 格式校验与入库；下载通过 `asyncio.to_thread` 避免阻塞事件循环。`studio_list_reference_assets` 描述同步更新，引导 Agent 先查库、缺图时用 URL 导入。
- 附带修复：`media_studio/routers/featured_router.py` 两处 `featured_id` 路径参数补 `Path(description=...)`，恢复 `test_core.ApiDocumentationTests` 中文文档断言（该缺失由同工作区在途改动引入）。
- 受影响文件：`frontend/src/mcp/{mcp-client.ts,mcp-client.test.ts,McpPage.tsx,mcp.css}`；`backend/app/mcp_gateway/{service,routes}.py`、`backend/tests/test_mcp_gateway.py`、`backend/app/media_studio/routers/featured_router.py`；本快照与 `功能说明与扩展指南.md` 同日章节。
- 兼容性：旧 MCP 客户端无需重新授权，重新发现工具即可拿到新工具与描述；REST `/api/mcp/*` 会话接口不变；页面无路由/端口/表结构变更；`referenceInstruction`/`moveReference` 仅前端内部函数，无外部引用。
- 验证：`python -m pytest backend/tests/test_mcp_gateway.py -q`（39 通过，含新增 `McpReferenceUrlGuardTests` SSRF 用例与 44 工具发现断言）；`pnpm --dir frontend exec tsc -b` 通过；前端全量 vitest 中 `tool-demo.test.tsx` 失败为其它会话在途 `tool-registry.ts` 改动所致，与本次无关；5173 桌面端以登录态逐平台点击自查胶囊切换、各平台差异文案、Claude 外链、素材库新区块文案与空态，暗色主题正常。
- 回滚方式：还原上述文件即可；新工具移除后旧引用它的 Agent 会得到 tools/list 中不存在该工具的提示，不影响既有创作链路。

## 2026-11-04 导演台首页「精选作品」只读展示位（管理员发布 + 全员可见）

- 变更原因：导演台首页只有「我的短剧」，管理员缺少面向全体成员的展示位；而 `ai_projects` 按 `owner_user_id` 隔离且没有公开只读模型，直接共享工程会让其他成员看到甚至改动原工程。改为独立展示表 + 冻结快照：发布时把当前项目、文档、分集、分镜与资产复制为只读快照，普通成员只读，不影响原工程。本轮只做只读版本，不含「复制到我的短剧」；后续要加复制时另走新工程克隆链路。
- 数据：`sql/021_featured_works.sql` 新增 `ai_featured_works`（`id` / `project_id` 唯一 / `title` / `summary` / `cover_url` / `snapshot_json` / `episode_count` / `shot_count` / `sort_order` / `status` / `published_by` / `published_at` / `updated_at`）。表内只保存已发布行（下架即删除），`status` 固定 `published`，列表按 `sort_order ASC, published_at DESC`。`storage.py` 同步 SQLite 建表，单元测试走临时 SQLite。若线上库尚未建表，启动时 `mysql_schema_sql()` 回放 `sql/` 会自动创建。
- 快照服务：`media_studio/services/featured_works_service.py` 的 `build_featured_snapshot` 只保留展示字段——项目 id/name/description/cover；文档 filename/raw_text（正文截断 20 万字符）；分集 id/number/title/status/script_text/summary/episode_video_url/beats；资产 kind/name/role/description/image_url。媒体地址仅接受 `http(s)://` 或 `/` 开头且 ≤2048 字符，非法值置空；分镜只保留 heading/speaker/dialogue/action/camera/scene/time_of_day，图片取 `render_url`→`sketch_url`→`triptych_url`，视频取 `video_url`→`upscaled_video_url`，时长取整，整条全空的分镜丢弃。封面回退顺序：项目 cover → 角色 → 场景 → 道具 → 首个分镜图。发布要求项目存在，且至少有一份文档正文或分集正文/分镜；同项目重复发布执行 UPDATE 并保留首次 `published_at`；`sort_order` 夹在 0–999。
- 接口：`GET /api/featured-works`（登录用户）返回已发布列表，不含 `snapshot_json`；`GET /api/featured-works/{featured_id}`（登录用户）返回只读详情（含 `snapshot`，404 表示不存在或已下架）；`POST /api/admin/featured-works`（`mutating_admin_user`）按 `project_id` 发布或更新；`DELETE /api/admin/featured-works/{featured_id}`（`mutating_admin_user`）下架。路由在 `main.py` 通过 `register_featured_work_routes` 注册；管理员判定沿用现有角色体系（`super_admin` / `admin`），员工只读。
- 前端首页：`Director2StudioHome` 在「我的短剧」下方新增「精选作品」区块。非管理员只在有已发布作品时显示；管理员始终显示（空态文案「管理员发布后全员可见」）。卡片展示封面、「精选」角标、标题、简介、集数与镜头数、发布日期；管理员在项目卡菜单增加「发布为精选 / 更新精选」，弹层可改标题、一句话简介、封面地址与排序（0–999，越小越前），并明确提示发布会把当前剧本、分集和角色场景冻结成只读快照；精选卡悬停右上角「更多」可「取消精选」（确认后仅下架展示位，短剧本身不受影响）。发布、更新、下架后刷新 `["director-featured-works"]`。
- 只读详情页：`/director/featured/:featuredId`（`FeaturedWorkPage`）——hero 封面 + 「ZLY 精选作品」+ 标题/简介/集数/镜头数/发布日期；Tabs「分集 / 剧本 / 角色与场景」；点分集卡从右侧 Drawer 播放本集成片，并列本集剧本与分镜（分镜媒体优先视频、其次图片）。页面无编辑、无复制、无工程入口。路由必须同时登记在 `frontend/src/paths.ts` 的 `ROUTE_PATTERNS.directorFeatured` 与 `STUDIO_ROUTE_PATHS`，否则会命中 catch-all 跳回生成页；`director2/paths.ts` 增加 `kind: "featured"` 解析，`Director2App` 有独立渲染分支。
- 受影响文件：`sql/021_featured_works.sql`、`backend/app/{storage,main}.py`、`backend/app/media_studio/services/featured_works_service.py`、`backend/app/media_studio/routers/featured_router.py`、`backend/tests/test_featured_works.py`；`frontend/src/{App.tsx,paths.ts,paths.test.ts}`、`frontend/src/director2/{api.ts,paths.ts,paths.test.ts,Director2App.tsx,Director2StudioHome.tsx,FeaturedWorkPage.tsx,director-home.css,director-featured.css}`；本快照、`README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md`、`docs/API.md`、`.gitignore`（新增 `!docs/design-ref-director/featured-20261104/` 放行参考截图）。
- 兼容性：全新表与接口，不改 `ai_projects` 及既有工程、任务、工作流与 ComfyUI 链路；快照发布后与原项目解耦，后续修改项目不影响已发布内容，需要同步时再次发布；删除快照行即下架；无端口、供应商、节点 ID 变化；明确不含复制功能。
- 验证：`python -X utf8 -B -m unittest backend.tests.test_featured_works -q`（9 项通过）；`npx tsc -b` 通过；`npx vitest run src/paths.test.ts src/director2/paths.test.ts`（17 项通过）；5173 桌面端以 `zlyadmin` 实测发布《闪婚蜜爱》为 `featured-edb63d1db19f4bf3`（4 集 / 44 镜头 / 28 项资产），首页精选卡、只读详情页、分集 Drawer 与浅暗双主题均正常，员工只读视图未单独造号验证。全量 `pnpm --dir frontend build` 因同工作区其他改动导致 `tool-demo.test.tsx` 失败，与本功能无关；已用 `npx vite build` 验证生产包可构建。
- 回滚方式：还原上述文件并删除 `sql/021_featured_works.sql`；线上库如需彻底回滚执行 `DROP TABLE ai_featured_works`（只影响精选展示，不影响短剧工程与任务）。

## 2026-11-06 精选作品升级为即梦式三段体验（成片预览 → 只读创作过程画布 → 复制项目）

- 变更原因：精选作品此前只是"剧本的另一种展示形式"（图文详情页），参考即梦精选短剧的浏览动线，升级为：点精选卡直接弹出成片预览播放器 → 右下「查看创作过程」进入只读画布（可查看视频生成提示词，不可编辑）→「复制项目」把快照复制成自己的短剧后才能编辑。原图文详情页保留为二级入口。
- 快照 v2（`build_featured_snapshot` 版本号 2）：beat 新增 `prompt`（取 `h3_prompt` → `video_prompt_zh` → `visual_prompt`，截断 4000 字符），资产新增 `id` 与 `visual_prompt`；发布时额外读取源项目绑定画布（`canvas_projects.linked_director_project_id` → `canvas_drafts.content`，画布为空则省略），把整份 `{nodes, edges, viewport}` 冻结进 `snapshot_json.canvas`。旧 v1 快照无这些字段，前端全部按缺省兜底。
- 新接口：`POST /api/featured-works/{featured_id}/copy`（登录用户）。`FeaturedWorksService.copy_to_user` 从快照还原一份新工程：`ai_projects`（名称＝"标题（副本）"，owner＝当前用户）→ 剧本文档（`ai_project_documents`，input_mode=paste）→ 分集（`ai_project_episodes`，status=script_ready，`data_json` 由展示 beat 反向映射回存储结构：`image_url→render_url`、`prompt→h3_prompt`、`duration→video_duration`，并保留 summary 与 episode_video_url）→ 资产（`ai_project_assets`，含 visual_prompt）→ 绑定画布（`CanvasStore.get_or_create_linked` + `save_draft`，画布资产投影节点的 `assetId` 重映射为新资产 ID；画布复制失败不阻塞项目复制）。返回 `{project_id, name, episode_count, shot_count, asset_count}`。`main.py` 以惰性 getter `lambda: app.state.canvas_store` 传入路由（canvas_store 在 lifespan 里才挂到 app.state，模块导入期直接取值会 KeyError）。
- 前端路由：`/director/featured/:featuredId/process` → `director2/paths.ts` 新增 `kind: "featured-process"`；`frontend/src/paths.ts` 的 `ROUTE_PATTERNS.directorFeaturedProcess` 必须同时登记进 `STUDIO_ROUTE_PATHS`，否则命中 catch-all 跳回生成页（本次实测踩过）。
- 首页动线（`Director2StudioHome`）：精选卡点击从跳详情页改为本页内弹出 `FeaturedWorkPreview` 全屏成片预览——近黑媒体舞台、视频自动静音播放、底部标题 + "内容由 AI 生成" + 分集切换胶囊（多集且有片源时）、右下「图文详情」（原详情页）与「查看创作过程」（进过程页）双按钮；Esc/返回键关闭，锁定 body 滚动。无成片时用封面图 + 提示文案兜底。
- 只读创作过程页（`FeaturedProcessPage`，`director-featured-process.css`）：顶栏＝返回详情、标题 + 副标（创作过程 · 完整创作画布/资产与分镜创作流程/分镜创作流程）、"当前为只读模式，如需创作请点击"、主按钮「复制项目」（成功后 message 提示并跳转新工程内容库）、X 回导演台首页。画布用 `@xyflow/react` 只读渲染（`nodesDraggable/nodesConnectable/elementsSelectable/edgesFocusable/edgesReconnectable` 全关，zoom 双击关，`deleteKeyCode=null`）：快照有 `canvas` 时归一化渲染真实画布（`normalizeRealCanvas` 同时兼容资产画布草稿 `kind` 方言与无限画布 `type` 方言；资产投影节点经 `assetById` 解析媒体，generator/editor 归一为提示词节点），无画布时用 `synthesizeProcessGraph` 从快照合成创作流程（资产行 + 每集一行「提示词→分镜图→成片镜头」链，镜头缺提示词时用动作+对白兜底，视频节点用分镜图当封面）。自定义节点必须内嵌隐形 `Handle`（`.fpc-handle` opacity:0），否则 React Flow 报 `Couldn't create edge #008` 且连线不渲染。点击带 prompt 的节点弹只读提示词面板（参考图缩略取入边上游媒体、提示词全文可选中、参数行 = workflowId + optionValues + 机位、「复制提示词」走剪贴板降级 execCommand）；点图片/视频/资产/分集节点开媒体灯箱；左下缩放条（百分比/放大/缩小/适应画布）。视觉全部走 `--studio-*` 双主题变量，媒体帧保持近黑。
- 详情页动线（`FeaturedWorkPage`）：hero 下新增操作行——「查看成片」（本页内弹出同一个 `FeaturedWorkPreview`）、「查看创作过程」、「复制项目」。
- 受影响文件：`backend/app/media_studio/services/featured_works_service.py`、`backend/app/media_studio/routers/featured_router.py`、`backend/app/main.py`、`backend/tests/test_featured_works.py`；`frontend/src/paths.ts`、`frontend/src/director2/{api.ts,paths.ts,Director2App.tsx,Director2StudioHome.tsx,FeaturedWorkPage.tsx,FeaturedWorkPreview.tsx(新),FeaturedProcessPage.tsx(新),director-featured.css,director-featured-process.css(新),featured-process-graph.test.ts(新)}`。
- 兼容性：v1 快照照常展示（过程页自动走合成视图，无 prompt 的镜头用剧本信息兜底）；复制出的工程与手工新建工程同构，工坊/资产库/剪辑按现有链路继续用；发布重复执行 UPDATE 语义不变；媒体仍是七牛 URL 引用，不复制文件。接口、表结构、端口、工作流协议均无破坏性变更。
- 验证：`python -m unittest backend.tests.test_featured_works`（14 项通过，含快照 v2 字段、画布捕获、复制服务与 assetId 重映射断言）；后端全量 `unittest discover`（1707 通过 / 1 skipped）；`pnpm --dir frontend build`（824 测试 + tsc + vite build 全过）；5173 桌面端 Playwright 实测（zlyadmin 会话注入）：首页精选卡 → 预览弹层 → 查看创作过程（80 节点合成画布）→ 提示词面板 → 复制项目跳转新工程内容库 → 删除副本清理，浅暗主题截图留存 `test-results/featured-ui/`。
- 回滚方式：还原上述文件即可；v2 快照字段为纯增量，旧前端/旧后端读到多出的 `prompt`/`canvas` 字段会忽略；copy 接口删除即下线该入口；复制产生的副本工程直接删除，不影响原工程与精选快照。

## 2026-11-04 图片编辑结果的「原图对比」契约（`result_compare`）与透明棋盘格

- 变更原因：去背景 / 局部重绘 / 消除笔这类「改一张已有的图」的任务，结果面板只放结果图，用户看不出改了什么；同时透明产物压在近黑底（`--studio-media`）上会被误读成「没出图」。对比策略必须写在后端注册表，不能在前端按 mode id 硬编码。
- 契约：`WorkflowDefinition` 新增 `result_compare: str = "none"`（`"overlay"`=结果可与原图逐像素叠层对比），随 `payload()` / `public_payload()` 自动透出；`models.ModeResponse` 同步新增 `result_compare: str = "none"`——否则 FastAPI 的 `response_model` 会把未声明字段过滤掉。声明为 `overlay` 的三个模式：`image-background-remove`、`image-inpaint`、`image-eraser`；`image-layer-split`（输出裁到主体包围盒）与 `image-outpaint`（输出换画幅）保持 `none`，因为叠层滑杆只在两张图像素对齐时成立。
- 前端：`Workflow` 类型加 `result_compare?: string`。新增纯函数模块 `frontend/src/media/image-compare.ts`——`resolveCompareSource(workflow, references)` 按 `reference_labels` 里以「原图」开头的槽位定位原图（不认死序号），非 overlay 或槽位缺失一律返回 `undefined`；`isCompareAligned(before, after)` 以 1% 长宽比容差判断能否叠层（分辨率可以不同）。结果卡（`media/ImageStudioModule.tsx`）在悬停工具条加「对比原图」开关按钮，点击就地换成原图并显示「原图」角标；`MediaPreviewModal` 新增可选 `compare` 属性，渲染两层 `clip-path: inset()` 互不重叠的叠层 + 覆盖整个画面的原生 `<input type=range>`（`opacity:0`、thumb 高 2000px 使画面任意位置都能拖），未对齐时退回单图且不裁切结果层。对比源经 `MediaPreview.compare` 随预览列表传递，上下切换时保持。
- 滑杆视觉（对齐市面 before/after 控件：分隔线 + 圆形磨砂旋钮 + 边缘标签胶囊）：`.media-preview-compare-handle` 内含 `line`（2px、上下 7% 渐隐、1px 暗描边 + 柔光，两端各一枚 12×2px 端帽刻度）与 `grip`（44px 圆钮，径向渐变顶光 + `backdrop-filter: blur(4px)`、内 1px 高光 + 外 1px 暗边，保证压在高亮/高暗图像都读得出）；钮内叠放两枚 lucide `ChevronLeft/Right` 与一个百分比读数，靠 `grid-area: 1/1` 同层互换。交互态全部用 `.media-preview-compare:has(.media-preview-compare-range:hover|:active|:focus-visible)` 驱动，无需额外 React 状态：hover 放大 1.06 并亮起 accent 光环、拖拽缩到 0.95 且光环加深 + 箭头淡出换成「38%」读数、键盘聚焦换成 `--studio-focus` 环。打开时播一次 `media-compare-hint` 缩放脉冲提示可拖（`prefers-reduced-motion: reduce` 关闭），标签胶囊改为圆角 999px + 1px 边框 + 模糊底 + 前导圆点（「结果」用 accent 色点区分）。
- 主题：`--studio-checker-a/-b` 两组语义变量（浅色 `#e6eaf0`/`#f2f5f8`，暗色 `#232833`/`#2c323c`），用于 `.media-preview-canvas-image .media-preview-frame` 与 `.studio-image-results .studio-image-result-media` 的棋盘格底；替换原先「图片底 = 白 / 近黑」的写法，不透明图片完全盖住格子，行为不变。滑杆另用一组叠在图像上的语义变量 `--studio-compare-line/-grip/-grip-ink/-edge`（浅色 `rgba(255,255,255,.9)` / `rgba(255,255,255,.88)` / `#171a1f` / `rgba(9,12,17,.3)`，暗色 `rgba(243,245,247,.94)` / `rgba(243,245,247,.92)` / `#12151b` / `rgba(3,5,8,.48)`），禁止在滑杆样式里写死颜色。
- 受影响文件：`backend/app/{workflow_registry,models}.py`、`backend/tests/test_image_edit.py`（registry 值 + `/api/modes` 透出）；`frontend/src/{App.tsx,index.css,media/image-compare.ts,media/image-results.css,media/ImageStudioModule.tsx,components/MediaPreviewModal.tsx}`、`frontend/src/media/{image-compare.test.ts,image-results.test.tsx}`；三份文档。
- 兼容性：新增可选字段，旧任务与旧前端读取 `/api/modes` 不受影响；未声明 `result_compare` 的工作流一律 `none`，界面与之前完全一致。无表结构、端口、节点 ID 变更。
- 验证命令：`python -m pytest backend/tests/test_image_edit.py -q`（24 OK）；`npx tsc -b --force` + `npx vitest run`（116 文件 / 769 用例）；5173 桌面端真实任务自查——`QRPwmOcXkjJR`（消除笔）、`ZbZokb3ZM0`（局部重绘）、`lH33mft4owI`（去背景）出「对比原图」按钮与叠层滑杆，`2Q5kQXRYcydv`（扩图）与 `TmExpaRSS98H`（图层分离）无按钮；把 `naturalWidth` 临时改为不同比例后确认退回单图（结果层 `clip-path: none`、无滑杆）。浅/暗双主题截图，自查后把主题偏好恢复为暗色。滑杆视觉自查用 760×520@2 临时视口放大细节，确认静止（44px 钮 + 渐隐线 + 端帽）、拖拽（`scale(.95)` + accent 光环 + 「38%」读数）与浅色主题三种状态后恢复默认视口与暗色偏好；`CSS.supports('selector(:has(*))')` 与样式表解析确认 7 条 `:has()` 交互规则未被浏览器丢弃。
- 回滚方式：还原上述文件即可；删除注册表三处 `result_compare="overlay"` 即回到「只看结果图」的旧行为，无需数据迁移。

## 2026-11-04 MiniMax H3 角色替换（换头修脸）接入为工作台工具 + 旁路分支裁剪

- 变更原因：将远端 GPU（`http://192.168.10.54:8188`，经 `comfy_provider_settings.base_url` 生效、`provider_bridge.comfy_row()` 读取）上已实测出片的 MiniMax H3「视频换角色身份（换头 / 修脸 / 表情迁移）」工作流以增量方式接入工作台，不替换既有工作流。以远端已验证出片的干净模板 `backend/app/face_swap_template.json`（190 节点 API 图）为基线做「模板 + 补丁」建图，只覆盖输入旋钮，并在远端内嵌 yolov8m 裁脸子图，避免半身参考图把背景整块塞进脸部框导致矩形鬼影。
- 后端接入：`models.py` 新增 `JobMode.MINIMAX_H3_FACE_SWAP`；`workflow_registry.py` 注册该模式（min/max references=2、`reference_labels=(角色形象图, 原片视频)`、第 1 位 image / 第 2 位 video、`accepts_video_reference`、目录组 `official_h3`、`default_prompt=FACE_SWAP_DEFAULT_PROMPT`）与 option schema——`duration`（primary，枚举 `5s/10s/15s` → `FACE_SWAP_FRAME_CAPS` 派生 internal `frame_load_cap`）、`crop_factor`（advanced，1.0-3.0）、`confidence`/`frame_load_cap`（internal）；`normalize_options` 专用分支。`face_swap_workflow.py` `build_face_swap_workflow(reference_image, source_video, prompt, *, crop_factor, frame_load_cap, confidence)`：深拷贝模板后把 `1068` VHS_LoadVideo 指向上传原片并写 `frame_load_cap`、`138` 写提示词（空则回落默认换脸提示）、内嵌 `9000` LoadImage → `9001` H3FaceTrackCrop（detector `bbox\face_yolov8m.pt`、`identity_track=False`——离网 GPU 上 insightface buffalo_l 联网下载会不可中断死锁、`select=largest_face`），再把模板原本挂在 `371`/`265` 两张半身参考图的六个 `MiniMaxH3ReferenceToVideo` 身份槽统一重指向 `9001` 裁脸输出。`comfy_service.py` 新增 `_run_face_swap`（references[0]=image / references[1]=video、上传→建图→`face_swap_missing_message` 远端节点/检测器预检→`run_workflow`→`completed_outputs`）并在派发与完成回显处接入该模式。
- 关键修复（本次端到端排障结论）：模板冻结自一段较长的 chovy 测试片，除换头成品输出 `161`（images=`["1631",0]`、audio=`["1068",2]`）外还挂着一条「整段重生成」旁路输出 `412`，其上游是按源片长度派生的分段循环 / 帧区间切片 / 音频偏移裁剪节点。这些旁路节点对任意短上传普遍越界——实跑依次失败于 `1570` TrimAudioDuration（`start ... within the audio length`，其 `start_index` 由节点 `931` 冻结为 ~5.67s 偏移）与 `1483` GetImageRangeFromBatch（`Start index is out of range`）；而对端换脸成品 `161` 其实早已成功产出。可达性核验（`build` 后的真实图）确认 `1483/1570/958/926/1353` 均在 `412` 闭包内、不在 `161` 闭包内，且 `412` 是纯输出汇点；`161` 音频走 `start=0` 的兄弟节点 `1569`（短片本就安全）。逐点打补丁是打地鼠，正确解法是**建图末尾把图裁剪到只保留 `161` 的祖先闭包**（`_ancestor_closure` + 字典过滤，77 节点），旁路分支（含 `412` 及其 91 个专属节点）整体不出现在提交图里、远端不再执行它们，与 ComfyUI 是否跳过孤儿节点无关。该修复取代了先前误打的 `1570` 补丁与 `replacement_seconds` 参数（一并移除）。
- 前端：新建 `tools/FaceSwapTool.tsx`（复用动作迁移的图 + 视频双槽与 helper，references 顺序=形象图→原片，提交 `mode/prompt/options`），`paths.ts` 新增 `/tools/face-swap` 及路由白名单，`tool-registry.ts` 新增「角色替换」视频卡 + `tool-icons` 图标 + 封面，`ToolsWorkspace.tsx` 接入路由分支；首次进入弹「功能示例」左右对比演示。表单遵守参数分层——仅「替换时长」primary、「裁脸范围」advanced 走「更多设置」，internal 不外泄。
- 受影响文件：`backend/app/{models,workflow_registry,face_swap_workflow,comfy_service}.py`、`backend/app/face_swap_template.json`；`backend/tests/test_face_swap_workflow.py`（14 项：registry/schema 分层/normalize/建图补丁/裁脸重指向/**旁路分支裁剪**/缺节点缺检测器预检）；`frontend/src/tools/{FaceSwapTool.tsx,tool-registry.ts,tool-icons.ts}`、`paths.ts`、`ToolsWorkspace.tsx` 及对应 vitest；三份文档。
- 兼容性：全新模式，不改动既有工作流与节点 ID；`frame_load_cap` 等由后端派生，历史任务无此模式不受影响；裁剪只删除交付不依赖的旁路节点，`161` 链路内节点 ID 不变，合规。
- 验证：`python -m unittest backend.tests.test_face_swap_workflow`（14 OK，bundled python310）；前端 `pnpm --dir frontend build` 绿。真实远端链路（5173 桌面端、`zlyadmin` 会话、远端 ComfyUI `192.168.10.54:8188`）：上传形象图 + 5.2s 原片 → 提交任务 `hD50lKMsr5u` → 逐阶段（上传形象图→上传原片→准备→检测替换）→ `status=succeeded`、`stage=生成完成`、`progress=100`，产出 `https://img.zlyun168.com/zly-ai-video-studio/face_swap/20261104/113110_0775f6581fc797de.mp4`（HEAD 200、video/mp4、4.83 MB、七牛云交付），生成页播放器 00:06 正常播放；诊断临时脚本置于 `.tmp/` 并已清理。
- 回滚：还原上述文件即可，无表结构 / 端口 / 节点 ID 迁移；该模式独立于既有工作流，移除注册项与前端工具卡即可下线。


## 2026-11-04 图层分离对照即梦补齐三种拆分方式（智能 / 框选 / 按描述）

- 变更原因：用户要求参考即梦完善图层拆分。原 `/tools/image-layer-split` 是「上传即提交」的通用页，后端只有文本概念自动分割一条路径；即梦提供 智能拆分 / 框选拆分 / 按描述拆分 三种方式。远端能力核查：`http://192.168.10.54:8188`（经 `comfy_provider_settings.base_url` 读取）装有 SAM3.1（文本/点/框三种提示，`/object_info/SAM3_Detect` 与 ComfyUI 官方 `nodes_sam3.py` 源码核对）与即梦同源 `ByteDanceSeedreamLayerSeparationNode`（API 节点，授权不可验证且计费，不采用）；三种方式均由 SAM3 本地免费承载。
- 后端（`image_edit_workflow.py`）：`build_image_layer_split_workflow` 新增 `split_box` 像素矩形参数——框选拆分把框中心换算为 `positive_coords` 正点提示（无文本）。**远端实测选型**：SAM3 `bboxes` 框提示路径不可靠（框完全落入均匀物体内部时返回空掩码；框带边距时返回稀疏噪声），中心正点在两种情况下都精确分割点下主体（探针掩码包围盒=主体精确边界），与动作迁移生产点提示链路同机制；模块 docstring 记录实测结论。`build_image_edit_workflow` 对 `split_mode=description` 且空 prompt 直接报错。`comfy_service.py`：`_split_box_pixels` 把千分比坐标串 `"x0,y0,x1,y1"` 按原图尺寸换算像素矩形（PIL 读尺寸，越界/跨度<1‰ 拒绝），仅在 `split_mode=box` 时传入；`_run_image_edit` 其余链路与输出节点 9/10 不变。`workflow_registry.py`：图层分离 schema 新增 `split_mode`（**primary**，枚举 auto/box/description，ui_options 中文名）与 `split_box`（internal 字符串）；`normalize_options` 新增图层分离专用分支（框选模式校验并归一化千分比串，`normalize_split_box_text` 在 `image_edit_workflow.py`）。描述文案同步三种方式。
- 前端（`tools/ImageLayerSplitTool.tsx` 重写 + `tools/image-layer-split.css` 新增）：从通用上传页重构为即梦式舞台编辑器（复用 `photo-edit-editor.css` 舞台/缩放/指令条体系）——暗色舞台 + 拖拽上传；指令条第一行为三方式标签页（Sparkles 智能拆分 / SquareDashed 框选拆分 / PenLine 按描述拆分，`role=tablist`），框选模式在舞台拖出青色虚线框 + 四角手柄（单框，重拖替换，误触不吞框），指令条内显示「框选 1 处」芯片，按描述模式内嵌 TextArea；右下「确认拆分」按钮按方式校验（无框/无描述禁用）。提交协议：`prompt`（仅描述模式）+ `options={split_mode, split_box?}`（千分比串，`boxToPerMille` 换算）；支持 `?job=&round=` 恢复原图。`tool-registry.ts` 工具卡文案同步。全部颜色走 `--studio-*` 双主题。
- 受影响文件：`backend/app/{image_edit_workflow,comfy_service,workflow_registry}.py`、`backend/tests/test_image_edit.py`（23 项：schema 分层、三方式 normalize/校验、框选正点 graph、描述空 prompt 拒绝、`_split_box_pixels` 换算）；`frontend/src/tools/{ImageLayerSplitTool.tsx,image-layer-split.css,image-source-tools.test.tsx,tool-registry.ts}`；三份文档。
- 兼容性：输出节点与交付链路不变（前景层/背景层两张透明 PNG）；智能拆分（缺省）与旧提交行为完全一致；`split_mode/split_box` 为新增可缺省参数，历史任务回显不受影响；无表结构、端口、节点 ID 变更。
- 验证：后端 `unittest discover -p "test_image_edit.py"`（23 OK，bundled python310）；`pnpm --dir frontend build`（vitest 754 + tsc + vite）通过。远端真实链路（7865 会话提交）：bboxes 变体出片 alpha 错误（暴露框路径缺陷）→ 隔离探针 4 组定位根因 → 中心点变体任务 `succeeded`，alpha 采样 框内主体 255/框外 0（前景层）与主体挖空 0/其余 255（背景层）全对；5173 桌面端暗/浅双主题截图自查（空态、框选拖拽、四角手柄、框选芯片、按描述输入、按钮禁用态与任务页「框选拆分」回显）。CUA 合成拖拽缺 pointerdown 属工具层限制，真实鼠标交互第一轮已验证。临时探针图与产物放 `tmp/` 并已清理。
- 回滚：还原上述文件即可，无迁移；`split_mode` 枚举收缩不影响旧 options 快照回显。

## 2026-11-04 扩图复刻即梦画布编辑器（任意目标画布 + executor 路由修复）

- 变更原因：用户要求图片扩图参考即梦改版。原 `/tools/image-outpaint` 是「上传 + 固定画幅 Select」，且实测发现两个既有执行层缺陷：① `storage._executor_for_mode` 只按 `grs-` 前缀判 executor，`image-inpaint`/`image-eraser`/`image-outpaint` 三个复合图片工作流被存成 `comfyui`，永远进不了 worker 的 GRS 分支而落到 ComfyUI legacy 兜底（报「视频模式需要三张参考图」），库内三模式历史上 0 次成功；② 复合工作流的 `provider_model` 内置默认 `nano-banana-2` 在当前环境被管理员停用，任务即使路由正确也必然失败。
- 后端（`grs_composite.py`）：`outpaint_canvas` 新增 `target_size`/`offset` 参数（显式目标画布优先于 `target_aspect`，offset 指定原图左上角、缺省居中），新增 `outpaint_target_size()`（校验 ≥ 原图、单边 ≤ `OUTPAINT_MAX_SIDE=4096`、偶数化）与 `outpaint_offset()`；`build_composite_inputs` / `compose_final` 的扩图分支读 `target_width`/`target_height`/`target_offset_x`/`target_offset_y`（0=未指定走旧画幅路径）；`composite_prompt` 扩图指令并入用户描述（`扩展区域按用户的描述生成：…`）。`workflow_registry.py` 扩图 schema 新增 4 个 internal 整数参数（0-4096，缺省 0），`target_aspect` 保留 primary 供生成页通用表单。
- 执行路由（`storage.py`）：`_executor_for_mode` / `_media_for_mode` 改为以 `workflow_registry` 为唯一来源（KeyError 时保留旧前缀推断兜底），复合三模式恢复为 `executor=grs`、`media_type=image`。
- 模型回落（`grs_provider.py` + `main.py` + `worker.py`）：新增 `GrsProviderService.model_enabled()` 与 `resolve_composite_model()`——提交时请求模型已停用/不存在则回落目录默认启用模型（本环境为 `gpt-image-2.5`）；`submit_generation` 对复合模式调用之并写回任务 options 快照；`execute_image` 对复合模式按 `provider_model` 校验（mode 本身不是目录 key）。
- 前端（`tools/ImageOutpaintEditor.tsx` 新组件 + `generation/outpaint-editor.ts` 纯逻辑 + `ImageOutpaintTool.tsx` 重写 + `image-outpaint-tool.css`）：上传后弹出即梦式「扩图」弹窗——近黑舞台（`--studio-media`）+ 深灰棋盘扩展区 + 白框 8 手柄（四角+四边，pointer capture 拖拽、非对称扩展、拖拽中冻结视图缩放）、左上角线性倍数标签（画布/原图最大边比）、Segmented 1.5x/2x/3x（每边线性放大，±0.05 容差高亮）、比例预设行 原比例/1:1/3:4/9:16/4:3（SVG 形状图标，原比例=保持当前倍数重置原图比例）、可选提示词（占位文案同即梦）、右下输出尺寸 + 应用。提交载荷为 `target_width/height + target_offset_x/y`（偶数化差值计入右/下 pad）。antd Modal/Segmented/Input.TextArea/Button 承载，主题经 `--studio-*` 与 antd token 双主题适配。
- 受影响文件：`backend/app/{grs_composite,workflow_registry,storage,grs_provider,main,worker}.py`、`backend/tests/{test_grs_composite,test_db}.py`；`frontend/src/tools/{ImageOutpaintEditor,ImageOutpaintTool,image-outpaint-tool.css,masked-image-tools.test.tsx}`、`frontend/src/generation/{outpaint-editor.ts,outpaint-editor.test.ts}`、`README.md`、本快照、`功能说明与扩展指南.md`。
- 兼容性：旧 `target_aspect` 提交路径与生成页通用表单行为不变；新 options 为可缺省 internal 参数；无表结构、端口、节点 ID 变更（grs_image_models 表沿用）；历史任务回显不受影响。executor/media 映射修复后，`image-inpaint`/`image-eraser` 与扩图同链路恢复可执行。
- 验证：`python -m pytest backend/tests/ -q`（1560 通过）；`pnpm --dir frontend vitest run`（754 通过）与 `tsc --noEmit` 干净。真实链路（远端 GRS，7865 会话）：编辑器拖拽（90px 屏幕位移=198px 图像像素，非对称 998×800、offset (0,150)）→ 出片 998×800，原图区域采样点逐像素一致，上/下扩展区为生成的天空/草地；倍数/比例/浅色暗色双主题 5173 实页截图自查通过。临时脚本与产物统一放 `tmp/` 并已清理。
- 回滚：还原上述文件即可；无迁移。回滚 executor 映射会重新触发复合模式错路由（历史缺陷，不建议单独回滚该项）。

## 2026-11-04 MCP 资产出图缺省出造型卡 + 纯文本集标题解析

- 变更原因：MCP 全流程实测（2026-11-04 会话）发现两处坑。① `studio_generate_asset_image` 角色缺省生成 avatar 头像，但出片前置检查只认 identity 造型卡（出片参考图=造型卡+场景主图），客户端按缺省走完仍被「缺少造型图」拦下；② 剧本解析器的集标题正则强制 markdown `#` 前缀，纯文本「第一集 xxx」整篇解析为 0 集，无法拆解。
- MCP 缺省变化（`mcp_gateway/director_service.py`）：角色资产缺省改为生成首个还没有图的造型卡（identity），不传 `identity_id` 自动解析该造型，已全部出图则重生成第一个；角色没有造型槽位时仍回落 avatar。响应 `note` 按目标类型说明出片语义（identity/scene_master 是出片参考图；avatar 仅用于界面展示并提示改用 `target_type=identity`）。工具描述同步更新（`routes.py`）。显式传参行为不变；工作台 UI 与 HTTP API 不受影响（按钮均显式传 target_type）。
- 解析器变化（`media_studio/services/script_parser.py`）：新增 `PLAIN_EPISODE_LINE`，仅在 `script_episode_spans` 找不到任何 markdown 集标题时，把严格形如「第X集」的行（集号后到行尾或跟空白/全半角标点/`**`）提升为 `# 第X集` 标题再走标准解析；「第一集就要上线了」这类无分隔的句子不会误判。已有 markdown 剧本零行为变化。
- 受影响文件：`backend/app/media_studio/services/script_parser.py`、`backend/app/mcp_gateway/director_service.py`、`backend/app/mcp_gateway/routes.py`、`backend/tests/test_standard_script_parser.py`（+3 例）、`backend/tests/test_mcp_gateway.py`（+1 例）、本快照、`docs/API.md`、`功能说明与扩展指南.md`。
- 兼容性：无表结构、端口、任务队列变更；markdown 剧本解析不变（提升仅在 0 集时触发）；MCP 工具签名不变，仅缺省行为与 note 文案变化；旧 MCP 客户端无需重新授权，重新发现工具即可拿到新描述。
- 验证：`python -X utf8 -B -m unittest backend.tests.test_standard_script_parser backend.tests.test_director_compact_script backend.tests.test_director_bracketed_script backend.tests.test_script_asset_extraction backend.tests.test_mcp_gateway -q`（46+37 项通过）；后端全量 `python -X utf8 -B -m unittest discover -s backend -t . -p "test_*.py"`。
- 回滚：还原上述三个源文件与两处测试即可，无迁移。


## 2026-11-04 导演台资产生图默认切到 GPT Image 2.5（1K）

- 变更原因：GRS 目录默认生图模型已切到 `gpt-image-2.5`（见同日下一章节），但导演台资产生图链路（`project_detail_service.generate_asset_image`）自带模型解析与直连 GRS 提交，前后端仍显式传 `gpt-image-2`。用户要求资产头像 / 造型 / 场景 / 道具等生图默认也走 2.5（1K 基础档即国内节点最便宜档 600 积分/张，比 flare 任意档位便宜）。
- 默认值：`ASSET_IMAGE_DEFAULT_MODEL = "gpt-image-2.5"`、`ASSET_IMAGE_DEFAULT_PROFILE = "gpt_image_2_5"`；模型解析查询补 `profile` 列，请求缺省或模型不可用时回落目录默认行（仍解析失败才用常量）。前端 `AssetsLibraryPane.tsx`（6 处：头像/造型/场景主视图/反打/全景/道具）与 `episode-shoot-prep.ts`（2 处：出片补齐的场景与造型）显式 `model` 改为 `gpt-image-2.5`。
- 线上协议适配：资产生成不走主注册表 `grs_request_size`（media_studio 直连 `generate_sync`），新增模块级 `grs_wire_aspect_ratio(profile, aspect_ratio, image_size)`——2.5 系列把 `1:1`/`16:9` 等比例按 `GRS_VIP_SIZES`（自 `...workflow_registry` 导入，映射单一来源）转成像素值，`auto` 与旧能力档（`gpt_image_2` 等）保持原字符串；`request_body.aspectRatio` 快照与 `generate_sync` 入参使用 wire 值，`payload.aspect_ratio` 保留业务口径供回显。设定板（identity）继续 16:9/2K。
- 受影响文件：`backend/app/media_studio/services/project_detail_service.py`（含 `_resolve_grs_model` 回退同步改 2.5）、`frontend/src/director2/panes/AssetsLibraryPane.tsx`、`frontend/src/director2/assistant/episode-shoot-prep.ts`、`backend/tests/test_job_list_payload.py`（新增 `AssetImageModelTests`：默认值 + 像素映射断言）、`backend/tests/test_asset_canvas_upload.py`（mock 模型行补 `profile`）、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`。
- 兼容性：资产生成接口请求字段不变；显式传旧模型名仍可用（目录中仍启用）；设定板 2K、造型/场景 16:9 等业务参数不变；图片编辑工具（photo-edit 等）与分镜管线不受影响。2.5 比例×分辨率组合缺失时回落该比例首个可用档，极端情况下由上游报错兜底。
- 验证命令：项目根 `python -m unittest discover -s backend/tests -t .`（1546 项 OK）；`pnpm --dir frontend exec tsc -b` 通过；`pnpm --dir frontend exec vitest run src/director2`（57 文件 / 376 项）通过。
- 回滚方式：还原上述后端与前端文件即可；无数据库迁移（目录 `profile` 列本就存在，仅查询多取一列）。

## 2026-11-04 图片去背景接入即梦式画布编辑器（SAM3 + 用户蒙版合成）

- 变更原因：对标即梦「图片去背景」交互。原工具页是单图上传表单，提交后直接跳生成页，用户无法在结果上修正分割边缘；即梦的正确体验是「上传 → 进入画布 → 看分割预览 → 画笔/橡皮修正 → 生成」。
- 前端交互基线：落地页 `/tools/image-bg-remove` 重写为即梦式（分屏插画 SVG、虚线拖拽区「将文件拖至此处添加」、「从本地上传 / 从资产选取」按钮复用 `AssetPickerModal`）；选图即 `POST /api/jobs`（mode=image-background-remove，单参考图，prompt 留空走 default）并跳 `/tools/image-bg-remove/editor?job=<id>`（新路由 `PATHS.toolImageBgRemoveEditor`，`ToolsWorkspace` 分发）。画布编辑器 `ImageBgRemoveEditor.tsx`（新增）：近黑媒体卡（`--studio-media`）上轮询任务（2s），queued/running 显示「正在识别主体并移除背景…」遮罩；成功后把结果渲染在透明棋盘格上，自动移除区叠蓝色高亮（rgba(101,127,255,.42)，从结果 alpha<0.5 提取，跨域污染时降级为只高亮画笔区）；底部浮动工具条 = 画笔/橡皮擦/粗细滑杆(6–80px)/撤销/重做/重置/「1 张」/生成，左下缩放控件（25%–400% + 适应画布 + 百分比标签），顶栏「节点 N · 状态」chip + 下载 PNG。语义：画笔=强制移除（叠加进自动移除区），橡皮擦=强制保留（按涂抹恢复原图像素）；撤销/重做是笔画级矢量栈（无整画布快照内存压力）。点「生成」把 remove/keep 两份蒙版按原图分辨率导出 PNG（白色=生效）作为 references[1]/[2] 提交新任务并替换 `?job=`；无涂抹时「生成」提示直接下载。
- 后端蒙版合成：`image_edit_workflow.py` 的 `build_image_background_remove_workflow` 新增可选 `mask_remove_filename` / `mask_keep_filename`，在既有节点（1/2/3/4/8/9 不变）外新增节点 12–16：`LoadImageMask(channel=red)` ×2 → alpha = `Invert(SAM3 mask)` `or` 移除蒙版 → `multiply` 反相保留蒙版（`MaskComposite` 的 or=max、multiply 保证 0–1 不越界），输出节点仍为 9（`SAM3_OUTPUT_NODE`，交付/恢复链路零改动）。`workflow_registry.py` 去背景条目 `min/max_references` 1→(1,3)，labels（原图 / 移除蒙版(白色=移除区) / 保留蒙版(白色=保留区)），描述补蒙版契约；`comfy_service.py` `_run_image_edit` 接受 1..3 张参考图并按序上传蒙版（图层分离仍限 1 张，蒙版参数仅去背景消费）。
- 受影响文件：后端 `backend/app/{image_edit_workflow,comfy_service,workflow_registry}.py`、`backend/tests/test_image_edit.py`（注册表条目 + 蒙版链 graph 用例 ×4）；前端 `frontend/src/tools/{ImageBgRemoveTool(重写),ImageBgRemoveEditor(新增),ToolsWorkspace,image-source-tools.test.tsx,image-bg-remove.test.tsx(新增),image-bg-remove.css(新增)}`、`frontend/src/paths.ts`。
- 兼容性：旧单图提交路径完全不变（references=1 即纯 SAM3 自动分割）；仅该 mode 的参考图范围放开为 1..3，图层分离与其余工作流不受影响；无数据库、端口、API 路径、节点 ID 与队列变更；历史任务回显不受影响。
- 验证：`python -m pytest backend/tests/test_image_edit.py -q` 17 passed；`pnpm --dir frontend build`（753 vitest + tsc + vite）通过。远端 SAM3 实测（`http://192.168.10.54:8188`，经 7865 真实任务链）：无蒙版任务 alpha 抽样正确（主体 255 / 背景 0）；双蒙版任务 keep 区恢复不透明（255）、remove 区强制透明（0），4 个采样点全过。5173 桌面端 Playwright 自查（chrome 通道 + e2etest 会话）：落地页对照即梦截图、画布棋盘格 + 蓝罩、画笔涂抹擦除生效（含笔径圈光标）、橡皮擦恢复原图、撤销/重做计数、浏览器内「涂抹 → 生成 → 新任务出片回画布」闭环（笔迹合成进最终产物 alpha）。临时脚本与截图放 `tmp/`（已 gitignore）并在验证后清理。
- 回滚：还原上述文件即可；蒙版链为纯新增节点（12–16），不带蒙版的旧 graph 行为不变；无数据迁移。

## 2026-11-04 镜头三联关键帧整体下线（分镜生图链路全部移除）

- 变更原因：三联关键帧不是出片输入，也不是写稿必需输入。远端 `ai-media` 只读普查：全库 `beat_triptych` 任务行 16 条（completed 15 / failed 1）只分布在 3 个项目（`proj-0f9c8015281149f0` 9+1、`proj-6f99a10cd9de4cfb` 4、`proj-6f8c48d559b24fe1` 2）；132 集 `ai_project_episodes.data_json` 里 `"triptych_url":"http` 出现 0 次（`triptych_panels` 仅剩 4 集的空残键）；131 条 `video_generation` 任务中 payload 出现过 "triptych" 字样的 24 条全部是镜头快照里的空键或英文提示词模板句，`triptych_*` 非空值 0 个、`reference_urls` 含三联 URL 0 条。正在制作的 `proj-a342bfd034eb4b20` 44 镜 0 三联、44/44 有 H3 指令、30/44 已出片。前一日已删掉「片段更多操作 → 规划关键帧并生成视频」串联菜单与 `prepare_video_keyframes`，三联只剩一处手工入口却仍占着任务类型、配方步骤、R2V 槽位、写稿看图与助手/MCP 契约五条链路。
- 当前界面基线（剧集工坊素材组）：头部只剩「参考图片」标签 + 「选已有 n/9」，下面是 H3 提示词区（重新生成 / 编辑 / 复制）；「生成三联关键帧 / 重生成三联」按钮、三联母图与三格裁切卡片、`WORKSHOP_H3_TRIPTYCH_GATE` 的「先出三联再写稿」拦截弹窗全部移除，素材组为空时的占位文案改为「先绑定本镜出场角色和场景，再点「生成 H3 提示词」」。九宫格上限仍是 9（`collectH3RefImages` 直接 `slice(0, 9)`，`<Picture n>` 与上传顺序对齐不变）。批量勾选、片段条缩略图、成片 Tab、配音、智能超清与「合并为一条生成」不变。
- 后端删除：`services/storyboard_image_service.py`（整个服务，含 `BEAT_IMAGE_TARGETS` 与调度器 `kick`）、`skill_packs/triptych.py`（母图裁切与 `normalize_panels`）、`skill_packs/half-narrated-live-action-short-drama/references/triptych-prompt.md`、`tests/test_storyboard_image_resume.py`。路由 `POST …/beats/{beat_id}/generate-triptych` 与 `POST …/episodes/{episode_id}/generate-images`（本集批量）一并删除，`ProjectDetailService.generate_beat_triptych` / `generate_beat_images_batch` 与 `H3PromptJobService` 的三联看图分支同批移除。至此分镜生图（草图 / 渲染图 / 三联）三条链路全部为空，`project_router.py` 的 beat 级生成路由只剩 `h3-prompt` 与 `generate-video`。
- 配方与提示词链路：`meta.yaml` 的 `workshop_shot` 收敛为 `write_timestamped_zh_prompt → polish_ref2va → bind_r2v_slots`，`r2v_slots` 只剩 `{source: characters}` 与 `{source: scene}`；`recipe.R2VSlot.is_full_triptych`、`aspect.triptych_panel_geometry_en`、`handlers.generate_shot_triptych` / `extract_triptych_panels` 删除。`H3PromptBuilder` 不再产出「同一镜构图路标」的 `<Subject n>` 句（`director_craft/references.py` 的 `composition_subject_line` 函数本体、`h3_prompt_builder.py` 的导入与 `mid|end|start` 分支一并删除），角色卡与场景卡语义不变；`episode_video_service` 装配镜头时不再追加 `triptych.start|mid|end` 裁切图，`video_prompt_signature` 不再哈希 `triptych_url` / `triptych_panels`（受影响的历史镜头会一次性重写提示词）。半解说包 `SKILL.md` / `SOURCE.md` / `h3-video-prompt-template.md` 明确写入「本工作台不执行官方第 5 步三联母图，`<Picture n>` 只送角色卡与场景卡，禁止引用未上传的构图裁切」。
- 助手与 MCP 契约：媒体类型 `storyboard_image` 端到端删除（`protocol.py` 的 `MediaDraft.media_type` Literal、`MEDIA_TYPE_ENUM`、`beat_id` 必填校验与工具说明，`actions.py` 的校验与 `_dispatch_media` 分支，`resources.py` 生产技能文案，前端 `assistant/api.ts` 的类型与 `mediaLabels`）。选择删除而不是在派发处报错，是为了不给助手留下一个「能确认、必然失败」的付费动作入口；旧的待确认分镜提案在确认时被 pydantic 拒绝，不会误落进 `compose`。MCP 工具 `studio_generate_storyboard` 与 `DirectorService.generate_storyboard` 删除，`/api/mcp` 工具数 44 → 43，`studio_list_project_jobs` 与 `studio_get_episode` 文案去掉分镜图；`BEAT_FIELDS` 继续回显历史 `triptych_*` / `sketch_*` 字段。
- 历史数据与任务：不删表、不清值。Beat 的 `triptych_url` / `triptych_panels` / `triptych_job_id` / `triptych_prompt` / `triptych_status` JSON 字段与写白名单保留（`project_detail_service.py:2125`、`director_service.py` 的 `BEAT_FIELDS`）。`RETIRED_BEAT_IMAGE_TARGETS` 扩为 `{beat_sketch, beat_render, beat_triptych}`，新增 `RETIRED_BEAT_IMAGE_MESSAGE`。因为 `StoryboardImageService.recover_interrupted_jobs()` 随服务一起消失，`main.py` 启动钩子只剩 `ProjectDetailService.recover_interrupted_image_jobs()`，该方法原本对 beat 目标 `continue`（会把三联活跃行永久留在 running，一直触发助手媒体提案的 409 保护），现改为与资产图同批收口：命中下线目标写 `RETIRED_BEAT_IMAGE_MESSAGE`，其余写原「服务重启时生图任务已中断」；`retry_job` 对三类下线目标统一抛同一条提示（普查当前活跃 beat 行为 0，属预防性收口）。
- 受影响文件（后端）：`media_studio/routers/project_router.py`、`services/{storyboard_image_service(删),project_detail_service,episode_image_prompts,video_preparation,h3_prompt_builder,h3_prompt_job_service,episode_video_service,job_payload}.py`、`skill_packs/{triptych(删),__init__,aspect,handlers,recipe,runner}.py`、`skill_packs/half-narrated-live-action-short-drama/{meta.yaml,SKILL.md,SOURCE.md,references/triptych-prompt.md(删),references/h3-video-prompt-template.md}`、`director_assistant/{protocol,actions,resources,service}.py`、`mcp_gateway/{routes,director_service}.py`、`director_craft/references.py`、`api_documentation.py`、`main.py`、`tests/{test_skill_packs,media_studio_test_h3_video,media_studio_test_storyboard_images,test_storyboard_image_resume(删),test_h3_coverage,test_workshop_video_preparation,test_mcp_gateway,test_job_list_payload,media_studio_test_storyboard_images}.py`。
- 受影响文件（前端）：`director2/panes/EpisodeWorkshopPane.tsx`（删三套生成中集合之外的三联 handler 与按钮）、`director2/workshop-r2v-refs.ts` 与 `workshop-r2v-refs.test.ts`（裁切拼装整块删除）、`director2/workshop-h3-gate.ts`（`WORKSHOP_H3_TRIPTYCH_GATE` 删除，`workshopH3PromptGate` / `beatsMissingH3Prompt` / `workshopH3GenerateLabel` 保留）及其测试、`director2/api.ts`（`generateBeatTriptych` / `generateBeatImagesBatch` 与 `Director2Beat` 的 `triptych_*` 字段删除）、`director2/assistant/api.ts`、`admin/LlmProviderSettings.tsx` 与 `assistant/{episode-shot-tasks,skill-pack}.test.ts` 的文案与夹具；`panes/JobsCenterPane.tsx` 的 `handleRetry` 改用 `director2ErrorDetail` 透出后端原因（原先 `catch {}` 只弹「重试失败」，下线的三联/草图/渲染任务点重试时看不到「已下线」这句，与同文件「智能超清」「二采」两个处理器不一致）。
- 兼容性：出片链路不变（H3 参考图一直是角色造型卡 + 场景主图/反面图）；资产生图（`identity` / `scene_master` / `scene_reverse` / `prop_*`）与 `image_generation` 任务类型、七牛存储、MySQL 表结构、ComfyUI 节点与工作流注册表零改动；`/api/modes` 不变；`GET …/jobs` 继续回显历史三联行（标题与 `result_url` 都在行内，任务中心缩略图仍可读）。已知代价：界面不再有「为本镜生成关键帧画面」的入口，需要看画面只能出片后回看或在无限画布/生成页单独生图。
- 验证命令：`python -X utf8 -B -m unittest discover -s backend/tests -t . -p "test_*.py"`（1546 项，1 跳过，1 项错误）与 `-p "media_studio_test_*.py"`（185 项，9 项失败）。两组失败都与三联无关且属并行会话的在途改动：`test_asset_canvas_upload.AssetCanvasImageUploadTests.test_generation_retains_edits_saved_while_the_provider_was_running` 在 `project_detail_service.py:1203` 抛 `KeyError: 'profile'`（该行 `grs_profile = (model_row["profile"] ...)` 是同日 GRS 2.5 章节新增的 `+` 行，`ASSET_IMAGE_DEFAULT_PROFILE` 在 HEAD 不存在，测试桩里的 `model_row` 没有这个键）；`media_studio_test_h3_video.EpisodeVideoUpscaleTests` 9 项引用 `episode_video_service` 中尚不存在的 `_vsr_rejection_for_shot` / `source_video_shape`。这些文件都不含三联相关 diff（按 `git diff | grep -c triptych` 逐文件核对）。本次改动涉及的 `test_skill_packs / test_director_assistant / test_job_list_payload / test_mcp_gateway / test_h3_coverage / test_workshop_video_preparation / media_studio_test_h3_video` 全绿。前端 `npx vitest run` 113 文件 / 754 项全通过，`npx tsc -b` 退出 0（此前挡住构建的并行会话文件已补齐），未为本轮验证打包 `frontend/dist`。路由删除在 HTTP 层核对：`POST …/beats/{beat_id}/generate-triptych` 与 `POST …/episodes/{episode_id}/generate-images` 已不再命中 API 路由（落到静态处理返回 405，同前缀 GET 是 SPA 回退 200），而仍在的兄弟端点 `POST …/beats/{beat_id}/h3-prompt` 返回 401。
- 桌面端 5173 实页自查（已执行，未触发任何生图 / 写稿 / 出片）：以测试账号登录后进入在产项目《闪婚蜜爱》`proj-a342bfd034eb4b20` 第 1 集工坊 → 「高级制作详情」抽屉，浅 / 暗双主题下素材组均为「素材组 + 已生成 chip → 参考图片 + 选已有 4/9 + 九宫格与 `+` 空位 + 展开更多(+1) → 提示词 + 重新生成 / 编辑 / 复制」，无「生成三联关键帧」按钮、无 16:9 母图卡与三张裁切格；提示词编辑态显示 `<Picture n>` 原文与 保存(禁用) / 取消 / 复制，点「取消」后整页网络记录只有 GET，无 PUT/POST，未写入数据；控制台无本次相关报错。任务中心 `…/jobs` 按「三联」筛选：`proj-0f9c8015281149f0` 图片生成 64 项中命中 10 条历史三联任务，已完成行的标题、进度、结果缩略图照常渲染，点开详情弹窗显示 目标类型 `beat_triptych` / 宽高比 16:9 / imageSize 2K / 输出分辨率 2048×1152 / 参考图数量 3 且不报错；唯一一条失败任务点「重试」返回 **400**，body 为 `{"detail":"镜头生图（草图 / 渲染图 / 三联关键帧）已下线，请直接为本镜生成 H3 提示词后用角色卡与场景卡出片。"}`，前端 toast 原样转达且未新建任务。参考截图文件本轮未落盘：仓库无 Playwright，自动化截图工具不允许写入本仓库路径，且应用内 Browser 视口不可见，故 `docs/design-ref-director/` 仍按附录待重拍。
- 回滚方式：还原上述文件的三联 hunk，并放回 `test-results/triptych-removal-backup-20261104/` 里的 7 份快照（`storyboard_image_service.py`、`skill_packs/triptych.py`、`references/triptych-prompt.md`、`tests/test_storyboard_image_resume.py`、前端 `workshop-r2v-refs.ts` 与 `workshop-r2v-refs.test.ts` 六个删除文件，外加 `media_studio_test_storyboard_images.py` 的改动前版本）；这些文件也都在 Git HEAD 里，`git show HEAD:<路径>` 可直接取回。`main.py` 需同时放回 `StoryboardImageService` 导入与启动恢复调用，`protocol.py` 放回 `storyboard_image` 媒体类型，`mcp_gateway` 放回 `studio_generate_storyboard`（工具数断言回到 44）。历史 Beat 字段与任务行都未清理，回滚后旧三联图卡片、裁切格与任务记录直接可读；无迁库、无端口与供应商配置动作。禁止对 `episode_video_service.py`、`project_detail_service.py`、`docs/*` 等共享文件整文件 `git checkout HEAD --`（同期含并行会话改动）。

## 2026-11-04 GRS 生图接入 GPT Image 2.5 系列并设为默认

- 变更原因：远端 GRS（grsai.dakka.com.cn）已上线 gpt-image-2.5 系列（`/v1/models` 实测返回 `gpt-image-2.5` / `gpt-image-2.5-flare` / `gpt-image-2.5-sunburst`）。用户要求把 GRS 生图配置成 2.5 全套并设为默认，旧的 gpt-image-2 / gpt-image-2-vip 保留可用。线上协议实测结论：2.5 系列 `aspectRatio` 不接受 `1:1` 等比例字符串（上游报错并要求像素值），必须传像素值或 `auto`；`imageSize` 沿用 1K/2K 档位字符串；`quality` 字段（low/medium/high/xhigh/max）被接受并影响计费。
- 目录与参数：`grs_catalog.py` 新增能力档 `gpt_image_2_5`（1K，基础版无画质参数）与 `gpt_image_2_5_vip`（1K/2K/4K + 画质 advanced 选项），内置目录新增 3 个模型（sort_order 5/6/7，`gpt-image-2.5` 为 `is_default`，`default_enabled=True`）。`catalog_record` 携带 `quality_options`/`default_quality`；`grs_image_models` 新增 `quality_json` 列（sqlite 建表 + `_ensure_column`、MySQL DDL `sql/001_init_mysql.sql` 同步），`_grs_image_model_from_row` 解析回目录。`workflow_registry.py`：`grs_option_schema` 新增两档分支（比例枚举复用 VIP 16 项含 auto，无 CUSTOM 自定义尺寸）；flare 画质 low/medium/high（默认 medium）、sunburst low~max（默认 high），均挂 `advanced` 组（`ui_control=select`）；`grs_request_size` 对 2.5 系列统一走 `GRS_VIP_SIZES` 像素映射；`normalize_options` 的比例×分辨率校验扩展到 2.5 两档。
- 提交链路与迁移：`grs_client.py` 的 `submit()` 新增可选 `quality`（有值才写 `body["quality"]`）；`worker.py` GRS 提交处透传 `options.get("quality")`。`_normalize_schema_options` 的 `quality → megapixels` 联动加 `megapixels_by_quality` 非空守卫（该联动本属 H3；GRS 2.5 的 `quality` 无映射表，原实现会 KeyError）。`storage.py` 新增一次性迁移 `GRS_GPT_IMAGE_25_MIGRATION = 2026-11-04-grs-gpt-image-25-default`：补插缺失的 2.5 三行、启用它们、把 `is_default` 切到 `gpt-image-2.5`；调用点在 `_ensure_grs_image_models`（每次启动对已迁移旧库也会执行，幂等）与 `sync_builtin_grs_image_models`（管理端“同步内置目录”兜底）。新库种子 `default_id` 改为 `gpt-image-2.5`。
- 受影响文件：`backend/app/grs_catalog.py`、`backend/app/workflow_registry.py`、`backend/app/grs_client.py`、`backend/app/worker.py`、`backend/app/storage.py`、`backend/app/models.py`（`GrsImageModelCreateRequest.profile` Literal 扩展）、`sql/001_init_mysql.sql`、`backend/tests/test_ai_studio.py`。前端零改动：创作页/管理页的模型目录、参数表单均由 `/api/modes` 与目录接口驱动，`quality` 走既有 `advanced`（更多设置）渐进渲染。
- 兼容性：历史任务 mode、GRS 提交协议字段（除新增可选 `quality`）与 `grs-gpt-image-2` / `grs-gpt-image-2-vip` 工作流全部保留，仅默认模型变为 `grs-gpt-image-2.5`（导演台 `default_image_workflow_id` 等取“首个启用模型”的路径自动跟随）；管理员仍可在管理页目录改回。旧库迁移只启用 2.5 三行并切换默认，不改动其他行；管理员事后可自由停用。`gpt-image-2.5` 基础版按 GRS 计费与 `gpt-image-2` 同价（1K ¥0.03/张），flare ¥0.1/张、sunburst ¥0.12/张起，画质档位影响实际计费。
- 验证命令：`python -m unittest tests.test_ai_studio`（45 项，含新增 `GptImage25RegistryTests` 3 项、目录种子/旧库迁移 2 项、quality 透传 1 项）；项目根 `python -m unittest discover -s backend/tests -t .`（1540 项 OK, 1 skipped）。线上实测（真实计费约 ¥0.3）：`gpt-image-2.5` 16:9 1K、flare 2K 像素映射（2048x1152）、flare 1K `quality=low` + 像素 1024x1024、flare `auto` 四个探针任务全部 succeeded 并返回图片 URL；不带 quality 的请求体不含该字段。
- 回滚方式：还原上述后端文件与 SQL 即可；`quality_json` 列残留无害（无读取方）。已应用的一次性迁移如需回退，由管理员在管理页把默认切回 `gpt-image-2` 并按需停用 2.5 系列，无需动数据库。

## 2026-11-03 剧本解析详情抽屉收敛为只读（前端入口下线，接口不动）

- 变更原因：抽屉（`ScriptWorkspace.tsx` 内嵌 `ContentLibraryPane`）的「转入资产库 / 规划出片镜头 / 同步至剧集工坊 / 抽屉内导入」在最新出片流程里都已有权威入口，属重复入口；「转入资产库」还走 `mode=merge`，会覆盖用户手工改过的角色描述与一致性 Prompt。是否保留「同步至剧集工坊」按远端 `ai-media` 只读普查判定，不凭调用点推断：33 份文档 / 31 个项目里 30 个项目只有 1 份活文档；工坊 131 集中 44 集带 `source_document_id`，44/44 指向本项目当前活文档，指向另一份文档的 0 集——「抽屉导入独立文档 → 覆盖同步整本工坊」这条链全库从未发生。
- 当前界面基线：抽屉头部只剩「标准剧本规范」；文档操作区只剩「剧本诊断 / 删除」；空态去掉「立即导入剧本」「一键导入《寒门硕士》标准范例」与格式提示行，文案指向剧本页「导入剧本」。内容解析摘要、六张解析 Tab、镜头规划瘦进度直播、文档列表与删除确认不变。规划完成 Toast 改为「镜头规划完成，关闭本抽屉后按助手进度卡继续出片」。
- 能力去向与前端状态模型：导入由 `ScriptWorkspace.importScript`（建文档后 `consolidateScript` 并入主剧本）、目录「上传文件解析新集」和首页建工程时的正文导入（`DirectorAssistant.tsx` 的 `startProject` → `createDocument`）承担；拆解资产只由剧本页底部 `nextStage()`（固定 `mode=append`）承担；规划只由智能助手进度卡承担（`WorkflowProgressCard.tsx` 的 `plan-shots` → `enqueueDocumentShotPlan`）。同步分两条：`append` 由「制作资产」页进入分镜时自动执行（`ProjectFlowShell.continueToWorkshop` → `transferEpisodesFromDoc(..., "append")`，非破坏），`overwrite` 只剩助手进度卡 `sync-episodes` 且仅在工坊还没有集时出现。抽屉不再制造独立文档，但 `primaryScript()`（最早创建的活文档）与 `documents[0]`（`ORDER BY updated_at DESC`，进度卡与进入分镜使用）仍是两套规则，多份活文档时依旧可能指向不同剧本。范例导入写死 `chinese_period_drama` 后经「最近更新文档画风」回退污染资产生图的路径已关闭。
- 受影响文件：`frontend/src/director2/panes/ContentLibraryPane.tsx`（1428 → 797 行，删两组 handler、8 个状态、导入 Modal 与同步 Modal、`SAMPLE_SCRIPT`、`ImportFormState` 与 `onEpisodesTransferred` 属性）、`panes/ScriptWorkspace.tsx`（抽屉调用点）、`panes/content-library.css`（865 → 813 行）、`panes/content-library-header.ts`、`director-surfaces.css`（空态遗留覆盖规则 `.empty-doc-box .ant-btn` / `.empty-doc-formats`）、`assistant/workflow-progress.ts`（空态与两处「到内容库检查」文案改指「剧本」页）、`panes/EpisodeWorkshopPane.tsx`（新建分集表单提示不再指向内容库导入）、`director2-stage-choices.ts`（澄清题说明改为「导入后在智能助手点「规划出片镜头」」）、`assistant/shot-plan-live.ts`（`documentCanPlanShots` 删除）及其测试、`docs/导演台流程与界面结构.md`。
- 兼容性：后端 `POST …/documents`、`…/transfer-assets`、`…/shot-plan`、`…/transfer-episodes` 与 `ProjectDetailService` 实现零改动，助手与 MCP 网关（`studio_plan_script`、`studio_extract_script_assets`）继续调用；只删前端入口，无表结构、端口、任务队列与 ComfyUI 变更。已知代价：界面不再有「用一份新剧本覆盖已有集数的工坊（含删集）」入口，也不再有导入时选「骨架模板 / 视觉风格」的表单。
- 验证命令：`pnpm --dir frontend exec tsc -b --pretty false` 通过；`pnpm --dir frontend exec vitest run src/director2`（58 文件 / 379 项）通过；`pnpm --dir frontend build`（全量 vitest + tsc + 打包）exit 0；5173 桌面端暗色实测 `proj-a342bfd034eb4b20` 抽屉，头部与文档操作区按新基线渲染，无空隙、无残留弹层。未做移动端检查。
- 回滚方式：还原上述前端文件与测试即可（两组 handler + 状态 + 两个 Modal + `SAMPLE_SCRIPT` + 三处按钮 + CSS 规则 + 文案），无数据与接口迁移。流程与普查明细见 `docs/导演台流程与界面结构.md` 同名章节。

## 2026-11-03 H3 动作迁移 · 多人参考视频版（与 minimax-h3-motion-transfer 并存）

- 变更原因：远端实跑验证（巴西顺拐舞原片 `3UOTTR8nWgaY`，单人竖无音/双人横/双人竖有音三条路线）证明存在一条更优的多人动作迁移直连路径：动作视频直接进 `MiniMaxH3ReferenceToVideo.ref_videos.ref_video_0`（`<Video 1>`）作为深度动作/表演来源，角色图扁平进 `ref_images.ref_image_0..5`（`<Picture n>`）按顺序绑定表演者，不依赖 SDPose 骨架抽取与 Fun ControlNet，运镜、场景与原声音轨可一并迁移。现有骨架版无法覆盖多人和原声迁移场景，产品化为独立工作流，与旧版并存互不影响。
- 后端新增：`models.py` JobMode `MINIMAX_H3_MOTION_REF_VIDEO`（`minimax-h3-motion-ref-video`，显示名「H3 动作迁移 · 多人参考视频版」，catalog_group=official_h3）；`workflow_registry.py` 新增 `MOTION_REF_VIDEO_OPTION_SCHEMA`（primary=aspect_ratio（默认 9:16）+duration，advanced=preserve_audio/render_quality/seed，其余 internal）、`MOTION_REF_VIDEO_WORKFLOW_IDS`/`is_motion_ref_video_workflow` 与 normalize 分支（复用 `resolve_motion_transfer_dimensions`，5/10/15s=124/243/362 帧 @24fps，16:9=864×480、9:16=480×864、1:1=640×640）；graph 构建器 `h3_motion_ref_video_workflow.py`：`<Subject>` 模板按 BLUE/RED/GREEN/MAGENTA/CYAN/YELLOW source performer 绑定角色数，用户已手写 `<Picture/<Video 1>/subject_definitions` 结构时原样透传，空提示词回落内置默认；preserve_audio 时接音频链 TrimAudioDuration→VAEEncodeAudio→SolidMask→SetLatentNoiseMask→LTXVConcatAVLatent，输出节点 `58`；模型链使用远端已有的 ref2va int8 UNET + qwen3vl_32b int8 CLIP + 视频/音频 VAE。
- 可变槽位工作流（新架构概念）：`reference_slots` 按最大数量声明（image×6 + video），实际提交数可变（2-7）；`WorkflowDefinition.reference_kind(index, count)` 在 count 小于声明槽位数时末位按尾槽类型（video）、其余按 image。`main.py` 三处调用点（`_validate_reference_upload`、`_validate_saved_references`、`public_reference` 回显）传 count；保存后视频槽校验复用 `validate_motion_video`；图片槽报错改为按工作流名与实际序号。`ModeResponse` 新增 `reference_slots` 字段经 `/api/modes` 透出，前端据此判断槽位，不硬编码。
- 执行链路：`comfy_service.py` dispatch 走 `_run_motion_ref_video`：`references[:-1]` 逐张上传为角色图（motion_ref_character_n），末位视频经 `motion_transfer_media.prepare_motion_reference_video`（新增：24fps 对齐、目标画布、tpad 0.75s，原片带音轨时保留 aac 音轨否则 -an）预处理后上传；接音频链是「用户 preserve_audio 开关 AND ffprobe（`has_audio_stream`，新增）实测有音轨」双闸。历史恢复走 `completed_outputs` 节点 58 分支，输出键 ("videos","gifs","images") 兼容。
- 前端：创作页下拉两条动作迁移工作流并存；多人版渲染新组件 `frontend/src/generation/MotionRefVideoReferences.tsx`（角色行 + 添加角色 1-6 + 末位动作视频行，支持替换/前移/后移/移除/预览）；`App.tsx` 以 `motionImageLimit`/`isMultiMotionWorkflow`（依据 `reference_slots`）切换两套表单，提交约束 1-6 图 + 1 视频，回显 kind fallback 按实际素材数末位判 video。单人骨架版组件与行为不变。
- 前端·工具页统一入口（同日增量）：「AI 工具 → 动作迁移」（`/tools/motion-transfer`）升级为三种迁移方式可选——SCAIL-2 人物替换（`scail2-replacement`，hidden_from_catalog，不在 `/api/modes` 列表内，工具页以 `Promise.all` 直查三个 `/api/modes/{id}`）、骨架 H3、多人参考视频版，展示名/标签/schema 全部取自注册表不硬编码；`?mode=` URL 深链、`valuesByMode` 按模式缓存参数互不覆盖、hero 副标题用前端语义文案 `MODE_TAGLINES`（注册表 description 面向接口含技术文本，不直接展示）。任务中心三种动作模式的「再次生成」统一路由回工具页并按 `round.mode` 恢复素材与参数。共享常量与 `motionImageLimit` 从 `App.tsx` 迁入 `frontend/src/generation/motion-transfer.ts`（`MOTION_TOOL_WORKFLOWS`），工具页与创作页同源判断。
- 兼容性：新 mode 不加入 `MOTION_TRANSFER_WORKFLOW_IDS`（测试断言两工作流互不影响）；旧版任务、历史媒体、MCP 网关边界均不变；SCAIL-2 人替换工作流本身与点选配对协议不变，只是工具页入口升级为三种方式可选（默认仍为 SCAIL-2）；无数据库、端口、供应商与 ComfyUI 节点安装变更。
- 验证：`python -m pytest backend/tests -q`（含新增 `backend/tests/test_h3_motion_ref_video.py` 23 项：registry/schema 分层/normalize/graph 扁平接线与音频链两态/service 分支/API 提交与 422）；`pnpm --dir frontend build` 通过；5173 桌面自查两条工作流并存、多人版表单（添加角色 0/6、保留原片声音开关）与单人版回归正常，截图在 `test-results/motion-transfer/`。集成前远端 192.168.10.54:8188 同接线已实跑出片（双人 9:16 带音 371s 成片）。
- 回滚方式：撤回 `models.py` 新 mode、`workflow_registry.py` schema/定义/normalize 分支、`h3_motion_ref_video_workflow.py`、`test_h3_motion_ref_video.py`、`comfy_service.py`/`main.py`/`motion_transfer_media.py` 分支增量与前端新组件及分支即可；无数据迁移，已有任务与媒体不受影响，骨架版工作流零改动。

## 2026-11-03 镜头草图与渲染图整体下线（分镜生图三阶段的第一批；三联关键帧已于 2026-11-04 一并下线）

- 变更原因：草图与渲染图从来不是出片输入。H3 的参考图只取角色选定造型卡、场景主图/反面图与三联关键帧裁出的 `triptych_panels`（`episode_video_service.py` 装配镜头），草图/渲染图过去只做缩略图回看；同日抽屉瘦身后两者已无界面入口，只剩助手 `storyboard_image` 提案与 MCP `studio_generate_storyboard(stage=...)` 两个调用方还在维持三阶段语义。继续保留等于让分镜生图并存「看起来能出片、实际不进片」的死路。
- 后端接口：删除 `POST /api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-sketch` 与 `.../generate-render`；`generate-triptych`（单镜）与 `generate-images`（本集批量）保留，批量路由 summary 改为「批量生成镜头三联关键帧」。
- 服务层：`ProjectDetailService.generate_beat_sketch/generate_beat_render` 及只服务它们的 `_generate_beat_still`（约 223 行旧同步出图实现）删除，`generate_beat_triptych`/`generate_beat_images_batch` 直接委托 `StoryboardImageService`。`StoryboardImageService` 收敛为单阶段：`enqueue(project_id, episode_id, beat_id, payload)` 去掉 `stage` 形参，`BEAT_IMAGE_TARGETS = {"beat_triptych"}`，删除 `_stage_canvas`、渲染画风校验与草图/渲染分支，画幅固定 16:9 / 2K（2048×1152）后由 skill pack 裁切三联。`episode_image_prompts.py` 只保留三联参考图装配：`beat_sketch_prompt`、`beat_render_prompt`、`SKETCH_MARKER_PALETTE`、`character_marker_color`、`visual_style_prefix`、`asset_to_prompt_dict` 与草图专用助手函数删除，`beat_reference_urls(beat, assets, *, scene_view="front")` 不再接收 `stage`，也不再注入历史 `sketch_url`。
- 两个调用方收口：`director_assistant/actions.py` 的 `storyboard_image` 改调 `ProjectDetailService.generate_beat_triptych`（媒体类型枚举与 `MediaDraft` 保持不变，历史待确认提案仍能确认，且不会因为删分支而落进 `compose` 这条错的付费动作）；MCP `studio_generate_storyboard` 去掉 `stage` 参数，`DirectorService.generate_storyboard` 直接按整集或勾选镜头入队三联关键帧。
- 历史任务与数据：新增 `RETIRED_BEAT_IMAGE_TARGETS = {"beat_sketch", "beat_render"}` 与 `RETIRED_STAGE_MESSAGE`。启动时 `StoryboardImageService.recover_interrupted_jobs()` 把共享 `ai_project_jobs` 里遗留的这两类活跃行置为 failed 并写入下线说明；任务中心「重试」经 `ProjectDetailService.retry_job` 同样路由到 `StoryboardImageService.retry` 并抛出该提示（`recover_interrupted_image_jobs` 继续跳过全部 beat 图片行，避免用通用「服务重启已中断」覆盖更准确的文案）。`beat.sketch_url / sketch_prompt / sketch_job_id / render_url / render_prompt / render_job_id / render_status` 的 JSON 字段、写白名单与缩略图回退（`WorkshopOverview`、`WorkshopWorkspace` 片段条、`smart_edit_service` 封面、`h3_take_split` 归档重置）全部保留，不改表结构、不清历史值。注意 `render_status: "completed"` 仍由视频链路写入，与已下线的渲染图阶段无关。
- 前端：`director2/api.ts` 删除 `generateBeatSketch` / `generateBeatRender` 封装；`EpisodeWorkshopPane.tsx` 的 `GenerationStage` 三态机件（三套生成中集合 + `trackedBatchJobsRef` 的「批量草图/批量渲染图」播报）收敛为三联关键帧单套（`setTriptychGeneratingSet` / `addToTriptychSet` / `deleteFromTriptychSet`），轮询只认 `beat_triptych`。
- 兼容性：出片链路不变（`video_preparation.prepare_video_keyframes` 与 `skill_packs.handlers.generate_shot_triptych` 只是少了 `stage` 实参）；旧 MCP 客户端继续传 `stage` 会被忽略并按三联关键帧执行；无数据库迁移、无 ComfyUI 与工作流注册表变更。
- 受影响文件：`backend/app/media_studio/routers/project_router.py`、`services/{project_detail_service,storyboard_image_service,episode_image_prompts,video_preparation}.py`、`backend/app/director_assistant/actions.py`、`backend/app/skill_packs/handlers.py`、`backend/app/mcp_gateway/{routes,director_service}.py`、`backend/tests/{media_studio_test_storyboard_images,media_studio_test_h3_video,test_job_list_payload,test_skill_packs,test_mcp_gateway}.py`、`frontend/src/director2/{api.ts,panes/EpisodeWorkshopPane.tsx}`，以及本快照、`README.md`、`docs/API.md`、`docs/导演台流程与界面结构.md`、`功能说明与扩展指南.md` 同日章节。
- 验证命令：`python -X utf8 -B -m unittest discover -s backend/tests -t . -p "test_*.py"`（1495 项通过，1 项跳过）与 `-p "*_test_*.py"`（191 项，仅 `EpisodeVideoUpscaleTests` 9 项失败）；后者在 HEAD 即已失败（测试引用 `_vsr_rejection_for_shot` / `source_video_shape`，`episode_video_service.py` 中并不存在），与本次改动无关，未顺手修改。前端 `pnpm --dir frontend build`（vitest + `tsc -b` + clean-dist + vite）通过。运行中的 7865 实测：`POST .../beats/{id}/generate-sketch|generate-render` 已落到静态兜底（405 Method Not Allowed，与任意不存在路径一致），`generate-triptych` 仍返回 401 需要登录。数据核对见下条。
- 影响面核对（《闪婚蜜爱：厉总的独宠娇妻》`proj-a342bfd034eb4b20` / 第 2 集「豪门初体验，暗藏玄机」`ep-abd1a4a1f072`）：该集 15 条 beat 的 `sketch_url`、`render_url`、`triptych_url` 全为空且 15 镜 `video_url` 均已完成；成功任务 `job-4891e7a90fc2`（一次提交 15 镜）的镜头 `reference_urls` 只有角色造型卡与场景卡（`ref_images[].source = characters / scene`）。全库 `image_generation` 334 行中 `beat_sketch` 22、`beat_render` 11，且全部已是 completed/failed 终态，没有在跑的行。结论：历史出片没有消费过草图或渲染图。
- 回滚方式：按 hunk 反向回退上述文件即可恢复三阶段（同一文件内含同期其他会话改动，禁止整文件 `git checkout HEAD --`）；历史 beat 字段与任务行都未清理，恢复后旧草图/渲染图卡片与任务记录直接可读，无迁库与配置动作。

## 2026-11-03 制作资产选择生成与单图入口（当前资产操作基线）

- 原因与行为：按即梦实页将多个按图种划分的批量按钮收敛为「多选 → 勾选一个/多个/选择全部 → 生成」。普通状态显示当前分类缺图资产数量，卡片继续进入原画布上传或生成。零选禁用生成；取消、搜索、分类或项目切换清空临时选择，全选只覆盖当前可见结果。
- 状态与调用：`AssetsLibraryPane` 使用临时 `selectionMode`、asset ID 集合及批次进度；`asset-library-generation.ts` 从所选资产派生缺图计划，角色按 identity ID 逐一补图，场景仅 `scene_master`、道具仅 `prop_reference`。沿用原同步 generate 接口串行提交，单项失败继续后续项并报告原因，成功结果按原资产/造型回填。无造型的旧角色在提交前按画布既有确定性 ID 补写初始造型；就绪判断兼容旧主图。列表也恢复已提交的进行中图片任务并阻止重复提交；刷新不会自动提交尚未发送的剩余项。
- 单图画布：`asset-canvas-model.ts` 默认只派生场景设定图和道具设定图，不再展示反打、360°、三视图、细节图。角色保留各套独立造型。原次视角媒体、提示词、位置与节点名称仍存储在 extra 中，后端目标类型与原链接协议继续兼容；不删除历史图片、分镜引用或任务。
- 受影响文件：`frontend/src/director2/{asset-library-generation,asset-canvas-model,project-flow}.ts` 及对应测试、`panes/AssetsLibraryPane.tsx`、`panes/production-assets.css`。组件使用 Ant Design Checkbox/Button 与 `--studio-*` 变量，浅暗主题共用根 Provider。不变更端口、供应商、工作流、API 或数据库。
- 验证：`pnpm --dir frontend build`（109 文件 / 719 项测试、TypeScript、Vite）；集成包 Python 显式将工作台根目录加入 sys.path 后运行 `backend.tests.test_asset_canvas_upload backend.tests.test_asset_source_references backend.tests.test_asset_prompt_inference`，33 项通过。5173 桌面浅暗主题实测缺图提示、零选/单选/全选/取消、搜索范围、空结果、分类切换与精简单图画布。浏览器拦截生成请求验证单选请求范围、多选串行和单项失败继续；测试后解除拦截并刷新恢复真实数据，没有提交供应商生图或上传素材。
- 截图基线：2026-11-03，`docs/design-ref-director/live-flow-20261103/asset-selection/`；索引与实测尺寸见导演台流程快照，受控响应不作为真实出图证据。
- 回滚：仅撤回上述文件的本次选择生成、就绪判断及单图槽位增量，再执行 `pnpm --dir frontend build`。原 extra 图片与布局字段无需迁移，已补写的初始 identity 可直接供原画布使用；不整文件回滚同期其他改动。

- 2026-11-03 真实生图补验：5173 工程 `proj-ed7e739b91ac4bf3`，实际单选李然 identity 图片（`job-db55b98bdb2f`）、批量选择玄关与一楼客厅场景图（`job-0b62df00d32f`、`job-7bb5515caec8`）。3 张均为 1672×941；回填后和刷新后图片正常加载，identity/master URL 一致，3 个成功任务均 completed/100%。观察到 3 次 200、1 次 500：一楼客厅首任务 `job-b5d2c174946e` 被后端明确标记「服务重启时生图任务已中断」，确认 failed 后重试原批次，只提交缺图的一楼客厅，已完成玄关未再次生成。23 项资产数量不变，另 20 项媒体与所有资产名称、描述、定位、视觉提示词、音色 ID 比对不变。无模拟响应、供应商切换或代码改动；未重复运行构建/单元测试。真实请求、媒体地址与截图在 `docs/design-ref-director/live-flow-20261103/asset-selection/verification.json` 的 `real_generation` 中保留。

## 2026-11-03 制作详情抽屉只保留素材组

- 变更原因：导演台的生成链路由智能助手与正文编辑器驱动，「高级制作详情」抽屉的四项手工参数（时长、说话人、时间氛围、标题）与文案、草图、成片三块内容对用户是重复且难操作的入口；保留外面做不了的一件事——核对与手改这条镜头的 H3 素材组。
- 前端形态：`EpisodeWorkshopPane.tsx` 的 `toolPanel === "details"` 分支不再渲染 `Tabs`，改为 `.ws-detail-tools` 单列容器（顶部 `.ws-detail-actions` 一行：素材组标签 + 状态 chip + 仅多切片镜头出现的「合并为一条生成」；下面是原 material pane 的 `h3-material-content` 参考图九宫格与提示词区）。`InspectorTab` 类型、文案/草图/成片三块 JSX、`保存设定`/`刷新数据` 行动行，以及随之失去调用方的 `batchGenerating`、`selectedBeatVideoProgress` 等派生量、`h3PromptCount`、`episodeFilm`/`episodeSource` 与 41 个未用 import 一并删除。`episode-workshop.css` 删除 `.xiaji-inspector-tabs*`、`.form-*`、`.look-*`、`.character-look-*`、`.sketch-*`、`.xiaji-shot-playback*`、`.tool-btn*` 约 275 行；保留 `.xiaji-inspector-tab-label`、`.xiaji-inspector-pane(.is-material)`、`.status-chip`、`.empty-hint` 与 `h3-*`。抽屉仍需 `.d2-episode-workshop ws-drawer-scope` 作用域包装（Drawer 走 portal）。
- 不受影响：`currentEpisode`/beats 的读取与保存路径、后端路由与 JSON 字段、`workshop-editor.ts`  prose 文档模型、三联关键帧与参考图绑定、H3 提示词生成与手改、合并为一条生成、配音与本集剧本抽屉。「刷新数据」仍在「本集更多操作」菜单。当时保留的 `director2/api.ts` `generateBeatSketch` / `generateBeatRender` 封装与对应后端端点，已同日「镜头草图与渲染图整体下线」一并删除，见该节。
- 同轮死代码清理（文件由 2023 行降到 1876 行，无行为变化）：删除声明即终点的 `episodeCounts`、`episodeProtagonist`、`videoWorkflowSelectOptions`、`selectedBeatVideoBusy`、`allBeatsChecked`、`getStatusColor`、`getStatusText`、`generationStatusText`、`generateVideoPrompt`、`handleToolNotice`、`startDragging`，以及随之失去调用方的 `beatCount`、`checkedBeatCount`、`generatingVideoBeatIds`、`beatJobStates`（轮询里只写不读）、`editableBeatFields`、`saveCurrentBeat`、`patchSelectedBeat`、`updateSelectedBeat`、`currentTab`、`currentSceneView`、`setSearchParams`、`splitPct`/`splitRef`/`isDraggingRef`/`onDragging`/`stopDragging` 整套左右分栏拖拽机件（`splitRef` 从未挂到任何 DOM 节点）。URL `?tab=` 深链仍然生效：`useEffect` 保留 `parseWorkshopTab` → `setToolPanel` / `setPreviewRequest`，只去掉对死状态 `setCurrentTab` 的写入。三个失去调用方的 import（`WorkshopTabKey`、`episodeOverviewCounts`、`groupedVideoWorkflowOptions`）一并移除，文件头注释改指 `updateBeatById`。
- 保留说明：`updateSelectedBeat` 内的“改源字段即作废 `workshop_prompt_document`”分支在 HEAD 之后已无调用方，正文编辑的文档同步由 `workshop-editor.ts` 与保存队列负责；`promptGateMissing` 缺提示词拦截弹窗属于 11-03「工坊一键生成」自动准备链路，已按该节决定不再弹出。
- 兼容性：无 API、数据库、工作流注册表、ComfyUI 节点与任务队列变更；已存在的 `video_duration` / `speaker` / `time_of_day` / `title` 值不会被清空，仍由助手和正文链路写入回显。
- 验证：`pnpm --dir frontend build`（vitest + `tsc -b` + clean-dist + vite）通过；`python -X utf8 -m unittest discover -s backend/tests -q` 通过；`http://127.0.0.1:5173` 桌面端浅/暗双主题实页打开抽屉自查，未写入数据。
- 回滚：`git checkout HEAD -- frontend/src/director2/panes/EpisodeWorkshopPane.tsx frontend/src/director2/panes/episode-workshop.css frontend/src/director2/panes/workshop-focus.css` 并重新构建即恢复四 Tab 抽屉；无迁库与配置动作。

## 2026-11-03 MCP 接入导演台全流程

- 原因与边界：同日审计确认 MCP 只覆盖素材生成与智能剪辑两头，导演台中段（项目 / 剧本 / 拆解 / 资产 / 工坊分镜 / 出片 / 配音）没有任何工具，外部客户端无法从剧本跑到可导出整片。本轮把中段接入，工具总数 24 → 44；作用域仍是 `studio:read` / `studio:generate` / `studio:edit`，已连接客户端重新发现工具即可使用，无需重新授权。
- 新增适配层：`backend/app/mcp_gateway/director_service.py` 的 `DirectorService(app, config)`，与 `EditingService` 同样从 `app.state` 取助手实例、直接调用工作台路由使用的那批 classmethod，不在网关里复制工坊状态机、就绪校验或租约规则。读取：`studio_list_projects`、`studio_get_project`、`studio_get_script`、`studio_get_episode`、`studio_get_dubbing`、`studio_list_project_jobs`；写入：`studio_create_project`、`studio_save_script`、`studio_plan_script`、`studio_extract_script_assets`、`studio_apply_script_episodes`、`studio_create_asset`、`studio_generate_asset_image`、`studio_update_beat`、`studio_generate_storyboard`、`studio_generate_beat_prompt`、`studio_generate_episode_video`、`studio_confirm_project_refine`、`studio_skip_project_refine`、`studio_generate_dubbing`。
- 复用映射（保持单一事实来源）：`ProjectService.list_projects/get_project/create_project`、`ProjectDetailService.list_documents/create_document/update_document/enqueue_document_shot_plan/transfer_assets_from_document/transfer_episodes_from_document/list_assets/create_asset/generate_asset_image/get_episode_detail/update_episode_beat/generate_beat_images_batch/generate_beat_h3_prompt/list_jobs/get_job`、`EpisodeVideoService.generate_episode_videos/confirm_refine/skip_refine`、`DubbingService.get_track`、`TtsGenerationJobService.enqueue`；按集改写继续走 `app.state.director_assistant.actions.edit_script_episode`，与 `PUT /api/projects/{pid}/documents/{doc_id}` 的分支一致。剧本写入沿用 `base_raw_text` 乐观并发：整篇改写必须带回 `studio_get_script` 的基线，拆解中或已进入制作的集由既有锁定规则返回冲突。
- 二采有两套：生成页任务的 `studio_confirm_refine` / `studio_skip_refine` 操作 `jobs` 表（`main.confirm_refine`）；工坊任务停在 `ai_project_jobs` 的 `awaiting_refine`，必须由 `studio_confirm_project_refine` / `studio_skip_project_refine` 调 `EpisodeVideoService.confirm_refine/skip_refine(project_id, job_id)`。两组工具并存且互不替换，工具描述里写明各自适用面。
- 输出裁剪：导演台文档行含整篇正文、`ai_project_episodes.data_json` 含全部 beats，直接透传会挤爆上下文。列表与项目概览只回 `raw_chars`、拆解摘要（集号/每集镜头数/资产计数/已拆资产集号）、资产造型 `has_image`、每集 `beat_count` 与 `video_ready_beats`；正文只在 `studio_get_script` 返回，beats 明细只在 `studio_get_episode` 返回。任务读取不暴露 `output_path` 绝对路径（沿用 `job_payload.serialize_job_row` 的既有收敛），并按活跃状态给出 `next_poll_seconds` 建议轮询间隔，取代 SSE。
- 参数治理：`studio_generate_episode_video` 的 `options` 透传工作流注册表的创作参数，`ui_group=internal` 的键（steps、megapixels、refine_preview 等）在入队前拒绝，与 `studio_create_video` 一致；技术参数由 `EpisodeVideoService.resolve_generation_options` 默认值托管。`studio_update_beat` 只接受分镜白名单字段，媒体地址只能由生成流程写入。
- 明确不做：不暴露整集合成 `EpisodeVideoService.create_compose_job`，11-02 起整集拼接的产品出口是智能剪辑，MCP 客户端继续用 `studio_prepare_edit_episode` → `studio_preview_edit` → `studio_confirm_edit` → `studio_export_edit`；不暴露项目/文档/分集/片段的删除，删除留在工作台人工执行；参考素材仍只接受图片，需要视频或音频槽位的工作流不进目录。
- 权限与兼容：`ai_projects`、`ai_project_documents`、`ai_project_assets`、`ai_project_episodes`、`ai_project_jobs` 没有 owner 列，导演台读取与写入按 `project_id` 全局可见，这是工作台 HTTP 接口的现状；MCP 未新增隔离也未放宽边界，因此 SDK `instructions` 改为如实表述「创作任务、参考图与剪辑时间线只覆盖当前授权账号自己的内容；导演台项目库和工作台一样属于同一共享工作区」。无表结构、无新 HTTP 端点、无 ComfyUI 与工作流协议变更；旧客户端忽略新工具即可，已授权连接无需重新授权。
- 受影响文件：`backend/app/mcp_gateway/director_service.py`（新增）、`backend/app/mcp_gateway/routes.py`、`backend/tests/test_mcp_gateway.py`，以及本快照、`docs/API.md`、`README.md`、`功能说明与扩展指南.md`。
- 验证：`python -X utf8 -B -m unittest backend.tests.test_mcp_gateway -q`（36 项通过，含工具发现 44 个、正文裁剪、CAS 基线、分镜白名单、内部参数拒绝、工坊/生成页两套二采分流、作用域与服务原因透传）；后端全量 `python -X utf8 -B -m unittest discover -s backend -t . -p "test_*.py"`（1491 项通过，1 项跳过）；`pnpm --dir frontend build`；本机 7865 与 5173 重启后 `/api/modes` 200、`/api/projects` 未登录 401。真实远端 ComfyUI 与远端 MySQL 上的端到端出片未执行，避免在共享项目库制造新数据。
- 回滚方式：撤回 `director_service.py`、`routes.py` 中的 `DirectorService` 导入/实例化与 20 个工具注册、`main.py` 无变化，测试与本文档同日章节一并回退即恢复 24 工具形态；无迁库，已创建的 MCP 授权与既有任务不受影响。

## 2026-11-03 MCP 二采确认与图片参考边界

- 原因与审计：导演台连续重构后（工坊一键生成、二采清晰度策略、H3 数字人 / 动作迁移 / 局部重绘 / 深度），MCP 网关自 2026-10-25 起未同步，暴露两处断点：开启 `refine_enabled` 的任务停在 `awaiting_refine` 而 MCP 没有任何确认入口，客户端只能看着任务停住；参考槽位含视频或音频的 4 个工作流仍出现在 `studio_list_workflows` 里，而 MCP 参考素材只接受 PNG/JPEG/WebP，提交能通过参数校验却在 ComfyUI 侧失败。
- 新增工具：`studio_confirm_refine(job_id)` 确认一采预览并复用同一 seed 只跑二采精修，`studio_skip_refine(job_id)` 把已完成的一采预览直接作为成片。两者复用 HTTP `/api/jobs/{job_id}/refine/confirm|skip` 的处理函数，由 `register_mcp_routes` 注入，不在网关内复制状态机；作用域沿用 `studio:generate`，工具总数 22 → 24。任务不在 `awaiting_refine` 时沿用既有 409「当前任务没有待确认的一采预览」。
- 参考边界：`CreativeService.unsupported_slots()` 以 `WorkflowDefinition.reference_kind()` 判定槽位类型，含 `video` / `audio` 槽位的工作流从 `studio_list_workflows` 排除，`studio_get_workflow` 与创建入口返回 422 并写明「第 n 项需要视频素材 / 音频素材；MCP 连接只支持图片参考」。判定完全取自注册表声明，网关不硬编码工作流 ID，后续再接入含视频的参考工作流无需再改 MCP。
- 协议提示：SDK `instructions` 补充 `awaiting_refine` 的处理路径与「只列出图片参考工作流」，客户端首次连接即可发现。参考上传、剪辑时间线与导出协议不变。
- 兼容：作用域集合未变（仍为 `studio:read` / `studio:generate` / `studio:edit`），已连接客户端重新发现工具即可使用新能力，无需重新授权；`refine_enabled` 默认 false，未显式开启二采的既有自动化行为不变；被排除的 4 个工作流在工作台生成页与 AI 工具中心继续可用，无 SQL 迁移、端口或 ComfyUI 节点变更。
- 受影响文件：`backend/app/mcp_gateway/{service,routes}.py`、`backend/app/main.py`（注入两个 refine 处理器）、`backend/tests/test_mcp_gateway.py`。
- 验证命令：`python -X utf8 -B -m unittest backend.tests.test_mcp_gateway`（30 项通过，含新增 4 项：槽位过滤、二采确认、二采跳过、作用域与跨账号隔离）；`backend.tests.test_local_drama_mcp backend.tests.test_editing_assistant backend.tests.test_smart_edit backend.tests.test_h3_refine` 与后端全量回归、`pnpm --dir frontend build` 通过。无界面改动，未做桌面检查。
- 回滚：撤销两个工具的注册与 `CreativeService` 的槽位判定/新方法，并恢复 `register_mcp_routes` 的注入签名即可；不删任务数据，已停在 `awaiting_refine` 的任务改由工作台页面确认或保留。

## 2026-11-03 片段批量操作

- 原因与页面：单集片段条的外扩描边、绿色角标和草图按钮与即梦不一致。`WorkshopWorkspace.tsx` / `workshop-focus.css` 改为 114×64px 缩略图、10px 间距、8px 标题间距、28px 按钮、缩略图内 1px 描边、右上 20px 点击区内的 16px 黑底白勾。批量模式从零选择开始，整张缩略图切换勾选；普通模式继续切换正文与预览。
- API：新增 `DELETE /api/projects/{project_id}/episodes/{episode_id}/beats`，JSON `{beat_ids: string[]}`；沿用项目会话与 CSRF。返回 `{status, deleted_beat_ids, beats}`。非法/过期选择、删除全部为 400；所选片段或整集有非终态任务为 409。OpenAPI 同步中文说明，并补齐现有 `doc_id` / `episode_id` / `episode_num` 参数说明。
- 持久化：`ProjectDetailService.delete_episode_beats()` 在事务内锁定最新分集，只移除选中 ID；保留其他 Beat 的 ID、sequence、正文、Take 与媒体字段，更新 `shots_count`，清除过期的 `episode_video_url/source/job_id` 绑定。原剧本、资产、云端文件和历史任务不删除。无 SQL 迁移、端口、供应商或工作流变更。
- 前端状态：`api.ts`、`EpisodeWorkshopPane.tsx` 接入真实删除；确认后先 flush 自动保存，再删除，回填剩余片段并选择相邻片段，移除相应本地草稿。`workshop-batch.ts` 排除失效选择并处理相邻选片。失败保留弹窗和勾选；至少保留 1 个片段，空选择与生成期禁用相关按钮。
- 验证：`python -X utf8 -m unittest discover -s backend/tests -q`（1442 项，发现一项既有 OpenAPI 参数说明缺失）；补齐后 `python -X utf8 -m unittest backend.tests.test_workshop_batch_delete backend.tests.test_core.ApiDocumentationTests -q` 16 项通过。`pnpm --dir frontend build`：108 文件 / 708 项通过，类型检查和构建通过。5173 桌面 1920×863 浅暗检查了零选、单选、全选禁删、14/15 选择确认及取消；未删除真实片段或提交视频生成。
- 回滚：选择性撤回本节列出的前端、删除路由/服务、API 文档与测试增量，保留其他并行改动；无需迁库。已确认删除的片段不会因回滚代码自动恢复，应从业务备份恢复。

## 2026-11-03 工坊视频自动准备

- 原因：新版工坊仍先弹出缺少 H3 指令，再进入旧素材组，并强制逐镜三联与再次点击写稿，割裂一次生成意图。本次把准备工作收进现有 video_generation 任务。
- 入口与协议：原 POST episodes/{id}/generate-video 及 beats/{id}/generate-video 不变。prompt_mode=h3 仍为默认，现在接受缺稿/失效稿并在后台补齐正式大模型指令；program 显式预览路径继续独立。新增可选控制参数 prepare_keyframes（布尔，默认 false），属于任务编排动作，不传入 Comfy graph。片段更多菜单「规划关键帧并生成视频」明确启用它，自动等待一份真实三联任务后继续写稿和出片；默认只用已有资产。2026-11-03 晚该菜单项与前端 `prepare_keyframes` 提交已下线（全库普查仅 3 个项目用过三联、当前在做的剧 0 三联）；2026-11-04 后端彻底移除该控制参数：`JOB_CONTROL_KEYS`、payload 写入与 `_prepare_job_prompts` 的等待分支一并删除，未知 option 仍按既有规则静默忽略，所以旧客户端传 `prepare_keyframes` 只会得到默认行为，不会报错。接口路径与其余协议未变。同日 `video_preparation.prepare_video_keyframes` 函数本体与其唯一记账键 `keyframe_jobs` 一并删除（`StoryboardImageService.enqueue` 收敛为 4 参数后已确认那笔改动定稿），写稿链路不再存在等待三联的代码；三联的按需生成仍只走 `StoryboardImageService` 的素材组入口。
- 执行与恢复：复用 LlmService.generate_h3_prompt 和 H3PromptJobService 的正式校验/格式化，不静默回退程序稿。图片与提示词准备发生在 occupy_gpu(comfy) 之前，避免 VLM/GPU 互等。沿用 queued / preparing / prompt_generation / uploading / running 等状态，只在 payload 增加 preparation 与 prompt_generation_progress。每个已完成提示词先写入任务 source_shots，再回填 Beat；失败后按原任务重试，保留已写指令，上游图片继续复用既有付费任务恢复能力。
- 输入与缓存：生成前等待所选片段的自动保存；保存失败、引用非法或本地恢复稿尚未采纳时留在当前页面。任务使用提交时的正文/引用/参数快照。Beat 可选 h3_prompt_input_signature 覆盖正文、台词、真实图片 URL 与顺序、画幅、时长和关键帧；输入变化使自动稿失效，人工保存稿优先。回填采用 expected_fields 的行锁比较，编辑过的正文或人工稿不会被迟到的自动稿覆盖；旧任务缺少编辑基线时只在自身保留稿件。
- 参考图：自动写稿看到的 Picture 顺序与实际上传顺序一致。自动入口必须同时传递 character_ids、character_look_ids、characters[].url 与 scene_id/scene，供既有制作配方再次绑定槽位；第二集实测暴露的漏传已修复，并以真实半解说配方绑定/附图/编号测试覆盖。失败任务保留中英文作者草稿与校验原因，列表不展开长文。默认配方已有三联时采用 start/mid/end 裁切，最多 9 张，整张母图不上传。原制作配方的槽位绑定保持原实现。
- 页面：生成时留在当前片段，显示「整理生成指令」或「正在规划关键帧」及视频阶段；刷新后由真实任务恢复。失败说明与「重试当前步骤」原位显示，新的成功/排队任务隐藏旧失败。重试沿用原提交快照；修改正文后通过生成入口创建新任务。旧表单仅由「高级制作详情」手动打开，更多设置默认收起。
- 批量渲染进度：任务列表从 render_plan.chunks 派生紧凑的 render_progress（total / completed / current），不发送完整 Timeline、graph 或作者草稿。工坊显示「正在生成第 3 / 8 组 · 当前步骤 42%」，避免把会重置的节点百分比误认为整集进度；旧任务无分组信息时兼容原阶段显示。不修改活动任务执行或远端提交协议。
- 实际拆片：H3 时长校准后的帧数可能超出剧本目标秒数。timeline_output_durations 从已提交 Timeline 的 frameCount / frameRate 计算真实跨度，按该跨度拆分选择范围，并更新各镜 outputStart / outputDuration、分组起点和总时长，避免跨组累计偏移；保留正文目标时长。无 Timeline 的旧任务继续使用原秒数。无需重跑已生成的远端视频。
- 渲染缓存恢复：重试成功分组时同时保留 output、timeline、render_request 与 director_report，避免仅保留文件地址后丢失真实帧边界。全部组已有成功输出时只合成和重新拆片，不再次提交 ComfyUI；有专项测试断言零重复提交。
- 帧精度：已知 Timeline 帧率时使用视频 trim 的整数帧索引与相同跨度的音轨 atrim；不把 7/24 秒先四舍五入到毫秒，避免额外切入下一段的一帧。真实红/绿/蓝三段带音轨媒体测试校验 5、7、12 帧数量和边界颜色；旧任务无帧率时保持原秒数拆分。
- 云端保存：第二集 8 组已成功后，七牛固定 30 秒读取超时中断整集发布。保留既有大于 8 MiB 的 V2 分片与三次重试，将分片从 4 MiB 调整为 1 MiB，SDK 请求配置为连接 10 秒、读取 120 秒；实际 Requests 传输层测试验证该超时及 HTTPS。受影响文件另含 qiniu_service.py / test_qiniu_upload.py；不改变 Bucket、域名、凭据或对象 URL 协议。失败后同一任务复用全部成功分组，只继续合成和拆片；回滚时可选择性恢复上述两项上传默认值。
- 受影响文件：backend/app/media_studio/services/{video_preparation,episode_video_service,project_detail_service,job_payload}.py；frontend/src/director2/{workshop-h3-gate,workshop-video-progress}.ts 与 panes/{EpisodeWorkshopPane,WorkshopWorkspace,Director2VideoSettingsPopover}.tsx；新增 backend/tests/test_workshop_video_preparation.py、对应前端测试与 .gitignore 测试白名单；api_documentation.py 与四份说明文档。
- 兼容性：无 SQL/端口/供应商/模型/Comfy 节点迁移，不增加队列状态，不修改已生成的视频与历史版本；旧客户端缺稿提交现在会异步准备，而非收到 400。可选 JSON 字段由旧客户端忽略。
- 验证：python -X utf8 -m unittest discover -s backend/tests；python -X utf8 -m unittest backend.tests.test_workshop_video_preparation backend.tests.media_studio_test_h3_video.EpisodeVideoPromptModeTests backend.tests.media_studio_test_h3_video.H3PromptTests -q；pnpm --dir frontend build；真实 5173 桌面浅暗主题及刷新恢复。最终完整回归 1494 项（1 跳过），准备/提示词专项 97 项，前端 109 文件 / 720 项和构建通过；真实任务 job-83da4d8c1664 已完成、自动回填且可播放，未生成三联，远端提交一次。初轮完整回归的同期新增剧本接口文档参数失败已在最终回归通过。截图见导演台快照同日章节。
- 回滚：等待活动视频任务结束，选择性移除本节的自动准备调用、可选规划入口、保存等待/原位失败显示及新增 helper，恢复旧缺稿校验；保留 Beat/任务里的生成稿、签名与全部媒体，旧版本会忽略附加字段。不要整文件回退同期剧本、资产画布或批量删除改动。
- 第二集完整制作验收：proj-a342bfd034eb4b20 / ep-abd1a4a1f072 / job-4891e7a90fc2；15 / 15 回填，4631 帧 @24fps，共 192.958 秒。8 组原片生成后，存储中断通过同一任务恢复，新增视频/提示词调用均为 0。真实大文件以 1 MiB 分片和 10/120 秒超时保存成功。15 段均校验帧数、音轨与时长，另有整集，本地 videos-v001 共 16 个 MP4；制作记录位于 data/director-production/proj-a342bfd034eb4b20/episode-2/manifest-v001.json。第一集仅补齐原日常造型引用，正文及 6 条原视频保留。桌面双主题、首/中/尾、连续换片、自然结束和整集预览均已检查；最新后端 1494 项（1 跳过）、存储 9 项、前端 109 文件 / 720 项及构建通过。


## 2026-11-03 剧本阅读、分集菜单与提取说明（当前细节基线）

- 原因：补齐即梦实测的只读设定、正文左对齐、分集管理和提取前说明，防止修改已进入制作的集数破坏资产引用。
- 界面：故事设定由 Ant Design Form / Input / TextArea 只读展示集数、目标受众、核心梗、故事类型、一句话故事、故事梗概；优先取已存结构或原文标签，缺项显示「未提供」。正文与标题左边线对齐，按集折叠；全局 Dropdown 为「上传文件·解析新集 / 新建一集 / 下载剧本」，未锁定集的悬停 Grip 菜单为「删除本集」，删除前确认。
- 状态与协议：沿用 analysis，新增 assets_extracted_episode_nums；资产拆解成功后以 JSON_SET 只标记当前正文集号，并校验 raw_text，避免覆写其他元数据。文档列表增加 locked_episode_nums、episode_lock_reasons；既有制作分集按集号及 source_document_id 兼容推导锁定。资产已拆解的集禁止修改/删除，已有制作工坊行亦锁定。追加新集与未锁定集的按集编辑可以和其他集出片并行；设定、资产及显式旧版整份替换仍受原任务互斥保护。预览和应用各自重新检查锁定，全文编辑亦检查锁定并对 analysis_json / raw_text 做并发校验。
- 分集操作：POST /api/projects/{p}/documents/{d}/episodes 新建大纲占位，集号取现有正文与大纲的最大号加一；PUT 原文档接口传 episode_num 可填写该占位正文。DELETE .../episodes/{n} 只移除未锁定的正文/大纲，保存 script_revision 旧稿；其他集原文与制作数据保留，不重排集号。新增、删除均要求 base_raw_text；服务端持有项目事务及文档行锁。
- 提取说明：底栏「提取能得到啥？」打开 960px Ant Design Modal，包含三项实际能力、三套角色造型示例、办公室/晚宴厅/出租屋三组全景/中景/特写、固定底部入口。示例 WebP 本地化在 frontend/public/director-extraction，sources.json 记录用户指定参考页及公开图片来源。示例明确标注，未复制积分、节省时长或自动出图承诺；拆解沿用原 append 接口，参考图在资产库生成。
- 受影响文件：script_documents.py、actions.py、project_detail_service.py、project_router.py；前端 api.ts、script-document.ts、ScriptWorkspace.tsx、script-workspace.css；对应测试、示例资源、API/助手/流程/README/扩展指南。
- 验证命令：python -X utf8 -m unittest backend.tests.test_director_assistant backend.tests.test_standard_script_parser backend.tests.test_director_project_info backend.tests.test_document_analysis_recovery -q；pnpm --dir frontend build；Impeccable detector。5173 桌面检查双主题、只读字段、集锁定、菜单、删除取消、上传弹窗与三组场景示例。快照位于 design-ref-director/script-episodes-20261103/，不在真实项目执行新增/删除或资产拆解。
- 本轮结果：后端定向 156 项、前端 107 文件 / 702 项及 TypeScript / Vite 构建通过；5173 桌面双主题验收完成。真实项目仍为一份主稿、两集，第一集原文与解析、来源原文、完整制作行及资产行均与修改前一致，摘要见 design-ref-director/script-episodes-20261103/details-verification.json。
- 兼容与回滚：不新增数据库列、依赖、端口、模型或工作流。旧 analysis 无标记时仍按制作行推导锁定；新字段可被旧客户端忽略。仅撤回本节代码、资源与文档增量并刷新前端/重启后端，保留原文、script_revision、资产与成片；需要恢复已删除集时先核对当前稿再从旧稿恢复，不批量回滚同期修改。

## 2026-11-03 首页风格库与选题

- 原因与行为：按即梦剧本创作的真实公开面板补齐风格、选题。`creative-presets.json` 保存原名称、原风格 ID、分类及三套受众词库；100 张原始 WebP 封面本地化于 `frontend/public/director-presets/styles/`，合计约 2.7 MB。预设为真人实拍 52、2D 25、3D 23，另有「无」；选题除 3 个受众选项外，泛人群 103、男频 110、女频 123 个分组选项，保留各组次序和重复名称。
- 前端状态：`HomeCreativeOptions.tsx` 直接组合 Ant Design Popover、Tabs、Input、Radio、Checkbox、Modal；`CreativeStyle` 保存预设 ID 与自定义草稿，`StoryTopics` 按六组保存。受众单选，其余多选；搜索／切换受众保留已选标签，逐项移除。风格默认「无」，自定义确认后生效、取消保留原选择；自定义上限 1000 字，以匹配助手消息约束。`HomeCreationPanel.tsx` 继续共用风格、比例、集数，四入口正文各自保留；剧本诊断不显示创作选项。
- 提交与存储：`home-creation.ts` 将解析后的视觉风格和分组词写入真实创作／改编首条消息，明确用于画面、人物、场景和道具设计；项目 extra 沿用 `creative_style`，增补 `creative_style_preset_id` 与 `story_topics`。导入仅保存设置，原文直接入库；小说原文独立保存。只选选题可发起创作。正文上限按完整消息动态扣除选项与改编要求，保留 50,000 字契约和超限反馈，不截断输入。
- 视觉与来源：公开页面 `https://jimeng.jianying.com/ai-tool/novel`，采集日期 2026-11-03；只采集可见名称、分类、选题与原封面，未复制私有提示词或服务接口。530px 浮层、四列封面、三列选题、12px 风格标题与 13px 选题按 CSS 实测落地，门户弹层使用成对 `--director-preset-*` token 继承根主题；修改前核对官方 Prompt Bar 与 globals.css。最新桌面截图及参数在 `docs/design-ref-director/home-agent-20261103/style-topic/`。
- 文件：`frontend/src/director2/{HomeCreationPanel,HomeCreativeOptions}.tsx`、`creative-presets.{json,ts,css,test.ts}`、`home-creation.{ts,css}`、本地封面，以及 README、功能指南和导演台流程快照。
- 兼容性：无 API、数据库列、依赖、端口、队列或 ComfyUI 变更，旧 `style` 字符串请求仍可用；未带新 extra 字段的工程照常读取。
- 验证：`pnpm --dir frontend build`（107 文件／696 项、TypeScript 与 Vite 通过）；集成包 Python 运行 `backend.tests.test_script_diagnosis backend.tests.test_director_assistant backend.tests.test_director_project_info -q`（135 项通过）。5173 桌面 1920×863，检查浅暗主题、分类、空结果、搜索保留、多选、受众切换、标签移除、自定义取消／确认和正文区域。实际创作验收项目 `proj-6949f2b684ab4106` 的首条消息包含所选风格与三组标签；共享服务重启中断后在同一会话重试成功，返回《末班电话·故事方向与视觉设定草案》，正文明确采用所选画风、悬疑与规则怪谈。未采纳或提交媒体生成。
- 回滚：只撤回本节首页组件、目录和提示词增量，并恢复原四项风格 Select；保留既有项目、会话与原文。新 extra 字段可保留，旧版本忽略；不回滚同期其他工作。

## 2026-11-03 制作资产共享画布（当前资产编辑基线）

- 原因：制作资产卡仍进入旧表单，与即梦的列表 → 定位画布 → 节点创作流程脱节。现 `AssetsLibraryPane` 保留列表及原控制器，选中资产时挂载 `AssetCreationCanvas`；旧表单 JSX 留作兼容存档，主路径不挂载。`?asset=` 旧链接兼容，新交互同时写入 `view=canvas`；返回列表先刷清待保存数据。
- 状态模型：`asset-canvas-model.ts` 从同一批 `ai_project_assets` 派生档案、原片参考、角色 look、场景主视角/反打/全景、道具主图/三视图/特写。节点 ID 为 `assetId::key`，look 继续使用原 identity ID。缺省布局按创建时间和 ID 排序，避免资产按更新时间返回时换位。无 look 的旧角色使用确定性初始造型，写入时才补身份数组；旧图片、声线、提示词继续保留。
- 持久化：可选 `extra.creation_canvas={version:1,positions:{key:{x,y}},links:[{sourceAssetId,sourceKey,url}]}`；视角名称存 `extra.canvas_node_names`，档案正文存 `extra.canvas_definition` 并同步资产 description。相机偏好按项目保存在 localStorage。跨资产连线把当时图片加入目标 `source_references`，明确为参考图快照，源图日后重生成不会自动替换已绑定快照；不引入第二份项目或 SQL 表。
- 保存与异步：防抖保存队列按资产 ID 合并，保留失败快照供重试，避免快速切换丢掉前一个资产。图片请求按原资产及槽位回填，只合并媒体字段；后端供应商调用结束后重新读取资产，保留生成期间保存的设定、参考图和节点位置。角色身份图片同时回填 object_key。画布每 5 秒读取既有项目任务，恢复进行中节点而不重提任务；精简任务列表补回 `identity_id`，失败原因在对应创作面板显示，任务列表首次读取失败时先保留生成锁。
- API：新增 `POST /api/projects/{project_id}/assets/{asset_id}/images`（multipart：`file`、`target_type`、可选 `identity_id`），沿用 mutating_user。支持 identity / scene_master / scene_reverse / scene_pano / prop_reference / prop_turnaround / prop_detail；先校验类型与身份，再校验真实 JPEG/PNG/WebP/GIF、非空且 ≤10 MiB，上传七牛，只更新指定制作槽位，主图仅在主槽或首造型时同步。原片参考仍走既有 source-reference 接口，不混入成品图。
- 主要文件：`frontend/src/director2/{asset-canvas-model,asset-generation-result,api}.ts`、`panes/{AssetsLibraryPane,AssetCreationCanvas}.tsx`、`panes/assets/AssetCanvasVoiceModal.tsx`、`panes/asset-creation-canvas.css`；`backend/app/media_studio/routers/project_router.py`、`services/{project_detail_service,job_payload}.py`。新测试为 `asset-canvas-model.test.ts`、`test_asset_canvas_upload.py`，媒体归属回归更新 `asset-generation-result.test.ts`。
- 兼容性：旧 assets 查询、现有 generate/voice/参考图接口、分镜中的 asset/identity ID 均保留，无数据库、队列、工作流、端口或供应商迁移。即梦 3D、超分、通用视频等工具未伪接到资产节点；当前画布提供本平台已有的角色/场景/道具制作能力。
- 验证：`python -m unittest discover -s backend/tests`；`pnpm --dir frontend build`（测试、TypeScript、清理 dist 与 Vite）。5173 默认桌面 Chrome 实测同项目 4 项资产，旧资产 URL 不挂载表单；档案编辑刷新保留、位置拖动保留、场景名称保存、一次 prop_detail 真实生成并回填、同图上传替换且 source_references 仍为 0、音色目录与素材库可达、浅暗主题和继续进入分镜。截图索引见导演台快照。
- 回滚：仅撤回上述文件本次资产画布、上传端点、精简任务字段与媒体合并增量，恢复旧详情分支后执行 `pnpm --dir frontend build`。可选 extra 字段可保留供旧版本忽略；不删除资产、图片、剧本、分镜或历史成片，不整文件回滚并行改动。

后端完整回归 1419 项（1 项跳过）；前端 107 个文件 / 695 项测试、TypeScript 与 Vite 构建通过。

- 2026-11-03 右键补充：`AssetCreationCanvas` 使用原生 Ant Design `Dropdown` 的 contextMenu 触发器与「添加节点」子菜单，复用已有角色/场景/道具创建流程；仅空白与组留白响应，输入框、图片节点和画布控件保留原有右键。菜单继承根主题、自动避让视口边缘，Esc / 点击画布 / 移动视口可收起，另含资产库与适应全部快捷入口。
- 创建位置：右键时通过 ReactFlow `screenToFlowPosition` 转换鼠标坐标，`AssetCanvasActions.create` 增加可选 position。控制器用 transient ref 保存到提交/取消；提交仍调用现有 POST assets，只追加既有 `extra.creation_canvas.positions.group`。取消或顶部入口清空待用位置，不新增状态版本、API、表或队列。受影响文件仅 `panes/AssetCreationCanvas.tsx`、`panes/AssetsLibraryPane.tsx`、`panes/asset-creation-canvas.css`。
- 补充验证：`pnpm --dir frontend build` 为 107 文件 / 702 项、TypeScript 与 Vite 通过；`python -X utf8 -m unittest backend.tests.test_asset_canvas_upload backend.tests.test_asset_source_references -q` 为 29 项通过。5173 内置浏览器实际 1379×776 桌面双主题，右下边缘主/子菜单均未越界；55% 缩放和平移下右键创建验收角色「夜班客人」（`ast-33fd4f78e428`），预期组坐标约 (2130.076, 218.773)，刷新前后 DOM 组坐标保持 (2130.08, 218.772)。只在既有验收项目中新增节点，没有提交媒体任务。
- 补充回滚：仅移除上述右键 Dropdown、capture/关闭事件和可选创建坐标入参，保留顶部新增及现有已保存位置；不删除验收资产或同期其他改动。


## 2026-11-03 主剧本与分集采纳（当前基线）

- 原因：此前 `script` 草稿只能新建文档或整份替换，续写第二集被保存为另一份剧本；目录又按文件展示。仅放开生成任务互斥不能修复分集归属。本次以即梦实际追加第二集的大纲、正文和资产更新提示为流程依据。
- 存储：沿用 `ai_project_documents`。主剧本 `analysis.primary_script=true`；未标记旧工程以最早文档为主稿。全剧设定保存于 `story_setting_text`，分集大纲在 `episode_outlines`，正文仍为 `raw_text` 与 `analysis.episodes`。续写按明确的 `# 第N集：标题` 追加；更新按集号替换原文区间，保留其余原文、解析对象与全剧设定。大纲与正文分开保存，只有大纲的集在界面标为「正文待创作」。
- 采纳协议：原预览/应用 API 保留；`mapping.script_action` 为 `append_episodes`（默认）、`update_episodes`，显式旧版整份替换映射继续兼容。`script.data.section` 默认为 `body`，`setting` 写全剧设定；`episodes` 草稿默认写主剧本大纲，`storyboard` 继续写制作工坊。旧客户端显式 `episode:N` 映射沿用旧工坊写入路径。正常界面移除新建独立文档/整份覆盖选项。重复集号须明确选择更新；无集标题的续写被拦截，首次单集稿保留兼容。
- 并发与恢复：项目行锁、草稿版本、目标完整哈希及采纳幂等保留；两份初次预览不能创建两份主稿。新增正文和未锁定集的按集更新可与普通媒体生成并行，同文档解析/镜头规划仍拦截；锁定规则见本页细节基线。设定修改与显式全文替换继续受生成任务保护。助手采纳、按集编辑及合并已有主稿前，以既有助手记录表的 `script_revision` 保存旧文档；正文变更标记受影响集数，提示核对大纲/资产，制作分集、Beat、Take 和成片均不自动改写。工程上下文提供主稿标识、分集摘要和最新集末段，避免长剧续写只读到开头。
- 历史稿合并：新增 `POST /api/projects/{project_id}/script/consolidate`，请求 `{document_id, source_document_ids}`，沿用会话/CSRF。一次事务合并，不同集号追加；冲突整批回滚；源文档原文不变，标为 `status=merged` 并记录 `merged_into_document_id`，正常列表与助手上下文过滤来源稿。重复合并幂等。编辑接口 `PUT .../documents/{doc_id}` 增加可选 `episode_num`，按集编辑并校验 `base_raw_text`；集号错误 400，版本冲突 409。全文编辑仍保留独立设定、大纲及未改集解析对象。
- 界面：目录只显示「剧本」与三个分区；正文使用 Ant Design Collapse 按集展开、编辑，保留全文编辑与未保存草稿恢复。导入分集接到主稿，旧独立稿提供「合并分集」。不改助手视觉 token、依赖或移动端布局。
- 文件：`backend/app/director_assistant/{actions,protocol,script_documents}.py`、`media_studio/routers/project_router.py`、`services/project_detail_service.py`、`backend/tests/test_director_assistant.py`；`frontend/src/director2/{api.ts,script-document.ts,script-document.test.ts,panes/ScriptWorkspace.tsx,panes/script-workspace.css,assistant/ArtifactDialog.tsx,assistant/api.ts}`；主文档、API、助手说明与截图索引。
- 验证：`python -X utf8 -m unittest backend.tests.test_director_assistant backend.tests.test_standard_script_parser backend.tests.test_director_project_info backend.tests.test_document_analysis_recovery -q`，148 项通过（集成包运行时显式将工作台根目录加入 `sys.path`）；`pnpm --dir frontend build`，106 文件 / 687 项、TypeScript 与 Vite 通过；Impeccable detector 无发现。5173 桌面双主题检查目录、两集展开、第二集编辑范围与取消；参考截图见 `design-ref-director/script-episodes-20261103/`。
- 实际数据验收：`proj-a342bfd034eb4b20` 的主稿 `document-3290d9a8e0c14713bab3cbb832a0ad68` 已包含 1、2 集，来源 `document-f9aafda58b184ca493abe7cab5a4b312` 保留原文并归档。合并前后第一集解析对象、完整制作分集行和全部资产行哈希均一致；未生成或重提媒体任务。验证摘要随参考截图归档。
- 兼容与回滚：无表结构、工作流、节点或供应商迁移。回滚仅撤回上述本次增量并刷新/重启；代码回滚不自动拆回已合并正文。若需恢复数据，先核对新版本，再从 `script_revision` 恢复目标旧稿与源状态；保留所有媒体、任务 ID 和同期其他改动。

## 2026-11-03 H3 原生视频编辑试验（minimax-h3-video-edit）

- 原因：用户要求在已通过的 SCAIL 双人成片上，直接测试 H3 视频生视频换为白天江边背景。此前 H3 R2V 只连接图片参考，动作/深度分支不能代替完整视频编辑。
- 基线：独立 JobMode、graph 和隐藏工作流；`/tools/video-edit` 是可恢复任务的试验页面，暂不添加工具卡片或通用模型选择项。references 恰好 1 段原片，显式 reference_slots=(video,)，现有 multipart 接口、属主校验、云端归档和串行任务队列不变。
- 工作流：平台在临时目录截取开头片段并对齐 24fps，缩放至不超过 512×896 像素预算、宽高 32 对齐；LoadVideo/GetVideoComponents 完整帧序列进入 MiniMaxH3ReferenceToVideo.ref_videos.ref_video_0，采用现有 INT8 Ref2VA、20 步原生采样，无骨架、深度或 SAM3 控制。CreateVideo 直接连接预处理原片音轨，关闭保留原声时不连接音轨，不解码或采用生成 BGM。5/10/15 秒档为 124/243/362 帧，原生 5 秒档实际 5.167 秒。首轮 v009 曾以 384×672 试片，用户复核远景女主脸偏糊；本次按用户要求恢复原片 512×896，避免再次缩小参考。
- 参数：注册表保存时长、保留原声（primary）、种子（advanced）、模型文件/采样/参考尺寸/画布/帧率（internal）。固定种子贯穿提交、执行及恢复；提交侧探测画布并保存有效快照。新节点位于新 graph，不修改已有 H3/SCAIL 节点 ID。前端复用既有单视频表单布局和 Ant Design 控件，仅增加模式与文案配置、布尔开关，旧深度工具默认行为不变。
- 文件：backend/app/h3_video_edit_workflow.py、models.py、workflow_registry.py、comfy_service.py、main.py；frontend/src/tools/DepthCaptureTool.tsx、ToolsWorkspace.tsx、paths.ts、App.tsx；backend/tests/test_h3_video_edit.py、frontend/src/tools/depth-capture-tool.test.tsx，以及 README、本节、扩展指南、API 与既有 ACCEPTANCE。
- 兼容性：无依赖、模型下载、数据库、端口、供应商、远端实例或队列协议迁移；沿用实际 ComfyUI 地址。功能处于试验阶段，生成成功不代表人物和舞步保真。
- 验证：`python -X utf8 -m pytest backend/tests/test_h3_video_edit.py backend/tests/test_h3_depth.py backend/tests/test_h3_inpaint.py backend/tests/test_scail2_replacement.py -q`（最终 41 项通过）；`pnpm --dir frontend build`（106 文件 / 687 项、TypeScript 与 Vite 通过，保留既有大包提示）；5173 桌面上传、原声开关、更多设置与单次提交已实测。平台任务 YsHJ4Zir0v6 的重新编辑恢复原片预览、提示词、种子 1373133514 和 BGM 开关一致。实际 5.167 秒换景已完成，背景替换成功、双人和主要动作保留，人物细节与少量动作存在重绘差异；原 BGM 零偏移相关系数 0.99950865。平台下载与远端原生 SHA256 一致，无平台外修片；未生成新的完整片。实际图、视频和判定见 ACCEPTANCE，不据任务 success 宣称人物完全不变。
- 回滚：只撤回本节列出的新模式、graph、分发/恢复及试验路由和表单可选配置；保留历史任务、媒体、旧工作流与同期无关修改。已有已提交 graph 按任务快照恢复。
- 原尺寸与智能高清复测 v010：提高 h3_video_edit_workflow.py 的像素预算及注册表默认画布，保留原片、提示词、种子 1373133514、20 步与原 BGM；平台任务 3UOTTR8nWgaY 已完成，实际文件及内嵌 graph 均确认 512×896 / 124 帧。随后按用户选择，从成片更多菜单用既有 SeedVR2 工作流做 2x 智能增强，任务 Qn9YX6Sp1YWu 已完成 1024×1792 / 24fps / 124 帧 / 5.167 秒原生文件，女主清晰度明显提升但部分运动帧仍有重建纹理与嘴部细节波动，未判为完全稳定。两阶段均由平台执行；H3 下载、远端原片及 SeedVR2 实际输入 SHA256 均为 6b7e8340568fb671641980a0ba752e1a5b121cd9044f808ec9ca05bd40299059，高清下载与远端原生 SHA256 均为 65c75d45258cf4ea168a89248943710505f89947e8fc9844f86a607f1f6cbd7d，原 BGM 对原片零偏移相关系数 0.99872712。原尺寸专项 6 项、前端最终 107 文件 / 702 项、TypeScript 和 Vite 通过；实际视频/对照与限制见 ACCEPTANCE，不平台外修片，也未生成新的完整片。旧 v009 清晰度失败保持有效。若仅撤回分辨率增量，恢复预算和默认画布至 384×672，并保留已提交快照与媒体。
- 成片智能高清入口：本次发现 VideoUpscaleTool 的独立上传路径仍被通用提交接口拒绝，未创建增强任务；不为该尝试更改后端保护。App.tsx、media/VideoStudioModule.tsx 补回原生成片菜单的 SeedVR2 2x 接跑，调用既有 /api/jobs/{job_id}/upscale，复用原输出定位、归档和队列；video-upscale.ts 的 canUpscaleRound 与对应测试限制为可操作、整体成功原片的最新轮次，避免旧轮次指向新原片，禁止对增强结果重复增强，并在请求中/已有活动增强时禁用。无新 API、节点、模型或数据库迁移；独立上传页面不兼容仍是已知限制。撤回本条只移除可选菜单回调、mutation、资格函数和测试，已有增强任务/媒体保留。

## 2026-11-03 新增剧本文档不再被同工程生成任务阻塞（历史修复）

- 原因：`AssistantRepository.project_transaction()` 对同工程所有活动生成任务统一互斥，导致第一集出片期间，第二集选择「新增一份剧本文档」也无法预览或采纳。
- 当前基线：`ProjectActions.preview()` 仅对 `script` 且未映射已有文档的新增操作放行普通生成任务；`apply()` 根据服务端保存的变更计划再次确认全部为新增文档。保留同一项目行锁、草稿版本与目标哈希校验、采纳幂等，以及旧版 `ai_pipeline` 和进行中的 `media_execution` 保护。更新已有剧本或采纳资产、分集、分镜仍使用原生成任务互斥。
- 受影响文件：`backend/app/director_assistant/{actions,repository}.py`、`backend/tests/test_director_assistant.py`、README、扩展指南、导演台流程快照与助手 V2 说明。
- 兼容性：不改 API 路径/字段、表结构、队列状态、ComfyUI、前端状态或样式；不取消、重提或改写既有生成任务，无数据迁移。
- 验证：`python -X utf8 -m unittest backend.tests.test_director_assistant backend.tests.test_standard_script_parser -q`，109 项通过；`pnpm --dir frontend build`，104 文件 / 673 项、TypeScript 与 Vite 通过。新增回归覆盖全部 9 种活动生成状态、预览后开始生成、重复采纳、旧稿覆盖保护和分集保护，原旧版 AI/媒体提交保护测试继续通过。真实 5173 桌面工程 `proj-a342bfd034eb4b20` 的第二集草稿已显示新增预览与可用采纳按钮，未执行真实采纳或付费生成。
- 回滚：仅撤回本节所列后端文件和测试的新增文档豁免；后端自动重载恢复全工程互斥。保留已有文档、预览、媒体与同期无关改动。

## 2026-11-03：导演台四入口与小说原作保存

- 原因：将首页创作起点统一为导入剧本、剧本创作、小说改编和剧本诊断，同时按即梦实际 CSS 修正输入区细节。
- 前端状态：`home-creation.ts` 定义四种模式、独立正文/文件名/改编要求/读取状态和错误；创作参数继续共用。文件提取请求捕获所属模式和版本，旧响应不能覆盖其他入口或已移除的文件。文本不静默截断；创作/小说原文上限 48,000 字，为助手 50,000 字消息契约保留要求空间；直接导入上限 500,000 字，诊断上限读取既有 capabilities。
- 小说提交：`HomeProjectRequest.adaptation` 是可选的前端请求上下文。既有 `createProject` 的 `extra.source_material` 保存 `{kind: "novel", name, text}`，原作与改编要求分别保存/组织，原作不会先作为剧本文档导入。助手首条消息使用小说改编要求和原文，沿用会话/消息幂等协议；生成稿通过既有预览/采纳新增独立文档。项目工具新增只读「查看小说原作」。
- 诊断提交：复用 `/api/script-diagnoses/capabilities`、`/extract` 与创建接口；提取不调用模型，诊断创建使用内容签名对应的 `client_request_id`，成功跳转现有 `?id=` 报告。`/director/script-diagnosis?history=1` 可从首页直接打开诊断历史。诊断不会创建短剧项目。真实验收遇到一次报告 GET 500，任务实际已完成；旧页 catch 后停止轮询。现仅对网络错误、408、429 和 5xx 在 5 秒后重新读取同一记录，永久 4xx 不循环，不重建诊断任务。
- 兼容性：端口、API 路径、SQL 表结构、ComfyUI、生成队列与既有工作流不变；`source_material` 是既有项目 extra 的可选字段，旧项目无此字段仍正常打开。原作不进入后续剧本解析和资产拆解，只有采纳的改编稿进入制作流程。
- 受影响文件：`frontend/src/director2/{HomeCreationPanel.tsx,home-creation.ts,home-creation.test.ts,home-creation.css,director-home.css,Director2StudioHome.tsx,ProjectFlowShell.tsx}`、`assistant/DirectorAssistant.tsx`、`script-diagnosis/ScriptDiagnosisPage.tsx`；文档与参考截图同步更新。
- 验证：`pnpm --dir frontend build`；集成 Python 3.10 显式将工程根加入 `sys.path` 后执行 `python -X utf8 -B -m unittest backend.tests.test_script_diagnosis backend.tests.test_director_assistant backend.tests.test_director_project_info -q`（117 项通过）。5173 桌面实测四入口切换、文档提取、改编要求、原作持久化、改编稿新增采纳及采纳后原作回读、诊断报告、历史入口和浅/暗主题。实际验收对象及截图见 `docs/design-ref-director/home-agent-20261103/four-modes/verification.json`；未提交媒体生成。
- 回滚：仅撤回本节列出的四入口、可选 adaptation/source_material 接线与样式增量；无需数据迁移，已保存原作和已采纳文档可保留，存量项目仍可打开。

## 2026-11-03 动作迁移参考遮罩孔洞与双人排除点修复

- 原因与证据：v004 调度修正并未解决黑点。新增平台原生预览后，v005 的参考遮罩和黑底抠图在生成前已丢失男主头发，并在脸部/衣服上形成孔洞；仅改为完整参考图不能消除坏遮罩。v006 通过页面补选头发、脸部和衣服后男主恢复，但另一人接收的自动排除点从 2 个增至 9 个，其遮罩和成片又出现相应黑块。当前判定为已观察到的输入质量缺陷，结果按实际试片验收。
- 当前接线：保留所有旧节点 ID 和最终视频输出 46；38 的视觉编码图、40 及续接的 reference_image 均接原图 3，reference_image_mask 仍由 10 原生提供，原生 WanSCAILToVideo 内部执行人物抠图。21–23 留作旧抠图对照，不再进入生成。追加 60–68 保存完整图、旧抠图、分色参考遮罩、视频首帧遮罩及每个人的初始 MASK，均为 ComfyUI 原生节点；单人不建立第二人分支。预览在远端既有 output/scail2_diagnostics/<上传图名>/ 保存，仅用于只读排障，不作为 API 成片或上传云端。
- 点选规则：新增 subject_prompt_points()，保留当前人物全部正点和手动排除点，仅取每个其他人物的首个正点作为自动排除锚点，补点不再增加其他人的负点。原始坐标与 subject=0/1 协议、20 点上限、参数层级和任务回显不变。选择器说明要求在头发、脸部、躯干等可见区域补点，提醒深色头发与衣服；继续使用原 Ant Design 弹窗。
- 进度：SamplerCustom 按采样节点解释；上述诊断 SaveImage 按准备阶段解释，避免预览输出被当成 90% 视频导出。其他 SaveImage 与既有流程不变。
- 受影响文件：backend/app/scail2_workflow.py、comfy_service.py，backend/tests/test_scail2_replacement.py，frontend/src/tools/MotionSubjectPicker.tsx；本节、README、扩展指南和原 ACCEPTANCE。无依赖、模型、供应商、数据库、端口、队列或 API 字段迁移，沿用实际配置的单个远端实例。
- 验证：专项 pytest 三文件 37 项通过，test_core.py -k "comfy_progress or comfy_loader" 2 项通过；pnpm --dir frontend build 为 103 文件 / 667 项、类型检查及 Vite 通过。5173 桌面点选弹窗与任务恢复已检查。双人 5 秒任务 JDSshIb1SaiU 已通过：原生预览确认正点 4/11、自动负点 1/1，人物遮罩无孔洞，成片头发/皮肤/服装/手腕干净，原 BGM 零偏移相关系数 0.99937814。种子 1373133514、用户提示词为空；原片 SHA256 b3c61bbf2d847c7726beb2808c151e164f7e86870e9fc417044c2cc1dcf377d1。之后从页面恢复同素材/标记，仅改为完整原片并提交一次任务 PyspmC2NUNl，已完成并通过只读视觉复核：512×896、16fps、242 帧、15.125 秒，每半秒及三处续接前后帧未见原黑点/遮罩孔洞或明显跳变；尾段小狗经原视频对照确认原本存在。原 BGM 相关系数 0.99922054，平台下载、保留副本及远端原生 scail2_replacement_00007_.mp4 的 SHA256 均为 6847a95a35552c72ff9ee50aac1d345481197c2a7daf8f61b57ee28dbf23767b，未外部处理。定时任务 automation-7 已删除，不归档聊天。连续实验与证据见 ACCEPTANCE。
- 回滚：仅撤回本节列出的输入接线、自动排除锚点、诊断节点、进度和提示文案增量，不改输出 46、已提交 graph、既有媒体及他人同期改动。历史任务继续按原 graph 恢复，无数据库或供应商回滚。

## 2026-11-03 导演台实走修复：剧本解析、资产回写与图片恢复

- 原因：从首页新建短剧的实际回归发现紧凑生成稿解析为零资产、比例未承接、资产选择变化后异步结果串位，以及上游已生成的图片在本地回写失败后重新扣费生成的风险。
- 数据边界：`StandardScriptParser` 扩展既有 JSON 结构的格式兼容；原始正文保持不变，旧零分集分析沿用按需恢复。空资产拆解返回可处理的 400。占位名“未命名短剧”纳入自动命名范围；制作说话人使用对白中的真实角色。
- 前端状态：`asset-generation-result.ts` 对请求资产 ID/类型验证后仅合并媒体字段；选中对象与排队自动保存稿按相同 ID 更新，保留本地文字修改。详情选择写入现有 `?asset=`。工坊读取项目比例作为首次默认值，本地制作设置继续覆盖默认。
- 预览布局：`panes/workshop-focus.css` 将视频定位在比例画布内，修复竖屏全片预览的 grid 原生高度溢出与裁切；不改视频尺寸或媒体文件。
- 图片队列：`StoryboardImageService.retry` 在失败任务已有上游 ID/存储输出时复用任务并恢复；完成后的主动重做仍走新生成。`_run` 保留失败时的上游与媒体信息，已存储三联分格可直接完成回写。`QiniuService` 配置 SDK 的默认 HTTPS zone，使表单上传与分片上传实际使用 HTTPS。
- 测试隔离：`main.py` 的 MySQL 媒体队列恢复仅在 MySQL runtime 启动；`media_studio/db.py` 禁止隔离测试新建真实 MySQL 连接。配方/VLM 单测补齐配置 mock，避免 SQLite 测试应用启动扫描真实媒体任务。H3 生成内容在前端按发起片段 ID 显示。
- 受影响文件：`backend/app/main.py`、`backend/app/media_studio/db.py`、`backend/app/media_studio/services/{script_parser,project_service,project_detail_service,storyboard_image_service,qiniu_service}.py`；`frontend/src/director2/{asset-generation-result,project-video-resolution}.ts`；导演台剧本、资产与工坊组件及对应测试。
- 兼容性：没有数据库迁移、路由/端口变更或工作流节点变化，返回结构保持兼容；恢复任务额外返回 `resumed: true`。不自动替换现有资产设定、分集或媒体。
- 验证：集成包 Python 运行 `unittest discover -s backend/tests`（1,385 项，跳过 1 项），覆盖紧凑剧本/说话人引用、跨资产结果、图片恢复、真实 SDK HTTPS 与测试隔离；`pnpm --dir frontend build`（667 项测试与构建通过）；5173 桌面实走《雨夜留灯·流程验收》。具体快照见 `导演台流程与界面结构.md` 同日实走章节。
- 回滚：仅撤回上述文件本节增量，保留已有项目、任务与媒体；无配置、供应商或数据迁移回滚。

## 2026-11-03 即梦式图片工具族上线（去背景/图层分离/图片编辑/局部重绘/消除笔/扩图）

- 原因：对标即梦图片面板补齐图片编辑能力。此前 `media_type=image` 的工作流只能经 GRS 目录执行器（`worker.execute_image` → `grs_client`），ComfyUI 侧只有视频分发；图片工作流没有遮罩、扩图等编辑语义。
- 路径一（ComfyUI 图片工作流，`is_comfy_image_workflow`）：`image-background-remove` / `image-layer-split`。graph 构建器 `backend/app/image_edit_workflow.py`：LoadImage → `CheckpointLoaderSimple(sam3.1_multiplex_fp16)` → `CLIPTextEncode(主体描述)` → `SAM3_Detect(conditioning 文本概念提示, individual_masks=False)` → `InvertMask` → `SaveImageWithAlpha(原图 RGB + 反相 mask 作 alpha)`；图层分离前景层用反相 mask、背景层用原始 mask（节点 9=前景/去背景，10=背景层）。**远端实测坑**：该实例的 `SaveImageWithAlpha` 实现把 mask 白色当作透明（与节点描述"mask as the alpha channel"相反），SAM3 mask（主体=白）必须先 `InvertMask` 才能得到"主体不透明"的 PNG；经点提示/文本提示双对照实验定位（MaskToImage 渲染正确、SaveImageWithAlpha 反相），修复后 alpha 数值验证全部正确（主体 255/背景 0，前景+背景两层互补可还原原图）。文本概念提示（the main subject / a person）在合成图与真实照片上分割均正确。执行走串行 comfy worker（`is_local_comfy_job` 纳入），prompt 字段承载主体描述（默认 `the main subject`）。选型依据：`easy imageRemBg` 的 RMBG-2.0 在远端因 HuggingFace 不可达（ConnectTimeout，`/models/rembg` 为空）无法落盘，弃用；SAM3.1 权重已在远端且点提示 mask 实测正确（主体 255/背景 0）。远端无 ComfyUI-Manager，图像编辑扩散模型（局部重绘用）暂无部署通道，故遮罩类重绘走路径二。
- 路径二（GRS 复合图片工作流，`is_composite_image_workflow`，executor=grs 走图片并发通道、不占用 ComfyUI）：`image-inpaint` / `image-eraser` / `image-outpaint`。纯函数模块 `backend/app/grs_composite.py`：`build_composite_inputs`（原图+白色遮罩 → data URI 输入与指令模板；扩图先 `outpaint_canvas` 等比垫图）→ `grs_client.submit(nano-banana-2)` → `compose_final`（遮罩外/原区域逐像素贴回，feather 羽化，`feather=0` 合法）。`worker.execute_image` 新增复合分支 `_submit_composite_image` / `_ingest_composite_image`，`_poll_image` 支持自定义 ingest 回调；素材校验失败直接 FAILED（不带计费警示语）。遮罩由前端 `ImageMaskPainter` 绘制（画笔/矩形、撤销重做、按原图分辨率导出白=编辑区 PNG），不要求用户单独上传遮罩图。
- 注册表：5 个 `WorkflowDefinition` 入新分组 `CATALOG_GROUP_IMAGE_EDIT`（"图片编辑"，order 1）。去背景/图层分离参数全 internal（threshold/refine_iterations/model_name）；扩图 primary=`target_aspect`（16:9/9:16/1:1/4:3/3:4），局部重绘/消除笔全 internal（feather/provider_model），消除笔与扩图有 default_prompt，局部重绘提示词必填。`is_grs_image_workflow` 收窄为 `grs-` 前缀（`mode_payload` 与创建/追加任务的 GRS 可用性检查只作用于目录模型）。
- 前端：`tool-registry.ts` 图片分类 6 张可用卡；工具页 `ImageBgRemoveTool`/`ImageLayerSplitTool`（共享 `ImageSourceToolPage`）、`PhotoEditTool`（GRS 模型下拉 + 1-10 参考图 + 编辑指令）、`ImageInpaintTool`/`ImageEraserTool`（共享 `MaskedImageToolPage` + `ImageMaskPainter`）、`ImageOutpaintTool`（目标画幅下拉）；`paths.ts` 六条路由；封面 6 张 PIL 生成占位图（可后续替换实拍帧）；图标映射 `tool-icons.ts` 扩展。
- 受影响文件：`backend/app/{models,image_edit_workflow,grs_composite,workflow_registry,comfy_service,worker,main}.py`、`backend/tests/{test_image_edit,test_grs_composite,test_core}.py`、`frontend/src/generation/image-edit.ts`、`frontend/src/tools/`（`tool-registry/tool-icons/ToolsWorkspace/ImageMaskPainter/ImageSourceToolPage/MaskedImageToolPage/ImageBgRemoveTool/ImageLayerSplitTool/PhotoEditTool/ImageInpaintTool/ImageEraserTool/ImageOutpaintTool/motion-transfer-tool.css`）、`frontend/src/paths.ts` 与封面、测试文件。
- 兼容性：不改既有工作流、节点 ID、API 路径与数据库表；`is_grs_image_workflow` 语义收窄仅影响新增工作流的可用性判定；GRS 目录模型与既有 GRS 提交路径不变。`test_core.py` 工作流 ID 白名单同步；`frontend/src/director2/project-video-resolution.test.ts` 为工作区既有未跟踪文件做了最小类型修正（`as unknown as` 两处，语义未动）。
- 验证：`python -m pytest backend/tests -q -k "not dev_reloader"` 1361 passed / 1 skipped（含关键帧叙事同期改动）；`pnpm --dir frontend build`（vitest + tsc + vite）通过，工具/生成目录 vitest 32 项通过；5173 桌面暗色检查 6 张工具卡与全部工具页。真实效果验收（`test-results/tmp-probe/grs-acceptance/`）：GRS nano-banana-2 指令改图加红帽 PASS（其余像素保持）；局部重绘/消除笔/扩图复合管线经同一 `build_composite_inputs → submit → compose_final` 路径实测遮罩外/原区域逐像素一致；ComfyUI SAM3 点提示/文本提示分割均正确；去背景与图层分离经构建器同款 graph 远端实测出图，alpha 数值验证全部正确（主体 255/背景 0、前景+背景互补）。
- 回滚：撤回上述源码、测试与前端增量即可；无数据库迁移，GRS 目录与远端模型无变更。

## 2026-11-03 关键帧叙事上线（minimax-h3-keyframe）

- 当前基线：创作页「官方 MiniMax H3」分组与 AI 工具中心新增可见工作流 `minimax-h3-keyframe`（`JobMode.MINIMAX_H3_KEYFRAME`，catalog_group=official_h3）。graph 在 `backend/app/h3_keyframe_workflow.py`，走 ComfyUI 0.43 官方 **FL2VA + AddGuide** 关键帧锚定路径：LoadImage(关键帧 1..N) → `MiniMaxH3ImageToVideo`（`first_frame`=关键帧 1，锚定 frame 0，输出 positive + AV latent）→ `MiniMaxH3AddGuide` 链（第 2~N 张各一节点，`frame_idx` 为像素帧号，`latent` 统一取基座 AV latent，`positive` 逐级串联，图片经 `_resize(center)` 居中裁切对齐画布）→ 采样链复用 I2V 官方模板（ReservedVRAMSetter 3GB 预留 + 可选 SageAttention patch + BasicGuider/BasicScheduler res_multistep/simple）→ VAEDecode + VAEDecodeAudio → CreateVideo(H3 原生音轨) → SaveVideo（节点 `30`）。关键帧隐变量进 conditioning 的 `minimax_keyframes`，每步重注入、永不加噪。模型为 I2V 同款 `minimax_h3_fl2va_pruned_int8_convrot.safetensors`，无新增权重。
- 锚点协议：options 新增 primary 参数 `anchor_seconds`——第 2~N 张关键帧的画面出现时间，逗号分隔秒数（24fps 换算），负数沿用 AddGuide 语义从末尾计数（`-1`=末帧），留空=均匀分布（首帧 0、末张末帧、其余均分，`even_keyframe_anchor_frames`）。解析与校验集中在 `resolve_keyframe_anchor_frames`（数量必须=N-1、(0,时长]、换算后帧号严格递增、越界报错，入队前 422）。`resolve_keyframe_dimensions` 把 aspect_ratio/duration 映射为 864×480/480×864/640×640 与 124/243/362 帧（17n+5 网格）。
- 实现文件：`backend/app/models.py`、`backend/app/h3_keyframe_workflow.py`（新增）、`backend/app/workflow_registry.py`（`KEYFRAME_OPTION_SCHEMA`、WorkflowDefinition(min 2/max 4、reference_labels=开场关键帧+关键帧 2-4)、`is_keyframe_workflow` 并入 `is_local_comfy_job`、`normalize_options` keyframe 分支）、`backend/app/comfy_service.py`（`run()` 分发 `_run_keyframe_narrative`：提示词必填、references 全为图片按序 `upload_image`、注册表已带 `randomize_when_zero` 的 seed 直接回写快照；`completed_outputs` 恢复分支）。primary=画面比例/生成时长/锚点时间，advanced=步数/种子，其余 internal——符合参数产品化标准。
- **回归修复（连带）**：`director_route_key` 原来把 `max_references >= 3` 的 collection 一律映射为导演台 r2v 路由，min2/max4 的关键帧条目会覆盖真实 R2V；已收紧为 `min_references <= 1 且 max >= 3` 才算 r2v，现有全部路由映射逐一核对不变（test_core 回归覆盖）。
- 前端：`frontend/src/generation/keyframe.ts`（素材/锚点校验、均匀分布预填、序列化，选项泛型复用 motion-transfer）、`frontend/src/tools/KeyframeNarrativeTool.tsx`（2-4 张动态上传卡：开场/序号角标、前移排序、逐张锚点时间与末张"结尾"开关、`anchor_seconds` 由专属 UI 接管不走通用控件、任务恢复）、`keyframe-narrative-tool.css`（沿用 `--studio-*` 语义 token，双主题）、`tool-registry.ts`/`tool-icons.ts`(Images 图标)/`paths.ts`/`ToolsWorkspace.tsx` 注册与封面 `frontend/public/tool-covers/keyframe-narrative.jpg`。
- 兼容性：新增枚举与注册表条目，不改既有工作流、API、数据库、端口与远端节点（`MiniMaxH3AddGuide` 为 ComfyUI 0.43 核心节点，远端已具备）；导演台路由行为与此前一致。`backend/tests/test_h3_keyframe.py` 新增 18 项（注册表层级、锚点解析边界、graph 结构、分发接线、/api/modes 暴露）。
- 验证：`python -m pytest backend/tests/test_h3_keyframe.py -q`（18 项）；`python -m pytest backend/tests -q`（1321 passed, 1 skipped）；`pnpm --dir frontend build`（vitest 647 项 + tsc + vite 通过，另修复 director2/project-flow.test.ts 两处既有 `as Director2Asset` 类型断言导致的 tsc 阻塞）；远端真实出片双路验证——直连 ComfyUI 提交与产品链路 `POST /api/jobs`（任务 P0hp8GhOOLNF，succeeded，历经后端热重载重启后由任务租约恢复续跑）均出片 864×480/124 帧/24fps，抽帧核对首/2.5s/末帧与三张关键帧逐一锚定对应，产物在 `test-results/keyframe-narrative/`；5173 桌面端浅暗主题自查（`/tools/keyframe-narrative` 默认层级、禁用态与工具中心卡片）。
- 回滚：撤回后端四文件 keyframe 增量与 `backend/tests/test_h3_keyframe.py`、前端 keyframe 相关文件与注册点即可；`director_route_key` 若单独回退需同步移除关键帧条目，否则 r2v 路由会被覆盖。无数据迁移与远端变更，进行中任务按已提交 graph 继续。

## 2026-11-03 「人声/伴奏分离」上线（stem-split，MelBand RoFormer 本地免费）

- 原因：补齐即梦式音频工具能力（清唱提取、伴奏制作、语音增强）。远端 ComfyUI（192.168.10.54:8188）已装 Mel-Band RoFormer 自定义节点与 `MelBandRoformer_fp16.safetensors`（models/diffusion_models），零新增依赖。
- 后端：`JobMode.STEM_SPLIT = "stem-split"`；graph 构建器 `backend/app/stem_split_workflow.py`（LoadAudio → MelBandRoFormerModelLoader → MelBandRoFormerSampler → 两个 SaveAudio，输出节点 4=人声 / 5=伴奏，前缀 `stem_split/vocals`、`stem_split/instruments`）；注册表新增 WorkflowDefinition（reference_slots=("media",)、option_schema 仅 internal `model_name`、hidden_from_catalog、default_prompt=分离人声与伴奏）；`comfy_service.run()` 分发 `_run_stem_split`，`completed_outputs()` 新增恢复分支；`is_stem_split_workflow` 并入 `is_local_comfy_job` 占用串行视频 worker。输出以 `kind="audio"` 交付两条音轨（人声 / 伴奏）。
- main.py：`_validate_reference_upload` 新增 `media` 槽位类型，接受音频（.mp3/.wav/.flac/.m4a/.aac/.ogg/.opus/.wma）或视频（.mp4/.mov/.webm/.mkv/.m4v/.avi）。
- 前端：工具注册表新增「人声/伴奏分离」可用卡（icon AudioWaveform、封面 `/tool-covers/stem-split.jpg`；随同期工具分类重组归入「视频」分组）；工具页 `StemSplitTool.tsx` @ `/tools/stem-split`（素材校验 ≤300 MB、任务素材恢复 `?job=`、提交后跳生成页）；`App.tsx` `Output.kind` 扩展为含 `audio`，任务详情新增音频结果条（播放 + 下载，`studio-audio-results` 样式进全局 `index.css`）、视频结果模块仅在存在视频产物时渲染；资产库与首页翻页墙过滤纯音频产物（首页墙仅展示视觉创作）。下载扩展名按产物后缀（FLAC）。
- 兼容性：不改既有任务、路由、端口、表结构；新工作流只由工具页与 API 创建，旧任务不受影响。`VideoResult`/`UpscaleOutputLike` 的 kind 联合同步扩展，剪映导出与画布入口保持视觉两型不变。
- 验证：`python -m pytest backend/tests/test_stem_split.py -q`（3 项通过）；合并关键帧会话路由修复后全量 `python -m pytest backend/tests -q` **1343 passed / 1 skipped / 0 failed**（首轮 3 failed 为同期「关键帧叙事」的 r2v 路由回归，已由关键帧会话修复 `director_route_key`）；`pnpm --dir frontend build` 通过；vitest `stem-split-tool.test.tsx` 3 项通过；5173 桌面检查工具页英雄区 / 上传卡 / 禁用态、工具中心卡片与首页翻页墙链接。
- 远端真实验收（2026-11-03，直连 192.168.10.54:8188 提交本节 graph，双探针互为镜像）：①合成 10 秒器乐探针音（440/220/330 Hz 混合）经 `/upload/image` 上传提交，队列等待约 40 分钟 success，输出节点 4=`stem_split/vocals_00001.flac`、5=`stem_split/instruments_00001.flac` 与 graph 映射一致，ffprobe 双轨时长均 10.000s，人声轨近静音（-91 dB）、伴奏轨承载全部能量（mean -11.7 dB）——合成音无语音成分，全部归入伴奏属正确行为；②真实语音探针（远端 input 既有 `avatar_accept_speech.wav`）success，人声轨 mean -21.7 dB / max -1.0 dB 承载全部语音能量、伴奏轨近静音（mean -66.7 dB）——分离方向正确，输出未接反。验收结论：上传→分离→双轨交付全链路可用；探针产物留在远端 `output/stem_split/`（无法经 API 清理，文件很小），本地 tmp 探针文件已清理。
- 回滚：撤回本节增量（models/workflow_registry/comfy_service/main 的 stem 分支、前端工具页与注册表条目、音频结果条样式）即可，不删已生成音轨文件；无数据库或供应商回滚。

## 2026-11-03 导演台三阶段项目壳与同文档编辑

- 原因：单集工坊已简化，但首页、内容库、资产库仍使用分裂的模式和并列菜单。本轮依据实际即梦流程先生成首页 / 剧本 / 资产设计图，再整体承接既有工坊。
- 当前基线：`Director2ProjectDetail.tsx` 为 `ProjectFlowShell.tsx` 的兼容入口。三阶段对应 `content / assets / workshop`，均使用 64px 项目栏；`edit / jobs` 与制作配方通过工具入口可达。全局 Header 保持，项目页替代全局图标栏。`Director2App` 的局部 Ant Design token 由根主题模式驱动，没有独立主题状态。新项目无正文时后续阶段禁用；存量资产 / 分集解锁后续流程。
- 首页：`HomeCreationPanel` 将创作意图、风格、画幅与集数交给原助手会话；先创建项目，再建关联 session / 提交幂等消息并进入剧本。直接导入只解析落库，不调用模型。旧独立助手及历史保留在“更多创作工具与历史”。
- 剧本：`ScriptWorkspace` 默认展示设定 / 大纲 / 正文，旧 `ContentLibraryPane` 下沉为“解析详情”。新文档编辑 `PUT /api/projects/{project_id}/documents/{doc_id}` 要求 `raw_text` 与 `base_raw_text`，校验活动规划和并发更新，重新解析同一 ID。空正文不允许，冲突返回 409，既有资产和分集不随保存自动改写。原文基线与未保存修改保存在项目 / 文档级浏览器恢复稿中，取消或成功保存后清理。
- 资产与分集：卡片和详情引用同一 asset ID，状态由角色每套造型图 / 场景主视角 / 道具参考图计算。`transfer-assets` 新增可选 `mode=append`，下一步只补新资产，保留已有文字设定；兼容默认 `merge` 的更新行为由解析详情保留。下一步调用既有 `transfer-episodes` 的 `append`，只补新集，不重写旧镜头和视频；缺图可明确确认后继续。高级规划和覆盖操作仍在解析详情。
- 前端状态：`project-flow.ts` 只保存项目内白名单菜单 / 文档 / 资产 / 分集位置，首页恢复前以服务端当前数据验证；已删除分集回概览。普通助手会话改为项目级存储与范围校验，剪辑会话原隔离规则不变。
- 受影响文件：`App.tsx`、`director2/{Director2App,Director2StudioHome,ProjectFlowShell,HomeCreationPanel,project-flow}`、`panes/{ScriptWorkspace,AssetsLibraryPane}`、`assistant/{DirectorAssistant,editing-tools}` 及对应样式 / 测试；后端 `project_router.py`、`project_detail_service.py`、`api_documentation.py` 和文档编辑测试。
- 兼容性：不改已有 URL、表结构、端口、供应商和生成 graph。`?mode=agent/manual` 作为旧链接参数保留，但默认同一工作区；旧 AI 任务仍由原服务运行，任务入口保留。新增 PUT 为可回退扩展。
- 验证：`python -m unittest backend.tests.test_document_analysis_recovery backend.tests.test_standard_script_parser -v`；`python -m unittest discover -s backend/tests`；`pnpm --dir frontend build`；5173 桌面 1536×864 双主题与导航、草稿恢复、资产定位、分集播放器检查。设计 / 实拍索引见 `docs/design-ref-director/three-stage-20261103/` 和流程文档。
- 回滚：撤回本节相关流程模块、主题 / 入口接线和新增 PUT，恢复原 `Director2ProjectDetail`；不删除持久化制作数据，不需要数据库回滚。浏览器位置与恢复稿是可忽略偏好，不影响旧界面读取。

## 2026-11-03 动作迁移完整原片与双人配对由平台执行

- 原因：用户要求验证平台本身对完整参考片、双人替换的能力，明确不接受 Codex 临时脚本编排作为平台验收。独立实验 prompt `720eaa49-5caf-4430-8e54-aba9b5908986` 已停止，仅保留诊断记录，不作为交付或平台能力证明。
- 注册表：`scail2-replacement` 新增 `duration=full`（1–30 秒）与 `subject_count=1/2`；primary 为生成范围、替换人数、原声开关，advanced 仍仅种子。`source_duration`、`length`、`conditioning_length`、`chunk_count` 为 internal，由 API 根据实际素材计算并随任务/轮次保存。原 `5s` / 81 帧默认值和既有单人任务保持兼容；旧标记未含 subject 时默认为 0。
- 人物协议：正负点新增整数 `subject=0/1`，形象图与视频中同号人物配对；每个人最多 20 点，两个素材中每组均须至少一个正点。准备素材时，其他已选人物的正点自动成为本人物的排除点。两个独立 SAM3_Detect 初始遮罩通过 BatchMasksNode 的 `masks.mask0` / `masks.mask1` 扁平 API 输入合并；VideoTrack 的 max_objects=2，ColoredMask 的 sort_by=none 保持手动配对顺序，支持两份素材左右次序不同。
- 长片协议：平台探测原片时长，完整片目标帧数为 ceil(时长×16)。每段最多 81 帧，下一段用上一段 decoded 尾部 5 帧作为 previous_frames、前段 offset 输出作为 video_frame_offset，起点每次推进 76 帧；每段遵守 4n+1 帧网格，最多补 3 帧。ImageFromBatch 剔除后续段前 5 帧，ImageBatch 顺序拼合，最终裁到真实目标帧数；CreateVideo 直接连接原片音频。全流程在单个平台 ComfyUI prompt 内执行，旧输出节点 46 与原有节点 ID 保持不变，续接仅追加新节点；任务恢复继续从 46 取片，不重复生成。
- 实例与数据：沿用当前供应商、既有 SCAIL-2/SAM3.1 权重、端口、串行 worker、存储和权限；无新表、依赖或第二套 ComfyUI。原图与原始整片通过平台 `/api/jobs` 上传，预处理临时文件仅在 staging 并自动清理；生成后不依赖平台外剪辑或音轨替换。
- 受影响文件：`backend/app/{scail2_workflow,workflow_registry,main,comfy_service}.py`、`backend/tests/{test_scail2_replacement,test_core}.py`；`frontend/src/generation/motion-transfer.ts` 及测试、`tools/{MotionTransferTool,MotionSubjectPicker}.tsx`、`motion-transfer-tool.css`；README、扩展指南、API、原动作迁移验收记录。
- 验证：专项后端 33 项通过，覆盖多人物配对、边界与非法输入、242→245 帧窗口、4 段锚点链路、自动拼合/去重与完整 multipart 快照；`pnpm --dir frontend build` 为 97 文件 / 647 项测试、类型检查和 Vite 构建通过。全量后端 `python -X utf8 -m pytest backend/tests -q -k "not dev_reloader"` 为 1306 passed、1 skipped、12 deselected、3 failed；失败均为同期导演台关键帧路由的旧 r2v 预期，未修改该业务。真实平台任务为 `5aMLu6mPL3j`，仅从 5173 页面上传原整片、点选双人、空提示词、默认种子与原声开关后提交；远端 prompt 为 `74246547-3937-442a-98e4-ce4b1614dbe4`，client_id 为平台 `zly-ai-video-studio-*`。
- 质量边界：该任务直接输出 512×896 / 16fps / 242 帧 / 15.125 秒，原 BGM 保留，平台下载与 ComfyUI 原输出 SHA256 一致，未在平台外修片。完整流程已跑通，但男主头发/服装颗粒失真，尾段出现多余背景物，双人质量未通过。注册表与页面将双人标为试用，建议先生成 5 秒；单人既有试片的通过结论不扩大到双人整片。最终原片、只读检查与失败证据见动作迁移 ACCEPTANCE。
- 同日头发反馈后的调度修正：对照 Comfy-Org 官方 `video_wan21_scail2_character_replacement_int8.json`，BasicScheduler 应从 LoRA 后、ModelSamplingSD3 前的模型产生 sigmas；平台误接了已覆写 shift 的模型。`scail2_workflow.py` 将节点 42 的 model 输入由 33 改接 32，续接副本一并继承；节点 ID、输出 46、LoRA、步数、参考图和默认提示词保持兼容。新增所有续接段的调度回归断言，专项 34 项通过，前端构建仍为 97 文件 / 647 项通过。真实同素材、同种子 1373133514 的 5 秒平台对照 `HGo0eUcdwuB` 已完成，原文件内嵌 graph 确认调度接线生效，但头发网状黑颗粒、发型偏差及皮肤/服装黑点仍明显，视觉验收失败；该修正没有解决本次头发缺陷。按用户条件未生成完整片，并结束定时监控。若撤回调度修正，仅恢复节点 42 的 model 输入；已提交 graph 和旧媒体不变。官方来源和失败证据见 ACCEPTANCE。
- 回滚：仅撤回本节完整片/双人增量，恢复 duration 仅 5s 和单人标记校验，保留 SCAIL 原输出 46 恢复分支、已生成媒体及其他同期改动。进行中任务按已提交 graph 继续，不能中途替换图；无需数据库或供应商回滚。

## 2026-11-03 导演台首页还原为智能助手 + 我的短剧

- 原因与当前基线：按已校准的 v003 / 即梦参考还原真实 `/director`；删除首页“短视频批量 / 参考片复刻 / 剧本诊断”整行入口。全局 Header 与 76px 导航不重建，首页由居中标题、303px 高输入区、创作建议与媒体卡片组成。1536px 桌面三列、1700px 以上五列；输入区 24px 圆角，标题 30px/38px，卡片名称 13px/20px，封面 16:9，gap 4px。日期改用现有高对比次文字；主题只继承根 Provider。
- 前端状态：`DirectorAssistantProvider` 新增 `presentation="home"`，默认仍为 `drawer`；首页通过 `AssistantHomeContext` 复用同一套消息、SSE、问题、产物、媒体确认与流程卡，不复制演示对话。首页 mount 与“返回首页 / 新对话”进入独立新草稿，首次发送才创建 `project_id: null` 会话；历史通过原 `/sessions` 显式恢复。`home` / `general` / 剪辑 scope 区分异步生命周期，切换页面后过期请求不回填旧视图。回复中禁止新建或返回以免误切会话，后台服务执行不变。
- 数据：我的短剧只读 `/api/projects`，按更新时间排序；默认一行，可搜索、全部/收起、打开、删除二次确认，并保留制作配方 Modal 新建。封面优先 `cover_url`，否则仅对进入视区的卡片读取既有 `/api/projects/:id/assets`，取最多三张去重真图片；角色/道具 contain，场景 cover，无图或加载失败显示空态。React Query 缓存 60 秒，采纳事件刷新项目并失效对应缩略图缓存。不会把即梦参考项目照片接入生产卡片。
- 受影响文件：`Director2App.tsx`、`Director2StudioHome.tsx`、`director-home.css`、`assistant/DirectorAssistant.tsx`、`assistant/assistant.css`、`home-project-cards.ts` 及测试；标题字体沿用已校准的本地参考子集 `frontend/public/fonts/director-heading.otf`。AI 对话 token 继续对照官方 MIT `prompt-bar.tsx` / `chat.tsx` / `approval-card.tsx` 与 `app/globals.css`，只复用设计，不引入 shadcn/Tailwind v4。
- 兼容性：不改 API、数据库、工作流、端口、媒体生成与采纳协议；项目/剪辑仍用助手抽屉。三个被移除的首页工具入口对应路由与既有数据保留，旧链接可直接访问；它们不再混入“我的短剧”。
- 验证：`pnpm --dir frontend build`（93 文件 / 633 项前端测试、TypeScript、clean 与 Vite 构建通过）；`python -X utf8 -B -m unittest backend.tests.test_director_assistant backend.tests.test_skill_packs backend.tests.test_editing_assistant -q`（174 项通过）。5173 桌面真实会话完成一轮最小连接检查，回复“对话正常”，未创建/修改工程或提交媒体任务；历史恢复、关联工程进度、搜索、项目打开、浅暗主题与卡片细节见流程文档和 `docs/design-ref-director/home-agent-20261103/`。
- 回滚：只撤回上述首页、助手展示层及对应文档/字体的本次增量，恢复原首页和默认 Drawer 展示；会话及工程数据无需迁移。

## 2026-11-03 「深度捕捉」上线（minimax-h3-depth，DA3 深度 + H3 Fun ControlNet）

- 当前基线：创作页与 AI 工具中心新增可见工作流 `minimax-h3-depth`（`JobMode.MINIMAX_H3_DEPTH`，catalog_group=official_h3，对标即梦「深度捕捉」）。graph 在 `backend/app/h3_depth_workflow.py`：LoadVideo/GetVideoComponents(原片) → **LoadDA3Model + DA3Inference(mono) + DA3Render(depth, v2_style)**（ComfyUI 0.43 核心节点，模型 `depth_anything_3_mono_large.safetensors` 位于远端 `models/geometry_estimation/`，1.34GB，2026-11-03 部署）→ 深度帧双路输出：一路 `VHS_VideoCombine` 存**深度预览视频**（节点 `7`，辅助产物），一路进 `MiniMaxH3FunControlNetApply(control_video=深度帧)`——复用动作迁移/局部重绘同款官方 Fun ControlNet Union patch（`ModelPatchLoader`），**实测深度控制信号有效**：结构、运镜与主体位置跟随原片，画面内容按提示词重塑 → MiniMaxH3ReferenceToVideo(无参考图) → 原生采样链（RandomNoise/KSamplerSelect/BasicScheduler/BasicGuider/SamplerCustomAdvanced，res_multistep/simple）→ VAEDecode + VAEDecodeAudio → CreateVideo(H3 原生音轨) → SaveVideo（节点 `28`）。画布由分发层 `probe_video`（ffprobe）探测预处理后原片宽高 32 对齐（探测与上传都在暂存临时目录存活期内完成）；帧数 17n+5（5s=124/10s=243/15s=345），原片经 `prepare_depth_source` 截取对齐（去音轨，成片用 H3 生成音轨）。DA3 推理分辨率 internal 默认 504（lower_bound_resize，14 的倍数）。
- 注册表：`DEPTH_OPTION_SCHEMA` primary=结构跟随强度(0.1-1.0)/生成时长(5s/10s/15s)，advanced=步数/种子（`randomize_when_zero=True`，归一化即得实际种子），internal=画布/帧数/DA3 分辨率/采样/精度；`normalize_options` 新增 depth 分支映射 duration→length；`reference_slots=("video",)` 显式声明单视频槽位；`is_depth_workflow` + `is_local_comfy_job` 纳入串行视频 worker。
- 提交链路：`comfy_service.py` run() 分发 `_run_h3_depth`（references[0]=原片视频 `upload_video`，时长校验 `validate_depth_source`），`_depth_capture_outputs` 供运行与恢复（`completed_outputs`）两条路径共用——成片为主产物，深度预览为辅助产物（缺失不阻塞交付）。前端 `frontend/src/tools/DepthCaptureTool.tsx`（`/tools/depth-capture`，原片上传+时长预检+schema 驱动参数+任务素材恢复）、`generation/depth.ts`（校验助手，复用 motion-transfer 泛型）、`tool-registry.ts`/`tool-icons.ts`(Layers)/`paths.ts`/`ToolsWorkspace.tsx`、封面 `public/tool-covers/depth-capture.jpg`（原片↔深度分屏，取自实测任务帧）。
- 兼容性：新增枚举与注册表条目，不改既有工作流与 API；`h3_depth_workflow.py` 对 `director_export.find_ffmpeg` 采用函数内延迟导入，避免 director_export→workflow_registry 模块环。产品提交链路实测（POST /api/jobs）暴露并修复两处隐患：①`main.py _validate_saved_references` 新增深度捕捉早退分支（references[0] 为原片视频，`validate_depth_source` 校验时长；否则旧分支按「首项=形象图」用 PIL 开视频必 422）；②画布探测用 `probe_video`（ffprobe）而非 `PIL.Image.open`（标准 Pillow 打不开 mp4），且探测+上传移入 `TemporaryDirectory` 存活期（`prepared` 随 with 块销毁，出块后上传会 WinError 3）——同款两处隐患在 `_run_inpaint` 一并修复（此前局部重绘只做过直连 ComfyUI 验收，产品提交路径未覆盖）。远端仅新增 `models/geometry_estimation/depth_anything_3_mono_large.safetensors`（HuggingFace `Comfy-Org/Depth-Anything-3` 官方 repack），不触碰 VACE/既有节点。
- 验证命令：`python -m unittest backend.tests.test_h3_depth`（11 项通过）；`python -m unittest discover backend/tests`；`npx vitest run`（92 文件 / 630 项通过）；`pnpm --dir frontend build`。远端实测（192.168.10.54）：①产品链路 `POST /api/jobs` E2E 通过（5s 原片，succeeded，成片+深度预览双产物）。②**A/B 对照实证深度锁定**（`test-results/depth-capture/ab/ab_compare_grid.jpg`）：H3 生成「前推穿越老城巷」源片，A=深度控制重绘为雪夜灯笼巷、B=同 seed 同提示词摘掉 ControlNet——A 的推进轨迹与走廊结构逐时间点跟随源片（t=0 巷口全景→t=4.5 深入巷中），B 几乎原地固定机位、构图自成一派，证明运镜与空间结构来自深度信号而非提示词。124 帧 20 步：A 约 210s（含 DA3 推理），源片生成约 200s。
- 回滚方式：撤回 `models.py`/`workflow_registry.py`/`comfy_service.py`/`h3_depth_workflow.py` 增量与测试，前端撤回 depth-capture 相关文件与 registry 路径增量；远端删除 `models/geometry_estimation/` 权重即回到原状。无数据迁移。

## 2026-11-03 「口型同步」上线为 AI 工具（minimax-h3-lip-sync，H3 rv2v 本地方案）

- 当前基线：占位工具「口型同步」转为可用（`/tools/lip-sync`）。经远端直连实验验证，采用**零新增模型**的 H3 本地方案：源视频帧作 `ref_videos` 参考锁定身份与场景，目标音频经 `MiniMaxH3AudioWindowT8` 对齐后以 `lock_source` 驱动口型，`MiniMaxH3AudioConditioningT8`（task_type=auto 实际路由 ref2va）→ 原生 res_multistep/simple 采样（ref2va INT8 完整权重 + ref2v Turbo LoRA 4 步 / pruned 20 步）→ AVDecode → OutputTrim → 24fps MP4（前缀 `MiniMaxH3/ZLY_AI_VIDEO_STUDIO_LIPSYNC`，输出节点 `14`）。graph 在 `backend/app/minimax_h3_lipsync_workflow.py`；实验依据：源视频=数字人成片 + 不同语音 → 输出身份/场景/服装完全保持、口型随新语音开合（说话窗口嘴部运动 1.5 倍于停顿窗口，对照区 1.35 倍）、时长与新音频等长。
- 注册表：`JobMode.MINIMAX_H3_LIP_SYNC`；`WorkflowDefinition` 新增 `reference_slots=("video", "audio")` 显式槽位机制（`reference_kind(index)` 优先按槽位返回，报错文案按槽位生成），`hidden_from_catalog=True` 仅 AI 工具入口（生成页下拉不出现，因其参考素材含视频）。schema：primary=生成速度（快速 4 步 Turbo / 精细 20 步完整 / 自定义 1-40 步，≤8 步挂 ref2v Turbo LoRA 0.75），advanced=种子，其余 internal（画布 width/height 与 `scene_duration_seconds` 由提交侧探测写入；音频/模型/编码参数托管）。`H3_WORKFLOWS` 纳入串行 worker，`H3_REFINE_WORKFLOWS` 显式排除（二采无音频感知契约）。
- 提交链路：`main.py _validate_reference_upload` 按 `reference_slots` 放行第 1 项视频/第 2 项音频（文案泛化）；`_validate_saved_references` 新增口型同步分支——`_probe_lipsync_source_canvas` 用 ffprobe 探测源视频时长（官方 2-15 秒政策，越界 422）与尺寸（32 对齐、面积超 1344×768 等比缩容）写入 `options.width/height`，`_probe_avatar_scene_duration` 复用探测目标音频（≤5 秒窗口）写入 `scene_duration_seconds`。`comfy_service` 分发 `build_minimax_h3_lipsync_workflow`，references [0] 走 upload_video、[1] 走 upload_image（同一 /upload/image 端点）。
- 前端：`frontend/src/tools/LipSyncTool.tsx`（视频槽：MP4/MOV/WebM、2-15 秒前端预检 + `<video>` 缩略预览；音频槽：WAV/MP3 ≤5 秒预检；提示词可选留空补默认；提交后跳转生成页任务详情）、`generation/lip-sync.ts`（校验与时长边界）、`lip-sync-tool.css`（`--studio-*` 双主题）；`tool-registry.ts` lip-sync 置 available（icon=`AudioLines`），`paths.ts`/`ToolsWorkspace.tsx` 路由；`digitalHumanAudioError` 增加 label 参数（目标音频复用）。
- 实验遗留说明：源视频若带 H3 自动烧录字幕/花字，输出会继承并可能出现错字（模型重新绘制所致）；干净源视频输出干净。对既有视频「只换口型、逐像素不动」的诉求仍属 LatentSync 类能力，如需可后续评估（需下载节点与权重，另行确认）。
- 验证命令：`python -m unittest backend.tests.test_workflow_lipsync backend.tests.test_workflow_avatar backend.tests.test_comfy_provider backend.tests.test_director_workflow_speed`（28 项通过）；`npx vitest run`（89 文件 / 625 项通过）；`pnpm --dir frontend build`；5173 桌面端实测工具卡可用、工具页上传/预检/提交 → 任务出片（另见功能说明变更章节）。
- 回滚方式：撤回 `models.py`/`workflow_registry.py`/`comfy_service.py`/`main.py`/`minimax_h3_lipsync_workflow.py` 增量与测试，前端撤回 lip-sync 相关文件与 registry 路径增量；无数据迁移。

## 2026-11-03 SCAIL-2 Replacement＋SAM3.1 接入动作迁移工具 Replacement＋SAM3.1 接入动作迁移工具

- 原因：H3 骨架流程在多人自拍舞蹈中出现主体切换、腿部缺失与背景重建。用户确认独立 SCAIL-2 试片效果后授权接入。新增 `JobMode.SCAIL2_REPLACEMENT = scail2-replacement`，独立 graph 和稳定节点 ID，原 H3 graph/ID、接口和历史任务不变。
- 当前流程：`/tools/motion-transfer` 从 `/api/modes/scail2-replacement` 读取注册表，上传原形象图和动作视频，分别在形象图和视频首帧点选目标。`source_points` / `reference_points` 为归一化坐标的 JSON 字符串，每项 `{x,y,exclude}`；每份 1–20 点且至少一个正点，后端拒绝越界、非有限数、错误类型或空标记。标记作为 internal 参数随任务/轮次保存，重新编辑返回工具页恢复原文件、标记、提示词与参数。任务页按注册表详情读取专属工作流名称。
- 预处理：本机 FFmpeg 按视频正确显示方向取首帧；画布按原片比例约 0.46 MP、32 对齐（256–1280 范围），图/视频分别等比缩放留黑边，并按各自缩放和平移换算标记坐标。API 保存实际宽高；16fps / 81 帧约 5.0625 秒，5 秒源片仅补极短尾帧，原音轨随同保留。临时素材放 staging 的临时目录并自动清理。
- graph：SAM3_Detect 的正负点分别锁定视频/形象图人物；SAM3_VideoTrack 使用 initial_mask、max_objects=1 跟踪，SCAIL2ColoredMask 使用 Replacement 分色规则；参考角色先单独抠出，再进入 CLIP Vision 与 reference_image，原 RGB 视频与分色遮罩进入 WanSCAILToVideo。DPO 1.0 → Lightx2v 0.8 → shift 5、Euler/simple、6 步、CFG 1；输出节点 `46`。CreateVideo 默认直接接原片 audio，关闭原声时省略 audio 输入；模型不另生成 BGM。Replacement 保持场景接近原片，但不承诺遮罩外逐像素相同。
- 权重：沿用实际生效远端 `192.168.10.54:8188`、ComfyUI 0.43.0、RTX 4080 16GB；没有切换地址、重启或部署第二实例。`wan2.1_14B_SCAIL_2_int8_convrot.safetensors`、UMT5 FP8、Wan2.1 VAE 放远端既有 `D:\ComfyUI-Models` 下的 diffusion_models/text_encoders/vae；SAM3.1 checkpoint、CLIP Vision H、DPO/Lightx2v LoRA 放原便携 ComfyUI 的 checkpoints/clip_vision/loras。7 个文件约 26.65 GiB，官方 ModelScope 副本已与 Hugging Face 官方 SHA256 全部匹配。工作台不自动下载模型；提交前检查当前实例节点与文件，缺失返回明确原因。
- 参数与队列：primary 仅时长与原声开关，advanced 仅种子，完整采样/模型/人物标记为 internal。首版只支持一位人物、开头约 5 秒；专属工作流不出现在通用创作下拉中，避免缺少人物点选的错误提交。仍走 `/api/jobs`、原串行 ComfyUI worker、七牛/本地交付和任务恢复；支持已有 prompt 的取片恢复，不重复提交。无新表、端口或依赖。
- 受影响文件：`backend/app/{scail2_workflow,workflow_registry,models,main,comfy_service}.py`、`backend/tests/test_scail2_replacement.py`、`.gitignore`；`frontend/src/{App.tsx,generation/motion-transfer.ts,tools/MotionTransferTool.tsx,tools/MotionSubjectPicker.tsx,tools/motion-transfer-tool.css,tools/tool-registry.ts}` 与相关测试；README、扩展指南、API 和动作迁移验收记录。
- 验证命令：`python -X utf8 -m pytest backend/tests/test_scail2_replacement.py backend/tests/test_h3_motion_transfer.py backend/tests/test_motion_transfer_media.py -q`（30 passed）；`python -X utf8 -m pytest backend/tests -q -k "not dev_reloader"`；`pnpm --dir frontend build`。5173 桌面浅暗主题验证上传、正负点、参数层级、声音开关、提交、任务回显与重新编辑；远端完整任务及全量回归结果补充在动作迁移 `ACCEPTANCE.md`。
- 临时产物：自动审批以 blocked by policy 拒绝删除 test-results/workshop-20261102/，未继续尝试；日志仍由 Git 忽略。真实界面基线保存在 docs/design-ref-director/workshop-20261103/。
- 回滚：仅撤回上述 SCAIL-2 增量，将工具工作流 ID 恢复 `minimax-h3-motion-transfer` 后重建前端；保留同期改动、历史任务、权重和成片。已有 SCAIL 记录需保留 enum/注册表及 completed_outputs 分支以继续读取，不对进行中的任务切换 graph。无需数据库或远端实例回滚。

## 2026-11-03 剧集工坊采用简洁工作台与分段播放联动

- 原因：按已确认的 v005 即梦式设计稿，把默认的多层 Tabs、表单与统计卡改为分集概览和单集制作工作区；复杂制作能力继续由原处理函数接线。
- 当前基线：工坊路由使用 56px 项目轨道、52px 顶栏；全局 Header 在这些路由收为主题/账号入口。单集为 340px 资产库、约 77:23 正文/视频栏和 172px 底部片段条。正文默认显示真实画面、对白和运镜；旧 H3 Picture 槽位/运行合同保留在“制作详情”，不作为默认正文。所有颜色继承根主题的 --studio-* token，不新增主题状态；其他模块保持原壳。
- 状态与持久化：新增 Beat JSON 字段 workshop_prompt_document（Tiptap doc，paragraph / text / hardBreak / assetReference）；引用 attrs 保存资产 id、造型 lookId、label 与 kind。PUT beats 仍用原接口与行锁 JSON 合并；后端校验资产属于工程、造型存在，再从节点派生资产绑定与 video_prompt_zh，按“对白：”“镜头：”段同步 dialogue / camera，余下正文写 action。正文/引用变化清空旧 h3_prompt、timestamped_zh_prompt 与 authored_en_valid，生成已由同日「工坊视频自动准备」承接；成片 URL 不动。高级表单修改旧字段时清除文档缓存并从字段重建，避免覆盖旧版编辑。
- 编辑行为：行内 24px 标签带 16px 真缩略图、名称/造型/主视角；支持 @ 搜索、光标插入、单处替换、转普通文字和撤销。资产库支持本集/全部范围、搜索、分组、列表/宫格与悬停菜单。每个 Beat 使用独立的串行合并保存队列，防止旧响应清掉新稿；失败稿保留本机，可重试或恢复。现有数据模型每片段仍绑定一个场景、每角色一个造型，冲突引用明确报错。
- 播放：右侧是现有各片段成片的连续播放列表，测得真实 duration 后重算全局段落边界。点击段、拖动 Ant Design Slider、底部选片和自然播放结束均通过同一个 selectedBeatId 联动正文、引用区、底部高亮与播放器；支持暂停、静音、当前段循环和全片预览。缺片保留其位置并显示空态，不伪造视频或跳过未完成片段。
- 历史版本：新增只读 GET /api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/video-takes，返回真实 takes / adopted_id / adopted_url；复用 collect_beat_video_takes，不写库、不发任务。采用版本仍调用原 POST .../video-takes/adopt。
- 受影响文件：frontend/src/App.tsx、components/StudioHeader.tsx、director2/{Director2ProjectDetail.tsx,api.ts,workshop-editor.ts,workshop-save-queue.ts}、panes/{EpisodeWorkshopPane,WorkshopOverview,WorkshopWorkspace,WorkshopPromptEditor,WorkshopPlayer,WorkshopHistory}.tsx 与 workshop-focus.css；backend/app/media_studio/{routers/project_router.py,services/project_detail_service.py,services/episode_video_service.py,services/workshop_prompt.py}；相关测试、frontend/package.json、pnpm-lock.yaml 和项目文档。新增 Tiptap 3.32.2（MIT），业务控件继续直接使用 Ant Design。
- 兼容性：原工坊 URL 和 ?tab=script / dubbing / compose 收藏仍可用，分别打开抽屉或全片预览；旧 Beat 无新字段时从原文案和已绑定资产构建编辑视图。无新表、端口、模型、节点或供应商变更。
- 验证命令：pnpm --dir frontend build；python -X utf8 -m pytest backend/tests -q -k "not dev_reloader"；python -X utf8 -m pytest backend/tests/test_core.py backend/tests/test_workshop_prompt.py -q。另运行 media_studio_test_h3_video.py，历史 EpisodeVideoUpscaleTests 中 9 项仍按已被智能超清替换的旧超分函数打桩；移除本轮新增历史方法后同样复现，属于现有测试与实现差异。浏览器验收只使用 5173 桌面入口，不提交生成任务。
- 本轮验证结果（2026-11-03）：前端 pnpm build 通过（86 个测试文件、606 项测试、TypeScript 和 Vite）；最新后端全量为 1257 passed / 1 skipped / 12 deselected / 1 failed，失败为 test_core.py 的工作流 ID 白名单断言，现有 SCAIL2 新工作流不在该断言列表，本轮工坊未改注册表。新增工坊 6 项测试已通过；工坊与核心定向回归 125 项通过（仅排除上述注册表 ID 白名单用例）。此前额外运行的旧 EpisodeVideoUpscaleTests 有 9 项与当前智能超清实现不一致，移除本轮只读历史方法后仍复现。5173 实拍和具体验证范围见导演台文档参考截图索引；自然播放跨段尚未完成浏览器验证，浏览器由用户按 Esc 停止。
- 回滚：仅撤回上述文件中本轮工坊布局、文档字段与只读历史接口增量，以及六项 Tiptap 精确依赖，再运行前端构建；保留同期已有改动和全部 Beat/媒体。旧客户端忽略附加 JSON 字段，无数据库或 ComfyUI 迁移。


## 2026-11-02 数字人提升为「AI 工具」中心独立工具模块（/tools/digital-human）

- 当前基线：对齐即梦的数字人独立工具入口，`minimax-h3-avatar` 工作流在保留生成页入口的同时，以「数字人」工具卡进入 AI 工具体系。`frontend/src/tools/tool-registry.ts` 新增 `digital-human` 条目（status=available、category=featured 但不 highlight，保持首页多功能墙前两位高亮契约不变；cover=`/tool-covers/digital-human.jpg`，取自真实出片帧）；icon 联合类型新增 `"digital-human"` 并在 `tool-icons.ts` 映射 `MicVocal`。新增工具页 `frontend/src/tools/DigitalHumanTool.tsx`（复用动作迁移工具页的 `studio-motion-*` 布局类与 `AssetPickerModal` 资产选取，新增 `digital-human-tool.css` 仅补充形象图/音频槽位样式，全部使用 `--studio-*` 语义变量适配双主题），共享校验逻辑在 `frontend/src/generation/digital-human.ts`（形象图 50MB/图片类型校验、口播音频扩展名+类型校验、`probeAudioDuration` 前端时长预检，超 5 秒拒绝与后端 `AVATAR_MAX_SCENE_SECONDS` 对齐）。路由：`paths.ts` 新增 `toolDigitalHuman` 并注册进 `STUDIO_ROUTE_PATHS`；`ToolsWorkspace.tsx` 按路径渲染；`studioWorkspaceFromPath` 经既有 `/tools/` 前缀规则自动归入 tools 工作区。
- 关键行为：工具页上传人物形象图 + 口播音频（选文件即探测时长并预检超限）→ 可选填写提示词与画面比例 → `POST /api/jobs`（mode=`minimax-h3-avatar`）→ 成功后跳转生成页任务详情。后端要求提示词非空，工具页留空时自动补默认场景描述「真实感人物面对镜头自然说话，画面稳定，光线柔和」（口型同步不依赖提示词）。
- 实现文件：`frontend/src/tools/{tool-registry.ts,tool-icons.ts,DigitalHumanTool.tsx,digital-human-tool.css,ToolsWorkspace.tsx}`、`frontend/src/generation/{digital-human.ts,digital-human.test.ts}`、`frontend/src/paths.ts`、`frontend/src/tools.test.ts`（新增 digital-human 路径与状态断言）、`frontend/public/tool-covers/digital-human.jpg`、`frontend/public/tool-art/digital-human-portrait.webp`（均取自验收任务 FHCcF8G9L2 真实出片帧，已裁除 H3 自动烧录的字幕带）。后端零改动。
- 用户可见行为：AI 工具中心「精选」组与生成页首页多功能墙出现「数字人」可用卡片（照片 + 配音，让人物开口说话），点击进入独立工具页，与即梦 `ai_feature_name=digitalHuman` 的独立工具形态对齐；生成页工作流下拉中的「H3 数字人口播」保持不变。
- 兼容性：纯前端增量，不改 API、数据库、工作流协议与既有路由；工具墙顺序契约（前两位高亮）与既有 605 项前端测试全部保持通过。
- 验证命令：`npx vitest run`（86 文件 / 605 项通过，含新增 4 项）；`pnpm --dir frontend build`；5173 桌面端实测：工具中心卡片、`/tools/digital-human` 工具页、双槽上传（含音频时长显示）、空提示词默认值提交 → 跳转任务页出片（任务 X55LaruXr5G succeeded，成片 4.0s 含音轨）。
- 回滚方式：撤回上述前端文件增量与两个 public 素材即可；后端无改动，无数据迁移。

## 2026-11-02 创作页新增「H3 局部重绘」工作流（minimax-h3-inpaint）

- 当前基线：创作页新增可见工作流 `minimax-h3-inpaint`（`JobMode.MINIMAX_H3_INPAINT`，catalog_group=official_h3）。graph 在 `backend/app/h3_inpaint_workflow.py`，走 ComfyUI 0.43 `MiniMaxH3FunControlNetApply` 的官方 inpaint 路径（mask=1 为重绘区、`source_video` 提供域外原片内容；不给 `control_video`）：LoadImage(遮罩图) → ImageToMask(red, 白色=重绘) 与 LoadVideo/GetVideoComponents(原片) → 遮罩+原片进 ControlNet patch → MiniMaxH3ReferenceToVideo(提示词描述替换内容) → 采样后 **ImageCompositeMasked 硬合成**（destination=生成帧、source=原片帧 ImageScale 对齐画布、mask=InvertMask）保证遮罩外**像素级保持**，CreateVideo 沿用**原片音轨**。画布由分发层用 ffprobe 探测原片宽高后 32 对齐；帧数 17n+5（5s=124/10s=243/15s=345），原片经 `prepare_inpaint_source` 截取对齐（保留音轨）。primary=重绘强度/生成时长，advanced=步数/种子，其余 internal。遮罩单帧自动广播到全片（patch 内 `_fit_frames` clamp）。
- 实现文件：`backend/app/models.py`、`backend/app/h3_inpaint_workflow.py`（新增构建器+`validate_inpaint_video`/`prepare_inpaint_source`）、`backend/app/workflow_registry.py`（`INPAINT_OPTION_SCHEMA`/定义/`is_inpaint_workflow`/`is_local_comfy_job`）、`backend/app/comfy_service.py`（run() 分发 `_run_inpaint`：references[0]=遮罩图 `upload_image`、references[1]=原片 `prepare_inpaint_source`+`upload_video`，提示词必填；`completed_outputs` 恢复分支）、`backend/tests/test_h3_inpaint.py`（新增 9 项测试）。前端零改动。references 语义复用 `accepts_video_reference`（第 2 项=视频），遮罩图为第 1 项图片。
- 用户可见行为：创作页「官方 MiniMax H3」分组出现「H3 局部重绘」——上传一张遮罩图（白色区域=要重绘的部分）和原片视频，填写"把遮罩区域替换成什么"，出片后遮罩外与原片逐像素一致、音轨不变。同日接入「AI 工具」中心：`/tools/partial-retake` 工具页（`frontend/src/tools/PartialRetakeTool.tsx`，遮罩图+原片上传、时长校验、schema 驱动参数、任务素材恢复），工具中心与首页翻页墙的「视频局部重拍」卡片翻为可用。
- 兼容性：新增枚举与注册表条目，不改既有工作流与 API；`_validate_saved_references` 对 accepts_video_reference 工作流的既有校验（paths[0] 图片 + validate_motion_video 时长检查）同样适用于本工作流。已在 192.168.10.54 实例实测：矩形遮罩替换验证 success，数值检验重绘区均值差 36.6（明显重绘）、遮罩外 0.87（像素级保持，99 分位 7.0 为缩放插值）。
- 验证命令：`python -m pytest backend/tests/test_h3_inpaint.py -q`（9 项通过）；`python -m pytest backend/tests -q`（全量回归）；`pnpm --dir frontend build`；5173 桌面端确认创作页出现「H3 局部重绘」。
- 回滚方式：撤回上述四个源码文件增量与测试文件；无数据迁移。


## 2026-11-02 动作迁移角色图 API 槽位修复

- 原因与实证：用户指定双人自拍顺拐舞、周屿与李诗雅参考后，真实任务 `Gs9PpHofi1O` 收到了 image + video 两份素材；远端视频节点和骨架控制链正确执行，但第 1 轮把前景男主生成成女生，人物、服装及背景均未跟随角色图。远端实际输入图片与上传图一致，排除了未上传与文件错配。
- 当前基线：`h3_motion_transfer_workflow.py` 节点 `12` 的角色图连接由 `ref_images: {"0": ["1", 0]}` 改成顶层 `ref_images.ref_image_0: ["1", 0]`，与当前 `COMFY_AUTOGROW_V3` 的 `ref_image_` 前缀及普通 H3 R2V builder 对齐。ComfyUI 只把顶层 API 链接视为图像依赖；嵌套写法可能无报错完成，却忽略角色图。参考 [ComfyUI #15667](https://github.com/Comfy-Org/ComfyUI/issues/15667)。
- 受影响文件：`backend/app/h3_motion_transfer_workflow.py`、`backend/tests/test_h3_motion_transfer.py`、README、本节、扩展指南和原有动作迁移验收清单。回归断言 API 扁平字段与顶层图像依赖，同时禁止重新引入嵌套 `ref_images`。
- 兼容性：只改变内部 graph 的身份参考连接；工作台 API、参数层级、数据库、节点 ID、模型文件和视频骨架链不变。新建及再次生成使用修正逻辑，历史任务快照和失败样片保留，不自动重跑。当前远端仍从实际 `/api/health` 读取。
- 质量边界更新：用户拒绝新双人竖屏片。真实骨架诊断发现 0.51 绘制阈值下腿部连线大量缺失，`max_detections=2` 的逐帧置信度选择还会从主角跳到路人；当前没有持续的双人身份跟踪，也没有源背景保护或独立面部驱动。0.30/0.10 阈值对照只供诊断，未修改生产图。身份接线回归通过不代表舞蹈复刻通过，见原 `ACCEPTANCE.md` 的后续诊断。
- 验证：`python -X utf8 -m unittest backend.tests.test_h3_motion_transfer backend.tests.test_motion_transfer_media -q`；`python -X utf8 -m pytest backend/tests -q -k "not dev_reloader"`；`pnpm --dir frontend build`。真实桌面任务保留两份参考素材，并在原任务内新增一轮受控复测，固定原素材、提示词、seed、时长与质量，只改变角色图接线；最终结果记于原 `ACCEPTANCE.md`。
- 回滚：撤回 builder 的该输入字段与对应回归断言并重载后端；无需修改历史任务或远端模型。旧嵌套字段在当前 ComfyUI 上会重现身份参考失效，不能把任务返回 success 当作角色验收通过。

## 2026-11-02 动作迁移设计图还原与能力核对

- 原因：已有动作迁移 API、双素材和参数能力，但专属工具页使用小缩略图与纵向表单，未达到 `docs/design-ref-generation/motion-transfer-20261102/工具页设计_v001.png` 的桌面布局。
- 当前基线：`/tools/motion-transfer` 使用居中横幅、1254px 创作面板与左右双栏；素材卡具有标题、大图/视频预览、视频时长和替换/移除入口。右侧依注册表排列 primary 控件，advanced 由局部 `advancedOpen` 状态控制「更多设置」展开；内部参数不展示。滑杆数值按注册表 step 精度显示。原生文件入口、资产选择、预览弹层和表单继续接到原有真实状态与 Ant Design 组件。
- 提交流程：仍发送角色图、视频有序 multipart 到 `/api/jobs`，成功进入原任务详情；增加组件内提交锁以避免连击重复请求，预览 object URL 在更换、移除或离开时释放。种子默认 0、提示词默认空，不将设计图示例伪装成用户素材或真实参数。
- 受影响文件：`frontend/src/tools/MotionTransferTool.tsx`、新增 `tools/motion-transfer-tool.css`、`generation/MotionTransferReferences.tsx`、`generation/motion-transfer.css`、两项前端测试、`frontend/public/tool-art/motion-transfer-pose.webp` 及本节/README/扩展指南/原有验收清单。共享素材组件新增可选 `variant="tool"`，默认 compact 保持生成页布局。
- 兼容性：不新增 API、数据库字段、ComfyUI 节点或模型映射，历史任务和生成页可继续使用。保留 ZLY 页头与导航，因此页面整体锚点相对无侧栏设计图有平移；只做桌面端与两种主题检查。
- 验证命令：`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_h3_motion_transfer backend.tests.test_motion_transfer_media -q`；`python -X utf8 -m pytest backend/tests -q -k "not dev_reloader"`（排除会重启当前 7865 的开发重载器用例）；真实 5173 桌面检查和结果见原有 `ACCEPTANCE.md`。临时产物只写入已忽略的 `test-results/motion-transfer-reconstruction/`。
- 能力边界：UI 还原阶段从运行工作台 `/api/health` 读取当前生效远端 `http://192.168.10.54:8188`，只读确认实际 graph 所需 22 类节点和 7 个模型均存在。当时旧 `remote-history.json` 曾有 SDPose 骨架提取错误，不能仅凭接口与模型可用宣称出片通过；随后已完成本页上方“角色图 API 槽位修复”的真实 GPU 对照复测及用户新选竖屏片，旧 SDPose 错误未复现，具体质量边界与原音乐后期处理记于原 `ACCEPTANCE.md`。
- 回滚：仅恢复工具组件与共享素材组件/CSS 的本次增量，移除新增样式、装饰资源和本次测试后按 `pnpm --dir frontend build` 构建；原 API、参数、任务与供应商设置不需迁移。

## 2026-11-02 生成档位与模型体积按 ComfyUI 机器配置自动托管

- 原因：生成页把「生成速度（采样步数）」和「模型体积（完整 32 GB / 精简 20 GB）」直接暴露给用户选择，属于过专业的技术参数，普通用户无法理解；按产品规范它们本就属于 internal（采样步数、设备/精度、显存类），应由后端默认值托管。
- 当前基线：全部 H3 家族（官方 H3、LightX2V、八步双加速、Director 加速版、T8、数字人口播）的 `speed`、`custom_steps`、`weight_profile` 统一改为 `ui_group=internal`，创建页、导演台视频设置与工坊生成设置都不再渲染这三个控件（游客 `public_payload` 与登录态 `payload` 均不再把 `speed`/`weight_profile` 归入 primary/advanced）。后端在 `normalize_options` 内按 ComfyUI `/system_stats` 探测的机器内存自动托管：`ram_total ≥ 40 GiB` 托管为完整权重 + 工作流默认档位（官方 H3 为均衡 8 步加速）；`ram_total < 40 GiB` 托管为精简权重 + 高质量 20 步完整采样（精简权重挂不了加速 LoRA，8 步无加速属于欠采样组合，故档位联动切到 quality）。读不到内存（`/system_stats` 不可用或缺 `system.ram_total`）时回退历史默认（完整权重 + 工作流默认档位）。Director 加速版两种档位都不依赖加速权重，仅托管模型体积、不联动档位。二采精修一采的平台托管默认值（`_refine_first_pass_defaults`）同样感知内存：LightX2V/八步双加速/T8 在低内存机器上的一采换为精简权重 + 20 步 + 关闭 LoRA，标准官方 H3 的一采保持平台固定（精简权重 + 8 步 LightX2V LoRA，与机器无关）。
- 显式值优先：旧 API/MCP 客户端显式提交 `speed` / `weight_profile` / `custom_steps` 仍被接受并按原逻辑校验；显式选加速档位（fast/balanced/≤8 步 custom）但未选权重时，托管为完整权重以保证 Turbo LoRA 可挂；显式选精简权重但未选档位时，托管为 quality 档避免欠采样。
- 硬件探测：`main.py` 应用工厂注入 `workflow_registry.set_hardware_profile_resolver()`，解析器经 60 秒 TTL 缓存（`TTLCache`）调用 `ComfyService.system_stats()`，返回 `{ram_total, vram_total, gpu}`；纯决策逻辑（`auto_weight_profile` / `auto_h3_runtime_options` / `auto_h3_weight_profile` / `comfy_ram_total_bytes`）留在 `workflow_registry.py`，便于单测与复用。每 60 秒最多一次同步探测（5 秒超时），无新增端口、路由或 ComfyUI 依赖。
- 受影响文件：`backend/app/workflow_registry.py`（internal 声明 + 自动托管逻辑 + 一采感知）、`backend/app/main.py`（硬件解析器注入）、`frontend/src/director2/director2-video-settings.ts`（兜底字段与生成摘要移除模型体积/生成质量）、对应后端/前端测试。任务详情的「运行参数」折叠区继续回显含托管值的完整有效参数快照，可复现、可排障。
- 兼容性：不新增 API、数据库列、节点 ID 或模型路径；`weight_profile`/`speed` 字段与枚举不变，历史任务按已保存参数回放；localStorage 中导演台已保存的 speed/weight 旧值会被前端 sanitize 丢弃，改由后端托管。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_core -q`（含新增 `HardwareAutoHostingTests` 13 项）；全量 `python -X utf8 -m unittest discover -s backend/tests -t . -q`（1231 项通过）；`npx vitest run`（584 项前端测试通过）；`pnpm --dir frontend build`。
- 回滚方式：把七个 option 构造函数的 `ui_group` 改回原值（`h3_speed_option`/`h3_custom_steps_option`/`h3_weight_profile_option`/`lightx2v_speed_option`/`dual_accel_speed_option`/`director_accel_speed_option`/`director_accel_weight_profile_option`），删除 registry 中自动托管块与 `main.py` 的 resolver 注入、`_refine_first_pass_defaults` 的 pruned 分支，并恢复前端兜底字段/摘要，重启后端并重新构建前端；已提交任务不受影响，无需数据库回滚。

## 2026-11-02 动作迁移工作台上传提交与回显链路补齐

- 原因：此前成功记录只证明直接提交 ComfyUI graph 可以出片。工作台前端 `newAssets` 过滤掉视频，`POST /api/jobs` 与追加轮次仍校验为纯图片，工具卡保持“即将上线”；空提示词、固定 seed 和运行参数快照也未闭环。下方旧“新增工作流”章节仅是底层图联调记录，不代表当时工作台已可用。
- 注册表为唯一能力来源：`WorkflowDefinition` / `ModeResponse` 新增默认关闭的 `accepts_video_reference` 和可空的 `default_prompt`，只有动作迁移启用视频能力；固定顺序为 references[0] 角色图、[1] 动作视频。公开参数声明 `image/*,video/*`，提示词可省略或留空，其余工作流仍拒绝空提示词及视频上传。新字段为增量，不改接口路径、数据库表或既有 graph 节点 ID。
- 参数产品化：primary 仍为动作强度、画面比例、生成时长；advanced 为 `render_quality`（preview=8 / standard=20 / fine=30）与 seed。steps 移入 internal，旧 API 显式 steps 仍兼容；内部 width/height/length/fps 由注册表归一化后、入队前计算并持久化。seed=0 在入队前随机一次，非零固定值经过范围/类型校验并在执行时保持不变；再次生成依据上一轮原始 seed 请求区分“随机”与“固定”。15 秒由错误的 345 帧修正为 362 帧，实际时长为 15.083 秒（5/10 秒对应 124/243 帧）。
- 上传与执行：`main.py` 的创建/追加轮次共用按角色的 MIME 校验、50 MiB 大小约束和保存后校验。角色图片必须可解码，视频经 FFprobe 确认可读且覆盖所选时长（容器误差容许 0.1 秒）；失败返回明确 422/413，清理已保存部分，不入队。`motion_transfer_media.py` 在执行前用 FFmpeg 取开头窗口、转 24fps、限制最长边 1280、对齐 H3 帧数，仅为网格尾部补帧，避免对整段长视频提取骨架。处理中间 MP4 放在 staging 独立临时目录，上传后删除。仍走已有串行 `JobWorker`、取消与 ComfyUI 历史恢复链路；输出是 H3 原生音轨，不是源视频音轨。
- 前端：`App.tsx` 依据视频能力显示 `generation/MotionTransferReferences.tsx` 双槽组件，沿用原 Ant Design 业务控件及根级 `--studio-*` 双主题；视频用 video/预览弹窗而非 img。图片/视频媒介草稿切换保留动作视频，替换/移除/卸载释放对象 URL。`/tools/motion-transfer` 为已注册的受保护启动路径，`ToolsWorkspace` 跳转到 `/generate/video?workflow=minimax-h3-motion-transfer`，在 `/api/modes` 确认能力后自动选择并清除参数；复用现有创作表单、任务页和登录门禁，不复制另一套表单。工具中心/首页卡同步改为可用。
- 历史素材：混合媒体任务的 `references` 新增可选 kind/label，两个鉴权参考素材接口按实际 MIME 返回文件，仍检查原有账号权限和 uploads 根目录。`reference-assets.ts` 依声明角色还原视频 File，`VideoRoundHeader.tsx` 显示视频标记并打开播放器，重新编辑同时恢复图片和动作视频；旧纯图片参考图继续按原逻辑处理。
- 受影响文件：`backend/app/{workflow_registry.py,models.py,main.py,comfy_service.py,h3_motion_transfer_workflow.py,motion_transfer_media.py}`；`frontend/src/{App.tsx,paths.ts,reference-assets.ts}`、`generation/{MotionTransferReferences.tsx,motion-transfer.ts,motion-transfer.css}`、`media/VideoRoundHeader.tsx`、`tools/{ToolsWorkspace.tsx,tool-registry.ts}`；对应后端/前端测试及 README、扩展指南、API 文档。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_h3_motion_transfer backend.tests.test_motion_transfer_media backend.tests.test_workflow_avatar -q`；`python -X utf8 -m pytest backend/tests -q`；`pnpm --dir frontend build`。额外的 `backend.tests.test_motion_transfer_browser` 默认跳过，设置 `ZLY_MOTION_BROWSER_E2E=1` 后用真实 5173 / 1536×864 桌面和临时 SQLite API 验证双主题、原文件字节与顺序、真实登录/CSRF、草稿保留、202 入队及重新编辑；设置 `ZLY_MOTION_RENDER_E2E=1` 才额外执行一次真实远端 GPU 任务。地址每次从运行中的 `/api/health` 读取，不改供应商配置，不写生产任务库。最终验收结果见同轮界面验收记录。
- 回滚：仅撤回上述文件的本轮增量及新建文件，把动作迁移工具状态恢复 coming_soon，构建前端；不撤回既有工作流接入及其它用户改动。无数据库迁移或模型/节点回滚，旧任务、已有成片和当前 ComfyUI 配置保持原样。

## 2026-11-02 创作页新增「H3 数字人口播」工作流（minimax-h3-avatar）

- 当前基线：创作页新增可见工作流 `minimax-h3-avatar`（`JobMode.MINIMAX_H3_AVATAR`，catalog_group=official_h3）。graph 在 `backend/app/minimax_h3_avatar_workflow.py`，基于远端 `comfyui-minimax-h3-audio-T8` 包（v1.3.0）的 `audio_lock` 官方示例链路：LoadImage（人物形象图，first_frame 精确帧 0）+ LoadAudio（口播音频）→ `MiniMaxH3AudioWindowT8`（按 24fps、17n+5 网格对齐渲染窗口，同时输出 length 与裁切参数）→ `MiniMaxH3AudioConditioningT8`（task_type=auto 实际路由 I2VA、audio_mode=lock_source、audio_denoise_strength=0.35、drive_audio 驱动口型）→ `SamplerCustomAdvanced`（KSamplerSelect res_multistep + BasicScheduler simple，4/8/20 步随生成速度，Turbo LoRA 走 `LoraLoaderBypassModelOnly`）→ `MiniMaxH3AVDecodeT8`（音画联合解码）→ `MiniMaxH3OutputTrimT8`（裁回精确口播时长）→ `VHS_VideoCombine`（输出节点 `14`，24fps h264-mp4，前缀 `MiniMaxH3/ZLY_AI_VIDEO_STUDIO_AVATAR`）。画布走 `ResolutionSelector` 32 对齐，受 T8 条件节点 1344×768 面积上限约束；模型/VAE/文本编码器与既有 H3 工作流完全同源（`minimax_h3_fl2va_*` + `qwen3vl_32b_nvfp4_awq` + 双 VAE + `ReservedVRAMSetter` 3GB + SageAttention），零新增模型。
- T8 契约要点（远端 0.43.0 实测得出）：①Hybrid 路径被 T8 包禁用（ComfyUI 变更了 ref/keyframe latent 组装，`assert_hybrid_layout_contract` 拦截），因此 `add_source_as_reference` 固定 False——源音频只编码进 AV latent 驱动口型，不进参考媒体表；②提示词不得携带 `<Audio n>` 标签（strict 校验会因 available audio count is 0 失败），builder 自动追加不含媒体标签的说话场景描述；③I2VA 契约禁止参考媒体，task_type 固定 auto 由节点自行路由；④**不要用 T8 的 `DualClockSamplerT8`/`MiniMaxH3MultiRateSamplerEXPT8` 采样器**——0.43 核心已把双时钟音频承载收编为原生 `model_sampling.audio_scale`，T8 采样器替换 model_sampling 后会触发 `'MiniMaxH3FlowSampling' object has no attribute 'audio_scale'`（既有 `minimax-h3-t8-dual-clock` / `minimax-h3-t8-all-reference` 工作流在该实例上同样受影响，待后续处理），avatar 采用与 lightx2v/dual-accel 相同的原生采样路径。
- 音频承载与校验：`WorkflowDefinition` 新增 `accepts_audio_reference` 字段，avatar 的 references 顺序约定为 [0]=人物形象图、[1]=口播音频（沿用动作迁移的 references 多类型先例）。`main.py submit_generation` 按 index 放行 audio content-type（audio/* 或 application/octet-stream），保存后用 `SystemFfmpegRunner.probe_duration`（ffprobe，回退 wave 模块）探测音频时长，超约 5 秒（`AVATAR_MAX_SCENE_SECONDS`，124 帧单渲染窗口）直接 422 拒绝，探测结果写入 `options.scene_duration_seconds` 供 AudioWindow 使用；长音频分窗渲染留作后续迭代。
- 实现文件：`backend/app/models.py`（新增 JobMode）、`backend/app/minimax_h3_avatar_workflow.py`（新增 graph 构建器）、`backend/app/workflow_registry.py`（`AVATAR_OPTION_SCHEMA`、WorkflowDefinition + `accepts_audio_reference` 字段、`AVATAR_WORKFLOW_IDS`/`is_avatar_workflow`、`H3_WORKFLOWS` 纳入串行视频 worker、references 参数描述）、`backend/app/comfy_service.py`（run() 分发 + avatar 跳过 `<Picture n>` 提示词注入）、`backend/app/main.py`（音频 content-type 校验 + 时长探测，director_export 导入 `SystemFfmpegRunner`）、`backend/tests/test_workflow_avatar.py`（9 项测试）。前端 `frontend/src/App.tsx`：Workflow 类型加 `accepts_audio_reference`、新增 `AvatarReferencePanel` 双槽上传（形象图 + 口播音频，含时长预检与超限提示）、`appendFiles` 限流 1 张图、`selectWorkflow` 切换清理、`createMutation` 追加音频并新增 onError、数字人模式隐藏 `<Picture n>` 标签行。
- 用户可见行为：创作页视频模式官方 H3 分组出现「H3 数字人口播」——上传一张人物形象图和一段 5 秒内的口播音频（WAV/MP3），填写提示词（描述人物与场景），生成口型与语音同步的说话视频；primary 参数为画面比例、生成速度（快速 4 步/均衡 8 步/高质量 20 步）、模型体积，其余全部后端托管。
- 兼容性：仅新增 JobMode 与注册表条目，不改既有工作流节点 ID、API 与数据库表；`submit_generation` 的音频校验只在 `accepts_audio_reference=True` 的工作流生效，其他工作流仍为纯图片。当前版本口播音频上限约 5 秒（单渲染窗口），提示词不引用媒体标签。
- 验证命令：`python -m unittest backend.tests.test_workflow_avatar -v`（9 项）；`python -m unittest backend.tests.media_studio_test_h3_video backend.tests.test_director_workflow_speed backend.tests.test_comfy_provider`（165 项回归）；`npx tsc --noEmit -p frontend/tsconfig.json`；远端 192.168.10.54 实测：占位形象图 + 3.99s 中文语音（SAPI 合成）直连 `/prompt` 提交成功，`node_errors={}`，渲染 success 输出 `ZLY_AI_VIDEO_STUDIO_AVATAR_00001-audio.mp4`（4.0s / 864×480 / 24fps / h264+AAC 含音轨），抽帧确认口型开合、眨眼与挥手等音频驱动动画；验收过程共排除三个 T8 契约问题（task_type、add_source_as_reference、采样器版本兼容），最终 graph 即当前构建器输出。
- 回滚方式：撤回上述五个源码文件增量、前端 App.tsx 增量与测试文件即可；无数据迁移，历史任务记录不受影响。

## 2026-11-02 创作页新增「H3 动作迁移」工作流（minimax-h3-motion-transfer）

- 当前基线：创作页新增可见工作流 `minimax-h3-motion-transfer`（`JobMode.MINIMAX_H3_MOTION_TRANSFER`，`hidden_from_catalog=False`，catalog_group=official_h3）。graph 在 `backend/app/h3_motion_transfer_workflow.py`，复刻 ComfyUI 官方模板 `video_minimax_h3_fun_controlnet_union` 的姿势迁移管线并内联其 SDPose 子图：LoadImage（角色形象图，`ref_images` autogrow 槽位 0 锁身份）+ LoadVideo/GetVideoComponents（动作参考视频）→ RTDETR_detect → SDPoseKeypointExtractor/SDPoseDrawKeypoints（全身骨架序列）→ MiniMaxH3FunControlNetApply（`strength` 即动作跟随强度，model_patch=`minimax_h3_fun_controlnet_union_pruned_int8_convrot`）→ MiniMaxH3ReferenceToVideo（ref2va 权重 + qwen3vl 文本编码器 + 视频/音频双 VAE，音画一体）→ SamplerCustomAdvanced（res_multistep/simple/默认 20 步）→ CreateVideo → SaveVideo（输出节点 `28`，`video/h3_motion_transfer` 前缀）。画布 32 对齐（16:9=864×480 / 9:16=480×864 / 1:1=640×640），帧数 17n+5 网格（5s=124 / 10s=243 / 15s=345），宽高与帧数由 primary 的 `aspect_ratio`/`duration` 在分发层映射并回写生效快照。对 ComfyUI 端的依赖：0.43 核心（含 `MiniMaxH3FunControlNetApply`/`MiniMaxH3ReferenceToVideo`/`ModelPatchLoader`）、ComfyUI-H3-FaceRefine 无需、SDPose 权重 `sdpose_wholebody_fp16`（checkpoints）、`rt_detr_v4-x-hgnet_fp16`（diffusion_models）、Fun ControlNet patch（model_patches）。
- 实现文件：`backend/app/models.py`（新增 JobMode）、`backend/app/h3_motion_transfer_workflow.py`（新增 graph 构建器与尺寸/帧网格工具）、`backend/app/workflow_registry.py`（`MOTION_TRANSFER_OPTION_SCHEMA`、WorkflowDefinition、`MOTION_TRANSFER_WORKFLOW_IDS`/`is_motion_transfer_workflow`、`is_local_comfy_job` 纳入串行视频 worker）、`backend/app/comfy_service.py`（run() 分发 `_run_motion_transfer`：references[0]=角色形象图 `upload_image`、references[1]=动作参考视频 `upload_video`；`completed_outputs` 恢复分支）、`backend/tests/test_h3_motion_transfer.py`（新增 10 项测试）。前端零改动：创作表单按 `ui_group` 通用渲染（primary=动作跟随强度/画面比例/生成时长，advanced=采样步数/随机种子，其余 internal 托管）。
- 用户可见行为：创作页视频模式出现「H3 动作迁移」——上传一张角色形象图和一段动作参考视频（如舞蹈视频），可选填写提示词（留空使用内置默认），即可把参考视频里的动作迁移到角色身上，输出带 H3 原生音频的成片。
- 兼容性：新 JobMode 仅新增枚举值与注册表条目，不改既有工作流节点 ID、API 与数据库表；references 顺序约定（图在前、视频在后）与 VACE 深度复刻（视频在前）不同，二者互不影响。依赖远端实例已升级至 ComfyUI 0.43+ 并安装 Fun ControlNet Union / SDPose 权重（2026-11-02 已在 192.168.10.54 实例完成部署并实测出片：864×480 / 124 帧 / 5.17s / 含音轨，带与不带角色参考图两次验收均 success）。
- 验证命令：`python -m pytest backend/tests/test_h3_motion_transfer.py -q`（10 项通过）；`python -m pytest backend/tests -q`（全量回归）；`pnpm --dir frontend build`；5173 桌面端创作页确认「H3 动作迁移」出现在官方 H3 分组且 primary/advanced 分层正确（需后端 7865 重启后生效）。
- 回滚方式：撤回上述四个源码文件增量与测试文件即可；无数据迁移，历史任务记录不受影响。

## 2026-11-03 工具中心新增「视频局部重拍」「视频超分」工具页

- 当前基线：「AI 工具」中心两个新工具页，均由「上传素材 → schema 驱动参数 → POST /api/jobs → 跳转生成页」构成，复用 `motion-transfer-tool.css` 工具页视觉与 `reference-assets` 素材恢复机制：
  - `/tools/partial-retake`（`frontend/src/tools/PartialRetakeTool.tsx`）：遮罩图(白色=重绘区) + 原片视频上传，提交 `mode=minimax-h3-inpaint`；助手模块 `frontend/src/generation/inpaint.ts`（校验/时长/选项泛型复用 `generation/motion-transfer.ts`）。
  - `/tools/video-upscale`（`frontend/src/tools/VideoUpscaleTool.tsx`）：原片上传 + 增强引擎单选（RTX 2x 快速 / SeedVR2 生成式），提交 `mode=nvidia-rtx-vsr` 或 `mode=seedvr2-upscale`（两个隐藏工作流的 run() 均已支持 `references[0]` 独立上传源片，`run_upscale_output(source_path=...)`）；助手模块 `frontend/src/generation/upscale.ts`（≤500MB 校验）。
  - 注册表 `frontend/src/tools/tool-registry.ts`：「视频局部重拍」「视频超分」翻 available，图标键 `partial-retake`(Brush)/`video-upscale`(MonitorUp)；工具中心与首页翻页墙自动出现。`paths.ts` 新增两条工具路径；`ToolsWorkspace.tsx` 新增两处路由。
- 用户可见行为：工具中心视频分组新增两张可用卡——「视频局部重拍」（遮罩外逐帧像素级保持原片、音轨不变）与「视频超分」（RTX 秒级 2x / SeedVR2 慢速补细节，倍率固定 2x）；生成页首页多功能墙同步更新。
- 兼容性：纯前端增量；后端工作流与 API 无改动。`nvidia-rtx-vsr`/`seedvr2-upscale` 仍 `hidden_from_catalog=True`（不出现在创作页模型列表），工具页经 `/api/jobs` 直提。
- 验证命令：`pnpm --dir frontend exec vitest run src/tools`（12 项通过，含 3 个新工具页测试）；`pnpm --dir frontend build`；5173 桌面端工具中心确认两张卡可进页并完整走提交流。
- 回滚方式：撤回上述前端文件增量即可；无后端与数据影响。

## 2026-11-01 LLM 供应商凭据档案（按服务保存 Key 与模型）

- 原因：端砚接入实测确认切换供应商必须重新粘贴 API Key（既有安全设计：凭据不跨服务地址复用），用户要求按供应商保存 Key 与模型记录以便随时切换。
- 当前基线：新增表 `llm_endpoint_credentials`（`base_url` 主键、`api_key_encrypted`、`model`、`updated_at`；SQLite schema 在 `storage.py initialize()`，MySQL 在 `sql/020_llm_endpoint_credentials.sql`，upsert 用「先查后改/插」的可移植写法）。`llm_provider.py`：`update()` 保存带 Key 时登记/刷新该端点档案；同端点不带 Key 保存时把既有主配置凭据回填为档案（历史数据升级即用）；切换端点时自动采用该服务档案 Key（密文直迁，无需主密钥重新加密），无档案且非本地端点仍要求填写一次并明确提示，切到本地端点保持清空；`test()` / `list_catalog()` 经新增 `_resolve_request_key()` 对非激活端点自动使用档案 Key；`public_config()` 新增 `saved_provider_credentials`（`models.py` 新增 `LlmEndpointCredentialSummary`，仅返回掩码）。前端 `LlmProviderSettings.tsx`：选中预设时若该服务有档案则自动带出上次使用的模型；Key 输入框占位符与下方提示展示「已保存掩码 Key，留空自动沿用」；输入新 Key 保存即覆盖档案。
- 受影响文件：`backend/app/storage.py`、`sql/020_llm_endpoint_credentials.sql`（新增）、`backend/app/models.py`、`backend/app/llm_provider.py`、`frontend/src/admin/LlmProviderSettings.tsx`、`backend/tests/test_llm_endpoint_credentials.py`（新增）、`.gitignore`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：PUT /api/admin/providers/llm 请求字段不变；响应新增 `saved_provider_credentials` 字段（前端可选消费）。VLM / TTS 设置页不在本次范围（各自独立凭据与「复用大模型凭据」开关不受影响）。无数据迁移：历史凭据在下次同端点保存时自动回填档案；档案切换同样依赖 `ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY` 可用（密文可直迁，但解密调用仍需主密钥）。后端测试使用临时 SQLite，MySQL 端建表走既有启动重放机制。
- 验证命令：`python -m pytest backend/tests/test_llm_endpoint_credentials.py backend/tests/test_llm.py backend/tests/test_llm_capabilities.py backend/tests/test_internai_provider.py backend/tests/test_zhipu_provider.py backend/tests/test_qiniu_provider.py -q`（137 项通过）；`python -m pytest backend/tests -q`（全量，见功能说明变更章节）；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend exec vitest run src/admin`（9 项）通过；5173 桌面端实测切换流程。
- 回滚方式：撤回上述源码增量并删除 `sql/020_llm_endpoint_credentials.sql` 与测试文件即可；`llm_endpoint_credentials` 表可保留（不影响运行）或 `DROP TABLE`，无其它数据迁移。

## 2026-11-01 书生·端砚 Discovery 官方预设与限时免费模型

- 原因：按用户提供的公众号文章（2026-11-01 核对，计费口径引自上海AI实验室 2026-09-13 官方新闻与端砚 Token Plan 官方文档），为管理设置补充上海AI实验室「书生·端砚」科研模型平台（`https://discovery-api.intern-ai.org.cn/v1`，标准 OpenAI 兼容协议，结尾必须带 `/v1`）官方预设，接入其测试期每月发放墨点的 10 款模型：`intern-s2`（书生-S2）、`atria-dawn-preview`、`agents-a1` 三款「限时 0 墨点」（官方仅注明测试期、未公布截止日），以及 `deepseek-v4-flash-0731`（ID 已由第三方实测确认）、`deepseek-v4-pro-0813`、`deepseek-v4-flash-vision`、`glm-5.3`、`kimi-k2.6`、`minimax-m3`、`qwen3.8-27b` 七款按墨点计费模型。
- 当前基线：新增 `backend/app/internai_catalog.py` 维护官方端点严格匹配（仅 `https`、`discovery-api.intern-ai.org.cn`、空路径或 `/v1`，拒绝旧入口 `chat.intern-ai.org.cn` 与仿冒后缀域名）、三款免费 / 七款计费的静态判定（不带时间窗口，以 `pricing_verified_at` 记录核对日期）与官方预设；`zhipu_catalog.model_provider_presets()` 在七牛之后追加端砚预设（`vision_models` 仅为平台官方口径中唯一可看图的 `deepseek-v4-flash-vision`）。`llm_client.py`：`catalog_provider_key` 识别 `discovery-api.intern-ai.org.cn` 返回 `internai`；`classify_model_free` 在七牛判定之后追加端砚判定，上游显式付费元数据仍优先。`llm_capabilities.py` 新增 `internai` 分支：按聚合网关保守口径对齐 modelscope 先例（不发送原生 tools，仅 deepseek/glm/qwen 工具家族启用 `json_object`，不发送显式缓存字段）。`llm_provider.py` 的 `VISION_MODEL_MARKERS` 无需改动（模型名自带 `vision` 字样）。前端仅在两个设置页的 `canFetchCloud` 自动拉目录白名单加入 `internai`（该平台 `/v1/models` 需携带 Key，与 zhipu/siliconflow 同机制），预设下拉经既有 `GET /api/admin/providers/model-presets` 动态渲染。
- 受影响文件：`backend/app/internai_catalog.py`（新增）、`backend/app/llm_client.py`、`backend/app/llm_capabilities.py`、`backend/app/zhipu_catalog.py`、`frontend/src/admin/LlmProviderSettings.tsx`、`frontend/src/admin/VlmProviderSettings.tsx`、`frontend/src/admin/provider-models.test.ts`、`backend/tests/test_internai_provider.py`（新增）、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：不新增 API 路由、数据库表 / 列、任务队列、ComfyUI 节点、工作流 graph 或依赖；`model-presets` 响应新增一个预设对象，前端按 key 渲染属既有逻辑。既有智谱 / 七牛 / ModelScope / 硅基流动判定分支与已保存配置不受影响；端砚免费标记在平台恢复计费后需人工更新目录表（上游显式价格元数据出现时自动优先）。
- 验证命令：`python -m pytest backend/tests/test_internai_provider.py backend/tests/test_qiniu_provider.py backend/tests/test_zhipu_provider.py -q`（41 项通过，含 TestClient 管理员会话验证 `GET /api/admin/providers/model-presets` 返回 zhipu→qiniu→internai）；`python -m pytest backend/tests -q`（1151 项全部通过）；`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend exec vitest run src/admin`（9 项通过，含端砚预设映射契约测试）与 `pnpm --dir frontend build` 均通过。真实连通验证待管理员在端砚平台创建 API Key 后于设置页执行「测试连接」「拉取模型目录」。
- 实机验证补充（同日）：真实 Key 实测目录为 13 款（文章 10 款 ID 全部命中，另有 `Atria-Dawn`、`deepseek-v4.1-flash-1017`、`Sage-A1.5` 三款未知计费模型显示「价格未知」）；`intern-s2` 短回复 14.5 秒、`Agents-A1` 短回复可用，但两模型对 1800 token 级润色生成都超过原 60 秒超时导致 502。为此将润色链路超时统一为新增常量 `LLM_OPTIMIZE_TIMEOUT_SECONDS`（现值 300.0，与导演台对话上限一致；`llm_client.py` 的 `optimize_prompt` / `translate_h3_prompt_to_chinese` / 参考图描述 / 看图理解 JSON，及 `llm_provider.py` 带图润色 `complete_authoring`），快响应供应商不受影响。注意 requests 的 read timeout 约束的是字节间隔而非总时长，网关慢速滴流回传时总耗时可以超过该值：intern-s2 润色实测 504 秒返回 HTTP 200，但内容为省略号骨架（`[Shot 1] ...`），免费通道不适合交互式润色。回滚时将该常量调用点恢复为 60 秒字面量即可。
- 回滚方式：撤回上述四个后端源码文件与两个前端文件的本次增量（删除 `internai_catalog.py` 与对应测试文件）即可恢复原预设列表；无数据迁移。

## 2026-11-01 界面图标与标题比例对标即梦

- 原因：用户反馈立体图标偏插画、与系统不搭，要求参考即梦，并明确缩小左侧图标、Logo 和标题。读取真实即梦资产 / 创作页：导航图标 20px、条目 36–40px、菜单文字 14px，创作标题 30px / 400；借鉴图形与密度关系，不复制第三方 SVG 路径。
- 实现：新增 `frontend/src/components/StudioSymbols.tsx`，提供原创折片 Z 与四枚导航 SVG，替换 `StudioHeader` / `App.tsx` 的 WebP 引用。图形随 `currentColor`、`--studio-symbol-accent/secondary` 和根主题显示，无独立主题状态。旧 `frontend/public/studio-icons/` 保留用于恢复，不再由 Header / 主菜单加载。
- 当前尺寸：顶栏仍高 48px，工作区仍从 y=76 起始；Logo 28×28、字标 16px、副标题 13px；76px 轨道内菜单项 56×60、图标 22×22、标签 11px。轻量中性选中背景与细短指示线、唯一活动项及 2px 焦点共同表示状态。
- 字体层级：生成首页主标题 24px / 500、入口标题 16–18px、最近创作 15px；画布首页主标题 24px、最近项目 20px、新建 / 库标题 18px；导演台首页左栏 22px、工程列表标题 24px、筛选文字 14px、刷新 / 搜索高 36px；资产日期标题 18px。导演对话创作室及官方复刻 token 不变。
- 受影响文件：`StudioSymbols.tsx`、`StudioHeader.tsx`、`studio-header.css`、`App.tsx`、`index.css`、`generation/generation-home.css`、`canvas/canvas-home.css`、`director2/director-home.css`；前端设计规范、README、扩展指南、导演台流程、画布说明及新截图基线。
- 兼容性：沿用现有 NavLink、根主题、登录门禁、最后访问地址和任务栏状态；无依赖、API、数据库、任务协议或 ComfyUI 变化。未创建生成任务，只检查桌面，浏览器主题检查后恢复。
- 验证：`pnpm --dir frontend build`（76 文件 / 558 项前端测试、TypeScript 与 Vite 通过）；`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_accounts backend.tests.test_guest_catalog -q`（114 项通过）。真实 `http://localhost:5173` 已有登录态四个工作区浅暗主题实测：SVG 22px、Logo 28px、菜单 56×60、选中项唯一、标题层级生效，无水平溢出；游客画布入口仍打开登录弹窗。记录在 `design-ref-generation/navigation-brand-20261101/implementation/`，导演台基线在 `design-ref-director/navigation-brand-20261101/`。
- 回滚：仅撤回本轮 8 份源码的 SVG 引用、尺寸和字体增量，删除新增 `StudioSymbols.tsx`，恢复保留的 WebP 引用后构建；保留同期其它改动，无后端或数据恢复。

## 2026-11-01 七牛云 AI 推理官方预设与 conatus 限时免费模型

- 原因：参照 Smart-Floor-Planner 项目已验证的接入方式，为管理设置补充七牛云 AI 大模型推理（`https://api.qnaigc.com/v1`，OpenAI 兼容）官方预设，接入其 1024 限时免费匿名融合模型 `qiniu/conatus-free`（官方活动页 2026-11-01 核对：免费窗口北京时间 2026-10-24 00:00 至 2026-11-30 23:59，结束即停止调用；官方声明支持工具调用、深度思考、结构化输出与图像理解，每日免费额度按账号实名等级发放）。
- 当前基线：新增 `backend/app/qiniu_catalog.py` 维护官方端点严格匹配（仅 `https`、`api.qnaigc.com`、空路径或 `/v1`）、活动窗口内免费判定与官方预设；`zhipu_catalog.model_provider_presets()` 在智谱之后追加七牛预设（`chat_models` 与 `vision_models` 均为 conatus，免费标记 `true`），前端两个设置页经既有 `GET /api/admin/providers/model-presets` 动态渲染，无需前端改动。`llm_client.py`：`catalog_provider_key` 识别 `qnaigc.com`（含子域，拒绝仿冒后缀域名）返回 `qiniu`；`classify_model_free` 在智谱官方判定之后追加七牛活动判定，上游显式付费元数据仍优先；`_thinking_control_fields(model, base_url)` 对官方端点上的 conatus 默认发送智谱式 `thinking.type=disabled`（Smart-Floor-Planner 生产已验证该请求体），显式 `thinking_enabled` 可覆盖，中转地址与其它模型一律不发送。`llm_capabilities.py` 新增 `qiniu` 分支：conatus 开放原生工具与 `json_object` 结构化输出，其余模型保持聚合网关保守口径。`llm_provider.py` 的 `VISION_MODEL_MARKERS` 增加 `conatus`（模型名无 VL/Vision 字样但官方支持图像理解），VLM 设置与目录过滤随之生效；qiniu `/v1/models` 目录为公开接口，无需 Key 即可拉取。
- 受影响文件：`backend/app/qiniu_catalog.py`（新增）、`backend/app/llm_client.py`、`backend/app/llm_capabilities.py`、`backend/app/llm_provider.py`、`backend/app/zhipu_catalog.py`、`backend/tests/test_qiniu_provider.py`（新增）、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：不新增 API 路由、数据库表 / 列、任务队列、ComfyUI 节点、工作流 graph 或依赖；`model-presets` 响应新增一个预设对象，前端按 key 渲染属既有逻辑。智谱判定分支与既有 deepseek/qwen 思考控制行为不变；非官方端点、其它模型与已有已保存配置不受影响。活动窗口结束后 conatus 不再标免费（模型本身也停止服务），无需代码回滚窗口。
- 验证命令：`python -m pytest backend/tests/test_qiniu_provider.py backend/tests/test_zhipu_provider.py backend/tests/test_vlm.py -q`（49 项通过）；`python -m pytest backend/tests -q`（1142 项全部通过）。真实连通验证待管理员填入七牛 API Key 后在设置页执行「测试连接」。
- 回滚方式：撤回上述五个后端源码文件的本次增量（删除 `qiniu_catalog.py` 与对应测试文件）即可恢复原预设列表；无数据迁移。

## 2026-10-31 Z 品牌标识与立体主菜单

- 原因：用户确认复杂精细的紫色立体图标方案，要求据此还原真实界面。基线为 `design-ref-generation/navigation-brand-20261031/zly-navigation-brand-v005.png`；设计稿中的选中示意不作为路由状态。
- 当前实现：`StudioHeader` 用主题对应的胶片 Z WebP 替换品牌星芒；`App.tsx` 的桌面主菜单用生成、场记板、多卡片画布、文件夹四枚独立透明 WebP。`frontend/public/studio-icons/` 保存 6 张 256×256 素材（Z 浅暗两版及四枚菜单图标，合计约 405 KiB）；原始素材板、裁切范围、哈希和 API 用量在设计目录 `implementation/` 归档。
- 视觉规格：共用 48px 悬浮顶栏、40px 品牌图片、76px 全局导航轨道；菜单项由 52×50 调整为 64×80，图片框 44×44（画布框 50×44），标签 12px / 16px。选中项使用成对的 `--studio-nav-active-*` / `--studio-nav-indicator`，带边框与左指示线，焦点保留 2px outline。根 Provider 驱动 Logo 换图及配色，不新增主题状态。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/src/components/StudioHeader.tsx`、`studio-header.css`、`frontend/public/studio-icons/`、`frontend/DESIGN.md`；README、扩展指南、导演台流程文档及相关设计素材 / 截图。
- 兼容性：生成 / 导演台 / 画布 / 资产共用同一导航，现有 `NavLink`、登录门禁、返回地址、任务栏展开状态和业务图标保持原接线。无新依赖、端口、API、数据库、工作流、ComfyUI 或创作数据迁移；本轮仅检查桌面。
- 验证：`pnpm --dir frontend build`（76 个测试文件 / 558 项，TypeScript 与 Vite 构建通过）；`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_accounts backend.tests.test_guest_catalog -q`（114 项通过）。真实 5173 / Chrome 1920px 宽桌面、DPR 1 的浅暗主题中，5 张可见图片全部载入，选中项唯一；游客点导演台 / 画布 / 资产仍打开登录弹窗，关闭后保留生成页，任务栏可收起 / 展开，键盘焦点可见。截图与真实 DOM 元数据在 `design-ref-generation/navigation-brand-20261031/implementation/`；导演台共用壳局部基线在 `design-ref-director/navigation-brand-20261031/`。未登录的受保护内容页未额外截图，未提交真实生成任务。
- 回滚：仅撤回上述四份源码内本次图片引用、品牌尺寸和导航样式增量，删除本次 `studio-icons` 静态素材后运行 `pnpm --dir frontend build`；保留同期已有改动及任务 / 媒体，无后端与数据库回滚。

## 2026-10-31 默认主题改为暗色

- 原因：用户要求把默认主题颜色改为暗色风格；此前首次访问、偏好缺失或存储异常时统一回退浅色。
- 当前基线：`frontend/src/theme.ts` 的 `resolveThemeMode()`、`ThemeProvider.tsx` 的 `readStoredTheme()` 异常分支与 `index.html` 首帧引导脚本均以 `dark` 为默认；`<meta name="theme-color">` 初始值为 `#0f1115`，引导脚本只把显式保存的 `light` 视为浅色。显式保存的 `light` / `dark` 仍按原值恢复；`data-theme`、`color-scheme`、Ant Design `defaultAlgorithm` / `darkAlgorithm` 与 `--studio-*` 变量层不变。
- 受影响文件：`frontend/index.html`、`frontend/src/theme.ts`、`ThemeProvider.tsx`、`theme.test.ts`；`AGENTS.md`、`frontend/PRODUCT.md`、`frontend/DESIGN.md`、`README.md`、`功能说明与扩展指南.md` 与本文件。
- 兼容性：不改 HTTP API、SQLite、任务/Recipe schema、工作流注册表、ComfyUI graph、节点 ID、模型路径、媒体目录或 7865/8188 端口；无数据迁移。仅影响未保存主题偏好的浏览器，已保存偏好保持不变。
- 验证命令：`pnpm --dir frontend test`、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build`。
- 回滚方式：把上述三处默认值恢复为 `light`、恢复 `theme-color` 初始值为 `#f8f9fa` 后重新构建前端；无需迁移或回滚数据库、任务、Recipe、媒体与 ComfyUI 资产。

## 2026-10-31 游客生成首页与按需登录弹窗

- 原因：按用户确认的 `docs/design-ref-auth/login-20261031/zly-login-modal-v002.png`，由独立登录页改为先浏览创作首页、在受保护操作时登录。
- 当前行为：未登录可浏览 `/generate/video`、`/generate/image`，填写提示词、选择工作流/创作参数、在本机选择参考图并使用公开灵感示例。提交生成/立即润色、进入导演台/画布/资产或查看个人记录时打开统一的 Ant Design 账号密码弹窗；关闭按钮、Esc 或遮罩返回原页。登录后保留图/视频草稿、参考图和参数，按原入口返回；生成需要再点击提交，不在登录成功后自动产生任务。登出清理查询缓存并返回游客生成页。
- 路由与状态：`paths.ts` 增加游客路径白名单，Root 保留初始化、强制改密和管理员角色闸门；深链私有页面仍经 `/login` 携带完整 pathname/search/hash。`router.tsx` 让 `/login` 和生成页共用 App 实例，并管理弹窗目标。App 接受空 user；私有查询由登录状态启用，游客不读取任务、余额、用户列表、LLM 或超分状态；会话过期清理私有弹层和查询。工作流参数按同一工作流 ID 合并默认值，避免登录切换丢失已选值。
- API：`GET /api/modes` 允许匿名只读，数据仍来自 `workflow_registry.py`。游客只返回声明为 primary/advanced 的创作参数，不返回 internal 控件、director_controls 或供应商可用性原因；登录后返回原完整注册表。`GET /api/modes/{id}`、任务/素材/管理接口和所有写操作继续依赖原登录、权限和 CSRF 校验。无新路由、表、节点、模型路径、端口或供应商切换。
- 视觉与素材：登录弹窗使用独立电影画面、可编辑 DOM 文案和直接接线的 Ant Design Modal/Form/Input；根 Provider 驱动浅暗主题，薄荷青仅用于弹窗主操作。`frontend/public/auth/` 的主视觉为官方 OpenAI Images API 从已确认设计重建的独立素材，四张示例是既有生成首页设计图的干净裁图，均为公开演示素材，不读取真实用户作品。原图、提示词、哈希及用量见 `docs/design-ref-auth/login-20261031/generation.artwork.v001.json`。
- 受影响文件：`frontend/src/{Root.tsx,router.tsx,paths.ts,paths.test.ts,App.tsx}`、`auth/{LoginModal.tsx,login-modal.css}`、`components/{StudioHeader.tsx,studio-header.css}`、`generation/{GenerationHomeSections.tsx,GuestInspiration.tsx,generation-home.css}`、`frontend/public/auth/`；`backend/app/{main.py,workflow_registry.py}`、`backend/tests/test_guest_catalog.py`、`.gitignore` 与三份主文档、前端设计规范。
- 兼容性：已登录工作台、首次管理员初始化、必须改密、OAuth/MCP 返回地址及员工管理权限保留；旧 `/login` 收藏变为生成页上的登录弹窗。API `/api/modes` 原登录响应不变，匿名响应只用于创作预览，不能提交。无数据迁移或新增依赖。
- 验证：`pnpm --dir frontend build`（76 个文件 / 558 项前端测试、TypeScript 与 Vite 通过）；`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_accounts backend.tests.test_guest_catalog backend.tests.test_job_list_payload -q`（118 项通过）。真实 5173 桌面浅暗主题验证游客页、生成触发、个人入口、关闭/Esc、必填校验、媒体草稿切换；通过浏览器已有自动填充完成真实登录，草稿保留、弹窗关闭，资产入口登录成功后返回 `/assets`，登出恢复游客页。未提交真实生成或提示词润色，未修改账号配置、任务或媒体；验证登录仅产生正常会话和审计记录。
- 回滚：只撤销上述文件中本次游客/登录弹窗增量，将 `/api/modes` 恢复 current_user 依赖，恢复原登录路由与跳转后运行 `pnpm --dir frontend build`；保留工作区原有改动与全部任务/媒体，无数据库或 ComfyUI 回滚。


## 2026-10-31 成片七牛上传改用分片续传并支持重试

- 日期与原因：2026-10-31。整集任务 `job-e78ee09cf607` 的四段渲染全部成功，但 ~16.3 MiB 合片在 `_publish_timeline_result` 上传七牛时连续两次失败：`HTTPConnectionPool(host='up-z0.qiniup.com', port=80): Read timed out. (read timeout=30)`。`QiniuService.store_bytes` 使用 `qiniu.put_data` 把整段成片作为一次表单请求发送，七牛 SDK 7.16.0 无逐调用超时参数，固定使用 30 秒 `connection_timeout`；成片经代理链路上传时容易在等待响应阶段超时。仓库内的 `backend/app/qiniu_storage.py` 已有「超过 8 MiB 分片续传 + 传输错误重试」，媒体服务此前未复用。
- 当前基线：`QiniuService.store_bytes` 按内容大小分流：超过 8 MiB 时优先调用 `qiniu.put_stream_v2`，SDK 无该入口（当前运行时 7.16.0）时回退 `qiniu.put_stream(..., version="v2")`，均传 `part_size=4 MiB`、`bucket_name` 与 HTTPS `regions`；≤8 MiB 仍走 `put_data`。整条上传最多尝试 3 次、按 0.5·2^n 秒退避，仅对可重试的传输错误重试（status -1/0/408/429/5xx、`ConnectionError`/`OSError`/`TimeoutError`、`RemoteDisconnected`/`Connection aborted`/`reset`/`Broken pipe`/`timed out`），4xx 等确定性错误立即抛错并保留七牛错误文本。对象 key 每次调用随机生成，重试不会覆盖已有对象。
- 兼容性：不新增 API 路由、数据库表 / 列、任务队列、ComfyUI 节点、工作流 graph、权限或依赖；调用方签名 `store_bytes(prefix, source_filename, content) -> (key, url)` 不变，图片、配音、智能剪辑等小文件上传行为与对象路径规则保持一致。仅影响七牛上传路径，不改变合片、任务状态机与失败重试语义。
- 受影响文件：`backend/app/media_studio/services/qiniu_service.py`、`backend/tests/test_qiniu_upload.py`；`docs/ARCHITECTURE.md`、`README.md`、`功能说明与扩展指南.md`。`docs/API.md` 与 `docs/导演台流程与界面结构.md` 无契约或界面变化。
- 验证命令：`python -m pytest backend/tests/test_qiniu_upload.py -q`（7 项通过：>8 MiB 走分片、无 `put_stream_v2` 时以 `version="v2"` 回退、小文件仍 `put_data`、临时错误重试后成功、超时异常重试至上限、4xx 不重试、重试分类）；集成运行时 Python 3.10 + qiniu 7.16.0 以 `unittest` 复跑同样 7 项通过。通过 5173 页面「重试」复用四个已成功分片（`segment-1_00002_.mp4`…`segment-4_00001_.mp4`，远端 ComfyUI 队列保持空），任务于 00:57:19 进入合成、00:58:00 完成，成片地址 `https://img.zlyun168.com/zly-ai-video-studio/video/20261031/005717_480e93bcd4c3b0c6.mp4` 返回 200、`Content-Length: 17046318`，浏览器预览 864×480、139.03 秒、`readyState=4` 无错误。
- 回滚方式：删除 `_upload` 的大小分流与 `UPLOAD_ATTEMPTS` 重试循环，恢复 `store_bytes` 直接调用 `qiniu.put_data` 的单次上传；不涉及数据库、任务队列或 ComfyUI，已上传对象保持原样。

## 2026-10-31 画布左侧导航并入全局共用图标栏

- 日期与原因：用户反馈左侧菜单不是公用的，进入画布后变成另一套。排查确认画布首页 `canvas-home.css` 把图标栏改为 92px / 76×80 / 18px 圆角并追加底部管理设置按钮，画布编辑器 `canvas-fidelity.css` 又改为 86px / 72×76 / 9px 圆角，且「画布」项在首页、编辑器与其他工作区分别使用 `Network`、九点标记与 `Frame` 三种图标；生成 / 资产 / 导演台则保持 `index.css` 的 76px、52×50 图标项。
- 当前基线：删除画布两套私有图标栏覆盖、首页专属设置按钮与九点图标分支；`App.tsx` 的桌面图标栏在所有工作区统一渲染 Sparkles / Clapperboard / Frame / FolderOpen 四项，宽度、字号、圆角与选中态全部回到 `index.css` 的 `.studio-icon-rail` / `.studio-global-nav-item`。画布首页沿用 76px 宽度，用 `@media (min-width: 1280px)` 的 37px 左内边距保持 1586px 基线 x=113 的内容起点；画布编辑器工具轨仍位于画布内 `left: 22px`，与导航保持 22px 间距。管理设置继续从页头账号菜单进入。
- 兼容性：只改前端壳层标记与样式，不改路由、API、数据库、任务队列、工作流、ComfyUI、权限或依赖；`studio-canvas-shell` / `studio-canvas-home-shell` 主题变量、画布工具轨、底栏与属性面板不变。窄于 1280px 时图标栏本就隐藏，首页不再保留无导航时的 92px 空白。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/canvas/canvas-home.css`、`frontend/src/canvas/canvas-fidelity.css`；`README.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`frontend/DESIGN.md`、`docs/design-ref-canvas/{DESIGN.md,FIDELITY.md}`、`docs/design-ref-canvas/home-exhibition-20261028/DESIGN.md`。
- 验证命令：`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend test`（76 个文件 / 554 项通过）；`pnpm --dir frontend build`（clean-dist、TypeScript 与 Vite 通过）。5173 桌面 1920×1080 浅暗主题检查生成页、画布首页与画布编辑器：图标栏 76px、图标项 52×50、11px 字号、8px 圆角与选中态一致；画布编辑器工具轨位于导航右侧 22px；画布首页内容保持设计起点。未改后端、未提交生成任务、未做移动端检查。
- 回滚方式：撤回 `App.tsx` 的图标分支与设置按钮删除，恢复 `canvas-home.css` / `canvas-fidelity.css` 的图标栏覆盖后重新构建；无需数据或 ComfyUI 回滚。

## 2026-10-30 本地开发热重载在视频任务进行中延迟重启

- 日期与原因：用户的一键生成整集任务在 2026-10-30 22:31 被后端热重载重启打断。`backend/dev_reloader.py` 只监视 `backend/app` 的 `.py` 变更并立即 `taskkill /F /T`，而启动恢复逻辑会把所有进行中的视频任务标为失败，远端 ComfyUI 已完成的分段也因任务失败而无法复用。用户要求「出片期间暂停热重载」，任务结束后再应用代码改动。
- 当前基线：监督器收到源码变更后先经过防抖，再调用 `count_active_video_jobs()` 查询 MySQL `ai_project_jobs` 中 `job_type='video_generation'` 且状态属于 `episode_video_service._ACTIVE_VIDEO_STATUSES` 的任务数（状态表从服务模块直接导入，不另维护副本）。存在进行中任务时每 5 秒复查、每 30 秒输出一次等待日志；任务清零后打印「no active video jobs left; applying deferred restart」并重启。等待期间子进程自行退出、数据库不可达或停止信号到达时立即放行（数据库异常按无法确认处理，宁可重启也不永久卡住）。Ctrl+C / 关闭窗口仍立即终止，不受保护逻辑影响。
- 兼容性：不新增 API 路由、数据库表 / 列、任务队列、ComfyUI 节点、工作流 graph、权限或依赖；只在本机 Windows 开发监督器生效，Docker / 生产直接运行 uvicorn 不受影响。视频任务本身的启动恢复逻辑不变，仅在监督器不再于任务进行中触发重启。
- 受影响文件：`backend/dev_reloader.py`、`backend/tests/test_dev_reloader.py`；`docs/ARCHITECTURE.md`、`README.md`、`功能说明与扩展指南.md`。`docs/API.md` 与 `docs/导演台流程与界面结构.md` 无契约或界面变化。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_dev_reloader -q`（12 项通过，新增 5 项：有活跃任务时等待到清零、无任务立即放行、数据库不可达时放行、等待中子进程退出立即放行、停止时不复查）；`python -c "from backend.dev_reloader import count_active_video_jobs; print(count_active_video_jobs())"` 对真实库返回 `0`。按用户确认重启监督器后，失败任务 `job-e78ee09cf607` 已通过「重试」整集重跑，进行中任务可被保护逻辑识别。
- 回滚方式：删除 `_wait_for_active_video_jobs` 的调用与 `count_active_video_jobs()`，恢复 `_wait_until_restart` 中变更后立即 `taskkill` 的旧分支；不涉及数据库与任务队列。

## 2026-10-30 程序装箱提示词改用真实镜头内容并去除模板冲突

- 日期与原因：用户要求先优化程序装箱。旧程序稿把 `visual_prompt` 当作画面正文，而该字段常只有一句短描述；为满足 280 英文词厚度校验，`render_ref2va` 反复插入 `_THICKNESS_PAD` 占位句，真实动作被淹没。同时 `_camera_for_speech_event` 会为每句台词注入 `The camera holds a static shot.` / `The camera pushes in a fraction on the closed mouth.` 等通用镜头句，与镜头真实运镜（如「低角度仰拍…摇到…」）互相矛盾；画面比例取自脚本里残留的「成片 9:16」而不是任务实际画幅；无对白镜头也会追加「After the last syllable…freezes」。
- 后端行为：`H3PromptBuilder` 新增 `program_visual_draft`，在 `action` / `video_prompt_zh` / `visual_prompt` 中按中英文信息量取最丰富的一条，剥离「运镜：」「声音：」分节与「成片 N:N」画幅注记，并去掉台词回显；`program_camera_text` 读取镜头真实运镜，`_program_align_framing` 按任务画幅把「纵向构图 / 横向构图」改写成一致方向。`assemble_shot_body` 新增 `explicit_camera` 与 `program` 开关：存在真实运镜时停用 coverage plan 的模板镜头落点（`CLAUSE_TILT_UP` / `CLAUSE_INNER_HOLD` / `CLAUSE_PUSH_IN` / 静态抱镜与 `_GAP_CAMERA_BEATS`），并跳过无对白镜头的默认 freeze 句；`render_ref2va(program=True, aspect_ratio=…)` 把真实运镜作为 `Camera movement:` 前置、补 `Lighting follows the scene's practical light sources.`，`build_prompts` 不再灌 `_THICKNESS_PAD`。`validate_prompts(program=True)` 只保留参考权威校验，不再要求 LLM 模板专用的 tilt-up / inner-hold / push-in 落点，但仍校验六段顺序、逐字台词、说话人 ID、参考标签与 camera/lighting/sound 术语。
- 兼容性：不新增 API 路由、数据库表 / 列、任务队列、ComfyUI 节点、工作流 graph、权限或依赖；`prompt_mode` 默认值与出片门禁不变。程序预览仍是免费、不调用大模型的路径，不写入镜头 `h3_prompt`；命名技能包、手动提示词与已保存成片不受影响。`render_ref2va` 的默认 `program=False` 保持原 LLM 骨架行为，`validate_prompts` 默认仍按 280 词与完整 coverage 规则校验。
- 受影响文件：`backend/app/media_studio/services/h3_prompt_builder.py`、`backend/app/media_studio/services/episode_video_service.py`、`backend/tests/media_studio_test_h3_video.py`；`docs/ARCHITECTURE.md`、`README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md`。`docs/API.md` 无接口契约变化。
- 验证命令：`python -X utf8 -m unittest backend.tests.media_studio_test_h3_video -q`（151 项通过，新增 5 项程序装箱质量用例：真实动作、无灌水句、任务画幅 16:9 与构图词一致、真实运镜替代通用镜头句、无对白不加 freeze、多说话人分行贴标）；`python -X utf8 -m unittest backend.tests.test_h3_coverage backend.tests.test_skill_packs -q`（65 项通过）；`pnpm --dir frontend test`（76 个文件 / 554 项通过）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build` 通过。用真实分集 `ep-69ceea34ea18`（11 镜）在 16:9 下重建程序稿：11 镜 `_THICKNESS_PAD` 均为 0，正文为完整动作描述，镜头 2 / 11 的两句对白各自贴 `(S1)` / `(S2)` 与独立 `<d>`，无通用静态抱镜句，画幅写 `16:9`。未提交付费出片、未调用 GPU，未做移动端检查。
- 回滚方式：撤回 `program_visual_draft` / `program_camera_text` / `_program_align_framing`、`assemble_shot_body` 的 `explicit_camera` 与 `program` 分支、`render_ref2va` 的 program 渲染与 `build_prompts` 的 `program=True` 校验参数后即可恢复旧程序稿；不涉及数据库、任务队列或 ComfyUI，已保存提示词与已提交任务保持原状。

## 2026-10-30 程序装箱预览提示词在提交时落盘并在素材组可见

- 日期与原因：用户点「一键生成视频」并选择「仅本次程序装箱预览」后，剧集工坊素材组仍看不到提示词。排查确认程序装箱稿原先只在后台 worker 开始执行后才写入任务 `payload.shots`，且任务列表的 slim payload 会剥掉 `shots[].prompt`，素材组也只读取镜头的 `h3_prompt`，而程序预览按设计不写回镜头，三处叠加导致用户在提交后无从查看本次实际使用的提示词。
- 后端行为：`EpisodeVideoService.create_job` 在 `prompt_mode == "program"` 时于插入任务前同步调用 `H3PromptBuilder.build_prompts(shots)`，把每镜提示词并入 `payload.shots` 后再入库，并写入 `prompt_source=program_preview` 与 `prompt_warning`；`_run_job` 仍按同一确定性模板重建，worker 启动不再影响可见性。`job_payload.py` 把 `prompt_warning` 加入 `_JOB_LIST_KEYS`；`_slim_shots` 新增 `include_prompt`，仅当 `prompt_source == "program_preview"` 时在列表瘦 payload 中保留 `sequence` 与 `prompt`，H3 正式稿与命名技能包任务的列表载荷仍不含提示词。
- 工坊界面：新增 `frontend/src/director2/workshop-program-prompt.ts`，从 `listJobs` 中取当前分集最新的 `program_preview` 任务及各镜提示词；`EpisodeWorkshopPane.tsx` 轮询任务时同步更新（内容相同不重渲染），素材组在镜头无已保存 H3 稿时只读展示该镜提示词，状态芯片显示「程序装箱预览」，顶部说明为「以下是最近一次程序装箱预览的提示词（任务 …），未保存到镜头。如需长期复用，请生成 H3 提示词，或点「编辑」后保存。」；点「编辑」以预览稿为草稿进入编辑，保存后仍写回镜头 `h3_prompt`。全部任务详情对 `program_preview` 任务显示「本次任务使用程序装箱预览，提示词未保存到镜头」。
- 兼容性：不新增 API 路由、数据库表 / 列、任务队列、ComfyUI 节点、工作流 graph、权限或依赖；不改变 `prompt_mode` 默认值与出片门禁。仅 `program_preview` 任务的列表 payload 增加提示词文本，其他任务类型载荷不变；已提交的程序预览任务在接口层即可回读提示词，无需迁移。程序预览仍不写入镜头 `h3_prompt`。
- 受影响文件：`backend/app/media_studio/services/{episode_video_service,job_payload}.py`、`backend/tests/media_studio_test_h3_video.py`；`frontend/src/director2/workshop-program-prompt.ts`、`workshop-program-prompt.test.ts`、`panes/{EpisodeWorkshopPane.tsx,JobsCenterPane.tsx}`、`panes/episode-workshop.css`；`docs/API.md`、`README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。
- 验证命令：`python -X utf8 -m unittest backend.tests.media_studio_test_h3_video.EpisodeVideoPromptModeTests -q`（7 项通过，含提交时落盘、列表保留程序预览提示词、不泄露已保存 H3 稿）；`pnpm --dir frontend test`（76 个文件 / 554 项通过）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build` 通过。5173 桌面端在工程 `proj-4185149f8672474d` 第 1 集实测：素材组 Tab 显示「程序装箱预览」芯片与上述说明，读取既有任务 `job-3402b9b1979e` 的 11 镜提示词；镜头 1 为李明、镜头 2 切换为王主管，内容随选中镜头变化。未提交新的出片、未调用大模型或 GPU，未做移动端检查。
- 回滚方式：撤回 `create_job` 的提交时程序装箱、`job_payload` 的 `prompt_warning` 与 `include_prompt` 分支、前端 `workshop-program-prompt.ts` 及其素材组 / 全部任务展示后重新构建前端；已入库任务的 `payload.shots[].prompt` 保持原样，不涉及数据库结构与 ComfyUI。

## 2026-10-30 默认配方改为 H3 官方六段式大模型装箱（程序装箱降为预览）

- 日期与原因：用户指出最近一次整集直出在剧集工坊看不到 H3 提示词，成片里大量画面描述被当成对白讲出来。排查确认未绑定技能包时链路走的是确定性程序装箱（`render_ref2va` + `prepare_generated_prompt`），提示词不经过 H3 官方 Skill，且过薄稿会被 `_repair_thickness_terms` 用固定句子灌水。用户要求把默认装箱改成 H3 官方六段式 Skill，并确认按此方案修改。
- 默认配方：`skill_packs/recipe.py` 的 `default_recipe()`（空 `id`）改名「H3 官方六段式」，摘要为「不绑定 Plaza 制作配方，直接按 H3 官方六段式 Skill 用大模型装箱。」；`workshop_shot` 清空，不再执行 `render_ref2va_default`；`packing_overrides.skip_program_pack=True`。命名技能包（如半解说真人短剧）仍按各自 `packing_overrides` 与 `workshop_shot` 执行，行为不变。
- 写稿路径：`LlmService._h3_system_prompt` 在未显式传入 overrides 时始终解析 `packing_overrides_of(skill_pack_id or "")`，未绑定配方因此拿到默认 six-section 合同。`generate_h3_prompt` 的 Ref2VA 未绑定分支不再调用 `run_workshop_prompt` 或 `render_ref2va`：先把 `timestamped_zh_prompt` / `video_prompt_zh` 并入 `visual_prompt`，用官方装箱 system + `build_packing_user_prompt` 请求大模型，`prepare_generated_prompt(..., pad_thickness=False)` 规范化，`_validate_h3_prompt` 校验六段标题、逐字台词、`<Picture n>` / `<Subject n>`；失败时用 `packing_retry_block` 重写一次，仍失败则 `h3_prompt` 任务 `failed` 并返回真实校验原因，不再骨架填空或静默降级。命名配方的写稿与 `skip_program_pack` 分支保持原样。
- 校验与灌水：`prepare_generated_prompt` 新增关键字 `pad_thickness`（默认 `True`）；未绑定官方路径与 `_finalize_prompt` 的空 `skill_pack_id` 分支传 `False`，不再注入 `_THICKNESS_PAD` 填充句。`_validate_h3_prompt` 的 `skip_program_pack` 放宽项（280 英文词、`[Shot 1]` 等）只在 `beat_info.skill_pack_id` 非空时生效：未绑定默认改回严格六段校验，命名半解说包仍按既有放宽规则。
- 对白解析：`H3PromptBuilder._parse_script_turns` 先按已绑定角色名匹配「名字：内容」行，再用 `_SCRIPT_LABEL_RE` 兜底识别无引号多角色对白；识别到至少两个说话人时优先于引号解析，避免整段旁白被并入同一句。`script_parser.py` 的 `### 镜头` 标题正则接受制表符与普通空格，修复 `### 镜头	N` 这类缩进写法导致镜头标题被跳过。
- 出片门禁：`EpisodeVideoService.create_job` 读取 `options.prompt_mode`（缺省 `h3`，仅接受 `h3` / `program`），写入 `payload.prompt_mode`。`h3` 模式在入队前调用 `_assert_h3_prompts_ready`，对缺少合格提示词的镜头抛 `ValueError`，接口返回 400 并列出 Beat 序号，提示先到工坊生成提示词或开启「程序装箱预览」；`_run_job` 中 `program` 才调用 `H3PromptBuilder.build_prompts` 并把 `prompt_source` 标为 `program_preview`、附 `prompt_warning`，`h3` 模式只使用工坊已保存提示词；保存稿过薄或校验不过时按缺失处理，不再回退程序装箱。大模型装箱只发生在 `h3_prompt` 任务中，不占用视频任务的 GPU 锁。
- 工坊界面：`workshop-h3-gate.ts` 新增 `beatsMissingH3Prompt`。`EpisodeWorkshopPane.tsx` 在单镜 / 选中镜 / 整集「一键生成视频」前调用 `decideVideoPromptMode`：未开程序预览且存在缺稿镜头时弹出「还有镜头缺少 H3 提示词」，列出前 8 个镜头与「…等 N 个镜头」，三个操作为「取消」「仅本次程序装箱预览」「先去生成提示词」（选中首个缺稿镜并切到素材 Tab）。`Director2VideoSettingsPopover.tsx` 顶部提示根据程序预览开关与缺稿数量显示对应说明，并在「更多设置」提供 Ant Design `Switch`「程序装箱预览」。`director2-video-settings.ts` 新增 `withVideoPromptMode` 与按工程持久化的 `loadProgramPreview` / `saveProgramPreview`（默认关闭）。
- 智能助手：`episode-shot-tasks.ts` 新增 `ensureEpisodeShotPrompts`，在 `submitEpisodeShotTasks` 前对缺少 `h3_prompt` 的镜头调用既有 `POST …/beats/{beat_id}/h3-prompt`，轮询 `listJobs` 直到完成，跳过已有提示词与本次失败镜头；失败清单写明 Beat 序号与错误，`WorkflowProgressCard.tsx` 在提示词准备阶段显示进度与失败态，只有全部就绪才提交逐镜视频任务。`episode-shoot.ts` 的 `episodeShootOptions` 固定带 `prompt_mode: "h3"`。
- 兼容性：不新增 API 路由、数据库表 / 列、任务队列、ComfyUI 节点、工作流 graph、权限或依赖。`prompt_mode` 为可选字段，旧客户端缺省按 `h3`；命名技能包、手动粘贴六段、已保存成片与既有任务不受影响。已经按程序装箱生成并保存的旧提示词仍可手动编辑或重新生成；程序装箱保留为免费、快速但不调用大模型的预览路径。旧工程无需迁移数据。
- 受影响文件：`backend/app/skill_packs/recipe.py`、`backend/app/media_studio/services/{llm_service,h3_prompt_builder,h3_prompt_job_service,episode_video_service,script_parser}.py`、`backend/tests/{media_studio_test_h3_video,test_skill_packs,test_standard_script_parser}.py`；`frontend/src/director2/{workshop-h3-gate.ts,workshop-h3-gate.test.ts,director2-video-settings.ts,director2-video-settings.test.ts}`、`frontend/src/director2/panes/{EpisodeWorkshopPane.tsx,Director2VideoSettingsPopover.tsx}`、`frontend/src/director2/assistant/{episode-shot-tasks.ts,episode-shot-tasks.test.ts,episode-shoot.ts,episode-shoot.test.ts,WorkflowProgressCard.tsx}`；`docs/API.md`、`README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。
- 验证命令：`python -X utf8 -m unittest backend.tests.media_studio_test_h3_video.H3PromptTests backend.tests.media_studio_test_h3_video.EpisodeVideoPromptModeTests backend.tests.test_skill_packs -q`（H3 写稿与出片门禁用例通过，含官方六段装箱、命名包不变、缺稿 400、program 预览、无引号对白解析）；`pnpm --dir frontend test`（75 个文件 / 549 项通过）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build` 通过。5173 桌面端在工程 `proj-4185149f8672474d` 第 1 集实测：配方标签「H3 官方六段式（默认）」、0/11 提示词，视频设置弹层显示缺稿提示，程序装箱预览开关可切换并持久化后恢复，提交整集时弹出 11 个缺稿镜头清单，取消后没有 `POST …/generate-video`，任务列表没有新增任务。未提交真实出片、未调用大模型或 GPU，未做移动端检查。
- 回滚方式：把 `default_recipe()` 恢复为「默认程序装箱」、`render_ref2va_default` 与空的 `PackingOverrides`，撤回 `llm_service` 的未绑定官方装箱分支、`h3_prompt_builder` 的 `pad_thickness` 与无引号对白解析、`script_parser` 的镜头正则、`episode_video_service` 的 `prompt_mode` 门禁与 `_run_job` 分支，撤回前端 `beatsMissingH3Prompt` / `withVideoPromptMode` / 程序预览开关 / 出片弹窗 / `ensureEpisodeShotPrompts` 接线后重新构建前端；不涉及数据库、任务队列或 ComfyUI，已保存提示词与已提交任务保持原状。

## 2026-10-30 智能助手补齐出片素材的执行器与生图稳定性

- 变更原因：用户在创作流程卡点击「补齐素材并出片」多次仍停在同一处。真实调用后确认补齐链路没有死循环，失败来自三处独立问题：角色设定板请求的 `clean_prompt` 已带 `TEXT-TO-IMAGE character production design sheet` 前缀，GRS 仍把长英文版式提示当成图片编辑请求，回复「目前没有可供编辑的原图，请上传参考图」，仅补前缀不足以解决；GRS 出图轮询上限 120 秒低于 2K 设定板实测耗时（约 170 秒）；场景主视图提示词含恐怖 / 血腥措辞被模型审核拒绝。前端补齐循环失败后只弹 toast，缺少常驻失败态，用户会重复点击。
- 当前基线：新增 `frontend/src/director2/assistant/episode-shoot-prep.ts` 作为纯执行器，按最多 3 轮「免费绑定 / 新建 → 生图 → 复检」补齐场景主视图与角色造型，同一轮最多 2 路并发，逐张回调 `{ phase, label, index, total }` 进度；任一张失败立即返回并保留已完成结果，复检通过后才由 `WorkflowProgressCard.tsx` 调用整集出片接口。卡片在补齐期间显示阶段、序号与已等待时间，按钮显示「补齐中 i/n」并锁定；失败后保留「上次补齐未完成」清单（最多 3 行，超出「…等 N 项」），再次点击只补齐缺失素材。
- 后端生图：`asset_image_prompts.py` 新增 `_text_only_identity_sheet_prompt`，在没有参考图锁定（无原片、无身份参考、无服装参考）时改用简短中文「纯文生图」指令，明确「没有任何输入图片、不需要参考图、不要索要参考图」，并保留三视图、六张头部细节、六张服装细节与白底无文字要求；有参考图时仍走原英文版式与 `REFERENCE 1` 身份锁定逻辑。`grs_client.py` 的 `GRS_POLL_MAX_WAIT` 由 120 秒提高到 240 秒；`asset_image_prompts.py` 新增 `safe_scene_master_prompt`，`project_detail_service.py` 的 `scene_master` 分支在拼接主视图提示词前移除血腥 / 尸体 / 恐怖等高风险子句并温和化，全部命中时回退为通用建立镜头描述。生图仍在请求内同步执行，前端 2 路并发对应 FastAPI 同步路由的线程池执行。
- 兼容性：不新增 API、数据库字段、任务队列、ComfyUI 节点、权限或依赖；不改变工作流注册表、任务协议与出片参数。提示词安全化只作用于 `scene_master`，角色 / 道具与参考图链路不变；已提交任务与已生成资产不受影响。补齐与出片仍复用既有 `createAsset` / `updateAsset` / `updateEpisodeBeat` / `POST /assets/{asset_id}/generate` / `POST /episodes/{episode_id}/generate-video`。
- 受影响文件：`backend/app/media_studio/services/asset_image_prompts.py`、`project_detail_service.py`、`grs_client.py`、`backend/tests/test_asset_source_references.py`；`frontend/src/director2/assistant/episode-shoot-prep.ts`、`episode-shoot-prep.test.ts`、`WorkflowProgressCard.tsx`、`assistant.css`；同步 `docs/导演台流程与界面结构.md`、`README.md` 与 `功能说明与扩展指南.md`。
- 验证命令：`python -X utf8 -m pytest backend/tests/test_asset_source_references.py -q`（22 项通过）；全量后端 1110 项通过，另有 3 项与本次改动无关的历史失败（`test_director` 大小写、`test_mcp_gateway` 工具数、`test_media_studio_schema` 夹具）。`pnpm --dir frontend test`（74 个测试文件 / 532 项通过，补齐执行器 6 项）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build` 通过。5173 桌面端以真实登录态调用既有补齐接口完成付费生图验收：第一轮场景主视图「诡异洗手间」成功，3 张角色造型因 GRS 索要参考图失败（job `0a5249e1` / `f9d7068e` / `e0fc3cd7`）；改用中文纯文生图提示词后第二轮 3 张设定板全部成功（job `39df4eed` 李明、`1c604dca` 王主管 13:41:53，`bfab332d` 老员工A 13:42:51，13:43:41 完成），预览图均为标准 16:9 设定板、白底、三视图 + 头部 / 服装细节完整。复检目标分集 `proj-4185149f8672474d` 第 1 集前置检查为 `ready: true`、`blocking: []`，5 张相关图片 HTTP 200 且为 `image/png`；MySQL `ai_project_jobs` 13:25 后仅有 4 条成功与 3 条失败的 `image_generation` 记录，出片提交前没有任何视频任务。验收另生成 1 张角色「林晓」提示词测试图（未写入项目）与 3 次失败请求，均未计入资产。用户确认后已提交第 1 集整集出片任务 `job-f192bd794c2a`（11 镜、3336 帧、138 秒、4 个分段，状态 running，首段已提交远端 ComfyUI），未等待成片完成。
- 回滚方式：恢复 `asset_image_prompts.py`、`project_detail_service.py`、`grs_client.py` 的对应改动，删除 `episode-shoot-prep.ts` / 测试并撤回卡片进度与失败态接线后重新构建；不涉及数据库、任务队列或 ComfyUI，已生成资产与已提交任务保持原状。

## 2026-10-29 无限画布连线与生成模式快捷弹层

- 变更原因：用户对照参考平台截图，要求复刻连线显示的「关闭 / 精简 / 完全」与生成节点展示方式的「独立 / 聚合」，并希望这些模式在画布内有更直观的入口。
- 当前基线：画布底栏新增「连线与生成模式」Popover（`Waypoints` 图标，位于视角入口左侧），分为「连线」与「生成节点展示方式」两组；每项包含图标、标题、说明与右侧选中对勾，点击立即写入画布设置并自动保存。属性面板的同类设置改为使用同一份选项元数据，标签统一为「连线」与「生成节点展示方式」，顺序与弹层一致（关闭/精简/完全、独立/聚合）。
- 精简焦点：`frontend/src/canvas/canvas-view-modes.ts` 的 `compactCanvasEdgeIds` 是纯函数，焦点集合包含选中节点、选中边、最近创建的边和当前悬停节点，并沿边迭代扩展上下游连通链；无任何焦点时不显示连线。`CanvasEditor` 通过 `onNodeMouseEnter` / `onNodeMouseLeave` 维护 `hoveredNodeId`，仅连接 `compact` 时参与计算。
- 关闭与完全：关闭沿用 `nodesConnectable={false}` 与 `.canvas-connections-off` 隐藏端口，`visibleEdges` 返回空数组，连线数据与设置仍保留；完全显示全部连线与端口。生成节点展示方式的「独立 / 聚合」行为不变，仅统一文案、顺序和入口。
- 兼容性：`canvasSettings.connectionMode` 仍为 `off | compact | full`，`generationDisplayMode` 仍为 `aggregate | independent`，默认值不变；`schemaVersion=2`，不改 API、数据库、任务队列、工作流注册表或 ComfyUI。
- 受影响文件：新增 `frontend/src/canvas/canvas-view-modes.ts`、`canvas-view-modes.test.ts`；修改 `frontend/src/canvas/CanvasEditor.tsx`、`CanvasSidePanel.tsx`、`canvas.css`；同步 `docs/无限画布开发计划.md`、`README.md`、`功能说明与扩展指南.md` 与本文件。
- 验证命令：`pnpm --dir frontend test`（69 个测试文件 / 484 项通过，其中画布 10 个文件 / 165 项）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build` 通过。5173 桌面端 1440×900 实测：底栏入口打开弹层，标题与 5 个选项说明和参考平台一致，完全/聚合默认选中；切到精简后无焦点时连线为 0，悬停生成节点显示其上下游链路（3 条），移出恢复 0；切到关闭时连线 0 条且端口 `opacity: 0`，切回完全恢复 5 条；浅色/暗色下弹层、图标与说明文字对比清晰，控制台无错误；验证后设置恢复为完全/聚合并已保存。
- 回滚方式：删除 `canvas-view-modes.ts` 与测试，撤回 `CanvasEditor.tsx` 的弹层、`hoveredNodeId` 与 `onNodeMouseEnter/Leave`、`CanvasSidePanel.tsx` 的元数据接入及 `canvas.css` 新增样式，恢复精简模式原有的内联计算与旧文案后重新构建；画布设置与草稿数据无需迁移。

## 2026-10-29 无限画布连线拖拽菜单与流光连线

- 变更原因：用户对照火龙平台指出画布连线交互差距：从节点拉出线后应按来源节点弹出可连接的下一个节点菜单并可直接创建；拖拽期间与菜单待选期间必须是虚线，只有真正建立连接后才变为实线；已连接线需要流光效果；不同节点类型应提供不同下游选项。首轮只按已有生成结果判断下游，导致尚未生成结果的图片生成节点拖出后没有菜单；随后按节点配置的图像 / 视频输出类型补齐，并按用户反馈取消「生成完成后可添加」的创建限制。
- 当前基线：新增 `frontend/src/canvas/canvas-connections.ts` 作为纯函数兼容层。文字节点只提供「生成节点」（连 `prompt`）；图片节点提供「生成节点」（连 `in` 参考图）；图片输出的生成节点提供「生成节点」（继承提示词/工作流并引用当前结果）与「图片节点」；视频输出的生成节点提供「视频节点」。所有下游项无论上游是否已有结果都可直接创建，不再禁用。生成节点按工作流媒体类型决定下游；缺少输出类型的旧生成节点不提供下游，加载模式列表后按 `workflowId` 补齐。画板、视频源不提供下游。菜单定位由 `canvasConnectMenuPosition` 夹取在画布内。
- 结果节点占位：上游尚无结果时，选择「图片节点 / 视频节点」会创建 `data.pendingGeneratorId` 指向来源生成节点的空媒体节点，标题为「等待生成」，画布内提示「等待上游生成完成，自动填入」。上游任务成功后 `canvasPendingResultFill` 生成填充补丁，`CanvasEditor` 在任务快照落地时写入结果地址、素材路径、`sourceJobId`、媒体类型与运行快照并清除占位标记；若独立展示模式已填入预留节点，则不再自动追加第二个结果节点。已有结果时仍直接带入结果与来源快照。
- 旧草稿兼容：模式列表加载后，缺少 `data.resultKind` 的生成节点按 `workflowId` 补齐工作流媒体类型（图片或视频），同时刷新节点数据缓存；补齐会进入正常自动保存。此前由旧数据创建的文生视频节点因此能显示视频下游与视频色输出端口。
- 交互：`CanvasEditor.tsx` 接入 `onConnectStart`/`onConnectEnd`，在空白画布释放且来源有候选时显示「添加节点」菜单；选择后创建目标节点、自动避让现有节点并建立边。菜单打开期间保留一条由 `getBezierPath` 计算的虚线预览路径与端点圆点（`ViewportPortal` 内 SVG）；`Escape`、点击空白、平移/缩放、切换工具都会关闭菜单。已有合法连线释放不弹菜单。
- 参考链：图片输出的生成节点即使还没有结果，也可作为下游生成节点的参考输入（`canvasReferenceEligible` 按输出类型判断）；提交时 `generatorReferenceIssue` 会指出「参考图没有可用地址」，上游完成后即可正常提交。
- 连线视觉：新增 `CanvasFlowEdge.tsx`，所有边在渲染层映射为 `canvasFlow`，底层保持实线并按来源节点类型着色（文字/图片/视频/生成），叠加 `pathLength=100` 的短虚线动画形成流光；拖拽连接线与菜单待选线使用虚线动画。`prefers-reduced-motion` 下停止动画并降低流光透明度。
- 兼容性：草稿仍保存 `type: "smoothstep"` 与既有 `buildEdgeId`，`schemaVersion=2` 不变；`pendingGeneratorId` 只是节点 `data` 中的可选字段，旧前端会当作普通空媒体节点显示并保留该字段。不改 API、数据库、任务队列、工作流注册表或 ComfyUI。
- 受影响文件：新增 `frontend/src/canvas/canvas-connections.ts`、`canvas-connections.test.ts`、`CanvasFlowEdge.tsx`；修改 `frontend/src/canvas/CanvasEditor.tsx`、`CanvasNodes.tsx`、`canvas-generation.ts`、`canvas-model.ts`、`canvas-generation.test.ts`、`canvas.css`；同步 `docs/无限画布开发计划.md`、`README.md`、`功能说明与扩展指南.md` 与本文件。
- 验证命令：`pnpm --dir frontend test`（68 个测试文件 / 476 项通过，其中画布 9 个文件 / 157 项、连线 12 项）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build` 通过。5173 桌面端 1440×900 实测：无结果图片生成节点拖出后「生成节点」与「图片节点」两项均可选，选择后创建「等待生成」占位节点、自动连线并出现流光；无结果视频生成节点菜单的「视频节点」可选；菜单与占位提示沿用既有菜单样式与 `--studio-*` token，未新增硬编码颜色；清理测试节点后通过「加载最新版本」恢复到测试前的 8 节点 / 2 连线，控制台无应用错误。自动填入路径由 `canvasPendingResultFill` 单元测试覆盖，本轮未触发真实出片。
- 回滚方式：删除 `canvas-connections.ts`、`CanvasFlowEdge.tsx` 及其测试，撤回 `CanvasEditor.tsx` 的 `edgeTypes`/`onConnectStart`/`onConnectEnd`/菜单/待选路径/输出类型补齐/占位填充接线、`CanvasNodes.tsx` 的等待提示与 `canvas.css` 新增样式，并将 `canvasReferenceEligible` 恢复为要求已有可用地址后重新构建。已保存的边仍是 `smoothstep`，`resultKind` 与 `pendingGeneratorId` 为向后兼容的节点数据，无需数据迁移或后端回滚。

## 2026-10-29 智能助手资源弹窗选中修复

- 变更原因：用户反馈在智能助手输入框的 Skill 弹窗中点击资源后无法选中（chip 不变化）。排查确认两处独立问题：Skill / 专家 Popover 的 `content` 由 `picker` 状态派生，点击打开时该次渲染传入 `null`，弹层不会挂载，即使随后状态变为非空也不再出现，表现为点击无反应；旧选择逻辑要等 `PATCH /sessions/{id}` 成功后才更新 chip，而该接口携带会话 `version`，服务端版本被其它流程推进时返回 409，界面只报错或保持原样。
- 当前基线：`DirectorAssistant.tsx` 的 Skill / 专家 Popover 使用受控 `open` 与 `destroyOnHidden`，`content` 始终传入 `ResourcePicker`；点击资源行后立即乐观更新 `selections`、关闭弹窗，再在后台保存会话。已选项在列表中显示 Check 与选中底色。
- 保存与冲突：`select()` 先记录前值并立即更新本地选择；无会话时只更新本地。`PATCH` 返回 409 时重新 `GET` 会话取得最新 `version` 后重试一次；仍失败才回滚前值、提示「选择保存失败」并重新加载当前会话。接口路径、CSRF、版本校验与 409 语义不变。
- 受影响文件：`frontend/src/director2/assistant/DirectorAssistant.tsx`（选择保存与 Popover 接线）；`ResourcePicker.tsx` 仅在行选中后关闭弹窗，行按钮、封面与搜索行为不变；无后端改动。
- 兼容性：不改 API 路径 / 请求体、数据库、权限、任务队列、工作流与 ComfyUI；旧会话按既有 `selections` 回显。乐观更新只在选中请求期间生效，失败会回滚，未保存的选择不会写入会话。
- 验证命令：`pnpm --dir frontend test`（67 个测试文件 / 462 项通过）、`pnpm --dir frontend build`（含 TypeScript、clean-dist 与 Vite，`✓ built in 7.74s`）。5173 管理员桌面端：在已加载会话（version 30）上把服务端版本推进到 31 后点击「资产提取」，chip 立即由「分镜设计」变为「资产提取」，自动重试成功，服务端版本 32 且 `skill_id` 已更新，无错误提示；再选回「分镜设计」版本 33。专家弹窗同样可打开并展示 17 条资源。应用内浏览器 `visibilityState=hidden` 会暂停离场动画导致残留 Popover，真实可见标签页不受影响；本轮无法截图，以 DOM 与接口状态为证。
- 回滚方式：撤回 Popover 的受控 `open` / `destroyOnHidden` 接线与 `select()` 的乐观更新、409 重试（恢复为保存成功后再更新选择），重新构建前端；后端、数据与会话无需回滚。

## 2026-10-29 智能助手资源市场改版：封面卡片与我的侧栏

- 变更原因：用户指出智能助手的 Skill / 专家市场缺少封面图（包括输入框上打开的 Skill / 专家弹窗），整体不如火龙平台美观，要求参考火龙平台重新设计。
- 当前基线：`ResourceMarket.tsx` 改为 1280px 弹层，头部「专家 / Skill」Tabs + 数量与关闭，分类 Tabs 右侧内嵌搜索框与来源 Select（全部来源 / 平台资源 / 我的收藏 / 个人资源）；主体为自适应卡片网格（`repeat(auto-fill,minmax(196px,1fr))`）+ 288px「我的」侧栏。卡片使用 16:10 封面、来源标签、收藏星标、分类与版本、更多操作（导出 / 复制为个人资源 / 编辑）与删除（仅 `manageable`），底部按钮在已选时显示「使用中」。侧栏按「已选 → 收藏 → 个人 → 内置 → 平台」排序去重展示前 8 条，并提供新建 / 导入。
- 选中态修正：此前市场只接收一个 `selectedVersionId`，在弹层内切换专家 / Skill 页签后仍用打开时的页签值，导致另一个页签的「使用中」和侧栏选中丢失。现改为传入 `selectedVersions: Record<ResourceKind, string | null | undefined>`，在组件内按当前 `kind` 取值，两个页签各自正确高亮。
- 封面策略：`frontend/public/assistant-covers/` 新增 11 张分类封面（`script / planning / storyboard / assets / prompt / workflow / review / editing / shortvideo / director / default`，均 1000×600 WebP，合计约 565 KB）。`resource-market.ts` 的 `resourceCover(category)` 负责分类映射与 `default` 回退；卡片在封面上叠加资源名、来源标签与收藏按钮，避免为 42 个资源逐一生成图片。卡片封面 `loading="lazy"`，弹窗和欢迎区缩略图 `loading="eager"`。
- 视觉：`.assistant-market` 纳入 `--director-*` token 作用域（浅色 / `:root[data-theme="dark"]` 成对），主按钮沿用墨色 ink / surface 反色，来源标签为内置灰、平台蓝、个人橙；Ant Design v6 弹层内部类名使用 `.ant-popover-container`、`.ant-modal-container`。
- 受影响文件：`frontend/src/director2/assistant/ResourceMarket.tsx`、`DirectorAssistant.tsx`、`ResourcePicker.tsx`、`ResourceCover.tsx`（新增）、`resource-market.ts`（新增）、`resource-market.test.ts`（新增 8 项）、`assistant.css`、`api.ts`、`frontend/public/assistant-covers/`；README、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。
- 兼容性：不改 API 路径 / 请求体、数据库表列、权限判断、任务队列、工作流、ComfyUI 节点与模型路径；不新增依赖。资源市场筛选、收藏、选用仍走既有接口；封面为前端静态资源，旧资源无需迁移，新增分类时补一张同名 WebP 即可。
- 验证命令：`pnpm --dir frontend build`（67 个测试文件 / 462 项通过，含 TypeScript、clean-dist 与 Vite 构建）；`python -X utf8 -m unittest backend.tests.test_director_assistant -q`（78 项通过，后端未改动）；`resource-market.test.ts` 覆盖来源优先级、封面映射与回退、分类 / 来源 / 搜索过滤、快捷列表排序去重。5173 管理员桌面端实测：市场宽 797px、高 682px，结果区 509px + 侧栏 288px，卡片 223×261、封面 221×138（16:10）；专家 17 张、Skill 25 张、Picker 25 行 25 张封面全部加载、欢迎区 6 张封面；来源筛选专家 17 → 平台 14 → 收藏 0 → 恢复 17，搜索「分镜」命中 6 条；收藏后「我的收藏」1 条、取消后 0 条；选用后市场关闭且输入框显示「剧本策划专家」，两个页签的「使用中」与侧栏选中均正确。受应用内浏览器 `visibilityState=hidden` 限制无法截图，本轮以 DOM 尺寸和计算样式证据为准，未做移动端检查。
- 回滚方式：撤回 `ResourceMarket.tsx` / `DirectorAssistant.tsx` 的布局与 `selectedVersions` 接线，删除 `ResourceCover.tsx`、`ResourcePicker.tsx`、`resource-market.ts` 及其测试与 `frontend/public/assistant-covers/` 后重新构建；后端、数据与既有资源不受影响，无需数据库或 ComfyUI 回滚。

## 2026-10-29 无限画布首页创作展板与节点预览

- 日期与原因：2026-10-29 完成。用户确认 2026-10-28 的浅暗设计稿后，要求将 `/canvas` 首页按稿还原，强化最近创作、新建入口和画布库的视觉层级。
- 当前基线：`CanvasWorkspace.tsx` 的列表视图采用标题、最近保存画布 / 新建入口、四列「我的画布」三层结构。最近画布从当前账号可见的非回收站项目中按草稿保存时间选取，不受收藏置顶、搜索或排序影响。全部 / 已收藏 / 回收站继续使用真实查询与管理接口，次要操作改为 Ant Design Dropdown，删除仍有确认；标签 Select 选中后自动收起，避免候选层遮挡保存按钮。
- 前端状态：沿用 `["canvas-projects", false/true]` 查询键。活动项目查询提供最近项目及全部计数，回收站查询仅在相应视图启用；不新增轮询、浏览器存储键或后端接口。搜索、标签和排序为组件内存状态；新建后继续进入原编辑器。`App.tsx` 的 `studio-canvas-home-shell` 只标记列表路由，复用当前共用 StudioHeader / 根级主题 Provider，首页尺寸覆盖不进入编辑器。
- 缩略图：`CanvasPreviewThumbnail.tsx` 改为带节点标题、摘要、媒体、端口和曲线连接的 SVG。`canvas-home.ts` 以真实节点坐标缩放；普通预览至多聚焦 7 个非画板节点，大预览至多 10 个，优先实际媒体及相连邻居，不编造节点或重排原画布。缩略摘要有截取时标注「局部预览 · N 个节点」。缺少旧摘要、无视频封面和失效图片有明确回退。
- 预览协议：`canvas_store.py` 在既有 `preview_json.items` 中增加可选 `label`（48 字符）与 `text`（160 字符），仅从节点已有 `label`、文本 / 提示词 / 说明生成，归一化空白、忽略非法类型。仍保持 120 节点 / 80 连线 / 12 媒体地址、48 KB 总预算和既有视频封面约束；超预算先舍弃可选文字，再按原策略降级封面、媒体或结构。前端归一化器接受缺少新字段的历史摘要。
- 受影响文件：`frontend/src/App.tsx`；`frontend/src/canvas/{CanvasWorkspace,CanvasPreviewThumbnail,CanvasCreateGraphic}.tsx`、`canvas-home.css`、`canvas-home.ts`、`canvas-home.test.ts`、`canvas-model.ts` 与其测试；`backend/app/canvas_store.py`、`backend/tests/test_canvas_store.py`；README、功能指南、`frontend/DESIGN.md`、无限画布开发计划及 `docs/design-ref-canvas/home-exhibition-20261028/`。
- 兼容性：不改 API 路径 / 请求体、数据库表列、草稿 `schemaVersion=2`、任务队列、工作流、ComfyUI 节点 / 模型 / 生效地址；不增加依赖。旧画布在下次保存时自然补齐摘要字段，不批量读取草稿或迁移数据库。用户真实项目和媒体仍是展示来源，设计裁图仅用于独立浏览器验收。
- 验证命令：`pnpm --dir frontend build`（66 文件 / 454 项测试、TypeScript、clean-dist 与 Vite 通过）；`python -X utf8 -m unittest backend.tests.test_canvas_store backend.tests.test_core -q`（127 项通过）。真实 5173、独立 Edge，1586×992 / 1440×900 / 1920×1080 的浅暗主题与受控管理交互检查见验收档案；未触发实际出片或移动端测试。
- 回滚方式：只逆向撤回本节首页展示 / 状态、缩略图和可选摘要字段的增量，移除新增首页样式 / 图形 / 工具函数及对应测试后重新构建；不要整文件恢复 `App.tsx`、README 等并行改动。已保存的可选摘要字段可保留，旧客户端会忽略；无需数据库或 ComfyUI 回滚，不删除画布、草稿或版本记录。

## 2026-10-29 智能助手资源改为平台资源与管理员管理

- 变更原因：用户要求从 WorkBuddy 与开源项目导入的短剧 Skill / 专家不是个人资源，而是所有账号共用的平台资源，并允许管理员维护内容。
- 当前基线：资源 payload 新增 `platform: true` 标记，平台资源存储在 `owner_id=""` 下；内置资源继续 `builtin: true` 且只读。`ResourceService.catalog(owner, can_manage_platform=...)` 为每条资源返回 `platform`、`manageable`，目录顶层返回 `can_manage_platform`。平台资源仅对管理员（`admin` / `super_admin`）为 `manageable`，个人资源仅对创建者为 true，内置资源恒为 false。
- 权限与接口：`POST /api/director-assistant/resources` 接受可选 `scope: "personal" | "platform"`，平台范围要求管理员；`PUT` / `DELETE /api/director-assistant/resources/{id}` 先按 `shared=True` 读取目标，内置资源返回 403，平台资源对非管理员返回 403，管理员以 `save("", ..., platform=True)` / `repo.update("", ...)` 维护 `owner_id=""` 记录。收藏、导出和会话选择继续使用 `shared=True`，因此任何账号都能选用平台资源；个人资源隔离不变。
- 数据迁移：2026-10-29 已将 zlyadmin 名下 33 条已导入短剧资源（19 个 Skill + 14 个专家）及其 99 条版本记录迁移为 `owner_id=""` + `platform=true`；9 条内置资源保持不变。迁移按资源名精确匹配，未命中其他个人资源。
- 前端：资源市场标签区分「内置 / 平台 / 个人」，筛选增加「平台」，「我的」排除平台；编辑与删除按 `manageable` 显示；管理员新建或导入时可选择资源范围（默认个人），平台资源编辑弹层标题为「编辑平台资源」。复制资源仍创建个人副本。
- 受影响文件：`backend/app/director_assistant/resources.py`、`routes.py`、`service.py`、`backend/tests/test_director_assistant.py`、`frontend/src/director2/assistant/api.ts`、`ResourceMarket.tsx`、`DirectorAssistant.tsx`；README、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。
- 兼容性：不新增表或列；旧个人资源 payload 没有 `platform` 字段时按 false 读取；内置资源、收藏、导出、会话快照和既有 API 路径保持兼容；不涉及 ComfyUI、任务队列、工作流注册表或模型路径。
- 验证命令：`python -X utf8 -m pytest backend/tests/test_director_assistant.py -q`（78 项通过）；`pnpm --dir frontend build`（66 个测试文件 / 454 项通过，含 TypeScript、clean-dist 与 Vite 构建）；5173 桌面端验证管理员 Skill / 专家平台筛选（19 / 14）、平台标签、编辑删除按钮、新建范围控件与「我的」排除平台。普通账号的服务层可见性与 HTTP 越权拒绝由新增测试覆盖；未使用其他账号实时登录。
- 回滚方式：将 33 条平台资源及 99 条版本记录恢复为 `owner_id=8UKOFV4-iyb37iqN` 并移除 payload 的 `platform` 标记，撤回前端平台标签 / 筛选 / 范围控件后重新构建；内置资源与其他个人资源不受影响，无需表结构回滚。

## 2026-10-28 H3 Director 加速版默认改用完整 32 GB 权重

- 变更原因：用户要求把 H3 Director 系列（`minimax-h3-director-accel-t2v/-i2v/-r2v`，整集直出、逐镜与短视频共用）的默认模型体积从精简 20 GB 改为完整 32 GB，并提交一条真实任务看速度。该系列加速来自双 Sage、cfg 1 与 `res_multistep`，不挂 Turbo LoRA，精简权重此前只是节省内存的回退档。
- 当前基线：`workflow_registry.director_accel_weight_profile_option()` 默认 `full`，界面仍提供「完整（32 GB）」与「精简（20 GB）」两档；`minimax_h3_director_accel_workflow.py` 缺省 profile 回退到 full；前端 `director2-video-settings.ts` 的兜底 schema 与生成摘要同步为 full。二采精修的一采（`_refine_first_pass_defaults`）仍由平台托管为精简 20 GB + 均衡 20 步，不受本次改动影响；显式传 `weight_profile=pruned` 的 API 调用、草稿与已保存的工程设置继续使用精简权重。
- 实测（2026-10-28，远端 `192.168.10.54:8188`，RTX 4080 16 GB / 约 68.5 GB 内存 / ComfyUI 0.30.0 + PyTorch 2.11.0+cu128）：创作页提交 Director 加速 T2V，任务 `ZuEsPLO9KziD`，参数 5 秒 / 16:9 / 0.4 MP / 均衡 20 步 / full / 未开二采，端到端 156.2 秒，ComfyUI 执行 152.5 秒；输出 864×480、24 fps、5.167 秒、H.264 + AAC、456 KB，并自动交付七牛。加载完整 UNET 时远端可用内存从约 52 GB 降到 3.4 GB，完成后回到约 55.8 GB。
- 运行成本：后端在本地视频队列空闲后主动 `/free` + `VRAMCleanup` / `RAMCleanup`（`comfy_service.free_resources()`），因此单条任务每次都重新加载 32 GB 权重；本次 156 秒中约 100 秒为权重加载与模型初始化，20 步采样约 48 秒（按 ComfyUI 进度时间戳估算）。队列里已有后续任务时不卸载，背靠背提交可复用已加载权重。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_director_accel_workflow.py`、`backend/tests/test_minimax_h3_director_accel.py`、`backend/tests/test_timeline_rendering.py`、`frontend/src/director2/director2-video-settings.ts`、`frontend/src/director2/director2-video-settings.test.ts`；README、`功能说明与扩展指南.md` 与本文件。
- 兼容性：不新增 API、数据库列、任务队列、ComfyUI 节点 ID 或模型路径；`weight_profile` 字段与两档枚举保持不变，历史任务按已保存参数回放。默认值变化只影响新提交且未显式传值的请求；Director 二采的一采托管值不变。
- 验证命令：`python -X utf8 -m pytest backend/tests/test_minimax_h3_director_accel.py backend/tests/test_timeline_rendering.py -q`（23 项通过）；`pnpm --dir frontend exec vitest run src/director2/director2-video-settings.test.ts`（18 项通过）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build`；`/api/modes` 确认 `minimax-h3-director-accel-t2v` 的 `weight_profile.default` 为 `full`；真实任务 `ZuEsPLO9KziD` 完成并交付。全量后端测试仍有 3 项与本轮无关的既有失败（`test_director` 大小写断言、`test_mcp_gateway` 工具数量、`test_media_studio_schema` 迁移夹具）。
- 回滚方式：把 `director_accel_weight_profile_option()`、`minimax_h3_director_accel_workflow.py` 与前端兜底 schema / 摘要回退都改回 `pruned`，重启后端并重新构建前端；已提交任务不受影响，无需数据库回滚。

## 2026-10-28 生成、导演台与画布共用悬浮 Header

- 原因：用户要求参考即梦的悬浮工具区，先出设计图再还原；原通栏顶栏占据完整宽度，现改为两块独立悬浮表面。同日用户要求导演台与画布（画布首页、画布编辑）与生成页共用该悬浮 Header，不再保留各自的通栏 / 独立顶栏。
- 当前基线：`frontend/src/components/StudioHeader.tsx` 与 `studio-header.css` 是所有工作区唯一的页头，`App.tsx` 始终渲染，不再按工作区分支隐藏。桌面 Header 距顶 12px、左右 16px、高 48px，品牌块最小 312px、工具块最小 364px、圆角 16px；生成、资产、导演台、画布的工作区及图标 / 任务左栏都从 y=76 起始。中间区域透明且不截获指针。
- 壳层统一：`App.tsx` 的工作区始终带 `studio-floating-workspace`；导演台 `studio-director-view`（批量 / 复刻 / 旧壳）与 `studio-director2-view`（首页 / 项目壳 / 剧本诊断）以及画布 `studio-canvas-view` 统一 `margin-top: 76px`、高度 `calc(100vh - 76px)`，主区域不再叠加内边距；`.studio-icon-rail` 在导演台与画布顶部对齐 76px。导演台首页原 64px 单层顶栏删除；项目条、批量、复刻与剧本诊断顶栏只保留业务控件，主题切换统一从全局页头或账号菜单进入。画布原有 56 / 60px Header 覆盖样式与首页私有 Header 覆盖全部删除。
- 浮层：无遮罩的智能助手 Drawer 与画布素材 Drawer 停在页头下方（桌面 `top: 76px`、`height: calc(100vh - 76px)`），页头保持可见可点；带遮罩的 Modal / Drawer 仍按标准覆盖全屏。助手停靠（`is-editing-assistant`）与页面右侧留白规则不变。
- 组件与主题：直接使用 Ant Design Button / Avatar / Dropdown / Tooltip，账号菜单保留 MCP、按权限显示的管理设置与退出登录；主题沿用根 Provider 和浏览器持久化，连接状态由既有 `/api/health` 返回值驱动，加载 / 可用 / 不可用均以文字加圆点展示。新增阴影与标志颜色成对声明为 `--studio-header-*` token，其余使用 `--studio-*`。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/components/StudioHeader.tsx`、`frontend/src/components/studio-header.css`、`frontend/src/index.css`、`frontend/src/canvas/canvas.css`、`frontend/src/canvas/canvas-fidelity.css`、`frontend/src/canvas/canvas-home.css`、`frontend/src/canvas/CanvasEditor.tsx`、`frontend/src/canvas/CanvasPreviewThumbnail.tsx`、`frontend/src/director2/Director2StudioHome.tsx`、`frontend/src/director2/director-home.css`、`frontend/src/director2/Director2ProjectDetail.tsx`、`frontend/src/director2/assistant/assistant.css`、`frontend/src/director2/script-diagnosis/ScriptDiagnosisPage.tsx`、`frontend/src/director/DirectorBatchStudio.tsx`、`frontend/src/director/DirectorReplicationStudio.tsx`；README、功能说明与扩展指南、`docs/导演台流程与界面结构.md`、`docs/design-ref-generation/header-floating-20261028/DESIGN.md`、`docs/design-ref-canvas/DESIGN.md`、`docs/design-ref-canvas/FIDELITY.md` 与本文件。
- 兼容性：不改 API、数据库、任务队列、工作流注册表、ComfyUI graph 或前端路由；仅前端壳层样式、页头接线与页面局部顶栏。生成 / 资产工作区、任务侧栏、输入框与历史任务行为保留；导演台与画布的数据与交互协议不变。无新依赖或数据迁移。移动端（≤767）不纳入本轮验证范围。
- 设计与证据：`docs/design-ref-generation/header-floating-20261028/` 保存先生成的 `design-light.png`、实际桌面浅暗截图、几何与交互记录；基线为真实 5173、1584×993 / DPR 1，并覆盖 1440×900 和 1920×1080。即梦未登录访问深链跳转首页，参考范围以实际可见工具分组为限。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_core -q`（107 项通过）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend build`（66 个测试文件 / 454 项通过，含前端测试与 clean-dist，`✓ built in 15.03s`）；隔离 SQLite 后端 + 隔离 Vite 在 1440×900 浅暗主题检查生成页、导演台首页 / 项目壳 / 剧本诊断、画布首页 / 编辑以及两个无遮罩 Drawer，均确认页头可见、左栏从 76px 起始、Drawer `top` 76px / 高 824px 且页头可点击；另以独立登录会话检查菜单键盘、刷新记忆、导航与退出，不改后台配置、不提交生成任务。
- 回滚：撤回 `App.tsx` 的页头 / 工作区壳层接线，删除 `StudioHeader.tsx` 与 `studio-header.css`，并恢复上述导演台 / 画布文件中被删除的局部顶栏与 Header 覆盖样式后重新构建；保留其他视频结果、超分与账号改名改动，无需数据库或 ComfyUI 回滚。

## 2026-10-28 新增 SeedVR2 生成式超分引擎

- 变更原因：RTX VSR 只做传统锐化与去块，2× 放大后细节仍偏软，用户实测最近任务「看起来没效果，还是模糊」。为用户提供第二档「高清增强」：用当前 ComfyUI 的原生 SeedVR2 3B Int8 节点做生成式 2× 重建，接受分钟级耗时换回细节；RTX 保留为默认的秒级档。
- 当前基线：新增隐藏工作流 `seedvr2-upscale`（`JobMode.SEEDVR2_UPSCALE`，`hidden_from_catalog=True`），graph 在 `backend/app/seedvr2_upscale_workflow.py`，节点编号 30–44，避开 H3 的输出 14 与 RTX VSR 的 20–24。graph 对照官方模板 `utility_seedvr2_3b_int8_upscale_video.json` 展开子图并把开关分支拍平：LoadVideo → GetVideoComponents → ResizeImageMaskNode（`resize_type=scale by multiplier`，`resize_type.multiplier=2.0`，lanczos）→ SeedVR2Preprocess → VAEEncodeTiled（tile 512 / overlap 128 / temporal 64 / temporal_overlap 8）→ SeedVR2TemporalChunk（`chunking_mode=auto`，`temporal_overlap=0`）→ SeedVR2Conditioning + KSampler（seed 42、1 step、cfg 1、euler / simple、denoise 1）→ SeedVR2TemporalMerge → VAEDecodeTiled → SeedVR2PostProcessing（`color_correction_method=none`）→ CreateVideo（画面 + 原片 audio / fps / bit_depth）→ SaveVideo（`video/ZLY_AI_VIDEO_STUDIO_SEEDVR2`）。`SeedVR2Conditioning.vae_conditioning` 与 `KSampler.latent_image` 必须共用同一个 `SeedVR2TemporalChunk` 输出：条件接收 16 通道 5-D latent 后补成 17 通道，若仍接切分前的 `VAEEncodeTiled`，长片会报 `SeedVR2 conditioning shape must match latent ...`。
- 引擎路由：`UPSCALE_ENGINES = {"rtx": "RTX 快速超分", "seedvr2": "SeedVR2 高清增强"}`，默认 `rtx`；`POST /api/jobs/{job_id}/upscale` 的 JSON body 可选 `{"engine":"rtx"|"seedvr2"}`，导演台 `episodes/{episode_id}/beats/{beat_id}/upscale` 与 `projects/{project_id}/jobs/{job_id}/upscale` 同步透传，任务 `payload.upscale_engine` 记录实际引擎。`comfy_service.append_upscale_if_requested()` / `run_upscale_output()` 按引擎选择 stage、上传标签（`rtx_vsr_source` / `seedvr2_source`）、输出标签（`2x 超分` / `2x 高清增强`）与文件名前缀；RTX 显存拒绝只对 `rtx` 生效，SeedVR2 由 `SeedVR2TemporalChunk` 按当前显存自动切块并在节点内合并。重试逻辑、失败/中断自动重提与「超分结果不可再次超分」的 422 对两个引擎一致生效。
- 能力探测：`GET /api/upscale/capabilities` 探测 `RTXVideoSuperResolution` 节点与 5 个 SeedVR2 原生节点、`UNETLoader` 的扩散模型枚举、`VAELoader` 的 VAE 枚举，返回 `engines[{id,label,available,reason}]` 与 `default`，结果缓存 30 秒。`comfy_service.require_seedvr2()` 在节点或模型缺失时返回可操作文案（升级 ComfyUI / 放入 `models/diffusion_models` 或 `models/vae`）。
- 前端：`frontend/src/video-upscale.ts` 统一两个引擎 id、标签与超分输出判定；生成页 `VideoStudioModule` 的超分按钮改为可下拉的引擎菜单（「快速超分（RTX）秒级完成…」/「高清增强（SeedVR2）生成式重建细节…」）；导演剧集工坊和「全部任务」的「超分」改为 Ant Design `Dropdown.Button`，默认 RTX，右侧箭头可选 SeedVR2；`jobUpscaleHint()`、成功提示与失败提示都带引擎名。
- 实测（远端 `192.168.10.54:8188`，RTX 4080 16 GB，3B Int8 convrot 模型 + fp16 VAE）：4 秒 / 98 帧 / 1056×576 样片 301.5 秒，输出 2112×1152（2×）、98 帧 / 24 fps、AAC 32 kHz 立体声完整保留，文件 5.2 MB；A/B 帧对比可见细节更干净、噪声更少。产品链路 E2E（生成页任务 `XC2o2unhNuv0` → 超分任务 `rQcIrKXU57IZ`，`engine=seedvr2`）：源片 608×352 / 5.2 秒 / 124 帧，140.8 秒完成，输出 1216×704、124 帧 / 24 fps、AAC 32 kHz 立体声，已自动交付七牛（`seedvr2_upscale/20261028/...mp4`，2.66 MB）；生成页原任务显示「原片 1」与「2× 高清增强」两个版本，默认选中增强版。同源 13.7 秒 / 328 帧样片在自动分块下超过 25 分钟未完成（本轮为优先验证产品路径而中止），耗时随帧数明显超线性增长。chunk auto 模式预算为 `free_gb - 8.5 - k*0.55`、约 0.55 GiB /（MP×帧），16 GB 实例上长片会切成几十段依次采样再合并，因此整段耗时为分钟级、长片可能十几分钟；这是「高清增强（慢）」的产品定位，不替换 RTX。
- 受影响文件：新增 `backend/app/seedvr2_upscale_workflow.py`；修改 `backend/app/models.py`、`workflow_registry.py`、`comfy_service.py`、`main.py`、`rtx_vsr_workflow.py`、`media_studio/services/comfy_video_client.py`、`media_studio/services/episode_video_service.py`、`media_studio/routers/project_router.py`、`backend/tests/test_rtx_vsr.py`、`backend/tests/test_core.py`；前端 `frontend/src/video-upscale.ts`、`video-upscale.test.ts`、`media/VideoStudioModule.tsx`、`media/video-results.css`、`media/video-result-model.ts`（版本菜单按引擎显示「2× 超分」/「2× 高清增强」，超分版本不再重复副标题）、`media/video-result-model.test.ts`、`media/VideoRoundHeader.tsx`、`App.tsx`、`director2/panes/EpisodeWorkshopPane.tsx`、`director2/panes/JobsCenterPane.tsx`、`director2/director2-video-settings.ts`；`backend/app/api_documentation.py`、`docs/API.md`、README、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。
- 兼容性：不新增数据库表或列、不新增队列；超分接口 body 可省略（默认 `rtx`），旧调用完全兼容；新增模式与隐藏工作流只由超分入口使用，不进入创作页模型列表；既有 H3 / RTX VSR 的节点 ID、graph 与模型路径不变。远端实例缺少 SeedVR2 节点或模型时仅 SeedVR2 显示不可用，RTX 不受影响。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_rtx_vsr -v`（21 项通过）、`python -X utf8 -m unittest backend.tests.test_core -q`（106 项通过）、`python -X utf8 -m unittest backend.tests.test_h3_refine backend.tests.test_job_list_payload -q`；`pnpm --dir frontend test`（64 文件 / 441 项通过）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build`。真实 5173 登录后 `GET /api/upscale/capabilities` 返回两个引擎均 `available`；生成页超分下拉展示两条引擎与说明；剧集工坊「超分」已渲染为拆分下拉按钮（当前工程 0/4 镜视频时为禁用态）。JobsCenterPane 与工坊共用同一 `Dropdown.Button` 配置，未额外造数据。产品 E2E 已用真实任务跑通（`XC2o2unhNuv0` → `rQcIrKXU57IZ`），生成页版本菜单显示「原片 1」/「2× 高清增强」并默认选中增强版。
- 回滚方式：删除 `seedvr2_upscale_workflow.py`，撤回 `models.py` / `workflow_registry.py` / `comfy_service.py` / `main.py` / 导演媒体服务中的 SeedVR2 分支与 `/api/upscale/capabilities`，前端恢复超分单按钮并移除引擎菜单后重新构建；远端 SeedVR2 节点与模型可保留，不影响 RTX。已提交任务按保存的 graph 回放，无需数据库回滚或媒体清理。

## 2026-10-27 生成页 V4：紧凑视频预览、摘要版本切换与悬浮操作

- 变更原因：按已确认的即梦参考 V4 局部设计，还原生成详情；原视频铺满结果列、版本按钮和下载脚注使主要操作容易落到吸底输入框下方。
- 当前基线：保留全局顶栏、76px 图标栏、240px 任务栏、单列轮次与原输入框。视频预览左对齐、最多 480px，按实际媒体元数据保持比例，较矮桌面窗口按高度收小。浅暗主题使用同一 `--studio-*` 与 Ant Design Provider。参考图以有序缩略图入口展开；摘要回显注册表模型名、最多两项非布尔主参数、轮次和状态，多个视频通过中性文本「版本 N/M」切换。
- 状态模型：`App.tsx` 的 `videoVersionByRound` 按轮次记录输出身份，键包含任务、生成项、输出索引和路径，轮询追加超分时保留用户选择；输出消失时回退有效版本。`videoRoundDetails` 控制当前参数弹层及运行参数展开态。上述状态仅存在于页面内存，不新增存储键。`VideoRoundHeader` 承担视频轮次摘要与参数层级；`VideoStudioModule` 只渲染选中版本、管理原生视频播放与悬浮层。
- 交互与能力：下载、加入画布、剪映导出使用选中输出的来源任务、生成项、索引与真实 URL；更多菜单提供查看运行参数及需确认的「删除任务」。原生媒体 API 驱动播放、声音、进度与全屏，菜单打开或键盘焦点进入时保持工具条，Esc 关闭后恢复焦点。生成中阶段/停止、失败摘要/重试、一采预览确认/保留继续常驻。
- 超分边界：现有 `POST /api/jobs/{id}/upscale` 处理最新生成项中的第一份原片，本轮不改变接口；其他版本上禁用超分并说明原因，避免让用户误以为会处理当前显示的另一个版本。
- 2026-10-27 补充交互：`VideoStudioModule` 通过原生 Slider 的局部组件 token 将圆点设为 6px（悬浮/聚焦不放大），页面不再自行覆盖滑块定位。`seekEngaged` 只管理单个播放器的进度交互状态：普通悬浮不显示圆点，点击/拖动时显示，离开进度条后隐藏，键盘焦点继续可操作。媒体容器原生 `mouseleave` 负责暂停，包括进入其边界外的 Dropdown portal，不因离开播放按钮或进入容器内其他控件而暂停；移回行为按下面 2026-10-28 更新执行。预期的播放取消 `AbortError` 不弹播放失败提示。只增加组件内存状态与事件监听，无新 API/持久化字段；验证命令与回滚沿用本节，详细结果见本轮验收说明。
- 2026-10-28 悬浮自动预览：按用户补充要求，原生 `mouseenter` 现在自动播放并显示现有进度条，同时重置鼠标的圆点显示状态；移出仍暂停，重新移入从原位置续播。手动暂停只影响当前停留，不会被容器内鼠标移动打断。悬浮预览遵从浏览器自动播放策略，拦截或正常中止不弹错误提示，原手动播放入口保留。受影响文件仅为 `VideoStudioModule.tsx` 与文档，无 API/持久化变化；可逆向撤回新增 `mouseenter` 监听与预览回调后重新构建，不撤回此前移出暂停与小圆点交互。验证命令同本节，浏览器验收记录见 `docs/design-ref-generation/v4-20261027/ACCEPTANCE.md` 的 2026-10-28 章节。
- 受影响文件：`frontend/src/App.tsx`、`index.css`、`media/{VideoRoundHeader.tsx,VideoStudioModule.tsx,video-results.css,video-result-model.ts,video-result-model.test.ts}`，三份主文档与 `docs/design-ref-generation/v4-20261027/`。
- 兼容性：不改路由、HTTP API、数据库、工作流注册表/graph、队列、ComfyUI 实例、节点或模型路径；已有任务、中文对照、超分与二采确认协议保持兼容。旧图片轮次保留原布局；只移除旧视频专用的铺满尺寸和脚注样式。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_job_list_payload backend.tests.test_h3_refine -q`；`pnpm --dir frontend build`（内含全部前端测试与 TypeScript）。浏览器在真实 5173 的桌面浅暗主题检查，任务/登录/媒体使用隔离的受控响应与已有本地成片，不写真实数据库、不提交生成或切换 ComfyUI。证据与范围见本轮设计验收说明。
- 回滚方式：逆向撤回上述本轮前端增量与文档，删除新增的四个视频辅助文件并恢复 `VideoStudioModule.tsx` 的旧版渲染，再执行 `pnpm --dir frontend build`。不得覆盖其他并行改动；不需要数据库迁移、媒体清理或 ComfyUI 回滚。

## 2026-10-27 生成页视频轮次改为紧凑头部与单卡版本切换

- 变更原因：生成页原先每轮重复渲染完整提示词、参考图、创作参数与全部结果卡；多版本任务（原片 + 2× 超分）把消息流拉得很长，播放器又依赖浏览器原生控件，无法在同轮内切换版本或快速执行常用操作。本轮把视频轮改成「一个轮次头部 + 一张主视频卡」的紧凑结构，版本切换留在头部元信息里。
- 当前基线：`frontend/src/media/video-result-model.ts` 统一轮次结果模型：`videoResultKey` 由 `jobId + generationItemId + outputIndex + path` 组成，避免相关任务或同路径输出互相覆盖；`selectVideoResult` 优先用户显式选择，其次最新 2× 超分，最后原片；`videoVersions` 只统计真实视频输出，标签为「原片 N / 2× 超分」；`videoDeliveryLabel` 与 `formatVideoTime` 负责交付状态与时间码。`VideoRoundHeader.tsx` 负责参考图缩略堆叠与弹层预览、两行提示词（展开 / 收起、中英切换）、元信息行（模型名、最多 3 个 primary 创作参数、第 N 轮、状态、版本下拉、详细信息弹层）；`mode` 原始工作流 id 不再重复展示，创作参数与运行参数分层收在「详细信息」中。
- 播放与轮次渲染：`App.tsx` 每个视频轮只把当前选中的 `featuredVideo` 交给 `VideoStudioModule`，版本切换同时暂停旧视频；`VideoStudioModule.tsx` 使用自绘 `<video>` 播放层与悬停工具栏（下载、加入画布、导出剪映、查看运行参数、删除任务、全屏、播放 / 暂停、时间码、2× 超分、静音、进度条），竖屏卡片允许控制条换行，`prefers-reduced-motion` 关闭悬停过渡。视频轮的错误信息在头部下方独立展示；图片轮继续使用旧头部、参考图与详情结构。
- 元数据同步：缓存视频可能在 React 挂载监听器前就完成 metadata 加载，导致时间码停在 `00:00 / 00:00`。`[result.src]` 副作用在 `readyState >= 1` 时主动同步一次宽高与时长，并监听 `durationchange`，进度条与总时长因此始终取真实媒体值；封面继续使用云端缩略图。
- 受影响文件：新增 `frontend/src/media/video-result-model.ts`、`video-result-model.test.ts`、`VideoRoundHeader.tsx`、`video-results.css`；修改 `frontend/src/App.tsx`、`frontend/src/media/VideoStudioModule.tsx`、`frontend/src/index.css`。文档同步 README、`功能说明与扩展指南.md` 与本文件。
- 兼容性：不新增或修改 API、数据库、任务队列、ComfyUI 节点与模型路径；版本模型只读任务既有输出，超分、加入画布、导出剪映与运行参数接口保持原协议；旧任务、图片轮与失败轮无需迁移。选择消失时回退到可用输出，不阻塞轮次展示。
- 验证命令：`pnpm --dir frontend test`（64 文件 / 438 项通过）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build`；真实 5173 在 1440×900 桌面浅色与暗色下检查任务 `Q0nhLeqATP49`（横屏双版本）、`Zjmy2ZdEFv1N`（9:16 竖屏）与 `sqXCOO5vZF9p`（失败轮）：提示词展开、参考图弹层、播放 / 暂停、进度拖动、版本切换（旧视频暂停、标签 2/2）、详细信息与运行参数、竖屏控制条换行均正常；修复后在缓存命中的视频上复查时间码为 `00:00 / 00:13` 且进度条可用。
- 回滚方式：恢复 `App.tsx` 的旧轮次头部 / 全部结果卡渲染与 `index.css` 旧视频样式，删除四个新文件与对应样式引用后重新构建；任务数据与生成结果不受影响，无需数据库回滚。

## 2026-10-27 整集分辨率确认写入工程并锁定出片画质

- 变更原因：制作配方要求出片前确认整集统一分辨率（2K / 768P），但此前只存在于对话里；工坊按各工作流的默认画质出片，同一工程不同镜头或切换工作流后可能落到不同分辨率。现在把确认结果写入工程设置，并在后端创建任务时强制按锁定档位映射画质。
- 当前基线：智能助手问题卡提交标题匹配「出片 / 视频 / 整集 + 分辨率」的答案时，`AssistantService._project_setting_from_answer` 从选项 label 或随附文本识别 768 / 2K / 2048，写入 `settings.extra.video_resolution`（`768p` / `2k`）与 `video_resolution_label`（`768P` / `2K`）；写入与回答消息在同一事务内完成，非分辨率问题或未携带 `question_id` 的普通消息不触碰工程设置。`EpisodeVideoService.confirmed_video_resolution(project_id)` 读取 `ai_projects.settings_json.extra`；`apply_confirmed_video_resolution(project_id, options)` 按 `PROJECT_VIDEO_RESOLUTION_QUALITIES` 映射：`768p → quality 0.98 / refine_quality 1.0`，`2k → 2.0 / 2.0`；开启二采时锁定 `refine_quality`，否则锁定 `quality`；工作流枚举缺少该档位时取最高可用值（例如 T8 最高 0.98）。`create_job` 对所有创作台来源（整集直出、逐镜、选中镜）统一调用该函数，智能助手 `propose_media` 在解析生成参数前同样先应用锁定。
- 工坊界面：`Director2VideoSettingsPopover` 接收 `confirmedResolutionLabel`，把对应字段的 Ant Design Select 置灰，并在设置区显示「整集分辨率已确认：{label}」与「出片按该分辨率锁定；如需更换，请在智能助手中重新确认。」；`EpisodeWorkshopPane` 进入分集时从工程详情读取锁定并同步画质值，监听 `director-assistant-project-updated` 事件，在助手回答分辨率问题后无需刷新即可更新锁定；切换视频工作流时重新套用锁定值，避免新工作流默认画质覆盖确认结果。
- 受影响文件：`backend/app/director_assistant/service.py`、`backend/app/director_assistant/actions.py`、`backend/app/media_studio/services/episode_video_service.py`、`backend/tests/test_director_assistant.py`、`backend/tests/test_h3_refine.py`、`frontend/src/director2/assistant/DirectorAssistant.tsx`、`frontend/src/director2/director2-video-settings.ts`、`frontend/src/director2/director2-video-settings.test.ts`、`frontend/src/director2/panes/Director2VideoSettingsPopover.tsx`、`frontend/src/director2/panes/EpisodeWorkshopPane.tsx`、`docs/导演台智能助手V2.md`、`docs/导演台流程与界面结构.md`、README、`功能说明与扩展指南.md` 与本文件。
- 兼容性：不新增 API、数据库列、任务队列或 ComfyUI 节点；仅在工程 `settings.extra` 增加两个可选键，未确认分辨率的旧工程保持原有默认值。存在锁定时，API / MCP 显式传入的 `quality` / `refine_quality` 会被锁定值覆盖，这是本轮有意的行为变化；历史任务按已保存参数回放，不重算。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_director_assistant -q`（76 项通过）、`python -X utf8 -m unittest backend.tests.test_h3_refine -q`（42 项通过）；`pnpm --dir frontend test`（64 文件 / 438 项通过）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build`；真实 5173 在剧集工坊用受控工程详情响应验证：768P 锁显示「整集分辨率已确认：768P」且分辨率档位为 0.98 MP、2K 锁切换为 2 MP 且切换工作流后仍锁定，解除锁后提示消失、字段恢复可选；验证过程未写入或改动任何工程数据。
- 回滚方式：移除助手回答写入、`apply_confirmed_video_resolution` 的两处调用与前端锁定提示 / 事件监听 / 切换工作流重套逻辑，重启后端并重新构建前端；如需清除已写入的锁定，删除对应工程 `settings.extra.video_resolution` 与 `video_resolution_label`。已提交任务与数据库结构不受影响。

## 2026-10-27 智能助手工具调用格式兼容（百炼 Qwen）

- 变更原因：真实 5173 使用阿里云百炼 `qwen3.8-max` 跑通剧本、资产、分镜后，分镜轮和分辨率回答轮先后因三种未声明的工具调用写法被 Pydantic 拒绝：`tool_calls[]` 附带 `label/title/description` 展示字段；`<tool_call>{"name":...,"arguments":{...}}</tool_call></tool_response>` 这种 JSON-in-tag 加多余结束标签；以及用 `input` 代替 `arguments` 承载参数对象。模型内容本身完整，不应整轮作废。
- 当前基线：`AssistantService._normalize_tool_alias` 仅在工具项除展示字段外只含 `name+arguments`，或只含 `name+input` 时归一化；`input` 映射为 `arguments`，其余未知字段、同时出现 `input` 与 `arguments` 仍判格式错误。`_parse` 的 `<tool_call>` 分支先移除无协议含义的 `<tool_response>` 包裹标签；无子标签且正文为 JSON 时接受严格 `{"name","arguments"}` envelope，裸工具名与 `工具名{JSON}` 写法继续可用。规范化后仍经过同一 AssistantTurn / ToolCall 白名单与参数校验。
- 受影响文件：`backend/app/director_assistant/service.py`、`backend/tests/test_director_assistant.py`、`docs/导演台智能助手V2.md`、`功能说明与扩展指南.md` 与本文件。
- 兼容性：无 API、数据库、任务队列、ComfyUI 节点、模型路径或前端变化；JSON envelope、配对 `param_key/param_value`、裸工具名和 `工具名{JSON}` 原有写法保持不变。草稿仍需“查看并采纳”；媒体提案仍需确认执行。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_director_assistant -q`（73 项通过，新增展示元数据、Qwen JSON 标签、`input` 别名与歧义拒绝四项覆盖）；真实 5173 用 `qwen3.8-max` 重试分镜轮成功出 4 镜草稿并采纳，分辨率回答轮确认 768P，生成 4 条待确认三联关键帧提案。
- 回滚方式：撤回 `_TOOL_CALL_METADATA` 展示字段容忍、`<tool_response>` 清理、JSON-in-tag 分支与 `input` 别名，重启后端；无需数据库回滚。

## 2026-10-27 二采新增清晰度策略（自动 / 强制高清）

- 变更原因：按片长强制封顶后，用户选 1.0 MP 却拿到 0.6 MP，界面无法表达“要绝对清晰、可以等”的诉求；而完全不封顶会让长片退回 27 分钟以上的单次二采，并伴随显存分页失败风险。因此把隐式封顶改为显式的清晰度策略：默认自动降档，强制高清由用户主动选择并在超出预算时二次确认。
- 当前基线：`workflow_registry.py` 新增选项 `refine_quality_mode`（`auto` / `force`，默认 `auto`，`ui_group=primary`，`ui_visible_when={"refine_enabled": true}`）；`refine_target_megapixels(quality, frames, force=False)` 在 `force` 时跳过 `REFINE_FRAME_MEGAPIXEL_BUDGET` 直接返回请求档位（向下取到 0.1 MP）。`_refine_settings()` 返回四元组并校验取值（非法值报「清晰度策略请选择自动或强制高清。」），`_apply_refine_first_pass()` 将模式写入标准化结果并按模式写入 `refine_megapixels` 回显；官方 H3 与 T8 分支同样处理。`build_refine_nodes()` 增加 `refine_mode` 参数，节点 45 的像素与宽高随模式变化；`build_minimax_h3_refine_workflow()` 与 `comfy_video_client` 时间线路径从 options 读取 `refine_quality_mode`。
- 前端：`director2-video-settings.ts` 新增 `refineFrames()`、`refinePlan()`、`formatRefineDuration()`、`refineForceWarning()`，`refineEffectiveMegapixels()` 增加 `qualityMode` 参数（默认 `auto`，签名向后兼容），`videoSettingsSummary()` 输出「· 自动降档」或「· 强制」。`Director2VideoSettingsPopover` 在二采开启时显示实际输出分辨率与预计全程时长；超出预算不估算时长，改为风险提示，并说明降档 / 强制语义。`EpisodeWorkshopPane` 的逐镜、选中镜、整集直出与 `App.tsx` 生成页在强制高清超预算时用 `Modal.confirm` 二次确认，取消则不提交。
- 估算口径：二采预计时长 `frames × (1.37 + 0.75 × effectiveMP) + 52` 秒，仅在 `frames × effectiveMP ≤ 200` 时给出；帧数按 `round(duration × 24)` 并对齐 17 帧网格（最小 5 帧）；分辨率按 `h3_dimensions` 的 32 对齐规则从 MP × 1024² 推导，与后端一致。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_refine_workflow.py`、`backend/app/media_studio/services/comfy_video_client.py`、`backend/app/comfy_service.py`、`backend/app/media_studio/services/episode_video_service.py`、`backend/app/api_documentation.py`、`backend/tests/test_h3_refine.py`、`backend/tests/test_core.py`、`frontend/src/director2/director2-video-settings.ts`、`frontend/src/director2/director2-video-settings.test.ts`、`frontend/src/director2/panes/Director2VideoSettingsPopover.tsx`、`frontend/src/director2/panes/EpisodeWorkshopPane.tsx`、`frontend/src/director2/panes/episode-workshop.css`、`frontend/src/App.tsx`、README、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md`、`docs/API.md` 与本文件。
- 兼容性：`refine_quality_mode` 为新增可选字段，缺省按 `auto` 处理，旧客户端、旧任务与正在运行的任务行为不变；`refine_quality` 仍只接受 1.0 / 2.0；一采托管参数、先预览流程与节点结构不变。任务运行参数回显 `refine_quality_mode` 与实际 `refine_megapixels`。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_h3_refine -q`（37 项通过）；`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_rtx_vsr -q`（120 项通过）；`python -X utf8 -m unittest backend.tests.media_studio_test_h3_video -q`（137 项通过）；`pnpm --dir frontend test`（63 文件 / 433 项通过）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend build`；真实 5173 桌面端浅暗检查二采设置、实际分辨率与强制确认。
- 回滚方式：移除 `refine_quality_mode` 选项及其 schema / 校验 / 回显，撤回 `refine_target_megapixels()` 的 `force` 参数、`refine_mode` 透传与前端策略控件、预估和确认逻辑，恢复 `refineEffectiveMegapixels()` 调用与摘要输出；重启后端并重新构建前端。已提交任务按保存的 graph 回放，无需数据库回滚。

## 2026-10-27 二采固定先预览一采（平台托管）

- 变更原因：二采总耗时由片长与目标像素决定，先预览只增加一个暂停确认点、不增加算力。保留用户开关会允许关掉预览后连续跑两段式，但把勾选框删掉却仍不预览会让用户困惑；因此改为平台托管：界面不提供开关，开启二采就固定先预览一采。
- 当前基线：全部 H3 家族的 `refine_preview` schema 默认 `true`、`ui_group=internal`，创建页、导演台视频设置与工坊生成设置都不再渲染该控件。`normalize_options()` 在 `refine_enabled=true` 时强制 `refine_preview=true`，请求显式传 `false` 也会被忽略；关闭二采时强制 `false`。任务运行参数回显与旧任务续跑仍以保存值为准，旧任务缺该字段时执行端继续按关闭处理。
- 整集直出：`render_scope=episode` 无法暂停。`EpisodeVideoService._apply_render_scope_settings()` 把 payload 中的 `refine_preview` 置为 `false`，不再因请求携带该字段返回 400；工坊「一键生成视频」在二采开启且当前为整集直出时提示「整集直出无法中途确认，本次将连续跑完两段式」。逐镜与选中镜固定先预览。
- 前端摘要：`videoSettingsSummary()` 增加 `previewFirstPass` 参数；可暂停的逐镜/选中镜二采摘要固定追加「先预览」，整集直出摘要不追加。`DIRECTOR2_VIDEO_FALLBACK_FIELDS` 移除预览字段；不再需要 localStorage 版本迁移，旧存档里的 `refine_preview` 值既不会渲染也不会提交。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/media_studio/services/episode_video_service.py`、`backend/tests/test_h3_refine.py`、`backend/tests/test_timeline_rendering.py`、`backend/tests/media_studio_test_h3_video.py`、`frontend/src/director2/director2-video-settings.ts`、`frontend/src/director2/director2-video-settings.test.ts`、`frontend/src/director2/panes/Director2VideoSettingsPopover.tsx`、`frontend/src/director2/panes/EpisodeWorkshopPane.tsx`、README、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md`、`docs/API.md` 与本文件。
- 兼容性：不新增 API、数据库列、节点 ID 或 ComfyUI 协议；旧任务和正在运行的任务按已保存参数执行。行为变化仅影响新提交的二采任务：API/MCP 显式传 `refine_preview=false` 不再生效，逐镜/选中镜固定停在 `awaiting_refine`；整集直出不再返回 400，改为自动连续两段式并写入 `refine_preview=false`。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_h3_refine backend.tests.test_timeline_rendering -q`（49 项通过）；`python -X utf8 -m unittest backend.tests.media_studio_test_h3_video -q`（137 项通过）；`pnpm --dir frontend test`（63 文件 / 431 项通过）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend build`；真实 5173 生成页开启「二采精修」后确认设置只显示「二采画质」、不再出现「先预览一采」，工坊逐镜摘要的「先预览」由前端单元测试覆盖（验收项目集数为 0，未在真实工坊触发摘要）。本轮未提交真实远端生成任务。
- 回滚方式：恢复 `refine_preview_option()` 的 `ui_group=primary` 与 `ui_visible_when`、`_refine_settings()` 读取显式值、整集直出的 400 校验与前端设置字段/摘要参数，重启后端并重新构建前端；已生成任务与数据库不受影响，无需迁移。

## 2026-10-27 二采按片长限制目标像素并清理显存

- 原因：用户反馈远端二采任务耗时异常。真实远端（RTX 4080 16 GB / 68 GB 内存 / ComfyUI 动态显存）实测 13 秒 / 328 帧二采：0.4 MP 为 16.9 秒/步，0.6 MP 为 29.4 秒/步，1.0 MP 为 557 秒/步（二采 27:46，全任务 36:45）。1.0 MP 已越过显存与内存阈值：一采模型驻留时二采再产生 SigmaShift 模型副本，第二个 20 GB 权重暂存把可用内存压到 5 GB 左右，Windows 随即分页，单步继续放大到 17 分钟以上。远端的二采空间切片在当前节点版本不生效（无 `spatial tiles` 运行日志），因此不能靠切片解决。
- 当前基线：`workflow_registry.py` 新增 `REFINE_FRAME_MEGAPIXEL_BUDGET = 200`、`REFINE_MIN_MEGAPIXELS = 0.4` 与 `refine_target_megapixels(quality, frames)`，按“片长×目标像素”封顶并向下取到 0.1 MP：328 帧 1.0/2.0 MP 均实际 0.6 MP；192 帧仍可用 1.0 MP；124 帧 2.0 MP 降为 1.6 MP；更长片段最低 0.4 MP。`normalize_options()` 在二采开启时写入 `refine_megapixels` 作为任务运行参数回显，`build_refine_nodes()` 以同一函数计算节点 45 的 `megapixels`/`width`/`height`，用户选择的 `refine_quality` 保留为上限值。
- 显存：`build_minimax_h3_refine_workflow()` 与 `media_studio/services/comfy_video_client.build_workflow()` 均把节点 12 的 `clear_vram_before_refine` 设为 `true`，在一采结束、二采开始前卸载一采模型再重新暂存，避免两份权重同时驻留主机内存；此前该值为 `false` 是为了避免卸载后重载，但实测重载约 13 秒，远低于分页代价。整集直出的二采长度改用时间线中最长的分段帧数计算，节点 44/45 的切片与像素封顶都按单段成本评估。
- 界面：导演台「生成设置 → 二采画质」说明改为“平台按片长自动控制二采像素”；`videoSettingsSummary()` 新增可选片长参数，工坊顶栏按当前选中镜头的时长显示生效值，例如「二采 0.6 MP · 自动降档」。未传片长时仍显示用户上限值，保持旧调用与测试兼容。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_refine_workflow.py`、`backend/app/media_studio/services/comfy_video_client.py`、`backend/tests/test_h3_refine.py`、`frontend/src/director2/director2-video-settings.ts`、`frontend/src/director2/director2-video-settings.test.ts`、`frontend/src/director2/panes/Director2VideoSettingsPopover.tsx`、`frontend/src/director2/panes/EpisodeWorkshopPane.tsx`、README、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。
- 兼容性：不新增 API、数据库列、节点 ID 或 ComfyUI 协议；`refine_quality` 仍只接受 1.0 / 2.0，封顶只影响生成的 graph 与回显。旧任务按已保存 graph 回放，不重算；正在运行的任务不受影响。关闭二采的工作流完全不变。
- 验证命令：`python -m unittest backend.tests.test_h3_refine -v`（35 项通过）；`python -m unittest backend.tests.media_studio_test_h3_video backend.tests.test_rtx_vsr backend.tests.test_core`（257 项通过）；`pnpm --dir frontend exec vitest run src/director2/director2-video-settings.test.ts`（15 项通过）；`pnpm --dir frontend exec tsc -b`；真实远端直连探针 `test-results/refine-06mp-20261027-011504`（13 秒 0.6 MP：328 帧、1056×576、AAC 32 kHz 双声道、全任务 581 秒）；本机后端真实链路 `test-results/preview-refine-13s-20261027-013558`（任务 `Q0nhLeqATP49`：预览→确认→二采全流程 674.0 秒，一采 465.3 秒、二采 207.3 秒，成片 1056×576 / 328 帧 / 13.667 秒 / AAC 32 kHz 双声道，`effective_options.refine_megapixels=0.6`）。
- 回滚方式：撤回 `refine_target_megapixels()` 及其调用、回显字段与前端摘要参数，把两处 `clear_vram_before_refine` 改回 `false` 并重启后端、重新构建前端；已提交任务不受影响，无需数据库回滚。

## 2026-10-26 长片二采复用一采模型，避免第二个 UNET 初始化卡死

- 原因：13 秒 / 328 帧 / 1.0 MP 的二采任务停在 `0/3 Model Initializing` 17 分钟以上；远端日志显示一采模型、TE 与 VAE 仍驻留、可用显存约 1 GB 时，二采再次加载第二个 UNET（`minimax_h3_ref2va_pruned_w4a8_mixed`，11956 MB、208 patches）后无法完成 DynamicVRAM 初始化。`/interrupt` 需多次才生效，`/free` 无效。上一版“空间切片 + 关闭 Sage 编译”只作用于采样前向，而卡死发生在采样前的模型初始化，因此未能消除问题。
- 当前基线：`build_refine_nodes()` 不再创建第二个 UNET / LoRA / Sage 节点（原 40–43），节点 45（`MiniMaxH3DirectorRefine`）不接线 `refine_model`，由 Director 复用一采模型；节点 44（`BasicScheduler`）与节点 12 使用同一一采模型链路，sigma 与采样模型保持一致。两个构造器把 `clear_vram_before_refine` 设为 `false`，避免卸载后重载同一模型。上游 `refine_model_for()` 明确空接线回退到 Director 主模型，短 sigma 精修也建议复用一采 UNET。
- 画质与音频：二采使用一采权重（含该工作流的 LoRA 与 Sage 补丁）做 3 步 beta、denoise 0.2 精修；音频仍由一采生成，二采不重新生成音频。长片空间切片保留：`refine_tiling()` 在 `192–243` 帧 2 片、`>243` 帧 4 片，重叠 128px；`enable_latent_chunking` 仍在帧数 >60 时开启。
- 兼容性：不新增 API、数据库列、节点 ID 或模型；旧任务保留已保存的工作流与参数，正在运行的任务不受影响。关闭二采的工作流与一采参数托管逻辑不变。
- 受影响文件：`backend/app/minimax_h3_refine_workflow.py`、`backend/app/media_studio/services/comfy_video_client.py`、`backend/tests/test_h3_refine.py`、`README.md`、本文件和 `功能说明与扩展指南.md`。
- 验证命令：`python -m unittest backend.tests.test_h3_refine -v`（32 项通过）；`python -m unittest backend.tests.test_minimax_h3_director_accel backend.tests.test_h3_coverage backend.tests.test_director_workflow_speed backend.tests.test_director2_ai_generation backend.tests.test_director_concurrency`（77 项通过）。
- 回滚方式：恢复 `build_refine_nodes()` 中第二个 UNET / LoRA / Sage 节点（40–43）、把节点 45 的 `refine_model` 接回 43、节点 44 接回二采模型，并把 `clear_vram_before_refine` 改回 `true`；重启后端。已提交任务不受影响。

## 2026-10-26 二采一采参数改为平台托管

- 原因：真实远端 13 秒 / 5 参考图 / 2.0 MP 任务把一采设为完整权重、高质量 25 步，单是一采就远超常规出片时间；普通用户无法判断一采应使用哪种速度、模型体积与 LoRA。二采开启后一采只是生成底片的实现细节，应由平台按工作流选择已验证的最优组合。
- 当前基线：`refine_enabled=true` 时 `workflow_registry.py` 的 `_apply_refine_first_pass()` 强制写入 `quality=0.4`、`megapixels=0.4`，并由 `_refine_first_pass_defaults()` 按工作流族覆盖一采技术参数：官方 H3 精简权重 + 8 步 FL2V Turbo LoRA（强度 1.0）；LightX2V 完整权重 + 快速 4 步 + 对应 FL2V / REF2V 4 步 LoRA（0.75）；八步双加速完整权重 + 均衡 8 步 + 双加速 LoRA（1.0）；Director 加速版精简权重 + 均衡 20 步 + 关闭 LoRA；T8 完整权重 + 均衡 8 步 + Turbo LoRA（1.0），全能参考视频 8 步 / 音频 10 步，双时钟统一 8 步。请求中冲突的一采值被覆盖，标准化结果与任务运行参数快照回写平台实际值。
- 界面：LightX2V、八步双加速、Director 加速版与 T8 的 `speed`、`weight_profile`、`custom_steps` 均声明 `ui_visible_when={"refine_enabled": false}`；前端 `videoOptionVisible()` 在开启二采后不再渲染这些字段，生成摘要也不再显示模型体积，只显示比例、二采画质与可选的「先预览」。关闭二采时原选项、默认值与提交行为不变。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/tests/test_h3_refine.py`、`frontend/src/director2/director2-video-settings.ts`、`frontend/src/director2/director2-video-settings.test.ts` 及四份主文档。
- 兼容性：不新增 API、数据库列、工作流节点或 ComfyUI 协议；旧任务按已保存参数回显，不重算。只有新建或重新提交的二采任务使用锁定的一采参数，正在运行的历史任务不受影响。
- 验证命令：`python -m unittest backend.tests.test_h3_refine -v`（30 项）；`python -m unittest backend.tests.test_minimax_h3_director_accel backend.tests.test_h3_coverage backend.tests.test_director_workflow_speed backend.tests.test_director2_ai_generation backend.tests.test_director_concurrency`（77 项）；`pnpm --dir frontend exec vitest run src/director2/director2-video-settings.test.ts`（14 项）；`pnpm --dir frontend build`。
- 回滚方式：撤回上述 registry helper、schema 可见性与前端摘要改动，重启后端并重新构建前端；二采任务恢复为沿用用户提交的一采参数，无需数据库回滚。

## 2026-10-25 批量与复刻创作设置精修

- 原因：继续精修导演台子页面。旧批量表单直接展示模型体积，复刻表单直接展示采样步数与深度控制强度，创作设置和内部运行参数混在同一层级；复刻底栏还包含与当前远端连接环境不符的「本地」说明。
- 当前布局：沿用 320px 设置栏、根级双主题和原工作室外壳。批量以 Ant Design Form 呈现数量 / 画面比例、单条时长、注册表提供的视频工作流与可选画风；复刻以 Form 呈现分镜方式、固定分段时的每段秒数、目标风格和开始操作，智能分镜的切镜灵敏度放入 Ant Design Collapse「更多设置」。控件标签和键盘可访问名称补齐。
- 参数兼容：UI 不主动改写旧载荷中的 `weightProfile`、`renderSettings.steps`、`renderSettings.vaceStrength` 和 seed；自动保存继续合并原载荷，内部设置不移入展开区。重新批量生成仍遵循原有后端创建流程，本轮不改后端默认值、图映射或任务提交协议。
- 受影响文件：`frontend/src/director/{DirectorBatchStudio,DirectorReplicationStudio}.tsx`、`frontend/src/director2/director-surfaces.css`、`.gitignore`，以及 README、扩展指南、导演台流程快照和 `docs/design-ref-director/specialists-ui-20261025/`。
- 验证：`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_core.WorkflowTests backend.tests.test_core.ApiDocumentationTests.test_shot_replication_payload_normalization backend.tests.test_core.ApiDocumentationTests.test_wan_vace_depth_workflow_parameter_layers_and_builder_mapping backend.tests.test_director_project_info -q`；5173 / DPR 1 下 1600×1000 冻结稿对照和 1440×900、1920×1080 桌面浅暗检查。浏览器 API fixture 隔离，未入队模型或访问用户数据；原始证据与边界见[验收报告](design-ref-director/specialists-ui-20261025/ACCEPTANCE.md)。
- 兼容与回滚：无新依赖、路由、API、数据库迁移或工作流变化；Prompt Bar 的官方 token 与内部视觉未改。仅逆向撤回上述三份 UI 文件的本轮增量及对应文档后构建，保留用户同期的首页、工坊、助手、生成页和后端修改。

## 2026-10-25 生成页提示词中文优先展示与英文对照

- 原因：MiniMax H3 润色结果按官方规范为全英文，任务卡直接显示英文对中文创作者不友好。用户要求界面默认显示中文，同时提供查看 / 翻译成英文的入口；实际提交 H3 的提示词必须保持英文。
- 当前基线：`POST /api/llm/optimize-prompt` 的 `optimized_prompt` 仍是直接用于生成的英文 H3 提示词；新增 `optimized_prompt_zh` 作为简体中文对照，仅供展示。中文翻译使用 `build_h3_prompt_chinese_translation_prompt` 与 `OpenAICompatibleClient.translate_h3_prompt_to_chinese`，失败时返回空串并静默降级，不阻塞生成。图片工作流不生成中文对照。
- 模型输出加固：真实 `XingChenAGI/Xing4.0-29B` 会把思维链直接写进 `content` 且不加 `<think>` 标签。`extract_h3_prompt_from_model_output` 优先取最后一个合法围栏代码块（至少包含两个官方字段），否则取未包裹的最终提示词并截掉尾随说明；判定为分析过程但找不到完整提示词时抛错，由前端回退原文，避免把 6,000 字推理当提示词提交。
- 中文翻译完整性：`missing_h3_translation_fields` 按英文原文中的官方字段逐项核对中文译文（认英文原名或中文标签）；缺段时带缺失字段提醒重试一次，仍不完整则返回空串并提示「中文对照暂不可用」。译文同时清理 Markdown 引用标记 `>`，字段名单独成行。
- 持久化：`POST /api/jobs` 与 `POST /api/jobs/{job_id}/rounds` 新增可选表单字段 `display_prompt`，与 `prompt` 不同时随轮次写入 `job_rounds.display_prompt`；`GET /api/jobs/{job_id}` 的每个轮次回显该字段。SQLite 与 MySQL 初始化都会自动补列（MySQL `LONGTEXT NULL`，SQLite `TEXT`），旧轮次保持 `NULL`。
- 前端：润色成功后编辑框展示中文，任务卡默认展示 `display_prompt` 并可切换 English；编辑器提供「查看英文」只读弹层与复制。未改动的已润色结果在按工作流、参考图、风格、时长匹配时直接复用英文提交，避免重复调用大模型；自动润色关闭时，匹配到已润色英文仍提交英文。任务列表、搜索、排序、重命名默认值和预览描述优先使用中文展示。
- 受影响文件：`backend/app/{llm_minimax_skills,llm_client,llm_provider,main,models,storage,api_documentation}.py`、`backend/tests/{test_llm,test_core}.py`、`sql/001_init_mysql.sql`、`frontend/src/App.tsx`、`docs/API.md` 及三份主文档。
- 兼容性：不新增路由、不改变 `prompt` 的提交语义；旧任务无 `display_prompt` 时前端回退英文。翻译失败、模型不可用或中文为空时，界面保留原文，任务卡仍可切换英文。
- 验证命令：`python -m unittest backend.tests.test_llm backend.tests.test_core.StoreTests backend.tests.test_core.ApiDocumentationTests -q`；`pnpm --dir frontend test`；`pnpm --dir frontend build`；真实 5173 桌面验证中文默认显示、English 切换、查看英文与重新编辑。2026-10-25 追加真实任务 `XC2o2unhNuv0` 验证中文轮次持久化与刷新后默认展示。
- 回滚：恢复上述文件本轮增量并重启后端；`job_rounds.display_prompt` 可保留为空列，不影响旧客户端读取，无数据回填需求。

## 2026-10-25 自然语言剧本创作与会话恢复

- 原因：真实 5173 默认模型已写出六镜剧本，却以顶层工具数组返回，原解析器报错且模型格式修复失败；代码回归另复现了自然表达漏判、只读工具调用后仍无剧本草稿却报告成功，以及点击当前历史会话后空白、终态详情读取失败后输入锁定。
- 当前基线：模型响应先做有界格式归一化，再走原工具白名单与参数校验，制作配方读取和采纳权限不变。明确剧本创作必须得到实际会话草稿或待答问题才可成功结束；只读工具调用不算草稿完成。意图继承以当前未完成任务为界，支持多轮澄清与已有剧本的自然语言修改，排除否定、标题/简介咨询和智能剪辑操作；重试保留来源任务，新写下一集不关联上一集的修订链。本节取代下方旧记录的「最近四条」意图窗口。
- 内容库：兼容 `## 主要人物` 下的简短人物设定，以及 `**动作**`、`**运镜**`、`**对白**`、`**旁白**` 等粗体字段。各字段分别保存，动作中照片上的引号文字不再被误识别为对白；保留原文和既有标准台本格式。
- 2026-10-26 解析补充：同集中的「同上 / 同前」继承前镜场景，跨集不继承；场景实体按逗号前的名称聚合，光线等说明仍保留在镜头与场景描述中，避免创建「同上」或同一地点的多个描述副本。镜头标题的 `0-8秒` 等明确时间段用于补齐 `duration_sec`，显式「时长」字段优先，六镜 `8/8/8/12/12/12` 正确合计 60 秒。
- 会话恢复：前端显式重新加载当前历史会话，终态读取失败释放陈旧运行锁并提供「重新加载」，成功恢复清除旧错误；不把失败标记成成功。
- 真实修订兼容：明确剧本请求在调用模型前通过既有 `project_read(stage=script)` 读取本轮配方并提供完整规范，界面显示「读取制作规范」，避免模型漏读后重复丢弃有效草稿。其他阶段的先读约束保留。格式修复若返回旧产物形状，只从合法 JSON 的完整 `content` 提取正文建立会话草稿，忽略模型自报的 `applied`、版本和产物 ID；修订关系使用当前会话的真实记录，仍需预览采纳。资产、媒体和剪辑的普通格式修复保留原工具类型。
- 2026-10-26 对话历史：发送给模型的历史以普通对话正文为主，澄清问题、草稿 ID 和工具结果明确标为历史数据；不再把前端 `markdown/tool/artifact` 事件数组直接当作聊天正文，避免模型照抄界面记录、引用旧草稿冒充新修订。持久化消息与前端事件协议保持原样。
- 文件：`backend/app/director_assistant/service.py`、`backend/app/media_studio/services/script_parser.py`、`backend/tests/{test_director_assistant,test_standard_script_parser}.py`、`frontend/src/director2/assistant/{DirectorAssistant.tsx,assistant-state.ts,assistant-state.test.ts}`、`frontend/src/director2/panes/content-library.css`、`.gitignore` 及四份主文档。
- 兼容性：不新增 API 路由、数据库字段、任务队列、ComfyUI 配置或媒体任务；保留现有 JSON envelope 与工具块格式。剧本仍先保存为会话草稿，预览后由用户采纳；内容库与剧集工坊同步仍为现有独立步骤。前端调整会话恢复逻辑，内容库镜头卡改用已有 `--studio-*` 表面、文本和边框变量以修复暗色残留白底，不修改官方对话视觉 token。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_director_assistant backend.tests.test_llm backend.tests.test_standard_script_parser backend.tests.test_director_project_info backend.tests.test_editing_assistant -q`；`pnpm --dir frontend build`；真实 5173 桌面自然语言多轮创作、修订、采纳、历史与刷新恢复。
- 2026-10-26 最终验收：上述后端 181 项通过，前端测试、TypeScript 与构建通过（最终 Vite 10.48 秒，仅既有大 chunk 提示）。真实 `XingChenAGI/Xing4.0-29B` 在工程 `proj-a402b136409c48be` 完成自然语言想法、普通文字回答澄清、首稿及两次改稿，草稿版本依次为 1/2/3；均经预览采纳，最终仍只有 1 份文档，解析为 1 集、6 镜、2 角色、1 场景、60 秒。刷新后内容与第 3 版采纳记录恢复。1440×900 浅暗截图见 `docs/design-ref-director/language-flow-20261025/content-light.png`、`content-dark.png`。当前模型仍可能触发格式整理并增加等待时间，无法产生有效正文时继续如实失败，不以旧草稿冒充新结果。
- 回滚：只逆向撤回上述文件本轮增量，保留此前流式修复和其他用户改动，重启后端并按需构建前端。已有会话、草稿和内容库文档保留，无需数据库迁移。

## 2026-10-25 导演台智能助手流式与剧本草稿可靠性修复

- 原因：真实 5173 对话验收发现三类问题：模型输出完内容后连接不关闭，运行长时间不结束；默认模型以 `<tool_call>工具名{JSON}</tool_call>` 返回调用时被当成工具名，触发整轮重写；用户明确要求写剧本时模型只把正文放进 `text`，没有创建可采纳的 `create_draft`。另外观察到模型在合法 JSON 前加 Markdown 引用符 `>`，导致首轮校验失败并整轮重写。
- 流式基线：`OpenAICompatibleClient._read_sse_chat` 在任一 choice 返回非空 `finish_reason` 时立即结束读取；守护线程在连续 90 秒没有新的正文或推理增量时关闭连接并抛出 `LlmStreamStalled`（总时长上限 900 秒）。`LlmProviderService.assistant_chat` 捕获 `LlmTemporaryError` 后用 `stream=False` 重试一次（连接 / 读取超时 15 / 300 秒），同一轮的模型、消息和 `max_tokens` 不变。其他同步调用和流式入口的超时行为不变。
- 格式基线：`AssistantService._parse` 先去掉 Markdown 引用符 `>` 与代码围栏，再按单个 JSON envelope 校验；流式预览正则和格式修复前的原始解析使用同一归一化规则。`<tool_call>` 分支继续只接受完整、有界、无块外正文的内容，并新增 `工具名{"参数":...}` 与裸工具名两种无子标签写法；参数必须是 JSON 对象，工具名仍受白名单约束。
- 剧本落草稿：系统提示要求用户明确要求写剧本、台本或某一集正文时必须调用 `create_draft(artifact_type="script")` 并把完整正文放进 `content`。服务端从最近用户消息判断剧本意图，排除“方向 / 建议 / 大纲 / 怎么 / 如何”等讨论型请求；若模型只返回正文且没有工具调用或问题，先修复调用一次；仍只有正文且文本达到剧本特征阈值（长度、场景 / 镜头 / 对白标记）时，确定性生成草稿工具调用，标题取 `《…》` 或“第 X 集”；否则整轮失败并明确反馈“没有生成可采纳的剧本草稿”，不伪造成功，也不写入工程。
- 受影响文件：`backend/app/{llm_client,llm_provider}.py`、`backend/app/director_assistant/{service,protocol}.py`、`backend/tests/{test_llm,test_director_assistant}.py`、`docs/导演台智能助手V2.md`、`README.md`、`功能说明与扩展指南.md` 与本文件。
- 兼容性：不新增或修改 API 路由、数据库表 / 列、任务队列、ComfyUI 节点、模型路径、工作流 graph 或前端路由；协议仍是单个 JSON envelope，已有 `<tool_call>` 成对参数格式和无工具纯文本回复继续可用。新增的确定性剧本草稿只是会话草稿，仍需用户“查看并采纳”后才写工程，不触发媒体任务。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_director_assistant backend.tests.test_llm -q`（101 项通过，覆盖 `finish_reason` 提前结束、静默流中断与回退、内联工具格式、`>` 归一化与流式预览、剧本自动草稿、讨论型请求不强制草稿、无可用正文时如实失败）；`pnpm --dir frontend build`（63 个测试文件、429 项测试、TypeScript、clean 与 Vite 构建通过，8.82 秒）。真实 5173 使用 `XingChenAGI/Xing4.0-29B` 完成“写第一集完整剧本”，run 成功并生成「雨夜回声 第一集」会话草稿（4567 字），界面显示「查看并采纳」，未写入工程；该次首轮格式失败由 `>` 触发，修复后已由单元测试覆盖，未再次发起付费重跑。
- 回滚方式：逆向撤回上述后端与测试改动并重启后端。提示词、意图判定和确定性草稿可单独回退；已保存的会话、草稿、采纳结果和数据库记录不受影响。

## 2026-10-25 多集短剧 / 剧集管理桌面设计还原

- 日期与原因：2026-10-25。用户确认“系列”为导演台的多集短剧 / 剧集管理；先生成完整主界面和微组件稿，再还原剧集工坊概览，修正暗色白底、假身份 / 场景数量、分集浏览和弹窗反馈不足。
- 当前界面：工程 → 分集 → 镜头层级及 `/director/projects/:id/workshop` 路由不变。概览采用单条制作统计、五项带数量的状态筛选、集数 / 标题 / 剧本搜索、集数升降序 / 更新时间排序与三列分集卡；卡片显示真实规划镜头、更新日期及由制作状态推导的四阶段位置，不展示出片完成百分比。项目资产加载失败显示可重试说明，不冒充零数量。
- 前端状态：`episode-overview.ts` 只做派生筛选、排序、统计、摘要、阶段和下一个集号；查询、筛选、排序、列表错误、新增 / 编辑 Form、删除确认和请求中标记均为组件挂载期状态，不新增持久化或协议字段。`is-workshop-overview` 只负责概览布局；助手原入口仅在该页移到项目导航底部，不修改 AI 对话与 Prompt Bar。
- 表单与删除：直接使用 Ant Design Form / Input / InputNumber / Select / Modal / Dropdown / Steps。新集序号为当前最大整数 + 1，创建前校验必填标题、正整数和本列表重复集数；编辑时集数只读（既有更新接口不写此字段），保留快照镜头数。空新集镜头数为 0。保存失败保留输入；请求中防重入并禁止关闭。删除使用受控 Modal，默认聚焦取消；失败就地显示错误并保留目标，捕获异常后允许重试。
- 兼容性：无依赖、API、数据库表 / 列、工作流、ComfyUI 地址或模型路径变更；原 `data_json`、镜头和媒体数据不迁移。浅暗沿用根级 Provider、Ant Design token 和 `--studio-*`。默认只验桌面。
- 受影响文件：`frontend/src/director2/{episode-overview.ts,episode-overview.test.ts,Director2ProjectDetail.tsx}`、`panes/{EpisodeWorkshopPane.tsx,episode-overview.css}`、`.gitignore` 和四份主文档；设计参考位于 `docs/design-ref-director/series-ui-20261025/`。另补齐 `backend/tests/test_media_studio_schema.py` 的存量画布 / 二采列 fixture，使原用例继续只验证 LLM 列的单次迁移，不修改后端业务实现。
- 验证命令：`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_director_project_info backend.tests.test_media_studio_schema -q`；5173 桌面浅暗交互 / 错误注入 / 三种宽度 / 原图几何与微组件截图对照。最终结果与已知差异见[验收报告](design-ref-director/series-ui-20261025/ACCEPTANCE.md)。
- 验证环境说明：本项目 `media_studio.db` 有独立 MySQL 连接池，单独设置 `DB_BACKEND=sqlite` 不会隔离该层。首次验证误建的 1 个样例工程、6 个分集已按明确 ID 与创建时间校验并清理，余量核对为 0，未修改其他记录。后续专用测试启动器在忽略的测试目录中适配该数据层到 SQLite，并直接拒绝 MySQL 连接；该启动器不是生产实现，不应把单一环境变量当作完整隔离保证。
- 回滚方式：只逆向撤回上述文件本轮的概览、表单和文档增量，保留工作区其他改动后执行前端构建。无需数据库回滚；既有分集和镜头继续可读。样例清理已完成，不应在回滚时重建到用户数据库。

## 2026-10-25 导演台首页：创作启动台与工程工作区（当前基线）

- 原因：将创建工程与继续工程分成两个工作区，替换原欢迎区、左一大右两小入口、横向诊断条与三列工程卡。
- 当前布局：全局 76px 导航 / 64px 顶栏；左侧 358px 创作启动台选择三类模式、查看对应三步说明并创建，剧本诊断独立位于左下；右侧标题、刷新、Ant Design Segmented / Input 与 Table 宽列表。主体在桌面内独立滚动。低于 1400px 的桌面将启动台收为 300px。浅色默认，所有业务控件继承根 Provider；新增视觉仅为局部蓝青 SVG 镜头核心。
- 状态与协议：新增局部 `createKind`，仅决定说明与按钮；点击模式不写库。批量与复刻共用既有 `creatingProject` 防止重复提交。`/api/projects`、`/api/director/projects`、`/api/skill-packs` 及三种创建目标路由保持原协议；列表仍按更新日期合并，默认筛选导演创作、显示六项。删除继续二次确认，改用 Ant Design Modal；复制 / 删除收于行操作 Dropdown。无持久状态或数据库迁移。
- 文件：`frontend/src/director2/Director2StudioHome.tsx`、`director-home.css`、`.gitignore`；README、扩展指南、导演台流程快照与 `docs/design-ref-director/home-workspace-20261025/`。并行子页面与后端改动不属于本轮。
- 验证：`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_director_project_info backend.tests.test_skill_packs -q`；5173 的 1505×1045、1440×1000、1920×1080 / DPR 1 桌面浅暗与隔离接口交互。19 个主体锚点及未达到逐像素一致的边界见[验收报告](design-ref-director/home-workspace-20261025/ACCEPTANCE.md)。
- 回滚：只逆向撤回本轮首页两文件与文档增量后构建，不回滚其他同期改动；无需迁移或恢复生产数据。

## 2026-10-25 导演台子页面设计与还原

- 日期与原因：2026-10-24 先制作设计图，2026-10-25 完成精修与验收。原子页面标题、控件和空态尺寸各异，批量参数列被压缩，资产库分类重复。用户确认沿用现有风格，统一到根级双主题。
- 当前界面基线：内容库、资产库、工坊分集、任务中心、短视频批量、参考片复刻和剧本诊断，共用 26px 标题、40px 主操作、36px 紧凑表单、12px 面板圆角。工坊概览后续采用同期[多集短剧设计](design-ref-director/series-ui-20261025/DESIGN.md)的 28px 标题、制作概览、搜索筛选排序与分集阶段卡，首轮设计对照保留为历史。项目顶栏 72px、导航 200px、内容留白 28px。剪辑保留既有独立布局，助手与 Prompt Bar 沿用官方 beautifului token。当前已下线的 Hypit 只保留历史设计，不恢复模块。
- 资产库：分类用 Ant Design Segmented 显示真实数量；侧栏 248px，搜索与角色 / 场景 / 道具列表可键盘操作。首轮验收发现 Ant Design 6 的 Spin 根为 `.ant-spin`，修订设计后兼容新旧包装结构，锁住剩余高度；名单和长详情分别滚动。完整定义、参考音、原片参考、设定板、场景与道具功能仍按原接口保存。
- 前端视图状态：任务页新增名称 / ID 搜索、状态筛选、筛选结果数量与无结果恢复；完成状态兼容 `completed/succeeded`，取消组兼容 `cancelled/canceled/interrupted`。切换筛选回第一页，结果缩减时校正页码；用户主动切换类型后，首次请求返回不再覆盖用户选择。筛选仅在本次页面挂载期间生效。
- 受影响文件：`frontend/src/director2/{Director2App.tsx,director-surfaces.css,panes/ContentLibraryPane.tsx,panes/AssetsLibraryPane.tsx,panes/EpisodeWorkshopPane.tsx,panes/JobsCenterPane.tsx}`，`frontend/src/director/{DirectorStudioModule.tsx,DirectorBatchStudio.tsx,DirectorReplicationStudio.tsx}`；`.gitignore`、README、扩展指南、导演台流程快照和 `docs/design-ref-director/subpages-ui-20261024/`。
- 兼容性：继续使用现有 React / Ant Design、路由、根级主题、项目与媒体保存接口。新增筛选为客户端视图状态，不新增依赖、API 或数据库迁移。历史 Hypit 设计与本轮当前路由验收分开归档。
- 验证命令：`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_director_project_info backend.tests.test_director2_ai_generation -q`。界面在真实 5173 入口按 1600×1000 同视口对照，并检查 1440×900、1920×1080 桌面浅暗主题。设计和交互证据、原稿差异与验证边界见[验收报告](design-ref-director/subpages-ui-20261024/ACCEPTANCE.md)。临时样例没有入队模型生成。
- 回滚：仅逆向撤回上述子页面 UI 增量及本次说明，并重新执行前端构建；保留用户同期的首页、生成页、缓存和后端修改。任务筛选可独立撤回，资产 Spin 包装修复也可单独恢复；无需迁移历史数据。

## 2026-10-24 智能剪辑桌面 UI 设计还原（新增当前基线）

- 日期与原因：2026-10-24。按用户要求先生成浅色设计图，再在既有智能剪辑中还原并进行真实 5173 浏览器验证，解决空白属性栏挤占预览、素材导入零散和工具层级不清晰的问题。
- 界面基线：使用内置 imagegen 的原始 1672×941 设计图；46px 命令栏、12px 区域间距、10px 面板圆角、60px 工具轨、16:9 素材缩略图与居中圆形播放键。素材列 272px / 宽桌面 328px，属性列 224px / 宽桌面 256px；时间线 276px（低于 820px 高度时 235px），轨名列 128px / 宽桌面 140px。1560px 为编辑器宽桌面分界；助手停靠分别为 <1560px 的 360px、1560–1799px 的 400px、≥1800px 的 440px。
- 前端状态与行为：`inspectorOpen` 仅为当前 `EditWorkspace` 的临时显示状态，默认关闭，选中片段自动打开，顶部切换按钮与面板关闭按钮可控制显示；不写入剪辑文档或浏览器草稿。剪辑页将工程图标栏整合为标题剪刀按钮的 Ant Design Dropdown，五项工程导航仍可使用，并在切换前等待 `saveLatest()`；项目基本信息按钮在剪辑页采用带无障碍名称的图标。
- 助手与主题：助手展示三项主入口，「智能成片」下拉仍包含四种剪辑动作及引流的五策略，「字幕」下拉保留自动字幕 / 音轨字幕；授权、理解 / 转写证据和确认语义不变。修改前已读取官方 `app/globals.css`、`components/chat.tsx` 和 `components/prompt-bar.tsx`；保留原 `--director-*` 成对 token。修正 Ant Design 6 的 `ant-drawer-section` 与 `ant-tabs-body-holder` 选择器，保证表面、内边距和属性滚动生效；编辑器继续从 `--studio-*` 派生颜色，选中态和滑块在双主题下保持清晰。
- 兼容性：未新增路由、API、数据库列、工作流参数、模型或依赖；剪辑 `version: 1`、revision CAS、自动保存、撤销重做、字幕、特效和导出协议不变。设计示例和测试媒体只存在于隔离验收工程，不进入业务代码。未切换 ComfyUI、未启动 ComfyUI，也未提交生成或转写任务。
- 受影响文件：`frontend/src/director2/smart-edit/{SmartEditPane,Preview,Inspector,Timeline}.tsx`、`smart-edit.css`、`frontend/src/director2/assistant/{DirectorAssistant.tsx,assistant.css}`、`frontend/src/director2/Director2ProjectDetail.tsx`；同步 `.gitignore`、README、扩展指南、导演台流程快照及 `docs/design-ref-director/smart-edit-ui-20261024/`。
- 验证命令：`pnpm --dir frontend build`（含前端测试、TypeScript、清理与构建）；`python -X utf8 -m unittest backend.tests.test_smart_edit backend.tests.test_editing_assistant -q`；真实 5173 + 隔离 SQLite 后端的桌面浅暗交互、三个宽度、控件 / 弹层截图、对比度与原图几何检查。最终数量、原图摘要、截图元数据和已知差异见[验收报告](design-ref-director/smart-edit-ui-20261024/ACCEPTANCE.md)。
- 回滚方式：只逆向撤回本节所述文件中的本轮 UI 增量，恢复原工程图标栏、固定属性栏与助手分组展示后重新构建；不整文件或整目录 checkout，不覆盖用户原有未提交改动。无需数据库回滚或工作流迁移，现有剪辑文档继续可读。

## 2026-10-24 无限画布 V4.9（上传封面裁切）（新增当前基线）

- 日期与原因：2026-10-24。V4.8 上传本地图片只能整图压缩，无法去掉无关边缘或按视频画幅取景。本轮在文件选择与压缩之间加入裁切弹窗，先按比例与缩放确定取景，再只压缩裁切区域；仍为纯前端几何与 Canvas 2D，不改草稿字段、接口、表结构或依赖。
- 当前基线：
  - `frontend/src/canvas/canvas-cover.ts`：新增 `CANVAS_COVER_CROP_MAX_ZOOM = 4`、`CanvasCoverCropAspect`（`original | 16:9 | 9:16 | 1:1`）、源图像素坐标的 `CanvasCoverCropRect` 与归一化 `CanvasCoverFocus`。`canvasCoverAspectRatio` 解析预设，`original` 使用图片真实宽高比；`canvasCoverCropRect` 先取比例内最大可用框，再按 1–4x 与焦点缩小，焦点越界自动贴边；`canvasCoverCropFocus` / `moveCanvasCoverCropFocus` 在焦点与屏幕拖拽位移间换算，位移按 `stageWidth / crop.width` 折回源图像素。
  - `canvasCoverFromFile(file, crop?)` 增加可选裁切区域：合法裁切用 9 参数 `drawImage` 只绘制选区后压缩；裁切越界时收敛到图片范围，完全无效则回退整图压缩。输出仍为 ≤64,000 字符 JPEG data URL，长边 320/240/200 px 三档质量回退，`time` 固定为 0。
  - 新增 `frontend/src/canvas/CanvasCoverCropModal.tsx`：Ant Design `Modal`（宽 560、标题「裁切封面」、确认「应用裁切」、`destroyOnHidden`），每次打开重置为原始比例、1x、居中焦点。舞台长边 360 px，图片按裁切框等比定位并叠加三分线；`Segmented` 提供原始/16:9/9:16/1:1，`Slider` 提供 1–4x（步进 0.05），「重置取景」恢复 1x 居中。支持指针捕获拖动、方向键 8 px / `Shift` 24 px；摘要显示源图裁切尺寸与 320 px 内输出尺寸；加载中显示 Spin，图片读取失败显示错误并禁用应用。
  - `CanvasInspector.tsx`：「上传封面」选择文件后先校验图片类型与 16 MB 上限，再打开裁切弹窗；应用时以 `canvasCoverFromFile(file, crop)` 得到封面，经既有 `onUpdateCover` 写入 `cover`、`coverSource = videoUrl`、`coverTime: undefined`，成功后提示「已裁切并写入封面」并清空草稿文件；取消或关闭不修改现有封面。`canvas.css` 增加 `.canvas-cover-crop-*` 弹窗、舞台与控件样式，沿用 `--studio-*` 语义变量。
  - 裁切几何在应用前一次完成，结果仍是普通封面 data URL；节点缩略图、列表卡片、预览 poster、PNG 导出与服务端 `_preview_cover` 全部沿用现有链路，无需感知裁切。
- 受影响文件：新增 `frontend/src/canvas/CanvasCoverCropModal.tsx`；修改 `frontend/src/canvas/{canvas-cover.ts,canvas-cover.test.ts,CanvasInspector.tsx,canvas.css}`；同步 `docs/无限画布开发计划.md`、本文件、`README.md`、`功能说明与扩展指南.md`。未新增后端文件、API、数据库表/列、依赖或 `schemaVersion` 字段；服务端预览摘要与 48 KB 预算不变。
- 兼容性：`cover`/`coverSource`/`coverTime` 格式与语义不变，旧封面无需迁移；裁切只影响新上传的图片，取消弹窗或图片读取失败保持原封面。封面仍计入画布 8 MB 上限，手动裁切仍走仅封面变更判定，不进入撤销栈。裁切只支持固定比例与 1–4x 缩放，不提供自由画幅、旋转或输出分辨率选择；结果统一压缩为 320 px 内 JPEG，透明 PNG 仍转为无透明 JPEG。
- 验证命令：`pnpm --dir frontend test`（60 个文件、407 项通过，其中画布 121 项：封面 10、模型 44、导出 12、保存 12、生成 27、管理 16）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_canvas_store backend.tests.test_library_query -q`（画布 18 项、作品库 10 项通过）。隔离 SQLite 后端 7866 托管生产构建 + 无头 Chrome 桌面验收：1200×800 图片原始比例裁切 1200×800、输出 320×213；16:9 裁切 1200×675、输出 320×180；9:16 裁切 450×800、输出 180×320，2x 时裁切 225×400、舞台 202.5×360；1:1 裁切 400×400、舞台 360×360、输出 320×320；4 次方向键累计位移 40 px、5 段拖动累计 50 px；应用得到 10,859 字符、实际 320×320 的 JPEG（显示 11 KB），草稿 v4 保存后重载封面保留、`preview_json` 视频项含同长度封面、预览 poster 生效、撤销保持禁用；取消后重开恢复原始/1x 且原封面不变；非图片提示「请选择图片文件」、超大文件提示「封面图片需小于 16 MB」；浅暗主题正常，控制台无报错。
- 验收边界：验收图片在页面内用 canvas 生成，隔离后端数据只写入 `.tmp/canvas-cover-acceptance`，结束后后端已停止、临时目录已删除；未访问生产账号、未切换 ComfyUI、未提交生成任务。
- 回滚方式：移除 `CanvasCoverCropModal` 渲染与「上传封面」的裁切入口，恢复 `canvasCoverFromFile(file)` 整图压缩调用，再删除弹窗组件、裁切几何函数、测试与 `.canvas-cover-crop-*` 样式即可；已生成封面仍是普通 data URL，无需数据库迁移或清理。

## 2026-10-24 无限画布 V4.8（自定义视频封面）（新增当前基线）

- 日期与原因：2026-10-24。V4.7 只能自动取视频开头一帧，片头黑场或空白时封面不可用，用户也无法为视频指定代表帧或使用本地图片。本轮在现有封面字段上增加显式时间取帧与本地图片上传，保持纯前端、`schemaVersion: 2` 与现有 API/表结构不变。
- 当前基线：
  - `frontend/src/canvas/canvas-cover.ts`：新增 `clampCanvasCoverTime(time, duration)` 把请求时间夹取到 `[0, duration]`；`captureCanvasCoverFromVideo` 对显式时间同样先夹取，返回实际取帧时间。取帧缓存键从 `url` 改为 `url#time`，同地址不同时间互不覆盖；`forgetCanvasCoverCapture(url)` 删除该地址全部时间缓存。
  - 新增 `canvasCoverFromFile(file)`：只接受图片且 ≤`CANVAS_COVER_FILE_MAX_BYTES`（16 MB），读取后用 2D canvas 按 320/240/200 px 长边与逐档 JPEG 质量压缩，返回不超过 64,000 字符的 `data:image/jpeg`，全部尝试失败返回 `null`。
  - `CanvasInspector.tsx`：「封面帧」区域新增取帧时间 `InputNumber`（`min=0`、`step=0.1`、`precision=2`，`aria-label=封面取帧时间（秒）`）、「按时间取帧」「上传封面」「自动取帧」与隐藏文件输入；摘要显示实际取帧时间与大小，上传封面不显示时间，底部提示上传会压缩为 320 px JPEG 且封面改动不进入撤销栈。
  - `CanvasNodes.tsx` 自动取帧仍写入 `cover/coverSource/coverTime`；`canvas-model.ts` 新增共享类型 `CanvasCoverPatch = Pick<CanvasNodeData, "cover" | "coverSource" | "coverTime">`。`CanvasEditor.tsx` 的 `updateNodeCover` 统一接收 patch，先置 `coverOnlyChangeRef` 再写节点数据；`CanvasSidePanel.tsx` 把 `onUpdateCover` 透传到检查器。
  - 撤销隔离：检查器的手动取帧、上传封面、清除封面与节点自动取帧全部经 `onUpdateCover` 进入 `isCoverOnlyCanvasChange` 判定，不再直接 `updateNodeData`。仅封面变更仍触发自动保存但不进入撤销/重做历史，修复了 V4.7 中手动封面编辑会污染撤销栈的问题。
  - 视频地址变化或作品库替换仍清空三个封面字段；选择「自动取帧」或「重新截取」时清除当前地址全部时间缓存，由节点 effect 重新取开头帧。
- 受影响文件：修改 `frontend/src/canvas/{canvas-cover.ts,canvas-cover.test.ts,CanvasInspector.tsx,CanvasNodes.tsx,CanvasEditor.tsx,CanvasSidePanel.tsx,canvas-model.ts,canvas.css}`；同步 `docs/无限画布开发计划.md`、本文件、`README.md`、`功能说明与扩展指南.md`。未新增后端文件、数据库表/列、API、依赖或 `schemaVersion` 字段；服务端预览校验与 48 KB 摘要预算不变。
- 兼容性：`cover`/`coverSource`/`coverTime` 仍为可选字段，只接受 `coverSource === url` 的封面；上传封面同样写入当前视频地址，因此旧前端、列表缩略图、预览 poster、PNG 导出与服务端 `_preview_cover` 无需改动即可识别。显式时间跳转依赖媒体服务支持 HTTP Range 与 CORS；不支持 Range 时浏览器只能停在开头帧，不影响自动取帧与上传封面。
- 验证命令：`pnpm --dir frontend test`（60 个文件、404 项通过，其中画布 118 项：封面 7、模型 44、导出 12、保存 12、生成 27、管理 16）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_canvas_store backend.tests.test_library_query -q`（画布 18 项、作品库 10 项通过）。隔离 SQLite 后端 7866 + 支持 Range/CORS 的本地媒体服务 7870 + Vite 代理 5174 桌面验收：2.334 秒视频在 1.5 秒取帧得到 16,287 字符封面并显示「取帧 1.5 秒 · 16 KB」；请求 3 秒夹取到 2.28 秒；本地上传 PNG 得到 5,343 字符封面且 `coverTime` 清空；「自动取帧」恢复 0.23 秒封面；手动取帧 1.2 秒后撤销保持禁用，改标签后撤销启用，撤销恢复标签且草稿 v14 仍保留 1.2 秒、16,819 字符封面，`preview_json` 含同长度封面；暗色主题下控件对比度正常。
- 验收边界：测试视频与上传图只存在于 `.tmp/` 隔离目录，验证后媒体服务、隔离后端、代理与临时数据均已停止并清理；未访问生产账号、未切换 ComfyUI、未提交生成任务。
- 回滚方式：移除检查器的时间输入、上传与「自动取帧」入口，恢复 V4.7 的 `captureCanvasCoverFromVideo` 缓存键与 `updateNodeData` 直写即可；`cover/coverSource/coverTime` 字段和既有封面数据继续兼容，无需数据库迁移或清理。回滚后手动封面编辑将重新绕过撤销隔离，需同时保留 `CanvasCoverPatch`/`onUpdateCover` 修复或接受该退化。

## 2026-10-24 无限画布 V4.7（视频封面帧）（新增当前基线）

- 日期与原因：2026-10-24。此前视频节点、画布列表缩略图和 PNG 导出只能显示类型色与播放标记，无法看出视频内容；本轮在浏览器端自动截取视频首帧作为封面，随画布草稿持久化，并复用到节点、检查器、列表与导出。纯前端取帧与摘要扩展，不新增 API、数据表、依赖或 `schemaVersion`。
- 当前基线：
  - 新增 `frontend/src/canvas/canvas-cover.ts`：`captureCanvasCoverFromVideo` 使用离屏 `<video crossOrigin="anonymous" preload="auto" muted playsinline>` 加载地址，等待 `loadeddata` 后 seek 到 `coverTime`，以长边 320 px 绘制到 2D canvas，输出 JPEG 质量 0.66；结果必须匹配 `data:image/jpeg` 且 ≤64,000 字符。10 秒超时、跨域污染或编码失败返回 `null`，不阻塞节点。
  - `requestCanvasCoverCapture(url)` 按地址复用 Promise 缓存（最多 40 条，超出按插入顺序淘汰）；`forgetCanvasCoverCapture(url)` 供「重新截取」清除该地址缓存。`readCanvasCover`、`canvasCoverSummary`、`canvasCoverFrameSize`、`normalizeCanvasCover` 负责读取、摘要与尺寸校验。
  - 视频节点 `data` 增加可选 `cover`（data URL）、`coverSource`（取帧时视频地址）与 `coverTime`（秒）；仅 `coverSource === url` 时使用。`CanvasNodes.tsx` 在节点已有 `url`、缺少封面时自动取帧并写回；`<video poster>` 与预览弹层使用该封面。
  - `CanvasInspector.tsx` 新增「封面帧」区块：96×54 缩略图、大小与取帧时间、「重新截取」；修改视频地址或从作品库替换会清空三个封面字段并重新取帧；预览按钮传入 `poster`。
  - 撤销栈：`canvas-model.ts` 的 `isCoverOnlyCanvasChange` 在序列化比较前剔除 `cover/coverSource/coverTime`，`CanvasEditor.tsx` 在自动取帧写入时标记并通过该判定跳过历史入栈；移动、改标签等其它变化仍正常进入撤销栈。
  - 列表缩略图：`CanvasPreviewThumbnail.tsx` 对视频项优先用 `<image>` + `clipPath` 裁剪绘制 `cover`，再叠加播放标记；无封面时沿用类型色。
  - 服务端 `canvas_store.py`：`_preview_cover` 只接受视频节点、`coverSource === data.url`、安全 `url`、≤64,000 字符且匹配 `data:image/(jpeg|webp|png);base64,...` 的封面；每个摘要最多 3 张封面、封面总预算 36 KB。`_fit_canvas_preview` 的摘要上限由 16 KB 提升到 48 KB（低于 MySQL `TEXT` 64 KB），超限时先移除封面（从最后一张开始），再清空 URL、连线与节点形状；解码 `decode_canvas_preview` 对封面做同样过滤。
  - `CanvasPreviewItem`（`backend/app/models.py`）增加可选 `cover`；PNG 导出 `canvas-export.ts` 把封面加入视频节点的图片候选，`canvas-export-render.ts` 在视频卡片中绘制封面并保留播放标记。
- 受影响文件：新增 `frontend/src/canvas/{canvas-cover.ts,canvas-cover.test.ts}`；修改 `frontend/src/canvas/{CanvasNodes.tsx,CanvasEditor.tsx,CanvasInspector.tsx,CanvasPreviewThumbnail.tsx,canvas-export.ts,canvas-model.ts,canvas-model.test.ts,canvas-export.test.ts,canvas.css}`、`backend/app/{canvas_store.py,models.py}`、`backend/tests/test_canvas_store.py`；同步 `docs/无限画布开发计划.md`、本文件、`README.md`、`功能说明与扩展指南.md`。未改数据库表/列、API、任务系统、工作流注册表或依赖。
- 兼容性：`schemaVersion` 保持 2，封面字段全部可选，旧前端忽略未知字段、旧画布无封面时照常显示占位；服务端预览摘要上限提升只影响 `preview_json`，历史版本与草稿校验和不含摘要。封面为客户端压缩图，不是原视频帧的像素级副本；跨域视频需目标服务器返回 CORS 头，否则自动降级且不报错。封面数据计入画布 8 MB 上限。
- 验证命令：`pnpm --dir frontend test`（60 个文件、397 项通过，其中画布 111 项：封面 5、模型 43、导出 12、保存 8、生成 27、管理 16）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_canvas_store backend.tests.test_library_query -q`（画布 18 项、作品库 10 项通过）。隔离 SQLite 后端 7866 托管生产构建 + 本地 CORS 媒体服务 7870 + 无头 Chrome 桌面验收：视频加载后自动生成 15,399 字符封面，`coverSource` 与地址一致、`coverTime=0`，节点 `poster` 生效；保存后 `preview_json` 含封面且总大小 15,635 字节，列表卡片渲染真实视频帧；检查器显示封面与「重新截取」，重截后自动保存且撤销保持禁用；重载后封面与禁用撤销状态保持；预览 poster 生效；浅暗主题正常，控制台无消息。
- 验收边界：示例视频由 `.tmp/` 下的本地 CORS 服务提供，仅用于隔离验收，验证后媒体服务、后端与临时目录均已停止并清理；未访问生产账号、未切换 ComfyUI、未提交生成任务。
- 回滚方式：移除节点/检查器/缩略图/导出的封面接线并删除 `canvas-cover.ts` 及其测试，服务端恢复 `PREVIEW_MAX_BYTES=16*1024`、移除 `_preview_cover` 与 `cover` 解码即可；旧草稿中的封面字段会被前端忽略、被服务端原样保留，无需迁移或清理数据。

## 2026-10-24 无限画布 V4.6（作品库分页检索）（新增当前基线）

- 日期与原因：2026-10-24。画布素材 Drawer 与「加入画布」此前都读取旧 `GET /api/library` 的全量数组，前端过滤并只显示前 80 项；作品库增长后首屏变慢，较旧的素材也无法被找到或插入。本轮增加服务端分页检索接口，旧接口保持兼容，不改画布草稿、任务表或存储协议。
- 当前基线：
  - `backend/app/library_query.py`：`build_library_entries` 把任务的轮次、生成项与输出扁平化为作品库条目，保留 `kind/path/label/delivery_status/download_url/job_id/generation_item_id/output_index/job_title/created_at`，并生成内部 `_search_text`；`query_library_entries` 排除 `delivery_status` 为 `local`/`expired` 的条目，支持大小写不敏感的标题/提示词/标签/路径/任务号包含匹配、`kind` 过滤、精确 `job_id`/`generation_item_id`/`output_index`、按 `created_at` 稳定倒序，并在返回前去掉 `_` 前缀内部字段。
  - `GET /api/library/query`（`backend/app/main.py`）：`q` 最长 100 字符，`kind` 仅 `image|video`，`limit` 默认 40、范围 1–100，`offset` 0–1,000,000，`job_id`/`generation_item_id` 最长 120，`output_index` 0–999；管理员可传 `user_id`（`all` 表示全部），普通用户始终限定本人。响应为 `{items,total,limit,offset,has_more,counts}`，`counts` 在 `kind` 过滤前统计，保证两个分类标签都有总数。
  - `GET /api/library`：改为复用 `build_library_entries`，保持数组响应，仅新增 `job_title` 字段；仍按账号最近 500 个任务生成，供旧调用方兼容。
  - `backend/app/models.py`：新增 `LibraryQueryCounts`、`LibraryQueryResponse`，并给 `LibraryItemResponse` 补 `job_title`，避免 FastAPI 响应模型裁剪字段。
  - 前端 `CanvasEditor.tsx`：素材 Drawer 用 `useInfiniteQuery` 每页 40 项、按 `kind` 与 300ms 防抖后的搜索词分页；图片/视频 Segmented 显示服务端计数，底部显示「已加载 X / Y」与「加载更多」；跨页按 `job:item:index` 去重。关闭 Drawer 清空搜索。`addJob/addItem/addOutput` 跳转改为精确筛选 `limit=1` 的独立查询，命中且可用才插入，插入一次后清理 URL 参数。
  - 前端 `canvas-api.ts` 提供 `queryCanvasLibraryItems`；`canvas-manage.ts` 提供 `canvasLibraryQueryString`（边界收敛与编码）与 `mergeCanvasLibraryItems`（跨页去重）。
- 受影响文件：新增 `backend/app/library_query.py`、`backend/tests/test_library_query.py`；修改 `backend/app/{main.py,models.py,api_documentation.py}`、`frontend/src/canvas/{CanvasEditor.tsx,canvas-api.ts,canvas-manage.ts,canvas-manage.test.ts,canvas-model.ts,canvas.css}`；同步 `docs/无限画布开发计划.md`、本文件、`README.md`、`功能说明与扩展指南.md` 与 `docs/API.md`。未新增数据库表/列、未改 `schemaVersion`、任务系统或工作流注册表。
- 兼容性：旧 `/api/library` 仍返回数组且字段只增不减，旧前端可继续使用；新接口是加法路由，不改既有画布 API。检索为字符串包含匹配（大小写不敏感），不做分词；分页基于账号最近 500 个任务的已加载快照，更早任务的产物可能不在结果中。`local`/`expired` 产物在服务端统一排除，与旧画布过滤语义一致。
- 验证命令：`pnpm --dir frontend test`（59 个文件、388 项通过，其中画布 102 项、画布管理 16 项）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_library_query backend.tests.test_canvas_store -q`（作品库 10 项、画布 14 项通过）。隔离 SQLite 后端 7866 + 临时 Vite 5174 桌面验收：图片 55 / 视频 8 计数、首屏 40/55、加载更多 55/55、搜索「灯塔」1/1、「产品展示」图片 5/视频 8、视频页 8/8、不可用产物不出现；旧接口返回 68 项数组并含 `job_title`；精确插入最旧素材 `seed-img-059.png` 成功；浅暗主题正常，控制台无报错。
- 验收边界：种子任务与图片只写入 `.tmp/` 隔离数据目录，验证后已清理；未访问生产账号、未切换 ComfyUI、未提交生成任务。
- 回滚方式：删除 `/api/library/query` 路由与 `library_query.py`，移除 `LibraryQueryCounts`/`LibraryQueryResponse` 与前端分页查询，恢复 Drawer 使用旧 `listCanvasLibraryItems` 即可；旧接口与既有数据无需迁移，已插入画布的内容不受影响。

## 2026-10-24 无限画布 V4.5（PNG 导出）

- 日期与原因：2026-10-24。画布此前只能导出 JSON，无法直接交付预览图。html-to-image 一类方案需处理跨域媒体且大画布成本高，服务端渲染需无头浏览器与队列；本次采用无依赖的客户端 Canvas 2D 导出，保留纯前端边界，不改后端与数据协议。
- 当前基线：
  - 编辑器「更多」菜单新增「导出 PNG」，弹窗位于 `frontend/src/canvas/CanvasExportDialog.tsx`：范围可选整个画布或选中节点，背景可选浅色/深色/透明，倍率可选 1x/2x；默认背景随当前主题（浅色主题默认浅色，暗色主题默认深色），倍率默认 2x，切换时实时重绘预览并显示输出像素、百万像素与自动降采样提示。
  - `frontend/src/canvas/canvas-export.ts` 为纯函数场景构建：包围盒取包含节点的最小外接矩形并加 48px 留白；画板始终先绘制，其余按 zIndex 与原始顺序；只导出可见节点与可见连线，丢弃自环、悬空边和非选中范围的跨界连线；生成提示词优先合并相连文字节点（按连线顺序），无来源时回退手动提示词；生成节点只导出当前选中结果版本；图片候选优先同源 `/api/media/{encodeURIComponent(assetPath)}`，其次安全原 URL，并去重。
  - `frontend/src/canvas/canvas-export-render.ts` 负责离屏绘制与图片加载：背景色浅色 `#f8f9fa`、深色 `#0f1115`，透明模式不填充；节点沿用编辑器类型色板；图片按 cover 裁切，视频绘制播放标记，生成节点绘制状态、提示词与结果，未知节点绘制虚线卡；图片请求 `crossOrigin=anonymous`（data URL 除外），10 秒超时或失败时绘制占位，避免污染画布导致 `toBlob` 失败。
  - 安全边界：单边上限 8192 px、总像素上限 2400 万、倍率上限 3、下限 0.01；请求倍率超限时自动降采样并把实际倍率写回场景，弹窗提示降采样。文件名清洗 `[\\/:*?"<>|\s]+ → _`、截断 60 字符，格式 `${标题}-YYYYMMDD-HHmm.png`，空标题回退 `canvas`。
  - 预览固定按 760×520 上限等比缩放，不放大；导出时才按实际倍率绘制。导出成功提示「PNG 已导出」并关闭弹窗。
- 受影响文件：新增 `frontend/src/canvas/{canvas-export.ts,canvas-export-render.ts,CanvasExportDialog.tsx,canvas-export.test.ts}`；修改 `frontend/src/canvas/{CanvasEditor.tsx,canvas-fidelity.css}`；同步 `docs/无限画布开发计划.md`、本文件、`README.md`、`功能说明与扩展指南.md`。未改后端、数据库、API、任务系统、工作流注册表或草稿 schema。
- 兼容性：导出只读取当前已加载的节点/边与生成节点状态，不写回草稿，不触发自动保存，不创建任务；关闭弹窗无副作用。旧画布与未知节点类型可正常导出（未知节点按通用卡片绘制）。导入 JSON、自动保存、版本历史、缩略图与任务追溯均不受影响。
- 验证命令：`pnpm --dir frontend test`（59 个文件、386 项通过，其中画布 100 项、导出 11 项）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend build`（通过）；`python -X utf8 -m unittest backend.tests.test_canvas_store -q`（14 项通过）。隔离 SQLite 后端 7866 + FastAPI 静态入口 7866 桌面浏览器验收：浅色 2x 输出 2152×1512、四角 `#f8f9fa`；深色 1x 输出 1076×756、四角 `#0f1115`；选中两个节点透明 2x 输出 1440×572、RGBA alpha 0–255；暗色主题 2x 使用深色画布与深色卡；文件名与时间戳正确，刷新后 6 节点草稿仍为已保存，控制台无报错。
- 验收边界：示例画布由临时脚本生成，仅存放于 `.tmp/` 并在验证后清理，不进入源码或数据库。当前使用隔离 SQLite 与静态构建，不访问生产账号、不切换 ComfyUI、不提交生成任务。跨域且未开 CORS 的图片在导出中以占位呈现，这是浏览器的画布安全限制，不是接口故障。
- 回滚方式：删除导出菜单项与 `CanvasExportDialog` 渲染，移除上述新增文件与 `canvas-fidelity.css` 中的 `.canvas-export-*` 样式即可；不改数据库、接口或草稿，无需迁移或清理。

## 2026-10-24 导演台内部控件与设计细节校准

- 原因：复核发现首页主按钮偏小、内容库按钮组偏上、搜索筛选栏右移，沿用原设计图校准字号、尺寸、图标和间距。
- 文件：`frontend/src/director2/director-home.css`、`project-detail.css`、`panes/content-library.css`、`Director2ProjectDetail.tsx`；同步 README、扩展指南、流程快照与设计验收产物。
- 基线：主页 CTA 212×52px，搜索宽 200px；内容库主按钮 174×48px，1505 基线 y=597；项目模式 208×58px、主题按钮 40px、菜单高 50px。首页最大几何偏差 3.75px、项目 16.5px，保留导航 76px 与内容组数学居中的已声明差异。
- 兼容：只有样式与导航文档图标变化，没有新增依赖、API、数据库、路由、业务状态或工作流协议。继承根级双主题，对话创作室官方 token 不变。
- 验证：`pnpm --dir frontend build`（60 文件 / 397 测试、类型检查、构建通过）；`python -X utf8 -m unittest backend.tests.test_director_project_info backend.tests.test_director2_ai_generation -q`（51 项通过）。真实 5173 页面 12 张桌面浅暗截图，本轮 198 项检查通过；没有提交生成或转写任务。
- 回滚：只逆向撤回上述四文件的本轮 UI 增量后构建，保留用户已有修改与历史数据；无需迁移。临时账号、会话和工程已清理。完整证据见[细节验收](design-ref-director/ui-20261023/details-20261024/REPORT.md)。

## 2026-10-23 导演台桌面 UI 设计还原

- 日期与原因：2026-10-23。导演台主入口占高较多、工程卡片信息层级接近，项目重复顶栏挤占工作空间。本轮先用真实 5173 截图与流程快照生成首页、内容库设计图，再在现有组件中还原。
- 当前基线：首页一层 64px 顶栏、主次入口、剧本诊断条和三列工程卡；项目一层 80px 顶栏、226px 工程导航、内容库的实色导入按钮与空态。全局 76px 导航保持既有尺寸。主题由根 Provider / Ant Design / `--studio-*` 继承；资产库 / 工坊 / 全部任务的中性色与表面也改为现有语义变量，消除暗色白底和深色标题；媒体预览仍为近黑底。智能剪辑素材标题与操作区允许自然换行，标题本身保持单行，解决助手停靠时的控件裁切。对话创作室 `--director-*` 和官方 beautifului 组件设计不变。
- 前端状态增量：`Director2StudioHome` 增加仅当前挂载期间的搜索文本与加载失败状态；`filterHomeProjects(items, filter, query = "")` 支持大小写不敏感的名称 / 简介查询，始终与类型过滤组合，保留服务器更新时间顺序。筛选或搜索时收起「查看全部」，空搜索结果可清空恢复；加载失败明确显示重试。没有新增持久化、API、数据库、路由或工作流映射。
- 项目条移除原始 ID 和固定「进行中」标记（该标记没有任务依据），保留真实名称与基本信息编辑；原五项菜单使用语义按钮、`aria-current` 与焦点环。工坊两处 loading 表达式补齐可空 `refineAction` 防护，避免已有类型错误阻塞完整构建，不改变精修行为。
- 受影响文件：`frontend/src/director2/{Director2StudioHome.tsx,director-home.css,home-projects.ts,home-projects.test.ts,Director2App.tsx,Director2ProjectDetail.tsx,director2.css,project-detail.css,panes/ContentLibraryPane.tsx,panes/content-library.css,panes/assets-library.css,panes/jobs-center.css,panes/episode-workshop.css,panes/EpisodeWorkshopPane.tsx,workshop-video-progress.test.ts,smart-edit/smart-edit.css}`；另同步当前画布节点默认宽度的既有测试断言 `frontend/src/canvas/canvas-model.test.ts`；`.gitignore`、本文件、README、扩展指南、导演台流程快照与 `docs/design-ref-director/ui-20261023/`。
- 兼容性：保留现有项目、配方、AI / 手动模式、用户主题、助手会话和全部业务入口。搜索是客户端视图状态；旧调用不传 query 保持原结果。无数据库迁移，无新增依赖，不触发模型生成、不更改供应商。
- 验证命令：`pnpm --dir frontend build`；`python -X utf8 -m unittest backend.tests.test_director_project_info backend.tests.test_director2_ai_generation -q`。真实 5173 页面通过 Playwright 采集相同 1505×1045 / DPR 1 的设计对照及 1440×1000、1920×1080 两种桌面浅暗状态，操作和偏差报告见[验收记录](design-ref-director/ui-20261023/ACCEPTANCE.md)。
- 回滚方式：只逆向撤回本轮上述 UI 增量，保留用户原有未提交代码与历史数据；重新构建即可恢复生产静态包，无需修改数据库、端口或工作流。保留工坊可空判断也可独立回滚。

2026-10-23 FFmpeg 本地工程互通补充：`frontend/src/director2/smart-edit/model.ts` 的 `parseDocument` 接受与后端相同格式的 `/api/local-media/[A-Za-z0-9_-]{4,2048}.[0-9a-f]{32}` 引用；后端仍验证签名、实际路径和权限，前端不接受 `file:`、裸路径或无签名引用。修复此前服务端已能引用本机素材但 JSON 导入/快照读取被前端拒绝的问题。`model.test.ts` 覆盖本机工程往返和非法路径；无数据库及 API 协议变化，可单独回退该校验分支。外部 Skill 使用本机原生序列化器保存工程，不写数据库或绕过 OAuth。

## 2026-10-24 无限画布原图校准与自动截图验收

- 日期与原因：2026-10-24。用户要求按已生成的原图还原，并在自动截图验证后才通过视觉验收。本次补齐精确尺寸、节点内联表单、连接点、菜单与弹窗细节；接口与数据基线继续包含当前 V4.5–V4.7 能力。
- 当前视觉基线：命令栏 64px；58px 工具轨、226×327px 添加菜单、360px 属性面板、375×49px 视图栏、174×101px 小地图。全局顶栏与左侧导航自 2026-10-28 / 2026-10-31 起与全工作区共用（48px 悬浮 Header、76px 图标栏），本段 60px / 86px 为 2026-10-24 验收状态。`canvas-fidelity.css` 只扩展画布语义变量和主题样式；浅暗主题仍由根 Provider 驱动。原图保持不变，截图与测量记录在 `docs/design-ref-canvas/`。
- 前端状态：画布设置可临时固定显示，不清除节点选择，浮动工具条因此可与画布设置共存；点击节点切回节点属性。生成节点内联 Select 读取实际 `/api/modes`，与检查器共用 `canvasWorkflowChangePatch`，切换工作流清除旧任务/结果并保留提示词与冻结运行快照。来源 Tag 可断开文字或图片连线，走既有撤销与保存链路。精简模式的已连接端口随可见边显示，输入端口颜色跟随来源。
- 尺寸与兼容性：新建生成节点默认 356×446；已有草稿尺寸不回写，旧 316×240 节点通过内部滚动保留操作按钮。新增前端文字端口 `prompt`，原 `in` 保留；旧草稿无需迁移。`schemaVersion 2`、API、表结构、任务队列、ComfyUI graph 节点 ID 与供应商配置没有因本次视觉校准改变。后续 PNG 导出、素材分页与视频封面代码保留。
- 细节补齐：Ant Design 弹层继承根主题；缩放菜单选中文字浅/暗对比度分别为 4.60/7.07，暗色节点类型图标改用深色前景；素材 Drawer 顶部对齐 60px 顶栏，搜索和分页固定于面板，网格独立滚动，避免正文和网格双重滚动。原图计数、字数等示意内容不覆盖真实业务状态。
- 受影响文件：本轮 `frontend/src/App.tsx`、`frontend/src/components/ThemeToggle.tsx`，`frontend/src/canvas/{CanvasWorkspace.tsx,CanvasEditor.tsx,CanvasNodes.tsx,CanvasSidePanel.tsx,CanvasGeneratorInspector.tsx,CanvasExportDialog.tsx,canvas-generation.ts,canvas-generation.test.ts,canvas-model.ts,canvas-model.test.ts,canvas-fidelity.css}`；同步 README、扩展指南、画布开发计划与设计验收记录。原 V4.4 的 `canvas.css` 和检查器细节继续保留，不覆盖 V4.5–V4.7 的后续增量。
- 验证命令：`pnpm --dir frontend build`（60 文件/397 项、类型检查、清理及构建通过）；`python -X utf8 -m unittest backend.tests.test_canvas_store -q`（18 项通过）。真实 5173 + 隔离 7866 SQLite 自动采集 21 区域，外框最大偏差 2 CSS px；浅暗 42 个控件和面板截图，基础 77 项交互断言、PNG/素材检索分页补充检查、旧尺寸节点和对比度检查通过；桌面 1440×900、1586×992、1920×1080，未做移动端检查。原图摘要、截图元数据与差异图见 `docs/design-ref-canvas/FIDELITY.md`，未触发生成任务。
- 回滚方式：只逆向撤回上述文件中本轮增量，不执行整目录恢复，不删除用户原有或 V4.5–V4.7 改动。撤回节点默认尺寸仅影响后续新建；已保存尺寸保留。若回到没有 `prompt` 端口的旧渲染器，需将新增文字连线端口恢复到 `in` 后才在旧界面显示；边数据本身保留。无需数据库回滚。

## 2026-10-23 无限画布 V4.4（设计稿还原与控件细节）

- 日期与原因：2026-10-23。用户要求先出设计图再还原，并逐项打磨小控件与弹窗。本轮保留既有画布能力，用内置 imagegen 的浅色设计稿作为基线，在原 React / Ant Design / React Flow 架构中实现，补齐暗色与桌面交互。
- 当前基线：64px 画布命令栏、48px 悬浮工具轨、12px 内边距的悬浮属性面板、300×42px 缩放栏；属性/图层/历史显示图标，素材入口固定在面板底部。节点新增类型标识、可读标题和说明，文字及生成提示词改用 Ant Design TextArea，画板名称改用 Input。位置尺寸与 ID 位于折叠区；原节点尺寸和草稿继续读取。
- 细节与行为：添加菜单带图标、说明与键帽；缩放菜单提供 25–200% 六个预设；十个视角收进浮层（1–9、0），空位点击保存、已存点击跳转、右键清除，`Shift+数字` 使用物理键码，避免 `!/@` 等符号导致保存失败。图片地址弹窗提供行内错误、辅助文本关联和禁用提交；新建/标签/导入/预览弹窗、下拉与确认浮层统一间距和圆角，取消双字按钮自动插空格，局部 Provider 加中文语言包。Modal、素材 Drawer、预览和导入确认打开时屏蔽底层画布快捷键。
- 主题与兼容：局部 ConfigProvider 仅继承根级主题并调整组件 token，不维护独立主题状态；类型色、点阵与阴影通过成对的 `--canvas-*` 补充变量提供。没有新增依赖、路由、API、数据列、工作流参数或持久化字段，`schemaVersion 2`、版本历史、自动保存与任务来源保持兼容，无需迁移。工作流与模型信息继续来自注册表；不把设计图示例写入业务。
- 受影响文件：`frontend/src/canvas/{CanvasWorkspace.tsx,CanvasEditor.tsx,CanvasNodes.tsx,CanvasSidePanel.tsx,CanvasGeneratorInspector.tsx,CanvasInspector.tsx,canvas.css}`；新增设计与截图档案 `docs/design-ref-canvas/`，同步本文件、README、扩展指南和无限画布开发计划。
- 验证命令：`pnpm --dir frontend build`（58 个测试文件、371 项、类型检查与 Vite 构建通过）；`python -X utf8 -m unittest backend.tests.test_canvas_store -q`（14 项通过）。真实 5173 + 隔离 SQLite 后端验收 28 个主要状态与补充交互，检查 1440×900、1586×992、1920×1080 桌面浅暗主题；节点保存刷新、菜单边界、JSON 导入取消、视角 0、Shift+1、弹窗快捷键隔离、全局提示词继承均正常。参考图与真实截图完成 URL/标题、DPR、字体、图片、视口与四个布局锚点核对；控件细节图为真实页面截图排版。仅有既有 List 弃用与构建大分块提示。
- 验收边界：测试浏览器仍打开 5173，仅将其 API 请求转发到隔离后端，连通性状态为验收桩；没有访问生产账号数据、切换供应商、启动 ComfyUI 或提交生成任务。示例内容不进入源码。详细设计与可接受差异见 `docs/design-ref-canvas/DESIGN.md`。
- 回滚：仅逆向撤回上列文件中本轮的界面和快捷键细节，保留已有画布模块与此前未提交改动；数据模型、`canvas-api.ts`、注册表和后端无需回退，不要整目录 checkout。

## 2026-10-23 无限画布 V4.3（结构化缩略图）（新增当前基线）

- 日期与原因：2026-10-23。画布列表长期只有占位图标，画布变多后只能靠标题、标签与保存时间辨认。客户端实时截图需要解析完整草稿、处理跨域媒体并承担大画布渲染成本；本次改为服务端在保存时生成轻量结构摘要，前端用无依赖 SVG 渲染缩略图，不新增第三方依赖、不引入无头浏览器。
- 当前基线：
  - `canvas_projects` 新增可空 `preview_json`（MySQL `TEXT NULL`、SQLite `TEXT`），通过 `JobStore._ensure_column` 幂等补列，`sql/019_canvas.sql` 同步更新；不新增表，不复制草稿内容，不改变版本历史与内容校验和。
  - `save_draft` 保存成功后从草稿节点/边重建摘要并写入 `canvas_projects`；`create_project` 写入空摘要；`restore_version` 复用 `save_draft`，恢复历史版本时同步刷新。`list_projects`/`get_project` 读取并通过 `decode_canvas_preview` 返回 `preview`，无摘要或解析失败返回 `null`。
  - 摘要结构 `{x,y,width,height,nodeCount,items,links}`：包围盒包含画板；`items` 最多 120 项，超出时按等距步长抽样并保留首尾；`links` 最多 80 条并映射到抽样后索引；媒体地址只取图片节点 `data.url` 与图片结果生成节点 `data.resultUrl`，最多 12 个、单个 768 字符，只接受 `/` 站内路径与 `http(s)`。序列化超过 16 KB 时按「清空 URL → 清空连线 → 缩减形状」降级。
  - `frontend/src/canvas/canvas-model.ts` 新增 `CanvasPreview`/`CanvasPreviewItem` 类型与 `readCanvasPreview`，对接口数据再次限流与容错；`CanvasProject.preview` 可空。
  - 新增 `frontend/src/canvas/CanvasPreviewThumbnail.tsx`：按包围盒与留白生成 `viewBox`，画板先绘制；节点按类型着色（文字紫、图片橙、视频蓝、生成绿、未知虚线），图片用 `clipPath` 裁切，视频画播放三角，文字画三条示意线，连线用三次贝塞尔曲线；SVG `aria-hidden`，不进入读屏顺序。
  - `CanvasWorkspace` 列表卡片改为纵向布局，顶部 150px 预览区；有摘要用抬升表面背景，无摘要保留原对角线占位与图标。收藏星标、悬停操作与箭头绝对定位，不遮挡预览。
  - `backend/app/models.py` 新增 `CanvasPreview`/`CanvasPreviewItem` 并给 `CanvasProjectListItem` 增加 `preview` 字段。FastAPI 会裁掉响应模型未声明的字段，此前即使存储层已返回 `preview`，列表接口也会丢失该字段；回归测试直接通过 `CanvasProjectListItem.model_validate` 覆盖此契约。
- 受影响文件：`backend/app/canvas_store.py`、`backend/app/models.py`、`backend/app/storage.py`、`sql/019_canvas.sql`、`backend/tests/test_canvas_store.py`、`frontend/src/canvas/{canvas-model.ts,CanvasWorkspace.tsx,CanvasPreviewThumbnail.tsx,canvas.css,canvas-model.test.ts}`；同步 `docs/无限画布开发计划.md`、本文件、`README.md`、`功能说明与扩展指南.md`。编辑器、任务系统、工作流注册表与 API 路径均未改动。
- 兼容性：`preview` 为可空增量字段，旧画布与新建空画布返回 `null`，列表显示原占位图标，下次保存或恢复历史版本后自动生成；旧前端忽略该字段。摘要只用于列表展示，不参与编辑器读写与内容校验，缩略图是结构示意而非像素级还原；视频不取封面。超大画布会抽样，摘要不覆盖的节点在缩略图中不出现。
- 验证命令：`pnpm --dir frontend test`（58 个文件、371 项通过，其中画布 88 项）；`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend build`（通过，`✓ built in 11.16s`）；`python -X utf8 -m unittest backend.tests.test_canvas_store -q`（14 项通过）。隔离 SQLite 后端 7866 + Vite 5174 桌面浅暗检查：保存后缩略图立即出现，负坐标包围盒、12 张图片、空画布占位、收藏/悬停布局与刷新持久化均正常，网络 200/304，控制台仅有既有表单字段警告。
- 回滚方式：停止读取 `preview` 并移除列表缩略图组件即可恢复占位图；`preview_json` 是加法列，可保留不读，不必立即删除。若需彻底回退，可在确认无旧代码运行后删除该列；不影响草稿、版本历史与任务数据。

## 2026-10-23 本地漫剧工作流 MCP 素材入口

- 日期与原因：2026-10-23。外部漫剧工作区已有按集落盘的 WorkRally 原片，需要直接接入本工作台智能剪辑，并将导出结果交回本地封面和抖音发布工作流。
- 受影响文件：`backend/app/mcp_gateway/{editing_service,routes}.py`、`backend/tests/test_local_drama_mcp.py`。新增工具复用既有 `studio:edit` OAuth scope、项目/分集服务、本机路径权限与智能剪辑版本化保存，不新增表、服务或模型。
- `studio_prepare_edit_episode(project_name, episode_code, title?, version?, script_text?)`：按准确名称选择唯一工程，必要时创建；用 `S01E09 v001 · 集名` 标识独立版本的剪辑分集。返回 `project_id/sequence_id`。同名歧义和同版本剧本冲突时报错，不覆盖旧脚本或手工时间线。
- `studio_import_edit_media(project_id, sequence_id, paths, revision, document_name?)`：只接收 1–200 个明确文件路径，依清单顺序引用。沿用本机素材权限；按 URL 复用已有素材，返回相同顺序的 `asset_ids` 供 `studio_preview_edit(video_arrange)`。保留所有现有片段，任一导入失败不保存，CAS 冲突返回 409。文件夹拒绝，避免把封面或旧成片混入原片。
- 外部约定：工作流在各剧 `02_分集制作/<集号>/04_生成素材/视频/<版本>/` 读取原片，封面在同集 `04_生成素材/图片/封面/<版本>/`，文案在 `06_后期工程/发布/`，正式 MP4 在 `03_交付成片/<集号>/待核验/`。调用既有 `studio_export_edit(output_dir=...)` 导出后由外部工作流校验归档；工作台不执行抖音发布或保存其 Cookie。
- 兼容性：现有 HTTP、MCP、前端编辑和导出协议保持兼容；无界面变更。服务器加载新代码后，MCP 客户端重新发现工具即可使用。
- 验证命令：`python -X utf8 -B -m unittest backend.tests.test_local_drama_mcp backend.tests.test_editing_assistant backend.tests.test_smart_edit`；`pnpm --dir frontend build`。外部 Skill 测试覆盖固定目录、阶段顺序、文案封面归档、可选合集、发布预演及重复发布阻止；不把模拟测试写成真实发布验收。
- 回滚：仅停用两个新增 MCP 工具及对应 EditingService 方法；不删除既有项目、剪辑、原片或导出文件。外部工作流可停用，不影响工作台原入口。

## 2026-10-23 智能剪辑 MCP 导出与本机输出目录（新增当前基线）

- 日期与原因：2026-10-23。用户询问成片保存位置，并希望 MCP 能直接控制导出目录，而不是固定写入工作台 `data/exports/`。上一轮 MCP 剪辑工具只覆盖时间线编辑，没有导出能力；本次补齐导出工具，并允许在 API/MCP 指定服务器本机绝对文件夹。
- 当前基线：
  - 新增 MCP 工具 `studio_export_edit(project_id, sequence_id, output_dir?, quality=1080)`（`studio:edit`）与 `studio_get_edit_export(project_id, job_id)`（`studio:read`），工具总数由 18 增至 20。导出读取账号隔离的时间线快照，异步执行，返回 `{id,status,progress,output_path,download_url}`；用 `studio_get_edit_export` 轮询。
  - `POST /api/projects/{project_id}/smart-edit/exports/mp4` 新增可选 `output_dir`。留空保持原行为：`data/exports/smart-edit/{job_id}.mp4`；指定目录时自动创建，文件名使用「工程名 + `YYYYMMDD-HHMMSS` + 任务号后 6 位」清洗后生成，避免覆盖。`GET …/exports/{job_id}` 与下载路由回显/读取 `output_path`。
  - 权限：管理员/超管可写入任意可创建且可写的本机目录；员工仅限 `ZLY_AI_VIDEO_STUDIO_LOCAL_MEDIA_ROOTS`（`;` 分隔）内，越界或相对路径返回 400。导出目录权限与「引用本机」共用同一允许目录，便于短剧素材与成片留在同一项目盘。
  - 任务 `payload_json` 保存输出绝对路径，但不含时间线文档；下载仍校验任务所属账号。通用项目任务接口（`GET /api/projects/{id}/jobs` 与 `…/jobs/{job_id}`）不返回 `output_path`，该字段只出现在本人的导出创建与查询响应中。目标文件被移动或删除后再下载返回 400，需重新导出。自定义目录中的成片不会随 `data/` 清理，也不会自动删除。
- 受影响文件：`backend/app/local_media.py`（新增 `ensure_export_allowed`）、`backend/app/media_studio/services/smart_edit_service.py`（`create_export`/`_run_export`/`get_export`/`export_file_path`）、`backend/app/media_studio/services/job_payload.py`（通用任务不返回本机路径）、`backend/app/media_studio/routers/smart_edit_router.py`、`backend/app/mcp_gateway/{editing_service.py,routes.py}`、`backend/tests/{test_smart_edit.py,test_mcp_gateway.py}`；同步 `docs/API.md`、本文件、`README.md`、`功能说明与扩展指南.md`、`docs/智能剪辑助手开发计划.md`、`docs/导演台流程与界面结构.md`、`.env.example`。前端未改动，工作台导出面板继续使用默认目录。
- 兼容性：不新增表或字段；旧导出任务无 `output_path` 时回退到 `data/exports/smart-edit/{job_id}.mp4`。未指定 `output_dir` 的 HTTP 调用行为不变；MCP 旧授权无需重新授权即可看到新增工具（作用域未变）。自定义目录权限依赖当前服务器文件系统与账号角色。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_smart_edit`（18 项通过）；`python -X utf8 -m unittest backend.tests.test_mcp_gateway`（26 项通过）；`python -X utf8 -m unittest backend.tests.test_core.ApiDocumentationTests.test_openapi_has_chinese_operation_and_field_documentation`（通过）；全量后端 952 项仅余 3 项与本改动无关的既有失败（`test_xiaji` 引用已删除模块、导演台提示词大小写断言、MySQL schema 迁移用例）。`pnpm --dir frontend build` 通过。
- 回滚方式：撤销 MCP 两个工具、`EditingService.export/export_status`、服务层 `output_dir` 参数与 `ensure_export_allowed`，恢复默认导出路径；已写入自定义目录的成片保留在原位置，数据库中的 `output_path` 字段随 payload 保留但旧代码不读取。

## 2026-10-23 智能剪辑本机素材直引与本机导出（新增当前基线）

- 日期与原因：2026-10-23。用户指出短剧素材常由其他流程生成在任意本机目录（如 `G:\workspace\...`），此前智能剪辑只能先上传七牛云或复制到 `data/` 才能使用，不符合实际制作习惯。本次增加「引用本机」能力：时间线可直接引用原目录文件，不复制、不上传，导出 MP4 也不再依赖七牛云。
- 当前基线：
  - 新增 `backend/app/local_media.py`。素材地址为 `/api/local-media/{base64url(绝对路径)}.{HMAC-SHA256(credential_key, "local-media:"+payload)[:32]}`；令牌只读、绑定当前服务器凭证密钥，篡改或文件缺失返回 404。`GET /api/local-media/{token}` 需登录，使用 `FileResponse`（支持 Range 206，可拖动播放）。
  - `POST /api/projects/{project_id}/smart-edit/{sequence_id}/import-local` 接受 `{path, recursive}`。管理员/超管可引用任意可读绝对路径；员工仅限环境变量 `ZLY_AI_VIDEO_STUDIO_LOCAL_MEDIA_ROOTS`（`;` 分隔的允许目录）内的文件。路径可指向单文件或文件夹；文件夹按自然顺序扫描，单次最多 200 个文件；逐个 `ffprobe` 校验，无法解码或无对应轨道的文件进入 `skipped[]`。素材记录新增 `local_path`，仍复用既有 `EditAsset` 结构，前端无需区分。
  - 时间线文档中的 `url` 保存签名地址而不是本机路径，因此保存/刷新/重启后仍可播放；`download_asset` 遇到本机地址直接返回原文件路径，渲染、bundle 打包与 `ffprobe` 都读取原目录，不产生副本。
  - 导出 MP4 不再要求七牛云：`_run_export` 将成品移动到 `data/exports/smart-edit/{job_id}.mp4`，`result_url` 为 `/api/projects/{project_id}/smart-edit/exports/{job_id}/file`；新增下载路由仅允许任务所属账号访问（未完成 409，非本人 404）。通用任务详情不暴露剪辑文档或其他账号路径。
  - 前端剪辑工作台素材面板新增「引用本机」按钮与弹窗（路径输入、可选包含子文件夹），导入后按 URL 去重合并，并把失败文件以提示列出；素材标题悬停显示原始本机路径。上传七牛云的旧入口保留，两种来源可在同一时间线混用。
- 安全边界：签名地址不是通用文件服务，只能读取导入时登记过的文件；员工不能借 `import-local` 遍历服务器任意目录；接口沿用登录与写操作 CSRF；`/api/local-media/*` 不写入通用任务 payload，导出快照仍按账号隔离。
- 受影响文件：新增 `backend/app/local_media.py`；修改 `backend/app/config.py`、`backend/app/media_studio/services/{smart_edit_document,smart_edit_service}.py`、`backend/app/media_studio/routers/smart_edit_router.py`、`frontend/src/director2/smart-edit/{model.ts,api.ts,SmartEditPane.tsx,smart-edit.css}`、`backend/tests/test_smart_edit.py`、`.env.example`；同步 `docs/API.md`、本文件、`README.md`、`功能说明与扩展指南.md`、`docs/智能剪辑助手开发计划.md` 和 `docs/导演台流程与界面结构.md`。
- 兼容性：不新增数据库表或字段；旧时间线（七牛云 URL）不变，仍可正常预览和导出。同一时间线可混合本机与云端素材。若播放服务器上另一个实例签发的本机地址会 404，需要在当前实例重新导入；更换 `data/credential.key` 会使旧本机地址全部失效。本机导出地址在 `data/exports/`，需随 `data/` 一同备份或定期清理。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_smart_edit`（17 项通过）；`python -X utf8 -m unittest backend.tests.test_smart_edit backend.tests.test_editing_assistant backend.tests.test_mcp_gateway backend.tests.test_director_assistant -q`（117 项通过）；`pnpm --dir frontend test`（58 个文件、366 项通过）；`pnpm --dir frontend build`（通过，16.15s）；5173 桌面端浅/暗主题检查「引用本机」弹窗、播放、时间线与导出下载，新增参考截图 `docs/design-ref-director/78-smart-edit-local-import-light.png` 与 `79-…-dark.png`。
- 回滚方式：还原上述后端/前端文件并重建前端；已保存的含本机素材时间线需要重新导入素材（签名地址依赖代码），云端素材时间线不受影响。

## 2026-10-22 移除本地作品存储目录

- 日期与原因：2026-10-22。用户确认今后所有作品统一使用七牛云存储，员工电脑的授权目录不再需要；原功能会在登录后以不可关闭的「设置作品存储目录」弹窗阻塞工作台，并要求每台浏览器单独授权目录。
- 当前基线：`frontend/src/App.tsx` 不再导入 `local-resource-store`，不再请求 `GET /api/storage`，也不再读取或缓存 `zly-storage-capability`；目录检查态、`requiresDirectorySetup` 弹窗、顶栏「设置存储」入口与资源「存储状态」筛选全部删除。`frontend/src/local-resource-store.ts`（IndexedDB 目录句柄、File System Access API、Tauri 写盘命令）删除。任务结果、批量下载、加入画布与剪映草稿链接统一使用 `download_url ?? cloud_url` 或现有媒体地址；结果卡「保存」改为云端直链下载。`ImageStudioModule`/`VideoStudioModule` 移除 `pendingSave`/`onSave`/本地状态判断，统一显示「已存入云端」。图片生成视频改为先 `fetch` 云端结果构造 `File` 再上传。登录页说明同步改为统一存入七牛云。
- 后端边界：`/api/storage`、`requires_local_directory`、`delivery_status`、`browser-stream`/`browser-directory` provider 与受保护下载路由均保留，供既有部署、桌面客户端和旧任务兼容；Web 前端不再调用或依赖它们。七牛云输出仍标记为 `cloud` 并返回云端/同源下载地址，历史 `local` 输出仍可凭 `download_url` 读取。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/media/{ImageStudioModule.tsx,VideoStudioModule.tsx}`、`frontend/src/auth/AuthScreens.tsx`、删除 `frontend/src/local-resource-store.ts`；同步 `README.md`、`功能说明与扩展指南.md`、`frontend/PRODUCT.md`。
- 兼容性：不修改后端 API、数据库、任务队列、ComfyUI 节点、端口、媒体对象或七牛云配置；旧任务输出、作品库和历史下载链接不受影响。浏览器中已有的 IndexedDB 目录记录不再读取，但不影响登录或其他本地偏好；回滚前端后仍可恢复目录授权流程。
- 验证命令：`pnpm --dir frontend exec tsc -b`；`pnpm --dir frontend test`（58 个测试文件、365 项通过）；`pnpm --dir frontend build`（`✓ built in 6.29s`）；`python -X utf8 -m unittest backend.tests.test_core -q`（102 项通过）。隔离 SQLite 后端（7866）+ 隔离 Vite（5174）+ 无头 Chrome 桌面验收：登录后无「设置作品存储目录」弹窗、顶栏无「设置存储」、资源筛选无「存储状态」；种子云端任务显示「已存入云端」并可下载、继续生成视频；控制台无应用错误。
- 清理：隔离后端与 Vite 已停止，`.tmp/storage-ui` 中的临时配置、SQLite、日志与截图已删除；未访问真实 MySQL、7865 后端或 ComfyUI，未提交生成任务。
- 回滚方式：恢复本次前端改动与 `frontend/src/local-resource-store.ts` 并重建前端即可；后端与数据无需迁移。已下载到员工电脑的历史文件需由员工自行保留，七牛云对象不受影响。

## 2026-10-22 无限画布 V4.2（标签、收藏与回收站）

- 日期与原因：2026-10-22。V4.1 已补齐画布搜索、排序与复制，但画布一多仍只能靠标题和保存时间管理，误删也无法挽回。本版为画布列表增加标签、收藏与回收站，采用纯加法迁移，保留现有 `DELETE` 的永久删除语义与草稿乐观锁。改动涉及后端 `canvas_projects` 表结构、画布接口与列表界面，不改变草稿 JSON、`schemaVersion 2`、`jobs` 表、工作流注册表或 ComfyUI 配置。
- 数据迁移：`canvas_projects` 新增 `tags_json`（MySQL `VARCHAR(512) NOT NULL DEFAULT '[]'`、SQLite `TEXT NOT NULL DEFAULT '[]'`）、`is_favorite`（0/1，默认 0）与 `deleted_at`（可空时间字符串），并增加 `(owner_user_id, deleted_at)` 索引。MySQL 每次启动重放 `sql/*.sql`，所以现有库的变更通过 `JobStore._ensure_column` 幂等补齐；SQLite 新库在 `CREATE TABLE` 中直接建列，旧库同样补列；`sql/019_canvas.sql` 同步更新供全新 MySQL 初始化。
- 标签：`normalize_canvas_tags` 去除首尾空白、忽略空项、按首次出现去重，单个最多 24 字符、最多 8 个，超限抛 `CanvasValidationError`（422）；`tags_json` 以紧凑 JSON 数组落库，`decode_canvas_tags` 对历史脏数据容错。前端 `normalizeCanvasTags` 使用同一组上限，在保存前给出提示。
- 部分更新与收藏：`CanvasStore.update_project` 接受 `title`/`tags`/`is_favorite` 任意组合，动态拼 SQL，空更新返回 422，只更新 `deleted_at IS NULL` 的画布；`PATCH /api/canvas/projects/{id}` 复用该入口，原 `rename_project` 委托给它。列表按 `is_favorite DESC, COALESCE(draft.updated_at, project.updated_at) DESC` 排序，收藏画布在服务端即置顶。
- 回收站：新增 `POST /api/canvas/projects/{id}/trash`（写 `deleted_at`，返回 `{id, deleted_at}`）与 `POST /api/canvas/projects/{id}/restore`（清空标记并返回完整项目），两者都要求 CSRF、按 `owner_user_id` 隔离并写审计日志。`GET /api/canvas/projects?trashed=1` 才返回回收站；详情、草稿保存、版本列表/恢复、PATCH 与再次移入回收站都排除已删除画布，回收站画布返回 404。`DELETE` 仍是永久删除（含草稿和全部历史版本），未新增自动清理。
- 列表界面：`CanvasWorkspace` 增加「全部 / 收藏 / 回收站」Segmented 视图、标签筛选（回收站隐藏）、标题或标签搜索与原有排序；卡片显示标签 chip、可点击星标和悬停操作列（编辑标签、复制、移入回收站），回收站卡片禁用打开并只保留恢复/彻底删除。标签编辑使用 Ant Design `Select mode="tags"`（`maxCount=8`、`maxTagTextLength=24`、中英文逗号分隔），收藏/移入/彻底删除都有即时提示与确认。
- 前端筛选：`filterCanvasProjects` 支持 `favoriteOnly` 与 `tag` 条件，搜索同时匹配标题和标签；过滤后再排序，最后把收藏项稳定置顶，不修改输入数组。`collectCanvasTags` 汇总当前视图标签。`AddToCanvasModal` 只请求未删除画布（`listCanvasProjects()`），避免向回收站画布插入素材。
- 兼容性：标签、收藏与删除标记都是列表级元数据，不写入草稿 JSON；旧前端加载的接口响应多出 `tags/is_favorite/deleted_at` 字段会被忽略，旧画布默认空标签、未收藏、未删除。复制画布仍只复制标题和草稿，不复制标签/收藏。回滚时可保留新增列（旧代码不读取），或撤销上述后端/前端改动并删除列；已移入回收站的画布在回滚后重新出现在列表中。
- 受影响文件：后端 `backend/app/{storage.py, models.py, main.py, canvas_store.py, api_documentation.py}`、`backend/tests/test_canvas_store.py`、`sql/019_canvas.sql`；前端 `frontend/src/canvas/{CanvasWorkspace.tsx, canvas-api.ts, canvas-model.ts, canvas-manage.ts, canvas-manage.test.ts, AddToCanvasModal.tsx, canvas.css}`；同步 `docs/无限画布开发计划.md`、`README.md`、`功能说明与扩展指南.md`。
- 验证命令：`pnpm --dir frontend test`（58 个测试文件、365 项通过，其中画布模型 37、保存 8、生成 26、画布管理 14，画布合计 85）；`pnpm --dir frontend exec tsc -b` 干净；`pnpm --dir frontend build` 通过（`✓ built in 9.96s`）；`python -X utf8 -m pytest backend/tests/test_canvas_store.py -q`（10 项通过）。隔离 SQLite 后端（7866）+ 隔离 Vite（5174）+ 无头 Chrome/CDP 桌面浅暗实测：收藏/取消收藏与置顶、标签编辑与筛选、按标签搜索、收藏视图、回收站恢复/再次移入/彻底删除、刷新持久化均正常；控制台无错误，并修复 Ant Design `Tag bordered` 弃用警告。隔离进程与 `.tmp/v42` 已清理，未访问真实 MySQL、7865 后端或 ComfyUI。
- 后续计划：PNG 导出、画布缩略图与 `/api/library` 服务端分页/检索仍待评估；V5 多人协作与分享需单独立项并先做 Yjs/权限 spike，详见 `docs/无限画布开发计划.md`。

## 2026-10-22 无限画布 V4.1（画布管理与素材流转）

- 日期与原因：2026-10-22。V4.0 已补齐画布操作与生成闭环，但生成结果回流画布仍要手动打开素材面板查找，画布列表也没有搜索/复制，画布内容只能留在服务器上。本版打通生成历史 → 画布的素材流转，补齐列表管理与 JSON 导入导出。仅改前端画布模块、资产页、样式、测试与文档；不新增后端接口、数据表、迁移、`jobs` 记录、`schemaVersion` 变更或 ComfyUI 配置。
- 加入画布：新增 `AddToCanvasModal.tsx`。生成历史资产卡在非批量、非查看他人资产且素材不是 `local`/`expired` 时显示悬停按钮；弹窗读取当前账号画布列表（搜索、最近更新排序），支持选择已有画布或「新建画布并加入」。跳转 URL 使用 `?addJob=<jobId>&addItem=<generationItemId>&addOutput=<index>`（旧任务无条目时省略 `addItem`），由 `canvas-manage.ts` 的 `canvasAssetInsertSearch`/`readCanvasAssetInsert` 统一构造与解析。
- 一次性插入与权限：`CanvasEditor` 在 URL 含插入参数时启用 `GET /api/library` 查询；加载完成后用 `findCanvasInsertLibraryItem` 命中 `job_id + output_index`（有 `addItem` 时同时匹配 `generation_item_id`），并继续经过 `isUsableLibraryItem` 与安全媒体 URL 校验。`consumedInsertAssetRef` 按 `${jobId}:${generationItemId ?? ""}:${outputIndex}` 去重，保证 StrictMode/重渲染只插入一次；插入走普通素材节点工厂且强制新增（不替换当前选中节点），成功后以 `setSearchParams(..., { replace: true })` 删除三个参数。加载失败、素材不属于当前账号或已过期时提示原因并同样清理参数，避免刷新重复触发。作品库仍由后端按账号隔离，未新增接口。
- 画布列表：`CanvasWorkspace` 新增标题搜索、排序（最近更新/最近创建/标题 A–Z）与无匹配空态；卡片新增复制按钮。复制由 `canvas-api.ts` 的 `duplicateCanvasProject` 组合现有接口完成：读取源画布 → 以 `canvasCopyTitle` 新建「标题 副本」→ 保存源草稿；保存失败会删除刚创建的空画布。后端画布表、归属隔离与删除语义不变。
- JSON 导出：编辑器「更多 → 导出 JSON」通过 `serializeCurrent()` 生成当前 `schemaVersion`/`canvasSettings`/`nodes`/`edges`，用 Blob + 临时对象 URL 下载，文件名由 `canvasExportFileName` 生成（清洗标题 + 时间戳），随后释放 URL。
- JSON 导入：隐藏 file input 读取文本，先在组件层按 `file.size` 拒绝超过 8 MB 的文件，再由 `canvas-manage.ts` 的 `parseCanvasImportContent` 做完整校验：去除 BOM、按 UTF-8 字节数复核 8 MB、`schemaVersion` 正整数、`canvasSettings` 为对象、`nodes`/`edges` 数组、节点 ≤ 3000、边 ≤ 6000、节点 id/type 非空且 id 唯一、坐标有限、`data` 为对象、图片/视频与生成结果及结果历史 URL 协议安全、边两端存在且不能自环。当前画布非空时使用受控 Ant Design `Modal` 二次确认（显示节点/连线数量与可撤销说明），确认前调用 `flushHistory()` 把替换前状态写入撤销栈；导入后的视口缺失时保留当前视口，节点/边/设置整体替换并触发自动保存。非法内容只提示、不修改画布。
- 主题与兼容：导入确认不再使用静态 `Modal.confirm`（其 holder 在主题切换时不会实时重渲染，暗色下会显示浅色弹窗），改为组件内受控 `Modal`，由当前 `ConfigProvider`/`--studio-*` 驱动双主题。`schemaVersion` 仍为 2，草稿 JSON 结构不变；旧前端可正常打开导入结果，未知节点仍按既有 `unknown` 兜底。PNG 导出与缩略图本轮只做方案评估（客户端 `html-to-image` 需解决跨域媒体与大画布降采样；服务端渲染需无头浏览器与队列），未引入依赖、未写数据库、未新增迁移。
- 受影响文件：新增 `frontend/src/canvas/AddToCanvasModal.tsx`、`frontend/src/canvas/canvas-manage.ts`、`frontend/src/canvas/canvas-manage.test.ts`；修改 `frontend/src/canvas/{CanvasWorkspace.tsx, CanvasEditor.tsx, canvas-api.ts, canvas-model.ts（复用）}`、`frontend/src/App.tsx`、`frontend/src/index.css`；同步 `docs/无限画布开发计划.md`、`README.md`、`功能说明与扩展指南.md`。
- 验证命令：`pnpm --dir frontend test`（58 个测试文件、363 项通过，其中画布模型 37、保存 8、生成 26、画布管理 12，画布合计 83）；`pnpm --dir frontend exec tsc -b` 干净；`pnpm --dir frontend build` 通过（`✓ built in 11.15s`）；`python -X utf8 -m unittest backend.tests.test_canvas_store -q`（7 项通过）。隔离 SQLite 后端（7866）+ 隔离 Vite（5174）+ 无头 Chrome/CDP 桌面实测：种子资产「加入画布」在新建画布和已有画布两条路径均只插入 1 个节点、URL 参数清理、服务端草稿含 `sourceJobId` 且自动保存完成；导出 JSON 文件名/结构正确；导入 2 节点/1 边确认替换并自动保存，撤销恢复原 1 节点；`javascript:` 图片地址与 9 MB 文件分别被拒绝且画布不变；列表搜索、空态清除、排序、复制（「室内对话 副本」）正常；浅色/暗色加入画布弹窗、更多菜单与导入确认弹窗对比度正常，控制台无应用错误。
- 清理：隔离后端（7866）、隔离 Vite（5174）与临时 Chrome 会话已停止，种子脚本、SQLite 数据、Cookie、截图与隔离配置位于已忽略的 `.tmp/v41/` 并已删除；未访问真实 MySQL 与 7865 后端，未启动或切换 ComfyUI，未提交生成任务。
- 兼容与回滚：不新增后端契约、表、迁移或依赖；`schemaVersion` 仍为 2，导入导出只使用现有草稿结构。回滚只需撤销上述前端文件、样式、测试与文档；已导出 JSON 可被旧前端按既有 `parseCanvasContent` 打开，已复制画布与已插入素材节点是普通画布数据，不影响任务页。
- 后续计划：标签/收藏/回收站、PNG 导出、缩略图、作品库服务端分页留待后续增量；V5 多人协作与分享需单独立项并先做 Yjs/权限 spike，详见 `docs/无限画布开发计划.md`。

## 2026-10-22 无限画布 V3.3（结果与追溯）

- 日期与原因：2026-10-22。V3.1/V3.2 已能在画布内生成并插入结果，但结果节点只有 `sourceJobId`，无法回显提交时实际使用的提示词与参数；任务被删除或产物过期时画布也没有明确状态。本版补齐运行快照、结果节点回链任务与失效状态，仍不新增后端接口、数据表、任务队列或第二套任务记录，任务状态以 `jobs` 表与 `GET /api/jobs/{id}` 为准。
- 快照模型：`canvas-model.ts` 新增 `CanvasRunSnapshot`（`jobId/workflowId/workflowName/prompt/optionValues/parameterSummary/referenceCount/mediaKind/submittedAt`）。`canvas-generation.ts` 新增 `buildCanvasRunSnapshot`、`readCanvasRunSnapshot`、`canvasRunHistory`、`canvasRunSnapshotForJob`、`appendCanvasRunSnapshot` 与上限常量；提交成功后由 `CanvasEditor.submitGenerator` 写入生成节点 `lastRun`，并按任务号去重追加到 `runHistory`（最近 12 条）。快照在提交时冻结，提示词截断 4000 字、参数最多 40 项、字符串值 200 字、摘要最多 6 条且每条 120 字，读取时同样清洗，避免画布体积失控。
- 结果溯源：`appendResultNode` 继续写入 `sourceJobId`、`assetPath`、`mediaKind`，并从生成节点的 `runHistory`/`lastRun` 复制对应 `sourceRun` 到图片/视频节点；手动插入、独立模式自动插入与分支生成共用这一路径。结果节点不保存任务状态副本，任务删除或产物过期时以实时查询结果为准。
- 追溯界面：新增 `CanvasRunTrace.tsx` 与 `useCanvasSourceJob`。生成节点检查器显示「本次运行」，图片/视频节点检查器显示「来源任务与运行参数」；组件在挂载、任务号变化、生成节点状态变化或点击「刷新状态」时查询任务，显示状态标签、可复制任务号、「在任务详情中打开」，折叠区展示工作流、提交时间、参考图数量、参数摘要、提交时提示词与提交参数原样值。旧结果只有任务号、没有快照时显示「该结果由旧版本画布创建，未保存提交时的参数快照」。
- 失效状态：404 显示「任务已删除」（画布结果保留，参数无法再从任务回读）；任务成功/部分成功但全部产物已过期或没有可用地址时由 `canvasJobOutputsExpired` 显示「结果产物已过期」；其它读取失败显示「无法核对来源任务」与重试入口。图片/视频节点在地址变化时重置加载状态，加载失败显示「素材无法加载 / 地址可能已过期」；生成节点结果加载失败显示「结果素材无法加载」并提示到属性面板核对来源任务，双重避免把过期产物当正常结果。
- 持久化与兼容：`schemaVersion` 仍为 2，`lastRun`/`runHistory`/`sourceRun` 均为可选字段，服务端仍按不透明 JSON 保存；不改变自动保存、重试、8 MB 限制、409 冲突、撤销栈、版本历史、`jobs` 表和工作流注册表。旧前端忽略新字段；回滚只需撤销追溯组件、快照函数、节点接线、样式、测试与文档，已写入草稿的快照不影响旧前端，任务仍可在任务页访问。
- 受影响文件：新增 `frontend/src/canvas/CanvasRunTrace.tsx`；修改 `frontend/src/canvas/{canvas-model.ts, canvas-model.test.ts, canvas-generation.ts, canvas-generation.test.ts, CanvasEditor.tsx, CanvasInspector.tsx, CanvasGeneratorInspector.tsx, CanvasSidePanel.tsx, CanvasNodes.tsx, canvas.css}`；同步 `docs/无限画布开发计划.md`、`README.md`、`功能说明与扩展指南.md`。生成逻辑新增 4 项单测。
- 验证命令：`pnpm --dir frontend test`（57 个测试文件、351 项通过，其中画布模型 37 项、保存 8 项、生成逻辑 26 项，画布合计 71 项）；`pnpm --dir frontend exec tsc -b` 干净；`pnpm --dir frontend build` 通过（`✓ built in 11.45s`）；`python -X utf8 -m unittest backend.tests.test_canvas_store -q`（7 项通过）。隔离 SQLite 后端（7866）+ 隔离 Vite（5174）+ 无头 Chrome/CDP 桌面 1440×900 浅暗实测：真实提交 T2V（隔离后端指向不可达 ComfyUI）返回 `interrupted` 后，「本次运行」显示任务号、状态、提交时间、参考图 0 张、参数摘要、提示词与参数原样值；保存草稿版本 12、8 节点确认 `lastRun` 九字段、`runHistory` 与结果节点 `sourceRun` 持久化；种子任务验证产物过期（「已完成」+「结果产物已过期」）、任务删除（404 →「任务已删除」）、旧结果无快照提示与未关联任务不显示追溯块；「在任务详情中打开」进入 `/generate/video/job-v33-expired`；浅色/暗色对比度正常，控制台除预期缺失任务/媒体 404 外无应用错误。
- 清理：隔离后端（7866）、隔离 Vite（5174）与无头 Chrome 已停止，临时 SQLite 数据、Vite 配置、Cookie、截图与种子脚本位于已忽略的 `.tmp/` 并已删除；未访问真实 MySQL 与 7865 后端，未启动或切换 ComfyUI。
- 后续计划：V4.1 画布管理与素材流转（生成历史/作品库「加入画布」、画布搜索/排序/复制、JSON 导入导出、缩略图方案）见 `docs/无限画布开发计划.md`。

## 2026-10-22 无限画布 V3.2（提示词与参考图连线）

- 日期与原因：2026-10-22。V3.1 已有生成节点，但只有图片可以连入作为参考图；文字节点连线没有业务含义，参考图数量只在点击提交后才校验，用户容易在不知情的情况下提交失败。本版补齐「文字节点→提示词」「连线顺序即参考图顺序」和连线变化的即时校验。只改前端画布模块、样式、测试与文档；后端接口、数据库、`schemaVersion 2`、`jobs` 表、工作流注册表和 ComfyUI 配置均不变。
- 提示词来源：指向生成节点的文字节点由 `incomingGeneratorPromptNodes` 按边数组顺序去重收集，`resolveGeneratorPrompt` 把非空文本以空行拼接为生效提示词；生成节点自身 `data.prompt` 只在没有文字来源时使用。已连接但内容为空的文字节点由 `generatorPromptIssue` 阻断提交并给出原因，不再静默忽略；节点卡片、浮动工具栏和检查器三处共享同一判定。
- 参考图顺序：图片与带安全 URL 的生成结果节点由 `incomingGeneratorReferenceNodes` 按同一边数组顺序取参考图并去重，序号 1..n 与 `<Picture n>` 一一对应；连线顺序是唯一排序依据，不新增排序字段。`canvasReferenceEligible` 与 `isValidConnection` 共同限制可连类型：文字、图片、生成结果可连入生成节点，图片/视频结果节点只接受生成节点来源。
- 即时校验：`generatorReferenceIssue` 在切换工作流或连线变化后立即按 `min_references`/`max_references` 生成提示（例如「支持 1-9 张参考图，当前 0 张」），`validateGeneratorInput` 在提交时做最终校验。数量不满足只禁用提交并说明原因，不删除边、不阻断继续编辑，也不自动创建任务；任务仍由卡片、浮动工具栏或检查器显式触发生成。
- 编辑辅助：检查器参考图列表逐行显示 `<Picture n>` 标记，手动提示词编辑器提供「插入参考图标记」下拉把标记插入光标处，并说明标记与上传顺序对应；系统不自动改写用户提示词，避免把普通文本误替换为标记。文字节点「以此生成」会自动创建并连一条文字边；图片节点分支生成在参考数量兼容时自动连参考边。
- 持久化与兼容：不新增草稿字段，边数组仍是提示词来源与参考图顺序的唯一事实来源；复制节点、撤销/重做、刷新和版本恢复后的语义保持一致。旧前端忽略新增的校验与提示，只把边当作普通连线，不丢数据。
- 受影响文件：`frontend/src/canvas/{canvas-generation.ts, canvas-generation.test.ts, CanvasEditor.tsx, CanvasNodes.tsx, CanvasGeneratorInspector.tsx, CanvasSidePanel.tsx, canvas.css}`；`docs/无限画布开发计划.md`、`README.md`、`功能说明与扩展指南.md`。生成逻辑新增 4 项单测。
- 验证命令：`pnpm --dir frontend test`（57 个测试文件、347 项通过，其中画布模型 37 项、保存 8 项、生成逻辑 22 项）；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend build` 通过（`✓ built in 10.63s`）；`python -X utf8 -m unittest backend.tests.test_canvas_store -q`（7 项通过）。隔离 SQLite 后端（7866）+ 隔离 Vite（5174）+ 无头 Chrome/CDP 桌面 1440×900 浅暗实测：文字节点「以此生成」自动连线并显示文字来源与合并提示词，编辑文字实时同步到相连生成节点；切换「LightX2V 多参考视频」后立即显示「支持 1-9 张参考图，当前 0 张」，卡片/浮动工具栏/检查器提交同步禁用且未创建任务；连入合法图片后警告消失、提交恢复，检查器显示「连线顺序即提交顺序 · `<Picture 1>`」；断开图片或文字边分别回到数量警告与手动提示词，重连恢复；控制台无新增错误。未提交真实生成任务，未访问真实 MySQL 或 7865 后端。
- 清理：验收使用临时管理员、SQLite 数据、Vite 临时配置、无头 Chrome 配置与截图，均位于已忽略的 `.tmp/`，验收后删除；未触碰真实业务数据。
- 兼容与回滚：`schemaVersion` 与后端契约不变；回滚只需撤销上述前端文件、测试与文档，已保存画布中的边与文字节点数据不受影响，旧版本仍可按普通连线打开。
- 后续计划：V3.3 已完成（见上一条）；V4.1 画布管理与素材流转见 `docs/无限画布开发计划.md`。

## 2026-10-22 智能剪辑助手 A5：音轨转写与音轨字幕

- 日期与原因：2026-10-22。`subtitle_arrange` 的字幕一直来自分镜/剧本对白，与成片实际配音或原声不同步，用户要求「按真实声音上字幕」时无路可走。本版接入已配置的 OpenAI 兼容转写接口，按素材生成带时间戳的段落，并新增 `audio_subtitle` 动作把转写段落铺成字幕轨。本增量只做字幕铺设，不用转写结果删镜头或改画面轨（属于 A6）。
- 转写客户端：`backend/app/llm_client.py` 新增 `OpenAICompatibleClient.transcribe()`，走 `POST {base_url}/audio/transcriptions`（multipart、`response_format=verbose_json`）；`backend/app/llm_provider.py` 增加 `transcription_model() / transcription_availability() / transcribe_audio()`，base_url 与 API Key 复用 `llm_provider_settings`（与 LLM、VLM 同源），不新增供应商配置表；模型取环境变量 `ZLY_AI_VIDEO_STUDIO_ASR_MODEL`，缺省常量 `DEFAULT_ASR_MODEL = "XingChenAGI/XingChenASR-V3.2-Ultra"`，单次超时 `ASR_TIMEOUT_SECONDS = 300`。错误分类镜像既有 `speech()`：HTTP 500 空 body、400/20012、超时与供应商不可用（开关未启用、凭据主密钥不可用、API Key 缺失）都映射成中文可读失败文案，日志与响应不得出现密钥。上游只给段级时间戳（`segments[].words` 恒为空），后端不伪造词级对齐；不向用户暴露语言选择，非法 `language` 会被上游静默忽略，界面不得宣称支持英语。
- 音频提取与预算：`backend/app/director_assistant/transcription.py`（新增 `MediaTranscription`）复用 `understanding.py` 的可信下载、`ffprobe` 探测与 `source_signature`；只处理时间线上仍在发声的片段，按素材用 FFmpeg `-vn -ac 1 -ar 16000` 输出 16k 单声道 WAV 到系统临时目录，转写成功或失败立即删除。单次上限 `MAX_MEDIA_PER_RUN=40` 条素材、`MAX_AUDIO_SECONDS_PER_RUN=600` 秒，另限制每素材 200 段/200 条 span、单段 400 字；超限素材标 `skipped` 并说明原因，不把上游容量当兜底。
- 记录与生命周期：仍复用 `ai_assistant_records`，新增 kind `media_transcript`，id 为 `trn-<sha256[:40]>`，载荷含 `model/source_signature/items[]/summary/progress/message/started_at/finished_at`，逐素材段落保存在 `items[].segments[{id,start,end,text}]`（源素材秒）、时间线↔源素材映射保存在 `items[].spans[{clip_id,timeline_start,timeline_duration,in_point,speed}]`，计费口径的音频秒汇总在 `summary.audio_seconds`（逐素材另存 `audio_seconds`）；状态 `queued/running/succeeded/partial/empty/failed`，源素材或时间线变化后由读取接口计算 `stale=true`；`run_token` 乐观锁、最多 2 并发、遗留 running 超过 15 分钟由 `recover()` 与读取路径判失败。无新表、无迁移。
- 接口：`GET /api/projects/{project_id}/smart-edit/{sequence_id}/transcript`（登录读取）与 `POST …/transcript`（CSRF，body `{force:boolean}` 重新转写），同一范围运行中返回 409。`editor_read.analysis.transcript` 与 `understanding` 并列暴露状态、段落数与音频秒数；助手 system prompt 明确 `audio_subtitle` 只能使用已完成/部分成功的转写证据，`missing/stale/empty/failed` 时必须说明原因并建议先点「转写音频」，不得把剧本对白冒充转写结果。
- 时间映射与新动作：`audio_subtitle` 段起点按 `timeline_start = span.timeline_start + (seg.start - span.in_point) / span.speed` 计算并钳制在该素材的可听区间内，段尾按镜头边界收短，超长句复用既有显式断行规则拆条；与手工文字或其它文字片段重叠的段落计入 `skipped_count`；无可用转写时返回 `empty` 或明确错误，绝不回退剧本对白。预览项为 `asset_id/beat_id/segment_id/name/start/duration/reason/action`，结果另带 `count/skipped_count/inaudible_count/replaced_count/total_duration`；确认沿用 revision CAS、幂等与同一事务，只替换 `origin=auto_subtitle` 的上一次自动字幕，手工文字永不覆盖。
- 前端：`frontend/src/director2/assistant/DirectorAssistant.tsx` 在画面理解卡片之外新增独立「音频转写」卡片（状态标签、进度、`模型 · N 段 / M 秒音频 · 完成时间`、可展开「逐段语音依据」逐素材与逐段时间、失败清单、开始/重新转写的按秒计费与外发披露）；`editing-tools.ts` 增加第 7 个动作「音轨字幕」；`smart-edit/api.ts` 增加 `MediaTranscript` 类型与读写请求。授权弹窗逐条列出字幕时间、文本与来源。两处桌面验收修复：运行中不再把服务端预置的「等待转写」素材列进「未转成功」；两张卡片的确认气泡统一限宽 340px（`assistant.css`）。
- 兼容性：既有 6 个剪辑动作语义与参数不变；转写供应商未配置、超时或单素材失败只影响 `audio_subtitle`，手动剪辑、`subtitle_arrange` 与旧提案不受影响；`media_transcript` 记录只用于回显与铺字幕，删除后界面回到「未开始」。依赖服务器 FFmpeg/ffprobe 与已配置的转写模型。
- 受影响文件：后端 `backend/app/{llm_client,llm_provider}.py`、`backend/app/director_assistant/transcription.py`（新增）、`backend/app/director_assistant/{editing,protocol,service}.py`、`backend/app/media_studio/routers/smart_edit_router.py`、`backend/tests/test_transcription.py`（新增）、`backend/tests/test_editing_assistant.py`；前端 `frontend/src/director2/assistant/{DirectorAssistant.tsx,editing-tools.ts,assistant.css}`、`frontend/src/director2/smart-edit/api.ts`、`frontend/src/director2/assistant/editing-tools.test.ts`；文档 README、`功能说明与扩展指南.md`、`docs/API.md`、`docs/导演台流程与界面结构.md`、`docs/智能剪辑助手开发计划.md`。
- 验证命令：`E:\anaconda3\python.exe -X utf8 -m unittest backend.tests.test_transcription backend.tests.test_media_understanding backend.tests.test_editing_assistant backend.tests.test_director_assistant backend.tests.test_smart_edit backend.tests.test_video_analysis -q` 127 项通过；全量 `unittest discover -s backend/tests -p 'test_*.py' -q` 911 项，仅 2 项既有失败（`test_xiaji` 导入已删除模块、剧本提示词大小写断言）；`pnpm --dir frontend build` 通过（57 个测试文件、327 项、`tsc -b` 干净）。5173 桌面浅暗实测：2 条 7 秒自产物有声素材 → 转写 2/2 条、3 段、14.0 计费秒 → 授权弹窗 4 条字幕（含「长句已分行」「已按镜头边界收短」）→ 确认写入文字轨 6 个片段 → 工具栏单步撤销恢复 2 个片段 → 重铺与硬刷新持久化 → 手工文字在同一次重铺后保留，且铺字幕不把转写标记为 `stale`。
- 清理：验收账号、工程、剪辑文档、5 条助手记录与 2 个七牛云对象已按 ID 删除；转写探针与中间 WAV 只放在仓库外的系统临时目录并已清理；未提交生成或导出任务，未向供应商外发真人音频。
- 回滚：删除 `transcription.py`、`test_transcription.py`，撤销 `transcribe()`、transcript 路由、`audio_subtitle` 动作与前端卡片即可；历史 `media_transcript` 记录无人读取即失效，已铺设的字幕可在时间线上单步撤销或改用 `subtitle_arrange` 重铺；无数据库迁移、无供应商切换。
- 后续计划：A6 语义分段与废片识别把转写段落作为语义段输入之一，新增 `remove_waste` 的可解释预览与确定性移除；见 `docs/智能剪辑助手开发计划.md` 第 5 节。

## 2026-10-22 无限画布 V4.0（操作手感与生成闭环）

- 日期与原因：用户手测 V3.1 后认为画布操作手感与参考平台差距较大，且生成闭环不完整。本版按「操作手感 + 生成闭环两层一起做」重做画布外壳与节点交互，并补齐生成节点内联、分支生成、结果版本与独立结果节点。仅改前端画布模块、样式、测试与文档；后端接口、数据库、`schemaVersion 2`、`jobs` 表、工作流注册表与 ComfyUI 配置不变。
- 布局与工具：编辑器改为顶部命令栏 + 左侧工具轨 + 画布 + 右侧常驻 `CanvasSidePanel` + 底部视图栏。工具轨含选择（V）/移动（H）/添加/画板/作品库/撤销/重做/删除/快捷键说明；底栏含小地图（M）、缩小/当前缩放/放大/适应画布与 1–9/0 视角。视角存 `canvasSettings.viewpoints[10]`，`Shift+数字` 保存当前相机，数字跳转；工具状态 `select | pan` 控制左键拖拽语义。
- 添加与菜单：画布右键菜单提供生成节点、文本、图片占位、画板、作品库插入、图片地址、粘贴与全选；节点右键菜单提供节点属性、生成、向右/向下生成、复制、删除。`T/A/G/F` 直接添加节点；无指针落点的添加调用 `findCanvasFreePosition` 做碰撞避让，`revealAddedNode` 在节点超出视口时用 `setCenter` 平移。菜单使用 Ant Design Menu，靠近视口底部时自动限高并滚动。
- 节点交互：六类节点由 `NodeFloatingToolbar` 提供快捷操作，`NodeResizer` 提供八向缩放；生成节点工具栏含生成/重新生成 + 分支下拉、插入、属性、复制、下载与删除，媒体节点含「以此生成」。句柄按媒体类型着色（图片 `#f19d3c`、视频 `#5b9cf5`、文字 `#9d7cf4`）。拖动节点用 `computeSnapGuides` 以 `6 / zoom` 阈值吸附并绘制 `.canvas-guide`，开关为 `guidesVisible`。
- 连线与设置：`canvasSettings.connectionMode` 为 `off | compact | full`；`compact` 用选中节点/边沿上下游闭包过滤边并短暂保留新边，`off` 只隐藏渲染、不删数据。设置新增 `generationDisplayMode`、`gridVisible`、`minimapVisible`、`guidesVisible`、`globalPrompt`（2000 字）与 `viewpoints`；`readCanvasSettings` 对旧草稿逐字段回退默认值。
- 面板：`CanvasSidePanel.tsx` 常驻右侧，Tab 为属性/图层/历史。属性在选中节点时渲染检查器，否则显示画布信息与设置；图层支持搜索、定位、复制、删除；历史合并本地撤销/重做与服务端版本恢复。原节点检查器 Drawer 由常驻面板取代，素材 Drawer 保留。
- 生成闭环：生成节点卡片内联提示词，结果区显示媒体、提示词摘要、双击预览与结果版本切换（`resultHistory` 最多 12 条，`resultIndex` 指向当前版本）。`canvasResultVersionPatch` 在任务快照变化时去重追加，`selectCanvasResultVersion` 切换版本。`branchGenerate(nodeId, direction)` 从生成/文本/图片节点读取提示词，优先继承生成节点工作流与参数，参考数量不兼容时用 `pickCanvasGenerationMode` 重选；`nextCanvasBranchSlot` 按方向与碰撞寻找槽位，图片源自动连边，相机按源+新节点包围盒自适应。全局提示词只用于新建节点与分支无提示词兜底。
- 独立结果：`generationDisplayMode === "independent"` 时，终止任务快照在 `appendResultNode` 中自动插入结果节点（`auto` 不抢选择），`autoInsertedJobsRef` 加 `sourceJobId` 双重去重，避免轮询/刷新重复插入；结果节点仍写 `assetPath`/`sourceJobId`/`mediaKind`。`aggregate` 保留原行为。
- 持久化与兼容：新增字段全部写入画布草稿 JSON，服务端仍按不透明 JSON 保存，自动保存/重试/8 MB/409/版本历史不变；`schemaVersion` 仍为 2，旧前端忽略新字段。回滚只需撤销画布前端、样式、测试与文档；已保存的 `branchDirection`/`resultHistory`/画布设置留在 JSON 中不影响旧前端，生成节点仍可回到任务页。
- 受影响文件：`frontend/src/canvas/{CanvasEditor.tsx, CanvasNodes.tsx, CanvasSidePanel.tsx（新增）, CanvasInspector.tsx, CanvasGeneratorInspector.tsx, canvas-model.ts, canvas-generation.ts, canvas.css}`、`canvas-model.test.ts`（37 项）、`canvas-generation.test.ts`（18 项）、`canvas-save.test.ts`（8 项）；`docs/无限画布开发计划.md`、`功能说明与扩展指南.md`、`README.md`。
- 验证命令：`pnpm --dir frontend build`（57 个测试文件、343 项通过；`tsc -b` 干净；`✓ built in 16.54s`）；`python -X utf8 -m unittest backend.tests.test_canvas_store -q`（7 项通过）。隔离 SQLite 后端（7866）+ 隔离 Vite（5174）+ 无头 Chrome/CDP 桌面 1440×900 浅暗实测：右键菜单限高与布局、分支生成避让/连线/揭视、G 空位添加、H/V/M、视角、连线三档、缩放、图层/历史、全局提示词预填、对齐参考线均正常；刷新后 9 节点/1 边、提示词、独立模式、完全连线、视口与视角 1 恢复；控制台仅有既有的 Ant Design `List` 弃用警告。未提交真实生成任务，独立模式自动插入与真实出片待远端 ComfyUI 可用时补验。
- 后续计划：V3.2 文字节点→提示词与连线即时校验已完成（见上一条）；V3.3 参数快照与结果追溯已完成（见上方记录）；V4.1 画布管理（搜索/复制/导入导出/缩略图）见 `docs/无限画布开发计划.md`。

## 2026-10-22 无限画布 V3.1（生成节点与任务联动）

- 原因与范围：V2.5 后画布可摆放和整理素材，但不能在画布内发起生成。V3.0 spike 验证了 `/api/modes` 参数 schema、图片节点同源取字节和 `POST /api/jobs` 契约后，本版新增 `generator` 节点，把工作流选择、提示词、创作参数、有序参考图、任务提交/轮询/取消和结果回填接进画布。只改前端画布模块、样式、测试与文档，不改后端接口、数据库、工作流注册表或 ComfyUI 配置；任务仍以 `jobs` 表为准。
- 节点与检查器：`generator` 节点左侧 `in` 接收图片参考、右侧 `out` 可继续连线；卡片显示工作流名、状态、提示词摘要、参考图数量、真实进度和结果缩略图，双击结果预览。检查器分「生成设置 / 参考图 / 任务 / 生成结果」四段：工作流 Select、提示词 TextArea、`primary` 参数内联、`advanced` 收进「更多设置」、`internal` 不显示也不提交；`ui_visible_when` 控制联动隐藏，切换工作流重置默认值并清空旧任务与结果。
- 参考图与提交：从所有指向生成节点的图片入边按边数组顺序取参考图并去重，检查器显示 1..n 序号，提交顺序与 R2V 的 `<Picture n>` 一致；文字节点暂不参与。地址优先 `assetPath → /api/media/{path}`，使用同源 `fetch(..., {credentials:"include"})` + `fileFromReferenceBlob` 构造 `File`；跨域地址不通过后端代理抓取。提交前校验提示词、`min_references`/`max_references` 和每个地址，随后以 multipart `mode`、`prompt`、`options`（仅可见参数，数值转 number）、有序 `references`、`title` 调用 `POST /api/jobs` 并带 `X-CSRF-Token`。不新增接口、不开放任意 URL 抓取。
- 状态与恢复：`jobId`、`jobStatus`、`jobError`、`resultUrl`、`resultKind`、`resultPath` 写入节点 `data`，随 1.2 秒防抖草稿保存；运行态另存 `liveJobs` 内存快照。只对 `queued`/`running` 每 2500ms 轮询 `GET /api/jobs/{id}`，全部终止后自动停止；刷新后从节点数据恢复任务号继续轮询。进度只取后端 `progress`，错误直接展示后端 `error`，不伪造进度、不显示模型思考过程；运行中禁用参数与提交，可调用 `POST /api/jobs/{id}/cancel`。
- 结果：显示首个产物缩略图、预览和可复制素材路径；「插入为图片/视频节点」在生成节点右侧 48px 创建对应节点并写入 `assetPath`、`sourceJobId`、`mediaKind`；「在任务详情中打开」跳转现有任务页。任务删除或产物过期后画布不另存副本，仍以任务详情为准。
- UI：布尔参数行改为两列 grid（标签 + 开关，说明占整行），修复标签被挤成竖排；生成节点与检查器沿用 Ant Design 和 `--studio-*` 主题变量，桌面浅色/暗色检查通过。
- 受影响文件：新增 `frontend/src/canvas/canvas-generation.ts`、`canvas-generation.test.ts`、`CanvasGeneratorInspector.tsx`；修改 `CanvasEditor.tsx`（生成节点注册、模式查询、提交/轮询/取消、结果插入、任务页跳转）、`CanvasNodes.tsx`（`GeneratorCanvasNode` 与上下文）、`canvas-model.ts`/`canvas-model.test.ts`（生成节点工厂与类型）、`canvas.css`（生成节点与检查器样式）；同步 README、扩展指南和开发计划。后端与数据库无改动。
- 验证：`pnpm --dir frontend test` 57 个测试文件、327 项通过（画布模型 27 项、保存 8 项、生成逻辑 12 项）；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend build` 通过（`✓ built in 11.20s`）；`python -X utf8 -m unittest backend.tests.test_canvas_store` 7 项通过。桌面验收使用隔离 SQLite 后端（7866）与隔离 Vite 开发页（5174，代理到 7866，局域网地址访问）+ 无头 Chrome/CDP：真实提交 T2V（隔离后端故意指向不可达 ComfyUI）返回 `interrupted`，检查器显示「已中断」、任务号和后端错误；拦截 `POST /api/jobs` 与 `GET /api/jobs/{id}` 模拟运行中 42% 进度、提交禁用与停止按钮，模拟成功后显示结果缩略图、「重新生成」「在任务详情中打开」，点击插入在右侧生成带来源的图片节点；浅色/暗色下设置、更多设置、参考图、状态、错误和结果区对比度正常，控制台无应用错误。未访问真实 MySQL、7865 后端，未启动或切换 ComfyUI。
- 清理：验收使用临时管理员、SQLite 数据、Vite 临时配置、无头 Chrome 配置、请求拦截脚本与截图，均位于已忽略的 `.tmp/` 与 `test-results/`，验收后已删除；未触碰真实业务数据。
- 兼容与回滚：`generator` 是新增节点类型，旧前端会按 V2.1 的未知节点提示卡保留其数据；`schemaVersion` 仍为 2，节点 `data` 只新增可选字段，服务端仍按不透明 JSON 保存。回滚仅撤销画布生成节点、检查器、生成逻辑、样式、测试与文档；已保存的生成节点在旧前端显示为未知节点，任务仍可在任务页访问；不删除 `jobs`、画布草稿或历史版本。
- 后续计划：V3.2 文字节点→提示词与连线即时校验已完成；V3.3 补参数快照与结果节点回链；详见 `docs/无限画布开发计划.md` 第 6 节。

## 2026-10-22 无限画布 V2.5（保存可靠性与性能）

- 原因与范围：V2.4 后画布已具备拖放与检查器，但保存失败只停在错误态、接近 8 MB 会静默失败、节点多时全量渲染、刷新后视口丢失。本版补齐保存重试、体积预警与拒绝、超过 300 节点的按需渲染和视口持久化。只改前端保存/渲染/视口逻辑、样式与测试，不涉及后端接口、表结构、工作流注册表或 ComfyUI 配置；草稿仍为 `{nodes, edges, schemaVersion, canvasSettings}` JSON，`canvasSettings.viewport` 是新增可选字段。
- 保存状态机与重试：`CanvasSaveState` 扩展为 `saved | dirty | saving | retrying | error | conflict`，状态标签新增「重试中」。保存失败后按 2 秒、5 秒、10 秒退避自动重试，最多 3 次；手动保存会立即重试。仅非 `ApiRequestError` 的网络异常、5xx、408、429 可重试；其它 4xx 直接失败；409 仍立即暂停自动保存并显示「加载最新版本」，不进入重试。卸载、重新加载或成功保存都会清理计时器；重试期间继续编辑不会丢失最新内容，保存完成后按内容是否仍为当前快照回到 `saved` 或 `dirty`。
- 体积保护：保存前用 `TextEncoder` 计算 UTF-8 字节数。≥6 MB 显示警示条「画布体积约 X MB，接近 8 MB 上限」；>8 MB 拒绝保存、显示「超过 8 MB 上限」错误条且不重试，并提示删除大型内嵌图片或改用素材地址。手动保存与自动保存共用同一检查，不会出现静默失败。阈值与后端 `MAX_CONTENT_BYTES = 8 * 1024 * 1024` 一致。
- 大画布渲染：节点数超过 300 时给 React Flow 设置 `onlyRenderVisibleElements`，只渲染视口内节点；阈值不改变节点数组、历史栈、MiniMap 数据或保存内容，301 节点画布仍由 MiniMap 显示全部节点。300 及以下保持原有全量渲染。
- 视口持久化：`onMoveEnd` 把 `{x, y, zoom}` 以 0.001 精度写入 `canvasSettings.viewport`；坐标变化 <0.5px、缩放变化 <0.001 时忽略。坐标和缩放均需有限且在 0.1–2 范围内才被视为合法。刷新后存在合法视口时作为 `defaultViewport` 并关闭 `fitView`，否则自动适配；从历史版本恢复时保留当前实时视口，避免画面跳走。视口变更会让画布进入待保存并随下一次防抖保存写入。首次打开没有视口记录的画布会因 `fitView` 保存一次视口，可能多出一个历史版本，属于已知限制。
- 受影响文件：`frontend/src/canvas/canvas-save.ts`（新增：状态类型、重试序列/可重试判定、409 版本解析、状态转换、UTF-8 体积/阈值/格式化、虚拟化阈值）、`canvas-save.test.ts`（新增 8 项）、`canvas-model.ts`（`CANVAS_MIN_ZOOM`/`CANVAS_MAX_ZOOM`、`readCanvasViewport`、`canvasViewportChanged`）、`canvas-model.test.ts`（新增 2 项）、`CanvasEditor.tsx`（重试计时器、体积状态、预警/错误条、视口记录与恢复、按需渲染）、`canvas.css`（重试状态与保存提示条）；同步 README、扩展指南和开发计划。后端与数据库无改动。
- 验证：`pnpm --dir frontend test` 56 个测试文件、314 项通过（画布模型 26 项、保存逻辑 8 项）；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend build` 通过；`python -X utf8 -m unittest backend.tests.test_canvas_store` 7 项通过。桌面验收使用隔离 SQLite 后端（7866）与隔离 Vite 开发页（5174，代理到 7866，局域网地址访问）：断网添加节点后显示「重试中（2/3）」，恢复网络后下一次退避自动保存成功；6.2 MB 画布显示预警；超过 8 MB 的画布添加节点后显示错误且等待 7 秒未重试；外部推进版本后编辑触发 409，点击「加载最新版本」恢复且版本未额外递增；301 节点画布缩放到局部后仅渲染 80 个节点 DOM、MiniMap 保持 301 个，点击可选中并打开检查器；独立无头 Chrome 通过 CDP 原生鼠标拖动节点，草稿位置 (900,520)→(1040.75,607.30)、版本 4→5；视口刷新前后均为 `translate(-51.765px, -179.967px) scale(1.631)`；浅色与暗色下预警/错误条和状态标签对比度正常，控制台无错误。
- 清理：验收使用临时管理员、SQLite 数据、Vite 临时配置、无头 Chrome 页面与脚本，均位于已忽略的 `.tmp/v25/`，验收后已删除；未访问真实 MySQL 与 7865 后端，未启动或切换 ComfyUI。
- 兼容与回滚：`canvasSettings.viewport` 为可选字段，旧前端会忽略但保留；旧草稿没有该字段时仍按自动适配打开。保存状态、重试与体积检查只在前端，回滚仅撤销 V2.5 前端逻辑、样式、测试与文档，不删除画布表、草稿或历史版本；回滚后视口不再恢复，已写入的 `viewport` 留在 JSON 中不影响旧前端。保存重试不影响服务器乐观锁语义。
- 后续计划：V2 已完成；V3.0 生成节点技术 spike 见 `docs/无限画布开发计划.md` 第 6 节。

## 2026-10-21 无限画布 V2.4（作品库拖放）

- 原因与范围：V2.3 已有点击插入与检查器，但素材库仍是带遮罩的 Modal，用户无法把素材直接放到画布上的目标位置。本版把素材库改为非模态右侧 Drawer，并为图片/视频卡片增加 HTML5 拖放、落点反馈和统一的插入路径。只改前端组件、模型函数、样式与测试，不涉及后端接口、表结构、工作流注册表或 ComfyUI 配置，画布 JSON 结构不变。
- 素材面板：原 `Modal width={880}` 改为 Ant Design `Drawer`（`placement="right"`、`size={560}`、`mask={false}`、`styles.root.top=56`、`onClose` 可关闭、底部「完成」）。打开 Drawer 时画布仍可平移、缩放并接收落点；点击素材插入后 Drawer 不自动关闭，便于连续插入，替换模式仍沿用检查器的 `assetTargetNodeId` 分支并在替换后关闭。
- 拖放协议：卡片在素材可用且非替换模式时设置 `draggable`，`onDragStart` 通过自定义 MIME `application/x-zly-canvas-asset` 写入 `{source:"zly-canvas-library", version:1, item}`。`canvas-model.ts` 的 `encodeCanvasAssetDrag`/`decodeCanvasAssetDrag` 在写入和读取两端校验来源、版本、媒体类型、交付状态与 URL 安全性；`local`/`expired`/无可用地址/任意协议/音频条目不会被拖动或在落点被拒绝。
- 落点与插入：画布容器接管 `onDragEnter`/`onDragOver`/`onDragLeave`/`onDrop`，`onDragOver` 设置 `dropEffect="copy"`；嵌套子元素导致的 `dragleave` 用深度计数处理，`drop`/`dragend` 清理落点状态。落点先转成相对 `.canvas-stage` 的屏幕坐标，再经 `useReactFlow().screenToFlowPosition` 转成流坐标，传入统一的 `insertLibraryItem(item, dropAt)`。
- 统一插入函数：`createLibraryNode(item, position, {center})` 统一做可用性校验、节点工厂、`assetPath`/`sourceJobId` 溯源和居中偏移，节点尺寸由 `CANVAS_LIBRARY_NODE_SIZES`（图片 320×200、视频 360×220）提供。点击插入仍使用窗口中心并叠加 `nodes.length % 6 * 28` 级联偏移；拖放则把节点中心对齐指针落点。两条路径共用同一函数和同一自动保存/撤销链路。
- 落点反馈：拖放时显示 `.canvas-drop-feedback` 虚线高亮层、顶部「松开鼠标插入图片/视频」提示和按当前缩放计算的节点幽灵（尺寸 = 节点尺寸 × `useViewport().zoom`），鼠标离开画布或结束拖放后消失；幽灵使用 `pointer-events: none`，不会干扰命中测试。
- 受影响文件：`frontend/src/canvas/CanvasEditor.tsx`（Drawer、拖放处理器、落点反馈、统一插入函数）、`canvas-model.ts`（拖放 MIME/编解码、`CANVAS_LIBRARY_NODE_SIZES`、`createLibraryNode`）、`canvas-model.test.ts`（拖放载荷与落点 4 项）、`canvas.css`（素材 Drawer、拖放反馈、幽灵与光标样式）；同步 README、扩展指南和开发计划。后端与数据库无改动。
- 验证：`pnpm --dir frontend exec vitest run src/canvas/canvas-model.test.ts` 24 项通过；`pnpm --dir frontend test` 55 个测试文件、304 项通过；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend build` 通过；`python -X utf8 -m unittest backend.tests.test_canvas_store` 7 项通过。桌面验收使用隔离 SQLite 后端（7866）与隔离 Vite 开发页（5174，代理到 7866，局域网地址访问）：Drawer 打开时画布 `elementFromPoint` 仍命中 `react-flow__pane`；CDP 真实拖拽在 50%/100%/200% 缩放下落点流坐标 (848.96,454.85)/(848.96,482.87)/(848.96,496.88) 与节点中心 (849,455)/(849,483)/(849,497) 一致；图片和视频均可插入，视频草稿保留 `mediaKind: "video"` 与 360×220；点击插入按窗口中心 + 级联偏移落位且 Drawer 保持打开；拖放与点击插入均可 `Ctrl+Z` 撤销并写回服务器；暗色下幽灵按 2× 显示 640×400，Drawer、提示与卡片对比度正常，浏览器控制台无错误。
- 清理：验收使用临时管理员、SQLite 数据、Vite 临时配置、无头 Chrome 页面与脚本，均位于已忽略的 `.tmp/v24/`，验收后已删除；未访问真实 MySQL 与 7865 后端，未启动或切换 ComfyUI。
- 兼容与回滚：草稿仍为 `{nodes, edges, schemaVersion, canvasSettings}` JSON，插入节点仍使用既有 `image`/`video` 类型与 `data.url`、`label`、`mediaKind`、`assetPath`、`sourceJobId`，旧 V1/V2 前端可继续打开；拖放载荷只存在于浏览器内存，不写入草稿。回滚仅撤销 V2.4 前端 Drawer、拖放处理器、模型函数、样式与文档，不删除画布表、草稿或历史版本；回滚后点击插入仍可用，已保存的素材节点保持有效。
- 后续计划：V2.5 保存可靠性与性能与 V2.6 文档回归已完成；下一阶段 V3.0 技术 spike 见 `docs/无限画布开发计划.md`。

## 2026-10-21 无限画布 V2.3（节点检查器）

- 原因与范围：V2.2 完成选择与对齐后，V2.3 补齐节点属性的统一编辑入口，把原「修改图片」弹窗、图片地址修改和来源查看合并到右侧检查器，同时覆盖文字与画板。本版只改前端组件、样式与测试，不涉及后端接口、表结构、工作流注册表或 ComfyUI 配置；画布 JSON 结构不变。
- 检查器交互：选中单个节点时自动打开右侧 Ant Design Drawer；Drawer 无遮罩并 `top: 56px` 下移到编辑器顶栏以下，画布仍可平移、缩放和选择其他节点。关闭后可点工具栏「编辑选中节点属性」重新打开；多选或选中边时不显示检查器。原工具栏图片编辑图标改为 `SlidersHorizontal`，编辑入口不再依赖节点类型。
- 属性范围：图片/视频节点可编辑标签、说明/字幕和地址，查看媒体类型、`assetPath`、`sourceJobId`，并打开预览或从作品库替换；文字节点编辑 `text`；画板编辑 `label` 并显示当前尺寸；`unknown` 节点保持只读，显示提示、原始类型与节点 ID。
- 状态与保存：检查器通过 `useReactFlow().updateNodeData` 写回节点 `data`，复用编辑器既有 `nodes` 状态、1.2 秒防抖自动保存和 350 毫秒历史快照；撤销/重做、刷新恢复和冲突处理没有第二套状态。URL 使用组件内草稿，只有空值或合法值写回节点，非法输入只显示行内错误，不进入自动保存。
- 媒体 URL 校验：`canvas-model.ts` 新增 `isSafeMediaUrl(value, kind)`。图片接受 `http(s)://`、站内 `/...` 和 `data:image/`；视频接受 `http(s)://` 与站内 `/...`，不接受 `data:` 或任意协议。空地址允许保存为占位节点；添加图片、检查器与历史入口共用同一规则。
- 作品库替换：原作品库弹窗增加替换模式，通过 `assetTargetNodeId` 区分插入与替换。替换模式固定当前媒体类型、隐藏图片/视频切换，点击素材后更新 `url`、`assetPath`、`sourceJobId`、`mediaKind` 并保留已有标签；插入模式仍按原逻辑在视口中心创建节点。插入与替换共用 `insertLibraryItem` 分支，关闭弹窗时清空替换目标。
- 受影响文件：`frontend/src/canvas/CanvasInspector.tsx`（新增检查器主体）、`CanvasEditor.tsx`（单选自动打开、检查器 Drawer、插入/替换分支、添加图片入口）、`canvas-model.ts`（`CanvasMediaKind`、`isSafeMediaUrl`）、`canvas-model.test.ts`（媒体 URL 校验 2 项）、`canvas.css`（检查器与替换提示样式）；同步 README、扩展指南、开发计划和本文档。后端与数据库无改动。
- 验证：`pnpm --dir frontend exec vitest run src/canvas/canvas-model.test.ts` 20 项通过；`pnpm --dir frontend test` 55 个测试文件、300 项通过；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend build` 通过；`python -X utf8 -m unittest backend.tests.test_canvas_store` 7 项通过。桌面验收使用隔离 SQLite 后端（7866）与隔离 Vite 开发页（5174，代理到 7866，局域网地址访问）：标签/说明修改后草稿版本递增，原生输入事件到「已保存」耗时 1310ms；`javascript:alert(1)` 与视频 `data:video/mp4` 显示行内错误且未写入草稿；作品库替换更新来源并保留标签；预览、文字/画板/视频/未知节点检查器正常；文本修改后真实 `Ctrl+Z` 恢复；浅色与暗色下 Drawer、输入框、提示与来源信息对比度正常，浏览器控制台无应用错误。
- 清理：验收使用临时管理员、SQLite 数据、Vite 临时配置、无头 Chrome 页面、截图与脚本，均位于已忽略的 `.tmp/canvas-v23/`，验收后已删除；未访问真实 MySQL 与 7865 后端。
- 兼容与回滚：草稿仍为 `{nodes, edges, schemaVersion, canvasSettings}` JSON，检查器只写入既有 `data.label`、`data.caption`、`data.url`、`data.text` 和来源字段，旧前端可继续打开；`unknown` 节点仍不参与编辑。回滚仅撤销 V2.3 前端组件、样式、测试与文档，不删除画布表、草稿或历史版本；回滚后「修改图片」入口需随旧代码恢复，已保存的标签/字幕/地址保持有效。
- 后续计划：V2.4 作品库拖放已完成；V2.5 保存可靠性与性能、V2.6 文档与回归见 `docs/无限画布开发计划.md`。

## 2026-10-21 无限画布 V2.2（多选、对齐与连线管理）

- 原因与范围：V2.1 稳固节点模型后，V2 的下一增量补齐编辑器的批量选择与整理能力，包括多选复制/删除、连线的选择与删除、六向对齐、水平/垂直等距和快捷键说明。本版仍只改前端、前端测试与样式，不涉及后端接口、表结构、工作流注册表或 ComfyUI 配置；画布 JSON 结构不变。
- 选择模型：编辑器状态由单个 `selectedId` 改为 `selectedNodeIds` 和 `selectedEdgeIds`，通过 React Flow 的 `useOnSelectionChange` 接收节点与边选择。多选使用库默认键位：Windows/Linux 为 `Ctrl + 点击`，macOS 为 `⌘ + 点击`；框选为 `Shift + 拖拽`。点击空白、应用历史快照或删除后清空选择。工具栏按节点/边分别显示计数与可用性。
- 多选复制：`duplicateCanvasSelection(nodes, edges, selectedNodeIds, 32)` 为选中节点生成新 ID 并把位置偏移 32px，只复制源和目标都在选择内的边，再用 `buildEdgeId` 生成新边 ID；复制结果替换当前选择。函数不修改入参数组，空选择返回空结果。
- 多选删除：删除选中节点时同时移除所有关联边（无论另一端是否被选中），选中边可单独删除；工具栏删除与 `Delete`/`Backspace` 走同一处理路径，结果进入既有撤销/重做历史。
- 对齐与分布：工具栏「对齐与分布」提供左对齐、水平居中、右对齐、顶部对齐、垂直居中、底部对齐、水平等距、垂直等距。`alignCanvasNodes` 按所有选中节点的联合包围盒计算目标坐标；`distributeCanvasNodes` 至少需要 3 个节点，按轴向排序后保持首尾位置并均分剩余间距。节点尺寸优先取 `measured.width/height`，缺失时取 `style.width/height`，再取节点顶层 `width/height`；仍缺失按 0 处理。
- 撤销语义：执行对齐/分布前先调用 `flushHistory` 把当前状态压入历史栈，再应用位移，因此一次对齐操作可一步撤销；位置更新只影响 `position`，不重建节点或边。
- 快捷键说明：工具栏新增 Popover，列出撤销、重做、复制、删除、多选、框选、平移/缩放和双击预览。键盘处理跳过 `input/textarea/select/contenteditable`，并在图片地址弹窗、历史版本、素材库和媒体预览打开时禁用，避免与表单输入冲突。
- 受影响文件：`frontend/src/canvas/CanvasEditor.tsx`（选择状态、工具栏、多选复制/删除、对齐调度、快捷键）、`canvas-model.ts`（`alignCanvasNodes`、`distributeCanvasNodes`、`duplicateCanvasSelection` 与类型）、`canvas-model.test.ts`、`canvas.css`（快捷键 Popover 样式）；同步 README、扩展指南、开发计划和本文档。后端与数据库无改动。
- 验证：`pnpm --dir frontend exec vitest run src/canvas/canvas-model.test.ts` 18 项通过；`pnpm --dir frontend test` 55 个测试文件、298 项通过；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend build` 通过；`python -X utf8 -m unittest backend.tests.test_canvas_store` 7 项通过。桌面验收使用隔离 SQLite 后端（7866）与隔离 Vite 开发页（5174，代理到 7866，局域网地址访问），headless Chrome 通过 CDP 实际派发鼠标和键盘事件：三个节点多选并顶部对齐后坐标统一，真实 `Ctrl+Z` 恢复原坐标且撤销/重做按钮状态同步；多选复制节点 3→6、内部边 2→4，撤销恢复；多选删除清理关联边，撤销恢复；单条边删除只减少边，撤销恢复；浅色/暗色主题和快捷键 Popover 对比度正常，浏览器控制台无错误。
- 清理：验收使用临时管理员、SQLite 数据、Vite 临时配置、无头 Chrome 配置、截图与脚本，均位于已忽略的 `.tmp/canvas-v22/`，验收后已删除；未访问真实 MySQL 与 7865 后端。
- 兼容与回滚：选择状态和快捷键只存在于前端运行时，不写入草稿；对齐/分布/复制/删除仍通过既有序列化入口保存，草稿仍是 `{nodes, edges, schemaVersion, canvasSettings}` JSON，旧 V0/V1 前端可继续打开。回滚仅撤销 V2.2 前端代码与文档，不删除画布表、草稿或历史版本；回滚后多选和对齐入口消失，但已保存的坐标和边保持有效。
- 后续计划：V2.3 节点检查器、V2.4 作品库拖放、V2.5 保存可靠性与性能见 `docs/无限画布开发计划.md`。

## 2026-10-21 无限画布 V2.1（节点模型与兼容层）

- 原因与范围：在 V1 编辑能力上先稳固画布的数据模型，解决 `canvasSettings` 保存后丢失、`zIndex` 未保留，以及旧/新版本互开时未注册节点类型静默消失的问题。本版只改前端与前端测试，后端接口、表结构、工作流注册表和 ComfyUI 配置不变。
- Schema 版本：`CanvasDraft` 新增 `schemaVersion`，当前版本为 2。`parseCanvasContent` 对缺少或非法版本的草稿按 1 读取，兼容 V0/V1；`serializeCanvasDraft` 始终写入当前版本，因此旧草稿在首次编辑保存后升级为 2。
- 序列化范围：`serializeCanvasDraft(nodes, edges, options)` 现在同时写入 `schemaVersion`、可选的 `canvasSettings` 和节点 `zIndex`，并继续保留 ID、类型、位置、宽高、`parentId`、`extent`、`expandParent`、`draggable`、`style` 与 `data`。历史快照、自动保存、手动保存和冲突重载共用同一入口，避免设置只存在于服务器或只存在于撤销栈。
- 未知节点兼容：加载时把不在 `text/image/video/artboard` 中的类型归一为 `unknown`，把原始类型写入 `data.originalType`，业务 `data` 原样保留；保存时把 `type` 还原为原始类型并从 `data` 移除 `originalType`。因此新版本创建的节点在旧前端打开、移动、复制和保存后不会丢失类型或数据，升级前端注册该类型后可继续编辑。
- 未知节点卡片：新增 `UnknownCanvasNode`，显示「未识别节点」、原始类型和内容保留说明，保留左右连线句柄；节点可拖动、复制、删除，并参与撤销/重做与自动保存。删除未知节点时 React Flow 同时清理关联边。
- 解析健壮性：解析阶段为缺失或非法的 `position` 回落 `{x:0,y:0}`，为非对象 `data` 回落 `{}`，并继续过滤缺少字符串 `id` 的节点；不做阻断式字段校验，避免旧草稿因单个字段异常无法打开。URL 协议仍在添加/修改入口校验。
- 受影响文件：`frontend/src/canvas/canvas-model.ts`、`canvas-model.test.ts`、`CanvasNodes.tsx`、`CanvasEditor.tsx`、`canvas.css`；同步 README、扩展指南、开发计划和本文档。后端与数据库无改动。
- 验证：`pnpm --dir frontend exec vitest run src/canvas/canvas-model.test.ts` 14 项通过；`pnpm --dir frontend test` 55 个测试文件、294 项通过；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend build` 通过；`python -X utf8 -m unittest backend.tests.test_canvas_store` 7 项通过。桌面验收使用隔离 SQLite 后端（7866）与隔离 Vite 开发页（5174，代理到 7866，局域网地址访问）：含 `generator` 未知节点的草稿正常显示提示卡，指针拖动后自动保存仍保留原类型、`data`、`canvasSettings` 和 `zIndex`；删除节点同步删除关联边，`Ctrl/⌘ Z` 恢复节点与边；浅色和暗色主题均检查。
- 清理：验收使用临时管理员、SQLite 数据、Vite 临时配置、无头 Chrome 配置、截图与脚本，均位于已忽略的 `.tmp/canvas-v21/`，验收后已删除；未访问真实 MySQL 与 7865 后端。
- 兼容与回滚：服务端仍按不透明的 `{nodes, edges, ...}` JSON 保存，不认识 `schemaVersion` 或 `originalType`，接口和校验规则不变。回滚到 V1 前端可以打开 V2.1 草稿，`schemaVersion` 与 `canvasSettings` 会被忽略、未知类型节点仍会因未注册而无法渲染，但数据仍保留在服务器；回滚前应保留历史版本。回滚仅撤销本版前端代码与文档，不删除画布表、草稿或历史版本。
- 后续计划：V2.2 起的多选、对齐、检查器、拖放和保存重试见 `docs/无限画布开发计划.md`。

## 2026-10-21 无限画布 V1（新增当前基线）

- 原因与范围：在 V0 JSON 画布上补齐编辑器内的生产效率能力，包括本机撤销/重做、复制选中节点、从作品库插入图片/视频，以及可预览的视频节点。V1 仍以 JSON 草稿和乐观锁持久化，不引入 Yjs 实时协作、分享管理或素材生成节点。
- 撤销/重做：以 `serializeCanvasDraft` 生成的规范化 JSON 快照作为历史单元，变更停止 350 ms 后入栈，最多保留 50 步；新操作会截断重做分支，快照与当前内容相同或由程序应用历史时不记录。工具栏提供撤销/重做按钮，快捷键为 `Ctrl/⌘ Z`、`Ctrl/⌘ Shift Z` 和 `Ctrl/⌘ Y`；焦点在输入框、画板标题或弹层内时不拦截快捷键。刷新页面、加载服务器最新版本或恢复历史版本后历史栈重置，撤销结果参与正常自动保存。
- 节点复制：复制选中节点时生成新节点 ID、完整复制 `data/style` 并把位置偏移 `32px`，新节点成为当前选中项；工具栏与 `Ctrl/⌘ D` 行为一致，复制不会写入服务器草稿之外的新数据结构。
- 作品库接入：新增 `listCanvasLibraryItems` 复用既有 `GET /api/library`，只在弹窗打开时请求并缓存 30 秒。弹窗按图片/视频分组，过滤非图片/视频以及 `delivery_status` 为 `local`、`expired` 的素材；地址优先 `cloud_url`，其次 `/api/media/{path}`，最后 `download_url`。每个分组最多展示最近 80 项，点击后按当前视口中心插入节点，并保存 `assetPath` 与 `sourceJobId` 作为来源记录。后端接口、查询范围和账号隔离规则均未改动。
- 视频节点：新增 `video` 节点类型，画布内以静音、循环、`metadata` 预加载的视频展示，带「视频」标识和播放按钮；点击播放或双击节点打开带原生控制条的预览弹窗。图片节点同步支持双击预览。视频地址仍来自作品库的站内媒体路径，不新增上传或转码链路。
- 受影响文件：`frontend/src/canvas/canvas-model.ts`（历史模型、视频节点、作品库 URL/可用性规则）、`canvas-model.test.ts`、`canvas-api.ts`、`CanvasNodes.tsx`、`CanvasEditor.tsx`、`canvas.css`；同步 README、扩展指南与本文档。后端、数据库、工作流注册表和 ComfyUI 配置无改动。
- 验证：`pnpm --dir frontend exec vitest run src/canvas/canvas-model.test.ts` 9 项通过；`pnpm --dir frontend test` 55 个测试文件、289 项通过；`pnpm --dir frontend build` 通过（内含 `tsc -b`）。桌面端在隔离 SQLite 后端（7866）和隔离 Vite 开发页（与 5173 同源代码）上验收：工具栏与快捷键撤销/重做、按钮与 `Ctrl/⌘ D` 复制、作品库图片/视频页签与插入、视频节点和预览弹窗、自动保存与刷新恢复、浅色/暗色主题均正常；真实 MySQL 与 7865 后端未被访问或修改。
- 清理：隔离验证使用临时账号、SQLite 数据、生成的 PNG/MP4、Cookie 和临时 Vite 配置，验收后已全部删除；项目根目录、业务源码目录和真实画布数据未留下测试产物。
- 兼容与回滚：草稿仍是 `{nodes, edges}` JSON，文字/图片/画板节点与 V0 完全兼容，旧画布无需迁移。新增 `video` 节点类型只存在于本次持久化内容中，回滚到 V0 前端后该类型无法渲染，回滚前需保留 V1 版本或先删除视频节点；撤销历史仅存在于当前页面，不回写服务器。回滚仅撤销 V1 前端代码与文档，不删除画布表、草稿或历史版本。
- 后续计划：V2–V5 的增量拆解、已知限制、验证手册和新对话接手步骤见 `docs/无限画布开发计划.md`。

## 2026-10-21 无限画布 V0

- 原因与范围：参考 WorkRally 无限画布，先交付 JSON 优先的最小可用画布，验证 React 19、Ant Design 6、双主题和中文输入链路。V0 只包含画布列表、React Flow 编辑器、JSON 自动保存/版本历史，不接入 Yjs 实时协作、撤销栈、素材库或分享管理。入口为 `/canvas`（列表）和 `/canvas/:canvasId`（编辑器），桌面图标导航与移动导航新增「画布」。
- 前端：新增 `frontend/src/canvas/`，使用 `@xyflow/react@12.12.0`。支持文字、图片、画板三类节点，边连接、MiniMap、缩放控件和平移；节点可拖动、删除，文字双击编辑，画板可缩放并改标题，图片地址仅接受 `http(s)`、站内路径或 `data:image/`。编辑器用 `colorMode` 与 `--studio-*` 语义变量跟随根主题，浅色与暗色分别验证。画布工作区固定为 `calc(100vh - 56px)`，全局生成页的底部留白规则显式排除 `.canvas-workspace-main`，避免 MiniMap 和缩放控件被撑出视口。
- 持久化与一致性：新增 `sql/019_canvas.sql` 加法表 `canvas_projects`、`canvas_drafts`、`canvas_draft_versions`，MySQL 随既有启动迁移幂等建立；`backend/app/storage.py` 为临时 SQLite 建立同构表和索引。每个画布只有一份当前草稿和一个单调递增版本号，保存使用 `base_version` 乐观锁并在事务内锁定读，旧版本写入返回 409 及 `current_version`。内容必须包含 `nodes` 和 `edges`，上限 8 MB、3000 节点、6000 边；历史版本每个画布保留最近 200 条。校验和由服务端按内容计算，恢复历史版本会写成新的当前版本，不覆盖历史。
- API 与安全：新增 `GET/POST /api/canvas/projects`、`GET/PATCH/DELETE /api/canvas/projects/{canvas_id}`、`PUT /api/canvas/projects/{canvas_id}/draft`、`GET /api/canvas/projects/{canvas_id}/versions`、`POST /api/canvas/projects/{canvas_id}/versions/{version}/restore`。全部接口要求登录，写操作校验 CSRF；画布按 `owner_user_id` 隔离，管理员也不能读取他人画布。删除画布依赖外键级联清理草稿和历史。
- 前端行为：编辑变更后 1.2 秒防抖自动保存，顶部显示「保存中 / 已保存 / 未保存 / 保存失败 / 版本冲突」；手动保存提供即时反馈。版本冲突时不覆盖服务器内容，弹窗可重新加载最新版本。历史版本弹窗显示版本号、节点数和保存时间，可恢复并重新载入。列表显示节点数、当前版本和最近保存时间，支持新建、打开、重命名和删除。
- 受影响文件：新增 `backend/app/canvas_store.py`、`backend/tests/test_canvas_store.py`、`sql/019_canvas.sql`、`frontend/src/canvas/{CanvasWorkspace,CanvasEditor,CanvasNodes,canvas-api,canvas-model,canvas.css}.tsx|ts|css` 及 `canvas-model.test.ts`；接线 `backend/app/{main.py,models.py,storage.py}`、`frontend/src/{App.tsx,paths.ts}`、`frontend/src/index.css`、`frontend/package.json`，并同步 README 与扩展指南。`frontend/src/router.tsx` 通过 `STUDIO_ROUTE_PATHS` 自动注册路由，无需额外分支。
- 验证：`python -m unittest backend.tests.test_canvas_store -q` 7 项通过；`pnpm --dir frontend test` 55 个测试文件、284 项通过；`pnpm --dir frontend exec tsc -b` 与 `pnpm --dir frontend build` 通过。5173 桌面端浅色、暗色分别检查画布列表、编辑器、图片加载、画板、连线、自动保存、刷新恢复、历史版本恢复和 409 冲突；不进行移动端验收。真实 MySQL 验证数据已按画布、账号和会话 ID 清理。
- 兼容与回滚：新增表和接口均为加法变更，不改任务队列、工作流、ComfyUI、模型配置或既有页面协议；未配置画布时其余功能不受影响。回滚仅撤销画布路由、导航、前端模块、后端模块与初始化接线，保留三张画布表及其数据，不删除其它业务记录。

## 2026-10-23 MCP 智能剪辑工具（新增当前基线）

- 原因与产品行为：用户确认希望 MCP 客户端不仅能生成图片/视频，还能操作智能剪辑助手完成自动剪辑、视频铺轨、自动字幕和添加标题。本次把导演台既有的确定性剪辑与 ASR 能力暴露为 MCP 工具：客户端可列出工程/分集、读取时间线 revision 与画面/音轨摘要、预览并确认七种剪辑动作、调整铺轨顺序、查询或提交音轨转写，以及直接向文字轨添加标题/对白字幕。
- 协议与作用域：新增 `studio:edit`，与 `studio:read`、`studio:generate` 分开授权；工具总数由 9 增至 18。只持有旧作用域的令牌无法调用剪辑工具，需在 `/mcp` 重新授权。OAuth 流程、resource 绑定、令牌时效和账号隔离沿用 2026-10-21 基线。
- 工具与语义：`studio_list_edit_projects`、`studio_get_timeline`、`studio_get_transcript`、`studio_get_edit_action` 为只读；`studio_preview_edit`、`studio_reorder_edit` 只生成/调整待确认方案；`studio_confirm_edit` 原子写入时间线并保持幂等；`studio_add_text` 直接写文字轨；`studio_start_transcript` 显式提交 ASR（外发与计费，调用前需用户同意）。`operation` 复用 `video_arrange`、`subtitle_arrange`、`audio_subtitle`、`dialogue_cut`、`quick_cut`、`highlight_cut`、`hook_cut`，不新增第二套剪辑语义。
- 安全与一致性：所有读写按令牌绑定的账号隔离，工程/分集沿用导演台共享可见性，但方案、动作、文字修改和转写记录只属于本人；越权按 404 处理，管理员无跨账号能力。方案执行沿用 `EditingActions` 的 revision CAS 与幂等确认；`add_text` 在工程行锁与时间线行锁后校验 revision，拒绝文字轨时间重叠，限制 1000 字、30 分钟时间线和 `#RRGGBB` 颜色，避免静默覆盖并发修改。动作/工程不存在映射为 404，状态冲突为 409，参数错误为 400，助手或 ASR 未启用为 503。
- 持久化：不新增表、不迁移。时间线继续保存在 `ai_smart_edit_documents`（每账号每工程/分集一份），方案与证据继续保存在 `ai_assistant_records`；删除 MCP 工具不影响已有时间线、方案或转写记录。
- 前端：`frontend/src/mcp/McpPage.tsx` 的连接表把 `studio:read`/`studio:generate`/`studio:edit` 显示为「读取 / 创作 / 剪辑」，并更新接入说明、步骤文案和「自动剪辑与字幕」示例；页面继续使用根级主题与 Ant Design。
- 受影响文件：新增 `backend/app/mcp_gateway/editing_service.py`；修改 `backend/app/mcp_gateway/{config.py,routes.py}`、`backend/tests/test_mcp_gateway.py`、`frontend/src/mcp/McpPage.tsx`；同步 `docs/API.md`、本文件、`README.md`、`功能说明与扩展指南.md` 和 `docs/智能剪辑助手开发计划.md`。未修改导演助手执行逻辑、工作流注册表、ComfyUI 配置或既有 HTTP 剪辑接口。
- 验证：`python -X utf8 -m unittest backend.tests.test_mcp_gateway -q` 25 项通过（含转写委托、越权、revision 冲突、文字轨重叠和幂等确认）；`python -X utf8 -m unittest backend.tests.test_editing_assistant backend.tests.test_smart_edit backend.tests.test_director_assistant -q` 87 项通过；`pnpm --dir frontend exec tsc -b` 干净；`pnpm --dir frontend test` 58 个文件、365 项通过；`pnpm --dir frontend build` 通过（`✓ built in 7.42s`）。隔离 SQLite 后端（7866）+ 隔离 Vite（5174）+ 桌面 Chrome 实测 `/mcp`：浅暗主题连接表显示「读取 · 创作 · 剪辑」、参考图与示例区排版正常、「自动剪辑与字幕」可复制，控制台无应用错误；未访问真实 MySQL、7865 后端或 ComfyUI，未提交生成/转写任务。
- 清理：隔离后端（7866）、遗留的隔离 Vite（5174）和临时 SQLite 数据已停止/删除，`.tmp/mcp-edit` 已清理；未改动真实账号与媒体数据。
- 兼容与回滚：不改变既有 HTTP 剪辑接口、OAuth 协议、任务队列、工作流或 ComfyUI 配置；旧 MCP 客户端保持原有 9 个工具可用。回滚仅撤销 MCP 剪辑工具注册、`studio:edit` 作用域、`editing_service.py` 与前端标签/文案，保留 `ai_smart_edit_documents`、`ai_assistant_records` 及已确认的时间线，不删除任务、参考图或其它工作区改动。

## 2026-10-21 MCP 连接 V1（新增当前基线）

- 原因与产品行为：让每个工作台账号把创作能力接入 Codex、Cursor 或其他支持 Streamable HTTP 的 MCP 客户端。新增连接页 `/mcp`（账号菜单入口）与授权确认页 `/mcp/authorize`，服务地址为 `<对外 origin>/api/mcp`；客户端在对话中可查询工作流、上传或选取有序参考图、创建图片/视频任务、查询进度、获取结果和停止任务，只访问当前授权账号自己的内容。
- 协议基线：OAuth 2.1 Authorization Code + PKCE(S256)、动态客户端注册（RFC 7591）和 RFC 8707 `resource` 绑定；refresh token 每次使用即轮换，重放时撤销整个 grant。授权码 5 分钟、待确认请求 10 分钟、访问令牌 1 小时、刷新令牌 30 天。作用域 `studio:read`（读取工作流、参考图、任务和结果）与 `studio:generate`（创建与停止任务）。发现地址为 `/.well-known/oauth-protected-resource/api/mcp` 和 `/.well-known/oauth-authorization-server/api/mcp/oauth`；MCP 传输为无状态 Streamable HTTP，使用 JSON 响应。
- 安全与隔离：OAuth 凭据绑定 client、resource、subject 和可撤销 grant，不保存“当前用户”。授权码与令牌只存 SHA-256 指纹，客户端密钥使用现有 GRS 主密钥加密；访问令牌每次校验 grant、有效期与账号可用状态，撤销连接、禁用账号或未完成初始密码修改立即失效。`GatewayGuard` 校验 Host/Origin、resource、PKCE S256 格式、请求体大小和注册/令牌接口速率，并复用会话 Cookie + CSRF 保护浏览器侧授权。管理员同样只能操作自己的任务与参考图。
- 工具：`studio_list_workflows`、`studio_get_workflow`、`studio_list_reference_assets`、`studio_create_image`、`studio_create_video`、`studio_list_jobs`、`studio_get_job`、`studio_get_results`、`studio_cancel_job`。工作流详情只暴露 `workflow_registry.py` 标记为 `primary/advanced` 的参数；内部参数由后端默认值托管。参考图按 `reference_asset_ids` 顺序对应 `<Picture n>`，提交时复制为任务快照，之后删除素材不影响已提交任务。
- 可靠性：创建工具要求 `request_id`，以账号 + 标识的指纹建立唯一提交记录并比较参数指纹；网络重试返回原任务，参数不同返回 409。并发相同请求复用同一确定性任务 ID。结果下载链接 5 分钟有效，过期后重新调用 `studio_get_results` 获取；已本地交付的产物按“不可用”如实返回。
- 持久化：新增 `sql/018_mcp_gateway.sql` 的加法表 `mcp_gateway_records`（client/request/code/grant/access/refresh/reference/submission），MySQL 随既有启动迁移幂等建立；`McpStore` 为临时 SQLite 建立同构表与索引。授权状态变更使用事务和锁定读，刷新与撤销统一先锁 grant 再锁凭据，避免反向加锁死锁。任务、参考图文件与结果继续复用既有队列、存储和七牛云配置，不新增第二套任务系统。
- 前端：`frontend/src/mcp/` 提供连接页、授权页、客户端配置生成和参考图排序工具；账号菜单增加「MCP 连接」。连接页含 Codex / Cursor / 通用客户端页签、服务地址与可复制片段、授权连接列表与撤销、参考图上传/从生成图片选取/预览/删除/上下移动。页面沿用根级主题、Ant Design 和 `--studio-*` token，支持浅色与暗色。
- 接口：浏览器侧新增 `GET /api/mcp/info`、`GET/DELETE /api/mcp/connections[/{id}]`、`GET/POST /api/mcp/authorization-requests/{request_id}`、`GET/POST /api/mcp/references`、`GET /api/mcp/references/{id}/preview`、`DELETE /api/mcp/references/{id}`、`GET /api/mcp/generated-images`、`POST /api/mcp/references/from-output`；OAuth 端点位于 `/api/mcp/oauth/*`；工具入口为 `/api/mcp`。
- 配置与部署：`ZLY_AI_VIDEO_STUDIO_MCP_PUBLIC_BASE_URL` 必须是对外 HTTPS origin（仅本机回环允许 HTTP，不能带路径、凭据、查询或片段），本地开发在 `backend/.env.dev` 配置为 `http://127.0.0.1:5173`。`ZLY_AI_VIDEO_STUDIO_MCP_ENABLED=false` 为关闭开关，仅停用入口并保留数据。Nginx 需代理 `/api/` 与 `/.well-known/oauth-`，示例见 `docker/nginx/zly-ai-video-studio.conf.example`；Vite 开发服务器同步代理 `/.well-known/oauth-`。
- 受影响文件：新增 `backend/app/mcp_gateway/`、`frontend/src/mcp/`、`sql/018_mcp_gateway.sql`、`backend/tests/test_mcp_gateway.py`、`docker/nginx/zly-ai-video-studio.conf.example`；接线 `backend/app/main.py` 生命周期与路由、`backend/requirements.txt`（`mcp==2.3.0`）、`frontend/src/{App.tsx,paths.ts,router.tsx,ThemeProvider.tsx}`、`frontend/vite.config.ts`、`.env.example`、`compose.yaml`、`backend/.env.dev`；同步 README、扩展指南与 API 文档。
- 验证：`python -X utf8 -m unittest backend.tests.test_mcp_gateway -q` 35 项通过；完整后端回归 844 项中仅 3 项既有失败（`test_xiaji` 引用已删除模块、导演台剧本提示词断言、导演助手日志断言），与 MCP 无关。前端类型检查、279 项单测和 `pnpm --dir frontend build` 通过；5173 桌面 1440×1000 浅暗主题检查连接页、参考图上传/排序、授权页和连接列表，并完成真实 OAuth 到 `studio_list_workflows` 的端到端调用。
- 兼容与回滚：不改既有任务、工作流、ComfyUI 或供应商协议；MCP 关闭时其余功能不受影响。回滚仅撤销 MCP 路由注册、生命周期、新模块、前端入口与依赖，保留 `mcp_gateway_records` 数据和已上传参考图，不删除任务或回退其它工作区改动。开发验证继续使用 5173，静态产物只通过 `pnpm build` 清理后生成。

## 2026-10-20 剧本诊断 V1

- 原因与产品行为：参考用户提供的火龙漫剧 / WorkRally 上传页，新增独立的剧本审阅能力。首页入口与内容库当前文档入口统一进入 `/director/script-diagnosis`，`?id=`恢复报告，`?project=&doc=`预览项目来源，点击开始才发起任务。根路由必须显式注册该地址，避免被旧 `/director/:projectId` 书签回退规则拦截。
- 五项报告：总时长、新颖度、节奏、情绪、风险；展示核心结论、优先修改的三项问题、各维度优点与建议。每项问题必须附可核对的连续原文，点击在右侧原文定位。无综合分数；新颖度不做全网查重，风险为辅助审阅。支持复制与 Markdown 导出，不产生修改稿。
- 输入：复用既有 `extract_document`，新增 `.markdown` 别名；TXT支持UTF-8/GB18030，DOCX和文字型PDF复用既有解析。最多10份、单份20MB、规范化后合计100000 Unicode字符。逐文件回报错误，前端要求移除/重新上传错误项后再提交；顺序由客户端来源数组确定。DOC、空文件、扫描/加密/损坏PDF明确报错。二进制只在提取请求期间读取，不另存媒体或加入内容库。
- 数据与任务：`sql/017_script_diagnosis.sql` 加法建表 `ai_script_diagnoses`，MySQL随既有启动迁移幂等建立，Repository为临时SQLite建立同构表及索引。记录账号、可选工程/文档引用、幂等键、标题、来源快照、阶段、片段完成数、实际模型、报告与错误；`(owner_id, client_request_id)`唯一。历史按账号隔离、分页读取摘要，不加载大字段。项目沿用既有共享访问规则，服务端检查文档确实属于指定项目；诊断结果属于发起账号。
- 执行：独立两线程后台服务，复用已配置的统一OpenAI兼容客户端，单次执行固定客户端及默认模型，密钥不入诊断记录。正文按分集/章节和最多6000字符的片段审阅，块保留原文字符偏移；所有片段成功后两两汇总，避免截断长剧本。引用经Pydantic和字面子串校验后由服务端计算位置；汇总只能沿用已验证引用。结构/引用问题最多修复一次。明确总时长或完整镜头时长由程序汇总，其余使用分段估算区间。
- 生命周期：`queued → running → succeeded/failed/cancelled/interrupted`，运行阶段为`analyzing/summarizing`。前端2秒轮询实际完成片段数，不显示虚构流式报告。数据库条件认领与条件写入保证重复执行、取消及迟到响应不会覆盖终态；重启将未结束记录标为中断，用户重试用相同输入快照建立新记录，旧记录保留。来源删除后仍可查看及重试。当前后台执行沿用单工作台后端进程部署。
- 接口：新增 `/api/script-diagnoses` 能力、来源预览、提取、创建、分页历史、详情、取消、重试及删除已结束记录，沿用会话和CSRF；接口说明见API文档。独立诊断不创建工程、不触发镜头规划，不接入媒体任务队列，也不更改LLM/ComfyUI配置。
- 受影响文件：新增 `backend/app/script_diagnosis/`、`frontend/src/director2/script-diagnosis/`、上述SQL及专项测试；接线后端main生命周期、前端根路由/导演台路由、首页及内容库。同步README、扩展指南、API与导演台流程快照；视觉沿用根级主题、Ant Design及`--studio-*`，对话创作室样式不在本次变更范围。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_script_diagnosis backend.tests.test_director_assistant backend.tests.test_llm backend.tests.test_media_studio_schema -q`；`python -X utf8 -m unittest discover -s backend/tests -p 'test_*.py' -q`；`pnpm --dir frontend build`。5173桌面1440×900、1920×1080浅暗主题检查上传、排序、失败阻止、粘贴、取消/重试、真实报告、引用、复制/导出、刷新和历史；不做移动端验收。真实短剧本使用已保存的`XingChenAGI/Xing4.0-29B`，五项报告成功，明示时长汇总60秒。
- 兼容与回滚：旧工程/剧本文档、助手、任务及参数协议不变；保留当前工作区其它改动。回滚仅撤销本模块入口、路由、服务初始化和新增模块代码；保留独立诊断表与数据，不删除业务记录，不回退供应商配置。开发验证继续用5173，最终构建只通过`pnpm build`清理后生成静态产物。

## 2026-10-20 智谱官方预设与模型费用标记

- 原因：按对照对话补齐 LLM 的智谱官方入口，统一既有 VLM 智谱预设与费用显示，区分免费、付费和未知型号。
- 当前基线：`backend/app/zhipu_catalog.py` 统一维护官方地址、文本/视觉推荐型号、费用标记、来源与核对日期。新增仅超级管理员可读的 `GET /api/admin/providers/model-presets`；两个设置页读取同一份元数据，不依赖供应商 Key。LLM 默认 `glm-4.7-flash`，VLM 默认 `glm-4.6v-flash`；保留付费型号和手填 ID。已保存的旧模型不被自动替换。
- 协议：既有客户端一直直接在 Base URL 后追加 `/chat/completions`，本次以回归固定官方 `/api/paas/v4` 根路径，目录、探针和业务请求均不追加 `/v1`。官方端点的零温度省略；支持切换的型号在短探针中发送 `thinking.type=disabled`。GLM-5.3 和固定 Thinking 型号保留思考，探针使用 4096 Token 预算；GLM-5.3 使用 `reasoning_effort=low`。非智谱与中转地址保留既有策略。
- 费用：上游明确付费或任一输入/输出价大于零时标为付费；仅一侧价格为零或缓存免费不推断为免费，需输入和输出同时为零或明确免费标记。官方元数据仅对准确的智谱官方端点和准确型号生效，不向未知 Flash 后缀、FlashX、国际站或中转站套用。VLM 补充目录仍遵守 `free_only`。来源：[官方定价](https://docs.bigmodel.cn/cn/guide/start/pricing)（2026-10-20 核对）。
- 状态与凭据：保存、测试与目录仅在地址相同时复用已保存 Key；切换服务清空页面 Key 草稿，避免把另一家的凭据发送到智谱。VLM 显式复用由服务端决定真实 LLM 地址和凭据，响应新增可选 `llm_base_url` 供费用展示。测试结果只记录到匹配的已保存连接，修改连接参数时清除旧测试状态；测试回读不会丢掉未保存的表单草稿。目录结果绑定请求地址，旧地址的返回不参与新地址费用判断。
- 受影响文件：`backend/app/{zhipu_catalog.py,llm_client.py,llm_provider.py,vlm_provider.py,models.py,main.py}`、`frontend/src/admin/{LlmProviderSettings.tsx,VlmProviderSettings.tsx,provider-models.ts}`、`backend/tests/test_zhipu_provider.py`、前端对应测试、`docs/API.md` 与三份主文档；`.gitignore` 为新增的规范后端测试补充白名单，测试输出仍忽略。
- 兼容与迁移：只新增读取 API 和可选响应字段，不改数据库、端口、ComfyUI、模型文件或工作流协议；旧配置保留。没有 `/models` 能力或缺 Key 时仍可选择推荐型号，但目录失败会如实提示；型号是否可调用以账号权限及测试连接为准。
- 验证命令：`python -m unittest backend.tests.test_zhipu_provider backend.tests.test_llm backend.tests.test_vlm backend.tests.test_vision_runtime -q`；`pnpm --dir frontend build`；5173 桌面浅暗主题验证预设、费用、手填、测试草稿、保存重进及 VLM 凭据复用。浏览器使用独立 SQLite 和合成供应商响应，不更改现有供应商配置，也未使用真实智谱 Key 实测。
- 验收结果：相关后端 99 项通过；前端 52 个文件 / 270 项测试、类型检查及 `pnpm build` 通过。5173 的 1440×1000 桌面两页浅暗主题和保存/重进/显式复用已验证，无横向溢出；12 个价格状态的最低文字对比度为 4.65:1。独立复核为 `ship`，范围仅限本次功能。补充覆盖 VLM 复用开关前后更换地址不重绑旧独立 Key，以及省略/传 null 时继承已保存复用状态。未运行完整后端回归，未用真实智谱 Key 推理。
- 回滚：仅撤销本次差异，保留其它工作区改动，重启后端并刷新前端；无需数据回滚或迁移。

## 2026-10-20 智能剪辑助手与智能铺轨

- 日期与原因：2026-10-20，补齐 WorkRally 参考图中剪辑页面自动切换专属助手、对话中部分组按钮与铺轨授权闭环。
- 前端：`Director2App`向助手传入可选`{kind:"smart_edit",sequence_id}`；`DirectorAssistant`按工程/分集切换会话，账号隔离的恢复 key 来自剪辑`draft_key`，普通会话保留原工程关联。右栏在1440宽桌面为360px、1700以上为440px；编辑器素材/预览/属性与三轨保持可操作，关闭剪辑助手不切换工程创作模式。欢迎区中部按`EDITING_TOOL_GROUPS`显示「素材归位 → 智能铺轨」，有消息时收为可展开的「剪辑工具」。
- 铺轨规则：本集采用版视频按`project_sources`的分镜顺序排列，随后处理库内导入视频；自由剪辑按库内顺序。跳过已使用的分镜、素材ID及同地址视频，不以图片代替缺失视频。追加到画面轨末尾，使用原速、原声和按fps向下对齐的完整时长，保留已有片段。工程上限沿用300素材、200片段、30分钟，超限整体拒绝。
- API：在`/api/projects/{project_id}/smart-edit/{sequence_id}/actions`增加`POST /preview`（operation=`video_arrange`、revision、可选session_id）、`GET /{action_id}`和`POST /{action_id}/confirm`。预览返回有序items、数量、追加位置、总时长、跳过及缺视频数量与base_revision；确认返回succeeded及新文档snapshot。登录和CSRF沿用已有依赖；账号/工程/分集不符拒绝，过期版本409。
- 后端：新增`director_assistant/editing.py`，按钮与`editor_read`/`propose_edit`工具共用确定性动作服务。模型仅提案，不能指定其它目标或跳过授权。提案使用`ai_assistant_records`的`edit_proposal`记录，无新表或列迁移；每轮冻结会话剪辑上下文。确认在同一DbConnection事务中锁定提案及剪辑，条件更新revision并保存执行记录；失败整体回滚，重复确认返回同一结果。状态查询可核对丢失响应后的执行结果。
- 编辑器接线：预览/发送剪辑消息前先等待保存，确认期间锁定编辑；返回结果原子同步doc与revision，并把操作前状态压入一次撤销记录。撤销/重做沿用自动保存，重试前查询记录，旧执行结果不会覆盖后续版本。`EditDocument.version=1`及原接口、粗剪、原片保持兼容，不触发ComfyUI、FFmpeg导出或媒体生成。
- 受影响文件：助手与smart-edit前端、`Director2App`/`Director2ProjectDetail`、助手protocol/service、剪辑router、新增editing动作与专项测试；同步README、扩展指南、API、流程快照、助手V2及前端设计记录。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_editing_assistant backend.tests.test_director_assistant backend.tests.test_smart_edit -q`；`python -X utf8 -m unittest discover -s backend/tests -p 'test_*.py' -q`；`pnpm --dir frontend build`。5173桌面1440×900和1920×1080浅暗主题核对欢迎区、清单、取消、执行、撤销/重做、刷新与自然语言入口。
- 回滚：只回退本次接线、动作工具、接口及样式，保留新增JSON记录和现有剪辑文档；恢复普通助手及原粗剪即可，无需删除数据、修改供应商或回退SQL。历史pending提案不会自动执行。

## 2026-10-21 智能剪辑理解摘要与引流剪辑

- 日期与原因：2026-10-21，参考 WorkRally Smart Clip 的“视频理解 → 宿主策略卡 → 用户确认 → 确定性执行”流程，补齐剪辑助手的理解证据与五种钩子策略。REA Evidence、bundle 原文和差距矩阵见 [WorkRally 智能剪辑对照分析](WorkRally智能剪辑对照分析.md)。
- 理解摘要：`editor_read` 返回 `analysis`。自由剪辑为 `kind/video_count/clip_count`；分集为 `kind/beat_count/video_count/dialogue_beat_count/dialogue_seconds/highlight_candidates`，候选最多 8 项，含 `beat_id/sequence/heading/duration/dialogue_seconds/score/reasons`。评分基于分镜标题、动作、对白文本的高光关键词、对白秒数和文本信息量。该摘要是**分镜与配音文本统计，不是视频画面或音频识别**；提示词要求引用时说明依据。
- 引流剪辑：新增 `hook_cut` 与 `conflict_3s`、`climax_only`、`quote_open`、`ending_hook`、`trailer` 五种策略。`EditDraft` 要求 `hook_cut` 必带策略、其它操作不得携带；模型在用户未选择时必须先询问。`_hook_plan` 以 `min(30s, max(6s, 总时长×50%))` 为目标，按策略选择开场与后续镜头、排除结尾收束，并为每镜生成 `role/reason/trim`；确认后重建画面和配音轨，保留手工文字。
- API：`POST /api/projects/{project_id}/smart-edit/{sequence_id}/actions/preview` 的 `operation` 增加 `hook_cut`，新增可选 `strategy`（仅 `hook_cut`）；返回增加 `strategy/strategy_title/principle`，`items[]` 增加可选 `reason`。确认、版本 CAS、幂等、账号隔离与事务语义不变。
- 前端：`EditingOperation`/`HookStrategy` 扩展；「智能成片」组新增「引流剪辑」，点击显示五种策略菜单；授权弹窗显示策略名、逐镜保留/截取时长与理由、策略原则。理由文字 12px、无透明度，浅暗主题均保持对比。`STUDIO_ROUTE_PATHS` 同时注册 `directorProjectEdit`，直接打开 `/director/projects/:projectId/edit/:episodeId` 不再回退；`paths.test.ts` 覆盖精确路由。
- 兼容性：未新增表或迁移，继续复用 `ai_assistant_records` 的 `edit_proposal`。旧操作、旧提案和旧客户端请求不受影响；旧记录缺少策略字段时前端按原样显示。不触发 ComfyUI、FFmpeg 导出或媒体生成。
- 受影响文件：`backend/app/director_assistant/{protocol,editing,service}.py`、`backend/app/media_studio/routers/smart_edit_router.py`、`backend/tests/test_editing_assistant.py`；`frontend/src/director2/smart-edit/api.ts`、`frontend/src/director2/assistant/{editing-tools.ts,editing-tools.test.ts,DirectorAssistant.tsx,assistant.css}`；对照文档、助手V2、README、扩展指南、API、流程快照及截图 61–65。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_editing_assistant backend.tests.test_director_assistant backend.tests.test_smart_edit -q`（81 项通过）；`pnpm --dir frontend build`（55 个测试文件、284 项测试、类型检查与构建通过）。全量后端 `unittest discover` 共 865 项，仅 2 项既有失败：`test_xiaji` 导入已删除模块、剧本提示词大小写断言，与本次功能无关。Vite 开发页实测五种策略菜单与授权理由；确认 `conflict_3s` 后得到 3 个画面、2 条配音和 1 条手工文字（8.75 秒），刷新后仍保留，授权与结果截图归档 `docs/design-ref-director/61`–`65`。
- 回滚：仅撤销上述前后端代码、接口字段和文档，保留历史提案与剪辑文档；历史 pending 提案不会自动执行，无需删除数据或切换供应商。

## 2026-10-21 真实视频理解（关键帧 + VLM）

- 日期与原因：2026-10-21，把上一节的纯文本统计升级为**显式触发的真实画面理解**，让理解摘要、引流评分和授权理由有可核对的视觉证据；不伪造 ASR 或 `understand_full`。最初每素材固定抽 2 帧，镜头边界检测与逐镜分析随后在同日「逐镜画面理解」章节补齐。
- 后端：新增 `backend/app/director_assistant/understanding.py`。用户显式触发后，服务从本集采用版时间线取视频，经可信下载、ffprobe 探测后抽取 2 张关键帧（0.2 秒与中点），以 data URL 调用当前默认 VLM 的 `analyze_video_shot`，返回单镜 `description/camera/subjects/keywords`。逐镜隔离失败，每镜最多重试 2 次；模型名写入结果。结果存 `ai_assistant_records` 的 `media_understanding`，**无新表或迁移**；账号、工程、分集隔离。
- 失效与并发：记录 `source_signature`（素材/时间线标识）。源视频或时间线变化后，`read` 返回 `stale`，`summary` 不下发旧条目，`evidence` 返回空；重新执行覆盖旧结果。同一范围运行中再次启动返回 409；遗留 running 记录超过 15 分钟后按失败回收，可重新触发。
- 证据链：`editor_read.analysis.understanding` 提供状态与条目；`hook_cut`/`highlight_cut` 评分把画面关键词、机位、主体并入理由，未理解或失败镜头不参与画面加权；授权弹窗显示「理解依据：视频画面 N 个镜头的关键帧描述」，逐镜理由带「画面理解：…」。原有确定性剪辑、授权、revision CAS、幂等确认与账号隔离不变。
- API：`GET/POST /api/projects/{project_id}/smart-edit/{sequence_id}/understanding`，POST 可选 `force` 重跑；写接口沿用登录与 CSRF。返回 `status/updated_at/model/items/stale`，运行中返回进度。实现位于 `backend/app/media_studio/routers/smart_edit_router.py`。
- 前端：剪辑助手新增理解卡片，展示未开始/运行/完成/失败/过期状态、进度、VLM 模型与完成时间，可展开逐镜描述并重跑；运行中轮询。样式使用 `--director-*` 双主题 token。
- 修复：GLM-4.5V 经 SiliconFlow 可能把 JSON 包在 `<|begin_of_box|>…<|end_of_box|>` 中，`llm_client.analyze_video_shot` 改为提取首个 `{` 到末个 `}` 再解析，并对单镜增加重试；真实 3 镜工程验证通过。
- 兼容性：旧记录、旧提案和未触发理解的剪辑流程不受影响；不触发 ComfyUI、FFmpeg 导出或媒体生成。理解依赖已配置的默认 VLM 与可下载的媒体域名；未配置时返回明确错误且不影响其它操作。
- 受影响文件：新增 `backend/app/director_assistant/understanding.py`、`backend/tests/test_media_understanding.py`；修改 `backend/app/llm_client.py`、`backend/app/director_assistant/{editing,service}.py`、`backend/app/media_studio/routers/smart_edit_router.py`；`frontend/src/director2/smart-edit/api.ts`、`frontend/src/director2/assistant/{DirectorAssistant.tsx,assistant.css}`；助手V2、对照文档、README、扩展指南、API、流程快照及截图 66–69。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_media_understanding backend.tests.test_editing_assistant backend.tests.test_director_assistant backend.tests.test_smart_edit -q`（93 项通过）；`pnpm --dir frontend build`（55 个测试文件、294 项测试、类型检查与构建通过）。5173 桌面 1440×900 浅暗主题实测：3/3 镜完成、授权弹窗显示理解依据与逐镜画面理由，确认后时间线为 6.13 秒。
- 回滚：移除理解路由、服务、前端卡片与证据接线，并回退 `llm_client` 的 JSON 提取即可；历史 `media_understanding` 记录可保留，读取接口消失后不影响剪辑与提案；无需数据库迁移或供应商切换。

## 2026-10-21 剪辑视频理解：镜头边界检测与逐镜分析

- 日期与原因：2026-10-21，上一版每条素材只取 2 帧，素材内部切镜会丢失；本版先用 FFmpeg 检测镜头边界，再对采样镜头各抽 2 帧调用 VLM，使理解摘要与授权证据落到镜头粒度。仍不做 ASR 与 WorkRally 的整片 `understand_full`。
- 镜头检测：`backend/app/video_analysis.py` 新增 `detect_scenes(path, duration)`，使用 `select='gt(scene,0.32)',showinfo`，解析 stderr 中的 `pts_time` 生成区间；最短镜头 0.8 秒，异常或未检出时回退为整段素材 1 个镜头。`showinfo` 日志固定合并 stderr，避免漏解析。
- 采样上限：每条素材最多采样 4 个镜头，整个时间线最多 40 个；超限按等距抽样，保证每条素材至少 1 个。每个采样镜头在 0.2 秒与中点抽 2 帧，调用默认 VLM 的 `analyze_video_shot`；单镜失败隔离、最多重试 2 次。
- 数据结构：仍复用 `ai_assistant_records.media_understanding`，无新表或迁移。`items[]` 增加 `detected_count/sampled_count/shots[]`，每个镜头含 `index/start/end/duration/status/description/camera/subjects/frames/error`；素材级 `description/camera/subjects` 由成功镜头聚合。`summary` 增加 `detected_shot_count/shot_count/shot_analyzed_count/shot_failed_count`，保留 `video_count/analyzed_count/failed_count`。
- 证据链：`evidence()` 在成功或部分成功时返回素材证据与 `shot_used_count`；`hook_cut`/`highlight_cut` 授权弹窗的「理解依据」改为「镜头边界检测后采样的 N 个镜头关键帧描述」，`extra.understanding` 增加 `shot_count/shot_analyzed_count/shot_used_count`。过期、失败或旧记录没有镜头字段时，前端回退到素材级文案。
- 前端：理解卡片显示检测/采样/成功镜头数，逐素材展开后列出内部镜头的时间范围、描述、机位、主体与失败原因；运行中显示「共检测 X 个镜头 · 已采样 Y 个 · 已理解 Z 个」。`api.ts` 增加 `UnderstandingShot/UnderstandingSummary` 与 `EditingAction.understanding` 的镜头字段，样式继续使用 `--director-*` 双主题 token。
- 兼容性：旧 `media_understanding` 记录按原素材级结构读取；未触发、过期或失败的理解不参与评分。依赖服务器 FFmpeg/ffprobe；不做音频转写、全片语义分段、去废片或智能拆条。
- 受影响文件：`backend/app/video_analysis.py`、`backend/app/director_assistant/{understanding,editing}.py`、`backend/tests/{test_media_understanding,test_video_analysis}.py`；`frontend/src/director2/smart-edit/api.ts`、`frontend/src/director2/assistant/{DirectorAssistant.tsx,assistant.css}`；README、扩展指南、API、流程快照、对照分析及截图 70–73。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_video_analysis backend.tests.test_media_understanding backend.tests.test_editing_assistant backend.tests.test_director_assistant backend.tests.test_smart_edit -q`；`pnpm --dir frontend build`。5173 桌面实测：2 条素材检测到 5 个内部镜头，采样分析 5/5；授权弹窗显示镜头级理解依据，确认 `conflict_3s` 后时间线为 2 个片段、6.38 秒，刷新后仍保留。
- 回滚：撤销 `detect_scenes`、逐镜采样与前端镜头展示，恢复按素材 2 帧的理解与证据文案；历史记录与剪辑文档保留，无数据库迁移或供应商切换。

更新时间：2026-10-22（含智能剪辑助手 A5 音轨转写与音轨字幕、无限画布 V2.5/V3.1/V3.2/V3.3/V4.0/V4.1/V4.2、真实视频理解、逐镜画面理解、智能剪辑理解摘要与引流剪辑）

## 2026-10-20 Thinking 视觉模型参数兼容修复

- 原因：共用客户端向所有非 GPT 模型发送 `enable_thinking=false`，Qwen3-VL-30B-A3B-Thinking 的上游拒绝该参数，VLM 测试连接返回 HTTP 400。
- 当前基线与文件：`backend/app/llm_client.py` 仅给名称匹配原版混合推理 Qwen3 的模型添加该开关；固定 Thinking、Instruct-2507、VL 及未知模型不携带。保留 DeepSeek V4 的 `thinking.type=disabled` 与 GPT 的既有参数处理。回归在 `backend/tests/test_llm.py`、`backend/tests/test_vlm.py`，覆盖实际多模态请求及 VLM 测试接口。
- 兼容性：测试连接、图像分析和文本创作共用该修复；不改 HTTP API、数据库或凭据。原版 Qwen3 仍关闭可切换思考，独立 Thinking 模型使用上游默认推理模式。升级后重启后端即可。
- 验证：`python -m unittest backend.tests.test_llm backend.tests.test_vlm backend.tests.test_vision_runtime -q`（82 项通过）；`pnpm --dir frontend build`。使用当前已配置的供应商和凭据，临时指定 `Qwen/Qwen3-VL-30B-A3B-Thinking` 的真实连接测试成功，未修改保存的模型。
- 验收结果：运行中的 5173 `/api/admin/providers/vlm/test` 使用与页面相同的模型及凭据复用开关返回 200、状态成功；原配置保持不变。前端 259 项测试、类型检查及构建通过。
- 回滚：仅撤销本次客户端、测试和文档改动并重启，无数据迁移。
- 参考：[Qwen3 混合推理说明](https://huggingface.co/Qwen/Qwen3-8B)、[Qwen3-VL Thinking 官方模型卡](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Thinking)。

## 2026-10-20 LLM 配置保存的 MySQL 字段迁移修复

- 原因：助手模型列表新增的 `assistant_models_json` 只在 SQLite 初始化时补列，MySQL 启动分支提前返回，旧库保存 LLM 配置报 `1054 Unknown column` 并返回 HTTP 500。
- 当前基线：`JobStore.initialize()` 在 MySQL 建表后通过既有 `ensure_column` 幂等补列；`sql/001_init_mysql.sql` 的 LLM 建表定义同步包含可空 TEXT 字段。已存在字段不重复执行 ALTER，不重写既有配置。
- 受影响文件：`backend/app/storage.py`、`sql/001_init_mysql.sql`、`backend/tests/test_media_studio_schema.py` 及三份维护文档。
- 兼容性与迁移：升级后重启后端自动补字段；原地址、模型、加密密钥和任务数据保留。空列表或 NULL 继续回退当前默认模型；HTTP API、端口及 ComfyUI 配置不变。
- 验证命令：`python -m unittest backend.tests.test_media_studio_schema backend.tests.test_llm backend.tests.test_director_assistant -q`；`pnpm --dir frontend build`；5173 桌面验证配置保存及刷新后回显。
- 验收结果：相关后端 94 项测试通过，前端 259 项测试、类型检查与构建通过；真实 5173 页面保存返回 200 并显示成功反馈，刷新回显一致，原有地址、模型和密钥保持不变。未运行后端全量回归。
- 回滚：仅撤销上述文件本次修复并重启；可保留新增列，不删除用户配置，也不回滚其它工作区改动。

## 2026-10-20 导演台智能剪辑

- 原因：按用户提供的 WorkRally 智能剪辑截图，为导演工程增加素材、预览、属性与时间线相连的剪辑工作区，复用现有工坊媒体和七牛云存储。参考 OpenCut 的编辑器分区；采用独立实现，不引入第三方整套编辑器或新的前端依赖。
- 前端：新增 `frontend/src/director2/smart-edit/`，路由为 `/director/projects/:projectId/edit/:episodeId?`（无分集时为自由剪辑）；项目菜单和工坊合成页均有入口。进入剪辑时右侧自动停靠智能剪辑助手，编辑器相应收窄；主题仍由根 Provider 管理。左工具轨和素材面板、中预览、右属性、底部文字/画面/音频三轨。包括素材导入、顺序粗剪、分帧拆分、裁切/移动/磁吸/排序、清除空隙、撤销重做、文字、画面变换、8 个基础色效、速度、音量/静音和淡入淡出。
- 状态协议：`EditDocument.version=1`，`settings` 保存比例、fps、背景，`assets` 保存媒体 URL 和实际时长，`clips` 保存素材引用与三轨片段；`start` / `duration` 为输出秒且对齐项目帧率，`in_point` 为原素材秒，消耗原片区间为 `duration * speed`。同轨不重叠，跨轨可以叠加；最多 300 个素材、200 个片段、30 分钟。每个分集独立保存；`main` 是自由剪辑。原片地址随已采用 Take 固化，刷新素材追加新版本，不替换正在编辑的原片。
- API：新增 `/api/projects/{project_id}/smart-edit/{sequence_id}` GET / PUT；`/{sequence_id}/sources` GET；`/{sequence_id}/upload` POST；`/exports/mp4` POST；`/exports/{job_id}` GET；`/exports/bundle` POST。读取沿用登录，写入沿用 CSRF。服务器再次验证工程、同轨重叠、原片区间和有限数字，不接受本地路径或任意服务器地址下载。
- 存储：`sql/016_smart_edit.sql` 新建 `ai_smart_edit_documents`，用项目、账号、序列派生 ID 隔离文档；`revision` 条件更新阻止多窗口覆盖（409）。浏览器按服务器返回的账号隔离 key 暂存未保存草稿；网络失败保留，冲突先下载备份再加载云端。新安装表外键随项目级联删除。既有 `ai_project_jobs` 增加类型 `smart_edit_export`；通用任务 payload 只含参数摘要，完整导出快照保存在账号隔离的文档表，避免通用详情泄露其他账号的完整剪辑。
- 导出：`smart_edit_render.py` 通过本机 CPU FFmpeg 真正执行裁切/变速/缩放/位置/旋转/透明度/色效/文字/淡入淡出及音轨混合，再发布到现有七牛云。每进程单个导出 worker，最多 4 个待完成任务；重启后的遗留任务查询时标记失败，可重新导出。原片和上传单文件限制 512 MB，工程 ZIP 素材总量限制 2 GB；临时媒体用系统临时目录并自动清理。素材下载只接受管理设置中的当前媒体域名，不跟随跳转。未调用 ComfyUI 或生成模型。
- 交换兼容：JSON 是完整可恢复工程；XML / OTIO 交换剪辑点、轨道和速度，样式仍由目标软件解释。剪映基础草稿沿用 `frontend/src/media/jianying-draft-builder.ts` 的既有结构，保留基础音视频剪辑和变换，文字/色效/淡入淡出需重建，客户端兼容性尚未实机验证。不生成伪装的 `.prproj`。ZIP 始终附 JSON 与使用说明，可附已用素材；离线素材重连面向外部后期软件，工作台 JSON 恢复仍需可访问的原始媒体地址。
- 字幕一致性：前后端共用同一逻辑画宽的显式断行规则，保留手动换行；后端复用已有 Pillow 依赖绘制居中行盒为透明字幕层，再由 FFmpeg 按时间、透明度和淡入淡出合成，避免系统字体的 drawtext 多行度量与浏览器不同。UI 使用同一行高和相对内边距。视频代表帧从非零时间提取并重试黑帧，提取失败明确回退示意。
- 受影响文件：上述目录、`smart_edit_document.py` / `smart_edit_render.py` / `smart_edit_service.py`、`routers/smart_edit_router.py`、项目路由注册、`main.py` 的 OpenAPI 标签、`Director2ProjectDetail.tsx`、`paths.ts`、工坊合成入口、任务类型/预览、测试、`.gitignore` 与四份主文档。
- 验证：`python -X utf8 -m unittest backend.tests.test_smart_edit -q`；`python -X utf8 -m unittest discover -s backend/tests -p 'test_*.py' -q`；`pnpm --dir frontend build`；真实 `http://127.0.0.1:5173` 的 1440×900 浅暗主题与交互。单元测试覆盖账号/工程/分集隔离、旧版本拒绝、非法工程、真实 FFmpeg、工程包；浏览器验收音频上传、粗剪、文字、拆分、排序、撤销、特效、自动保存和刷新恢复。真实接口导出 2 秒 H.264/AAC MP4，ffprobe 核对 1280×720 与准确时长。全量后端既有失败是 API 文档标签断言、剧本场景账本提示断言以及已下线 `test_xiaji` 模块导入，见恢复基线；本次不掩盖这些结果。
- 回滚：撤销本次新增模块、路由菜单/注册与文档改动并重启；保留新表和已有导出媒体即可，无需迁移旧项目、恢复业务数据或切换供应商。仅在确认不再保留剪辑工程后另行清理新表；不要回滚工作区其他已有修改。

2026-10-20 验收结果：前端 50 个文件的 259 项测试、类型检查与构建通过；新增后端 12 项通过，包含真实 FFmpeg 合成。后端全量 768 项保留上述既有 2 失败、1 导入错误。实际导出的 OTIO 经官方 OpenTimelineIO 0.18.1 解析成功（3 轨、5 片段）；长中文和手动换行字幕另经真实 MP4 抽帧对照。当前开发库的新表已对齐 `utf8mb4_unicode_ci` 与项目级联外键。验收临时账号、项目和本次上传/导出的云端测试对象在完成后清理，界面基线保存至 `docs/design-ref-director/28`–`31`。

## 2026-10-19 导演台全局智能助手 V2（新增当前基线）

- 原因：以Skill、专家、知识检索、会话模型组合替代固定AI入口，独立保存草稿，采纳后写入，媒体单独确认。
- 文件：`backend/app/director_assistant/`、`frontend/src/director2/assistant/`、`sql/015_director_assistant.sql`，主应用、LLM供应商、项目壳、管理页及媒体模型上下文同步接线。
- 接口和存储：新增`/api/director-assistant`，三表保存账号隔离的类型化聚合、顺序事件与项目锁；LLM配置幂等增加`assistant_models_json`。消息内顺序独立于时间戳。
- 兼容：保留项目路由、mode参数、旧AI接口、四阶段ID与制作配方；旧任务可恢复或取消，新旧入口共用项目写入互斥。
- 验证：`python -m unittest backend.tests.test_director_assistant`、完整后端回归、`pnpm --dir frontend build`及5173桌面浅暗主题检查；恢复代码已有失败单列。
- 验收结果：助手41项新增测试通过；后端发现式回归770项，仅保留恢复前已有2失败和1导入错误；另159项角色/H3/分镜媒体回归通过。前端50个文件、259项测试通过，TypeScript与正式构建通过。为解除恢复基线构建阻塞，修复9处原有类型错误，未回滚恢复代码。真实5173完成问答、剧本与11项资产的预览采纳、修订、个人ZIP资源版本、资料上传解析、跨页关联保持及媒体提案检查；未确认或执行真实媒体生成。详细失败项与范围见助手说明。
- 回滚：设置`ZLY_AI_VIDEO_STUDIO_DIRECTOR_ASSISTANT_V2=false`并重启，保留新表和历史。详见[助手V2说明](导演台智能助手V2.md)。

## 2026-10-19 导演工程基本信息与自动命名

- 原因：工程名称、简介已有更新接口但没有界面入口，AI 剧本标题也没有同步到项目条和首页。
- 行为：项目顶栏「编辑基本信息」使用 Ant Design Form / Input / Modal，支持名称与简介保存、错误提示和空白/255 字符校验，两个创作模式都可编辑。项目条颜色改用 `--studio-*` 双主题变量，长名称省略显示。
- 自动命名：`AiGenerationService._adapt_recipe` 仅在 `script` 阶段落库后调用 `ProjectService.sync_generated_script_info`，从已生成的 `script.title` / `script.summary` 填入默认工程名及空简介；来源记录在现有 `settings_json.extra` 的 `name_source` / `description_source` 和 `ai_generated_name` / `ai_generated_description`。手动保存分别标为 `manual`，后续重新生成不覆盖；存量自定义名称/简介保持。更新使用旧名称、简介、设置快照作条件，避免覆盖同时发生的手动编辑。AI 阶段结束刷新父层项目数据，自动名称无需硬刷新。
- 受影响文件：`backend/app/media_studio/{models.py,services/project_service.py,services/ai_generation_service.py}`、`frontend/src/director2/{Director2App.tsx,Director2ProjectDetail.tsx,project-detail.css,panes/Director2AiStudioPane.tsx}`、`backend/tests/test_director_project_info.py`、`.gitignore` 和维护文档。`Director2App` 只保留尺寸 token，移除强制浅色算法及颜色覆盖，继承根级主题以保证新弹层的暗色对比度。
- 兼容性：沿用 `PUT /api/projects/{id}`，不新增 API、表或迁移；可选 extra 字段旧代码可忽略。端口和远端 ComfyUI 连接不变。
- 验证：`python -m unittest backend.tests.test_director_project_info backend.tests.test_director2_ai_generation -q`（51 项通过，新增 7 项 SQLite 测试）；`python -m unittest discover -s backend/tests -p 'test_*.py'`（717 项，原有 2 失败、1 导入错误，与恢复基线相同）；`pnpm --dir frontend build`（245 项前端测试通过，TypeScript 被恢复基线已记录的 9 处旧错误阻塞，未改写原静态产物）。5173 桌面验证实际项目入口、临时工程的自动命名、名称/简介编辑、空白校验、保存刷新与手动信息保护；浅/暗参考截图见导演台流程文档。
- 回滚：仅撤销上述文件本次功能变更并重启 7865；已保存的项目名称和简介可继续读取，来源字段可保留，无需迁移或恢复业务数据。

## 2026-10-19 恢复最近一次部署镜像代码

- 原因：用户要求将代码恢复到最近一次 `zly-ai-video-studio_latest` 打包时的版本。根目录普通镜像包构建时间为 `2026-09-20T03:23:02.765460036Z`（北京时间 11:23:02），比带数据包及 `packages/` 内的包更新。
- 来源：镜像 config ID 与原包 SHA256 记录在备份 `restore-manifest.json` 的 `image_id`、`archive_sha256` 中。镜像内 352 个有效文件在恢复后逐一通过 SHA256 比对，随后仅补充本次维护文档。
- 范围：`backend/`、`local_video_studio.py`、`sql/`、`frontend/dist/` 与 `docs/` 使用镜像原文件；其他已跟踪项目代码使用打包前最后提交 `9965babffaaf9005a0d6493b945c987360cdc690`。镜像没有前端源码或 source map，`frontend/src/` 只能恢复到该 Git 提交，不能声称与原编译产物完全可复现。
- 当前导演台回到项目级 AI／手动模式与剧集工坊，后续统一工坊、制作方案、全局资产等新代码从恢复分支移除。旧流程与原截图基线见 `docs/导演台流程与界面结构.md`。
- 兼容性：没有执行数据库回退；保留业务数据、媒体、所有实际 `.env*` 配置、`docs/存储配置.md`、当前 `AGENTS.md` 与 `.gitignore`。7865 与 5173 端口不变，ComfyUI 继续使用已保存的远端实例；未启动或切换 ComfyUI。
- 验证命令：`python -X utf8 -m unittest discover -s backend/tests -p "test*.py" -q` 运行 710 项，2 项失败、1 项错误；失败为 API 文档断言和剧本场景账本提示断言，错误为历史 `test_xiaji` 引用已下线模块。`pnpm --dir frontend build` 中 48 个测试文件、245 项测试通过，TypeScript 检查报告 9 处旧错误，未进入清理或重建静态产物阶段。原镜像静态前端仍保留，不将本次验证标为全量通过。
- 补充专项：`python -X utf8 -m unittest backend.tests.media_studio_test_character_content backend.tests.media_studio_test_h3_video backend.tests.media_studio_test_storyboard_images -q`，159 项全部通过。
- 运行检查：恢复后 5173 首页、7865 静态首页与 `/api/health` 均返回 200，实际远端 ComfyUI 可达。桌面浏览器到达登录页；未登录的业务页面和真实生成未验收。
- 恢复前备份：父目录 `code-backups/zly-ai-video-studio-before-restore-20261019-164754/workspace-before-restore.zip`，995 个文件，已校验 ZIP 完整性；清单与原文件 SHA256 见同目录 `restore-manifest.json`。Git 安全分支 `codex/backup-before-latest-20261019-164754` 保存原工作区快照，原 `dev` 分支仍指向 `53a9ae1`。
- 回滚：先停止本机 5173／7865，保留当前恢复分支，再依据备份清单恢复 ZIP 中的原工作区文件，并切回原 `dev` 分支；已跟踪的原修改另可从上述 Git 安全分支恢复。原来未跟踪及忽略的文件以 ZIP 为准，原删除状态以 `git-status-before.bin` 为准。数据库与媒体无需回滚。

## 2026-09-20 导演台2 任务列表瘦 payload，避免占满连接

- 变更原因：线上点「全部任务」后 `GET /api/projects/{id}/jobs` 把每条任务的 LONGTEXT `payload_json` 和 N+1 资产查询打进同步线程池，其它 API 一起排队。
- 当前基线：列表返回瘦 `payload`（镜号、结果 URL、精简 `shots`/`stream`，不含草稿/`request_body`/`payload_json`）。`GET /api/projects/{id}/jobs/{job_id}` 返回完整 payload。全部任务轮询进行中 2 秒、空闲 8 秒且禁止重叠。内容库规划兜底改为拉单条任务。`media_studio.db` 对 autocommit 查询复用最多 16 条 MySQL 连接。
- 受影响文件：`backend/app/media_studio/services/job_payload.py`、`project_detail_service.py`、`routers/project_router.py`、`media_studio/db.py`、前端任务中心/工坊/内容库、`backend/tests/test_job_list_payload.py` 与四份主文档。
- 兼容性：不改表结构。列表 JSON 不再带原始 `payload_json` 和超长草稿。
- 验证命令：`python -m unittest backend.tests.test_job_list_payload`。
- 回滚方式：还原上述文件并重新部署。

## 2026-09-20 导入确认成片画幅，规划/写稿/出片共用

- 变更原因：出片比例在工坊 localStorage，写稿锁死 9:16，导入立刻规划会把剧本里的竖屏写进镜头卡。
- 当前基线：成片画幅解析顺序为本次请求 `aspect_ratio` > 项目 `settings.extra.workshop_aspect_ratio` > 配方 `confirm_format.aspect_ratio` > `9:16`；横竖语文案随比例（高>宽竖屏、宽>高横屏、相等方形）。内容库导入仍立刻切集落库，但不再自动入队 `shot_plan`；文档 `status=awaiting_aspect`，响应带 `aspect_hint`（扫描原文 `9:16`/`16:9`/`1:1`/`3:4`/`4:3`/`21:9` 与竖屏/横屏/方形）。用户确认后写入 extra 再 `POST …/shot-plan`（body 可带 `aspect_ratio`）。工坊改生成设置除 localStorage 外写入同一 extra；`POST …/h3-prompt` 与 `POST …/generate-triptych` 请求体带 `aspect_ratio`，入队写入 `beat_info.aspect_ratio`。写稿 system/user、槽位标签、骨架、`inject_craft` 用解析结果；user 复制镜头目的/运镜时覆盖旧 heading 画幅用语，不改库里 Beat 原文。三联母图仍 16:9 三等分裁切，标签按成片比例说（不再写死 9:16 裁切）。规划 system/user 写明确认画幅为权威。`ai_pipeline` 仍不规划。角色/场景设定板仍 16:9 白底。
- 受影响文件：`skill_packs/aspect.py`、`handlers.py`、`triptych.py`、`h3_prompt_job_service.py`、`episode_shot_planner.py`、`project_detail_service.py`、工坊/内容库前端、测试与四份主文档、`docs/API.md`。
- 兼容性：不改表结构、端口或 ComfyUI。旧客户端仍可直接 `POST …/shot-plan`（无 body 则用 extra/配方缺省）。半解说配方 yaml 缺省仍是 9:16。
- 验证命令：`python -m unittest backend.tests.test_workshop_aspect backend.tests.test_skill_packs backend.tests.test_episode_shot_planner backend.tests.media_studio_test_storyboard_images backend.tests.test_shot_plan_job backend.tests.media_studio_test_h3_video -q`；`pnpm --dir frontend exec vitest run src/director2/workshop-aspect.test.ts src/director2/shot-plan-live.test.ts`。
- 回滚方式：还原上述文件。

## 2026-09-20 工坊成片多 Take 选用

- 变更原因：重新出片会覆盖 `beat.video_url` 并清空超分，历史成功抽卡仍在任务里但成片 Tab / 合成只认最新一条。
- 当前基线：逐镜/选中镜写入时把旧原片归档进 `beat.video_takes`（`data_json`，不新建表），`video_url` 默认采用最新。成片 Tab 列出本镜全部成功 Take，预览任意一条，`POST …/video-takes/adopt` 才把它变成正式成片。合成、配音提取、顶栏超分仍只读采用版 `video_url`。2x 挂在对应原片 Take 的 `upscaled_url`，不单独成 Take。拼接片不进单镜条带；整集直出过去也不进，2026-11-04 起其段级按镜落地同样写进单镜条带（Take 按 `shot` 记录，见下方「整集直出也按镜落地」）。历史任务由工坊已有 `listJobs` 按镜回填。不改 H3 节点，不引入已下线的 Recipe `shot.takes`。
- 受影响文件：`episode_video_service.py`、`project_detail_service.py`、`project_router.py`、工坊成片 Tab、`director2-video-settings.ts`、测试与四份主文档、`docs/API.md`。
- 兼容性：旧镜没有 `video_takes` 时由任务列表回填；未采用预览不影响镜头卡「已出片」和合成。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video.EpisodeVideoTakesTests backend.tests.media_studio_test_h3_video.EpisodeVideoUpscaleTests -q`；`pnpm --dir frontend exec vitest run src/director2/director2-video-settings.test.ts`。
- 回滚方式：还原上述文件。

## 2026-09-20 写稿不再把角色内心塞进旁白原文

- 变更原因：工坊入队 H3 时把内心折进 `beat_info.narration`，user 同时写「内心不要进旁白」和「旁白原文必须抄内心」。5.6 按合同把内心写进了中文旁白块。
- 当前基线：`dialogue_turns` 保留完整台词（含（内心））；`narration` 只留第三人称/第一人称旁白。写稿 user / 八块骨架 / 通道校验都用 `third_person_narration`，内心与旁白原文相同则视为无旁白。不改表结构、端口或 ComfyUI。镜头一需再生成 H3 提示词。
- 受影响文件：`h3_prompt_job_service.py`、`h3_prompt_builder.py`、`skill_packs/handlers.py`、官方模板、测试与四份主文档。
- 兼容性：真旁白仍进旁白块。程序装箱仍从对白里的（内心）取内心。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video backend.tests.test_h3_coverage -q`。
- 回滚方式：还原上述文件。

## 2026-09-20 镜头一写稿失败改为拦通道与 00:00 内心，不再误杀小数时间码

- 变更原因：工坊重新生成镜头一 H3 时，正确挂在下摇看衣的草稿因小数时间码、`00:00:15`、缺 `[Chinese]`、UTF-8 流把「参」打成 U+FFFD 而失败，Beat 仍是旧稿（内心从 00:00 起念），用户按旧稿出片。
- 当前基线：中文薄校验接受 `00:02.50`、`00:00:15` 和标题首字乱码；英文 `<d>` 可省略 `[Chinese]`。表演顺序第 1 句不是内心时，禁止内心原文出现在任何 00:00 起幅时间段。无旁白时仍禁止旁白块抄内心。半解说包不恢复 thickness / packing leftover。写稿失败仍不覆盖上一版提示词。不改表结构、端口或 ComfyUI。工坊需再生成镜头一 H3 提示词后再出片。
- 受影响文件：`skill_packs/handlers.py`、`h3_prompt_builder.py`、测试与四份主文档、`docs/API.md`。
- 兼容性：镜头二多句切开仍通过。旧的 00:00 内心稿不会自动改。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video backend.tests.test_h3_coverage -q`。
- 回滚方式：还原上述文件。

## 2026-09-20 内心与旁白改由写稿合同约束三通道

- 变更原因：镜头一不是画外音关键字失效，而是模型为填满「旁白」把内心提前到 00:00，又把开口判断句复制进第二个 `<d>`。复杂时间码规则已经误杀过镜头二。
- 当前基线：双稿 system/user 写清开口 / 角色内心 / 第三人称旁白三通道，并按 `ordered_speech_events` + `split_speech_atoms` 给出编号表演顺序。无 `narration` 时八块「旁白」固定写「本镜无第三人称旁白」，内心只进对白并标（内心）。中文薄校验：内心进第三人称/第一人称旁白、开口被标成内心、无旁白却用台词充数。半解说包 `skip_program_pack` 在既有内心交付校验之外增加 `speech_schedule_errors`（台词去重 + `<d>` 表演顺序），不打开 thickness / packing leftover。不改表结构、端口或 ComfyUI。工坊需重新生成镜头一 H3 提示词后再出片。
- 受影响文件：`skill_packs/handlers.py`、`h3-video-prompt-template.md`、`h3_prompt_builder.py`、`llm_service.py`、测试与四份主文档、`docs/API.md`。
- 兼容性：手动粘贴六段仍按原文出片。未绑技能包仍走程序装箱。镜头二多句切开不被新规则误杀。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video backend.tests.test_h3_coverage -q`。
- 回滚方式：还原上述文件。

## 2026-09-19 工坊内心戏改用官方 H3 画外音句式

- 变更原因：半解说包 `skip_program_pack` 把 GPT 英文六段原文送进本地 H3 后，内心对白常被写成 `says: <d>…</d>`，模型按开口对白驱动口型。
- 当前基线：写稿合同要求内心使用 MiniMax 官方 `says in an off-screen voiceover`，并把 `while … lips remain completely closed` 写在 `</d>` 后面。出片前对内心做外科修补（不灌水），`skip_program_pack` 也校验这条交付；仍写成口型同步 `says:` 则任务失败。程序装箱同样按官方句式渲染内心。不改表结构、端口或 ComfyUI。
- 受影响文件：`h3_prompt_builder.py`、`llm_service.py`、`h3_prompt_job_service.py`、`episode_video_service.py`、`skill_packs/handlers.py`、`director_craft/coverage.py`、测试与四份主文档、`docs/API.md`。
- 兼容性：手动粘贴六段仍按原文出片。未绑技能包仍走程序装箱。H3 对内心独白本身仍非 100% 保证。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video backend.tests.test_skill_packs`。
- 回滚方式：还原上述文件。

## 2026-09-19 写稿按句校验长对白，英文缺 [Shot 1] 时程序补上

- 变更原因：第一集镜头二台词是「吴耐免租 + 沙丽丽四句连问」写在同一引号里。模型已把各句拆进不同分秒和对白行，但校验把整段当一句做汉字连续匹配，说话人标签插在中间就报「台词未逐字出现 / 多轮对白必须拆进不同时间段」；英文六段标题齐全却常用 `00:00-00:03:` 而不写 `[Shot 1]`，`skip_program_pack` 不再装箱注入，任务直接失败。
- 当前基线：`split_speech_atoms` 按问号/句号切开同一人连续多句（过短叹词并入下一句）。中文八块和英文六段都按句校验原文。写稿 user 列出切开后的各句。`normalize_authored_ref2va` 在 `detailed_description` 开头补 `[Shot 1]`（已有则不重复）。真缺句、整段挤在同一时间码仍失败。不改表结构、端口或 ComfyUI。
- 受影响文件：`h3_prompt_builder.py`、`skill_packs/handlers.py`、`llm_service.py`、测试与四份主文档、`docs/API.md`。
- 兼容性：半解说包 `skip_program_pack` 仍出 GPT 英文；未绑包仍走程序装箱。
- 验证命令：`python -m unittest backend.tests.test_skill_packs`。
- 回滚方式：还原上述文件。

## 2026-09-19 制作配方选择页使用官方动态封面

- 变更原因：首页「选择制作配方」还是文字单选，需要对齐 MiniMax Design Skill Hub 的视频封面卡，并接入官方封面数据。
- 当前基线：半解说包 `meta.yaml` 写入 Hub 同源 `cover` mp4（`cdn.hailuoai.com`）与 `author`。`GET /api/skill-packs` 透出 `cover` / `author`；只接受 `http(s)` 地址，视频热链播放，不拷进仓库。选择页为两列卡片：有封面则静音循环播放，未绑定配方用渐变占位。后续新包在各自 `meta.yaml` 填 `cover` 即可，前端不写死列表。不接入其它 Plaza 包。
- 受影响文件：半解说包 `meta.yaml` / `SOURCE.md`、`skill_packs/recipe.py`、`models.py`、`SkillPackPickerModal.tsx`、首页、测试与四份主文档、`docs/API.md`。
- 兼容性：旧客户端忽略新字段。不改表结构、端口或 ComfyUI。封面来自 Hub 已公开 CDN，不爬 Design 客户端。
- 验证命令：`python -m unittest backend.tests.test_skill_packs`；`pnpm --dir frontend exec vitest run src/director2/skill-pack.test.ts`。
- 回滚方式：还原上述文件。

## 2026-09-19 半解说包写稿补齐六段 `name:` 标题

- 变更原因：GPT 英文六段常写成行首 `subject_definitions`（无冒号）或中文冒号；`skip_program_pack` 只规范化 `<Picture>` 后立刻按 `^name:\s*` 校验，任务报 `required section headings are missing or out of order`。系统提示原先列出的也是无冒号名称。
- 当前基线：`canonicalize_section_headings` 把行首六段名（可 Markdown、可无冒号/中文冒号）收成 ASCII `name:`。半解说包写稿、润色、落库与出片走 `normalize_authored_ref2va`（标签 + 标题）。不灌水、不 `ensure` 填 N/A；后两段真缺失仍失败。双稿合同要求独占一行并带英文冒号。
- 受影响文件：`h3_prompt_builder.py`、`llm_service.py`、`skill_packs/handlers.py`、`h3_prompt_job_service.py`、`episode_video_service.py`、测试与四份主文档、`docs/API.md`。
- 兼容性：不改表结构、端口或 ComfyUI。未绑技能包仍走 `prepare`。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件。

## 2026-09-19 导演台新建工程时选择技能包

- 变更原因：配方已按项目 `extra.skill_pack_id` 执行，但首页直接建「未命名导演工程」，界面没有选择器；后续还要接入更多 Plaza 类配方。
- 当前基线：`GET /api/skill-packs` 带 `summary`。首页「新建导演工程」先选配方（默认半解说真人短剧，可选不绑定），再写入 extra。项目顶栏 Select 可改。未绑定不再把三联生图提示偷偷回退半解说模板。后续新包只需放入 `backend/app/skill_packs/`，前端不写死列表。内容库「骨架模板」仍不是技能包。
- 受影响文件：`skill_packs/recipe.py`、半解说 `meta.yaml`、`storyboard_image_service.py`、`models.py`、首页/项目壳前端、测试与四份主文档、`docs/API.md`。
- 兼容性：旧工程 extra 为空仍走默认程序装箱。不改表结构、端口或 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_storyboard_images`；`pnpm --dir frontend exec vitest run src/director2/skill-pack.test.ts`。
- 回滚方式：还原上述文件。

## 2026-09-19 三联三格裁切全部作为 R2V 参考图

- 变更原因：写稿已看整张 16:9 三联，但出片只上传左格起幅；中格/右格已裁好却不出片。本地 H3 仍不能吃整张母图，否则会把三格插值成一条宽画面。
- 当前基线：半解说包 `r2v_slots` 为角色设定板 + 场景卡 + `triptych.start|mid|end`。有 URL 才追加；槽位不够（最多 9）时先丢中格、再丢结果，起幅尽量保留。提示词把三张 9:16 裁切写成同一镜时间路标（00:00 构图锚 / 主动作 / 落幅），禁止分栏、禁止三格同框、禁止把 16:9 母图当 `<Picture n>`。写稿附图仍含整张 `triptych_url`。旧镜只有左格时 `extract_triptych_panels` 会按母图补裁中/右格。工坊素材组追加三张裁切并过滤母图。
- 受影响文件：半解说包 `meta.yaml` / `SOURCE.md` / `SKILL.md`、`skill_packs/handlers.py`、`director_craft/references.py`、`h3_prompt_builder.py`、`h3_prompt_job_service.py`、`EpisodeWorkshopPane.tsx`、`workshop-r2v-refs.ts`、测试与四份主文档、`docs/API.md`。
- 兼容性：未绑技能包仍走默认角色+场景参考图。不改表结构、端口或 ComfyUI。禁止上传整张 16:9。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video backend.tests.test_h3_coverage`；`pnpm --dir frontend exec vitest run src/director2/workshop-r2v-refs.test.ts`。
- 回滚方式：还原上述文件。

## 2026-09-19 工坊生成 H3 前先出三联，已有稿可重新生成

- 变更原因：用户先点「生成 H3 提示词」、后补三联时，写稿看不到三联；生成后提示词栏只剩「编辑 / 复制」，不容易再生成。
- 当前基线：工坊点生成 H3 时若本镜无三联（或 `triptych_status` 仍为 queued/running），弹出确认并只入队三联生图，完成后由用户查看再手动生成提示词。生成/重新生成只在素材组「提示词」栏，分区标题只留状态芯片（及拆镜时的「合并为一条生成」）。后端 `h3_prompt` 任务仍不自动 `enqueue_images`。不改表结构、端口或 ComfyUI。
- 受影响文件：`EpisodeWorkshopPane.tsx`、`workshop-h3-gate.ts`、对应测试与四份主文档。
- 兼容性：已有三联的镜头直接写稿；覆盖已保存提示词仍确认。
- 验证命令：`pnpm --dir frontend exec vitest run src/director2/workshop-h3-gate.test.ts src/director2/workshop-prompt-live.test.ts`；5173 打开工坊第一镜自查门禁与重新生成按钮。
- 回滚方式：还原上述文件。

## 2026-09-19 Hypit 在 16GB 卡上改用精简 H3 权重

- 变更原因：4080 16GB 上 Hypit 默认打完整 `ref2va_int8_convrot`（Turbo LoRA 需要 AdaLN 2688 维），权重暂存约 32GB，动态换入要近一小时。不是 4080 不能跑 H3。
- 当前基线：提交前读 Comfy `/system_stats`。显存不到 20GB（含读不到）用 `minimax_h3_*_pruned_int8_convrot`，20 步、不上官方 Turbo LoRA。≥20GB 仍用完整权重 + 4 步 Turbo。可用 `ZLY_HYPIT_H3_WEIGHT_PROFILE=full|pruned` 覆盖。画质档仍是 `h3Quality`。不改本机 VACE/导演台2 Comfy。
- 受影响文件：`packages/provider-comfy-h3`、四份主文档。
- 兼容性：24GB+ 行为不变。16GB 单段会比 4 步 Turbo 慢（约十几分钟级），但不再做 32GB 换入。54 上 Comfy 若升级到 PyTorch cu130，int8_convrot / nvfp4 会更快。
- 验证命令：在 `D:\zlyun\hypit-poc\packages\provider-comfy-h3` 执行 `npm test`。
- 回滚方式：还原上述文件。

## 2026-09-19 Hypit 编译回收孤儿执行器，Comfy 丢 prompt 即失败

- 变更原因：`hypit build --follow` 的父进程被工作台中断或热重载杀掉后，带 `--execution-root` 的执行器仍会卡在 `waiting-history`，占死 `comfy.h3` 并发槽；Comfy 重启后队列和 history 都没有该 prompt，旧逻辑永不失败。手工杀 PID 只能解一次。
- 当前基线：`@zly/provider-comfy-h3` 在 prompt 不在 `/queue` 且 `/history` 缺失超过 45s 时返回 `COMFY_H3_LOST`（旧 `startedAt` 在 Comfy 重启后会立刻失败）。工作台 `run_hypit` 改为 `Popen`，登记 PID；取消、超时、`CancelledError`、`stop()` 都会 `taskkill /T` 并回收没有活着的 `hypit build --follow` 的执行器。下一次 `hypit_compile` 先按工程目录回收遗留 `build` 与无主执行器，不杀池化 `_worker`（`--ready-file`）。不改本机工作台 Comfy，不新开 8188。
- 受影响文件：`backend/app/director_hypit.py`、`director_operations.py`、`packages/provider-comfy-h3`、四份主文档。
- 兼容性：API 与 payload 不变。Comfy HTTP 在大模型加载期间超时仍走 `comfy-unreachable` 等待，不按丢 prompt 处理。仍在 `/queue` 里的卡死任务不是孤儿进程，需在 Comfy 侧中断。
- 验证命令：`python -m unittest backend.tests.test_director_hypit -q`；在 `D:\zlyun\hypit-poc\packages\provider-comfy-h3` 执行 `npm test`。
- 回滚方式：还原上述文件。

## 2026-09-19 Hypit 复刻页可选 H3 画质档

- 变更原因：768P（0.98 MP / 768×1344）在 16GB 4080 上会卡死；MP 只写在 `hypit.runtime.json`，页面没有入口。
- 当前基线：`hypit_replication.h3Quality` 为语义三档 `safe`（0.6 MP / 608×1056，默认）、`balanced`（0.7 MP / 640×1152）、`official`（0.98 MP / 768×1344）。前端用 Ant Design Select 显示像素尺寸，不提供原始 MP 数字框。编译时写入工程 `notes/hypit.runtime.overlay.json`（`dataRoot` 改绝对路径）并设置 `ZLY_HYPIT_H3_MEGAPIXELS`；`@zly/provider-comfy-h3` 每次 submit 读取该环境变量。不改工作台本机 Comfy 默认档。
- 受影响文件：`backend/app/director_hypit.py`、`director_operations.py`、`DirectorHypitStudio.tsx`、`hypit-model.ts`、`packages/provider-comfy-h3`、四份主文档。
- 兼容性：旧工程缺字段时归一为 `safe`。SVML 仍可写 `resolution="768P"`，实际像素由画质档决定。
- 验证命令：`python -m unittest backend.tests.test_director_hypit -q`；`pnpm --dir frontend exec vitest run src/director/hypit-model.test.ts`；在 `D:\zlyun\hypit-poc\packages\provider-comfy-h3` 执行 `npm test`。
- 回滚方式：还原上述文件。

## 2026-09-19 导演台并入 `/director`，九阶段 Recipe 界面下线

- 变更原因：侧栏「导演台」实际打开的是原 `/director2` 项目壳，「导演台2」才是旧九阶段 `/director`。产品只保留一套导演台。
- 当前基线：`DIRECTOR2_PREFIX` 改为 `"/director"`。侧栏只留「导演台」。`/director` 为首页；`/director/projects/:id/{content|assets|workshop|jobs}` 为导演创作；`/director/batch|replication|hypit/:id` 路径不改。`/director2/*` `Navigate` 到对应 `/director/*`。旧 `/director/:recipeId` 回首页。首页合并 `/api/projects` 与三项 `/api/director/projects`（过滤 recipe / timeline）。前端删除九阶段 Recipe 页面与专属组件（`DirectorRecipeStudio`、时间线、`opencut-timeline` 等）。本轮不重命名 `frontend/src/director2/`，不改后端 `surface: "director2"`，不拆除 `/api/director/recipes/*`。`/api/jobs` 轮询只在生成页和三条工作室开启。（2026-10-25 更新：资产页会拉取一次任务快照但不再周期轮询，见文末「生成页性能与错误反馈优化」。）
- 受影响文件：`frontend/src/paths.ts`、`frontend/src/router.tsx`、`frontend/src/App.tsx`、`frontend/src/director2/paths.ts`、`Director2StudioHome.tsx`、`DirectorStudioModule.tsx`、`frontend/src/director/` 九阶段专属文件（删除）、四份主文档。
- 兼容性：三项工作室与 `/assets`、生成页 URL 不变；旧 `/director2` 书签可跳转；旧 Recipe 书签不再打开九阶段界面。
- 验证命令：`pnpm --dir frontend exec vitest run`；5173 自查首页、四类入口、重定向与生成/资产页。
- 回滚方式：从 Git 恢复删除的 Recipe 文件与路径前缀。

## 2026-09-19 Hypit H3 768P 不再用 0.2 MP 预览档

- 变更原因：沙丽丽护肤复刻成片出现横竖条纹。H3 原片只有 352×608（`megapixels: 0.2`），Hyperframes 再 cover 到 720×1280，YUV 4:2:0 色度块被拉大成网格。
- 当前基线：`@zly/provider-comfy-h3` 把 `768P` 落到 `0.98` MP（9:16 为 768×1344）。`hypit.runtime.json` 默认同此。配置 `≤0.2` 视为旧预览档并忽略。16GB 卡 OOM 时可把 `comfy.h3.config.megapixels` 调到 `0.4`–`0.9`。工作台本机 Comfy 默认档不变。
- 受影响文件：`D:\zlyun\hypit-poc\packages\provider-comfy-h3`、`hypit.runtime.json`、三份主文档。
- 兼容性：不改 VACE / 创作页 / 导演台2 的 H3 默认 0.2。已生成的 352×608 成片需重新编译。
- 验证命令：在 `D:\zlyun\hypit-poc\packages\provider-comfy-h3` 执行 `npm test`。
- 回滚方式：把 `megapixels` 改回 `0.2` 并还原 `resolveH3Megapixels`。

## 2026-09-19 超分提交前检查 RTX 节点是否装在当前 Comfy

- 变更原因：工作台连着 `192.168.10.54:8188` 时，Comfy 返回 `missing_node_type`：该机没有 `RTXVideoSuperResolution`。节点只装在本机整合包 `custom_nodes/Nvidia_RTX_Nodes_ComfyUI`，本机 8188 当前也没在跑。
- 当前基线：入队和跑图前 `GET /object_info/RTXVideoSuperResolution`。没有节点则 422，文案写明当前 Comfy 地址和 GPU，并提示拷贝该包、安装 `nvidia-vfx` 后重启。`POST /prompt` 若仍报缺节点，同样译成这段中文，不再甩原始 HTTP 400 JSON。
- 受影响文件：`rtx_vsr_workflow.py`、`comfy_service.py`、`comfy_video_client.py`、`episode_video_service.py`、`main.py`、`project_router.py`、测试与三份主文档、`docs/API.md`。
- 兼容性：不改 H3 节点 ID；不在 54 上远程安装 custom_nodes；不新开第二套 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_rtx_vsr backend.tests.media_studio_test_h3_video.EpisodeVideoUpscaleTests`。
- 回滚方式：还原上述文件。

## 2026-09-19 超分显存门闸改读当前连接 ComfyUI

- 变更原因：原先按 12GB 卡写死约 8GB 可用额度，连着 16GB 的 `192.168.10.54` 时仍会把 864×480×362 帧（估约 8.4GB）拦掉。
- 当前基线：提交 2x 超分前 `GET` 当前管理设置里的 ComfyUI `/system_stats`，用 `devices[].vram_total` 减 2GiB CUDA 余量作为额度。读不到显存时不编造 8GB，交给后续 Comfy 报错。拒绝文案写明连接的 GPU 名称与总显存。
- 受影响文件：`rtx_vsr_workflow.py`、`comfy_service.py`、`comfy_video_client.py`、`episode_video_service.py`、`main.py`、测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改 H3 节点 ID、不装 DLSS5。超分仍走当前连接的那一台 ComfyUI，不是第二套实例。
- 验证命令：`python -m unittest backend.tests.test_rtx_vsr backend.tests.media_studio_test_h3_video.EpisodeVideoUpscaleTests`。
- 回滚方式：还原上述文件。

## 2026-09-19 导演台2角色造型改为设定板，不再先生成头像

- 变更原因：单独 1:1 头像是给旧四宫格用的；新设定板已含正脸与全身，继续先出头像会多花一次 GRS 且容易漂。
- 当前基线：`target_type=identity` 出 16:9 / 2K / `2048x1152` 设定板（左三视图、右上六头、右下六细节）。无头像也可入队；无外观描述且无原片仍拒绝。参考图：原片 > 其他已出图设定板 > 仅当两档都没有时才用旧 `avatar_url`。界面去掉「角色基础头像」与「一键生成所有头像」；列表缩略图优先设定板。`target_type=avatar` 仍可用但不在界面露出。不删 `avatar_url` 字段。H3 `character_subject_line` 把造型图当作单人多视图设定板，只锁身份/发型/服装，禁止把分格、白底、重复小人带进镜头。三联关键帧参考图在已有造型图时不再追加 `avatar_url`（无造型图时才回退旧头像）。
- 受影响文件：`asset_image_prompts.py`、`project_detail_service.py`、`director_craft/references.py`、`episode_image_prompts.py`、`h3_prompt_builder.py`、`llm_minimax_skills.py`、`skill_packs/handlers.py`、半解说包 `SKILL.md` / `h3-video-prompt-template.md`、资产库前端、测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、端口或 ComfyUI。旧项目头像仍可读。旧导演台 Recipe / xiaji 肖像四联本轮不动。
- 验证命令：`python -m unittest backend.tests.test_asset_source_references backend.tests.test_h3_coverage backend.tests.media_studio_test_h3_video.LookSelectionTests backend.tests.test_skill_packs`；`pnpm --dir frontend exec vitest run src/director2/panes/assets/shared.test.ts src/director2/panes/assets/CharacterWorkspace.test.tsx src/director2/asset-source-references.test.ts`。
- 回滚方式：还原上述文件。

## 2026-09-19 从成片框选提取角色参考音

- 变更原因：多人开口的 H3 成片不能默认切前几秒当参考音，否则会串到旁人声。
- 当前基线：导演台2 资产库角色工作区「从成片提取」。列出该角色有开口对白且已有 H3 原片 `video_url` 的镜头；用户在弹层里播放并框选 1–15 秒，后端 `ffmpeg -ss` 在 `-i` 前只切该时段为 16 kHz mono wav，写入 `extra.voice` 并清空 `preset_id`。`source` 记录 `kind/episode_id/beat_id/start_sec/end_sec`。列候选只读解析 `data_json`，不走会回写空 beats 的 `get_episode_detail`。同步、不入队、不占 GPU。不用超分片或整集拼接片。
- 受影响文件：`voice_extract.py`、`voice_profile.py`、`project_detail_service.py`、`project_router.py`、资产库前端、测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、端口或 ComfyUI。旧角色无 `source` 仍可上传/选用内置声线。
- 验证命令：`python -m unittest backend.tests.test_voice_extract backend.tests.test_voice_bank`；`pnpm --dir frontend exec vitest run src/director2/voice-extract-window.test.ts src/director2/voice-profile.test.ts`。
- 回滚方式：还原上述文件；已写入的 `extra.voice.source` 可忽略。

## 2026-09-19 Hypit H3 改走局域网 ComfyUI

- 变更原因：Hypit A-roll 不应占用本机工作台 ComfyUI（`127.0.0.1:8188` / 管理设置 `ZLY_AI_VIDEO_STUDIO_COMFY_URL`）。H3 画面要打到局域网 `http://192.168.10.54:8188`。
- 当前基线：POC Provider `@zly/provider-comfy-h3` 允许回环或 RFC1918 明文 HTTP，默认与 `hypit.runtime.json` `comfy.h3.comfyUrl` 均为 `http://192.168.10.54:8188`。可用 `ZLY_HYPIT_COMFY_URL` 覆盖。工作台 `hypit_compile` 仅在该地址是回环时才 `occupy_gpu("comfy")`；远端时不锁本机 GPU。导演台2 / 创作页 VACE·H3 仍走本机 Comfy。不新开 8188、不 vendoring Hypit。
- 受影响文件：`D:\zlyun\hypit-poc\packages\provider-comfy-h3`、`hypit.runtime.json`、`director_hypit.py`、`director_operations.py`、`DirectorHypitStudio.tsx`、测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改工作台 Comfy 管理地址、节点 ID、端口 7865/本机 8188。旧 `shot_replication` 不变。
- 验证命令：`python -m unittest backend.tests.test_director_hypit`；`pnpm --dir frontend exec vitest run src/director/hypit-model.test.ts`；在 `D:\zlyun\hypit-poc\packages\provider-comfy-h3` 执行 `npm test`；`npx --no -- hypit doctor --runtime D:\zlyun\hypit-poc\hypit.runtime.json`。
- 回滚方式：把 `comfyUrl` 改回 `http://127.0.0.1:8188`，并还原 URL 校验与 occupy 逻辑。

## 2026-09-19 内置短剧配音声线

- 变更原因：导演台2 配音需要角色参考音才能克隆；不能把剪映/魔音工坊等商业音色包放进仓库。
- 当前基线：`backend/app/voice_bank/` 收录 IndexTTS 官方 11 条示例 wav（HuggingFace Space `IndexTTS-2-Demo/examples`），产品侧归档为沉稳男主、解说旁白、甜妹女主等短剧角色名。`GET /api/voice-bank` 列目录，`GET /api/voice-bank/{id}/audio` 读 wav；`POST .../assets/{id}/voice/preset` 写入 `extra.voice.preset_id`。资产库与工坊配音左栏可选内置声线。合成仍走本地文件，不经七牛下载参考音。许可证见 `voice_bank/SOURCE.md`。
- 受影响文件：`voice_bank/`、`voice_profile.py`、`dubbing_service.py`、`project_detail_service.py`、工坊/资产库前端、测试与三份主文档、`docs/API.md`。
- 兼容性：不改表结构。旧角色无 `preset_id` 仍可上传自定义参考音。
- 验证命令：`python -m unittest backend.tests.test_voice_bank`；`pnpm --dir frontend exec vitest run src/director2/voice-profile.test.ts src/director2/voice-bank.test.ts`。
- 回滚方式：还原上述文件；可保留 `prompts/*.wav`。

## 2026-09-19 剧集工坊逐镜 RTX 2x 超分

- 变更原因：创作页已能出片后独立超分；工坊整集直出和拼接片时长/帧量过大，不能自动放大。
- 当前基线：工坊生成设置「更多设置」按 schema 渲染布尔开关「出片后 2x 超分」（Ant Design Switch）。仅 `render_scope=shot|selection` 在原片写入 Beat `video_url` 后自动接跑同一套 RTX VSR graph（先 `POST /free`）；`episode` 整集直出和 `compose` 拼接即使开关打开也不自动超分。手动 `POST /api/projects/{id}/episodes/{id}/beats/{id}/upscale` 入队独立 `video_generation`（`render_scope=upscale`），结果写 `upscaled_video_url`，原片不动。全部任务已成功视频可点「超分」，走 `POST /api/projects/{id}/jobs/{job_id}/upscale`（用该任务成片地址；超分任务本身和多镜 selection 不可点）。超分失败写 `upscale_warning` 仍保留原片。镜头卡标「2x」并优先播超分版；任务中心预览超分结果并可切回原片。
- 受影响文件：`episode_video_service.py`、`comfy_video_client.py`、`project_router.py`、工坊/任务中心前端、测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改 H3 节点 ID；不装 DLSS5。重新出片会清空该镜 `upscaled_video_url`。
- 验证命令：`python -m unittest backend.tests.test_rtx_vsr backend.tests.media_studio_test_h3_video`；`pnpm --dir frontend exec vitest run src/director2/director2-video-settings.test.ts src/director2/workshop-video-progress.test.ts src/video-upscale.test.ts`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-19 全部任务手动 2x 超分

- 变更原因：导演台2「全部任务」原先只能预览超分结果，已成功成片无法从任务列表提交 2x。
- 当前基线：视频生成 Tab 操作列和详情弹层增加 Ant Design「超分」。`POST /api/projects/{id}/jobs/{job_id}/upscale` 用该任务 `result_url` 入队独立 VSR；单镜写回 Beat，整集/拼接可手动提交（过长仍被显存门闸拒绝）。超分任务本身、未完成、多镜 selection 不提供按钮。完成后回写源任务 `payload.upscaled_video_url`，原片 `result_url` 不动。
- 受影响文件：`episode_video_service.py`、`project_router.py`、`JobsCenterPane.tsx`、测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改 H3 节点 ID；工坊逐镜开关与 Beat 超分接口仍可用。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video.EpisodeVideoUpscaleTests`；`pnpm --dir frontend exec vitest run src/director2/director2-video-settings.test.ts`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-19 Hypit 复刻第四入口（POC 出门后）

- 变更原因：本机 Hypit POC 已通过（无 HypiHub doctor、WhisperX 中文对齐、Chromium 图形成片、ComfyUI 8188 H3 A-roll）。需要与 VACE 参考片复刻并列的结构复刻入口，而不是把 Hypit 填进 `shot_replication`。
- 当前基线：新 payload kind `hypit_replication`，路由 `/director/hypit/:projectId`。导演台与导演台2 首页第四张卡「Hypit 复刻」文案为拆结构、换内容、合字幕图形。后端子进程调本机 `hypit` CLI（默认 `D:\zlyun\hypit-poc`，工程目录 `data/hypit/{user}/{project}`），不 vendoring monorepo。拉片 `hypit_transcribe`（WhisperX），编译 `hypit_compile`（check/plan/build，`Popen` 可取消；开始前回收本工程遗留执行器）；H3 走现有 8188，编译期间仅本机 Comfy 才 `occupy_gpu("comfy")`。没有 `.svrun` 时提示用 Coding Agent 写 SVML。VACE `analyze_reference_video` / `replicate_shots` / `/director/replication/:id` 零改动。CLI 报告保留 Hypit 名称。
- 受影响文件：`director_hypit.py`、`director_recipe.py`、`director_operations.py`、`main.py`、`models.py`、`storage.py`、导演台首页/工作台前端、测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、端口或 ComfyUI 节点。不新开 8188。旧 `shot_replication` 工程不受影响。
- 验证命令：`python -m unittest backend.tests.test_director_hypit backend.tests.test_core backend.tests.test_director`；`pnpm --dir frontend exec vitest run src/director/hypit-model.test.ts`。
- 回滚方式：还原上述文件；首页去掉第四张卡即可，已有 Hypit 工程仍可当普通 payload 删除。

## 2026-09-19 导演台2 配音进成片与 GPU 互斥

- 变更原因：台词轨已能生成，但合成仍只拼接 H3 原片；解说剧缺旁白也能点合成；生成页 worker 空闲 `/free` 可能打在导演台2 H3/TTS 占用期间。
- 当前基线：工坊「配音」Tab 三栏（角色声线可绑定/试听、台词轨 B1…Bn、配音导演情绪/语速/混音）。`job_type=tts_generation` 在全部任务「配音」Tab。合成默认 `mix_dubbing=true`：内心/旁白叠到对应镜，`mix=replace` 开口句静音该镜原声；开口 overlay 不叠 TTS。半解说包旁白未配音则合成 400。`gpu_runtime.occupy_gpu` 领取前卸载对方引擎；worker 空闲 `/free` 走 `idle_run`，H3/TTS 占用时跳过。
- 受影响文件：`dubbing_mix.py`、`episode_video_service.py`、`gpu_runtime.py`、`worker.py`、工坊/全部任务前端、测试与三份主文档、`docs/API.md`。
- 兼容性：不改表结构、端口或 ComfyUI。精品剧不强制旁白配音。旧 Recipe 配音页不改。
- 验证命令：`python -m unittest backend.tests.test_dubbing_lines backend.tests.test_gpu_runtime backend.tests.media_studio_test_h3_video`；`pnpm --dir frontend exec vitest run src/director2/dubbing-track.test.ts src/director2/director2-job-types.test.ts src/director2/paths.test.ts`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-19 半解说包双稿不再把说明句当正文

- 变更原因：失败已冒泡后，GPT-5 仍把「请先输出 <<<ZH>>> 官方八块中文分秒稿」当成整篇回复；系统提示还灌入 SKILL.md 工作坊章节，`reasoning_effort=low` 又把 `max_completion_tokens` 花在隐藏推理上，校验于是报出一整串缺标题。
- 当前基线：双稿 system 只保留八块填空骨架，不再 `inject_craft` 工作坊章节。用户提示改为「直接输出两块正文」，禁止复述说明句。中英文 stub（如「官方八块中文分秒稿与」「英文六段稿。」）打回重写，错误只有一句，不再展开缺标题清单。看图写作 `chat_on_endpoint` 对 GPT-5 / o 使用 `reasoning_effort=none`，双稿 `max_tokens=16000`。失败 payload 可带 `author_raw_draft`。半解说包仍 fail-hard，不回退骨架。
- 受影响文件：`skill_packs/handlers.py`、`llm_service.py`、`vision_runtime.py`、对应测试与三份主文档、`docs/API.md`。
- 兼容性：不改表结构、端口或 ComfyUI。`LlmService.chat_text` 仍用 `reasoning_effort=low`。未绑技能包仍走默认程序装箱。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.test_vision_runtime backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-18 成片后独立 RTX 2x 超分

- 变更原因：12GB 卡不能把 H3 和 RTX VSR 放进同一张 prompt；需要在出片后卸模型，再单独放大。
- 当前基线：新增隐藏工作流 `nvidia-rtx-vsr`（不进创作页模型列表）。独立 API graph 为 `LoadVideo → GetVideoComponents → RTXVideoSuperResolution（固定 2x / ULTRA）→ CreateVideo → SaveVideo`，输出节点 `24`，不占用 H3 的 SaveVideo `14`。H3 / LightX2V / 八步双加速 / Director 加速 / T8 增加 `upscale_after`（`advanced` 布尔，默认关）。创作页勾选后，原片写入 `outputs[0]`，强制 `POST /free`，再跑 VSR，结果为 `outputs[1]`「2x 超分」；失败时任务仍成功并保留原片。`POST /api/jobs/{job_id}/upscale` 按已成功成片新建独立超分任务（可带 `source_job_id`），同一原片已有进行中超分返回 409。`comfy_phase=rtx-vsr` 恢复时只续超分。提交前按宽×高×2×帧数估显存，额度来自当前连接 ComfyUI `/system_stats` 的 `vram_total`（减 2GiB 余量）；读不到显存则不编造限额。
- 受影响文件：`rtx_vsr_workflow.py`、`workflow_registry.py`、`comfy_service.py`、`worker.py`、`main.py`、创作页结果卡、测试与三份主文档、`docs/API.md`。
- 兼容性：不改已接入 H3/LightX2V 节点 ID；不装 DLSS5；不打开 LightX2V 侧栏已 bypass 的 RTX 节点。超分失败不影响原片。
- 验证命令：`python -m unittest backend.tests.test_rtx_vsr backend.tests.test_core`；`pnpm --dir frontend exec vitest run src/video-upscale.test.ts src/director2/director2-video-settings.test.ts`。
- 回滚方式：还原上述文件。

## 2026-09-18 导演台2 接入 IndexTTS-2.5 配音旁路

- 变更原因：导演台2 需要角色参考音克隆和逐句情绪/语速，OpenAI 兼容 CosyVoice 系统音色做不到；IndexTTS 也不能装进 FastAPI 或塞进 ComfyUI 8188 队列。
- 当前基线：独立旁路进程默认 `http://127.0.0.1:7866`（`tools/indextts_sidecar/`，`启动 IndexTTS 旁路.bat`），权重在工作台父级 `整合包及模型/index-tts/checkpoints`。管理设置 `/admin/tts` 增加「本机 IndexTTS-2.5」预设；测试连接打 `/health`。角色资产 `extra.voice` 存参考音；工坊「配音」Tab 从 Beat `ordered_speech_events` 展开台词轨，写入 `data_json.beats[].dubbing_lines`；`job_type=tts_generation` 单句/批量生成。H3 与 TTS 经 `gpu_runtime.occupy_gpu` 互斥卸载。合成默认混入内心/旁白，开口 overlay 保留 H3 口型声。
- 受影响文件：`tools/indextts_sidecar/`、`tts_provider.py`、`gpu_runtime.py`、`dubbing_*.py`、`tts_generation_job_service.py`、资产/工坊/任务前端、测试与三份主文档。
- 兼容性：不改表结构、不改 ComfyUI 端口。CosyVoice 仍可作无 GPU 降级。旧 Recipe「配音」页不改。
- 验证命令：`python -m unittest backend.tests.test_tts_provider backend.tests.test_indextts_sidecar backend.tests.test_dubbing_lines`；`pnpm --dir frontend exec vitest run src/director2/director2-job-types.test.ts src/director2/voice-profile.test.ts src/director2/dubbing-track.test.ts`。
- 回滚方式：还原上述文件；不要把 IndexTTS 装进工作台 venv。

## 2026-09-18 半解说包 H3 写稿失败不再静默降级

- 变更原因：绑定半解说包后，「生成 H3 提示词」任务会完成，但落库的是骨架八块 + `render_ref2va` 灌水句。双稿系统提示词拼了装箱器「只出英文、不要 `<d>`」，解析把纯英文当中文空稿，裸 `except` 再填骨架并伪造成功。
- 当前基线：`build_dual_author_system` 不再拼接 `packing_system_prompt`。半解说包 `skip_program_pack` 时，中文八块与英文六段都必须通过校验才写回 Beat；出片英文规范化 `<Picture>` / `<Subject>` 和六段 `name:` 标题，不再 `render_ref2va`、不再灌水句。LLM 或校验失败则 `h3_prompt` 任务 `failed`，`payload` 保留 `author_errors`、`vision_*` 与截断残稿，不覆盖上一版 `h3_prompt` / `timestamped_zh_prompt`，禁止骨架填空当成功。工坊失败 toast 显示真实原因，直播残稿保留，状态芯片为「生成失败」。`fill_timestamped_zh_prompt` 只给模板单测，不进入工坊成功路径。未绑技能包仍走默认程序装箱。
- 受影响文件：`skill_packs/handlers.py`、`runner.py`、`llm_service.py`、`h3_prompt_job_service.py`、工坊前端直播/失败态、对应测试与三份主文档、`docs/API.md`。
- 兼容性：不改表结构、端口或 ComfyUI。默认配方不受影响。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video backend.tests.test_llm`；`pnpm --dir frontend exec vitest run src/director2/workshop-prompt-live.test.ts src/director2/workshop-vision-status.test.ts`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-18 内容库镜头规划改为结果画布瘦进度

- 变更原因：内容库把工坊「生成 H3 提示词」的思考+逐字正文套进规划任务，用户看到英文 CoT 和残缺 JSON，而交付物其实是镜头卡。
- 当前基线：SSE 协议不变（`delta` 仍是本集 JSON 正文）。前端 `parsePartialShotPlanJson` 从残缺 JSON / markdown 围栏取出已闭合镜头和当前未闭合对象的已有字段。内容库去掉 `WorkshopPromptLive`，标题下只留一行瘦进度（按集 `Progress` +「本集已写出 K 条镜头」）；思考默认折叠，不渲染 JSON。当前规划集隐藏剧本切镜，网格里用解析中的镜头卡就地长出（至少有标题或动作才出现，字段随 JSON 补全，`duration_sec` 显示为「N 秒」）；`episode_done` 后换成后端归一化结果。集头统一为排队 / 规划中 / `已规划 · N 镜 · N 秒` / 规划失败（失败保留剧本切镜）。完成后 Toast，不钉成功绿卡。未规划只保留标题「未规划」和集头「剧本切镜」。工坊提示词直播不变。
- 受影响文件：`shot-plan-live.ts`、`ContentLibraryPane.tsx`、`shot-plan-slim-progress.tsx`、`content-library-shot-card.tsx`、对应 vitest 与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、端口、SSE 事件名或 ComfyUI。
- 验证命令：`pnpm --dir frontend exec vitest run src/director2/shot-plan-live.test.ts src/director2/panes/shot-plan-slim-progress.test.tsx src/director2/panes/content-library-shot-card.test.tsx`。
- 回滚方式：还原上述文件。

## 2026-09-18 内容库导入拆成解析落库 + shot_plan 任务直播

- 变更原因：粘贴/文件导入在 `create_document` 同步逐集调大模型，导入弹窗会锁十几分钟，开发代理也可能先断开。
- 当前基线：`POST /api/projects/{id}/documents` 只跑解析器并立刻落库（解析器镜头可先显示），非 `ai_pipeline` 再入队 `job_type=shot_plan`，响应带 `shot_plan_job_id`，文档 `status` 为 `planning` / `ready`。文档 `ready` 只表示当前没有规划任务，不等于已规划；未规划时内容库标题显示「未规划」，集头显示「剧本切镜」。旧稿可 `POST …/documents/{doc_id}/shot-plan` 触发同一任务。任务线程池逐集 `plan_episode_shots`，每集成功立刻写 `analysis_json`（`shots_source=llm`），失败保留解析器镜头并写 `analysis.logs`。`GET …/jobs/{job_id}/events` 按 `job_type` 分流，`shot_plan` 推 `status` / `reasoning` / `delta` / `episode_done` / `done` / `error`。内容库点导入/规划后自动打开「分集与镜头」，剧本标题下方为按集瘦进度（思考默认折叠，不展示 JSON）；完成后 Toast。规划中禁用「同步至剧集工坊」。全部任务增加「镜头规划」Tab，可跳回 `/director2/projects/:id/content?doc=`。`ai_pipeline` 仍不入队。
- 受影响文件：`shot_plan_job_service.py`、`project_detail_service.py`、`project_router.py`、`episode_shot_planner.py`、`main.py`、`ContentLibraryPane.tsx`、`JobsCenterPane.tsx`、`shot-plan-live.ts`、`director2-job-types.ts`、对应测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、端口或 ComfyUI。导入接口仍 200；规划从同步改为后台任务。
- 验证命令：`python -m unittest backend.tests.test_shot_plan_job backend.tests.media_studio_test_storyboard_images backend.tests.test_episode_shot_planner`；`pnpm --dir frontend exec vitest run src/director2/shot-plan-live.test.ts src/director2/director2-job-types.test.ts src/director2/paths.test.ts`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-18 同步剧集工坊不再补跑镜头规划

- 变更原因：旧稿点「覆盖并同步」会在同一 HTTP 请求里逐集调大模型规划出片镜。6 集可能跑十几分钟，Vite 代理 120 秒先断开，弹窗却一直转圈。
- 当前基线：`POST …/transfer-episodes` 只把内容库已有 `shots` 写成工坊 beats。规划走导入后的 `shot_plan` 任务，不在同步请求里做。开发代理超时改为 15 分钟。
- 受影响文件：`project_detail_service.py`、`ContentLibraryPane.tsx`、`vite.config.ts`、对应测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、端口或 ComfyUI。未规划文档同步解析器镜头；需要规划时请重新导入。
- 验证命令：`python -m unittest backend.tests.media_studio_test_storyboard_images`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-18 导入按集规划出片镜头，生成 H3 不再程序拆镜

- 变更原因：导入只正则抄写 `### 镜头`，生成 H3 时再用口型/内心/近景规则把一条剧情镜炸成三条，既不准也太晚。集数已写在台本 `# 第N集` 里，不该让大模型再切集。
- 当前基线：解析器仍只认 `# 第N集`（无集头则整篇第 1 集），每集补 `body`。粘贴/文件导入在 `create_document` 只解析落库，再入队 `shot_plan` 逐集调用 `LlmService.plan_episode_shots`（单镜 5–15 秒），覆盖 `shots` 并标记 `shots_source=llm`；失败保留解析器镜头并写 logs，不让整单失败。`input_mode=ai_pipeline` 跳过规划。同步工坊只拷贝文档已有出片镜，不再补跑规划。`POST …/h3-prompt` 点哪条入队一个任务，不再 `should_split_beat`；工坊已有拆开镜仍可 `merge_as_one`。澄清题 `shots_per_episode` 说明改为导入时规划镜头。
- 受影响文件：`script_parser.py`、`episode_shot_planner.py`、`llm_service.py`、`project_detail_service.py`、`h3_take_split.py`、内容库/澄清题前端、对应测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、端口或 ComfyUI。未规划文档同步解析器镜头；AI 流水线文档不二次拆镜。
- 验证命令：`python -m unittest backend.tests.test_standard_script_parser backend.tests.test_episode_shot_planner backend.tests.media_studio_test_storyboard_images backend.tests.test_h3_coverage`；`pnpm --dir frontend exec vitest run src/director2/director2-stage-choices.test.ts`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-18 内容库同步剧集工坊可覆盖或只补新集

- 变更原因：内容库可保存多份剧本，但「同步至剧集工坊」原先只改 `title` / `script_text` / `shots_count`，不重写 `data_json.beats`；工坊详情只要已有 beats 就不会按新剧本重建，同一部剧再导入看起来像没同步。
- 当前基线：`POST /api/projects/{project_id}/documents/{doc_id}/transfer-episodes` JSON `{ mode }`，缺省 `overwrite`。覆盖按本剧本重写对应集的镜头（新 beat id，不带旧草图/视频），并删除这份剧本里没有的旧集。`append` 跳过已有集号，只创建还没有的集。工坊为空时前端直接覆盖；已有集时弹出单选「覆盖已有集数 / 只补新集」。
- 受影响文件：`project_detail_service.py`、`project_router.py`、`frontend/src/director2/api.ts`、`ContentLibraryPane.tsx`、`EpisodeWorkshopPane.tsx`、`backend/tests/media_studio_test_storyboard_images.py`、三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、端口或 ComfyUI。旧客户端不传 `mode` 时按覆盖处理（含重写 beats）。
- 验证命令：`python -m unittest backend.tests.media_studio_test_storyboard_images`；`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-18 半解说包暂时旁路本地 H3 装箱

- 变更原因：中文八块分秒是 Hub 给 MiniMax Design 的导演文档，不是本地 `MiniMaxH3Director` 出片格式。`polish_ref2va` / `prepare_generated_prompt` 会把 GPT 英文六段盖成骨架 + 中文 `00:00–` + 灌水句 + 轿厢句。
- 当前基线：配方 `packing_overrides.skip_program_pack`。半解说包临时为 `true`。打开后：`polish_ref2va` 只有合法 `authored_en_prompt`（六段标题且校验通过）才出片，不再 `render_ref2va` + 灌时间码；英文缺失、无六段标题或校验失败则任务失败，不回退无时间码骨架、不覆盖 Beat。`generate_h3_prompt` 与双稿写稿不再 `prepare` / overlay / 第二次装箱 LLM。工坊 `h3_prompt` 落库与出片规范化 `<Picture>` / `<Subject>` 和六段 `name:` 标题。校验放宽到六段标题、台词逐字、`<Picture n>`，280 英文词不再挡短稿。中文分秒仍写入 `timestamped_zh_prompt`。未绑技能包仍走默认程序装箱。把 `meta.yaml` 该行改回 `false` 即恢复。
- 受影响文件：`skill_packs/recipe.py`、`handlers.py`、半解说包 `meta.yaml`、`llm_service.py`、`h3_prompt_job_service.py`、`episode_video_service.py`、对应测试与三份主文档、`docs/API.md`。
- 兼容性：不改四阶段 ID、表结构、端口或 ComfyUI。默认配方不受影响。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video backend.tests.test_skill_packs`。
- 回滚方式：半解说包 `skip_program_pack` 改回 `false`，或还原上述文件。

## 2026-09-18 工坊生成提示词直播思考与正文

- 变更原因：工坊「生成 H3 提示词」虽已对流式读取上游，界面仍只显示「正在生成…」，看不到 GPT-5 思考过程和逐字成稿。
- 当前基线：上游 SSE 把 `reasoning_content` / `<think>` 与正文分开回调。`h3_prompt` 任务经 `GET /api/projects/{project_id}/jobs/{job_id}/events` 推送 `status` / `reasoning` / `delta` / `done`。工坊素材组按 beautifului Thinking + Streaming Text 语法直播（可折叠思考轨迹、正文 blur-in 与光标）。任务 payload 另存 `stream` 快照，轮询可兜底。不改表结构。
- 受影响文件：`llm_client.py`、`llm_service.py`、`h3_prompt_job_service.py`、`project_router.py`、工坊前端直播组件、对应测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：导演台既有 `on_chunk` 仍只收正文。无思考字段的模型只直播正文。
- 验证命令：`python -m unittest backend.tests.test_llm backend.tests.media_studio_test_h3_video`；`pnpm --dir frontend exec vitest run src/director2/workshop-prompt-live.test.ts`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-18 写稿看图走多模态 LLM，工坊一次产出中英双稿

- 变更原因：工坊第一次看图走独立弱 VLM，装箱再走纯文本 LLM；`gpt-5.6-sol` 配在 LLM 页也看不到图。看图失败还会静默改成纯文本。
- 当前基线：`vision_runtime.py` 统一解析。写稿/润色（工坊 H3、生成页优化、导演台最终润色）优先用名称可看图的 LLM，否则用已启用的 VLM；7B 等纯文本模型不发 `image_url`。反推/拉片/主体分析仍默认 VLM，VLM 未开且 LLM 可看图时才回退 LLM。工坊一次多模态请求按 `<<<ZH>>>` / `<<<EN>>>` 同时写中文八块和英文六段；英文通过校验则跳过第二次 `_request_h3_prompt`。半解说包 `skip_program_pack` 时中文或英文未过即任务失败；未绑包时中文过、英文不过仍可用 `polish_ref2va` 六段壳叠加细节。任务记录 `vision_status`（`used` / `failed_text_fallback` / `unavailable`），工坊提示词旁显示看图状态。`GET /api/llm/status.supports_vision` 表示写稿路径能否附图。VLM 页可复用 LLM 凭据（默认关）。本地 H3 仍只吃角色卡、场景卡、起幅。
- 受影响文件：`vision_runtime.py`、`llm_service.py`、`skill_packs/handlers.py`、`vlm_provider.py`、`llm_provider.py`、`models.py`、`main.py`、管理页 LLM/VLM、工坊前端、对应测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改技能包四阶段 ID；不把整张三联送进本地 H3。`vlm_provider_settings.use_llm_credentials` 默认 0。未绑技能包仍走默认程序装箱。
- 验证命令：`python -m unittest backend.tests.test_vision_runtime backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video backend.tests.test_llm backend.tests.test_vlm`；`pnpm --dir frontend exec vitest run src/director2/workshop-vision-status.test.ts`。
- 回滚方式：还原上述文件并去掉 `use_llm_credentials` 列。

## 2026-09-18 工坊生成提示词走流式并识别中转站 504

- 变更原因：自定义中转站写长 H3 提示词时 nginx 返回 HTML `504 Gateway Time-out`，工坊任务把整页 HTML 当成失败原因。
- 当前基线：工坊 `LlmService.chat_text` 与看图写作 `chat_on_endpoint` 改走 `OpenAICompatibleClient`，流式读取以免中转站 60 秒掐断；GPT-5 / o 系列测试外的长写使用 `reasoning_effort=low`，并与连接测试一样不传 `temperature`。504/网关超时改写为中文说明，超时会自动再试一次。
- 受影响文件：`llm_client.py`、`llm_service.py`、`vision_runtime.py`、对应测试与三份主文档。
- 兼容性：不改表结构、端口或 ComfyUI。Qwen 等非 GPT-5 模型不传 `reasoning_effort`。
- 验证命令：`python -m unittest backend.tests.test_llm backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-18 LLM 测试连接改用完整创作请求

- 变更原因：自定义 OpenAI 兼容中转站能拉 `/v1/models`，但「测试连接」发送「请仅回复两个字：收到」会被上游判为非法短输入 / 心跳探测（HTTP 400）。
- 当前基线：LLM / VLM「测试连接」只发一句略长的身份询问（「你好，你是什么模型」），模型有回复即成功；`max_tokens` 为 128。GPT-5 / o 系列不传 `temperature`、改用 `max_completion_tokens`，测试时带 `reasoning_effort=none`。若上游仍返回 short-input / heartbeat probing，错误文案说明「目录可通 ≠ 对话可通」。
- 受影响文件：`backend/app/llm_client.py`、`backend/tests/test_llm.py`、`frontend/src/admin/LlmProviderSettings.tsx`、三份主文档。
- 兼容性：不改数据库、端口、ComfyUI 或已保存的 LLM 配置。
- 验证命令：`python -m unittest backend.tests.test_llm`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-18 工坊 LLM 写中文分秒稿并忠实装箱

- 变更原因：半解说包工坊只把 heading/action/camera/dialogue 填进官方八块，没有 LLM 看三联写分秒；后面又按「一句对白一个运镜」重排，对不上 Design 成稿。
- 当前基线：绑定半解说包时，`write_timestamped_zh_prompt` 用 LLM 按官方第 8 / 8.1 步与八块模板写中文分秒稿（管理后台 VLM 启用时附角色卡、场景卡、整张三联或左中右裁切）。校验失败重试一次，再失败则任务失败，不回退骨架填空、不覆盖 Beat。有 `timestamped_zh_prompt` 时六段装箱以中文稿为 `detailed_description` 唯一调度权威：`render_ref2va` 不再一句一运镜，`build_packing_user_prompt` 不再下发 COVERAGE LANDINGS 重写指令，`prepare_generated_prompt` 不再把 tilt-up / push-in 整句硬插到 `<d>` 前（门禁修补仍保留）。`packing_overrides.faithful_zh_pack=true`。R2V 末槽仍是起幅，不送整张三联。覆盖合同只在生成后校验，失败只 LLM 重装箱。
- 受影响文件：`backend/app/skill_packs/handlers.py`、`recipe.py`、`llm_service.py`、`h3_prompt_builder.py`、`half-narrated-live-action-short-drama/meta.yaml`、对应测试与三份主文档、`docs/API.md`。
- 兼容性：未绑技能包仍走默认程序装箱与覆盖硬插入。不改表结构、端口或 ComfyUI 节点。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-18 工坊官方 H3 模板填稿与导台2 章节注入

- 变更原因：半解说包已换成 Hub 原文，但工坊仍可能重建八块稿、R2V 只送角色+场景；导台2 四阶段若按正文关键词截 SKILL.md 会灌进无关章节。
- 当前基线：工坊 `workshop_shot` 按官方 `h3-video-prompt-template.md` 填中文分秒稿（时间码从本镜 `00:00` 起），再程序润色六段 Ref2VA。R2V 槽位为角色卡 + 场景卡 + 三联**起幅**；有起幅时出片参考图末槽送起幅，整张三联不上传。生成提示词会把 `timestamped_zh_prompt` 写回 Beat。导台2 仍是 `script → assets → episodes → storyboard`，`inject_craft` 按官方标题注入对应章节：剧本双通道（对白/画面分离）、白底 16:9 角色/场景卡、镜头合同 5–15 秒；不注入 Seed Audio。
- 受影响文件：`backend/app/skill_packs/handlers.py`、`runner.py`、`context.py`、`h3_prompt_builder.py`、`llm_service.py`、`h3_prompt_job_service.py`、`episode_video_service.py`、`director_craft/references.py`、`backend/tests/test_skill_packs.py`、`backend/tests/media_studio_test_h3_video.py` 与三份主文档、`docs/API.md`。
- 兼容性：未绑技能包仍走默认程序装箱与角色+场景参考图。不改表结构、端口或 ComfyUI 节点。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video backend.tests.media_studio_test_storyboard_images`。
- 回滚方式：还原上述文件即可。

## 2026-09-18 半解说包改用 Hub 官方原文，三联母图只送起幅

- 变更原因：磁盘上的半解说包仍是重建稿；官方 Hub 包定位后，要用原文约束剧本/定妆/分镜，并避免本地 H3 把 16:9 三联插值成一条画面。
- 当前基线：`backend/app/skill_packs/half-narrated-live-action-short-drama/` 使用 Hub `v1.0.1` 的 `SKILL.md` 与 `h3-video-prompt-template.md`（`@Image` 改为 `<Picture n>`），`SOURCE.md` 标明路径与适配。`confirm_format` 为 9:16、H3 **5–15** 秒、分辨率 `user-confirmed`（2K / 768P）。工坊 `workshop_shot` 仍为三联 → 裁切 → 填官方模板 → 六段润色 → 绑槽位。`StoryboardImageService` 新增 `stage=triptych`：16:9 / 2K 母图，完成后写 `triptych_url` 并裁切 `triptych_panels.start|mid|end`；R2V 只推进起幅。`POST .../generate-triptych` 入队。提示词任务默认仍不入队三联生图。不做 Seed Audio。
- 受影响文件：`backend/app/skill_packs/`、`storyboard_image_service.py`、`episode_image_prompts.py`、`h3_prompt_job_service.py`、`project_detail_service.py`、`project_router.py`、工坊前端、`backend/tests/test_skill_packs.py` 与三份主文档、`docs/API.md`。
- 兼容性：未绑技能包仍走默认程序装箱。不改表结构、端口或 ComfyUI 节点。已有 Beat 无三联字段时行为与原先一致。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video backend.tests.media_studio_test_storyboard_images`。
- 回滚方式：还原上述文件即可。

## 2026-09-18 技能包步骤注册表与项目 extra.skill_pack_id

- 变更原因：Plaza 短剧模板需要整条制作配方，但不能让 LLM 当 Design Agent 自由调工具；中止前的注册表代码已在磁盘上，需要补完接线而不是推倒重写。
- 当前基线：`backend/app/skill_packs/` 扫描包目录 `meta.yaml`，步骤 id 必须已在 Python handler 注册。项目 `settings_json.extra.skill_pack_id` 绑定配方（空为默认程序装箱）。工坊 Ref2VA 走 `SkillPipelineRunner`；H3 `packing_system_prompt` 读取配方 `packing_overrides`（默认仍禁止时间码与多段运镜）。导台2 四阶段 ID 不变，只在绑定技能包时 `inject_craft`。`GET /api/skill-packs` 列出配方。提示词任务默认不入队三联生图。
- 受影响文件：`backend/app/skill_packs/`、`project_service.py`、`llm_service.py`、`h3_prompt_job_service.py`、`h3_prompt_builder.py`、`ai_generation_service.py`、`director_agents.py`、`llm_minimax_skills.py`、`llm_client.py`、`llm_provider.py`、`models.py`、`main.py`、`api_documentation.py`、`frontend/src/director2/api.ts`、`backend/tests/test_skill_packs.py` 与三份主文档、`docs/API.md`。
- 兼容性：未绑技能包的项目仍走默认 `render_ref2va_default`；不改表结构、端口或 ComfyUI 节点。未知 `skill_pack_id` 创建/更新项目或优化提示词返回 400。
- 验证命令：`python -m unittest backend.tests.test_skill_packs backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可；已写入 extra 的项目可把 `skill_pack_id` 清空。

## 2026-09-17 工坊 H3 参考图权威与确定性校验

- 变更原因：Subject 行仍可能抄小传，CAST LOCK 进六段，场景图被当成站位锁；覆盖/内心闭嘴/运镜落点靠模型自觉，独立审片和 I2VA 首尾帧还不能当 v1 前提。
- 当前基线：工坊编译按 `character_ids` / 上传顺序写短 Subject：角色 `<Picture n>` 只锁身份、不迁移姿势；场景 Picture 声明不锁站位。资产索引只映射编号与资产，不把造型小传写进装箱 user 或六段。`_validate_h3_prompt` / `validate_prompts` 用正则检查覆盖主体是否在内心段、`follows his gaze`、内心是否开口、已站定是否写开门、上摇/推近落点。独立 LLM 审片、失败 retake、I2VA 首尾帧控制等级仍下一波。
- 受影响文件：`director_craft/references.py`、`director_craft/coverage.py`、`h3_prompt_builder.py`、`llm_service.py`、`h3_prompt_job_service.py`、`llm_minimax_skills.py`、对应测试与三份主文档。
- 兼容性：不改表结构或 API；`h3_prompt_source=manual` 仍按原文出片。重新点「生成 H3 提示词」即可换上身份短定义。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video backend.tests.test_h3_coverage`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 H3 从动作编译并可拆出片镜

- 变更原因：工坊仍从文学 visual_prompt 抠 `follows his gaze`，口型、内心钉构图和二次运镜抢同一次采样；`shots_per_episode=6` 被当成硬顶。
- 当前基线：工坊「生成 H3 提示词」从 Beat 的动作/运镜/台词编译六段 Ref2VA（官方 `tilts up/down|pushes in` + `with small amplitude at slow speed`；内心钉胸腰闭嘴；最后开口才推近）。旧英文 visual_prompt 只作补丁，不再默认文学 gaze。`h3_prompt_source=manual` 仍按原文出片。同一剧情镜若同时有开口对白、内心覆盖和第二次运镜，当时默认拆成多条出片镜（`parent_beat_id` + `take_role`，`story_shot` 保留剧情号）；`POST …/h3-prompt` 可带 `merge_as_one=true` 合并回一条再生成。剧本/分镜只加一屏覆盖合同，不新增 Markdown 标签。`shots_per_episode` 只作节奏建议。**2026-09-18 起**：生成 H3 不再调用 `should_split_beat`，出片镜改在导入时按集规划，见文首。
- 受影响文件：`director_craft/coverage.py`、`h3_prompt_builder.py`、`h3_take_split.py`、`project_detail_service.py`、`llm_minimax_skills.py`、工坊前端、对应测试与三份主文档、`docs/API.md`、`docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构；旧 Beat 无 take 字段时仍按单镜生成。重新点「生成 H3 提示词」即可拆镜或覆盖旧六段。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video backend.tests.test_h3_coverage backend.tests.test_director_clarify`；`pnpm --dir frontend exec vitest run src/director2/workshop-beat-label.test.ts`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 H3 提示词支持手动编辑

- 变更原因：工坊素材组提示词面板只读，外部 AI 写好的六段无法贴回本镜。
- 当前基线：`PUT …/beats/{beat_id}` 可写 `h3_prompt` 与 `h3_prompt_source`。素材组可编辑、粘贴并保存；系统生成仍走原任务并标记 `generated`。手动保存标记 `manual`，出片只规范化 `<Picture>`/`<Subject>` 大小写，不再 `prepare` 改写正文，也不因厚度/对白校验失败而重渲染该镜。
- 受影响文件：`EpisodeWorkshopPane.tsx`、`episode-workshop.css`、`api.ts`、`project_detail_service.py`、`h3_prompt_job_service.py`、`episode_video_service.py`、`media_studio_test_h3_video.py`、三份主文档、`docs/API.md` 与 `docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构；旧 Beat 无 `h3_prompt_source` 时仍走生成路径的 prepare + 校验。
- 验证命令：`python backend/tests/media_studio_test_h3_video.py`；`pnpm --dir frontend exec vitest run src/director2/h3-prompt-display.test.ts`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 内心戏画面停在被看的人身上

- 变更原因：抽帧显示「浓妆艳抹 / 黑色小短裙」时画面是沙丽丽胸腰铺满竖屏（吴耐不出画）；生成片却先推吴耐近景，变成双人中景再切他的脸。
- 当前基线：内心节拍只接下摇/钉住对方身子，并写明衣服铺满画面、思考者不出画；推思考者近景放在内心 `<d>` 之后。动作与 PERFORMANCE 按「画面停在谁身上」写，不先写「推到谁脸上」。
- 受影响文件：`h3_prompt_builder.py`、`media_studio_test_h3_video.py`、`tmp/huajia/花甲正少年-剧本.md`、三份主文档与 `docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构或 API；重新点「生成 H3 提示词」覆盖旧六段。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 内心戏把视线下摇接到被看的人身上

- 变更原因：镜头 1 吴耐内心「浓妆艳抹」时，程序按 FIFO 把「推房东 + 下摇衣服」捆成一句，PERFORMANCE 里「顺着他的视线下摇过红吊带和短裙」被丢掉，画面停在吴耐脸上。
- 当前基线：内心节拍优先使用 gaze / tilt-down-outfit 运镜，可先落到思考者近景再顺着视线看到对方衣服；最后一句开口优先 push back。不是切到对方主观视角。
- 受影响文件：`h3_prompt_builder.py`、`media_studio_test_h3_video.py`、三份主文档与 `docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构或 API；重新点「生成 H3 提示词」覆盖旧六段。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 Ref2VA 拆开工坊模板再渲染时间轴

- 变更原因：按句顺序装箱会把人物小传写进 Subject、把构图说明当运镜、把 PERFORMANCE 英文复述整段堆在开口后面，内心也会出现两句 thinks。
- 当前基线：`<Subject n>` 只锚参考图，不抄角色小传。COMPOSITION 按 then 切开，一句运镜接一句锁定台词；LOCATION/LIGHTING/CAST LOCK 作锁定层；PERFORMANCE 里的英文台词复述、花字旁注和 Lip-sync 粘贴丢掉。音效从 SYNCHRONIZED SOUND 写入 overall_soundscape。
- 受影响文件：`h3_prompt_builder.py`、`media_studio_test_h3_video.py`、三份主文档。
- 兼容性：不改表结构或 API；重新点「生成 H3 提示词」覆盖旧六段。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 Ref2VA 由程序渲染 [Shot 1]

- 变更原因：让模型写六段正文再靠规则修补，会出现自造场景标签、重复 thinks、开口后再推镜；继续加正则只会换皮复发。
- 当前基线：工坊「生成 H3 提示词」和出片回退的 Ref2VA 不再调大模型写时间轴。程序按参考图写 `<Subject n>`（不抄人物小传），按剧本写入锁定 `<d>`，COMPOSITION 运镜句与台词交错，冻结放最后。LOCATION/LIGHTING/CAST LOCK 保留为锁定层，不把 PERFORMANCE 英文复述当正文。T2VA/I2VA 仍走装箱。不安装 open-h3-ir，不接官方 Context-IR。
- 受影响文件：`h3_prompt_builder.py`、`llm_service.py`、`media_studio_test_h3_video.py`、三份主文档与 `docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构或 API；点「生成 H3 提示词」即可覆盖旧六段。厚草稿不依赖大模型。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 H3 对白按 open-h3-ir 占位渲染

- 变更原因：禁止模型写 `<d>` 后再整段删 `says`、把锁定台词接到 `[Shot 1]` 末尾，会把运镜撕成 `medium-clos in a casual young female voice`，冻结也跑到开口之前。
- 当前基线：装箱只把 `{{D1}}` token 放在对应运镜节拍，编号对照单独写、禁止抄进正文；(Sn) 必须等于 `<Subject n>`，场景只用 `<Subject n>`。`fill_speech_placeholders` 填回锁定开口/内心，清掉 `then speaks` / `spoken lip-sync —` / `speaks with` 残句、错位 hold 和 `<Location n>`。多句对白若把全部运镜堆在开口前会校验失败并重写 `[Shot 1]`。不接入 open-h3-ir 的 Comfy 节点。
- 受影响文件：`h3_prompt_builder.py`、`media_studio_test_h3_video.py`、三份主文档、`docs/API.md` 与 `docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构或 API；重新生成即可。不安装 open-h3-ir，不新增 ComfyUI。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 H3 对白由程序锁进 [Shot 1]

- 变更原因：装箱后模型仍在英文正文里写 `<d>`，把「大爷」写成「八字」，吴耐开口留在散文里，`[Shot 1]` 合同缺句。汉字已在任意标签里就不补说话人合同。
- 当前基线：`prepare_generated_prompt` 先删掉模型写的全部 `<d>` 和正文里的锁台词汉字，再按剧本演出顺序写入 `[Shot 1]`（开口 / 闭嘴内心交错）。Packer 禁止输出 `<d>`。校验拒绝多余标签和顺序错误。
- 受影响文件：`h3_prompt_builder.py`、`llm_service.py`、`media_studio_test_h3_video.py`、三份主文档与 `docs/API.md`。
- 兼容性：不改表结构；重新生成或出片复用时覆盖模型假台词。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 H3 收拢英文夹杂的复读台词

- 变更原因：第一集第二镜「啊？大爷你不要房租？该不会想让我那啥吧？我是正经人，卖艺不卖身的。」生成失败。动作把一句台词拆成多段，模型装箱时夹在英文中间；校验按汉字序列判定复读，旧收拢只删连续原文，Lip-sync 英文正则又因非贪婪+可选结尾只删了前缀。
- 当前基线：`collapse_repeated_speech` 按汉字序列从 `<d>` 以外删掉同一句；`_flexible_line_re` 允许分句之间夹非汉字。草稿清洗会删 Lip-sync 整段和 4 字以上分句。生成、落库、出片仍先 `prepare_generated_prompt` 再校验。
- 受影响文件：`h3_prompt_builder.py`、`media_studio_test_h3_video.py`、三份主文档。
- 兼容性：不改表结构或 API；已失败任务点「生成 H3 提示词」重试即可。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 H3 提示词按 MiniMax Design 装箱

- 变更原因：工坊「生成 H3 提示词」把已有厚 `visual_prompt` 交给模型后，system 仍要求「展开 320 词」另写一场戏；校验失败再整份重写。质量在第二跳丢失，出片回退 `H3PromptBuilder.build_prompts` 也会对冲工坊结果。
- 当前基线：Ref2VA system 改为 packer 短合同（官方 Workflow/Output Rules/Tips + Complete Example + 标签纪律）。清洗后的英文草稿放进 `SOURCE VISUAL DRAFT` 作为画面正文权威；厚草稿只装箱保住构图/光/调度/运镜/禁止项，薄草稿只补缺失的 camera/lighting/sound/时序。有参考图时 `subject_definitions` 写 appearance from `<Picture N>`，正文不再小说式重描五官。草稿或 `aspect_ratio` 已写 9:16/16:9 则原样保留。校验失败只修合同项（`Keep the same detailed_description; only fix these contract issues.`），禁止 Rewrite the complete prompt。出片回退走同一套装箱 user。词数仍是输出门槛，不再当改写压力。
- 受影响文件：`llm_service.py`、`h3_prompt_builder.py`、`episode_video_service.py`、`EpisodeWorkshopPane.tsx`、`media_studio_test_h3_video.py`、三份主文档与 `docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、工坊默认 16:9、导演台四步流程或 MiniMax Design 产品接入。已保存超薄 `h3_prompt` 出片时仍会装箱重写。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 Director 整集直出也可生成选中镜头

- 变更原因：H3 Director 加速版（整集直出）镜头卡没有勾选，「一键生成视频」只会提交 1 个整集 Timeline；用户想先出某一镜时只能改用逐镜工作流。
- 当前基线：「一键生成视频」在 Director 下仍是 1 个 `render_scope=episode` 任务。镜头卡始终可勾选；「生成选中」把 `beat_ids` + `force` 交给同一 `POST …/generate-video`。Director 把勾选镜放进 **1 个** Timeline 任务（多镜作为同一 Comfy graph 的分段，超 6 段/1152 帧才在该任务内再切 chunk），`render_scope=selection`（一镜仍是 `shot`）。成片按镜拆开写入各 Beat `video_url`。逐镜工作流仍是每镜一个 graph 任务。未勾选时 Director 仍一次出整集。合成 Tab 在各镜都有 `video_url` 时可拼接，Director 直出的分集成片仍直接播放。
- 受影响文件：`episode_video_service.py`、`EpisodeWorkshopPane.tsx`、`media_studio_test_h3_video.py`、三份主文档与 `docs/导演台流程与界面结构.md`。
- 兼容性：不改表结构、端口或节点 ID；不传 `beat_ids` 的 Director 一键生成行为不变。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`、`pnpm --dir frontend test`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 H3 先补全再校验

- 变更原因：模型输出常缺句号、漏 `<Picture N>`、同一句中文再抄一遍。旧链路先按原文精确匹配校验，失败则不跑 normalize；宽松正则又把标点变体计成复读，同一镜同时报 missing 和 duplicated。
- 当前基线：`generate_h3_prompt`、落库 `_finalize_prompt`、出片 `_workshop_prompts_usable` 都先 `H3PromptBuilder.prepare_generated_prompt`（规范化标题与参考标签、补合同行、按汉字收拢重复台词、内心改闭嘴画外音），再校验。逐字与唯一性比较汉字序列，`<Picture N>` 大小写不敏感。
- 受影响文件：`h3_prompt_builder.py`、`llm_service.py`、`h3_prompt_job_service.py`、`episode_video_service.py`、`media_studio_test_h3_video.py`、三份主文档与 `docs/API.md`。
- 兼容性：不改表结构；重新生成或出片复用时自动补标签并去掉第二份中文。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-17 工坊 H3 内心不口型同步、中文台词不复读

- 变更原因：第一镜内心「浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙」被动作、visual_prompt、video_prompt_zh、对白原文、多轮对白各贴一遍，且 `吴耐（内心）` 被当成必须 `<d>` 口型同步的开口台词；重新生成还会把旧提示词整段塞回 user。成品里同一句中文出现两次。
- 当前基线：`H3PromptBuilder.split_spoken_and_inner` 把「内心/旁白/画外音」从开口对白里拆出。组装 user 时剥掉「本镜对白必须口型同步 / Lip-sync the exact Chinese line(s)」粘贴块，并跳过与动作重复的 `video_prompt_zh`；不再把 `existing_prompt` 交给模型。校验要求开口台词与内心原文各只出现一次，内心必须闭嘴画外音、禁止口型同步。生成结果的补标签与收拢复读见上一条 `prepare_generated_prompt`。
- 受影响文件：`h3_prompt_builder.py`、`llm_service.py`、`h3_prompt_job_service.py`、`EpisodeWorkshopPane.tsx`、`media_studio_test_h3_video.py`、三份主文档与 `docs/API.md`。
- 兼容性：不改表结构；旧 Beat 动作里若仍粘着整段台词，生成时会剥掉。已保存的复读提示词需重新生成。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-16 云端 LLM 测试连接等待推理模型

- 变更原因：自定义 OpenAI 兼容接口能拉到 `/v1/models`，但「测试连接」只等 15 秒并只给 8 个 completion token。GPT-5 / R1 等推理模型和中转站首字经常超过 15 秒，被误报成连接失败。
- 当前基线：LLM / VLM「测试连接」统一等待 90 秒（本地冷启动与云端推理模型相同）。探测对话使用 256 个 token，避免思考过程把额度吃光后写不出「收到」。超时文案区分「目录可通 ≠ 对话可通」。
- 受影响文件：`backend/app/llm_client.py`、`llm_provider.py`、`vlm_provider.py`、`backend/tests/test_llm.py`、`frontend/src/admin/LlmProviderSettings.tsx`、三份主文档。
- 兼容性：不改数据库、端口、ComfyUI 或已保存的 LLM 配置；快模型仍会立刻返回。
- 验证命令：`python -m unittest backend.tests.test_llm`。
- 回滚方式：还原上述文件并重启工作台。

## 2026-09-16 出片复用工坊 H3 提示词前先 normalize

- 变更原因：工坊已生成的 Ref2VA 只缺 `<Subject 3>` 或 `<d>[Chinese]` 标签时，出片校验直接失败并现场再调一次 LLM；任务详情又只读 `shots[].prompt`，工坊已有 `h3_prompt` 会被显示成「提示词尚未生成」。
- 当前基线：`EpisodeVideoService._workshop_prompts_usable` 先走与现场生成相同的 `H3PromptBuilder._normalize_prompt`（补 Subject/Picture 合同行、对白标签、hold 句），再跑 `validate_prompts`。通过则 `prompt_source=workshop_material`，跳过 `prompt_generation` 调 LLM。过薄或对白对不上仍重写。`H3PromptJobService` 落库前同样 normalize。全部任务详情读 `prompt || h3_prompt`。
- 受影响文件：`episode_video_service.py`、`h3_prompt_job_service.py`、`JobsCenterPane.tsx`、`director2-job-types.ts`、对应测试与三份主文档。
- 兼容性：不改表结构与 jobs API 字段；超薄旧提示词仍会重写。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`、`pnpm --dir frontend exec vitest run src/director2/director2-job-types.test.ts`。
- 回滚方式：还原上述文件即可。

## 2026-09-16 剧集工坊时长与 H3 接入导演台1 timing 预算

- 变更原因：工坊 Beat 常存 `video_duration=5`，H3 只加载官方 `h3-prompt-writing`，导演台1 的 Seedance timing skill 没有接到出片链，厚调度会被压进 5 秒。
- 当前基线：`resolve_shot_duration_sec` 按对白+调度抬高 2–15 秒（不缩短用户更长设定），工坊打开分集、落库 Beat、「生成 H3 提示词」都会写回 `video_duration`。`LlmService` / `H3PromptBuilder` 注入 `build_workshop_h3_timing_rules`（与导演台1 `load_shot_timing_excerpt` 同一套预算：约 4 字/秒、2–3 秒一拍、禁止 5 秒塞走位+转身+长对白），但 Ref2VA 禁止 `At HH:MM.SSS` 时间码。H3 按已匹配的 N 秒写 `[Shot 1]`，不再写死 8 秒。不复刻导演台1 那轮改 JSON `promptText` 的 LLM 时长润色。
- 受影响文件：`backend/app/dialogue_timing.py`、`llm_minimax_skills.py`、`media_studio/services/{ai_generation_service,project_detail_service,h3_prompt_job_service,llm_service,h3_prompt_builder,script_parser}.py`、`EpisodeWorkshopPane.tsx`、对应测试与三份主文档。
- 兼容性：不改表结构；已有工坊项目下次打开分集时，过短的 `video_duration` 会按剧本抬高，不会压短用户已设的更长秒数。
- 验证命令：`python -m unittest backend.tests.test_dialogue_timing backend.tests.test_director2_ai_generation backend.tests.media_studio_test_h3_video backend.tests.test_standard_script_parser backend.tests.test_director_clarify`、`pnpm --dir frontend exec vitest run src/director2/director2-script-live-view.test.ts`。
- 回滚方式：还原上述文件即可。

## 2026-09-16 剧集工坊 H3 提示词按可出片厚度生成

- 变更原因：工坊「生成 H3 提示词」不把 `visual_prompt` / `audio` 传给模型，校验只查六段标题和对白；出片只要已保存 `h3_prompt` 超过 30 字就复用，超薄提示词会直接进 Comfy。
- 当前基线：`H3PromptJobService.enqueue` 把 Beat 的 `visual_prompt`、`audio`、`video_prompt_zh` 写入 `beat_info`。`LlmService._h3_user_prompt` / `_h3_system_prompt` 要求英文至少 320 词，并把中文动作、英文 visual_prompt、音效展开进 `detailed_description` / `overall_soundscape`；`_validate_h3_prompt` 对齐 `H3PromptBuilder.thickness_errors`（英文词数 ≥280，必须出现 camera / lighting / sound），外加对白原文、Ref2VA `<Picture N>` 与单镜 `[Shot 1]`，失败则带错误重写（仍 2 次尝试）。落库与出片复用前都先 `H3PromptBuilder._normalize_prompt`。`EpisodeVideoService._run_job` 仅在规范化后的已保存提示词通过 `validate_prompts` 时设 `prompt_source=workshop_material`，否则走 `H3PromptBuilder.build_prompts`。
- 受影响文件：`backend/app/media_studio/services/{h3_prompt_job_service.py,llm_service.py,h3_prompt_builder.py,episode_video_service.py}`、`backend/app/api_documentation.py`、`backend/tests/media_studio_test_h3_video.py`、三份主文档与 `docs/API.md`。
- 兼容性：不改表结构与 jobs API 字段；过薄的旧 `h3_prompt` 出片时会重写，不再因「超过 30 字」被复用。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video backend.tests.test_director2_ai_generation backend.tests.test_standard_script_parser backend.tests.test_director_clarify`。
- 回滚方式：还原上述文件即可。

## 2026-09-16 导演台剧本与分镜落库加厚

- 变更原因：剧本步把每个镜头教成「一个可见动作变化」并禁止提示词，分镜落库又把内容库压成画面/运镜/对白三行，工坊 Beat 只剩一句话动作。
- 当前基线：`build_script_agent_prompt` 把一个 `### 镜头` 写成可提交的 8 秒单镜：动作含空间/调度/收束，并写音效与画面/调度英文「提示词」（不是工坊六段 Ref2VA）。`STORYBOARD_JSON_CONTRACT` / `DIRECTOR_STUDIO_ADAPTER` 要求 `description` 承接厚动作、`promptText` 禁止一句话、默认 `durationSec=8`。`_recipe_text` 按内容库标准写出人物/场景/道具/动作/运镜/台词/音效/提示词；若集正文已含 `### 镜头` 则不再前置以免双份镜头卡。`_beat_payload` 把厚 `description` 写入 `action`，`promptText` 写入 `visual_prompt`/`sketch_prompt`，格式化 `camera`，`audio←soundscape`，`video_prompt_zh` 拼接动作+运镜+声音，`video_duration` 用 `durationSec`（默认 8）。直播卡仍隐藏「提示词」标签。
- 受影响文件：`backend/app/llm_minimax_skills.py`、`ai_generation_service.py`、`script_full_story.py`、`director_agents.py`、`frontend/src/director2/director2-script-live-view.ts`、对应测试与三份主文档。
- 兼容性：不改表结构与解析器字段名；已导入旧项目不回写，只影响之后「AI 生成 / 重新生成剧本 / 重新生成分镜」。
- 验证命令：`python -m unittest backend.tests.test_director2_ai_generation backend.tests.test_standard_script_parser backend.tests.test_script_full_story backend.tests.test_director_clarify`、`pnpm --dir frontend exec vitest run src/director2/director2-script-live-view.test.ts`。
- 回滚方式：还原上述文件即可。

## 2026-09-16 导演台视频任务进度对齐 ComfyUI

- 变更原因：全部任务里的视频生成进度条不是 ComfyUI 采样步进，而是 `/history` 轮询时从 50% 每次 +1%，和 ComfyUI 页面不一致。
- 当前基线：`ComfyVideoClient` 提交前连接 `/ws?clientId=`，用 `interpret_comfy_progress` 把 `progress` / `progress_state` 写成 `ai_project_jobs.progress`（采样节点百分比与 ComfyUI 一致，导出封顶 99，完成才 100）。无 WebSocket 时不再假递增。全部任务列表改为 1 秒轮询。
- 受影响文件：`backend/app/media_studio/services/{comfy_video_client.py,episode_video_service.py}`、`frontend/src/director2/panes/JobsCenterPane.tsx`、`backend/tests/media_studio_test_h3_video.py`。
- 兼容性：jobs API 字段不变；准备阶段仍可能从上传进度跳到 Comfy 队列/采样进度。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`。
- 回滚方式：还原上述文件即可。

## 2026-09-16 剧集工坊素材组与 H3 对白清洗

- 变更原因：检视器里的高精渲染图 / 分镜动态视频不参与 H3 Director 出片；用户需要按镜头编辑参考图并预生成 H3 提示词。模型常把「沙丽丽：」写进 `<d>` 对白标签，成片会念出角色名。
- 当前基线：镜头检视器保留分镜草图，去掉渲染图与单镜视频检视（顶栏「一键生成视频」和合成 Tab 仍可用）。新增「素材组」：最多 9 张参考图（角色造型 → 场景 → 道具）+ H3 提示词面板。`POST /api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/h3-prompt` 入队 `job_type=h3_prompt`，`LlmService.generate_h3_prompt` 按官方 skill 生成后清洗 `<d>`（台词不含说话人姓名）。`H3PromptBuilder` 从 `姓名："台词"` 解析对白轮次。整集/逐镜视频若每镜已保存且通过厚度校验的 `h3_prompt` 则 `prompt_source=workshop_material`，不再现场调 LLM。全部任务增加「H3 提示词」Tab。
- 受影响文件：`backend/app/media_studio/services/{h3_prompt_builder.py,llm_service.py,h3_prompt_job_service.py,episode_video_service.py,project_detail_service.py}`、`project_router.py`、`main.py`、`frontend/src/director2/{api.ts,h3-prompt-display.ts,director2-job-types.ts,panes/EpisodeWorkshopPane.tsx,panes/episode-workshop.css}`、测试与三份主文档。
- 兼容性：草图/渲染图/单镜视频 API 仍在；渲染图与单镜视频只是工坊检视器不再展示。不改表结构。旧 Beat 无 `h3_prompt` 时视频仍走 `H3PromptBuilder.build_prompts`。
- 验证命令：`python -m unittest backend.tests.media_studio_test_h3_video`、`pnpm --dir frontend test`。
- 回滚方式：还原上述文件即可；已写入的 `h3_prompt` 可忽略。

## 2026-09-16 剧集工坊整集直出 / 逐镜生成分流

- 变更原因：剧集工坊「一键生成视频」原先无论选什么工作流都走 MiniMaxH3Director Timeline，且整集只能有 1 个进行中视频任务；官方 H3 / LightX2V / 八步双加速 / T8 无法逐镜出片，合成 Tab 也没有后端接口。
- 当前基线：`episode_video_render_mode(workflow_id)` 只读注册表 `supports_timeline && supports_multi_segment`。Director 加速版 R2V 仍是 1 个整集 Timeline 任务（超 6 段/1152 帧继续 `plan_timeline_chunks` + ffmpeg）；完成后把 `episode_video_url` / `episode_video_source=director_direct` 写入 `ai_project_episodes.data_json`。其它多参考 R2V 的一键生成改为每个缺成片的 Beat 各建 1 个 `render_scope=shot` 任务，graph 走现有 `build_minimax_h3_workflow` / LightX2V / dual accel / T8，时长取该镜 `video_duration`。并发锁：整集/合成互斥；单镜只锁同一 `beat_id`。新增 `POST /api/projects/{project_id}/episodes/{episode_id}/compose`：全镜 `video_url` 就绪后 ffmpeg 拼接并回写 `episode_video_source=composed`；Director 直出且各镜未逐镜出片时 400。工坊「生成设置」列出全部未隐藏多参考 R2V（`reference_mode=collection` 且 `max_references>=3`），按 `catalog_group_label` 分组并标注「整集直出 / 逐镜」。`GET /api/modes` 的 `ModeResponse` 现回传 `supports_timeline` / `supports_multi_segment`，前端据此判定模式，不自行声明。一键生成按模式提示「已创建 1 个整集任务」或「已提交 N 镜（跳过 M 镜已有成片）」；逐镜模式镜头卡可勾选，工具条「生成选中（N）」把 `beat_ids` + `force` 交给同一接口，只提交勾选镜（已有成片也会重跑），`_prepare_shots` 前置检查也只校验这些镜；检视器「生成本镜」同样只检查当前 Beat。合成 Tab 在逐镜下显示已出片 x/n 并可点「一键合成全集成片」，Director 直出则隐藏合成按钮、直接播 `episode_video_url`。3 秒轮询覆盖视频/合成任务，完成后刷新分集详情。
- 受影响文件：`backend/app/models.py`、`backend/app/media_studio/services/{timeline_rendering.py,episode_video_service.py,comfy_video_client.py,project_detail_service.py}`、`backend/app/media_studio/routers/project_router.py`、`frontend/src/director2/{director2-video-settings.ts,api.ts,panes/Director2VideoSettingsPopover.tsx,panes/EpisodeWorkshopPane.tsx,panes/episode-workshop.css}`、`backend/tests/{test_timeline_rendering.py,media_studio_test_h3_video.py}`、`frontend/src/director2/director2-video-settings.test.ts`。
- 兼容性：旧 `job_id` 字段保留；一键生成额外返回 `render_mode` / `job_ids` / `submitted` / `skipped`。不改表结构、端口或 Comfy 节点 ID。T2V/I2V/T8 双时钟/VACE 不进入工坊列表。
- 验证命令：`python -m unittest backend.tests.test_timeline_rendering backend.tests.media_studio_test_h3_video`、`pnpm --dir frontend test`。
- 回滚方式：还原上述前后端文件即可；已写入 `data_json` 的成片字段可忽略。

## 2026-09-16 导演台2取消后重试会清掉取消标记

取消任务落为 `cancelled` 后，payload 里仍保留 `cancel_requested`。`_update` 原先无条件锁住该标记，导致「从当前阶段重试」把任务重新入队后，新 worker 立刻再次取消。现仅在仍有活跃 worker（queued/running/clarifying/revising）时锁住该标记；从终态入队时允许清掉。页头「正在停止当前生成」只在进行中显示。验证：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend test`。回滚：还原 `ai_generation_service.py` 与 `director2-ai-operation-state.ts`。

## 2026-09-16 TTS 供应商预设（硅基流动 CosyVoice2）

TTS 管理页新增与 LLM/VLM 同级的「快速服务预设」：默认推荐 SiliconFlow CosyVoice2（按 UTF-8 字节计费，非 LLM 永久免费档）、OpenAI 官方与自定义接口。后端 `tts_provider.py` 按上游返回对应音色目录；旧 Recipe 中 OpenAI 音色 ID（onyx/nova）在硅基流动配置下会自动映射。验证：`python -m unittest backend.tests.test_tts_provider backend.tests.test_director.DirectorAvExportTests.test_tts_writes_succeeded_status`。

## 2026-09-16 TTS 独立管理页

TTS 语音合成从 LLM 管理页拆出，新增管理页签「TTS 语音合成」：`/admin/tts`，组件 `frontend/src/admin/TtsProviderSettings.tsx`。后端 API（`GET/PUT /api/admin/providers/tts`、`POST …/tts/test`）与 `tts_provider_settings` 表不变；仍支持「复用大模型凭据」。用户可见未就绪提示由「管理设置 → LLM」改为「管理设置 → TTS」。验证：`pnpm --dir frontend build`、打开 `http://127.0.0.1:5173/admin/tts` 自查；`python -m unittest backend.tests.test_director`（TTS 相关用例）。回滚：删除 TTS 页签与组件，将表单迁回 `LlmProviderSettings.tsx`。

## 2026-09-16 独立 VLM 视觉模型配置

看图推理不再占用 LLM 配置。新增 `vlm_provider_settings` 与管理页签「VLM 视觉模型」：`GET/PUT /api/admin/providers/vlm`、`POST …/vlm/test`、`POST …/vlm/models`、`GET /api/vlm/status`。资产库 `infer-prompts`、`POST /api/llm/analyze-subject`、复刻台拉片只走 VLM；提示词优化、拆剧本、导演 Agent 仍走 `llm_provider_settings`。`GET /api/llm/status.supports_vision` 表示 VLM 是否可用，不再看 LLM 模型名。保存 VLM 时校验名称含 VL/Vision（含 `glm-4.6v`）。默认关闭，推荐智谱 `glm-4v-flash`。验证：`python -m unittest backend.tests.test_vlm backend.tests.test_director.DirectorAnalyzeEndpointTests backend.tests.test_llm.LLMAppEndpointsTests`。回滚：删表与 VLM 页，视觉调用改回 LLM。

## 2026-09-16 导演台资产库按原片反推提示词

导演台 `/director2` 资产库在已有 `source_references` 时可 `POST /api/projects/{id}/assets/{id}/infer-prompts`：下载最多 3 张原片图，用独立 VLM 视觉模型反推 JSON，覆盖头像/面部/描述/当前造型服装（角色）或场景/道具提示词。VLM 未启用返回 400。验证：`python -m unittest backend.tests.test_asset_prompt_inference backend.tests.test_vlm`。回滚：还原 inference 模块、llm_service、project_detail_service、路由与资产库面板。

## 2026-09-16 导演台资产库原片参考图优先于旧提示词

导演台 `/director2` 资产生图在存在 `source_references` 时：头像不再把 `avatar_prompt`/描述写进 GRS；造型图不再把衣装正文当服装源，也不再把已生成头像混进参考图。原片截图最高优先级，禁止按文字加外套。验证：`python -m unittest backend.tests.test_asset_source_references`。回滚：还原 `asset_source_references.py`、`asset_image_prompts.py`、`project_detail_service.py` 与资产库面板。

## 2026-09-16 导演台资产库原片参考图

导演台 `/director2` 资产库角色、场景、道具均可上传最多 9 张原片截图，写入 `ai_project_assets.extra_json.source_references`（七牛 `asset-ref/`）。生成头像、造型、场景主视角、道具概念图时，这些图排在 GRS `images` 最前并追加身份锁定提示词；反打/全景/转面/特写仍只吃已生成的主图链。新增 `POST/DELETE /api/projects/{id}/assets/{id}/references`。验证：`python -m unittest backend.tests.test_asset_source_references`、`pnpm --dir frontend test`。回滚：还原参考图 helper、项目详情服务、资产库面板与文档。

## 2026-09-16 导演台2创意确认增加每集镜头数

导演台2 创意确认在方向问题之后固定两道控制题：`episode_count`（分多少集）和 `shots_per_episode`（每一集默认拍多少个镜头，档位 4/6/8/12，推荐 6）。剧本按每集默认镜数拆写，分集缺省 `targetShots` 填该值，分镜消费已确认集大纲。旧 `/director` 仍用全剧 `beat_count`。验证：`python -m unittest backend.tests.test_director_clarify backend.tests.test_director2_ai_generation`。回滚：还原澄清题与 script/episodes agent 约束。

## 2026-09-16 导演台剧集工坊视频生成设置

剧集工坊「一键生成视频」与「生成本镜」共用 `/api/modes` 注册表里的 H3 Director 加速版参数，不再写死 0.4 MP / 20 步。`POST …/generate-video` 现接收 options（`aspect_ratio` / `quality` / `speed` / `weight_profile`）；`EpisodeVideoService.resolve_generation_options` 经 `normalize_options` 校验后写入任务 payload，`ComfyVideoClient` 按注册表计算画布（如 0.4 MP 16:9 = 864×480，1.0 MP = 1376×768）并映射步数、精简/完整 UNET。时长仍按 Beat，不在整集设置里覆盖。默认 16:9、0.4 MP、均衡 20 步、精简 20 GB。旧客户端不传 body 时走同一默认值。验证：`python -m unittest backend.tests.test_timeline_rendering backend.tests.media_studio_test_h3_video`、`pnpm --dir frontend test`。回滚：还原工坊前后端与 Comfy Timeline 客户端。

## 2026-09-16 剧本确认卡按标准台本排版

导演台2 剧本步 `fullStory` 按内容库标准 Markdown 台本生成（`build_script_agent_prompt`：`# 第N集` / `### 镜头` / 真实换行，每个镜头为 8 秒单镜厚动作并写音效与画面英文提示词），落库前 `normalize_script_full_story` 把 Beat 账本和无换行糊墙字整理成可切分镜头块；场景切分同时认 `【` 与 `### 镜头`。前端 `parseScriptLiveView` + `groupScriptLiveView` + `Director2ScriptLiveBody` 把直播/确认卡渲染为 `.director-stream-article`：定位/人物常驻，集层用与分镜共用的 `DirectorEpisodeCapsule`（确认默认收起、直播展开当前集）；刷新回填 `recipe.script`；旧导演台 `StoryParagraphs` / `DirectorScriptDocument` 共用解析高亮、不加集胶囊。SSE 仍是 `title` / `summary` / `fullStory`。验证：`python -m unittest backend.tests.test_director backend.tests.test_director2_ai_generation backend.tests.test_script_full_story`、`pnpm --dir frontend test`。回滚：还原 prompt、`script_full_story.py` 与导演台2 剧本卡渲染。

## 2026-09-16 剧本确认卡按集折叠

导演台2 剧本确认卡过长滚动问题：`Director2ScriptLiveBody` 改为 preamble（片名/定位/人物）常驻 + 按 `# 第N集` 的集胶囊手风琴；分镜与剧本共用 `DirectorEpisodeCapsule`。无集头旧稿仍线性手稿。不改 SSE/API。验证：`pnpm --dir frontend test`；5173 待确认剧本卡不用滚完全文即可看到集清单。回滚：还原 `Director2ScriptLiveBody`、`groupScriptLiveView` 与文档对「剧本不加集胶囊」的约束。

## 2026-09-16 导演台入口互换与 /director2 新首页

侧边栏「导演台」入口改指 `/director2`（新导演台），「导演台2」（原「导台2」）指向 `/director`（旧导演台）；URL 不变，旧工程深链不受影响，`App.tsx` 新增 `lastDirector2PathRef` 记录最近 `/director2` 路径用于导航回跳。`/director2` 首页由 `Director2Home.tsx`（创作项目列表页，已删除）替换为 `Director2StudioHome.tsx`：逐像素复刻旧导演台首页（复用 `index.css` `.director-home-v2`/`.dh-*` 双主题样式），列表接 `/api/projects`；「导演创作」直接创建「未命名导演工程」进入内容库；「短视频批量 / 参考片复刻」沿用旧导演台 `/api/director/projects` 创建并跳转 `/director/batch/:id`、`/director/replication/:id`；卡片仅「打开/删除」（导演台2 无复制接口）。首页分支不渲染 AI Media Studio 顶导航、不套 director2 强制亮色 antd 主题（`Director2App.tsx` 拆分，暗色主题正确）；旧导演台首页标题改为「导演台2」。验证：`pnpm --dir frontend build`（内含 vitest 与 tsc）；5173 浅色/暗色、390×844 移动宽度与创建/删除/跳转闭环自查。回滚：还原前端文件即可，`Director2Home.tsx` 可从 Git 历史恢复。

## 2026-09-16 导演台2 AI 逐步卡点确认

导演台2 AI 流水按四个真实卡点推进：`script → assets → episodes → storyboard`。每个 leg 只跑该阶段 agents（`script`；`characters+locations`；独立 `episodes`；`storyboard` 消费已确认的 `recipe["episodes"]`），跑完写入 `awaiting_stage` 并进入 `awaiting_review`（暂停、不占 worker、不发 terminal）。「采纳」`POST …/advance` 把当前步记入 `completed_stages` 并启动下一 leg，最后一步采纳后 `succeeded`。「不满意」`POST …/revise` 进入 `revising`，按该阶段 `feedback` 流式出澄清卡，作答后 `POST …/rerun` 只重跑当前步并回到确认卡。`ACTIVE` 不含 `awaiting_review`，`OCCUPYING` 含 `awaiting_review/revising`；`create` / `GET …/ai/operations/active` 按占用槽位判重与接管。进程重启只收敛 `queued/running/clarifying/revising`，待确认任务保留给用户继续审核。GET 公开载荷额外回传 `stage_clarifications`，供完成步骤行回显已选选项；SSE 协议不变。验证：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend test`、`pnpm --dir frontend build`。回滚：还原 `AiGenerationService` 状态机、路由、episodes agent 与导台2 卡点 UI。

## 2026-09-16 导演台2完成步骤选项回显

导演台2 AI 创作室完成步骤行不再只显示笼统摘要。`AiGenerationService._public` 把 payload 里的 `stage_clarifications` 带回 GET / 接管；前端 `director2-stage-choices.ts` 把创意确认的 `request.clarifications` 与各阶段修订答案去重后映射为只读 chip。记录流在用户创意气泡下方增加按阶段分组的「创作路径」Tool Chips（chip 文案为答案、`title` 为 `问题 → 答案`；无答案则不渲染）。`DirectorLiveStepRow` 在 30px 行头下方始终展示 `问题 → 答案`（或「已采纳本次生成」/「已跳过，沿用默认」），不增加 `aria-expanded` 或集胶囊手风琴。阶段抽屉顶部同步列出同一组选项。验证：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend test`。回滚：还原 `_public`、helper、路径条与步骤行接线。

## 2026-09-15 导演台2 AI 生成模式 v1

导演台2项目详情新增 `AI 生成 / 手动编辑` 双模式。AI 模式通过 `/api/projects/{project_id}/ai/operations` 创建项目级流水线，首期覆盖创意澄清、剧本、角色/场景/道具文本、分集和 Beat 分镜；2026-09-16 起改为四步卡点确认，见上一节。结果通过适配层写入导台2现有表，不改变导演台 Recipe 存储。角色/场景/道具会写入内容库文档的人物、场景、道具章节与 `analysis`，切换「手动编辑」后内容库与资产库都能看到同一批数据。任务以 `ai_pipeline` 写入 `ai_project_jobs`，复用导演台 SSE 事件格式；手动模式和既有逐项生成接口保持兼容。同一项目同时只允许一个活跃 AI 任务（含待确认与调整中）；后端启动时把重启遗留的 worker 活跃 `ai_pipeline` 任务收敛为 `failed`（可重试），前端通过 `GET /api/projects/{project_id}/ai/operations/active` 自动接管进行中的任务。验证：`pnpm --dir frontend build`、`python -m unittest discover -s backend/tests -p 'test_*.py'`。回滚：隐藏 AI 模式入口，不删除已有数据。

AI 工作区视觉接线复用导演台现有 `DirectorPromptBar`、`DirectorTaskRows` 和 `guided-flow.css` 的 `director-recipe-shell[data-look="cinema"]` 结构；不再维护一套独立的 Director2 Card 样式，顶部模式切换也复用 `DirectorCreationModeSwitch`。澄清问答进一步抽为双方共用的 `DirectorClarificationCard` 与纯状态机：预置项高亮后 480ms 自动进入下一题，自定义输入与预置答案严格分离，同时统一支持上一题/下一题、进度点、跳过本题和「跳过全部，直接生成」。

## 组件关系

```text
React/Vite frontend
        -> FastAPI session + CSRF + RBAC
        -> MySQL ai-media（users/sessions/audit_logs/jobs/director_* / xiaji_* / provider settings）
        -> 单任务 Worker
        -> ComfyUI API（默认 http://127.0.0.1:8188，管理后台可改）
        -> OpenAI 兼容 TTS（/v1/audio/speech，可复用 LLM 凭据或独立配置；小米 MiMo 走 /v1/chat/completions 适配）
        -> 本机 ffmpeg/ffprobe（成片 concat / 混音 / 可选烧字幕）
        -> 七牛云对象存储（任务输出与上传素材；管理设置保存 AK/SK）
        -> 浏览器 File System Access API -> 员工授权目录
        -> ZLYUN AI Tauri 客户端 -> 受限 Rust 写盘命令 -> 员工授权目录
        -> POST delivered 回执 -> 标记本机交付完成
```

Docker 部署：React 在镜像构建阶段生成 `frontend/dist`，运行阶段由同一 FastAPI 容器托管。Linux 服务器 Compose 使用 `host` 网络，FastAPI 仅监听 `127.0.0.1:18189`；Nginx 在 `https://comfyui.zlyun168.com/` 代理前端和 `/api` 后端。ComfyUI 不进入 Compose，也不向公网暴露路径；工作台通过服务器内部 `http://127.0.0.1:18188` 访问唯一实例，该地址可以是 FRP 映射到服务器回环地址的远端 ComfyUI。容器不挂载 ComfyUI `output`，已完成视频不写入服务器磁盘。

Windows 本地开发由 `启动本地视频工作台.bat` 同时启动 Vite（`0.0.0.0:5173`）与 FastAPI（`0.0.0.0:7865`）。浏览器始终打开本机 Vite 地址 `http://127.0.0.1:5173`（含 FastAPI 已在 7865 运行时的重复双击）；同一局域网可用 `http://<本机IPv4>:5173` 或 `http://<本机IPv4>:7865`。`/api` 由 Vite 代理到 FastAPI，以提供 React 热更新。FastAPI 由 `backend/dev_reloader.py` 在独立进程组中拉起 uvicorn（无 `--reload`），监视 `backend/app` 源码变更并在崩溃后重启；`frontend/dist` 继续仅用于 FastAPI 的生产静态托管、局域网访问和 Docker 镜像，启动脚本不再自动打开 7865。双击 `关闭本地视频工作台.bat` 结束 `5173` 与 `7865` 上的工作台进程树及启动控制台，不停止固定 ComfyUI `8188`。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| `frontend/src/Root.tsx` | 按 `/api/auth/status` 做鉴权闸门：初始化、登录、强制改密后进入创作台或管理设置 |
| `frontend/src/paths.ts` | 前端路径常量、管理 Tab 权限与登录回跳规则 |
| `frontend/src/router.tsx` | `BrowserRouter` 路由表：登录/改密、管理设置、创作台壳 |
| `frontend/src/auth/AuthScreens.tsx` | 登录、首次超级管理员初始化与强制改密界面 |
| `frontend/src/admin/AdminSettings.tsx` | 管理设置（账号 / AI 供应商 / LLM / VLM / TTS / 媒体存储） |
| `frontend/src/App.tsx` | 已登录创作台壳：由 URL 驱动生成 / 导演台（`/director` 首页与项目壳，`/director/batch|replication` 两项工作室）/ 资产；图/视频与选中任务；工作流、参考图草稿仍在组件 state |
| `frontend/src/xiaji/XiajiStudioModule.tsx` | 导台2：项目内内容库、资产库、剧集工坊、全部任务 |
| `frontend/src/xiaji/XiajiHome.tsx` | 导台2 项目列表与新建 |
| `frontend/src/xiaji/XiajiAssetsModule.tsx` | 导台2 资产库：角色/场景/道具/声线定义与生成 |
| `frontend/src/xiaji/XiajiWorkshopModule.tsx` | 导台2 剧集工坊：规划落库、脚本 Beat、镜头与成片合成 |
| `frontend/src/xiaji/XiajiShotsWorkbench.tsx` | 导台2 镜头工作台：左 Beat 网格、右文案/单帧/参考图 |
| `frontend/src/director2/Director2StudioHome.tsx` | 导演台首页：导演创作主入口 + 两项工作室 + 剧本诊断 + 合并最近工程 |
| `frontend/src/director2/Director2ProjectDetail.tsx` | 导演创作项目壳：内容库 / 资产库 / 剧集工坊 / 全部任务 |
| `frontend/src/director/DirectorStudioModule.tsx` | 短视频批量 / 参考片复刻装配 |
| `frontend/src/director/types.ts` | 批量/画风辅助与 Recipe 类型兼容层（九阶段 UI 已下线） |
| `frontend/src/local-resource-store.ts` | 目录句柄/资源索引 IndexedDB 持久化及本地文件读写 |
| `desktop/client/` | ZLYUN AI 客户端本地启动页与品牌图标 |
| `desktop/src-tauri/` | Tauri Windows 壳、可信 origin capability 与受限本地资源命令 |
| `backend/dev_reloader.py` | 本机 Windows 开发监督器：无 `--reload` 拉起 uvicorn，源码变更或崩溃后重启 |
| `backend/app/main.py` | HTTP API、认证依赖、资源交付、上传和静态前端托管 |
| `backend/app/xiaji_visual_styles.py` | 导台2 内容库六项视觉风格预设与风格说明 |
| `backend/app/xiaji_store.py` | 导台2 内容库文档/章节/分析持久化（项目隔离） |
| `backend/app/xiaji_project_store.py` | 导台2 项目 CRUD 与旧数据回填 |
| `backend/app/xiaji_asset_store.py` | 导台2 资产库角色/场景/道具/声线与媒体版本 |
| `backend/app/xiaji_episode_store.py` | 导台2 剧集、资产绑定与 Beat |
| `backend/app/xiaji_episode_prompts.py` | 导台2 草图/精绘/视频提示词与人工 Beat 规范化 |
| `backend/app/xiaji_literal_script.py` | 导台2 生成脚本：逐行标注，一行一个 Beat |
| `backend/app/xiaji_episode_api.py` | 导台2 剧集工坊 API |
| `backend/app/xiaji_compose.py` | 导台2 剧集成片：本机 ffmpeg 拼接、字幕与 SRT/ZIP |
| `backend/app/xiaji_episode_run_store.py` | 导台2 整集自动生成编排记录 |
| `backend/app/xiaji_auto_pipeline.py` | 导台2 整集串行草图/精绘/提示词/视频 |
| `backend/app/auth.py` | scrypt 密码、会话、用户、角色和审计数据访问 |
| `backend/app/resource_storage.py` | 可替换资源 provider 契约、browser-stream 引用实现与旧版 browser-local 暂存兼容 |
| `backend/app/workflow_registry.py` | 工作流能力、参考图上下限、H3 参数校验 |
| `backend/app/minimax_h3_workflow.py` | 根据上传参考图动态生成 H3 API graph |
| `backend/app/rtx_vsr_workflow.py` | 旧独立 RTX 2x 超分 API graph（不占用 H3 节点 ID）；2026-11-02 起不再被「智能超清」调用，仅保留给旧生成页接口 |
| `backend/app/minimax_h3_t8_workflow.py` | 生成全能参考多速率与双时钟 T8 API graph |
| `backend/app/comfy_provider.py` | 超级管理员可配置的 ComfyUI 连接地址、连接测试与运行时解析 |
| `backend/app/comfy_service.py` | 上传素材、提交 ComfyUI prompt、轮询、下载结果；队列空闲时 `POST /free` 卸载模型 |
| `backend/app/director_compiler.py` | 导演台按 MiniMax H3 官方 skill 编译提示词、Recipe 参考图装箱，按所选工作流族自动路由 T2V/I2V/R2V |
| `backend/app/director_catalog/` | 9 类 34 条画风 JSON 种子与查询 |
| `backend/app/director_recipe.py` | Recipe / 批量 payload 规范化、画风目录校验、旧时间轴转 Recipe |
| `backend/app/director_library.py` | 员工级人物/场景/道具资产库规范化、从 Recipe 快照、插入工程 |
| `backend/app/voice_bank/` | 内置短剧配音声线：IndexTTS 官方示例 wav + 产品侧角色名 |
| `backend/app/tts_provider.py` | 独立 TTS 供应商；硅基 CosyVoice 走 OpenAI 兼容 `/audio/speech`；本机 IndexTTS-2.5 走旁路 `/v1/tts/clone` 与 `/health` `/free`；小米 MiMo 走 `/v1/chat/completions` 的 base64 音频通道（`OpenAICompatibleClient.speech_via_chat`） |
| `backend/app/gpu_runtime.py` | H3（ComfyUI）与 IndexTTS 同卡互斥：领取前卸载对方；空闲 `/free` 不得打断占用中的一方 |
| `backend/app/media_studio/services/dubbing_mix.py` | 台词混音策略与 ffmpeg 叠轨；半解说包旁白门闩 |
| `backend/app/worker.py` | 单任务串行执行；Comfy 跑前 `occupy_gpu("comfy")` 卸载 IndexTTS；队列空闲且 GPU 未被 TTS/H3 占用时才 `POST /free` |
| `tools/indextts_sidecar/` | IndexTTS-2.5 旁路 HTTP 服务（不进 FastAPI venv，权重在父级整合包） |
| `backend/app/media_studio/services/dubbing_service.py` | 导演台2 台词轨展开、单句导演参数、配音生成调度 |
| `backend/app/director_export.py` | 逐镜 TTS、BGM、ffmpeg 成片、FCPXML/EDL；失败镜头不进入成片 |
| `backend/app/director_agents.py` | 顺序调度；导演对话走 SSE 流式读取（连接 20 秒、分块空闲 300 秒）；独立 `episodes` agent 写集大纲，分镜优先消费已确认结构；分镜读取官方 h3-prompt-writing，并依次做时长润色与 Seedance 风格衔接润色；配音/配乐写可播放媒体元数据；绑定技能包时 `_system` 注入 `inject_craft` |
| `backend/app/skill_packs/` | 技能包配方（Hub 官方 Markdown + `meta.yaml` + `summary`）与步骤注册表；首页/顶栏绑定项目 `extra.skill_pack_id`；空 id 默认配方「H3 官方六段式」按官方 Skill 用大模型装箱，`skip_program_pack=True`；工坊一次写官方八块中文分秒稿和英文六段；半解说包临时 `skip_program_pack` 出片用 GPT 英文、不程序装箱；R2V 绑角色卡+场景卡+三联三格成片画幅构图（不送 16:9 母图）；导台2 四阶段按官方标题 `inject_craft` |
| `backend/app/media_studio/services/ai_generation_service.py` | 导台2 项目级 AI 流水：澄清 → 四步卡点（`awaiting_review` / `advance` / `revise` / `rerun_stage`）；`retry(stage=…)` 可从已完成的更早阶段重跑并作废后续步骤；结果适配写入内容库/资产库/剧集工坊；阶段生成套 `skill_pack_scope` |
| `backend/app/llm_minimax_skills.py` | MiniMax H3 风格技能、官方 prompt-writing、shot-timing 与 shot-continuity 加载器，供生成页优化和导演台分镜共用 |
| `backend/app/script_full_story.py` | 剧本 `fullStory` 规范化与按 `【` / `### 镜头` 切场景，供导演台与导台2 共用 |
| `backend/app/shot_continuity_skill/` | Seedance 2.5 改编的 scene ledger / 相邻镜交接方法，供剧本与分镜 Agent 使用 |
| `backend/app/h3_prompt_writing/` | MiniMax 官方 `h3-prompt-writing` skill 原文（SKILL.md、T2VA/Ref2VA 参考） |
| `backend/app/director_jobs.py` | Recipe 定妆 GRS 入队、七牛地址回写、分镜/批量按所选工作流族入队 |
| `backend/app/db.py` | MySQL 连接池与 SQLite 测试适配；连接信息读取 `docs/存储配置.md` |
| `backend/app/storage.py` | 任务、owner、交付状态与导演工程元数据（生产 MySQL，unittest SQLite） |
| `frontend/dist/` | FastAPI 生产环境托管的前端构建产物 |
| `frontend/scripts/clean-dist.mjs` | `pnpm build` 前清空 `dist` 的构建脚本（本机 Node `fs.rmSync` 会静默失败，改走 shell 删除） |
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

## 2026-09-18 本机 Vite 对局域网 IPv4 开放

- 当前基线：`启动本地视频工作台.bat` 将 Vite 绑到 `0.0.0.0:5173`（`--host 0.0.0.0`，`allowedHosts: true`），FastAPI 仍为 `0.0.0.0:7865`。本机浏览器仍打开 `http://127.0.0.1:5173`；启动窗口打印 `http://<本机IPv4>:5173` 与 `http://<本机IPv4>:7865`。脚本尝试在 Windows 防火墙 Private/Domain 配置文件放行 `5173/tcp` 与 `7865/tcp`（无管理员权限时跳过，不中断启动）。`/api` 仍由 Vite 代理到本机 `127.0.0.1:7865`。首次 `/api/auth/setup` 仍仅允许工作站回环地址。ComfyUI 仍只由本机工作台访问 `127.0.0.1:8188`，不向局域网暴露。
- 原因：开发入口先前只绑回环地址，同一台机器的局域网 IPv4 或同网设备无法打开 5173。
- 受影响文件：`启动本地视频工作台.bat`、`frontend/vite.config.ts`、`AGENTS.md`、`README.md`、`功能说明与扩展指南.md` 和本文件。
- 兼容性：本机 `127.0.0.1:5173` / `127.0.0.1:7865`、端口号、API、Cookie、任务队列和 Docker 部署路径不变。已在运行且绑在 `127.0.0.1` 的旧 Vite 需先关闭再启动。
- 验证命令：双击 `关闭本地视频工作台.bat` 后重新启动；本机访问 `http://127.0.0.1:5173`，再用 `http://<本机IPv4>:5173` 打开同一登录页。
- 回滚方式：将启动脚本 Vite `--host` 恢复为 `127.0.0.1`，去掉 `allowedHosts: true`，删除 `ZLY AI Video Studio LAN 5173` / `7865` 防火墙规则（如已创建）。

## 工作流协议

## 2026-08-31 导演台结构化角色定妆与资产版本协议

- 当前基线：导演 Recipe 使用 `assetSchemaVersion: 2`。角色由 `identitySpec`（年龄、脸型、发型、肤色、体态、不可变配饰等）+ `portrait` 身份肖像 + 一个或多个 `looks[].sheet` 四联定妆板组成；地点使用 `plate` 空场景母版，道具使用 `props[].turnaround` 四视图转面图。每个 rendition 保存 `versions[]`、`activeVersionId`、`approvedVersionId`、提示词快照、工作流和执行选项。
- 生成协议：`POST /api/director/recipes/{project_id}/generate-assets` 先生成身份肖像；批准后，定妆板以批准肖像作为唯一 `<Picture 1>` 参考。地点、道具分别生成空场景母版和四视图转面图。生成候选不会自动批准，`POST /api/director/recipes/{project_id}/approve-asset-version` 才能将版本投入分镜参考图和资产库。
- 绑定协议：分镜镜头优先写入稳定的 `characterBindings`、`locationId`、`propIds`，名称字段只作为旧工程兼容。编译器按资产 ID 装箱，并在 stable 绑定模式下超过 MiniMax H3 的 9 张参考图上限时返回可操作错误，不再静默截断；旧名称模式继续保留历史最多 9 张的兼容行为。
- 调度顺序：创作方案默认按 `research -> script -> art_style -> characters -> locations -> storyboard -> voice -> music -> media` 执行，使分镜能读取已规范化的人物、场景和道具目录；公开的旧 `AGENT_IDS` 顺序和历史 `agentStatus` 仍兼容。
- 兼容性：旧工程的 `imageUrl/imageJobId` 会投影成已批准的单一 rendition；旧时间轴和旧资产库字段无需迁移。新结构化资产必须先批准候选图才能导入资产库，旧无版本资产仍按历史规则可读。未修改端口、SQLite 表、ComfyUI 节点 ID、模型路径和工作流外部协议。
- 受影响文件：`backend/app/director_recipe.py`、`director_jobs.py`、`director_compiler.py`、`director_agents.py`、`director_library.py`、`director_project_service.py`、`models.py`、`main.py`，`frontend/src/director/recipe-model.ts`、`recipe-execution.ts`、`director-api.ts`、`DirectorRecipeStudio.tsx`、`components/RecipeAssetWorkbench.tsx`、`index.css` 及对应测试。
- 验证命令：`python -m pytest backend/tests -q`、`pnpm --dir frontend build`。浏览器检查导演台桌面 1440×900 与手机 390×844：身份肖像→定妆板、版本历史批准、资产库门禁、角色/地点/道具稳定绑定、超过 9 张参考图的提示和双主题弹层。
- 回滚方式：恢复上述代码和前端构建产物后重启工作台；Recipe schema 2 为增量规范化，不需要数据库回滚。若需保留已生成候选图，可只回滚 UI/API 入口，历史 `imageUrl` 投影仍可读取。

当前 `/api/modes` 注册以下视频工作流，并下发 `catalog_group` / `catalog_group_label` / `catalog_group_order` 供创作页分组：

- LightX2V：`minimax-h3-lightx2v-t2v`（0 张）、`minimax-h3-lightx2v-i2v`（1-2 张首尾帧）、`minimax-h3-lightx2v-r2v`（1-9 张参考图）。默认 1.0 MP、快速 4 步、euler 采样，加载 `G:\ComfyUI-Models\lightx2v` 下的 LightX2V LoRA；官方 H3 三个模式的节点 ID 不改动。开启二采精修时改走 Director 两段式，一采由平台固定为快速 4 步、对应 4 步 LoRA 与 euler，不再读取用户的速度选择。
- 八步双加速：`minimax-h3-dual-accel-t2v`（0 张）、`minimax-h3-dual-accel-i2v`（1-2 张首尾帧）、`minimax-h3-dual-accel-r2v`（1-9 张参考图）。复用参考 JSON 的加速链：`LoraLoaderModelOnly`（`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`，强度 1.0）→ `PathchSageAttentionKJ`（`auto` / 禁止 compile）→ `MiniMaxH3MemoryEfficientSageAttentionPatch`，默认 0.4 MP、8 步 `res_multistep` 与 video/audio Shift 12/3。默认不接入 `MiniMaxH3Director` 节点；仅开启二采精修时改用 Director 两段式，一采由平台固定为完整权重、8 步 LoRA 与双 Sage。文生/首尾帧用全量 INT8 FL2VA，多参考用全量 INT8 Ref2VA。
- 官方 MiniMax H3：`minimax-h3-t2v`、`minimax-h3-i2v`、`minimax-h3-r2v`。动态 API graph 在既有节点 1–15 之后接入 `ReservedVRAMSetter`（预留 3 GB 并在采样前清缓存）与 `MiniMaxH3MemoryEfficientSageAttentionPatch`，避免 16GB 显卡在 `SamplerCustomAdvanced` 的 INT8 QKV 上 OOM。既有节点 ID 不变。三个官方模式支持可选的「二采精修」（`refine_enabled`）：开启后改走 `minimax_h3_refine_workflow.py` 的 Director + `MiniMaxH3DirectorRefine` 两段式 graph。全部 H3 工作流（官方、LightX2V、八步双加速、Director 加速、T8）都不再暴露 `upscale_after`，统一提供 `refine_enabled` / `refine_quality`；开启二采后一采固定 0.4 MP，步数、LoRA、unet 与 Sage 由平台按工作流族锁定，不再读取用户选择。
- 自定义：`minimax-h3-t8-all-reference`（0-9 张；无图 `T2VA`+FL2VA，有图 `Ref2VA`+Ref2VA，`MiniMaxH3MultiRateSamplerEXPT8`）、`minimax-h3-t8-dual-clock`（0-1 张；无图 `T2VA`，单图 `I2VA` 首帧，`MiniMaxH3DualClockSamplerT8`）。默认使用 T8 专有采样器；开启二采精修时一采改走 Director 两段式，由平台固定为完整权重、8 步 Turbo LoRA（全能参考视频 8 步 / 音频 10 步），T8 专有采样器与音频模式不参与二采。
- 隐藏（2026-11-02 起降为历史能力）：`nvidia-rtx-vsr` 与 `seedvr2-upscale` 不出现在创作页模型列表，也不再是「智能超清」的实现方式——导演台2 的智能超清改为复放本镜生成图只跑二采（见文末同名章节）。两个 graph 本身保留：`LoadVideo → GetVideoComponents → RTXVideoSuperResolution（固定 2x / ULTRA）→ CreateVideo → SaveVideo` 与 SeedVR2 3B Int8 子图，节点编号不变，仍可由旧生成页 `POST /api/jobs/{job_id}/upscale`（前端入口已下线）和 `GET /api/upscale/capabilities`（前端已不调用）触发；历史任务里已存在的 2x 结果仍只读回显。H3 生成选项不自动接跑 RTX 超分；显存门闸读当前连接 GPU 的 `vram_total`。

H3 options 使用 JSON：`aspect_ratio`、`quality`、`duration`，以及由后端按机器配置托管的 `speed`、`weight_profile`（自定义档位另有 `custom_steps`）。全部 H3 工作流另有 `refine_enabled` / `refine_quality`，且不再向界面或标准化结果暴露 `upscale_after`（旧客户端传入会被忽略）。比例接受任意有限正数的 `宽:高` 格式；分辨率由注册表提供可用尺寸档位并映射到内部 `megapixels`。`speed` 为语义预设：`fast`（4 步加速）、`balanced`（8 步加速，默认）、`quality`（20 步、关闭加速 LoRA）、`custom`（1–40 步）。`weight_profile` 为 `full`（默认，约 32 GB 全量 INT8，可挂加速 LoRA）或 `pruned`（约 20 GB 精简 INT8，强制关闭加速 LoRA，步数仍由 `speed` 决定）。**2026-11-02 起** `speed` / `weight_profile` / `custom_steps` 均为 internal，表单不再展示；客户端未显式提交时由后端按 ComfyUI `/system_stats` 的机器内存自动托管（≥40 GiB 内存 → 完整权重 + 默认档位，不足 → 精简权重 + quality 档，读不到内存 → 历史默认），显式提交的值仍优先。开启 `refine_enabled` 后，一采固定 0.4 MP，二采目标 `refine_quality` 取 `1.0` / `2.0`；一采步数、LoRA、unet、采样器与 Sage 由平台按工作流族锁定（官方 H3 精简权重 8 步 FL2V LoRA；LightX2V 完整权重 4 步，低内存机器自动换精简权重 20 步；八步双加速完整权重 8 步，低内存机器自动换精简权重 20 步；Director 加速精简权重 20 步；T8 完整权重 8 步并改用 Director 管线，低内存机器自动换精简权重 20 步）。`quality`、`speed`、`weight_profile`（及 T8 `custom_steps`）在二采开启时隐藏，运行参数快照回写实际生效的一采值与二采目标。导演台2 的清晰度放大统一收敛为「智能超清」：它复放该镜头已留存的一采生成图并挂上二采节点，`refine_upscale_method`（`auto` / `rtx` / `h3_latent`）是 internal 选项，由平台按注册表映射到 `MiniMaxH3DirectorRefine.upscale_method`，界面不展示也不接受请求侧覆盖。旧的独立 RTX 2x 超分不再是默认链路，也不再由 H3 创建选项自动触发。界面按当前比例显示实际输出尺寸，尺寸会按 32 的倍数计算并保持模型画布上限，时长为 2–15 秒，帧数按 H3 的 24fps、17n+5 时间网格对齐。

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
- 当前基线：`frontend/src/main.tsx` 使用 `BrowserRouter`。`frontend/src/paths.ts` 集中声明路径；`frontend/src/router.tsx` 声明 `<Routes>`。`Root.tsx` 仍用 `/api/auth/status` 做闸门（不引入 router loader）：`setup_required` → `/setup`，未登录 → `/login`（记下原路径），`must_change_password` → `/password`，员工访问 `/admin/*` → `/generate/video`。`/` 与未知路径在已登录时去 `/generate/video`。管理设置抽出为 `AdminSettings`，Tab 受控于 `useParams().tab` 并 `navigate`。创作台 `App` 作为已登录壳挂在生成/导演/资产路径下，避免这些路径互切时卸载；进入 `/admin/:tab` 仍卸载 `App`。登出 `queryClient.clear()` 后硬跳 `/login`。FastAPI `GET /{path:path}` 回退 `index.html`（无构建产物时 404），`/assets/{file}` 提供打包静态资源，精确路径 `/assets` 仍回退 SPA。无需改 Nginx。（2026-11-02 更新：该兜底路由已改为先直出 dist 根下的 `public/` 静态文件，再回退 `index.html`，见文末同日章节。）
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

## 2026-08-30 导演工程一致性与持久化操作基线

- 原因：原实现让用户创作内容与生成执行状态共享整份 Recipe 覆盖写入，无法正确处理生成期间编辑、跨窗口保存和长 LLM 请求；旧 Take/旧 job 状态还会影响新提交、串播和合成判定。
- 写入模型：`director_projects.revision` 在任何创作或执行更新时递增；`content_revision` 只在创作更新时递增。客户端创作保存提交 `expected_content_revision`，服务端在同一 SQLite 短事务中读取最新记录、校验版本并调用 `merge_recipe_creative()`；不匹配返回 `409 DIRECTOR_CONTENT_CONFLICT`，响应携带 `current_revision` 与 `current_project`。服务端进度通过 `persist_recipe_execution()` 重新读取最新 payload，只合并白名单执行字段，因此不会与用户输入争用 `content_revision`。
- 字段所有权：创作侧拥有工程元数据、剧本/画风、场景镜头顺序、标题/描述/提示词/对白/时长、角色与地点引用、首尾帧意图和 `approvedTakeId`。执行侧拥有 Agent 状态、`jobId/status/progress/error/compiledPrompt`、定妆/静帧/TTS/视频 URL 与路径、mux 状态及 Take 的执行快照。Take 集合按稳定 key 追加合并；批准 Take 是持久化创作决策，活动预览 Take 是前端局部状态。业务入口禁止再直接用旧 Recipe 整体覆盖当前 Recipe。
- Take 状态规则：当前 `shot.jobId` 是最新提交的唯一执行状态源，批准的旧 Take 不参与当前任务轮询。当前任务失败/中断/取消且存在旧可用 Take 时，镜头恢复为可合成状态但保留最新 `error` 和 job ID供重试/诊断；预览和 mux 按“有效批准 Take，否则最近可用 Take”选择。没有旧可用媒体时才保留失败状态。
- LLM 错误边界：流式读取把原生 `Timeout` 与 `ConnectionError` 中包装的超时统一转换为 `LlmTemporaryError`。`run_agent` 先写 `agentStatus=failed` 再重新抛出 `LlmError`；HTTP 层统一返回 502。仅本地 JSON 解析/内容修复保留降级，传输与供应商错误不得伪装成成功 200。
- 长操作：`director_operations` 持久化 `plan_pipeline` 与 `shot_render_prepare` 的 `request_json/result_json/status/progress/error/cancel_requested/created_at/updated_at`。`POST /api/director/recipes/{project_id}/operations` 返回 202，`GET /api/director/operations/{operation_id}` 查询，`POST /api/director/operations/{operation_id}/cancel` 请求取消。进程重启时遗留 queued/running 操作统一标记 `interrupted`，不自动重放 LLM；操作准备出的 ComfyUI job 继续复用原 JobStore/worker。每个工程同一时间只允许一个活动导演操作。旧同步 `/api/director/recipes/run` 与 `/api/director/recipes/{project_id}/render-shots` 保留一个版本并标记 deprecated。
- 前端状态边界：自动保存先 flush 待保存内容，再创建操作；工程轮询只调用 `mergeRecipeExecutionState()` 合并执行字段。409 时停止自动保存，`director-project-controller.ts` 驱动 Ant Design Modal 的“加载云端/明确覆盖”。`director-operation-controller.ts` 负责活动状态、恢复 key、目标镜头过滤和失败 Agent 判定。Recipe 类型按模型、readiness、时间轴、执行状态拆分，`types.ts` 暂时 re-export。
- 时间轴坐标：`recipeShotLayout()` 始终对完整镜头序列累计真实 `startSec/endSec`；可播列表只过滤媒体，不重新累计。播放器在缺片区间跳到下一可播镜头的真实开始时间。轨道 clip 的 `left=startSec×pps`、`width=durationSec×pps`；最小 pps 为 `max(24, ceil(72/minDurationSec))`（上限 120），确保最短片段不小于 72 px。删除镜头后通过 controller 同步校正勾选和当前选中 ID。
- 数据库迁移：首次打开既有 SQLite 前创建 `<数据库文件>.pre-director-concurrency-v2.bak`，再增加 `revision`、`content_revision` 和 `director_operations`。迁移不改 jobs、工作流协议或媒体路径。回滚 schema 前必须停止服务、另存当前库，再恢复该备份；恢复备份会放弃迁移后的工程与操作变更。
- 测试门禁：前端契约改为 Vitest `.test.ts`，生产入口无断言副作用；`pnpm --dir frontend build` 先跑测试再执行 `tsc -b` / Vite。后端覆盖超时/502/失败持久化、原子并发编辑、Take 追加/回退、迁移/409/重启中断；前端覆盖执行合并、操作/工程控制器、完整时间轴与最小缩放。OpenAPI 全量测试包含所有路径参数说明。
- 受影响文件：`backend/app/{llm_client,director_agents,director_jobs,director_project_service,director_takes,director_operations,storage,models,main,api_documentation}.py`，`frontend/src/director/DirectorRecipeStudio.tsx`、`director-api.ts`、两个 controller、`recipe-{model,readiness,timeline,execution}.ts`、时间轴/Inspector 组件、Vitest 配置与测试，以及三份主文档。
- 兼容性：第一阶段不迁移数据库，超时的错误成功 200 改为规范 502。第二阶段 schema、响应字段和 API 均为增量；旧客户端可暂时不传内容版本。未修改 `/api/modes` 注册表、ComfyUI graph、任何既有节点 ID、模型路径、工作台 7865 或 ComfyUI 8188。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend test`、`pnpm --dir frontend build`；桌面 1440×900 与手机 390×844 验证生成期间编辑、异常提示、缺片跳播、时间轴几何、删除选择、冲突 Modal 与响应式布局。
- 回滚方式：第一阶段恢复应用文件即可。第二阶段先停服务并保留当前库；需要完全回退时用 `.pre-director-concurrency-v2.bak` 替换数据库后启动旧代码。历史媒体、工作流 JSON 和 ComfyUI 节点不需要回滚。

## 2026-08-30 导演台时间轴移植 OpenCut classic 交互内核

- 原因：旧轨道由 React 事件直接修改 Recipe，缺少独立交互 Session、预览/提交边界和可拖播放头；高频 pointer/timeupdate 更新会扩大到导演台状态与自动保存。
- 架构基线：`frontend/src/director/opencut-timeline/` 固定映射 OpenCut classic commit `cf5e79e919144200294fb9fed22a222592a0aeea`（MIT，许可证随目录保留）。控制器层移植 Playhead、Resize、ElementInteraction、Zoom 与 edge-auto-scroll；`director-timeline-engine.ts` 适配上游 media tick/pixel math 到 24fps `RecipeShot` 连续主轨；React 组件只订阅控制器 view 并在 gesture commit 时写 Recipe。
- 状态边界：拖动采用 `idle/pending/dragging` 或 `idle/active` Session；5px 后才认定换序；resize draft 存在控制器中，mouseup 才把 2–15 秒整数写回；playhead scrub 逐帧 preview、mouseup commit；播放热路径由 `requestVideoFrameCallback` 直接写两个 playhead DOM transform，`timeupdate` 仅负责低频业务状态与跨镜头串播。
- 交互基线：镜头换序、跨场景插入、边界/播放头吸附、Shift 绕过吸附、Ctrl/Command+滚轮播放头锚定缩放、拖动边缘自动滚动、空白 scrub、Shift 框选、空格/中键平移。Ruler 与轨道共享 `scrollLeft`，Recipe 仍是唯一持久化事实源。
- 受影响文件：`frontend/src/director/opencut-timeline/*`、`director-timeline-engine.ts`、`types.ts`、`DirectorRecipeStudio.tsx`、三个时间轴组件、时间轴测试、`index.css` 和三份主文档。
- 兼容性：无后端、API、SQLite、Recipe schema、ComfyUI 工作流或端口变化；旧工程直接使用。未移植 OpenCut 的任意多轨、组、transition 与 WASM 媒体模型，因为导演 Recipe 当前只有一条连续镜头主轨。
- 验证命令：`pnpm --dir frontend test`、`pnpm --dir frontend build`、`python -m unittest backend.tests.test_director`；桌面 1440×900 和手机 390×844 浏览器回归。
- 回滚方式：恢复上述前端文件和三份文档并重新构建；数据库、Recipe、媒体和 ComfyUI 无需回滚。

## 2026-08-30 导演台播放器五键运输层

- 原因：时间轴已采用 OpenCut 控制器，但预览播放器仍暴露浏览器原生 controls，无法按工程 fps 前后逐帧，也缺少首尾跳转与专业时间码。
- 当前基线：`PlayerTransport.tsx` 复刻 `S07K/OpenCut` commit `e9c6cc06b549d7fa857bb8f43f02c47a39368e33` 的 `PreviewPanel.tsx` 五键布局；`opencut-timeline/transport.ts` 适配其 `timeline-engine/time.ts` 与 `playback-engine/transport.ts` 的整数帧 clamp、step、结尾回放和 `HH:MM:SS:FF` 格式化。具体上游文件映射见 `UPSTREAM.md`。
- 状态边界：Recipe 秒数仍是持久化事实源，运输层只在交互边界以 `recipe.fps` 转换整数帧。暂停逐帧会同步当前 video source offset；播放从当前帧继续，若位于结尾则回到开头；缺片区会前进到下一条可播放镜头而不压缩原时间轴空档。视频帧回调同时直接刷新时间码和播放头 DOM。
- 交互基线：五键、Home/End、左右键、Space；Shift+左右键为 10 帧。SAFE 是局部显示状态，不写 Recipe。浏览器原生 controls 已移除，避免与统一运输层重复。
- 受影响文件：`DirectorTimelineView.tsx`、`PlayerTransport.tsx`、`opencut-timeline/transport.ts`、时间轴测试、`index.css` 和三份主文档。
- 兼容性：无后端、API、SQLite、Recipe schema、ComfyUI 工作流、节点或端口变化。
- 验证命令：`pnpm --dir frontend test`、`pnpm --dir frontend build`、`python -m unittest backend.tests.test_director`；桌面与移动端浏览器回归。
- 回滚方式：恢复上述前端文件和文档并重新构建；无需处理持久化数据或媒体。

## 2026-08-30 全站双主题状态基线

- 原因：浅色工作台、导演台固定色与 Ant Design 弹层此前没有统一的主题事实源；局部暗色会产生页面、门户弹层和刷新首帧不一致。
- 状态流：`frontend/index.html` 在应用启动前校验 `localStorage['zly-ai-video-studio.theme']` 并设置 `html[data-theme]`、`color-scheme` 与 `theme-color`；React 挂载后 `ThemeProvider.tsx` 接管 `ThemeMode`，向后代暴露读取/切换接口，同时选择 `theme.ts` 中的 Ant Design `defaultAlgorithm` 或 `darkAlgorithm`。`ConfigProvider.config({ holderRender })` 使静态 `message`、`Modal` 等门户复用当前配置，`index.css` 的 `--studio-*` 变量负责非 Ant Design 和旧页面适配。
- 持久化边界：唯一键为 `zly-ai-video-studio.theme`，合法值仅 `light`、`dark`；首次访问、非法值和读取异常均回退 `light`。偏好只属于浏览器，不进入 React 业务任务状态，不写后端或用户账号，也不监听系统主题。
- 覆盖边界：根级状态覆盖登录/初始化/密码状态页、图片与视频创作、素材库、导演首页/项目库/批量台/方案台、管理员设置及传送弹层。导演台隐藏全局头部时自行复用同一 `ThemeToggle`，不创建第二份状态。
- 受影响文件：`frontend/index.html`、`frontend/src/theme.ts`、`ThemeProvider.tsx`、`components/ThemeToggle.tsx`、`main.tsx`、`App.tsx`、登录、后台和导演台页面、`index.css`、`theme.test.ts`、产品/设计规范、`AGENTS.md` 与三份主文档。
- 兼容性：前端内部状态模型增加主题上下文和一个本地存储键；不改 HTTP API、SQLite、任务/Recipe schema、工作流注册表、ComfyUI graph、节点 ID、模型路径、媒体目录或 7865/8188 端口。删除偏好即可恢复默认浅色行为。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend test`、`pnpm --dir frontend build`；以 1440×900 和 390×844 验证双主题、持久化、登录、工作台、账户菜单、Ant Design Select、导演台与后台。
- 回滚方式：恢复上述前端主题相关文件和文档后重新构建前端，并可删除 `zly-ai-video-studio.theme`；无需迁移或回滚数据库、任务、Recipe、媒体与 ComfyUI 资产。

## 2026-09-01 分镜连续性提示词基线

- 当前流程：`storyboard` Agent 依次执行完整拆镜、对白/动作时长润色、连续性润色。剧本 Agent 与首次拆镜即注入 Seedance 风格 scene ledger；连续性润色以完整有序的 `scenes[].shots[]` 为输入，为相邻镜头生成 `continuityIn`、`continuityOut` 和 `transitionNote`；前两项是英文边界状态，后者是中文编辑说明。方法原文落在 `backend/app/shot_continuity_skill/`。
- 编译边界：`director_compiler.recipe_shot_as_timeline_shot()` 与前端 `compileRecipeShotPreview()` 均把边界状态编入本地时间轴从 `00:00` 开始的 H3 单镜正文。它们不改 H3 的 T2VA / I2VA / Ref2VA 外层结构。若用户启用 `usePreviousEndFrame`，现有 `apply_recipe_continuity()` 仍把上一镜尾帧（或静帧）作为下一镜首帧，形成实际 I2V 视觉锚点。
- 兼容与回滚：字段可选，`normalize_recipe_payload()` 对旧 Recipe 不填默认值，故不需要 SQLite 迁移。删除第三次 Agent pass、三个字段、`shot_continuity_skill/` 及边界文本拼接即可回滚；工作流协议、ComfyUI 节点 ID、模型路径、7865/8188 端口均未变更。

## 2026-09-01 Seedance 剧本全流程衔接润色

- 原因：仅靠拆镜后的第三次衔接 pass，剧本阶段与首次拆镜仍可能缺少可继承的开场/收束状态；Seedance 2.5 skill 的 scene ledger / start-end state / adjacent-cut QA 需要进入整条生成链。
- 当前基线：内置 `shot_continuity_skill`（改编自本地 Seedance 2.5 的 production-contract / prompt-patterns / narrative route）。`script` 按 scene ledger 写分场开场-节拍-收束；`storyboard` 首次拆镜即草拟 `continuityIn/Out`/`transitionNote`；时长 pass 后仍跑衔接润色，并做缺口提示。编译与可选尾帧 I2V 承接不变。不向 H3 发送 Seedance API 标签。
- 受影响文件：`backend/app/shot_continuity_skill/**`、`llm_minimax_skills.py`、`director_agents.py`、`backend/tests/test_director.py`，以及三份主文档。
- 兼容性：不改端口、SQLite schema、ComfyUI 节点、工作流协议或既有 Recipe 必填字段。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorRecipeModelTests.test_official_h3_prompt_writing_skill_is_vendored backend.tests.test_director.DirectorAgentPipelineTests.test_storyboard_runs_timing_and_continuity_passes backend.tests.test_director.DirectorAgentPipelineTests.test_script_agent_uses_scene_ledger_continuity_guidance backend.tests.test_director.DirectorCompilerTests -q`、`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述文件并移除 `shot_continuity_skill/`；历史工程无需迁移。

## 2026-09-02 任务列表避免远程 MySQL 全表拉取 LONGTEXT

- 原因：迁到远程 `ai-media` 后，管理员 `GET /api/jobs?user_id=all` 对 `jobs` 执行 `SELECT * ORDER BY pinned, created_at LIMIT 100`。没有匹配索引时 InnoDB 会先扫描全表并读出 `prompt` / `references_json` 等 LONGTEXT，再丢掉未入选行，列表接口会卡到数十秒。
- 当前基线：先只查 `id` 再按 ID 回表组装任务与轮次；启动时补 `idx_jobs_pinned_created`、`idx_jobs_owner_pinned_created`。列表 JSON 字段不变，默认仍最多 100 条。
- 受影响文件：`backend/app/storage.py`、`backend/app/db.py`、`sql/001_init_mysql.sql`、`backend/tests/test_core.py` 与三份主文档。
- 兼容性：不改 `GET /api/jobs` 查询参数、响应模型和员工隔离；不改 ComfyUI 节点或端口。已有库启动时自动建索引。
- 验证命令：`python -m unittest backend.tests.test_core.StoreTests.test_jobs_are_filtered_by_owner_and_delivery_is_recorded backend.tests.test_ai_studio.JobEndpointTests.test_admin_can_filter_jobs_by_user_id_and_employee_cannot`。
- 回滚方式：恢复上述文件并重启工作台；可选 `DROP INDEX idx_jobs_pinned_created ON jobs`、`DROP INDEX idx_jobs_owner_pinned_created ON jobs`。

## 2026-09-03 导演台提示词润色开关

- 原因：定妆资产已经固定时，手动生成视频应允许跳过云端 H3 提示词润色。
- API：`DirectorOperationCreateRequest` 与兼容的 `DirectorRenderShotsRequest` 新增 `polish_prompt`，默认 `true`。导演操作服务和旧渲染接口仅在该值为真且 LLM 可用时传入 `polish_director_h3_prompt`；为假时直接将现有镜头提示词交给 `render_recipe_shots`，其余校验、参考图编译、任务入队和进度持久化不变。
- 前端：`DirectorRecipeStudio` 在输出设置中使用 Ant Design `Switch`，按项目将偏好保存到浏览器 `localStorage`（默认开启，静帧模式禁用），并把值提交到导演操作请求。
- 兼容性：仅增加可选请求字段和前端本地偏好，无数据库迁移、Recipe 必填字段、工作流协议、ComfyUI 节点或端口变化。
- 验证：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚：恢复相关后端、前端和文档文件并重新构建；无需回滚已有项目、任务或媒体。

## 2026-09-03 导演台镜头进度条恢复实时刷新

- 原因：迁库后为减少远程 MySQL 压力，`GET /api/jobs` 轮询被限制为仅在「生成」工作区启用；导演台分镜/定妆进度条依赖同一 `allJobs` 列表，停在导演台时进度冻结。
- 当前基线：`App.tsx` 在 `generate` 与 `director` 工作区启用任务列表轮询（资产页、导台2 仍关闭）。有排队/运行/中断任务时约 4 秒刷新，空闲约 15 秒。（2026-10-25 更新：资产页改为仅拉取一次快照，用于冷启动与删除后刷新；仍不周期轮询。导台2 仍不请求列表。系统健康检查由 8 秒放宽到 30 秒，GRS 余额仅在生成页图片模式查询。）`DirectorRecipeStudio` 在镜头出片或静帧进行中也会 1.5 秒轮询工程，打开工程时后端 `sync_recipe_asset_images` 继续把 `jobs.progress` 写回 Recipe。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/director/DirectorRecipeStudio.tsx` 与三份主文档。
- 兼容性：不改 `GET /api/jobs` 契约、数据库、工作流或 ComfyUI；仅恢复导演台侧轮询。
- 验证命令：`pnpm --dir frontend exec tsc -b --pretty false`、`pnpm --dir frontend build`；导演台出片时确认进度条与按钮百分比随 `jobs.progress` 递增。
- 回滚方式：恢复上述前端文件并重新构建。

## 2026-09-03 共享数据库视频任务本地素材保护

- 原因：本地工作站和服务器使用同一 MySQL，但 `data/uploads` 并非共享文件系统；旧 worker 会在任意实例恢复所有排队 H3 任务，使非创建端因绝对参考图不存在而在 ComfyUI 提交前失败。
- 架构基线：`JobWorker.references_available_locally()` 是视频任务恢复与执行的本地性门禁。绝对参考图只要有一项无法在当前主机读取，该实例就跳过任务且不变更数据库状态；素材所在工作站仍按既有队列接管。`PureWindowsPath` 用于让 Linux 实例识别 Windows 盘符路径。
- 受影响文件：`backend/app/worker.py`、`backend/tests/test_core.py` 与三份主文档。
- 兼容性：不新增数据库字段，不改变 API、任务 JSON、工作流 graph、ComfyUI 节点或端口；无参考图 T2V 与相对路径旧任务行为保持不变。
- 验证命令：`python -m unittest backend.tests.test_core.WorkerTests`、`pnpm --dir frontend build`。
- 回滚方式：移除恢复/执行前的本地参考图门禁并恢复文档；无需数据库回滚。

## 2026-09-08 分镜连续性窗口与 QA 修复

- 原因：连续性润色沿用五镜头无重叠分块时，镜头 5 与镜头 6 会落在两个请求中，模型看不到跨块的动作、人物位置和道具状态，导致相邻镜头断裂。
- 当前基线：时长润色仍按原五镜头分块；连续性润色改用五镜头窗口并重叠一个上下文镜头（1–5、5–9、9–13）。每个请求携带全局 `shotNumber`、`contextShotNumbers` 和 `editableShotNumbers`，重叠镜头只读，不会覆盖已确认结果。连续性响应只允许写入 `promptText`、`continuityIn`、`continuityOut`、`transitionNote`、`soundscape` 和 `soundscapeEn`；缺镜头、重复编号、窗口外编号或无效 JSON 会整块丢弃并重试，仍失败则保留原内容并记录风险。
- QA 与对白：后端新增相邻镜头 `validate_continuity_pairs()`，检查边界字段、场景硬切标记、人物/道具/地点、天气/时间/光线、开场动作和转场说明，并把结构化结果写入可选 `Recipe.continuityQa`。对白字段统一去除 `<d>`、`[Chinese]` 和角色/情绪前缀，再同步 H3 `promptText` 的 `<d>` 标签；原始对白内容不翻译、不改写。高风险只在 Agent 状态中提示，不阻断流水线。
- 受影响文件：`backend/app/director_agents.py`、`backend/app/director_recipe.py`、`backend/app/llm_minimax_skills.py`、`backend/app/director_jobs.py`、`backend/tests/test_director.py`。
- 兼容性：不改 API 请求格式、数据库表、ComfyUI graph、节点 ID、模型路径或 7865/8188 端口；`continuityQa` 为可选字段，旧 Recipe 与旧客户端可继续读取。旧 Recipe 不自动重写，重新生成分镜时启用新逻辑。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend test`、`pnpm --dir frontend build`。完整后端发现测试还需按当前实例环境配置 ComfyUI 地址和 LLM provider。
- 回滚方式：恢复上述后端、测试和三份文档；无需迁移或回滚数据库、媒体和 ComfyUI 资产。

## 2026-09-08 分镜连续性阶段 2：因果动作修复

- 原因：阶段 1 的重叠连续性窗口和确定性 QA 能定位出镜状态与下一镜开场动作的断裂，但不能自动改善已经生成的镜头正文。
- 当前基线：`storyboard` Agent 在连续性 QA 后，对风险相邻镜头执行一次有界因果修复 pass。请求同时携带原剧本片段、风险原因、前后镜头的可视状态和资产绑定；修复器要求下一镜在 `00:00` 先呈现上一镜的触发/空间状态，再进入本镜动作。修复后重新运行 `validate_continuity_pairs()`，`continuityQa.repair` 保存尝试数、应用数、未完成错误和 `resplitRequired` 边界。
- 字段所有权：修复 pass 只能写 `promptText`、`continuityIn`、`continuityOut`、`transitionNote`、`soundscape`、`soundscapeEn`。对白、`durationSec`、`shotNumber`、镜头顺序、`characterBindings`、`locationId`、`propIds` 和 `camera` 仍属于锁定字段。响应必须覆盖已请求边界，重复、越界或缺失项整项不应用；`needs_resplit` 仅记录明确风险，不在后台擅自重编号。
- 兼容性：新增结果字段为可选 Recipe 数据，不改 HTTP 请求格式、数据库表、工作流注册表、ComfyUI graph、节点 ID、模型路径或 7865/8188 端口；旧 Recipe 无 `continuityQa.repair` 时照常读取。
- 受影响文件：`backend/app/director_agents.py`、`backend/app/director_recipe.py`、`backend/app/llm_minimax_skills.py`、`backend/tests/test_director.py`。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend test`、`pnpm --dir frontend build`；重点回归镜头 5→6 的因果开场、锁定字段不被覆盖和需要重拆的风险记录。
- 回滚方式：恢复上述后端、测试和文档文件；无需数据库、历史 Recipe、媒体或 ComfyUI 资产回滚。

## 2026-09-08 阶段3：剧本拆解模式

/api/llm/split-script 新增可选 script_mode（默认 literal，兼容旧客户端）；literal 保留原对白和事件顺序，creative 允许扩写并要求标记 AI-added。后端将模式传入 MiniMax H3 提示词，不改变数据库、ComfyUI 或端口。验证：python -m unittest backend.tests.test_director -q。回滚：移除字段并恢复默认提示词。

## 2026-09-08 局部连续性修复闭环

新增 `POST /api/llm/repair-continuity`。后端仅接收当前 Recipe 与相邻镜头号，调用连续性修复模型并原子应用连续性字段，随后重新执行 QA。前端桌面、移动端和时间线检查器统一调用该接口，并只合并连续性字段，保留本地对白、时长、相机、素材和生成状态。验证：`python -m unittest backend.tests.test_director -q`、`pnpm --dir frontend build`。回滚：移除接口调用并保留旧 QA 展示。

## 2026-09-08 H3 分辨率质量档位优先

旧任务或导演草稿可能保留内部 `megapixels=0.4`，但用户可见的 `quality` 已选择 `0.9`。`h3_dimensions()` 现在以质量档位为权威值，只有缺少可识别 `quality` 时才回退到 legacy MP；不改 API、数据库、节点 ID、模型路径或端口。验证：`python -m unittest backend.tests.test_core.WorkflowTests.test_h3_dimensions_prioritize_quality_over_stale_internal_megapixels -q`、`pnpm --dir frontend build`。回滚：恢复相关后端与测试文件。


## 2026-09-08 流式媒体请求卡死修复

- 原因：请求日志中间件回放请求体后无限返回空 `http.request`，流式响应监听断连时可能进入无让出的忙循环，阻塞同进程健康检查和其他请求。
- 当前基线：请求体仅回放一次，后续 `receive()` 委托原始 ASGI transport，保留真实等待与断连；上传期间断连不再派发残缺请求。
- 受影响文件：`backend/app/request_log.py`、`backend/tests/test_request_log.py` 和三份主文档。
- 兼容性：无 API、数据库、端口、工作流或媒体格式变更。需重建并更新服务器镜像，仅重启旧镜像不会修复。
- 验证命令：`python -m unittest backend.tests.test_request_log -v`、`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。部署后打开媒体预览并同时执行 `curl --max-time 5 http://127.0.0.1:18189/api/health`。
- 回滚方式：恢复上述代码并重建旧镜像；无需回滚数据库和数据卷，但旧版会恢复该忙循环风险。
## 2026-09-08 手动分镜结构化对白

为解决双人对白合并到单个语音标签的问题，RecipeShot 新增可选 dialogueLines（speaker/text），经 director_recipe.py 保存、director_compiler.py 和前端 types.ts/prompt-compiler.ts 编译为逐句独立标签；manual-import.ts 与 RecipeShotInspector.tsx 支持导入和编辑角色台词。角色编号在单镜内按首次出现顺序复用，角色名放在语音标签外。旧 dialogue 字符串保持兼容；旧数据丢失的角色信息需重新导入或编辑，不能自动恢复。

验证：pnpm --dir frontend build；python -m unittest backend.tests.test_structured_dialogue backend.tests.test_director -q。当前系统 Python 缺少 pymysql，导演测试有一项启动失败。回滚：恢复上述前后端文件并重新构建；无需数据库迁移。


## 2026-09-08 导演台八步双加速提交修复

导演台预览、终稿及批量生成按所选工作流注册表校正速度：旧工程或默认预览中的 fast 在八步双加速下回退到注册表默认 balanced，避免“生成速度不是有效选项”；支持的速度保持原值。涉及 backend/app/director_compiler.py、backend/app/director_jobs.py 与 backend/tests/test_director_workflow_speed.py。不改变 API、数据库或 ComfyUI graph 协议，旧工程无需迁移。

验证命令：python -m pytest backend/tests -q；pnpm --dir frontend build。回滚：撤销上述文件中本节对应的速度校正和测试改动，保留其他已有修改。

## 2026-09-08 导演台导入与润色预览纠正

修复 Markdown 时间码导入为默认 5 秒、声音遗漏和结构化对白重复；前后端编译保留画面描述。检查器区分当前编译预览与最近一次实际提交快照，明确词数按空白统计。开启润色而 LLM 不可用时返回错误，禁止静默跳过。受影响文件：manual-import.ts、prompt-compiler.ts、types.ts、RecipeShotInspector.tsx、director_compiler.py、director_operations.py、main.py。兼容性：不改数据库与工作流节点；旧工程不自动改写。验证：pnpm --dir frontend build；python -m unittest backend.tests.test_structured_dialogue backend.tests.test_director -q。回滚：仅撤销本次相关变更并重建前端，保留其他未提交改动；无需数据迁移。
## 2026-09-08 导演台五阶段流程重构

- 原因：阶段导航、创作视图和执行动作耦合，空态与失败态无法给出可执行下一步。
- 实现：新增 `recipe-flow.ts` 派生阶段摘要、缺项和镜头运行/采用状态；`DirectorStageNav` 使用五阶段分组；保存队列和操作轮询提取为 `useDirectorProjectSession`、`useDirectorOperation`；工作流 payload 增加兼容的 `director_controls` 声明；导出增加排除镜头定位；手机参数进入 Drawer。
- 兼容性：保留现有 stage、旧别名、`view=plan|timeline`、Recipe/Take/节点协议和工程 ID；仅改变导航不触发生成/导出的用户行为。
- 验证：`pnpm --dir frontend build`（40 tests）；`python output/playwright/run-backend-check.py`（SQLite 隔离，379 passed / 6 个既有测试失败）；`node output/playwright/director-flow-check.cjs`（桌面/手机、浅色/暗色、导航和保存失败路径）。
- 回滚：恢复本次前端组件、纯函数、注册表 `director_controls` 和三份文档；无需数据库迁移。

## 2026-09-11 导演台剧本生成流式展示（SSE）

- 原因：剧本阶段（片名/一句话梗概/完整故事）一直是可编辑输入框，用户误以为是输入区，实际是 script agent 生成后一次性回填；生成过程只有 1.2 秒轮询状态文案，看不到内容逐步产出。
- 当前基线：`backend/app/director_stream.py` 提供 `ScriptFieldStreamTracker`（把 script agent `on_chunk` 的累积原文容错解析为 title/summary/fullStory 字段级增量，处理 `<think>` 块、``` 围栏、跨块转义与模型改写重置）和 `DirectorOperationEventBus`（按操作缓冲带递增 seq 的事件，`call_soon_threadsafe` 支持工作线程发射，订阅可重放 `since` 之后的历史并实时推送，终态后关闭并清理，最多缓冲 128 个操作）。`DirectorOperationService` 在生命周期发 `status`/`agent`/终态事件；`run_director_recipe`/`run_recipe_pipeline`/`run_agent` 新增 `on_stream` 回调，script agent 分支接入 tracker。新端点 `GET /api/director/operations/{operation_id}/events`（SSE，15 秒心跳；事件 `status`/`agent`/`script_delta`/`done`/`cancelled`/`error`，`id:` 为事件序号，查询参数 `since` 控制重放起点）与既有轮询接口同权限；断流由前端携带 `since` 重连，既有 1.2 秒轮询保留为兜底。
- 前端：`director-operation-stream.ts` 手写 SSE 解析（fetch + ReadableStream、AbortController、最多 4 次断线重连）；`DirectorScriptStreamPanel` 生成中视图（脉动状态栏 + 9 Agent 任务行 + 打字机文档 + 骨架屏 + 耗时 + 取消，正文自动跟随滚动、上滚暂停）；`DirectorScriptDocument` 成稿只读文档（「编辑剧本」显式切回表单、「进入分镜设计」CTA）；`DirectorRecipeStudio` 剧本阶段四态 empty/streaming/document/edit，完整方案生成成功后停留在剧本页，不再自动跳转分镜。
- 受影响文件：`backend/app/{director_stream,director_operations,director_agents,llm_provider,main}.py`、`backend/tests/test_director_stream.py`、`frontend/src/director/{director-operation-stream.ts,DirectorRecipeStudio.tsx,action-copy.ts,guided-flow.css}`、`frontend/src/director/components/{DirectorScriptStreamPanel,DirectorScriptDocument}.tsx` 和三份主文档。
- 兼容性：不改既有 operation 创建/轮询/取消 API、Agent 提示词与 JSON 契约、数据库 schema、ComfyUI 节点或端口。SSE 为纯增量通道，事件仅在内存短期缓冲，服务重启或缓冲被逐出后前端自动回退轮询；旧客户端不受影响。
- 验证命令：`python -m pytest backend/tests/test_director_stream.py backend/tests/test_director.py backend/tests/test_director_concurrency.py backend/tests/test_director_controls.py -q`；`pnpm --dir frontend build`。浏览器验证空态/流式/成稿/编辑/取消/失败/刷新恢复七个场景与双主题、移动端布局。
- 回滚方式：还原本次提交即可回到输入框 + 纯轮询的现状，无数据库迁移。

## 2026-09-11 导演台生成过程全面流式化与创意澄清

- 原因：中间区域只流式展示剧本，script 之后的 Agent 运行时画面静止；研究与脚本两步缺少计划模式式的方向引导，用户无法影响剧情走向。
- 当前基线：`director_stream.py` 的 `ScriptFieldStreamTracker` 泛化为 `AgentStreamTracker`（声明式 spec：`scalar_fields` + `AgentArraySpec(key, display_fields, extractor)`）。新事件：`agent_delta`（agent/field/index/delta/reset，index=null 为标量字段，否则为数组条目的展示字段流式）与 `agent_item`（数组条目闭合解析后整体发出，finish 时以权威解析值覆盖重发，上限 200 条）。多调用 Agent（storyboard 每场景片段、重拆重试）在每次 LLM 调用前 `begin_call()`，条目序号跨调用连续。spec 注册表覆盖 research/script/characters（含 props）/locations/storyboard（scenes+嵌套 shots）/voice/music/clarify；art_style（仅 id）与 media（无 LLM）不接流式。`run_agent`/`run_recipe_pipeline` 新增 `clarifications` 参数，script 分支用 `_clarified_goal_text()` 把问答以「创作方向确认」附加到 user content（goal 本身不改动，避免污染标题回退等逻辑）。
- 创意澄清：新 operation kind `plan_clarify`（`models.py` 的 `DirectorOperationCreateRequest.kind` 增量、新增 `clarifications: list[DirectorClarificationItem]`）。`llm_minimax_skills.build_clarify_questions_prompt()` 要求 2-4 个剧情走向问题（每题 3-4 个选项含 recommended、allowCustom）；`LlmProviderService.run_director_clarify()` 流式生成问题并经 `parse_json_object` 归一化；`DirectorOperationService._run_clarify` 通过事件总线推送问题文本流，questions 存入 operation result 并由 done 事件携带；`_run_plan` 把 clarifications 透传 `run_director_recipe`。创建接口对 plan_clarify 校验 LLM 可用性与 goal 必填。
- 前端：`DirectorScriptStreamPanel` 重构为聊天记录式生成视图——每个 Agent 一个段落块（运行中展开、完成折叠为一行摘要、点击回看），块内按 Agent 渲染：剧本手稿、画风揭晓卡、角色/道具/场景卡片（agent_item 逐张出现 + 活动卡片描述打字机）、镜头行（跨场景全局镜号）、声线分配行、配乐方案文本；顶部 Task Rows 与创作方向 chips 保留。澄清流程：点「生成创作方案」创建 plan_clarify → 问题文本流式 → Approval Card 逐题作答（选项 chip 单选 / 自定义输入 / 跳过这题 / 跳过全部）→ 答完自动等待前一操作落定后创建 plan_pipeline（携带 clarifications）。未答问题持久化在 `director-clarify:{projectId}`，刷新恢复后重新展示。
- 受影响文件：`backend/app/{director_stream,director_agents,llm_minimax_skills,models,llm_provider,director_operations,main}.py`、`backend/tests/test_director_stream.py`、`frontend/src/director/{director-operation-stream.ts,DirectorRecipeStudio.tsx,director-api.ts,action-copy.ts,guided-flow.css}`、`frontend/src/director/components/DirectorScriptStreamPanel.tsx` 和三份主文档。
- 兼容性：`script_delta` 事件被 `agent_delta`（agent=script）取代，SSE 事件协议随本次前后端同版本变更；既有 operation 创建/轮询/取消 API、数据库 schema、Agent JSON 契约与 ComfyUI 协议不变（kind 与 clarifications 为增量字段）。旧客户端轮询路径不受影响。
- 验证命令：`python -m pytest backend/tests/test_director_stream.py backend/tests/test_director.py backend/tests/test_director_concurrency.py backend/tests/test_director_controls.py -q`；`pnpm --dir frontend build`。人工回归：提问→回答/跳过→生成、聊天记录滚动与折叠、取消/失败、刷新恢复、双主题与移动端。
- 回滚方式：还原本次提交即回到「仅剧本流式」现状；无数据库迁移。

## 2026-09-11 导演台 Prompt Bar 对话式创作室布局

- 原因：创意简报输入位于左上角侧栏，与内容展示区（中部）割裂；生成/取消按钮在顶栏、阶段操作行、底栏三处重复，界面组织仍是「表单 + 内容」而非对话式创作。
- 当前基线：新组件 `frontend/src/director/components/DirectorPromptBar.tsx`——对话式输入条（TextArea 自适应 + 圆形发送按钮），Enter 发送、Shift+Enter 换行、输入法组合键保护；三态 idle（可编辑+发送）/ streaming（锁定为状态条：脉动指示 + 状态文案 + 取消）/ clarify（禁用 + 「回答上方的问题以继续」）。剧本阶段改为对话式创作室 `.director-script-room`：内容区从上到下为用户创意气泡（`brief` prop，取本次操作 request.goal 快照）→ 澄清问题卡 → 生成记录块 → 成稿文档，底部 sticky Prompt Bar（`.director-recipe-main` 为滚动列，`min-height:100%` 保证空态时输入条也贴底）。空态改为 hero 欢迎区 + 3 个示例创意 chips（点击填入输入框）。
- 入口收敛：剧本阶段移除顶栏「生成创作方案」（Prompt Bar 承担生成/取消，`scriptRoomActive` 控制）、移除 rail 内简报卡与移动端简报卡、隐藏移动端底栏（Prompt Bar fixed 于安全区上方，z-index 85）；画风阶段保留顶栏生成按钮；其他阶段 mobilePrimary/底栏逻辑不变。批量短视频页主题输入从「主题与参数」卡迁移到底部常驻 Prompt Bar（卡片改名「生成参数」，shell 改纵向 flex + `.director-batch-scroll` 滚动），顶栏「裂变并生成」与移动底栏移除。
- 受影响文件：`frontend/src/director/{DirectorRecipeStudio.tsx,DirectorBatchStudio.tsx,action-copy.ts,guided-flow.css}`、`frontend/src/director/components/{DirectorPromptBar.tsx,DirectorScriptStreamPanel.tsx}` 和三份主文档。
- 兼容性：纯前端布局调整；`goal`/`payload.theme` 的 state 绑定与自动保存逻辑不变，不改 API、后端协议、数据库或 ComfyUI。`SCRIPT_EMPTY_HINT` 等文案同步更新，删除 `.director-script-empty` 样式（index.css 中 `.director-brief-card` 系列成为死样式，留待下次清理）。
- 验证命令：`pnpm --dir frontend build`；`python -m pytest backend/tests/test_director_stream.py backend/tests/test_director.py -q`（确认无后端回归）。人工回归：空态 hero→示例填入→发送→澄清→生成记录→成稿→改简报重新生成；生成中取消；画风阶段顶栏生成；批量页新输入流；桌面+移动端、双主题。
- 回滚方式：还原本次提交即恢复侧栏简报卡 + 顶栏按钮布局。

## 2026-09-11 导演台 Agent 对话界面重构（双模式）

- 原因：对话创作界面上残留旧工作台元素（剧本/画风 Tabs、阶段头「继续」按钮、顶栏任务活动/取消按钮、Task Rows 为水平单行不符合 beautifului 形态），且分镜文字没有逐字流式打印——根因是活跃镜头（JSON 未闭合）只有 agent_delta 事件而无渲染载体，镜头行要等 agent_item 整行出现。
- 当前基线：双模式布局——`script` 阶段为全屏 Agent 对话创作室（`.director-recipe-layout.is-chat` 单列：隐藏左侧导航、剧本/画风 Tabs 与 DirectorTaskHeader；顶栏收敛为返回/工程名/主题/串播/更多，「任务活动」移入更多菜单，取消生成由 Prompt Bar 状态条承担）；其他阶段（分镜/素材/镜头/声音/成片）保留现有编辑工作台与左侧导航，侧栏「剧本」即回对话。对话流新结构：用户气泡 → 垂直任务面板（新组件 `DirectorTaskRows`：每行状态图标+任务名+实时消息，头部总进度条+百分比+耗时，运行中常驻、终态折叠为一行可展开）→ 澄清卡 → 产出块卡片化（圆角卡+Agent 图标，运行中主色描边）→ 分镜块活跃镜头逐字打印（`activeIndex` 跟踪各 field 最新 delta 序号，活跃行以打字机 shown 值渲染+光标，title 未到时骨架行；活跃场景标题同理）→ 画风卡（`更换画风` 打开 Modal 内嵌现有 ArtStyleCatalogPicker，选完提示可重新生成）→ 完成卡（新组件 `DirectorCompletionCard`：成功/部分失败状态 + 下一步 chips「进入分镜设计」「重新生成」，由完成 effect 写入 `lastPlanCompletion` state 渲染在成稿视图上方）。
- 受影响文件：`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/components/{DirectorTaskRows,DirectorCompletionCard,DirectorScriptStreamPanel}.tsx`、`frontend/src/director/{action-copy.ts,guided-flow.css}` 和三份主文档。
- 兼容性：纯前端；不改 API、阶段 URL 协议（`?stage=`）、工作台阶段行为或后端（分镜 delta 事件已存在，本次为渲染修复）。删除水平任务 chips（`.director-agent-tasks`）与 `.director-style-reveal` 样式。
- 验证命令：`pnpm --dir frontend build`；`python -m pytest backend/tests/test_director_stream.py backend/tests/test_director.py -q`（后端未改动，确认无回归）。人工回归：对话全流程（气泡→任务面板→澄清→分镜逐字→画风弹层→完成卡→进入分镜设计→侧栏点剧本回对话）、生成中取消/失败、刷新恢复、桌面+移动端双主题。
- 回滚方式：还原本次提交即恢复 Tabs+侧栏+水平任务行布局。

## 2026-09-12 导演台对话界面 beautifului 官方皮肤校准

- 原因：此前皮肤按官网 CSS 推测实现，视觉与 beautifului.dev 有差距；用户找到官方源码仓库 `TurboKach/ai-native-react-components`（beautifului.dev 同源，MIT），提供 19 个组件的精确实现与完整双主题 token。
- 使用方式：不安装（shadcn CLI 需 Tailwind v4 + shadcn 项目）、不整文件复制（组件为自驱动 demo 动画的视觉参考，且工作台规范要求 antd 统一）——将其源码与 `app/globals.css` token 块作为像素级样式规范，校准导演台对话创作室的皮肤。
- 当前基线：`.director-recipe-layout.is-chat` 作用域内的 `--director-*` token 层替换为官方精确值（accent #0285ff/暗 #3d9aff、green/red/orange 及 tint 系、三层 `shadow-card`/`shadow-btn`/`shadow-raised` 阴影）。`DirectorTaskRows` 重写为官方 Capsules 语法：SVG 圆环序号徽章（灰底环+旋转弧+中心序号）、实心绿圆勾/红圆叉状态徽章（pop-in 弹出）、行右侧 tint 状态胶囊（已完成绿/失败红）、每行独立白胶囊卡（44px 高、22px 圆角、运行中收窄 14px、hairline 阴影、hover inset、fade-up stagger 进场）。产出块/澄清卡/完成卡/示例创意卡统一 `shadow-card`+14px 圆角+fade-up 曲线；用户气泡改 accent 蓝底白字；Prompt Bar 用 `shadow-raised`、聚焦 accent 描边、发送键按压缩放 `scale(.94)`、提示行虚线上边；关键帧补齐官方 `fade-up/pop-in/stream-in/fade-in`（cubic-bezier(0.23,1,0.32,1)）。
- 受影响文件：`frontend/src/director/guided-flow.css`、`frontend/src/director/components/{DirectorTaskRows,DirectorScriptStreamPanel}.tsx`。
- 兼容性：皮肤仅作用于对话创作室（`is-chat` 作用域），工作台模式与全局 `--studio-*` 主题不变；MIT 许可仅参考样式值，不引入任何新依赖或复制组件源码。
- 验证命令：`pnpm --dir frontend build`。人工回归：对话创作室浅色/暗色双主题视觉、任务面板胶囊行、按压动效、移动端。
- 回滚方式：还原本次提交即恢复 `--studio-*` 皮肤。

## 2026-09-12 生成完成后对话记录常驻（历史回放）

- 原因：对话记录（任务面板、产出块）只存在于流式内存中，生成完成或刷新后剧本阶段退化为纯成稿文档视图，用户看不到 Task Rows 与生成过程——浏览器实测发现。
- 当前基线：`DirectorScriptStreamPanel` 新增 `historyMode`/`recipe` props。活动操作结束后以 `historyMode` 渲染：从已保存的 recipe payload 一次性重建全部产出块（剧本三字段、globalMusic/globalSoundscape 文本、角色/道具/场景卡、分镜镜头行、声线行）与任务面板（recipe.agentStatus），默认全部展开、可手动折叠；任务面板头部在历史模式隐藏耗时。空 recipe（工程查询未返回）不消费 seed 机会，等真实数据到达。完成状态 `lastPlanCompletion` 持久化到 `director-plan-completion:{projectId}`，刷新后完成卡恢复。成稿文档在历史回放下方常驻（运行中不显示）。历史头部显示「AI 导演创作记录」+ 完成图标，隐藏取消按钮与脉动点。分镜场景标题相邻去重、镜头描述两行截断（英文编译提示词属噪音）、道具芯片修复被 grid 拉伸的问题。
- 受影响文件：`frontend/src/director/components/{DirectorScriptStreamPanel,DirectorTaskRows}.tsx`、`frontend/src/director/{DirectorRecipeStudio.tsx,action-copy.ts,guided-flow.css}`。
- 兼容性：纯前端；不改 API 与数据。
- 验证：浏览器实测（登录工作台 → 血与恩情工程剧本阶段）：任务面板 9 行官方胶囊形态、角色/场景/道具卡、9 镜头行、画风卡、846 字手稿、完成卡、亮/暗双主题截图确认。
- 回滚方式：还原本次提交即恢复「完成后仅文档视图」。

## 2026-09-12 对话创作室布局重构（官方 chat 固定高度卡内滚动）

- 原因：剧本对话阶段使用页面级滚动 + sticky 输入条，输入框被页面滚动截断，需滚到底部才能看全；不符合官方 chat 的「整卡固定高度、消息区内部滚动、输入区常驻」布局。
- 当前基线：`is-chat` 作用域内 `.director-recipe-main` 改为纵向 flex 容器（`overflow: hidden`），`.director-script-room` 弹性填充，对话卡（`.director-script-stream`）`flex: 1; min-height: 0` 固定视口高度，**唯一滚动区为消息列表**（`.director-stream-body { flex: 1; min-height: 0; overflow-y: auto }`），Prompt Bar 静态常驻卡底（不再 sticky）。完成卡与成稿文档经新 `transcriptFooter` prop 渲染在消息流末尾。任务面板 `max-height: min(46%, 360px)` 内部滚动，历史回放默认折叠为一行摘要（运行中保持展开），避免挤压消息区。空态判定改为仅看 `script.fullStory`（工程创建时 title/summary 会写入工程名，不能作为「已有剧本」依据）。文案/图标/指示条配色统一改用 `--director-*` token。
- 受影响文件：`frontend/src/director/{DirectorRecipeStudio.tsx,guided-flow.css}`、`frontend/src/director/components/{DirectorScriptStreamPanel,DirectorPromptBar}.tsx`。
- 兼容性：纯前端布局与样式；移动端断点保持原行为（页面自然滚动 + fixed 输入条）。
- 验证：浏览器实测三个场景——已完成工程（无页面滚动、任务面板折叠/展开、消息区滚动到手稿与成稿文档）、生成中工程、空白工程（hero + 示例创意 + 输入框完整可见）；亮/暗双主题截图确认。
- 回滚方式：还原本次提交即恢复页面级滚动 + sticky 输入条布局。

## 2026-09-12 剧本 Beat 数量由澄清问答确认（beat_count）

- 原因：剧本 Agent 固定 800-1500 字导致短句创意也生成数十个 Beat，无法做短剧级控制。
- 当前基线：`plan_clarify` 返回「2-3 道剧情走向题 + 固定 `beat_count` 镜头数量题」（档位 8/16/30/50 硬编码于 `llm_minimax_skills.py`，`normalize_clarify_questions` 兜底）；`POST /api/director/recipes/{id}/operations` 的 `clarifications[]` 新增可选 `id` 字段。`plan_pipeline` 剧本 Agent 用 `_clarified_beat_target` 解析用户确认数量并经 `build_script_agent_prompt(target_beats=N)` 约束 Beat 总数（±2，钳制 3-120）；未确认时保持旧行为。
- 受影响文件：`backend/app/llm_minimax_skills.py`、`backend/app/llm_provider.py`、`backend/app/director_agents.py`、`backend/app/models.py`、`backend/tests/test_director_clarify.py`、`frontend/src/director/{director-api.ts,DirectorRecipeStudio.tsx,components/DirectorScriptStreamPanel.tsx}`。
- 兼容性：`id` 可选，旧请求/旧澄清记录不受影响。
- 验证命令：`python -m unittest backend.tests.test_director_clarify backend.tests.test_director -q`；`npm --prefix frontend run build`。
- 回滚方式：还原本次提交即恢复固定字数生成与纯方向澄清题。

## 2026-09-12 复刻台（shot_replication）：参考片拉片与 Wan VACE 深度控制转绘

- 原因：产品化"上传参考片 → 分镜反推提示词 + 深度视频 → 本地 VACE 复刻镜头"管线（对标 AniShort 一键转绘叙事，差异化在本地免费可换引擎）。预研确认整合包已具备全部底层资产：`vace-native-checkpoint/` 的 Wan2.1 VACE 1.3B diffusers 单文件 checkpoint（经硬链接归位 `models/diffusion_models/wan2.1_vace_1.3B.safetensors`，ComfyUI `model_detection` 识别 `vace_blocks` 键）、`models_t5_umt5-xxl-enc-bf16.pth`（原版命名 ComfyUI 0.30 不识别，改下载重打包版 `umt5_xxl_fp8_e4m3fn_scaled.safetensors` 6.74GB）、`wan_2.1_vae.safetensors`、核心 Depth Anything 3 节点 + `models/geometry_estimation/depth_anything_3_mono_large.safetensors`（1.34GB）、`toonflow_vace_multi_reference` 自定义节点（原生 `control_video` 输入）、VHS。实测：mp4 可经 `/upload/image` 落入 `input/`；DA3 视频深度 33 帧 10s 完成；VACE 复刻图（4 步 smoke）176s 出片。
- 当前基线：导演台新增第三种 payload kind `shot_replication`（复刻台）。管线：上传参考片（`POST /api/director/replications/{id}/source-video`，mp4/mov/webm ≤2GB，`data/uploads/{user}/{project}/source/`）→ 操作 `analyze_reference_video`（ffmpeg 场景检测智能分镜/固定分段双模式 → 全片一次 DA3 深度提取（`ComfyService.run_depth_extraction`，输出节点 5）→ 逐镜 ffmpeg 切段+双关键帧 → 逐镜视觉 LLM 反推 H3 英文提示词+主体清单（JSON 契约，`analyze_video_shot`；无视觉模型降级为手动填写）→ 逐镜深度切段）→ 人工微调提示词 → 操作 `replicate_shots`（每镜 `wan21-vace-depth-v2v` 排队任务：references[0]=深度视频段、可选首帧参考图，`WanVaceMultiReference` 多参考/`WanVaceToVideo` 无参考回退，输出节点 30）→ 前端原片/复刻并排对比、单镜重试。任务走既有 jobs 串行队列与 `MediaOutput` 交付。`workflow_registry` 新增隐藏工作流 `wan21-vace-depth-v2v`（`hidden_from_catalog=True` 不出现在 `/api/modes`，`WorkflowDefinition` 新增该能力位；options：primary=vace_strength/keep_first_frame，advanced=steps/seed，其余 internal；`normalize_options` 对带 schema 的非 H3 工作流改为按 schema 归一化；seed 沿用平台"归一化即随机"约定，分发层读原始提交值 0=随机并回写生效快照）。复刻台操作经 `POST /api/director/replications/{id}/operations`（复用 SSE 事件流与轮询），OpenAPI tags 新增"复刻台"。
- 受影响文件：新增 `backend/app/{video_analysis.py,video_depth_workflow.py,wan_vace_depth_workflow.py,director_replication.py}`、`frontend/src/director/{DirectorReplicationStudio.tsx,replication-model.ts}`；修改 `backend/app/{models.py,workflow_registry.py,comfy_service.py,director_recipe.py,director_operations.py,main.py,llm_client.py,llm_provider.py,llm_minimax_skills.py}`、`frontend/src/{paths.ts,director/{director-api.ts,DirectorStudioModule.tsx,DirectorHome.tsx,guided-flow.css}}`、`backend/tests/test_core.py`。模型归位脚本 `.zcode/link-vace-models.ps1`（等价 python os.link）。另修复存量阻断项：`xiaji_episode_api.py` 缺 `Response` 导入（OpenAPI 生成崩溃）、compose/export 路由参数缺中文说明。
- 兼容性：payload kind 判定向后兼容（timeline/recipe/batch 不变）；`flatten_recipe_shots` 对顶层 `shots` 的既有兜底使进度统计自动兼容；旧 payload 无需迁移。深度模型文件位于整合包 ComfyUI 目录（符合模型路径规则），未新建第二 ComfyUI 实例，未迁移 VACE 自定义节点。
- 验证命令：`python -m pytest backend/tests -q`（440 通过，新增 `test_wan_vace_depth_workflow_parameter_layers_and_builder_mapping`、`test_shot_replication_payload_normalization`）；`npm --prefix frontend run build`（40 测试+构建通过）。ComfyUI 实跑验证：DA3 深度提取与 VACE 复刻图均出片。人工检查：复刻台桌面/移动端双主题（--studio-* 令牌）。
- 回滚方式：还原本次提交即移除复刻台；已归位模型硬链接/下载文件可保留（不影响既有工作流）。回滚 `normalize_options` 需连同 `workflow_registry.py` 一并还原。

## 2026-09-12 任务队列原子认领与后端并发/健壮性修复批次

- 原因：后端代码审查发现，多宿主共享 MySQL（代码注释明确支持的生产拓扑）下任务认领无原子性——GRS 图片任务可能被多机重复提交重复扣费、同机重复入队双提交、T2V 被另一宿主误标丢失重提；另有运行存储取消竞态、最后一个超管保护为 check-then-act、导演台文件端点按当前登录用户而非工程属主定位文件、批量裂变可静默覆盖任意工程 payload，以及一批解析/计时/资源泄漏健壮性问题。
- 当前基线：`storage.py` 新增 `claim_generation`（条件更新原子认领：仅 QUEUED 且未取消可认领，成功后刷新轮次与任务状态）；`worker.py` 视频 QUEUED→RUNNING 与 GRS 图片提交统一走认领，新增 `queued_generation_ids` 去重集合，参考图不在本机的宿主对 GRS 项留队不认领；`xiaji_episode_run_store.update()` 改为只写显式传入字段（用户取消标志不再被管线进度回写复活）；`auth.py` 新增 `LastSuperAdminError`，`update_user` 以同事务锁（SQLite BEGIN IMMEDIATE / MySQL 锁定读）校验「最后一个活跃超管」；导演台首尾帧上传/读取、TTS、试听、BGM、FCPXML/EDL 导出端点统一使用工程属主 `owner_user_id` 定位文件；`create_director_batch` 携带 project_id 时先校验目标工程为 batch 类型（否则 422，且在 LLM 裂变调用之前）；`request_parameters` 与任务创建对未声明 `negative_prompt`/`image_size` 的工作流容错（不再 KeyError、写路径按 `accepts_*` 忽略）；`replace_dialogue_in_prompt` 改用 lambda 替换（对白含 `\d`/`\1` 等反斜杠序列不再抛 `re.error`），`_speaker_matches_shot` 以角色名词干（前两字）泛化匹配取代「同门/灵石」硬编码加分；`format_srt_time`/ASS 时间按总毫秒/总厘秒取整进位（不再出现 `00:00:60,000`）；`generate_recipe_stills` 增加在途任务守卫（静帧排队/运行中不再重复建任务，force 仍可强制重生成，且对已删除任务 ID 容错）；create_job/create_job_round 参考图保存失败统一清理已落盘目录；`comfy_service.wait` 对 200+非 JSON 响应按瞬时故障处理、`record.status` 空值安全、缺失检查由全量 `/history` 轮询改为轻量 `live_queue_ids`；GRS 轮询超时文案改用 `grs_timeout_seconds` 动态生成；七牛 `object_url` 对 object key 百分号编码；登录限流在 key 失效后回收条目；`verify_credentials` 从 `authenticate` 拆出（修改密码不再污染 `last_login_at`）。同批次补充：`retry_failed_items` 对不存在的轮次 ID 抛 KeyError 并由端点映射 404（此前静默重试最后一轮）；`create_round` 捕获 `UNIQUE(job_id, sequence)` 冲突并抛 ValueError、端点映射 409 并清理已上传参考图（此前 500）；create_job/create_job_round/retry-failed-items 的存储读写包 `asyncio.to_thread`（远程 MySQL 抖动不再阻塞事件循环）；`xiaji_auto_pipeline` 镜头重取使用显式缺失检查（镜头被删除时给出明确错误而非 StopIteration）；worker 的 fire-and-forget 任务（GRS 余额刷新）改经 `_spawn_background_task` 持强引用并在 `stop()` 统一取消（不再可能被 GC 中途丢弃）。
- 受影响文件：`backend/app/{main,storage,worker,auth,comfy_service,dialogue_timing,xiaji_auto_pipeline,xiaji_compose,director_jobs,director_export,xiaji_episode_api,xiaji_episode_run_store,qiniu_storage,llm_provider,api_documentation}.py`、`backend/tests/{test_core,test_director,test_dialogue_timing,test_dev_reloader,test_xiaji,test_ai_studio}.py`。
- 兼容性：API 请求/响应结构与工作流协议不变，无数据库迁移；行为变化：`POST /api/director/batches` 对非 batch 工程返回 422（此前静默覆盖 payload）、对不接受 `negative_prompt`/`image_size` 的工作流这两个表单字段被忽略（此前入库脏数据并可能令任务列表 500）、管理员访问员工工程时导演台文件端点改按工程属主目录读写（此前必然 404 或写错目录）；其余为并发安全与健壮性加固。
- 验证命令：`python -m pytest backend/tests -q`（407 passed；另有 2 个依赖本机工作流 JSON 目录的既有环境性失败，与本批次无关）；`pnpm --dir frontend build`。
- 回滚方式：还原本次提交即恢复原无条件认领/读改写回写/端点级超管检查等逻辑。

## 2026-09-12 导演台生成过程直播工作区视图（单行环节记录 + 当前环节直播 + 始终跟随滚动）

- 原因：剧本阶段「每环节一张折叠卡片」的展示不可用——运行中已完成环节缩成一行摘要、历史回放全量堆叠且漏种子 `researchNotes`（研究块展开为空）、自动跟随滚动依赖不完整且无回底入口，用户无法直观看出当前 agent 正在生成什么。
- 当前基线：`DirectorScriptStreamPanel` 管线视图改为直播工作区时间线：已完成/失败环节渲染为单行完成条目（官方 tool-chips 行语法），整行点击打开 antd Drawer（`rootClassName=director-agent-drawer`，抽屉根节点成对配置官方浅色/暗色 `--director-*` token，因 Drawer 挂载在 body 下拿不到 `.is-chat` 作用域 token），抽屉内容复用 `renderBlockBody`；失败条目内联重试（`onRetryAgent`）。当前运行环节渲染为唯一的全宽直播卡片（`director-block is-live`，官方 thinking「工作中」头部语法，无折叠交互）；`manualExpanded`/`blockPreview` 折叠逻辑移除。滚动跟随改为 ResizeObserver 监听 `.director-stream-body` 与内容容器（`.director-stream-feed`）高度变化贴底，上滚超 48px 解除跟随并显示「回到底部」胶囊（即时 `scrollTop=scrollHeight`，不用平滑滚动——目标值会随流式内容过期），`runningAgentId` 变化强制恢复跟随，终态出现后 `scrollIntoView` 定位到完成卡页脚。历史回放种子补 `research|notes|`（`RecipeProject` 新增可选 `researchNotes` 字段，后端 payload 原样透传）。`DirectorTaskRows` 新增 `onOpen`（完成/失败行点击打开同一抽屉，重试按钮 `stopPropagation`）。
- 受影响文件：`frontend/src/director/components/{DirectorScriptStreamPanel,DirectorTaskRows}.tsx`、`frontend/src/director/{recipe-model.ts,action-copy.ts,guided-flow.css}`。
- 兼容性：纯前端展示层；SSE 事件、REST API、存储结构不变；旧工程历史回放自动获得新视图。
- 验证命令：`pnpm --dir frontend build`（vitest + tsc + vite）、`python -m unittest discover -s backend/tests -t . -p "test_director*.py"`。人工回归：浅/暗双主题历史回放与抽屉、390px 移动端、真实运行中单行记录累积/直播卡贴底/上滚解除跟随/回底后持续跟随、失败态红行与内联重试。
- 回滚方式：还原本次前端提交即恢复折叠卡片视图。

## 2026-09-12 导演台生成过程两栏化（左侧任务栏 + 右侧全宽直播）

- 原因：自查发现运行中「生成任务」面板（max-height 360px）与直播时间线上下堆叠：同一份 agentStatus 呈现两遍、直播区被压缩、无流式内容的环节（画风/媒体类）只剩标题卡 + 大片空白、阅读顺序为任务→方向→创意→过程。
- 当前基线：`DirectorScriptStreamPanel` pipeline 分支在桌面端（`!isMobile`）渲染 `.director-script-layout`（flex 两栏）：左 `.director-task-rail`（248px，`DirectorTaskRows variant="rail"`——常开、纵向头部「生成任务 n/m + 进度条 + 百分比/已进行」、行内不渲染 message，点击完成/失败行走 `onOpen` 抽屉），右为原 `.director-script-stream` 直播卡（flex:1）。创作方向 chips 从流卡外移入 `.director-stream-feed`（创意气泡之后）。空 body 运行环节渲染 `.director-live-skeleton`（shimmer 骨架行）。澄清/空态分支维持单栏流卡。移动端断点隐藏侧栏并回落为折叠任务面板置顶。
- 受影响文件：`frontend/src/director/components/{DirectorTaskRows,DirectorScriptStreamPanel}.tsx`、`frontend/src/director/guided-flow.css`。
- 兼容性：纯前端布局；数据流、SSE、API、存储不变。
- 验证：`pnpm --dir frontend build`；浏览器实测双主题两栏、侧栏进度条、侧栏行抽屉、移动端回落形态。
- 回滚方式：还原本次提交即恢复单栏 + 顶部任务面板。

## 2026-09-12 分镜直播镜头级行列表

- 原因：分镜直播把全部镜头平铺且描述 clamp 两行，无法观察单镜头实时生成；流式过程中跟随滚动易丢。
- 当前基线：`renderBlockBody("storyboard")` 在直播态（`runningAgent?.id === "storyboard"` 且非 historyMode）渲染 `.director-shot-stream-row` 行列表——完成镜头一行（镜号 + 标题 + CheckCircle2，title 悬停显示描述），当前镜头展开完整流式 title/description/dialogue（光标跟随最后一个非空字段），场景标题行置顶；`agent_item` 闭合即收起、新镜头 delta 开始即展开。`activeIndex["storyboard|shots"]` 变化时强制恢复跟随（`followTailRef=true` + 跳底）。历史回放与 Drawer 保持原平铺渲染。
- 受影响文件：`frontend/src/director/components/DirectorScriptStreamPanel.tsx`、`frontend/src/director/guided-flow.css`。
- 兼容性：纯前端展示层。
- 验证：`pnpm --dir frontend build`；雨夜抉择历史回放回归（侧栏/条目/失败行重试）通过。
- 回滚方式：还原本次提交。

## 2026-09-12 分镜直播 activeIndex 键不匹配修复

- 原因：`agent_delta.field` 为显示字段名（title/description/dialogue）、`index` 为数组内全局序号，前端 `activeIndex` 键为 `storyboard|<field>`；分镜渲染读取不存在的 `activeIndex["storyboard|shots"]` 导致当前镜头直播从未渲染（历史遗留 bug，非本次重构引入）。另场景/镜头字段同名同序号导致前端文本键串字。
- 当前基线：前端 `storyboardShotOrdinal = max(activeIndex["storyboard|title"|"description"|"dialogue"])` 作为当前镜头序号，`activeShot >= len(shots)` 时才追加活跃行防键重复；后端 `_stream_active_item` 新状态首条 delta 发 `reset=true`（前端按 key 替换，场景标题不再拼进镜头标题）。后端改动需重启进程生效。
- 受影响文件：`frontend/src/director/components/DirectorScriptStreamPanel.tsx`、`backend/app/director_stream.py`。
- 兼容性：SSE 事件结构不变；旧事件流兼容。
- 验证：`pnpm --dir frontend build`、导演台 119 项单测通过。
- 回滚方式：还原本次提交。

## 2026-09-12 分镜打磨阶段进度面板

- 原因：分镜打磨（按秒分配对白与动作/校验镜头衔接）的 LLM 调用不进 tracker（`chat_fn.on_chunk` 被替换为字数上报），打磨期间前端无 delta 流，无法展示当前处理的镜头。
- 当前基线：`director_agents.py` 打磨/衔接运行消息附镜头范围（timing chunk 取 `shotNumber` 首尾，continuity 窗口取 `editableShotNumbers` 首尾）；前端 `parseStoryboardPhase` 解析运行消息，storyboard 直播卡在打磨阶段渲染 `.director-phase-panel`（阶段名 (i/N) + `director-phase-chip` 镜头芯片网格：已完成/处理中/未到三态 + 已收字数），阶段切换强制恢复跟随；写分镜阶段维持镜头行直播。
- 受影响文件：`backend/app/director_agents.py`、`frontend/src/director/components/DirectorScriptStreamPanel.tsx`、`frontend/src/director/guided-flow.css`。
- 兼容性：运行消息文本变化，前端兼容旧格式（无范围时不高亮芯片）。
- 验证：`pnpm --dir frontend build`、导演台 119 项单测通过。
- 回滚方式：还原本次提交。

## 2026-09-12 逐步确认流程（分环节 plan_clarify + 引导链）

- 原因：创意澄清只覆盖剧本方向，画风/角色/场景/分镜/配音/配乐由 Agent 自动决定，用户无确认点。
- 当前基线：`plan_clarify` 请求新增可选 `agent`（取值 `STAGE_CLARIFY_AGENT_IDS = art_style/characters/locations/storyboard/voice/music`，`main.py` 校验；`DirectorOperationService._run_clarify` 按环节加载 Recipe 上下文并透传 `run_director_clarify(goal, recipe, agent)`，复用 `AGENT_STREAM_SPECS["clarify"]` 流式问题）。`plan_clarify`/`plan_pipeline` 请求新增 `guided` 标记；`DirectorClarificationItem` 新增 `agent` 归属——剧本 Agent 只消费无标记答案（`_clarified_goal_text/_clarified_beat_target` 过滤），`run_agent` 的 art_style/characters/locations/storyboard/voice/music 经 `_clarified_stage_text` 把对应环节答案注入 user 消息。初始流水线从「一次跑全量」改为只跑 `script`，之后前端编排引导链：每个 `guided` `plan_pipeline` 成功且无失败 agent 时，用 `guided-flow.ts` 的 `nextGuidedStep(payload)`（按画风/角色/场景/镜头/声线/配乐派生，幂等、刷新安全）自动发起下一环节 `plan_clarify`；链条走完或失败/取消才落完成卡。澄清作用域持久化为 `{agent, questions}`（键 `director-clarify:{projectId}`，兼容旧数组）。`plan_pipeline` 的 `agents` 子集与单飞约束、SSE 事件、审批流均不变。
- 受影响文件：`backend/app/{llm_minimax_skills,llm_provider,director_operations,director_agents,models,main}.py`、`frontend/src/director/{guided-flow.ts,guided-flow.test.ts,action-copy.ts,director-api.ts,DirectorRecipeStudio.tsx,guided-flow.css}`、`frontend/src/director/components/DirectorScriptStreamPanel.tsx`。
- 兼容性：不带 `agent` 的 `plan_clarify` 与不带 `guided` 的 `plan_pipeline` 行为不变；旧 clarifications（无 agent）仍作用于剧本；前端兼容旧 localStorage 格式。
- 验证：`pnpm --dir frontend build`、前端 vitest 45 项、导演台 120 项单测通过。
- 回滚方式：还原本次提交。

## 2026-09-12 逐步确认链 E2E 联测修复

- 原因：真实全链路联测发现：旧澄清问题卡在新一轮提问期间仍可作答（作答走过期作用域后被静默丢弃）；配音完成误判（归一化填默认 voiceId，`characters.some(voiceId)` 恒真）；环节澄清流式期间标题回退剧本轮文案。
- 当前基线：面板以 `initialQuestions`（澄清作用域）为唯一事实源，作用域清空/换轮即重置问题卡与作答进度；`handleRun`/`continueGuidedFlow` 创建新操作前清空待答作用域；`handleStartPipeline` 作用域缺失时提示并忽略作答（3 秒竞态宽限），单飞等待超时改为明确提示。`nextGuidedStep` 改为「产出存在或 agentStatus=completed 视为完成」，配音环节只看 `agentStatus`。面板 `clarifyAgent` 回退读活动 plan_clarify 的 `request.agent`。已在测试工程（proj-79bc4dc943d14c03）跑通 剧本→画风→角色→场景→分镜→配乐→配音 全链路并验证刷新恢复。
- 受影响文件：`frontend/src/director/{guided-flow.ts,guided-flow.test.ts,DirectorRecipeStudio.tsx}`、`frontend/src/director/components/DirectorScriptStreamPanel.tsx`。
- 兼容性：纯前端修正；后端协议不变。
- 验证：`pnpm --dir frontend build`、前端 vitest 46 项、浏览器自动化全链路实测。
- 回滚方式：还原本次提交。

## 2026-09-12 分镜打磨阶段直播化（当前镜号 + 流式字幕）

- 原因：打磨期间直播卡只有镜头芯片和静态「已收 N 字」，用户看不到正在处理哪个镜头、更看不到被改写的内容，要等整段跑完才有反馈。
- 当前基线：`director_stream.py` 新增 `scan_current_shot_number()`（跳过 `<think>`/围栏后取累计流中最后一个 `"shotNumber": N`）与独立命名空间 spec `storyboard_polish`（shots 数组，display 字段 description/dialogue）。`director_agents.py` 的 Timing/Continuity pass 每个分块/窗口新建一个 `storyboard_polish` tracker 与字数上报合并挂到 `chat_fn.on_chunk`：①运行消息追加「· 正在第 N 镜」（复用既有 SSE `agent` 事件）；②当前正在改写镜头的 description/dialogue 以 `agent_delta` 实时推送（每分块索引归零，前端仅作瞬时直播字幕，不落 `storyboard|shots` items，历史回放不受影响）。前端 `parseStoryboardPhase` 解析 `currentShot`，`.director-phase-panel` 芯片按 currentShot 逐镜推进（已完成绿/当前脉冲），新增 `.director-phase-live` 当前镜直播行（标题取已完成镜头 items，正文流式打字机 + 光标），「已收 N 字」加千分位与 live 脉冲点。
- 受影响文件：`backend/app/{director_stream,director_agents}.py`、`backend/tests/test_director.py`、`frontend/src/director/components/DirectorScriptStreamPanel.tsx`、`frontend/src/director/components/DirectorScriptStreamPanel.phase.test.ts`、`frontend/src/director/guided-flow.css`。
- 兼容性：SSE 事件为纯增量（新 agent 命名空间 `storyboard_polish`，旧客户端忽略未知字段即可）；运行消息新增片段但旧格式仍可解析（无 `正在第 N 镜` 时回退 range 高亮）；不改 API、数据库、ComfyUI 协议。
- 验证：`python -m unittest backend.tests.test_director.DirectorAgentPipelineTests`（含新增 `test_storyboard_polish_reports_current_shot_and_streams_deltas`）、`pnpm --dir frontend test`、`pnpm --dir frontend build`。
- 回滚方式：还原本次提交即回到芯片网格 + 静态字数面板。

## 2026-09-12 已完成环节「重新生成」（含级联清空后续）

- 原因：逐步确认链走完后每个环节只有「已完成」徽章和抽屉回看，用户对某环节产物不满意时没有任何重做入口，只能放弃整案。
- 当前基线：任务栏（rail/panel）与聊天结果行（`renderStepRow`）的已完成环节新增「重新生成」入口（官方重试图标语法，hover 显现、触屏常显、运行中禁用；仅历史回放/终态展示，直播中隐藏）。点击弹出确认框：①范围单选「仅重做本环节 / 重做本环节并清空后续环节」（无已完成下游时省略）；②动作「直接重新生成 / 调整要求后重新生成」（脚本/研究/媒体无阶段澄清，仅提供直接重生成）；分镜附媒体关联失效提示。`plan_pipeline` 请求新增 `reset_following: bool`——`DirectorOperationService._run_plan` 在目标环节**成功后**调用 `director_recipe.reset_recipe_following(recipe, agent_id)`：按 `PIPELINE_AGENT_ORDER` 清空其后环节产物（artStyle、characters/props、locations、scenes+continuityQa、characters[].voiceId、globalMusic/globalSoundscape）并重置 agentStatus 为 pending（失败/取消不动下游）；旧 shot 的 takes/jobId 随 scenes 替换解绑，沿用「原任务媒体不删除」语义。`result.reset_following` 回显是否执行。前端重生成请求一律带 `guided: true`，级联清空后 `nextGuidedStep` 自然指向下一缺失环节，引导链自动从下一环节续跑；「调整要求」路径复用 `continueGuidedFlow(agent)` 重新生成该环节确认问题卡，级联标记经澄清作用域 `{agent, questions, regenerateResetFollowing?}`（键 `director-clarify:{projectId}`）持久化并在 `handleStartPipeline` 注入。顺带修复 `handleRerun` 的 `skip_research` 反向条件（`agentId !== "research"`）。
- 受影响文件：`backend/app/{models,director_recipe,director_operations}.py`、`backend/tests/test_director.py`、`frontend/src/director/{action-copy.ts,action-copy.test.ts,guided-flow.ts,guided-flow.test.ts,director-api.ts,DirectorRecipeStudio.tsx,guided-flow.css,index.css}`、`frontend/src/director/components/{DirectorTaskRows,DirectorScriptStreamPanel}.tsx`。
- 兼容性：`reset_following` 默认 False，不传行为与旧版完全一致；澄清作用域新增可选字段，`parseClarifyScope` 兼容旧格式；无数据库迁移。
- 验证：`python -m unittest backend.tests.test_director`（117 项，含新增 `ResetRecipeFollowingTests` 7 项）、`pnpm --dir frontend test`（51 项）、`pnpm --dir frontend build`、浏览器双主题/桌面+移动端自查。
- 回滚方式：还原本次提交（前端隐藏入口 + 后端忽略新参数即等价回滚，无数据迁移）。

## 2026-09-12 确认题强制保留自定义输入

- 原因：所有澄清/确认题必须允许用户自填答案，`allowCustom` 不能交给 LLM 决定。
- 当前基线：`_normalize_clarify_item` 强制 `allowCustom=true`；两份 clarify prompt 声明禁止关闭自定义；前端 `DirectorScriptStreamPanel` 无条件渲染自定义输入行。`plan_clarify` 协议不变。
- 受影响文件：`backend/app/llm_minimax_skills.py`、`backend/tests/test_director.py`、`frontend/src/director/components/DirectorScriptStreamPanel.tsx`。
- 兼容性：纯收紧性修正，接口与数据结构不变。
- 验证：导演台单测 129 项、前端 vitest 54 项、前端构建通过；浏览器实测自定义答案提交并生效（beat_count 自填 12 → 剧本 12 Beat）。
- 回滚方式：还原本次提交。

## 2026-09-13 剧本封面上传与澄清自定义选项

- 变更原因：导演台设计稿缺少“输入你的想法”自定义选项的明确表达，且剧本创意中的人物被误画成无数据来源的背景图；系统需要一个真实的剧本封面上传位置。
- 当前基线：Recipe 的 `script` 支持可选 `coverUrl`；新增 `POST/GET/DELETE /api/director/recipes/{project_id}/cover`，图片按 `data/uploads/{user}/{project}/cover.*` 隔离保存，并通过 `cover_url` 回显到工程列表。导演台剧本空态和成稿文档使用 Ant Design `Upload` 提供上传、替换、移除；首页工程卡有封面时显示用户图片。无封面时保持纯 UI 空态，澄清卡逐行保留全部预置选项并额外包含“输入你的想法”可输入项。
- 受影响文件：`backend/app/{director_recipe,director_jobs,main,models,storage,api_documentation}.py`、`frontend/src/director/{recipe-model,director-api,DirectorRecipeStudio,DirectorHome}.tsx`、`frontend/src/director/components/{DirectorScriptCoverPicker,DirectorScriptDocument}.tsx`、`frontend/src/director/{guided-flow.css}`、`frontend/src/index.css`、`docs/导演台设计图生图提示词.md`、`docs/导演台流程与界面结构.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：旧 Recipe 没有 `coverUrl` 时继续正常打开和生成；无数据库迁移；内容版本校验沿用现有 409 冲突机制。回滚可移除新增入口、路由和封面文件，不影响镜头任务或既有媒体。
- 验证命令：`python -m unittest discover -s backend/tests -p 'test_*.py'`、`pnpm --dir frontend build`；补充浅色/暗色桌面与 390px 移动宽度的真实工作台检查。
- 回滚方式：还原本节涉及代码与文档，删除 `data/uploads/{user}/{project}/cover.*`（可选），旧工程数据无需迁移。

## 2026-09-13 导演台「AI 生成 / 手动编辑」创作模式切换

- 变更原因：导演台九阶段产物此前只有零散的手动编辑入口（如对话流底部的「编辑剧本」），没有一个总开关让用户在 agent 自动创作与手动创作之间显式切换；同时确认三处编辑缺口——配乐方案文本（`globalMusic`/`globalSoundscape`）无任何编辑 UI、角色/场景/道具无手动新建、创作视图分镜空态无「新建镜头」。
- 当前基线：新增纯前端创作模式 `DirectorCreationMode = "agent" | "manual"`（`frontend/src/director/creation-mode.ts`），真源为 URL `?mode=manual`（可分享），缺省读工程级 localStorage（`director-creation-mode:<projectId>`），再缺省 AI 生成；切换双写 URL + localStorage，切阶段/刷新保持。顶栏与移动端头部常驻 antd Segmented 切换（`components/DirectorCreationModeSwitch.tsx`，AI 写作进行中禁用）。手动模式：剧本阶段与普通阶段同布局（显示左侧阶段导航与任务头，可直接跳转其他环节），主区渲染专属手动工作区（`DirectorScriptDocument` 默认编辑态，860px 居中栏，隐藏 Prompt Bar/澄清卡/继续生成/AI 记录流）；隐藏 AI 写作类入口（画风「生成创作方案」、「根据剧本生成分镜」、「按剧本重新生成分镜」菜单、任务活动抽屉「生成/重跑」、移动端 FAB 同步过滤），保留全部执行类操作（定妆/静帧/渲染/TTS/合成）；补齐缺口——`DirectorExportPanel` 配乐段新增「配乐方案/环境声方案」TextArea（两种模式可见），角色/场景/道具工具条新增「新增」按钮（`createEmptyRecipeCharacter/Location/Prop` + 导出 `newRecipeEntityId`，两种模式可见），分镜空态与 bin 工具条新增「新建镜头」（复用 `insertRecipeShotAfter`，空 scenes 自动建首场景）；「更多操作」菜单项为空时不渲染按钮。手动填写内容经既有 `PUT /api/director/projects/{id}` 整包保存，就绪度由 payload 派生，切回 AI 生成时引导链自动跳过已有内容环节，**后端零改动**。
- 受影响文件：`frontend/src/director/{creation-mode.ts(新增),DirectorRecipeStudio.tsx,recipe-model.ts,types.ts,DirectorMobileChrome.tsx,guided-flow.css}`、`frontend/src/director/components/{DirectorCreationModeSwitch.tsx(新增),DirectorExportPanel.tsx}`、`docs/导演台流程与界面结构.md`（含新增参考截图 `22-script-manual.png`、`23-storyboard-manual-empty.png`，重拍 02-12/17/18/19）、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：无 API/数据库变更；默认 AI 生成模式行为与旧版完全一致（对话创作室复刻组件零样式改动）；localStorage 缺失或被禁用时回退 URL/默认值。
- 验证命令：`pnpm --dir frontend build`、`python -m unittest discover -s backend/tests -p 'test_*.py'`（470 项；`test_director_stream.test_plan_clarify_emits_stream_and_done_with_questions` 为 dev 分支既有失败，与本变更无关，已用 git stash 基线复现确认）、真实工作台浏览器自查（桌面 1920/1440 + 移动 390 宽、浅色/暗色双主题、模式切换与刷新保持、手动编辑自动保存、AI 模式回归对照）。
- 回滚方式：还原本次前端提交即可（无数据迁移、无后端变更；localStorage 键与 URL 参数残留无害）。


## 2026-09-13 镜头正文“中文编辑、英文提交”（中文镜头正文 + 一键翻译）

- 变更原因：镜头检查器此前只暴露英文 `promptText`（MiniMax H3 官方要求英文镜头正文），中文用户读写困难；且前端编译预览错误地把中文卡片描述 `description` 前置拼进正文（`prompt-compiler.ts` 623-624 行），与后端实际提交内容（`recipe_shot_as_timeline_shot` 只取 promptText，为空才回退 description）不一致，用户会误以为中文会被提交。
- 当前基线：检查器文案 Tab 以「中文镜头正文」承载中文内容——即镜头既有 `description` 字段（AI 分镜生成后直接有值，同时仍是静帧提示与编译回退来源），原「描述（中文卡片）」编辑框移除，中英正文一一对应；`RecipeShot` 另有 `promptTextStale`（中文改过、英文待同步）、`promptTextManual`（用户手动改过英文，翻译需确认覆盖）与兼容字段 `promptTextZh`（已不再由界面写入，接口仍作输入回退）三个可选键，`_normalize_shot` 按需透传（缺省键不落盘，旧工程零迁移）。字段顺序：标题 → 中文镜头正文 → 英文镜头正文（提交用，可手动微调）+「翻译为英文正文」按钮与同步状态徽标（待同步 / 已手动调整 / 已同步；手动改过英文时翻译需 Popconfirm 确认覆盖）。新增同步接口 `POST /api/director/recipes/{project_id}/shots/{shot_id}/translate-prompt`（body 可选 `text`，缺省读镜头中文正文：`promptTextZh` → `description`，规范化产生的标题占位不算中文正文）：用已配置 LLM 按官方 `h3-prompt-writing` skill 翻译（对白/画面文字保留原语言、人名不翻译、保留时间码与 `<Picture n>`），只返回 `{promptText}` 不落库，由前端随既有 `PUT /api/director/projects/{id}` 保存链写回。LLM 未配置返回 503、缺中文正文 422、未知 shot 404。同时移除前端预览的中文描述前置拼接，编译预览与真实提交（润色前）一致；`handleRender` 对“英文正文为空但有中文正文”的镜头给出非阻断提醒（仍走 description 回退编译）。
- 受影响文件：`backend/app/{director_recipe,llm_minimax_skills,llm_provider,main,models,api_documentation}.py`、`backend/tests/test_director.py`、`frontend/src/director/{recipe-model,director-api,prompt-compiler,DirectorRecipeStudio}.tsx/ts`、`frontend/src/director/components/{RecipeShotInspector,DirectorTimelineView}.tsx`、`frontend/src/index.css`、四份文档。
- 兼容性：提交/编译/润色链路零改动（`promptText` 仍是唯一提交正文来源）；旧工程无新字段时翻译按钮禁用、原直接写英文的工作流不变；无数据库迁移。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorTranslatePromptEndpointTests backend.tests.test_director.DirectorRecipeModelTests`、`python -m unittest discover -s backend/tests -p 'test_*.py'`（475 通过 1 失败；失败项 `test_director_stream.test_plan_clarify_emits_stream_and_done_with_questions` 为 dev 分支既有失败，git stash 基线复现确认）、`npx tsc --noEmit` 与 `npm run build`（frontend，54 项前端单测全过）。
- 回滚方式：还原本次提交即可；新字段为可选键，存量数据无需迁移。参考截图 `11/12/19` 因检查器新增字段待按附录重拍。

## 2026-09-13 分镜失败「重试」续跑（保留已产出镜头，不重头拆镜）

- 变更原因：分镜 Agent 先写镜头再做对白补全、按秒时长分配与衔接校验，后续步骤的 LLM 失败会把整个环节标记失败，但已产出的镜头仍在工程里；此时完成卡只有「继续生成：下一环节」，用户想修分镜只能从任务栏失败 pill「重跑」——而那是整环节重拆，会替换全部镜头，与“只补完失败部分”的直觉相悖。
- 当前基线：`plan_pipeline` 请求新增可选 `resume: bool`（`DirectorOperationCreateRequest`，默认 False）→ `DirectorOperationService._run_plan_pipeline` → `run_director_recipe` → `run_recipe_pipeline` → `run_agent` 透传。分镜 Agent 在 `resume=True` 且工程已有镜头时跳过「读剧本拆镜」与 `_apply_storyboard`（不覆盖 `scenes`），直接补跑 `_normalize_recipe_dialogue_fields` → 对白覆盖率检查/剧本对白回填 → 按秒 Timing Pass → 衔接校验与因果修复 → completed（运行消息「保留已有 N 个镜头，继续完成对白与衔接处理」）；`resume=True` 但无镜头时回落为完整重拆，非分镜环节忽略该标记。前端：完成卡（`DirectorCompletionCard`）在有失败环节时渲染「重试<环节名>」按钮（title「保留已产出结果继续这一步，不重头生成。」），点击经 `handleRetryFailedAgent` 分派——分镜走新增 `handleResumeStoryboard`（`agents:["storyboard"]` + `resume:true` + `guided:true`，成功后引导链自动衔接下一环节；无镜头回落 `handleGenerateStoryboard`），其余环节仍走 `handleRerun`；任务栏失败 pill（`onRetryAgent`）与 `handleRerun` 的分镜分支统一改走同一续跑入口，重试语义全局一致。
- 受影响文件：`backend/app/{models,director_operations,llm_provider,director_agents}.py`、`backend/tests/test_director.py`（新增续跑 2 项）、`frontend/src/director/{action-copy.ts,director-api.ts,DirectorRecipeStudio.tsx}`、`frontend/src/director/components/DirectorCompletionCard.tsx`、`frontend/src/director/guided-flow.css`、四份文档。
- 兼容性：`resume` 默认 False，不传行为与旧版完全一致；无数据库迁移；旧工程失败态直接可续跑。全量重拆入口不变（分镜设计页「按剧本重新生成分镜」仍走 `handleGenerateStoryboard` 并保留替换确认弹窗）。
- 验证命令：`python -m unittest backend.tests.test_director`（130 项通过）、`pnpm --dir frontend build`；浏览器自查完成卡重试按钮双主题渲染。
- 回滚方式：还原本次提交即可（前端不传 `resume`、后端忽略该字段即等价回滚，无数据迁移）。



## 2026-09-13 「道具定妆」独立子阶段（前端阶段模型）

- 变更原因：视觉素材步骤左侧阶段导航只有角色/场景两个子项，右侧内容区却是角色/场景/道具三个 Tab；「道具」此前仅靠组件本地状态（`assetTab`）寄生在角色定妆阶段下，无导航入口、无 URL 阶段、无就绪度，两侧清单不一致。
- 当前基线：`recipe-readiness.ts` 的 `RECIPE_STAGE_IDS` 新增 `props`（位于 `locations` 后；同日 `storyboard` 阶段并入 `shots`，阶段总数为 9），`RECIPE_STAGE_GROUPS` 视觉素材组为 `["characters", "locations", "props"]`，`RECIPE_STAGE_LABELS` 新增「道具定妆」，`recipeReadiness` 新增 props 就绪度（已采纳转面图 `turnaround` 计数）；`recipe-flow.ts` 的 `next` 映射新增 `props: "shots"`。`DirectorRecipeStudio` 删除 `assetTab` 本地状态，Tab 栏与内容渲染统一由 `?stage=` URL 参数驱动；`DirectorTaskHeader` 的 `STAGE_DETAILS` 补 props 条目。后端九环节 agent 流水线（`AGENT_IDS`）不变，道具仍由 characters 环节产出。
- 受影响文件：`frontend/src/director/recipe-readiness.ts`、`frontend/src/director/recipe-flow.ts`、`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/components/DirectorTaskHeader.tsx`、`frontend/src/director/recipe-readiness.test.ts`、`frontend/src/director/recipe-flow.test.ts`、`docs/导演台流程与界面结构.md`、`README.md`。
- 兼容性：纯前端导航层变更，无 API / 数据库 / ComfyUI 协议变化；`?stage=characters` 等旧链接与既有工程数据不受影响，`parseRecipeStage` 对未知阶段仍回落剧本阶段。
- 验证命令：`pnpm --dir frontend test`（54 项通过）、`pnpm --dir frontend build`；浏览器实测左右导航联动与 `?stage=props` 深链。
- 回滚方式：还原本次提交即可，前端回滚后道具退回角色定妆内 Tab 形态，无数据迁移。


## 2026-09-13 「分镜设计」阶段并入「镜头设计」（设计 / 制作双模式）

- 变更原因：左侧导航的「分镜设计」（`storyboard`）与「镜头制作」（`shots`）两个阶段底层是同一份镜头数据（`recipe.scenes[].shots`），就绪计数 8/8 与 0/8 数的是同一批镜头，用户感知为重复内容；两者渲染同一个镜头工作台（镜头列表 + `RecipeShotInspector`），仅 focus 不同（design=编辑分镜与提示词，production=画质设置与逐镜出片）。
- 当前基线：`recipe-readiness.ts` 删除 `storyboard` 阶段 id，`shots` 标签改为「镜头设计」，`RECIPE_STAGE_GROUPS` 收敛为 4 组并按 故事与风格 → 视觉素材（角色/场景/道具）→ 镜头设计 → 声音与交付 排序（与后端 Agent 流水线顺序一致）；导出 `placeholderBoard` 供流程判断；`parseRecipeStage` 的 legacy 映射把 `storyboard` / `board` 重定向到 `shots`（旧链接 `?stage=storyboard` 仍可用）。`DirectorRecipeStudio` 新增 `shotMode`（`design | production`，默认 design，切换工程重置），镜头工作台批量条左侧新增 antd Segmented「设计 / 制作」；原 `activeStage === "storyboard"` 分支全部改由 `shotMode` 承载，检查器 `focus` 直接传 `shotMode`，设计模式底部按钮改为「切换到制作」（模式内切换，不再跳阶段）。`recipe-flow.ts` 的 next 映射改线性：script/art_style → characters，characters/locations/props → shots，shots → voice，export → shots；镜头设计阶段 summary 合并为「N 镜已设计 · X / Y 镜可用」。后端 9 个 LLM Agent（`storyboard` 仍为拆镜环节）不变。
- 受影响文件：`frontend/src/director/recipe-readiness.ts`、`frontend/src/director/recipe-flow.ts`、`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/action-copy.ts`、`frontend/src/director/components/DirectorTaskHeader.tsx`、`DirectorStageNav.tsx`、`RecipeShotInspector.tsx`、`DirectorExportPanel.tsx`、`DirectorCompletionCard.tsx`、`frontend/src/director/recipe-readiness.test.ts`、`docs/导演台流程与界面结构.md`、`docs/API.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：纯前端导航与交互层变更；不改后端 Agent、payload、数据库与 ComfyUI 协议，既有工程数据零迁移；旧 URL `?stage=storyboard` / `board` 经 legacy 映射落到 `shots`。
- 验证命令：`pnpm --dir frontend build`（vitest + tsc + vite）、`python -m unittest backend.tests.test_director`（129 项通过）；浏览器桌面/移动端检查导航分组计数、设计/制作切换、主按钮流转与旧链接兼容。
- 回滚方式：还原本次前端提交即可（导航层回退到双阶段结构，数据无影响）。

## 2026-09-15 导演台2 AI 取消与直播记录对齐

- 变更原因：导演台2 取消接口只写入 `cancel_requested`，前端收到响应后却立即关闭 SSE，导致看不到后端稍后写入的 `cancelled`；生成记录区也只渲染骨架，没有消费导演台 Agent 的直播事件。
- 当前基线：`AiGenerationService.cancel` 写入取消标记后立即广播 `status`，流式回调、澄清返回后和最终 adapter 写库前均检查取消，最终以明确的 `cancelled` 终态关闭事件流；Director2 前端点击后先乐观标记“正在停止”，保持 SSE 与 1.2 秒状态轮询直至终态。`DirectorLiveStepFeed.tsx` 是导演台与导演台2共用的步骤行/展开直播块视图，Director2 消费 `status`、`agent`、`agent_delta`、`agent_item`、`done`、`cancelled`、`error`，已完成阶段显示摘要行，当前阶段显示真实流式正文和条目卡。
- 受影响文件：`backend/app/media_studio/{routers/project_router.py,services/ai_generation_service.py}`、`backend/tests/test_director2_ai_generation.py`、`frontend/src/director/components/{DirectorLiveStepFeed.tsx,DirectorScriptStreamPanel.tsx}`、`frontend/src/director2/{director2-ai-operation-state.ts,director2-ai-operation-state.test.ts,panes/Director2AiStudioPane.tsx}`。
- 兼容性：API 路径、operation JSON 与数据库结构不变；SSE 新增标准 `id` 行并补充取消中的 `status` 事件，旧客户端会忽略新增字段。已完成数据和手工内容不会因取消删除。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`；在 5173 验证运行中、取消中、已取消、失败、完成及桌面/移动双主题。
- 回滚方式：还原上述前后端文件即可；无数据迁移或数据回滚。

## 2026-09-15 导演台2 AI 任务中断恢复与自动接管（修复“已有进行中的 AI 任务”死锁）

- 变更原因：`AiGenerationService.recover_orphaned_jobs()` 虽已实现（进程重启后把 `queued/running/clarifying` 的 `ai_pipeline` 孤儿任务标记为 `failed`），但 `main.py` lifespan 只调用了 `EpisodeVideoService` 与 `StoryboardImageService` 的恢复，漏掉了它——后端重启后 `ai_pipeline` 任务永久停留在活跃状态，`create` 的唯一活跃任务校验从此拒绝该项目的一切新提交，报「该项目已有进行中的 AI 任务：aiop-xxx」，且界面上看不到任何运行中的任务（0/5、0%）。前端又只依赖 localStorage 里的 operation id 恢复视图，换浏览器 / 清缓存 / 旧版本创建的任务一律不可见，用户既不能取消也不能重试，形成死锁。
- 当前基线：`main.py` lifespan 在 `EpisodeVideoService` / `StoryboardImageService` 之后调用 `AiGenerationService.recover_orphaned_jobs()`，重启后被中断的任务标记为 `failed`（error=「服务进程重启，AI 任务已中断，请重新提交或重试。」），可走既有「重试本阶段」。`AiGenerationService` 新增 `get_active(project_id)`，路由新增 `GET /api/projects/{project_id}/ai/operations/active`（注册在 `/{operation_id}` 之前避免路径参数误捕获；无活跃任务时返回 JSON `null`）。前端 `Director2AiStudioPane` 挂载时先调 active 接口认领进行中的任务（订阅 SSE + 1.2s 轮询），无活跃任务才回退 localStorage 恢复；`createAiOperation` 失败（400 活跃任务冲突等）时同样自动认领并提示「该项目已有进行中的 AI 任务，已恢复显示其进度」，认领失败才回退展示原始错误 toast。
- 受影响文件：`backend/app/main.py`、`backend/app/media_studio/{services/ai_generation_service.py,routers/project_router.py}`、`backend/tests/test_director2_ai_generation.py`、`frontend/src/director2/{api.ts,panes/Director2AiStudioPane.tsx}`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：新增只读端点，既有 AI 操作 API 路径、operation JSON 与数据库结构不变；`active` 与既有任务 id 命名空间不冲突（任务 id 为 `aiop-` 前缀）。历史残留的活跃孤儿行在下次后端重启时自动收敛为 `failed`，无需手工修库。
- 验证命令：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend build`。
- 回滚方式：还原上述前后端文件即可；无数据迁移或数据回滚。


## 2026-09-13 存储目录弹窗不再因 /api/storage 瞬时错误误弹（七牛云场景）

- 变更原因：七牛云启用时 `GET /api/storage` 正确返回 `requires_local_directory: false`，但前端把该查询的瞬时失败（后端重启、网络抖动）也当作「需要本地目录」，导致七牛云用户在刷新/登录时偶发被「设置作品存储目录」弹窗拦截。
- 当前基线：`frontend/src/App.tsx` 的 `storageQuery` 成功后把能力结果缓存到 `localStorage`（`zly-storage-capability`）并作为 `initialData`；`localDirectoryRequired` 在有能力数据（实时或缓存）时只信 `requires_local_directory`，仅当完全没有任何能力数据且查询失败时才保守回退为需要（默认 browser-stream 场景）。后端 `/api/storage` 契约不变：七牛云持久存储 `false`，本地暂存/流式交付 `true`。
- 受影响文件：`frontend/src/App.tsx`、`README.md`、`功能说明与扩展指南.md`。
- 兼容性：无 API / 数据 / 后端变化；未启用七牛云的部署仍按原逻辑弹目录授权；缓存只影响瞬时错误时的兜底判断，接口成功后立即覆盖。
- 验证命令：`pnpm --dir frontend build`（vitest 54 项通过）。
- 回滚方式：还原 `App.tsx` 本次改动即可。

## 2026-09-14 澄清待答不再锁定「创作模式」切换（修复手动模式切不回 AI 生成）

- 变更原因：创作模式切换的禁用条件原为 `planPipelineRunning || clarifyActive`（`DirectorRecipeStudio.tsx`）。澄清问题卡会持久化在工程级 localStorage（`director-clarify:<projectId>`），用户拿到问题后未作答就离开（关页、切走、或另一标签页触发澄清）时该残留长期存在；而澄清卡只在剧本对话室渲染，其余阶段既看不到卡片也得不到任何提示，模式开关却被整体 disabled，表现为「手动编辑模式下点任意步骤后切不回 AI 生成」。同一条件还牵连 `scriptManualActive`，使手动模式下的剧本阶段漏出 AI 对话室，违背 3.0 节「手动模式隐藏 Prompt Bar/澄清卡」的承诺。
- 当前基线：`creationModeLocked` 仅由 `planPipelineRunning`（流水线进行中，含 `plan_pipeline`/`plan_clarify` 活动操作恢复）驱动，流式进度与「取消生成」入口仍可见，符合原锁定意图；澄清问题待答不再影响开关可用性与 `scriptManualActive`。未答问题卡继续保留在 localStorage，切回 AI 生成后在剧本对话室仍可见、可作答或跳过；新一轮生成（`handleRun`/`continueGuidedFlow`）沿用既有「丢弃旧卡」逻辑，不会出现新旧卡片叠答。同时 `setCreationMode` 在切换时用 antd message 即时反馈（「已切换到手动编辑，可直接编写各环节内容」/「已切换到 AI 生成，可继续用 AI 打磨各环节」）：画风等阶段两种模式界面几乎一致，无提示时用户会误以为切换无效（实测同一工程画风页两种模式按钮完全相同）。
- 受影响文件：`frontend/src/director/DirectorRecipeStudio.tsx`（锁定条件与切换反馈）、`docs/导演台流程与界面结构.md`（§3.0）、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：纯前端交互条件变化，无 API/数据库/存储格式变更；流水线运行中的锁定行为与旧版一致；残留澄清卡的清理解析不变。回滚仅还原该行表达式即可。
- 验证命令：`pnpm --dir frontend test`、`pnpm --dir frontend build`、`python -m unittest discover -s backend/tests -p 'test_*.py'`；浏览器实测：注入 `director-clarify:<projectId>` 待答状态后，手动模式在各阶段点击「AI 生成」立即生效（桌面 1280 + 移动 390），剧本阶段显示手动编辑器而非对话室；无残留状态时各阶段「点步骤 → 切模式」回归正常。
- 回滚方式：还原 `DirectorRecipeStudio.tsx` 中 `creationModeLocked` 表达式与四份文档对应段落，无数据迁移。

## 2026-09-14 接入 MiniMax H3 Director 加速版

- 原因：新增 MiniMaxH3Director 节点结合双 Sage 优化的工作流（单镜自动路由 T2V/I2V/R2V），提升出片速度。
- 当前基线：\ackend/app/models.py\ 新增 \JobMode\ 包含 \minimax-h3-director-accel-t2v\, \i2v\, 2v\。\workflow_registry.py\ 新增 \CATALOG_GROUP_DIRECTOR_ACCEL\，参数层级对齐加速版特性（无 Turbo LoRA，双 Sage，默认 0.4MP/20步/pruned）。\minimax_h3_director_accel_workflow.py\ 提供构建器，支持 0-9 张参考图并使用外部 Group 接线给 Director 节点，最后输出到 SaveVideo。
- 前端：\rontend/src/director/director-workflows.ts\ 的 \FALLBACK_DIRECTOR_WORKFLOW_FAMILIES\ 增加 \h3_director_accel\ 降级配置，使其在 API 未就绪时显示下拉项。
- 测试：\ackend/tests/test_minimax_h3_director_accel.py\ 新增 builder 和注册表的单测。\	est_director_controls.py\ 补充对该模式的界面控制测试。
- 兼容性：新增流程，向前兼容；工作台需要连接已安装 ComfyUI_MiniMaxH3_Director 的实例。

## 2026-09-14 夏姬模块下线，导演台2（AI Media Studio）整体替代

- 变更原因：旧 xiaji（夏姬）前后端模块整体退役，由复刻自 dev0914 终态的「导演台2 / AI Media Studio」替代：后端 `media_studio` 模块 + 前端 `director2` 应用。
- 当前基线：后端删除 `backend/app/xiaji_*.py`（analyze/api/art_style/asset_api/asset_prompts/asset_store/auto_pipeline/compose/episode_api/episode_prompts/episode_run_store/episode_store/literal_script/llm_jobs/parser/project_api/project_store/store/visual_styles，共 19 个文件）；新增 `backend/app/media_studio/`（`db.py` 启动重放建表、`models.py`、`provider_bridge.py`、`routers/`、`services/`）。`main.py` 移除全部 xiaji store 与路由装配，改为 `media_studio.routers.project_router.register_project_routes`，并接入 `EpisodeVideoService` / `StoryboardImageService`（启动时恢复孤儿与中断任务）；`llm_provider.py` 移除 xiaji ingest 分析方法。数据库新增 `sql/013_media_studio_init.sql`：`ai_projects` / `ai_project_documents` / `ai_project_assets` 等 5 张 `ai_*` 表（索引内联建表、每次启动重放、禁止 ALTER），与旧 `xiaji_*` 表并存。前端删除 `frontend/src/xiaji/`（9 个文件）与 `index.css` 中约 2600 行 xiaji 样式；新增 `frontend/src/director2/`：`Director2App` / `Director2Home` / `Director2ProjectDetail`，panes（内容库 / 资产库 / 剧集工坊 / 任务中心，各 pane 独立 CSS）与 settings（LLM / GRS / Comfy / 七牛存储）；路由重构为 `/director2/projects/:projectId/:menu`、`/director2/projects/:projectId/workshop/:episodeId`、`/director2/settings`，`App.tsx` 以 lazy `Director2App` 装配（workspaceView `director2`）；`ArtStylePicker` 样式类由 `xiaji-art-style-*` 更名 `director-art-style-*`（行为不变）。
- 受影响文件：`backend/app/{main,llm_provider}.py`、`backend/app/media_studio/**`、`backend/app/xiaji_*.py`（删除）、`backend/tests/media_studio_test_*.py`（新增 3 个）、`sql/013_media_studio_init.sql`（新增）、`frontend/src/{App.tsx,index.css,paths.ts,router.tsx}`、`frontend/src/director/ArtStylePicker.tsx`、`frontend/src/director2/**`（新增）、`frontend/src/xiaji/`（删除）。
- 兼容性：`sql/001-012` 与既有 `xiaji_*` 数据表保留、不迁移不删除；旧 xiaji HTTP API 与 `/director2/art-styles`、`/director2/:projectId` 旧链接不再可用（导演台2 改用新路由结构，无重定向）；`__pycache__` 已在 `.gitignore` 中。
- 验证：`python -m unittest backend.tests.media_studio_test_character_content backend.tests.media_studio_test_h3_video backend.tests.media_studio_test_storyboard_images`、`pnpm --dir frontend build`。
- 回滚方式：还原本提交即恢复 xiaji 模块、旧路由与旧样式；`ai_*` 新表与旧表并存，无需数据回滚。

## 2026-09-15 移除导演台2内置设置页

- 变更原因：导演台2顶栏的设置入口及其独立页面与现有管理后台重复，且该页面源自 dev0914 复刻分支。
- 变更内容：删除 `frontend/src/director2/` 顶栏「设置」按钮、`/director2/settings` 路由解析与全局路由注册，并移除 director2 专用设置页及 LLM / GRS / Comfy / 七牛配置卡组件；配置统一使用 `/admin/accounts` 及管理员配置页。
- 受影响文件：`frontend/src/director2/Director2App.tsx`、`frontend/src/director2/paths.ts`、`frontend/src/director2/director2.css`、`frontend/src/paths.ts`、`frontend/src/director2/settings/**`（删除）。
- 兼容性：无 API、数据库或工作流协议变化；直接访问旧 `/director2/settings` 地址不再进入导演台2设置页，现有项目路由不受影响。
- 验证命令：`pnpm --dir frontend build`；浏览器打开 `/director2/projects/:projectId/content` 确认顶栏无设置按钮。
- 回滚方式：恢复上述前端文件及 `frontend/src/director2/settings/` 目录即可；无数据回滚。

## 2026-09-15 导演台2多集分镜直播流水线

- 变更原因：原 AI 生成仅产出单集，分镜直播把场景与镜头平铺，且阶段消息无法传递到前端。
- 当前基线：澄清题新增 `episode_count`；剧本按 `# 第N集 标题` 分节；分镜 agent 按集生成并在每集内完成“写分镜→按秒分配→校验衔接”打磨。SSE `agent_delta` / `agent_item` 新增可选 `episode`，`status` 携带阶段 `message`；`ai_project_episodes` 按集落库。
- 前端 `Director2AiStudioPane` 使用共享 `DirectorStoryboardLiveBody` 与 `storyboard-stream-view`，按集→场景→镜头分组渲染，支持当前镜头打字机、打磨字幕和阶段摘要；旧导演台 `parseStoryboardPhase` 保持 re-export 兼容。
- 受影响文件：`backend/app/{llm_minimax_skills.py,director_agents.py,director_stream.py,director_recipe.py,media_studio/services/ai_generation_service.py}`、`frontend/src/director/{director-operation-stream.ts,storyboard-stream-view.ts,components/DirectorStoryboardLiveBody.tsx,components/DirectorScriptStreamPanel.tsx}`、`frontend/src/director2/panes/Director2AiStudioPane.tsx` 及对应测试。
- 兼容性：默认 1 集时行为与旧流程一致；SSE 新字段为可选，旧客户端可忽略；不改变节点 ID、端口、数据库结构或工作流协议。
- 验证命令：`python -m unittest backend.tests.test_director_stream backend.tests.test_director2_ai_generation`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码与文档即可；无需数据迁移或资源清理。

## 2026-09-15 导演台2分镜等待态与阶段文案持久化

- 变更原因：分镜阶段要连续等待远端 LLM，轮询会丢掉 `result.message`，页头又优先展示进程重启残留的 `error_message`，直播卡在镜头出现前是空的，看起来像卡死。
- 当前基线：`on_progress` 把运行中 agent 文案写入 `result.message`；仅在 `completed_stages` 增长时调用 `_adapt_recipe`；分镜切入不再覆盖「正在读剧本并构思」；`status=running` 时清掉残留 `error_message`。前端页头忽略进行中任务的 error，轮询同步阶段文案；空分镜显示等待骨架，`parseStoryboardPhase` 识别带集前缀的读剧本 / 写分镜文案。
- 受影响文件：`backend/app/media_studio/services/ai_generation_service.py`、`frontend/src/director2/panes/Director2AiStudioPane.tsx`、`frontend/src/director2/director2-ai-operation-state.ts`、`frontend/src/director/storyboard-stream-view.ts`、`frontend/src/director/components/DirectorStoryboardLiveBody.tsx` 及对应测试。
- 兼容性：GET 仍返回既有 `result.message` 字段；不改表结构、端口或工作流协议。
- 验证命令：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend test`。
- 回滚方式：还原上述文件即可。

## 2026-09-15 导演台2双层 Timeline 渲染架构

- 变更原因：导演台2需要同时支持单镜快速重试、整集一次提交，以及超过 H3 安全长度的长集稳定出片。
- 当前基线：`timeline_rendering.py` 定义统一的 `renderScope=shot|episode` 请求和分段规划；单镜与整集都由 `ComfyVideoClient` 生成同一份 `timeline_data`。H3 Director 加速版注册表声明 `supports_timeline`、`supports_multi_segment`、`max_segments=6`、`max_total_frames=1152`、连续性与音频批处理能力。
- 调度行为：6 个 8 秒镜头以内一次提交；超过能力上限按镜头边界分段，在同一 ComfyUI 实例串行执行，全部成功后由 ffmpeg concat 合成并上传七牛。分段状态、时间码和每个 Beat 的 `segmentIndex/renderStatus/outputStart/outputDuration/promptSnapshot` 保存在任务 payload 中；重试时保留已成功分段。
- API：新增 `POST /api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-video`；整集接口保持不变。导演台2默认改为 `minimax-h3-director-accel-r2v`，旧 `/director` 单镜行为不变。
- 兼容性：旧任务 payload 可继续查看；不改 ComfyUI 节点 ID、数据库表结构和旧接口字段。七牛未配置时，单镜仍可返回 ComfyUI 预览，分段整集合成会明确失败并保留已完成分段，待配置存储后重试。
- 验证命令：`python -m unittest backend.tests.test_timeline_rendering backend.tests.media_studio_test_h3_video.ComfyWorkflowTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复 `timeline_rendering.py`、视频服务、Comfy 客户端、注册表、路由和导演台2 API/面板改动即可；无需数据迁移。

## 2026-09-15 导演台2 AI 资产回写内容库

- 变更原因：AI 生成模式抽屉能看到角色/场景/道具，但适配层只把剧本文本解析进内容库；人物设定不在剧本文本里，且资产完成时 `current_stage` 会回落到 `script`，导致内容库识别人物/场景/道具为空。
- 当前基线：`_recipe_text` 把 recipe 角色、场景写成内容库可解析的 Markdown；`_adapt_recipe` 把 recipe 资产合并进 `analysis_json`，只要有具名资产就写入 `ai_project_assets`；内容库读取 AI 文档时若分析缺资产，会从最近一次 `ai_pipeline` 任务的 recipe 回填。
- 受影响文件：`backend/app/media_studio/services/ai_generation_service.py`、`backend/app/media_studio/services/project_detail_service.py`、`backend/app/media_studio/services/script_parser.py`、`backend/tests/test_standard_script_parser.py`。
- 兼容性：不改表结构、端口或 SSE 协议；手动导入的内容库文档不受影响。
- 验证命令：`python -m unittest backend.tests.test_standard_script_parser backend.tests.test_director2_ai_generation`。
- 回滚方式：还原上述文件即可。

## 2026-09-15 导演台2创意确认改为集数题

- 变更原因：剧本已经按“分集 → 分镜”组织，导演台2不应再要求用户预估整部剧的 Beat 数量。
- 当前基线：导演台2澄清请求携带 `surface=director2`，只生成 `episode_count` 固定题；旧 `/director` 保留原镜头数量兼容行为。导演台2旧任务读取时会过滤遗留的 `beat_count`，没有集数题时自动补上 `episode_count`。
- 受影响文件：`backend/app/llm_minimax_skills.py`、`backend/app/llm_provider.py`、`backend/app/media_studio/services/ai_generation_service.py`、`frontend/src/director2/panes/Director2AiStudioPane.tsx`、相关测试。
- 兼容性：不改数据库结构；旧任务 payload 无需迁移即可在读取时修正。大模型后续按剧本和集数自动拆分每集 Beat 数量。
- 验证命令：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件即可，旧任务数据不受影响。

## 2026-09-15 导演台2分镜打磨芯片按集分组

- 变更原因：多集剧本进入「按秒分配对白与动作」后，直播卡把全剧镜头平铺成一排无标签序号（例如 1–26）。用户会误以为是集数、秒数或当前集镜数；`(1/3)` 实际是本集打磨批次，也容易看成「第 1 集 / 共 3 集」。
- 当前基线：`parseStoryboardPhase` 保留集号；芯片上方写明「全剧 N 集 · 共 M 镜 · 当前第 X 集」；多集时按集分行；标题把 `(i/N)` 改成「第 i/N 批」。当前镜号优先用消息里的「正在第 N 镜」，缺失时用本批起点 + 流式序号，不再把 tracker ordinal 直接当成镜号。
- 受影响文件：`frontend/src/director/storyboard-stream-view.ts`、`frontend/src/director/components/DirectorStoryboardLiveBody.tsx`、`frontend/src/director/guided-flow.css`、对应测试与三份主文档。
- 兼容性：纯前端展示；单集仍是一排芯片，只多「共 M 镜」说明。不改 API、库表或工作流。
- 验证命令：`pnpm --dir frontend test`。
- 回滚方式：还原上述前端与文档文件即可。
## 2026-09-15 导演台2失败阶段可幂等重试并保留快照

- 变更原因：失败态按钮在重复点击或 SSE/轮询尚未同步时会误报“只有失败或已取消的 AI 任务可以重试”；刷新后抽屉也无法继续查看已生成的部分内容。
- 当前基线：`AiGenerationService.retry` 对 queued/running/clarifying 请求直接返回同一操作，不重复启动 worker；失败/取消时记录 `result.failed_stage`，重试优先从该阶段继续并复用 payload 中已有 Recipe。终态 GET 在 `result.recipe` 返回保存的 Recipe 快照，前端抽屉在无流式缓存时回显角色、场景、道具、分集与镜头。
- 受影响文件：`backend/app/media_studio/services/ai_generation_service.py`、`backend/tests/test_director2_ai_generation.py`、`frontend/src/director2/api.ts`、`frontend/src/director2/panes/Director2AiStudioPane.tsx`、`frontend/src/director/storyboard-stream-view.ts`。
- 兼容性：不改数据库表、端口、SSE 事件或工作流协议；旧任务没有 Recipe 快照时仍可通过内容库/剧集工坊查看已回写数据。
- 验证命令：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend build`，并在 `http://127.0.0.1:5173` 导演台2终态页面检查按钮 loading 与抽屉回显。
- 回滚方式：还原上述文件即可，无需数据迁移。

## 2026-09-16 导演台2 AI 逐步卡点状态机

- 变更原因：原先 `clarify` 后一次性跑完 `script → assets → episodes → storyboard`，中途只能取消；用户无法按阶段确认，也不可能只按反馈重跑当前步。
- 当前基线：`AiGenerationService` 把 pipeline 改成逐 leg 状态机。`STAGES = script / assets / episodes / storyboard`，`STAGE_AGENTS` 分别为 `[script]`、`[characters, locations]`、`[episodes]`、`[storyboard]`。`_run_stage_leg` 跑完写 `awaiting_stage`、`status=awaiting_review`，发非终态 `status` 事件。`advance` 校验待确认后把当前步加入 `completed_stages` 并启动下一 leg，无下一 stage 则 `succeeded`。`revise` 对当前 stage 调 `run_director_clarify(agent=<stage>, feedback=…)` 进入 `revising`；`rerun_stage` 把 clarifications+feedback 并入 `stage_clarifications` 后只重跑当前 agents。因为每步前暂停，重跑时下游尚未生成。`ACTIVE` 不含 `awaiting_review`（无 worker），`OCCUPYING` 含待确认与调整中；`create` 的判重 SQL 与 `get_active` 使用占用集合。`recover_orphaned_jobs` 仍只收敛 `queued/running/clarifying/revising`，不把用户正在审核的任务标失败。导演台 `run_agent("episodes")` 写入结构化 `recipe["episodes"]`，分镜优先消费该大纲。路由新增 `POST …/advance`、`…/revise`、`…/rerun`。前端 `DIRECTOR2_ACTIVE_AI_STATUSES` 不含 `awaiting_review`，左侧 rail 把 `awaiting_stage` 标为「待确认」。
- 受影响文件：`backend/app/media_studio/services/ai_generation_service.py`、`backend/app/media_studio/routers/project_router.py`、`backend/app/director_agents.py`、`backend/app/llm_minimax_skills.py`、`backend/app/llm_provider.py`、`backend/tests/test_director2_ai_generation.py`、`frontend/src/director2/{api.ts,director2-ai-operation-state.ts,director2-ai-operation-state.test.ts,panes/Director2AiStudioPane.tsx}`、`frontend/src/director/components/{DirectorLiveStepFeed.tsx,DirectorTaskRows.tsx,DirectorPromptBar.tsx}`、`docs/导演台流程与界面结构.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：operation 仍写入 `ai_project_jobs`（`job_type=ai_pipeline`），无数据库迁移。旧一次性 pipeline 客户端收不到 terminal 就会停在第一步待确认，需使用本版前端的采纳/调整接口。`awaiting_review` / `revising` GET 回传 Recipe 快照供确认卡展示。导演台九环节 Recipe 存储不变。
- 验证命令：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend test`、`pnpm --dir frontend build`；5173 浅色/暗色与移动宽度自查确认卡、澄清卡与只重跑当前步。
- 回滚方式：还原上述前后端与文档文件即可；无需数据迁移。待确认中的历史任务回滚后可能停在 `awaiting_review`，需取消或按旧逻辑重试本阶段。

## 2026-09-16 导演台资产库原片参考图

- 变更原因：资产库角色/场景/道具生图只吃文字提示词，没有原片截图上传位，生成形象对不上原剧。
- 当前基线：`extra.source_references` 保存最多 9 张七牛图；`POST/DELETE /api/projects/{project_id}/assets/{asset_id}/references` 上传删除。`generate_asset_image` 对 `avatar` / `identity` / `scene_master` / `prop_reference` / `asset` 把原片图排在 GRS `images` 最前并追加 SOURCE PHOTO REFERENCES 提示；`scene_reverse` / `scene_pano` / `prop_turnaround` / `prop_detail` 仍只跟已生成主图。无参考图时行为与改前相同。
- 受影响文件：`backend/app/media_studio/services/asset_source_references.py`、`project_detail_service.py`、`project_router.py`、`frontend/src/director2/asset-source-references.ts`、`api.ts`、`panes/AssetsLibraryPane.tsx`、`panes/assets/{AssetSourceReferenceStrip,CharacterWorkspace,SceneWorkspace,PropWorkspace}.tsx`、`assets-library.css`、对应测试与三份主文档。
- 兼容性：不改表结构、端口或 GRS 协议；旧客户端不上传则纯文生图。
- 验证命令：`python -m unittest backend.tests.test_asset_source_references`、`pnpm --dir frontend test`；5173 资产库上传条与浅/暗主题。
- 回滚方式：还原上述文件即可。

## 2026-09-16 分镜直播卡集层 Task Rows 手风琴

- 变更原因：多集分镜直播把各集镜头平铺，当前集容易被顶出视口；完成镜头也不能点开回看描述/对白。
- 当前基线：`DirectorStoryboardLiveBody` 以「集」为父行胶囊（运行中展开、完成后收起、可回看）；写分镜子行仍是 `.director-shot-stream-row`。打磨阶段同样按集折叠，每个胶囊只显示这一集的镜头芯片（本集 1…N），不把全剧镜号铺进同一集。不改 SSE/API。行内手风琴不用于剧本直播卡、资产摘要卡、分集大纲卡、左侧任务栏 rail、阶段外层 `DirectorLiveBlock` / 已完成步骤行。
- 受影响文件：`frontend/src/director/components/DirectorStoryboardLiveBody.tsx`、`frontend/src/director/storyboard-stream-view.ts`、`frontend/src/director/guided-flow.css`、`frontend/src/director2/panes/Director2AiStudioPane.tsx`、对应测试与三份主文档。
- 兼容性：纯前端展示；单集同样走胶囊，不必硬造第二集。
- 验证命令：`pnpm --dir frontend test`；5173 多集工程看直播与确认卡。
- 回滚方式：还原上述前端与文档文件即可。

## 2026-09-16 导演台2创意确认增加每集镜头数

- 变更原因：导演台2 创意确认只问集数，每集镜头数由模型自行估算，单集体量不稳定。
- 当前基线：`surface=director2` 时固定追加 `shots_per_episode`（「每一集默认拍多少个镜头？」），档位 4/6/8/12，推荐 6。剧本 Agent 按每集默认镜数约束 `### 镜头`；分集 Agent 把缺省 `targetShots` 填成该值；分镜继续消费集大纲目标镜数。旧 `/director` 仍用全剧 `beat_count`，不出现本题。读取旧澄清任务时过滤遗留 `beat_count`，并补齐 `episode_count` 与 `shots_per_episode`。
- 受影响文件：`backend/app/{llm_minimax_skills.py,llm_provider.py,director_agents.py,models.py,media_studio/services/ai_generation_service.py}`、`backend/tests/{test_director_clarify.py,test_director2_ai_generation.py,test_director.py}`、三份主文档。
- 兼容性：不改表结构、端口或工作流协议；未答本题时分集仍可自行估算镜数。
- 验证命令：`python -m unittest backend.tests.test_director_clarify backend.tests.test_director2_ai_generation backend.tests.test_director.EpisodesAgentTests`。
- 回滚方式：还原上述文件即可。

## 2026-09-16 导演台2可单独重试已完成阶段

- 变更原因：取消或失败后只能「从当前阶段重试」，已完成的更早阶段（创意确认 / 剧本等）无法单独重跑。
- 当前基线：`POST …/ai/operations/{id}/retry` 可带 `{stage}`。`failed` / `cancelled` / `awaiting_review` / `succeeded` 均可指定已完成阶段；该阶段之后从 `completed_stages` 作废，recipe 后续字段清空，跑完停在 `awaiting_review`。无 `stage` 时仍只续跑当前失败/取消步。`stage=clarify` 在同一条 pipeline 上重开场问题（`revising`），答完 `rerun` 从剧本开跑。左侧任务栏与记录流已完成行 hover「重新生成」；有 pipeline 任务时完成态以任务记录为准，不再和内容库存量并集。
- 受影响文件：`backend/app/media_studio/services/ai_generation_service.py`、`routers/project_router.py`、`backend/app/api_documentation.py`、`backend/tests/test_director2_ai_generation.py`、`frontend/src/director2/{api.ts,director2-ai-operation-state.ts,director2-ai-operation-state.test.ts,panes/Director2AiStudioPane.tsx}`、三份主文档。
- 兼容性：不改表结构；旧客户端不传 `stage` 行为与改前相同。库表已写入内容等该步再次跑完后由 `_adapt_recipe` 覆盖，不立即删除。
- 验证命令：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend test`。
- 回滚方式：还原上述文件即可。

## 2026-09-16 导演台2取消后重试会清掉取消标记

- 变更原因：取消落为 `cancelled` 后 `cancel_requested` 仍为 true；`_update` 无条件锁住该标记，重试入队后新 worker 立刻再次取消。
- 当前基线：仅当当前状态与写入后状态都仍是活跃 worker（queued/running/clarifying/revising）时才锁住取消标记。从 `cancelled`/`failed`/`awaiting_review`/`succeeded` 入队允许清掉。页头「正在停止当前生成」只在任务仍进行中时显示。
- 受影响文件：`backend/app/media_studio/services/ai_generation_service.py`、`backend/tests/test_director2_ai_generation.py`、`frontend/src/director2/director2-ai-operation-state.ts`、对应测试与三份主文档。
- 兼容性：无表结构或接口变化；取消进行中的 worker 仍不能用旧快照清掉标记。
- 验证命令：`python -m unittest backend.tests.test_director2_ai_generation`、`pnpm --dir frontend test`。
- 回滚方式：还原上述文件即可。

## 2026-09-20 服务器启动补建导演台2 表，DATA_DIR 不再改走 SQLite

- 变更原因：`deploy-server-image.sh` 健康检查失败，容器反复退出，日志 `pymysql.err.ProgrammingError: (1146, "Table 'ai-media.ai_project_jobs' doesn't exist")`，栈在 `EpisodeVideoService.recover_orphaned_jobs()`。
- 当前基线：Compose 的 `ZLY_AI_VIDEO_STUDIO_DATA_DIR` 只用于上传/暂存/凭证/SQLite 迁移源，不再把生产后端切到 SQLite。`ZLY_AI_VIDEO_STUDIO_DB_BACKEND` 默认 `mysql`，unittest 仍隔离 SQLite。`media_studio.db.ensure_schema()` 在首次 MySQL 连接和 FastAPI lifespan（恢复孤儿任务之前）重放 `sql/*.sql`，含 `ai_project_jobs` 等 `ai_*` 表。
- 受影响文件：`backend/app/config.py`、`backend/app/db.py`、`backend/app/media_studio/db.py`、`backend/app/main.py`、`compose.yaml`、`.env.example`、`backend/tests/test_media_studio_schema.py` 与三份主文档。
- 兼容性：已有 `ai-media` 库用 `CREATE TABLE IF NOT EXISTS` 补表，不改既有行。旧 Docker 卷里的 SQLite 仍可由 `deploy-server-image.sh` 的迁移步骤导入 MySQL。
- 验证命令：`python -m unittest backend.tests.test_media_studio_schema`。
- 回滚方式：还原上述文件并重新导出镜像；缺表时也可对目标库手动执行 `sql/013_media_studio_init.sql`。

2026-10-20 模型格式兼容：实际可选模型可能返回`<tool_call>`及成对`param_key/param_value`标签；后端仅接受完整、有界的工具块，规范化后仍通过同一工具/参数白名单校验，拒绝未知工具、跨目标参数、声明实体及块外正文，不跳过用户确认。JSON协议继续兼容。

2026-10-20 验收结果：前端52个测试文件、270项测试及类型检查/构建通过；助手与剪辑后端专项67项通过，其中新增铺轨专项14项。完整后端789项保留既有2失败（OpenAPI旧标签、剧本场景账本大小写）与1导入错误（已下线xiaji_api），不标为全量通过。真实5173在1440×900与1920×1080浅暗主题无横向溢出或右栏遮挡，截图46–52已归档。按钮实测清单取消不写入、确认追加保存、整次撤销/重做、刷新和重复跳过；实际可选Qwen/Qwen3-8B完成自然语言editor_read→propose_edit→同一授权弹窗→保存。并发改版本返回409且无部分写入，重新预览可执行，旧待授权记录不再在新动作完成后重复弹出。验收未提交视频生成或导出任务。

本次验收临时账号、工程、助手记录及2个上传云端视频均已按ID核对后清理；46–52桌面基线已归档。本地临时目录的批量清理及明确列出的4个认证/媒体文件删除均被自动审批以blocked by policy拒绝，未执行删除；临时文件和验证报告保留在Git忽略的test-results/editing-assistant。

## 2026-10-22 官方 H3 二采精修替代出片后 2x 超分

- 变更原因：官方 H3 的「出片后 2x 超分」只做后处理放大，对生成细节没有提升；用户实测有效的做法是 0.4 MP 精简权重一采 → H3 3D latent 放大 → 3 步 beta denoise 0.2 二采。把该配方产品化为「二采精修」，官方 T2V/I2V/R2V 不再暴露 `upscale_after`；LightX2V、八步双加速、Director 加速和 T8 继续保留 RTX 2x 超分。
- 当前基线：`workflow_registry.py` 的官方 H3 schema 新增 `refine_enabled`（primary 布尔，默认关，创建栏与导演台弹层直接显示）与 `refine_quality`（primary 枚举 `1.0` / `2.0`，默认 `1.0`，仅开启时显示）。开启后 `normalize_options` 强制一采为 0.4 MP、`pruned`、8 步、`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` 强度 1.0，并忽略传入的 `quality` / `weight_profile` / `speed` / `upscale_after`；`quality`、`weight_profile`、`speed`、`custom_steps` 通过 `ui_visible_when` 隐藏。`comfy_service` 在官方模式且 `refine_enabled` 时改用新增的 `backend/app/minimax_h3_refine_workflow.py`。
- Graph 结构：一采为 `MiniMaxH3Director` + 对应 Group（R2V 用 `MiniMaxH3DirectorGroupReferenceToVideo`，其余用 `MiniMaxH3DirectorGroupImageToVideo`），节点 1 pruned FL2VA → 15 八步 LoRA → 18 `ReservedVRAMSetter`（3 GB）→ 16/17 Sage；二采节点 40（R2V 用 `ExperimentalW4A8UNETLoader` + `minimax_h3_ref2va_pruned_w4a8_mixed`，其余用 `UNETLoader` + pruned FL2VA）→ 41 四步 LoRA → 42/43 Sage → 44 `BasicScheduler`（beta / 3 步 / denoise 0.2）→ 45 `MiniMaxH3DirectorRefine`（`mode=upscale`、`upscale_method=h3_latent`、`minimax_h3_latent_upscaler_3d_bf16`、euler、passes 1、seed 继承、`aspect_ratio=跟随导演台`、`skip_fl2v` 仅非首尾帧为 true）。`CreateVideo` 13 → `SaveVideo` 14 保持下载节点不变；帧数超过 60 时开启 latent chunking，不启用 tiling。
- 兼容性：不新增表字段、端口或 API 路由。旧任务 options 缺 `refine_enabled` 时按默认关处理；缺 `refine_quality` 时按当前 schema 默认 `1.0` 回显，API 客户端省略该字段也会得到 1.0 MP 二采（此前默认 2.0）。`main.py` 的有效参数快照在判断 `ui_visible_when` 时回落到 schema 默认值，因此旧任务仍会回显 `quality` / `speed`。API 仍接受官方 H3 传入 `upscale_after`（`H3_OPTION_NAMES` 保留），但界面不再展示；开启二采时该字段被强制为 false。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_refine_workflow.py`（新增）、`backend/app/comfy_service.py`、`backend/app/main.py`、`backend/tests/test_h3_refine.py`（新增）、`backend/tests/test_rtx_vsr.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx`、`README.md`、`功能说明与扩展指南.md` 和本文档。
- 验证命令：`python -m unittest backend.tests.test_h3_refine backend.tests.test_rtx_vsr backend.tests.test_core backend.tests.test_h3_coverage backend.tests.test_director_workflow_speed`、`pnpm --dir frontend test`、`pnpm --dir frontend build`。
- 远端验收（2026-10-22，用户确认地址 `http://192.168.10.54:8188`，`.env` 已同步）：I2V、5 秒、2.0 MP、seed `5359709363136135826` 跑通两段式。远端节点与模型齐全；一采 8 步 54 秒，latent 放大 864×480 → 1952×1088 约 34 秒，二采 3 步采样约 48.5 分钟（三步步进波动大，总耗时约 52 分钟，RTX 4080 16 GB）。产物 1952×1088、124 帧、24 fps、带 AAC 音频、5.167 秒；抽帧检查主体一致、运镜稳定、霓虹文字清晰，未见明显接缝或崩坏。2.0 MP 的实际画布由 `aspect_ratio=跟随导演台` 按一采 864×480 比例计算为 1952×1088（UI 标签写 16:9 约 1920×1088）。二采耗时远高于旧文案的“约两倍”，用户可见说明已改为“5 秒 2.0 MP 在 16 GB 显卡上约 50 分钟”。若后续需要缩短耗时，再评估 1.0 MP 或开启 spatial tiling；本轮未改动已验证的采样参数。
- 1.0 MP 对比（2026-10-23，同一首帧、提示词与 seed `5359709363136135826`）：1.0 MP 任务（prompt `a61d0750-ddbd-41ce-bb3a-f0b6862b59a7`）总耗时 215.5 秒（约 3 分 36 秒），产物 1376×768、124 帧、24 fps、AAC、5.167 秒、1.88 MB；2.0 MP 任务（prompt `93f92dfe-f045-412a-b1ec-ad22b470774b`）总耗时 3126.9 秒（约 52 分 7 秒），产物 1952×1088、3.18 MB。将 2.0 MP 缩到 1376×768 与 1.0 MP 原生逐帧对比：构图、色彩、运镜一致；2.0 MP 在雨丝、湿发和霓虹边缘略多微细节，1.0 MP 更平滑，正常观看尺寸下差异很小。耗时相差约 14.5 倍而观感接近，判断 2.0 MP 在 16 GB 显存上已受显存压力影响。按该结论，`refine_quality` 默认值已由 `2.0` 改为 `1.0`（2026-10-23），2.0 MP 仍可手动选择；如后续确需 2.0 MP 的额外细节，再评估开启 `enable_tiling`（2 tiles、overlap 128）。已验证的采样参数未改动。
- 验收产物：远端 `output/video/ZLY_AI_VIDEO_STUDIO_MiniMax_H3_Refine_00001_.mp4`（2.0 MP）与 `..._00002_.mp4`（1.0 MP）；本地副本、抽帧与 `compare_full.png` / `compare_face.png` 位于已忽略的 `.tmp/acceptance/`，确认后可清理。
- 回滚方式：恢复上述文件并重启后端、重建前端；已提交任务不受影响。

## 2026-10-23 二采精修扩展到全部 H3 工作流

- 变更原因：2026-10-22 只在官方 H3 上线了「二采精修」，LightX2V、八步双加速、H3 Director 加速版和 T8 仍保留无效的「出片后 2x 超分」。用户要求所有 H3 工作流统一替换为二采，并让每个工作流用自己更快的一采设置生成首段，以缩短两段式总耗时。
- 当前基线：`H3_STANDARD_OPTION_SCHEMA` 及 LightX2V / 八步双加速 / Director 加速 / T8 的专属 schema 全部提供 `refine_enabled`（primary 布尔，默认关）与 `refine_quality`（primary 枚举 `1.0` / `2.0`，默认 `1.0`，仅在开启时显示）；所有 H3 schema 删除 `upscale_after`。`normalize_options` 对全部 H3 工作流先丢弃旧客户端或旧草稿里的 `upscale_after`，开启二采时统一把一采 `quality` 固定为 `0.4`、`megapixels` 固定为 `0.4`，并保留各工作流自己的步数、采样器、模型体积、LoRA 与 Sage 设置。分辨率选项通过 `ui_visible_when={"refine_enabled": false}` 隐藏，二采画质只在开启后出现。
- 调度：`comfy_service` 在 `refine_enabled` 时统一调用 `build_minimax_h3_refine_workflow`，否则按原工作流族分派；导演台2 逐镜 / 选中镜经 `ComfyVideoClient.build_shot_workflow` 走同一入口；整集直出与时间线合成经 `ComfyVideoClient.build_workflow` 在原有 Director 时间线图（节点 12）上追加 `build_refine_nodes` 生成的 40–45 节点，并把节点 12 的 `refine` 连接到 45。
- 一采按工作流族保留各自速度特征：官方 H3 固定 8 步、pruned FL2VA/REF2VA、8 步 LoRA 强度 1.0、`ReservedVRAMSetter` 3 GB 与双 Sage；LightX2V 沿用当前 speed（默认快速 4 步）选择 4/8 步 LoRA（强度 0.75）和 euler，LoRA 开启时用完整 INT8，仅挂 H3 显存高效 Sage；八步双加速沿用 8 / 20 / 自定义步数与 8 步 LoRA 强度 1.0，full INT8 + 双 Sage；Director 加速沿用 20 / 25 步、`director_accel_unet` 的完整/精简体积、cfg 与双 Sage，不挂 LoRA；T8 一采改用 Director 管线并沿用 `video_steps`（多速率）或 `steps`（双时钟）、完整 INT8 + T8 Turbo LoRA、`res_multistep` 与 H3 Sage，但 T8 专有采样器与音频模式不参与二采（界面与文档已注明）。
- 二采图与官方 H3 一致：节点 40 加载 pruned FL2VA（R2V 用 `minimax_h3_ref2va_pruned_w4a8_mixed`）→ 41 四步 LoRA → 42/43 Sage → 44 `BasicScheduler`（beta / 3 步 / denoise 0.2）→ 45 `MiniMaxH3DirectorRefine`（`mode=upscale`、`upscale_method=h3_latent`、`minimax_h3_latent_upscaler_3d_bf16`、euler、passes 1、seed 继承、`aspect_ratio=跟随导演台`、目标 1.0 / 2.0 MP、`skip_fl2v` 仅非首尾帧为 true、帧数超过 60 时开 latent chunking、不启用 tiling）。`CreateVideo` 13 → `SaveVideo` 14 与下载协议不变。
- 兼容性：不新增表字段、端口或 API 路由。旧任务 options 缺 `refine_enabled` 时按关闭处理，缺 `refine_quality` 时按默认 `1.0` 回显；旧任务里的 `upscale_after` 仅在任务详情作为历史快照保留，不参与新任务。已成功视频结果卡、「全部任务」与工坊的「超分」按钮及 `POST /api/jobs/{job_id}/upscale`、`…/beats/{beat_id}/upscale`、`…/projects/{id}/jobs/{job_id}/upscale` 手动 RTX 接口继续保留；自动超分分支因归一化不再产生 `upscale_after` 而停用。T8 开启二采后不再保留原 T8 采样器与音频模式，这是二采节点的硬约束，需要 T8 原味输出时关闭二采。
- 界面层级（2026-10-23 补充）：`refine_enabled` / `refine_quality` 的 `ui_group` 由 `advanced` 提升为 `primary`，创建栏与导演台视频设置弹层默认显示；二采画质仍由 `ui_visible_when` 只在开启精修后出现。创建栏紧凑布尔开关固定 36px，与相邻下拉等高；「更多设置」网格里的布尔项改为标签在上、开关在下，避免被同行控件拉伸。浅色主题的工具栏通用按钮底色规则已排除 `.ant-switch`，并为开关轨道显式设置关闭灰 `#aeb7c1` / 开启蓝 `#435ce8`（悬停变体同步），避免 Ant Design 轨道被刷白、开合无法辨认。创建栏紧凑下拉按选项最长文案自适应宽度：超过 18 字符 300px、超过 12 字符 240px、其余 188px，经内联 `--studio-compact-select-width` 与 `index.css` 的 `@media (min-width: 640px)` 规则生效，确保「二采画质」的 2.0 MP 长文案完整显示。前端 `DIRECTOR2_VIDEO_FALLBACK_FIELDS` 同步为 primary，避免目录加载前回退到旧层级。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_refine_workflow.py`、`backend/app/comfy_service.py`、`backend/app/media_studio/services/comfy_video_client.py`、`backend/app/media_studio/services/episode_video_service.py`、`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/src/director2/director2-video-settings.ts`、`frontend/src/director2/panes/Director2VideoSettingsPopover.tsx`、`backend/tests/test_h3_refine.py`、`backend/tests/media_studio_test_h3_video.py`、`backend/tests/test_rtx_vsr.py`、`backend/tests/test_core.py`、`docs/API.md`、`backend/app/api_documentation.py`、`README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 和本文档。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_h3_refine backend.tests.test_rtx_vsr backend.tests.test_core backend.tests.media_studio_test_h3_video -q`（275 项，仅保留既有 `GET /api/local-media/{token}` 参数说明失败）、`pnpm --dir frontend exec vitest run src/director2/director2-video-settings.test.ts`（13 项通过）、`pnpm --dir frontend exec tsc -b`（通过）。
- 远端验收（2026-10-23，`http://192.168.10.54:8188`，ComfyUI 0.30.0 / RTX 4080 16 GB，队列空闲时提交）：先校验全部 14 个 H3 工作流生成的二采图，14 个节点类型与所需 unet / LoRA / 3D latent 放大权重在远端均存在。随后以 2 秒、1.0 MP 二采各跑一条：LightX2V 首尾帧 146.1 秒、Director 加速文生 127.4 秒、T8 全能参考 127.5 秒；三条产物均为 1376×768、56 帧、24 fps、AAC 双声道、2.334 秒，远端文件为 `video/ZLY_REFINE_CHECK_<case>_00001_.mp4`，本地副本在已忽略的 `.tmp/acceptance/family_<case>_1mp.mp4`。首尾帧链路同时验证了 `MiniMaxH3DirectorGroupImageToVideo` 与二采节点 45 的连接。
- 回滚方式：恢复上述文件并重启后端、重建前端；已提交任务与其产物不受影响。旧客户端若仍发送 `upscale_after`，回滚后可重新触发自动 RTX 超分。

## 2026-10-23 FRP 大参考图上传超时与单文件重试

- 变更原因：线上工作台经 `127.0.0.1:18188` 的 FRP 转发连接既有 ComfyUI，内网开发环境直连同一实例。7 图 R2V 的逐文件诊断中，前 5 张成功，第 6 张 15.16 MB PNG 在 5.02 秒触发 `ConnectionError / TimeoutError`；ComfyUI 对应报错位于 `/upload/image` 的 multipart 接收阶段。Requests/urllib3 在发送请求体前设置连接超时，在发送结束后才切换到响应读取超时，原 `(5, 30)` 因而对大图发送形成 5 秒限制。官方依据：[urllib3 connectionpool.py](https://github.com/urllib3/urllib3/blob/main/src/urllib3/connectionpool.py)。
- 当前基线：`backend/app/comfy_service.py` 的上传专用常量 `COMFY_UPLOAD_TIMEOUT=(120, 180)` 分别作为连接/发送与响应读取等待时间；短请求、提交 prompt、队列与历史查询仍沿用各自的既有超时。
- 重传与幂等：一次 `upload_image` 调用固定解析后的上传 URL 与远端文件名，最多尝试 3 次；只在 `requests.ConnectionError` / `requests.Timeout` 时重传，间隔 1、2 秒。每次从头打开本地原文件，以相同名称及 `overwrite=true` 上传；此前已上传的其他参考图不因单文件的这次重传重复上传。HTTP 拒绝与无效请求不进入重传。超过次数后继续走既有 `ComfyUnavailable` → 中断/恢复流程。
- 日志与回显：每次网络异常记录文件名、文件大小、次数、耗时、原始类型和异常堆栈；最终异常保留 `__cause__`，任务 error 显示失败素材与原始原因，便于用 Docker 日志定位发送超时。日志不输出图片内容。
- 受影响文件：`backend/app/comfy_service.py`、新增 `backend/tests/test_comfy_upload.py`、`.gitignore` 中该正式测试的白名单、`README.md`、`功能说明与扩展指南.md` 与本文档。
- 兼容性与迁移：无数据库迁移、接口、端口或新配置项；不更改模型、节点 ID、ComfyUI 目标、媒体内容与参考图顺序。`upload_video` 复用同一方法。仅需更新线上后端镜像并重启工作台；已中断任务按原参数重新提交，完成的视频与旧参数快照保持有效。
- 验证命令：`python -X utf8 -B -m unittest backend.tests.test_comfy_upload backend.tests.test_comfy_provider backend.tests.test_core backend.tests.test_minimax_h3_director_accel -q`（121 项通过，覆盖重传回卷、同名覆盖、有界重试、底层异常和 HTTP 拒绝）；`pnpm --dir frontend build`（58 个测试文件、368 项测试及构建通过）。本次没有前端代码或界面变化。
- FRP 传输验收：本机通过已核对的 `124.70.90.30:18188` FRP 映射入口连接同一 RTX 4080 ComfyUI，使用新的 `(120, 180)` 超时上传 15,160,000 字节随机二进制诊断数据，37.62 秒返回 HTTP 200。该探测只验证 multipart 上传传输，没有提交视频生成任务，也未修改线上容器；原任务在更新后端后仍需重新提交验收。所有本轮诊断文件在验证后清理。
- 回滚方式：仅撤销本次上传专用常量、单文件重传和日志改动并重新部署后端，测试和文档同步撤销本节；不回滚其他工作区改动或删除数据、素材、历史任务与产物。

## 2026-10-23 H3 R2V 分组必填尺寸参数兼容

- 变更原因：线上提交 7 图 Director 加速 R2V 返回 HTTP 400 `prompt_outputs_failed_validation`，节点 `30` 的 `MiniMaxH3DirectorGroupReferenceToVideo` 缺少 `ref_image_size`。当前生效地址已核对：开发侧 `http://192.168.10.54:8188`，线上侧经 FRP 的 `http://127.0.0.1:18188`，连接同一实例。远端 `/object_info/MiniMaxH3DirectorGroupReferenceToVideo` 声明 `prompt`、`duration_sec`、`ref_image_size` 为必填输入；尺寸是 COMBO，取值 `match` / `1024` / `1280` / `1536` / `max`，默认 `match`。
- 当前基线：`build_minimax_h3_director_accel_workflow` 和 `build_minimax_h3_refine_workflow` 仅在创建 R2V 分组时写入 `ref_image_size`。优先使用注册表归一化的 `reference_image_size`，其次沿用 T8 全能参考的 `ref_image_size`，均缺失时使用 `match`。正常 Director、官方/LightX2V/八步双加速的二采 R2V 和 T8 全能参考二采均得到该字段；T2V/I2V/FL2V 分组以及 T8 双时钟的既有路由保持原样。
- 兼容性与迁移：无数据库、端口、模型、API 路由或界面变更；继续使用节点 `30`、`12`、`14` 与有序 `ref_images.ref_image_0…8`。新增字段由后端托管，不暴露 ComfyUI 技术控件。旧任务按原参数重新生成 graph 即可，线上必须更新本次后端代码；上传超时修复属于独立问题，继续保留。
- 受影响文件：`backend/app/minimax_h3_director_accel_workflow.py`、`backend/app/minimax_h3_refine_workflow.py`、`backend/tests/test_minimax_h3_director_accel.py`、`backend/tests/test_h3_refine.py`、`README.md`、`功能说明与扩展指南.md` 与本文档。
- 验证命令：`python -X utf8 -B -m unittest backend.tests.test_minimax_h3_director_accel backend.tests.test_h3_refine backend.tests.media_studio_test_h3_video backend.tests.test_core backend.tests.test_comfy_upload -q`（274 项通过）；`pnpm --dir frontend build`（58 个文件、371 项前端测试及构建通过）。当前远端 32 类节点定义对照 14 个工作流、64 组组合，3301 个必填输入检查及枚举值检查无错误，其中 R2V 分组 18 组。
- 实际推理验收：远端队列空闲时提交 7 张已上传参考图的 Director 加速 R2V，2 秒时长参数、2 步、0.4 MP、seed 12345、`sage_allow_compile=false`、`ref_image_size=match`。提交返回 HTTP 200、`node_errors={}`，prompt `4130da03-0598-4983-afef-26e7c707f670` 在 58.733 秒后 `success`，输出 `test-results/ref-image-size-20261023/smoke_00001_.mp4`（325,260 字节）。临时输出随后清理；未重新提交用户原有 15 秒任务，也未直接更改线上容器，线上仍需部署本次两个工作流构建器的修复。
- 回滚方式：仅撤销两处 R2V 分组字段映射和对应测试/文档后重新部署后端；保持上传超时修复，不删除数据、参考素材或既有产物。

## 2026-10-24 H3 二采先预览一采（单条创作与工坊单镜/选中镜）

- 变更原因：二采精修在 16 GB 显卡上按 1.0 MP 约需数分钟、2.0 MP 可达数十分钟。此前开启精修后一采与二采连续执行，用户只能在全部跑完后看到结果。本次增加「先预览一采」：先只跑 0.4 MP 一采并停下，用户看过预览再决定是否用同一 seed 只跑二采。当前范围是单条创作任务与剧集工坊的逐镜/选中镜生成；整集直出仍为一次跑完两段式，后端明确拒绝该组合。
- 选项与界面：全部 H3 家族（官方 H3、LightX2V、八步双加速、Director 加速、T8）的 option schema 新增 `refine_preview`，中文名「先预览一采」，布尔、默认 `false`、`ui_group=primary`、`ui_visible_when={"refine_enabled": true}`。创建栏、导演台视频设置弹层与工坊生成设置都在「二采画质」之后显示；未开启二采精修时不出现，且归一化会把 `refine_preview` 强制为 `false`。开启后生成摘要显示「二采 X MP · 先预览」。
- 一采预览图：`minimax_h3_refine_workflow.build_refine_nodes(..., confirm_first_pass=True)` 在 Director 采样节点 `12` 之后增加预览输出，二采采样节点 `45` 使用 `ExecutionBlocker(None)` 阻止下游执行。单镜图使用节点 `46`（`VHS_VideoCombine` 预览）与 `47`（预览输出），时间线图使用节点 `16` / `17`，两者都读取精修前的 Director 图像与音频。`add_first_pass_preview()` 负责接入，`continuation_workflow()` 只移除预览输出节点。确认二采时把保留下来的同一份工作流（去掉预览输出）重新提交，ComfyUI 命中一采缓存，只执行放大与二采采样；因此无需重新上传参考图或重新跑一采。
- 任务状态与持久化：新增 `JobStatus.AWAITING_REFINE="awaiting_refine"`。创作任务在 `generation_items.refine_state_json` 保存 `{status, workflow, seed, preview_outputs, refine_quality}`，`update_generation()` 新增 `refine_state` / `clear_refine_state` 参数；worker 在预览阶段结束后把生成项置为待确认，确认后续跑使用保存的 seed 与工作流，二采成功后清除该状态。工坊任务把续跑信息写入 `ai_project_jobs.payload_json.refine_continuation`，内容为 `{status, mode, quality, preview_url, preview_merged, chunks[]}`，每个 chunk 保存续跑 graph、镜头 ID 和预览输出。
- 状态语义：`awaiting_refine` 属于可取消但非活动的状态，不计入 worker 启动恢复、也不允许中断恢复；同一镜头已有待确认任务时继续计入重复任务拦截。对外任务响应仍隐藏内部 `refine_state`，只通过 `status`、`stage`、`result_url`/`outputs` 暴露预览。待确认任务在工坊与任务中心隐藏「超分」入口，创作页保留按钮但禁用；确认或保留后再按既有规则出现。
- 创作页接口：`POST /api/jobs/{job_id}/refine/confirm`（202，校验唯一生成项处于 `awaiting_refine` 且保存了工作流，把续跑状态标记为 `confirmed`，任务改回 `queued`、阶段「等待二采精修」并重新入队）；`POST /api/jobs/{job_id}/refine/skip`（202，把一采输出直接作为最终结果、状态改为 `succeeded`、清理续跑状态）。接口沿用现有任务权限校验。worker 只有看到 `refine_state.status="confirmed"` 才走续跑图；一采预览失败、取消或进程中断后重试时状态仍是 `awaiting`，会重新执行一采预览，不会跳过预览直接跑二采。工坊续跑以 `refine_continuation.status="running"` 为闸门，失败后重试同样回到常规生成路径。
- 工坊接口：`POST /api/projects/{project_id}/jobs/{job_id}/refine/confirm` 与 `/refine/skip`。确认用原子 `UPDATE … WHERE status='awaiting_refine'` 防止重复点击，并提交已保存的续跑图；跳过把预览写为镜头成片并结束任务，多段预览未合并时先经 FFmpeg 合并并上传七牛云，未配置七牛云且无法合并时拒绝跳过并提示确认二采或重新生成。二采成功后才写入镜头 Take 与自动超分；待确认期间镜头卡只播放预览，不把预览写成正式成片。
- 前端：创作页 `App.tsx` 增加待确认状态文案/颜色、取消入口与轮次确认/保留按钮；创建栏新增开关后底部工具行变长，暗色主题此前缺少浅色已有的 `flex-shrink: 0` 与时长文案不换行规则，导致时长按钮被压成两行；本次把两条规则移到基础样式，并把紧凑时长按钮由 76px 调至 92px，浅暗主题均为单行。「全部任务 → 视频生成」显示金色「一采预览待确认」、结果卡「一采」标签和确认/保留操作。工坊在镜头检视器顶部显示「一采预览已生成」与「确认二采 / 保留一采」，成片 Tab 的角标在待确认时为「一采预览」，确认后二采期间为「二采中」并继续播放预览；只有待确认项时轮询间隔回落到 3 秒。`workshop-video-progress.ts` 将 `awaiting_refine` 视为非活动状态，避免永久 1 秒轮询。
- 兼容性与迁移：`generation_items.refine_state_json` 是启动时自动补齐的加法列（SQLite `TEXT`、MySQL `LONGTEXT`），无独立迁移脚本，旧任务为空即可；`refine_preview` 未出现在旧参数快照时按关闭处理，旧任务行为不变。不改变 ComfyUI 地址、模型、既有节点 `12`/`14`/`45` 的采样参数、参考图顺序或媒体存储位置。整集直出 + 先预览会被后端拒绝（提示改为逐镜或选中镜），前端在提交前给出同样拦截。线上需同时更新前后端镜像；已处于 `awaiting_refine` 的任务升级后可直接确认或保留。
- 受影响文件：`backend/app/{workflow_registry.py,minimax_h3_refine_workflow.py,comfy_service.py,worker.py,storage.py,models.py,main.py}`、`backend/app/media_studio/services/{comfy_video_client.py,episode_video_service.py}`、`backend/app/media_studio/routers/project_router.py`；`frontend/src/{App.tsx,index.css,director2/api.ts,director2/director2-video-settings.ts,director2/workshop-video-progress.ts,director2/panes/EpisodeWorkshopPane.tsx,director2/panes/JobsCenterPane.tsx,director2/panes/episode-workshop.css}`；测试 `backend/tests/{test_h3_refine.py,test_timeline_rendering.py,test_core.py,media_studio_test_h3_video.py}`、`frontend/src/director2/{director2-video-settings.test.ts,workshop-video-progress.test.ts}`；`README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文档。
- 验证命令：`E:\anaconda3\python.exe -X utf8 -B -m unittest backend.tests.test_core backend.tests.test_h3_refine backend.tests.media_studio_test_h3_video backend.tests.test_director2_ai_generation -q`（316 项通过）；`pnpm --dir frontend test`（58 个文件、375 项通过）；`pnpm --dir frontend exec tsc -b`（通过）。后端全量 976 项保留 2 失败、2 错误（OpenAPI/画布 mock、已下线 `xiaji_api`、MCP 工具数量、剧本提示词断言），均与本节无关。预览专项覆盖：选项层级/默认值/归一化、单镜与时间线预览节点及 filename、`continuation_workflow()` 仅移除预览输出、待确认状态与公开响应脱敏、worker 续跑不重新执行 `run`、未确认的续跑状态会重新执行一采、创作页确认接口写入 `confirmed` 并可续跑、创作页保留接口、工坊逐镜与选中镜确认/保留及整集拒绝。桌面自查（2026-10-24，隔离 SQLite 后端 7867 + 隔离 Vite 5174 + 临时管理员，未访问真实 MySQL、7865 后端或 ComfyUI）：开启二采后创建栏按序显示「二采精修 / 二采画质 / 先预览一采」，关闭精修时新开关隐藏；浅暗主题下开关状态、标签和时长按钮均为单行，控制台仅有既有的 Ant Design `popupClassName` 弃用与表单 id 警告。工坊与任务中心的待确认条、确认/保留按钮和轮次状态由前端/后端专项测试覆盖，本轮未在页面中构造真实待确认任务。尚未提交真实远端预览任务（避免占用远端队列与消耗二采时间），远端二采图本身已在 2026-10-23 验证。
- 回滚方式：移除 `refine_preview` 选项与归一化、预览图构造及 `awaiting_refine` 状态流转，恢复确认/保留接口和前端按钮后重新部署。已产生的一采预览与 `refine_state_json` / `refine_continuation` 数据可保留不读；不要删除既有成片、镜头 Take 或媒体文件。


## 2026-10-24 无限画布自动化回归修复

- 原因：对当前无限画布做实际浏览器自动化时，发现并发保存、离开页面、网络恢复、撤销和生成任务状态之间存在内容丢失或展示不一致。
- 前端状态基线：`canvas-save.ts` 的保存队列按版本串行提交，等待请求期间的新编辑补存后才允许返回；错误/409 时保留当前草稿。`canvas-recovery.ts` 保存 `{baseVersion, content}` 到项目级 `sessionStorage`，在同一标签页刷新或侧栏切换后恢复，存储受限时使用会话内存；编辑器所有权防止旧请求回写，已与服务器内容一致的备份按已保存处理。`CanvasWorkspace` 由稳定项目 ID 挂载编辑器，禁用后台重连替换编辑器草稿；恢复历史版本前先保存当前内容，冲突允许导出本页草稿后再加载服务器版本。
- 编辑基线：重命名与最新保存标题比较；撤销包含画布设置，排除相机与封面变更；删除节点清理完整关联边；导入和旧草稿归一化校验常见文本字段；新增节点按可用舞台区域定位。检查器长标题按剩余宽度省略，保存/取帧操作有稳定无障碍名称，收藏空态能回到全部画布。
- 生成基线：画布接入现有 `POST /api/jobs/{id}/refine/confirm`、`/refine/skip` 与取消接口；`awaiting_refine` 保持预览与确认操作，不自动插入独立结果。正式完成后插入并按任务号去重，立即完成也可落盘；优先最终输出并跳过过期产物；当前选中的历史结果优先于终止任务的最新快照；404 终止轮询并更新所有引用节点。提交锁按节点隔离；多个文字来源中有任何空文本都会阻断提交。
- 受影响文件：`frontend/src/canvas/{CanvasWorkspace,CanvasEditor,CanvasNodes,CanvasGeneratorInspector,CanvasSidePanel,CanvasInspector}.tsx`、`canvas.css`、`canvas-save.ts`、新增 `canvas-recovery.ts`、`canvas-model.ts`、`canvas-manage.ts`、`canvas-generation.ts` 及相应 `*.test.ts`；README、扩展指南、开发计划和 `docs/design-ref-canvas/audit-20261024/`。
- 兼容性：仅客户端状态与展示修复，草稿仍为 `schemaVersion: 2`，无 API、数据库、ComfyUI 图、模型、节点 ID 或依赖变更。生产环境实际 ComfyUI 地址从健康检查读取，始终为 `http://192.168.10.54:8188`；隔离后端测试连接同一远端，未修改生产供应商设置、未启动其他 ComfyUI。
- 验证命令：`pnpm --dir frontend build`（61 文件、422 项测试、TypeScript、clean、Vite 全部通过）；`python -X utf8 -m unittest backend.tests.test_canvas_store backend.tests.test_library_query backend.tests.test_core backend.tests.test_h3_refine -q`（163 项通过）。Playwright CLI 驱动真实 5173，API 转发到隔离 SQLite 17966，覆盖桌面浅暗、保存故障/冲突、编辑/生成、素材、导出、封面和 350 节点；当前远端实际生成 H.264/AAC 视频 608×352、56 帧、2.333333 秒、204280 字节，画布内播放与下载通过。预览确认/保留/取消及作品库多页数据使用受控响应，接口由后端 unittest 补充；未调用付费图片生成。截图与结果见本轮验收报告。
- 回滚方式：仅逆向撤回上述本轮画布增量后执行 `pnpm --dir frontend build`，不整文件覆盖用户已有改动，不移除 V4.8/V4.9 或其他模块。恢复备份可保留不读，服务器原画布和版本不变，无需数据库回滚。

## 2026-10-25 生成页性能与错误反馈优化

- 变更原因：生成页每次进入都会同时拉取任务列表、健康状态和图片余额，并持续轮询；资产页与导演台二也复用同一列表查询；长历史页面每秒由根组件触发整页重渲染；部分提交/重试/取消/批量删除失败没有用户可见反馈；深链到不在最新列表分页内的任务会显示空态。
- 查询与轮询基线：`jobsQuery` 仅在生成页、资产页和旧导演工坊启用；周期轮询只在生成页与旧导演工坊启用，生成页有运行中任务时 4 秒、空闲时 15 秒，并跳过上一轮未完成的请求。资产页只取一次任务快照、不再周期轮询，运行中的新产物需重新进入或刷新资产页才能看到。导演台二不请求任务列表。`healthQuery` 轮询由 8 秒调整为 30 秒；图片余额仅在生成页且媒体类型为图片时启用，生成中 5 秒、空闲 15 秒。
- 深链与加载态：选中任务不在最新列表结果中时，改为请求 `GET /api/jobs/{id}` 单任务接口，并只在任务或轮次仍活跃时 4 秒轮询；列表加载、单任务加载和任务缺失分别显示「正在加载任务…」与「任务不存在或已删除」，后者附带接口错误信息。
- 渲染与交互：回合等待计时改为每个 `RoundWait` 局部每秒更新，取消根组件级整页定时重渲染；自定义日期筛选按本地自然日解析并以次日零点为开区间；切换选中任务时自动回到顶部；参考图选择在 `reference_mode === "none"` 时直接忽略；提示词输入支持拖拽/粘贴图片、`Ctrl/Cmd+Enter` 提交，工作流选择可搜索，技能菜单改为点击触发且「优化当前提示词」为独立菜单项，并提供「撤销优化」。
- 上传与媒体：参考图在前端按最长边 1024 px、WebP 0.86 压缩，仅在体积确实更小时替换，GIF/SVG 保持原样；单次仍最多 8 张。剪映导出弹窗用隐藏 `<video preload="metadata">` 探测未知视频时长（12 秒超时，失败按 5 秒估算），总时长、ZIP 和 JSON 使用探测结果；超分按钮禁用时通过外层容器显示提示，切换器以「原片 N / 2x 超分」区分版本。
- 错误反馈：原始创建、追加回合按 `apiErrorMessage` 解析响应；重试、取消、追加上下文、重试失败项均补充失败提示；批量删除使用 `Promise.allSettled`，只触发一次列表刷新，并按全部成功/部分失败给出一次汇总提示。
- 参数校验基线：工作流注册表新增通用 `ui_not_less_than` 与 `ui_requires_references_when` 元数据，前后端校验由选项定义驱动，不再在 `validate_option_relationships` 中硬编码 T8 字段。
- 视觉回归修复：吸底输入框样式在移除 `.studio-light` 前缀后，选择器优先级低于 Tailwind `.lg:sticky`，导致暗色主题下 `position` 回落为 `sticky` 并横向偏移。现以 `.studio-workspace .studio-composer-form` 和 `.studio-workspace:not(.studio-task-rail-collapsed)` / `.studio-workspace.studio-task-rail-collapsed` 提升优先级，1024/1280 两种侧栏宽度下浅暗主题都保持 `fixed` 与正确居中偏移。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/src/media/VideoStudioModule.tsx`、`frontend/src/media/JianyingExportModal.tsx`、`backend/app/workflow_registry.py`、`backend/tests/test_core.py`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`、`README.md`。
- 兼容性：不新增或修改 API 路由、数据库表/列、任务队列、ComfyUI 节点、模型路径、工作流 graph 和前端路由；任务、资产、导演台与画布数据保持原格式。行为差异是资产页不再自动轮询、健康检查间隔变长，以及深链任务改走单任务接口。未切换或启动任何 ComfyUI 实例，未访问真实 MySQL。
- 验证命令与证据：`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_h3_refine backend.tests.test_job_list_payload backend.tests.media_studio_test_h3_video -q`（276 项通过）；`pnpm --dir frontend build`（61 个测试文件、422 项测试、TypeScript、clean、Vite 构建通过，构建 7.32 秒）；`pnpm --dir frontend test`（61 文件 / 422 项通过）。隔离 Vite 5174 + SQLite 后端 7867 + 本地媒体 7871 完成桌面 1440 浅暗检查：任务与资产加载、自定义日期筛选、吸底输入框 `position: fixed`、账号菜单、剪映弹窗真实视频时长 2.3 秒、总时长 10.7 秒。未触碰真实 5173/7865 和真实数据库。
- 回滚方式：逆向撤回本轮上述前端查询/渲染/交互改动、CSS 优先级修复、注册表元数据与测试，再执行 `pnpm --dir frontend build`；不整文件覆盖用户其他改动，不删除任务、资产或上传文件，无需数据库迁移或 ComfyUI 配置回滚。仍保留的后续结构优化（`App.tsx` 拆分为独立组件、后端任务列表分页/资产虚拟化、健康检查服务端缓存）不在本轮范围内。

## 2026-10-25 仓库废弃代码与历史产物清理

- 日期与原因：2026-10-25。仓库长期累积一次性改写脚本、已下线模块的测试与建表脚本、无引用前端残留，以及约 8GB 旧归档、日志、测试截图与构建缓存；本次只做删除和依赖收敛，不改变运行时行为。
- 代码基线：删除 `backend/app/patch.py`、`patch2.py`–`patch14.py`、`patch_rail.py`（均为一次性源码改写脚本，目标文件多已不存在）；删除 `backend/tests/test_xiaji.py`（仍导入已删除的 `backend.app.xiaji_api`，属于既有失败用例）；删除 `frontend/src/components/ui/{button,card}.tsx`（无任何 import 或 re-export）与根目录 `pelican_bicycle.html`。`frontend/src/director/recipe-readiness.ts` 初判无引用，复核发现 `frontend/src/director/types.ts:538` 仍通过 `export * from "./recipe-readiness"` 桶导出，已恢复保留。移除 `frontend/package.json` 中仅被上述死文件使用的 `@tauri-apps/api`、`class-variance-authority`、`clsx`、`tailwind-merge`，并删除 `frontend/src/lib/utils.ts` 的 `cn`；`pnpm-lock.yaml` 已同步。`local_video_studio.py` 仍被 `backend/app/comfy_service.py` 与测试作为 legacy 辅助模块引用，保留。
- 历史兼容资产：删除 `sql/002_xiaji_ingest.sql`–`012_xiaji_episode_compose.sql`（旧 xiaji 后端与表已下线，当前媒体工作台使用 `ai_*` 表）；现有 MySQL 中的 `xiaji_*` 表不删除，仅全新库不再创建。删除 `mysql-init/01_ai_media_dump.sql`（初始库快照，无 Compose/Docker/脚本引用）、`workflows/wan_vace_multi_reference_comfyui.json`（无代码引用）与 `tools/{recover_lost_comfyui_tasks.py,repair_director_from_sqlite.py,repair_director_video_urls.py,run_crossover_h3_chain.ps1,run_sasuke_gojo_h3_chain.ps1,run_train_h3_chain.ps1}` 六个一次性运维脚本。保留 `tools/generate_design_images.ps1`、`tools/indextts_sidecar/`、`docs/xiaji-modules.md` 和未跟踪的 `scripts/` 本地实验目录。另移除 `deploy-server-image.sh` 末尾重复且不可达的 `[5/5]` 迁移输出块。
- 本地产物基线：删除根目录 `data.rar`、`zly-ai-video-studio_latest_with_data.tar`、`packages/zly-ai-video-studio_latest.tar`、`debug.txt`、旧日志、`payload_*.json`、`project_data.json`、`latest_*.json`、`ui-*.png`、`submit_h3_*.py`；删除 `tmp/`、`test-results/`、`.tmp/`、`output/`、`logs/`、`.playwright-cli/`、`.pytest_cache/`、各层 `__pycache__/`、`dev-log/api-requests.log` 与 `desktop/src-tauri/target/`。保留根目录最新 `zly-ai-video-studio_latest.tar`（`deploy-server-image.sh` 的最终回退镜像）、`data/`、`results/`、`frontend/node_modules/`、根 `node_modules/`、`desktop/` 源码与 `dev-log/修改记录.md`。
- 兼容性：不新增或修改 API 路由、数据库已有表与列、任务队列、ComfyUI 节点、模型路径、工作流 graph 或前端路由；`frontend` 仍使用 Ant Design，不恢复 shadcn/Tailwind UI 依赖。删除的 `sql/002–012` 只影响全新 MySQL 初始化，旧库无需迁移；`mysql-init` 与 `workflows/` 目录删除后不被 Dockerfile、Compose 或运行时代码引用。被忽略的历史产物不进入 Git，无法回滚恢复；最新部署镜像与运行数据均保留。
- 验证命令：`pnpm --dir frontend test`（61 个文件、422 项通过）；`pnpm --dir frontend build`（TypeScript、clean 与 Vite 构建通过，13.10s）；`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_db backend.tests.test_canvas_store backend.tests.test_h3_refine backend.tests.test_job_list_payload -q`（162 项通过）；补充运行 `backend.tests.test_db` 与 `backend.tests.test_dev_reloader` 通过，`backend.tests.test_media_studio_schema` 仍有既有的 `canvas_projects` mock 失败，与本轮删除无关。全量后端套件未完整重跑，避免触发依赖外部服务的长等待用例。
- 回滚方式：从 Git 恢复本次删除的跟踪文件，执行 `pnpm install` 恢复前端依赖后重新 `pnpm --dir frontend build`；如需恢复旧 MySQL 初始化行为，只恢复 `sql/002–012` 即可，无需迁移现有表。`desktop/` 源码、`data/`、`results/` 和最新部署镜像未删除，无需回滚；忽略目录中的历史日志、截图和缓存在删除后不可恢复。

## 2026-10-25 移除 Hypit 复刻

- 变更原因：Hypit 复刻依赖本机 `D:\zlyun\hypit-poc` CLI、WhisperX 与独立 SVML 工程目录，长期只有实验价值；产品保留 VACE 参考片复刻即可覆盖结构复刻需求，继续维护两套复刻链路成本高于收益。本次按要求完整删除该功能。
- 当前基线：导演台首页只有导演创作、短视频批量、参考片复刻三个创作卡（主卡 `grid-row: 1 / 3`），下方为整行剧本诊断入口；最近工程筛选为导演创作 / 短视频批量 / 参考片复刻 / 全部，只保留 `batch_run` / `shot_replication`，并过滤 recipe / timeline / 旧 `hypit_replication`。`DirectorStudioModule` 只装配批量与 VACE 复刻；`isDirectorLegacyStudioPath` 只识别 `batch` / `replication`。后端 payload kind 仅保留 `timeline`、`director_recipe`、`batch_run`、`shot_replication`；durable operation 不再有 `hypit_transcribe` / `hypit_compile`。
- 删除范围：后端删除 `backend/app/director_hypit.py` 及 `main.py` 中六个 `/api/director/hypit/*` 端点与绑定辅助函数；`director_recipe.py` 删除 `hypit_replication` 常量、注册项与归一化分支；`director_operations.py` 删除 Hypit 进程登记/回收、任务分派与取消清理；`models.py` 删除 Hypit kind、operation 与 `language` 字段；`storage.py` 删除 Hypit 进度特判；`api_documentation.py` 删除端点文档。前端删除 `DirectorHypitStudio.tsx`、`hypit-model.ts`、`hypit-model.test.ts`，并清理 `DirectorStudioModule`、`paths.ts`、`director-api.ts`、`home-projects.ts`、`Director2StudioHome.tsx`、`Director2App.tsx`、`index.css`、`director-home.css` 中的路由、类型、入口、样式与筛选。测试删除 `backend/tests/test_director_hypit.py`，并从 `test_core.py` / `test_director.py` 移除 Hypit 用例。
- 兼容性：不新增或修改数据库表/列，不迁移既有数据。历史 `payload.kind = "hypit_replication"` 在 `payload_kind()` 中回退为 `timeline`，工程记录仍保留，但不再出现在导演台首页；`data/hypit/{user}/{project}` 工作目录及其中已有产物未删除。旧 `/director/hypit/*` 书签由导演台路由兜底回首页。VACE `shot_replication` 的 `/director/replication/:id`、分析/转绘接口与任务协议不受影响。Hypit 原先使用的局域网 ComfyUI、`ZLY_HYPIT_*` 环境变量与 `hypit.runtime.json` 均不再由工作台读取。
- 受影响文件：`backend/app/{main,director_hypit,director_recipe,director_operations,models,storage,api_documentation}.py`、`backend/tests/{test_director_hypit,test_core,test_director}.py`、`frontend/src/paths.ts`、`frontend/src/director/{DirectorStudioModule,DirectorHypitStudio,hypit-model,director-api}.tsx`、`frontend/src/director2/{Director2StudioHome,Director2App,home-projects}.tsx`、`frontend/src/index.css`、`frontend/src/director2/director-home.css`、四份主文档与 `docs/API.md`、`docs/导演台流程与界面结构.md`。
- 验证命令：`python -m compileall -q backend/app`（通过）；`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_director backend.tests.test_director_project_info -q`（253 项，1 项既有无关失败：`test_script_agent_uses_scene_ledger_continuity_guidance` 期望小写 `opening spatial state`，实际提示词为大写开头）；`pnpm --dir frontend build`（60 个测试文件、415 项前端测试、TypeScript、clean 与 Vite 构建通过）。桌面端首页在 1505×1045、1440×1000、1920×1080 三种视口完成浅暗主题检查（三创作卡、主卡 `grid-row: 1 / 3`、四项筛选、无横向溢出），截图与元数据见 `docs/design-ref-director/ui-20261023/details-20261025/`；未触发 LLM 或出片任务。
- 回滚方式：从 Git 恢复被删除的 `backend/app/director_hypit.py`、`backend/tests/test_director_hypit.py`、`frontend/src/director/{DirectorHypitStudio.tsx,hypit-model.ts,hypit-model.test.ts}` 以及上述文件中被移除的 Hypit 分支与样式，再执行 `pnpm --dir frontend build` 并重启后端。无需数据库回滚；既有工程数据和 `data/hypit/` 目录在删除期间保持原样。

## 2026-10-25 只读接口与轮询负载优化

- 变更原因：作品库每次分页都会重新水合 500 个完整任务聚合（含参数、参考图与体积很大的二采续跑状态）；`GET /api/media/{filename}` 为查找一个文件要完整水合最多 1000 个任务；健康检查每个请求都同步探测 ComfyUI；请求日志中间件把整个 multipart 上传体拼进内存；导演台二任务中心固定 1 秒轮询。多用户同时轮询时，这些重复的同步工作叠加在单进程后端上。
- 后端读取基线：`JobStore.list_jobs()`/`list()` 默认不再解析 `generation_items.refine_state_json`，单任务 `get()`、worker 恢复与续跑路径仍完整读取。新增 `list_library_sources()` 只投影 job/round/item/output 字段，`output_locations()` 一次构建路径到输出的索引。`JobStore` 新增进程内 `content_epoch`，在任务创建、追加轮次、写回 outputs（含交付状态）、标题/置顶修改、删除和账号归属变更后自增；作品库条目与媒体路径索引只在 epoch 变化后重建。缓存实例挂在 `app.state`，随应用生命周期创建，unittest 的临时 SQLite 不会串数据。
- 接口行为：`GET /api/library` 与 `GET /api/library/query` 共用按 `(目标用户, API 前缀)` 缓存的条目，搜索、筛选与分页仍每次在内存执行；`GET /api/media/{filename}` 改为查询路径索引，仍按普通用户本人 / 管理员全量隔离，并保留原有 404 与 410 语义。媒体索引现在覆盖同一任务的各轮输出（旧实现只覆盖最新轮），与作品库链接一致。
- 健康检查：`GET /api/health` 对 ComfyUI `/system_stats` 的探测结果按当前生效地址缓存 10 秒；切换「管理设置 → AI 供应商 → ComfyUI」地址后缓存 key 改变，会立即重新探测。`webui` 与 `grs` 仍每次从数据库读取实时配置。
- 上传日志：`RequestLogMiddleware` 对 GET/HEAD/DELETE/OPTIONS 不再读取请求体；`multipart/form-data` 与 `application/octet-stream` 改为边转发边计数，日志仍记录 `<binary N bytes>`；JSON 与表单仅在 64 KiB 内合并记录，超过后按原分块转发上游并在日志标记截断。原有断连与流式响应行为保持不变。
- 前端轮询：导演台二「全部任务」改为自适应定时器：存在活动任务（queued/pending/preparing/prompt_generation/uploading/comfy_queued/running）时 1 秒，空闲 5 秒，标签页隐藏 15 秒，并跳过重入请求；切回标签页立即刷新。任务列表与当前选中项在状态、进度、更新时间、结果地址和错误均未变化时复用旧对象，避免每次静默轮询重渲染整页。
- 兼容性：不新增或修改 API 路由、响应 schema、数据库表/列、任务队列、ComfyUI 节点、模型路径与前端路由，任务、资产、导演台和画布数据格式不变。缓存只存在于单进程内存；当前 Dockerfile 为单 uvicorn 进程，多 worker 部署时每进程各自持有。行为差异是媒体接口可读取旧轮次输出、健康检查最多滞后 10 秒、导演台二空闲任务列表最多滞后 5 秒。
- 受影响文件：`backend/app/{cache.py,media_index.py,storage.py,main.py,request_log.py}`、`backend/tests/{test_storage_projections.py,test_read_caches.py,test_request_log.py}`、`frontend/src/director2/panes/JobsCenterPane.tsx`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_h3_refine backend.tests.test_job_list_payload backend.tests.media_studio_test_h3_video backend.tests.test_storage_projections backend.tests.test_read_caches backend.tests.test_request_log backend.tests.test_library_query -q`（297 项通过）；`pnpm --dir frontend build`（62 个测试文件、423 项测试、TypeScript、clean 与 Vite 全部通过）；`pnpm --dir frontend test`（62 文件 / 423 项通过）。健康检查缓存使用 mock 的 `ComfyService.health` 验证，未启动或切换 ComfyUI，未访问真实 MySQL。
- 回滚方式：逆向撤回上述缓存模块、存储投影、端点接线、日志中间件与轮询改动，重启后端并执行 `pnpm --dir frontend build`。缓存都是进程内派生数据，无需数据库迁移，也不影响已生成的任务、资产与媒体文件。

## 2026-10-28 员工姓名自助修改与管理员修改全部账号

- 日期与原因：2026-10-28。姓名只在管理员创建账号时填写，员工无法自行纠正错字或改名，管理员也无法修改既有账号姓名；本次补齐姓名维护能力。
- 用户可见行为：生成 / 资产页账号菜单、导演台与画布的旧账号菜单新增「修改姓名」，所有已登录账号都可以修改自己的显示姓名；「管理设置 → 账号管理」为每个账号新增「修改姓名」，管理员与超级管理员可修改任意账号（含管理员、超级管理员）的姓名。保存后当前账号界面立即刷新，并写入审计日志。
- 接口与权限：新增 `PATCH /api/auth/profile`，JSON body 为 `{"display_name":"新姓名"}`（1–80 字符，去首尾空白后不能为空），沿用会话 Cookie 与 `X-CSRF-Token`，返回最新 `AuthStatusResponse`（含 `user` 与 `csrf_token`），不换发会话。`PATCH /api/admin/users/{user_id}` 新增可选 `display_name`；姓名对全部账号开放给管理员/超级管理员，`role` 与 `is_active` 仍沿用原范围，管理员调整非员工账号的角色或启停继续返回 403。
- 受影响文件：`backend/app/{auth,models,main,api_documentation}.py`、`backend/tests/{test_accounts,test_core}.py`、`frontend/src/components/{RenameUserModal,StudioHeader}.tsx`、`frontend/src/admin/AdminSettings.tsx`、`frontend/src/App.tsx`、`docs/API.md`、README、本文件与功能说明。
- 兼容性：复用 `users.display_name`，不新增或修改表/列；不改任务、媒体、导演台、画布、ComfyUI、工作流、端口或前端路由。旧客户端不调用新接口时行为不变，管理接口既有请求体仍合法。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_accounts backend.tests.test_core -q`；`pnpm --dir frontend build`；5173 桌面端浅暗主题检查账号菜单与管理设置改名。
- 回滚方式：撤回新增接口、管理接口的姓名参数与前端入口/弹窗，恢复原权限判断后重启后端并重新构建前端；无需数据库迁移，已修改的姓名保留。


## 2026-10-28 生成首页 V3：创作优先与真实作品预览

- 日期与原因：2026-10-28。按用户确认的 V3 设计稿实现，解决生成首页留白过大、V2 等尺寸网格缺少主次的问题；保留紧凑操作尺寸与现有工作流能力。
- 当前基线：未选择任务的生成首页展示一行问候、现有创建表单、导演台 / 图片生成 / 无限画布入口及最近作品；任务详情仍使用原有轮次和吸底输入框。提示词灵感从首页芯片移入 Ant Design Dropdown；编辑器改为 Input.TextArea，ref 同步适配；任务栏以图标加文字语义表达状态。新增样式限定于 studio-generation-home，复用根 Provider 与 --studio-*，支持桌面浅暗主题。
- 数据与状态：GenerationHomeSections 复用现有 jobsQuery 的可见任务数据，不新增接口或轮询。generation-home.ts 从最近可用轮次选取每任务一份产物，回退旧结果，跳过过期 / 无产物，保留真实 URL、比例和时长。媒介筛选为组件内存状态，过滤后最多显示 12 项，不写存储键。作品通过原 openGenerateJob 打开正确媒介路由；暂无、加载、错误、重试和媒体失效均有界面反馈。保留媒介草稿、提示词优化、首尾帧 / R2V 及参数 schema 的既有处理。
- 受影响文件：frontend/src/App.tsx；新增 frontend/src/generation/{GenerationHomeSections.tsx,generation-home.ts,generation-home.css,generation-home.test.ts}、frontend/public/generation-home/ 三张入口图片；frontend/DESIGN.md、README、本文件、功能说明与扩展指南及 docs/design-ref-generation/home-v3-20261028/ 设计 / 素材 / 实现记录。未修改既有 index.css，保留工作区原有未提交改动。
- 兼容性：不改 API、HTTP 请求体、路由、数据库、队列、工作流注册表、ComfyUI 节点 / 模型路径 / 地址；无新依赖。表单继续按 registry 展示，默认 H3 的额外主选项使工具行自然排成两行，不按参数名隐藏。导演台与画布仅复用既有链接，未调整其内部流程。
- 验证命令：pnpm --dir frontend build（65 文件、447 项前端测试，TypeScript / clean-dist / Vite 通过）；python -X utf8 -m unittest backend.tests.test_core backend.tests.test_job_list_payload -q（111 项通过）。真实 5173、独立 Edge，1586×992 / 1440×900 / 1920×1080 桌面及暗色检查，27 项浏览器检查通过；登录、服务、任务及提交响应在独立会话内受控模拟，未写真实数据库或提交远端 / 付费任务。截图、边界及数据见同目录设计验收记录，未做移动端检查。
- 回滚方式：只撤回 App.tsx 本节首页与 TextArea ref 增量，删除本次新增的 generation 模块及 public/generation-home 后重新运行 pnpm --dir frontend build。不得用整文件回滚覆盖已有 Header、超分、视频结果或账号改名改动；无需数据库或 ComfyUI 回滚。

## 2026-10-29 导演台助手接入模型能力（缓存 / 结构化输出 / 原生工具 / 联网搜索）

- 日期与原因：2026-10-29。助手此前只把每轮对话当作普通文本请求，未使用供应商已经提供的上下文缓存、结构化输出、原生 function calling 与联网搜索；本次按「最高 / 高 / 中」价值接入，同时保持既有 JSON envelope 协议与全部旧测试不变。
- 能力检测：新增 `backend/app/llm_capabilities.py`，按 `catalog_provider_key(base_url)` 与模型类型判断。百炼（dashscope）不分模型名：所有文本对话模型默认开放原生工具、联网搜索、JSON 模式与缓存，qwen3 及 qwen≥3.5 优先 `json_schema`，较早模型用 `json_object`，显式缓存按 qwen-plus / qwen-max / qwen≥3.5 判断，其余按隐式缓存；具体模型缺某项能力时由运行时拒绝降级兜底。DeepSeek、SiliconFlow 使用隐式缓存与 `json_object`；ModelScope 聚合网关不启用原生工具；智谱、Ollama 与自定义地址按模型名保守判断。视觉 / 音频 / 嵌入 / 重排 / 视频模型一律不启用可选项。
- 请求层：`llm_client.py` 增加可选 `response_format`、`tools`、`enable_search`、`cache_control`（DashScope 显式缓存，只标记最后一条非工具消息的文本块）与 `stream_options.include_usage`；上游以 4xx 拒绝可选字段时抛出 `LlmCapabilityError(field)`，服务层一次只去掉一个字段重试，并按 `base_url|model` 在进程内记住降级，重启后端后重新探测。非流式回退、SSE 结束与 90 秒空闲超时保持原样。
- 协议：`protocol.py` 保留原 JSON envelope 提示词与解析，新增 `NATIVE_SYSTEM_PROMPT`、10 个原生工具（知识检索 / 读取、工程读取、Skill 参考、草稿、媒体提案、剪辑读取 / 提案、提问、引用）与 `ASSISTANT_RESPONSE_SCHEMA`；原生 `ask_question` / `cite_sources` 会归一为既有 `question` / `citation_ids`，澄清卡、引用与草稿采纳逻辑不变。`ASSISTANT_RESPONSE_SCHEMA` 不启用 `strict`，因为工具参数与草稿 `data` 是自由对象。
- 助手服务：每轮开始时读取所选模型能力，只有 `native_tools=true` 才走原生工具消息；同时维护旧协议与原生工具两份消息列表，工具结果按 `tool_call_id` 回传，最多 8 轮。若上游忽略 `tools` 仍返回旧 envelope，或工具字段被降级，本轮立即回到旧协议继续，不丢内容。不支持能力的模型继续调用原 `assistant_chat`，请求与结果与改造前一致。
- 用户可见行为：输入框工具栏新增「联网」按钮，仅在当前模型开放搜索时可点；开启后本轮请求带 `enable_search`，回复下方显示「联网来源 · N 处」折叠列表。每轮结束显示「输入 / 输出 tokens · 缓存命中 · N 次请求」，仅对返回 usage 的模型显示。能力不支持或上游拒绝时自动关闭对应能力，不改变回复可用性。
- 兼容性：不新增 API 路由、数据库表 / 列、任务队列、ComfyUI 节点、工作流 graph 或前端路由；`selections` 只新增可选 `web_search`（缺省 `false`）；目录接口只新增 `capabilities`；消息块只新增 `usage` 与 `web_search` 两种，旧客户端忽略未知块。媒体任务、媒体提案、项目写锁与旧 AI 操作接口不变。
- 受影响文件：`backend/app/{llm_capabilities,llm_client,llm_provider}.py`、`backend/app/director_assistant/{protocol,service}.py`、`backend/tests/{test_llm_capabilities,test_director_assistant}.py`、`frontend/src/director2/assistant/{api.ts,DirectorAssistant.tsx,assistant.css}`、`.gitignore`（放行新测试文件）、`docs/API.md`、`docs/导演台流程与界面结构.md`、`docs/导演台智能助手V2.md`、README 与本文件。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_director_assistant backend.tests.test_llm backend.tests.test_llm_capabilities backend.tests.test_editing_assistant -q`（208 项通过，57.9 秒）；`pnpm --dir frontend test`（69 个文件 / 484 项通过）；`pnpm --dir frontend build`（TypeScript、clean-dist、Vite 构建通过，10.08 秒，仅保留既有大 chunk 提示）。真实 5173 桌面浅暗主题：`qwen3.8-max` 下「联网」可点并显示提示，选中为绿色底与 ink 文本，刷新后保持，再次点击关闭恢复；目录接口对 3 个可选模型返回 dashscope / 原生工具 / json_schema / 显式缓存 / 联网搜索能力；能力检测单测覆盖 qwen-long、kimi、MiniMax、qwq 等非 Qwen 命名的百炼文本模型，均开放原生工具、联网与 JSON 模式，多模态模型仍不启用。本轮未调用真实 LLM，tokens / 缓存命中行与联网来源列表由单元测试覆盖，未计为真实回复验收；未触发媒体任务、未切换 ComfyUI、未访问真实 MySQL。
- 回滚方式：删除 `backend/app/llm_capabilities.py`，撤回 `llm_client.py` / `llm_provider.py` 的可选字段、降级重试与 `assistant_chat_with_meta`，撤回 `protocol.py` 的原生提示与工具定义、`service.py` 的能力分支，撤回前端 `web_search` / `usage` 块与工具栏按钮后重启后端并重新构建。`selections.web_search` 与已保存的 usage / 来源块可留在会话 JSON 中，旧客户端忽略，无需数据迁移。

## 2026-10-30 智能助手默认分段出片（整集出片改到剧集工坊）

- 日期与原因：2026-10-30。上一个改动在创作流程卡同时提供整集与分段两条出片路径且默认整集。用户确认「默认分段出片」，并指出整集出片不必在智能助手里实现、手动在剧集工坊操作更好：助手内的整集入口与工坊「一键生成视频」重复，且整集任务必须等全部分段完成才能看到结果，无法逐镜预览。
- 用户可见行为：流程卡不再显示「整集出片 / 分段出片」切换。目标分集就绪且素材齐全时，标题「分段提交逐镜任务」、说明「为 N 个镜头各提交一个独立任务，可在工坊逐个查看和重做；整集出片请在剧集工坊手动操作。」、主按钮「提交 N 个逐镜任务」；存在可自动补齐的素材缺口时标题「补齐出片素材」、主按钮「补齐素材并分段出片」；无法自动修复时主按钮仍为「去工坊处理」。确认框标题「确认提交分段出片？」，正文为一次性提交 N 个逐镜任务、工作流与参数摘要、「每个镜头独立出片并独立计费，全部完成后可在工坊合成整集」，以及任务会排队执行、可在「全部任务 → 视频生成」分别查看；确认后只调用逐镜接口。左侧「进入工坊」保留为整集出片与逐镜检查的手动入口。提交中进度、部分失败重试、活跃整集任务阻断、跳过已有成片与在途镜头的规则保持不变。
- 实现：`WorkflowProgressCard.tsx` 删除 `shootMode` 状态、Ant Design `Segmented` 与整集提交分支，`shootEpisode` 固定走逐镜路径；`episode-shoot.ts` 删除 `EpisodeShootMode` 类型、`episodeShootSummary`、`episodeShootConfirmLines` 与 `durationLabel`；`workflow-progress.ts` 的 `open-workshop` 动作标题 / 说明 / 按钮改为分段提交；`assistant.css` 删除 `.assistant-shoot-mode` 样式。逐镜提交器 `episode-shot-tasks.ts`、前置检查 `episode-shoot-preflight.ts` 与素材补齐 `episode-shoot-prep.ts` 未改动。
- 受影响文件：`frontend/src/director2/assistant/WorkflowProgressCard.tsx`、`episode-shoot.ts`、`episode-shoot.test.ts`、`workflow-progress.ts`、`workflow-progress.test.ts`、`assistant.css`；`README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。
- 兼容性：不新增后端路由、数据库字段、任务队列、ComfyUI 节点、工作流 graph、权限或依赖；逐镜提交复用工坊单镜出片接口，整集出片仍由工坊「一键生成视频」调用 `POST /episodes/{episode_id}/generate-video`。流程卡不再创建整集任务，已提交的整集或逐镜任务不受影响；`EpisodeShootMode` 等删除项均为前端内部符号，不涉及持久化数据。
- 验证命令：`pnpm --dir frontend test`（75 个测试文件 / 539 项通过）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build`（仅保留既有大 chunk 提示）通过。5173 桌面端在工程 `proj-4185149f8672474d` 第 1 集（11 镜、素材已就绪）实测：流程卡显示 `4/4`，不再有出片方式切换，标题「分段提交逐镜任务」、说明「为 11 个镜头各提交一个独立任务，可在工坊逐个查看和重做；整集出片请在剧集工坊手动操作。」、按钮「进入工坊」「提交 11 个逐镜任务」；点击主按钮弹出「确认提交分段出片？」，正文为 11 个逐镜任务、`H3 Director 加速版 多参考视频 · 逐镜任务 · 16:9 · 0.4 MP · 完整`、独立计费与排队说明；点「取消」后网络面板只有分集、资产、任务、`/api/modes` 等 GET 请求，没有 `POST /beats/{beat_id}/generate-video` 或 `POST /episodes/{episode_id}/generate-video`，未创建任何任务。验证期间发现 5173 的 Vite 进程自 14:26 起停止热更新并持续返回旧组件（控制台 `ReferenceError: shotsMode is not defined`），重启开发服务器后恢复，未修改业务逻辑；内置浏览器不可见（`visibilityState=hidden`），验证基于 DOM 与网络请求完成。未提交真实出片、未调用模型或 GPU，未做移动端检查。
- 回滚方式：恢复 `WorkflowProgressCard.tsx` 的出片方式状态、`Segmented` 与整集提交分支，恢复 `episode-shoot.ts` 的 `EpisodeShootMode` / `episodeShootSummary` / `episodeShootConfirmLines` 及对应测试，恢复 `workflow-progress.ts` 的整集文案与 `assistant.css` 的 `.assistant-shoot-mode` 后重新构建前端；不涉及后端、数据库、任务队列或 ComfyUI，已提交任务保持原状。

## 2026-10-30 智能助手支持整集 / 分段出片（已被同日「默认分段出片」取代）

- 日期与原因：2026-10-30。创作流程卡此前只调用 `POST /episodes/{episode_id}/generate-video` 提交一个整集任务，整集工作流（如「H3 Director 加速版 多参考视频」）要等全部分段完成后才能看到结果，用户无法先检查单个镜头。用户要求助手内可选择「整集出」或「分段出」，并明确「分段提交 = 一次性提交 N 个视频生成任务，每集可以单独查看」。本节的选择器已下线，当前行为见上方同日期章节。
- 用户可见行为：目标分集就绪后，流程卡在步骤条与动作区之间新增 Ant Design `Segmented`「整集出片 / 分段出片」，默认整集出片，行为与之前完全一致；分段出片时说明改为「每个镜头单独一个任务，可分别查看」，标题为「分段出片」、说明为「为 N 个镜头各提交一个独立任务，可分别查看和重新生成。」、主按钮为「提交 N 个逐镜任务」。确认框标题「确认提交分段出片？」，正文依次为一次性提交 N 个逐镜任务（每个镜头可单独查看和重新生成）、工作流与参数摘要、「每个镜头独立出片并独立计费，全部完成后可在工坊合成整集」，以及任务会排队执行、可在「全部任务 → 视频生成」分别查看。提交中按钮显示「提交中 i/n」、说明显示「正在提交第 i/n 个任务：Beat X」；部分失败时卡片常驻「有 N 个镜头未提交」清单（最多 3 行），按钮变为「重试未提交镜头（Y）」，再次点击只补交失败镜头；全部成功提示「已提交 N 个逐镜任务，可在工坊分别查看」并跳转该集镜头页；所有镜头都已有成片或正在生成时提示并跳转工坊。
- 实现：新增纯函数模块 `frontend/src/director2/assistant/episode-shot-tasks.ts`。`ACTIVE_VIDEO_STATUSES` 与后端 `episode_video_service._ACTIVE_VIDEO_STATUSES` 保持一致，`activeEpisodeVideoJobs(jobs, episodeId)` 从既有 `listJobs` 的 slim 数据（`payload.render_scope` / `beat_id` / `beat_ids`）识别同一分集进行中的整集 / 合成任务（作为阻断项）和逐镜 / 选中镜任务（作为在途镜头）；`submitEpisodeShotTasks` 按 Beat 序号去重排序，跳过已生成 `video_url`、本次会话已提交和活跃在途的镜头，逐个调用既有 `POST /api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-video`，单个失败不中断并返回任务 ID、已提交镜头与失败明细。`WorkflowProgressCard.tsx` 增加出片方式状态、会话内已提交 `ref`、提交进度与常驻失败清单；分段模式在提交前和素材补齐后各读取一次 `listJobs` 重新判定，若存在进行中的整集 / 合成任务则提示「该分集已有进行中的视频任务 …，请等待完成后再提交分段任务」并停止；素材补齐仍复用 `prepareEpisodeShootAssets`，两种模式共用同一套工作流与工坊已保存参数。`assistant.css` 增加 `.assistant-shoot-mode` 样式。
- 受影响文件：`frontend/src/director2/assistant/episode-shot-tasks.ts`、`episode-shot-tasks.test.ts`、`episode-shoot.ts`、`episode-shoot.test.ts`、`WorkflowProgressCard.tsx`、`assistant.css`；`docs/导演台流程与界面结构.md` 与本文件。
- 兼容性：不新增后端路由、数据库字段、任务队列、ComfyUI 节点、工作流 graph、权限或依赖；分段提交复用工坊单镜出片接口，生成的是标准 `shot` 作用域任务，成功后在 `beat.video_url` 回写成片，与工坊逐镜生成完全一致。后端仍在 `_assert_can_enqueue` 中保证整集 / 合成任务执行期间拒绝任何新任务、同一镜头的逐镜任务不重复，并在 `_prepare_shots` 中再次校验场景主视图与角色造型；前端的三层防重（按钮锁定、会话内已提交集合、提交前重新读取活跃任务）只用于减少无效请求，不替代后端校验。默认整集模式保持不变，用户不切换时行为与旧版一致。
- 验证命令：`pnpm --dir frontend test`（75 个测试文件 / 540 项通过，新增逐镜任务提交器 7 项覆盖活跃任务识别、按序号提交、跳过已生成 / 指定 / 在途镜头、单镜失败继续、缺少 `job_id` 视为失败、空输入；出片计划 7 项新增分段确认文案）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build` 通过。5173 桌面端以真实登录态在工程 `proj-4185149f8672474d` 第 1 集（11 镜、素材已就绪）用 `window.fetch` 拦截逐镜与整集出片 POST（返回假 `job_id`，不触发生成）实测：Segmented 显示「整集出片 / 分段出片」且默认整集；切到分段后按钮为「提交 11 个逐镜任务」，确认框文案与上述一致；确认后恰好发出 11 个 `POST /beats/{beat_id}/generate-video`、0 个 `POST /episodes/{episode_id}/generate-video`，成功提示出现并跳转该集镜头页；随后让 `/jobs` 返回真实活跃整集任务 `job-f192bd794c2a` 再点分段提交，出现「该分集已有进行中的视频任务 job-f192bd794c2a，请等待完成后再提交分段任务」且没有新增任何 POST。验证后已还原 `window.fetch` 并清理测试全局；MySQL 任务表没有新增视频任务（仍只有原有整集任务 `job-f192bd794c2a`）。后端全量 `python -X utf8 -m unittest discover -s backend/tests -p "test*.py"` 运行 1113 项，仅有 3 项与本改动无关的既有失败（`test_director` 场景连续性英文断言、`test_mcp_gateway` 工具数 22 vs 20、`test_media_studio_schema` 缺少 `job_rounds` 夹具），本次未改后端。未做移动端检查。
- 回滚方式：删除 `episode-shot-tasks.ts` 及其测试，撤回 `episode-shoot.ts` 的分段确认文案与测试，撤回 `WorkflowProgressCard.tsx` 的出片方式状态、`listJobs` 判定、逐镜提交分支与失败清单，以及 `assistant.css` 的 `.assistant-shoot-mode` 后重新构建前端；不涉及后端、数据库、任务队列或 ComfyUI，已提交的整集或逐镜任务保持原状。

## 2026-11-01 生成页新增「提示词反推」（图生提示词）

- 日期与原因：2026-11-01。用户要求新增提示词反推功能。生成页此前只有从文字到提示词的润色链路，缺少"看到一张好画面却写不出提示词"的入口；现在把已有的 VLM 看图分析链路包装成生成页能力：上传/粘贴一张参考图，反推出可直接用于生成的中文与英文提示词并一键填入创作框。
- 用户可见行为：生成页创作框工具栏在「灵感」旁新增「反推」按钮（图标 `ScanSearch`）。点击打开 Ant Design 弹窗「提示词反推」：顶部 `Segmented` 切换「视频提示词 / 图片提示词」（默认跟随当前创作类型），中部拖拽/点击/粘贴（`Ctrl+V`）上传一张 ≤8MB 图片（可更换、移除），可选「补充要求」（≤200 字），点「开始反推」调用视觉模型；成功后弹窗内显示可编辑的「中文提示词（填入创作框）」与「英文提示词（生成时提交）」，各带复制按钮，「重新反推」可换图重来，「填入创作框」把中文填入提示词输入框并关闭弹窗。视频模式下同时登记英文对照（复用「润色」的 `optimizedPrompt` 机制：生成提交英文、界面显示中文、「查看英文」可对照，手动改动文本后自动失效）；图片模式只填中文。看图模型未配置时按钮禁用并以 Tooltip 提示配置入口；上游报错在弹窗内以 Alert 原样展示。
- 实现：`backend/app/llm_client.py` 新增 `SYSTEM_PROMPT_REVERSE_VIDEO` / `SYSTEM_PROMPT_REVERSE_IMAGE` 与 `OpenAICompatibleClient.reverse_generation_prompt`（单图多模态请求，要求返回 JSON `{"chinese_prompt","english_prompt"}`，兼容 ```json 围栏与前后缀文本，双语互为回退，`temperature=0.4`、`max_tokens=1024`、复用 `LLM_OPTIMIZE_TIMEOUT_SECONDS`）；`backend/app/vlm_provider.py` 新增 `VlmProviderService.reverse_prompt`（走既有 `resolve_analysis_endpoint`：VLM 优先、可看图 LLM 兜底，与主体分析同一路由）；`backend/app/models.py` 新增 `PromptReverseResponse`；`backend/app/main.py` 新增 `POST /api/llm/reverse-prompt`（multipart：`image` + `media_type`（`video|image`，缺省 `video`）+ `hint`（≤200 字），图片 ≤8MB 且必须 `image/*`，未配置看图模型返回 503，写 `reverse_prompt` 审计）。前端新增 `frontend/src/prompt-reverse.ts`（校验、请求与响应归一化）与 `frontend/src/components/PromptReverseModal.tsx`（Ant Design Modal + Segmented + 原生文件入口/拖拽/全局粘贴监听，`--studio-*` 语义变量适配双主题）；`frontend/src/App.tsx` 工具栏按钮按 `/api/llm/status` 的 `analysis_vision.available` 门控，`applyPromptReverse` 复用 `optimizeUndo` / `optimizedPrompt` 既有状态机。
- 受影响文件：`backend/app/{llm_client,vlm_provider,models,main,api_documentation}.py`、`backend/tests/test_prompt_reverse.py`（新增）、`frontend/src/prompt-reverse.ts`、`frontend/src/prompt-reverse.test.ts`（新增）、`frontend/src/components/PromptReverseModal.tsx`（新增）、`frontend/src/App.tsx`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 与本文件。
- 兼容性：新增一个独立接口与一个弹窗组件，不改既有接口、数据库、任务队列、ComfyUI 节点或工作流协议；`PromptReverseResponse` 为新增响应模型，旧客户端不受影响。看图路由与 `analyze-subject` 完全一致，`analysis_vision` 不可用时只影响新按钮而不影响既有功能。不新增依赖。
- 验证命令：`python -m pytest backend/tests/test_prompt_reverse.py backend/tests/test_vlm.py -q`（32 项通过）；`python -m pytest backend/tests -q`（1174 项全部通过）；`pnpm --dir frontend test`（77 文件 / 565 项通过，新增 `prompt-reverse.test.ts` 6 项）；`pnpm --dir frontend build`（TypeScript、clean-dist、Vite 通过）。真实 5173 桌面端（登录态、1440×900）：「反推」按钮出现在视频与图片创作类型工具栏，弹窗支持粘贴上传（预览/更换/移除）、「开始反推」真实调用后上游报错（`model is not supported by TokenPlan`，与既有 `analyze-subject` 同源的上游套餐限制）在 Alert 中原样展示；页内拦截该接口返回样例后验证成功链路——中/英文提示词展示、复制、重新反推、填入创作框后输入框回填中文、「查看英文」出现；暗色与浅色主题弹窗均已截图核对。验证用临时会话已吊销、临时测试账号已删除、页面状态（主题/草稿）已还原；未创建生成任务。
- 回滚方式：删除 `frontend/src/prompt-reverse.ts`、`prompt-reverse.test.ts`、`components/PromptReverseModal.tsx`、`backend/tests/test_prompt_reverse.py`，撤回 `App.tsx` 的按钮/状态/导入、`llm_client.py` 的两条 system prompt 与 `reverse_generation_prompt`、`vlm_provider.py` 的 `reverse_prompt`、`models.py` 的 `PromptReverseResponse`、`main.py` 的路由与导入、`api_documentation.py` 的字段说明后重启后端并重新构建前端；无数据迁移。

## 2026-11-01 提示词反推从生成页工具栏迁入「AI 工具」中心

- 日期与原因：2026-11-01。用户反馈同日上午上线的「反推」入口放在生成页创作框工具栏不合适，应像即梦一样做成独立工具（后续还会加入动作迁移等工具），因此迁移为「AI 工具」工作区，并把工具注册表做成可扩展结构。
- 用户可见行为：左侧图标导航在「画布」与「资产」之间新增「工具」（路由 `/tools`，Guest 点击打开登录弹窗，直接访问 `/tools` 未登录会被重定向登录）。`/tools` 为工具中心卡片页（渐变封面 + 图标 + 标题 + 描述，当前仅「提示词反推」一张卡）。`/tools/prompt-reverse` 为独立工具页：返回链接 + 头部卡（图标 + 标题 + 描述）+ 大虚线上传区（拖拽 / 点击 / 粘贴 Ctrl+V，「从本地上传」「从资产选取」两个按钮），选中图片后进入预览卡（更换/移除、反推目标 Segmented、补充要求、开始反推），结果区为可编辑的中英文提示词（复制、重新反推、填入创作框）。「从资产选取」弹窗拉取 `/api/jobs` 的最近图片输出（≤48 张，按 `download_url` 同源读取为 File）。点「填入创作框」回传 App：同媒体直接填中文提示词并跳转生成页；跨媒体走 `pendingMediaDraftRef` 草稿（默认目标媒体工作流、清空参考图）后跳转，提示词只填中文（H3 规范英文仍由「润色/自动优化」链路生成）。生成页首页「创作工具」门廊卡下方新增一行「AI 工具」紧凑入口卡；生成页创作框工具栏的「反推」按钮与旧弹窗移除。看图模型未配置时工具页显示 Alert 并禁用开始反推。
- 实现：`frontend/src/paths.ts` 新增 `PATHS.tools` / `PATHS.toolPromptReverse`、`StudioWorkspace` 增加 `"tools"`、`studioWorkspaceFromPath` 识别 `/tools` 前缀、`STUDIO_ROUTE_PATHS` 注册两条路由；`frontend/src/components/StudioSymbols.tsx` 新增 `tools` 导航符号（四宫格）；新增 `frontend/src/tools/` 模块：`tool-registry.ts`（工具注册表：id/title/description/tagline/path/icon/accent/status，`status: "coming_soon"` 不参与路由与展示，供动作迁移等后续工具登记）、`tool-icons.ts`（图标键映射）、`ToolsHome.tsx`（工具中心）、`PromptReverseTool.tsx`（工具页，复用 `prompt-reverse.ts` 的校验/请求/归一化）、`AssetPickerModal.tsx`（资产选取）、`ToolsWorkspace.tsx`（按路径分流）、`tools.css`（`--studio-*` 语义变量，双主题）；`frontend/src/tools.test.ts`（注册表契约与路径映射）；`App.tsx` 删除工具栏反推按钮、`promptReverseOpen` 状态与 `PromptReverseModal` 渲染，`applyPromptReverse` 改为 `sendPromptToComposer`（含跨媒体草稿），渲染分支新增 `workspaceView === "tools"`，主内容容器加 `studio-tools-main`；`GenerationHomeSections.tsx` 门廊卡下新增工具入口条（Guest 走 `onRequestLogin`）；`generation-home.css` 增加入口条样式。`frontend/src/components/PromptReverseModal.tsx` 删除。后端接口 `/api/llm/reverse-prompt` 无任何变化。
- 受影响文件：`frontend/src/{paths.ts,App.tsx,tools.test.ts}`、`frontend/src/components/StudioSymbols.tsx`、`frontend/src/components/PromptReverseModal.tsx`（删除）、`frontend/src/tools/`（新增 6 个文件）、`frontend/src/generation/{GenerationHomeSections.tsx,generation-home.css}`、`docs/API.md`、`README.md`、`功能说明与扩展指南.md` 与本文件。
- 兼容性：仅前端路由与组件层变化，后端接口、数据库、任务队列、ComfyUI、工作流协议不变；`/tools` 未纳入游客白名单，未登录访问统一登录引导。生成页 composer 行为与此前一致（仅少了反推按钮）；`sendPromptToComposer` 跨媒体复用既有 `pendingMediaDraftRef` 机制，不改变草稿语义。不新增依赖。
- 验证命令：`pnpm --dir frontend exec tsc -b` 通过；`pnpm --dir frontend test`（78 文件 / 569 项通过，新增 `tools.test.ts` 4 项：`/tools` 前缀映射、注册表路径唯一、不可用工具不可路由、未知路径返回 null）；`pnpm --dir frontend build` 通过。真实 5173 桌面端（登录态 1440×900）：侧边栏「工具」入口与四宫格符号正常高亮；`/tools` 卡片页与 `/tools/prompt-reverse` 头部卡 + 大上传区按暗色主题渲染；「从资产选取」弹窗列出真实资产（橘猫图、镜头草图、道具图）且点选后带入预览；拦截 `/api/llm/reverse-prompt` 返回样例后反推结果可编辑、可复制，「填入创作框」跳转 `/generate/video` 且中文提示词已回填；生成页首页工具入口条出现且创作框工具栏不再有反推按钮；浅色主题工具页截图核对后已还原暗色主题并清空页面状态。未创建生成任务，未做移动端检查。
- 回滚方式：删除 `frontend/src/tools/` 目录与 `frontend/src/tools.test.ts`，恢复 `components/PromptReverseModal.tsx`，撤回 `paths.ts`（tools 路由与工作区）、`App.tsx`（导航/渲染分支/`sendPromptToComposer`）、`StudioSymbols.tsx`（tools 符号）、`GenerationHomeSections.tsx` 与 `generation-home.css`（工具入口条）的增量后重新构建前端；后端无改动、无数据迁移。

## 2026-11-02 工具中心与生成页首页「即梦式」视觉改版（照片封面 + 翻页多功能墙）

- 日期与原因：2026-11-02。用户认为首版工具中心过空、与即梦差距大，连续四轮用 OpenAI Images API 以「即梦真实界面 + 本系统实拍」为参考图迭代设计稿（设计稿与参考图存 `tmp/jimeng-tools-design/`，gitignore），确认 v3（工具中心分组照片封面卡）+ v5-04（首页三列多功能区 + 翻页墙）+ v2（反推工具页居中 hero）后按稿实现；封面虚化强度用户保留后续单独调整的权利。
- 用户可见行为：①`/tools` 工具中心改为居中大标题「创作所需 一应俱全」+ 分类 chips（全部/精选/视频/图片/效率）+ 分组竖版卡片（照片封面在上、名称/描述在下、状态角标「可用/即将上线/规划中」），底部虚线「更多工具陆续接入」占位条；②生成页首页原「导演台大卡 + 图片生成/无限画布 + AI 工具入口条」合并为三列多功能区：导演台通高照片卡独占一列、图片生成与无限画布横卡（封面右侧窄幅左渐隐）占一列、右侧为 AI 工具翻页墙——一页 2×2 共 4 张 + 右缘半张卡渐隐暗示，悬停显示圆形玻璃箭头（第一页仅右箭头，滚动后左右双箭头；左缘渐隐仅滚动后出现），提示词反推与动作迁移为深青高亮卡；③`/tools/prompt-reverse` 头部改为居中渐变艺术横幅 + 居中标题/描述，上传区与结果区改为卡片化（结果区外层卡片 + 内嵌画布色块、无内边框输入）。移动端未检查（仅桌面端）。
- 实现：`frontend/src/tools/tool-registry.ts` 扩展为 `category`（featured/video/image/efficiency）、`cover`（`/tool-covers/*.jpg`）、`highlight`、三态 `status`（available/coming_soon/planned）并新增 `TOOL_STATUS_LABEL` / `TOOL_CATEGORY_LABEL` / `TOOL_CATEGORY_ORDER` / `toolsByCategory` / `wallTools`（占位工具登记唯一 path 但不可路由）；`tool-icons.ts` 增加 `generic` 键；`ToolsHome.tsx` 重写为 chips + 分组竖版卡；`tools.css` 重写（hub v2、工具页渐变 hero、结果卡片化）；`PromptReverseTool.tsx` 换居中 hero、TextArea 改 `variant="borderless"`；`GenerationHomeSections.tsx` 重写为 `studio-home-featurezone` 三列结构 + `FeatureWall` 组件（横向 scroll-snap 滚动容器 + onScroll 同步左右渐隐/箭头可见性 + 末列「更多工具陆续接入」占位卡，Guest 点击可用工具走登录引导）；`generation-home.css` 删除旧 doorways/入口条样式，新增三列区、翻页墙、渐隐遮罩与箭头样式（`--studio-canvas` 渐变遮罩、`--studio-chrome` 玻璃箭头）；`index.css` 新增 `--studio-teal-wash` / `--studio-teal-edge` 双主题 token；封面素材 10 张置于 `frontend/public/tool-covers/`（OpenAI Images API `gpt-image-2.5-flare` 1536x864 生成，无文字）。后端零改动。
- 受影响文件：`frontend/src/{index.css,tools.test.ts}`、`frontend/src/tools/{tool-registry.ts,tool-icons.ts,ToolsHome.tsx,PromptReverseTool.tsx,tools.css}`、`frontend/src/generation/{GenerationHomeSections.tsx,generation-home.css}`、`frontend/public/tool-covers/`（新增 10 张封面）、`README.md`、`功能说明与扩展指南.md` 与本文件。
- 兼容性：路由、后端接口、数据、依赖不变；`availableTools()`/`toolFromPath()` 契约保持（占位工具不可路由），`accent` 字段删除（无引用）。滚动箭头用原生 scroll + snap，不新增依赖；`:focus-within` 保持键盘可达。窄于 1180px 时多功能区折叠为两行两列（仅兜底，桌面端为主）。
- 验证命令：`pnpm --dir frontend exec tsc -b` 通过；`pnpm --dir frontend test`（78 文件 / 571 项通过，新增注册表 cover/category/highlight 契约 2 项）；`pnpm --dir frontend build` 通过。5173 桌面端实测（1536×864，e2e 会话登录后已吊销）：暗色工具中心分组/chips/占位条、反推页渐变 hero、首页三列区与翻页墙（第一页仅右箭头、点击后双箭头 + 左缘渐隐）、浅色主题两页均核对；封面图片全部加载。
- 回滚方式：撤回上述前端文件增量（恢复 doorways 与入口条样式/JSX），删除 `frontend/public/tool-covers/`；后端无改动、无数据迁移。


## 2026-11-02 线上 public 静态图片被 SPA 兜底吞掉（dist 根静态文件直出）

- 日期与原因：2026-11-02。用户部署到线上后反馈 `https://comfyui.zlyun168.com/generation-home/director-coast.png` 打不开、浏览器直接跳登录页。实测该 URL 返回 `200` + `Content-Type: text/html`、`cache-control: no-store`，正文是 `index.html`（1059 字节），即请求命中的是 SPA 兜底路由而不是图片。根因：`backend/app/main.py` 只对 `/assets/{file}` 提供文件，其余全部路径由 `GET /{path:path}` 回退 `index.html`，而 Vite 把 `frontend/public/` 原样复制到 **dist 根**（不在 `assets/` 下），所以线上所有 public 素材都拿不到字节；浏览器拿到 HTML 当作图片渲染失败，直接打开该 URL 则加载 SPA、路由不匹配 → `Root` 判定未登录跳 `/login`，看起来像「200 却跳登录」。本机 5173 由 Vite dev server 直接伺服 `public/`，因此只在本地正常、线上失效。线上实测同时受影响的还有 `/auth/cinematic-shore.webp`（登录页主视觉）、`/studio-icons/*`（品牌与侧栏图标）、`/assistant-covers/*`、`/tool-covers/*`、`/generation-home/*`。
- 当前基线：`backend/app/main.py` 新增 `dist_static_file(relative)`，把请求路径解析到 `settings.frontend_dist_dir` 之下，只接受真实存在的文件，并拒绝空路径、含空字节和越出 dist 根的 `..` 逃逸（`resolve()` 后校验 dist 根为父目录）。`GET /assets/{asset_path:path}` 改为复用它；`GET /{path:path}` 先尝试 dist 根静态文件（`index.html` 除外，保持 `no-store` 语义），命中则用显式 `ASSET_MEDIA_TYPES` 返回（新增 `.png/.jpg/.jpeg/.webp/.gif`，避免依赖容器内 `mimetypes` 对 WebP 的猜测），未命中才回退 SPA 外壳。精确路径 `/assets` 与无文件扩展名的前端路由（`/generate/video`、`/director/:id`）行为不变；Nginx 与 Dockerfile 无需改动（`COPY --from=frontend-builder /build/frontend/dist frontend/dist` 本就带上了 public 素材）。静态文件不加长缓存头：`public/` 文件名无内容哈希，重新部署后需能立即更新。
- 责任边界（不是 Nginx，也不是前端工程配置）：`docker/nginx/zly-ai-video-studio.conf.example` 的 `location /` 全量代理到 `127.0.0.1:18189`，Nginx 侧没有静态 root，响应里的 `cache-control: no-store` 正是 FastAPI 兜底路由自己写的头，说明请求已经进到应用；`pnpm build` 也正常，`clean-dist` 后 `public/` 会原样出现在 `frontend/dist/` 根（本机 `frontend/dist/generation-home/director-coast.png` 存在且已入库），镜像构建阶段直接 COPY 该目录。因此修复点只在应用路由，Nginx、Vite 配置和打包流程都不需要动。
- 受影响文件：`backend/app/main.py`、`backend/tests/test_ai_studio.py`（`FrontendSpaFallbackTests` 新增 public 子目录图片直出与 `..` 逃逸断言）、本文件、`功能说明与扩展指南.md`。
- 兼容性：不新增/删除 API，不改数据库、任务队列、工作流、ComfyUI、认证与前端代码；`/api/*` 精确路由优先级不变（注册顺序在前）。旧镜像行为可回退。线上需重新构建镜像并重跑 `deploy-server-image.sh`（或等效的 `docker load` + `docker compose up -d --no-build --force-recreate`）才生效。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_ai_studio.FrontendSpaFallbackTests -q`（通过：`/generation-home/director-coast.png` 返回 `image/png` 与原字节；`/generation-home/%2e%2e%2f%2e%2e%2f%2e%2e%2foutside-dist.txt` 这类解析到 dist 根之外的路径拿不到文件内容，只回退 SPA 外壳——实测路由收到的 path 参数已百分号解码为 `../../../`，因此该断言确实覆盖逃逸分支）；以真实 `frontend/dist` 复核 `dist_static_file()` 解析与逃逸判定。部署后线上复验：`curl -I https://comfyui.zlyun168.com/generation-home/director-coast.png` 应为 `image/png` 而不是 `text/html`。
- 回滚方式：还原 `main.py` 中 `ASSET_MEDIA_TYPES`、`dist_static_file()`、`frontend_asset()`、`frontend()` 四处与本测试断言，重新构建镜像即可恢复原行为；无数据迁移。

## 2026-11-02 数字人口播明确排除在二采精修契约之外

- 日期与原因：2026-11-02。`backend/tests/test_h3_refine.py` 的选项契约测试按 `H3_WORKFLOWS` 全量参数化，`minimax-h3-avatar` 入表后 5 项 subTest 报 `KeyError: 'refine_enabled'`。排查确认这不是注册表漏配：`comfy_service.py:1291` 只要 `refine_enabled` 为真就改走 `build_minimax_h3_refine_workflow()`，而该图是 Director 两段式（`MiniMaxH3Director` + `MiniMaxH3DirectorGroupImageToVideo/ReferenceToVideo`），只有 `LoadImage` 参考媒体、没有 `LoadAudio`/`MiniMaxH3AudioWindowT8`/`MiniMaxH3AudioConditioningT8`，二采 `build_refine_nodes()` 的 `task_type` 也只支持 T2V/I2V/FL2V/R2V，不处理 avatar 的 AV latent。给 avatar 补上开关会让口播任务静默丢掉音频驱动、音轨变成模型自生成；且 T8 条件节点画布上限 1344×768（≈0.98 MP），2.0 MP 目标本就不可达。因此按「守卫」而非「补参数」收口。
- 当前基线：`workflow_registry.py` 新增 `H3_REFINE_WORKFLOWS = H3_WORKFLOWS - {JobMode.MINIMAX_H3_AVATAR}`，把「哪些 H3 工作流支持二采」变成显式契约（`H3_WORKFLOWS` 仍表示 H3 全家，用于分组与校验）。`H3_REFINE_OPTION_NAMES`（`refine_enabled` / `refine_quality` / `refine_quality_mode` / `refine_preview`）集中声明二采入参；`normalize_options()` 的 avatar 分支在调用 `_normalize_schema_options()` 前拦截这组键，抛出「数字人口播暂不支持二采精修：二采改用 Director 管线，会脱离口播音频驱动。」（→ 422），替代原先笼统的「当前工作流不支持参数」。`minimax_h3_refine_workflow.build_minimax_h3_refine_workflow()` 的模式守卫由 `H3_WORKFLOWS` 收紧为 `H3_REFINE_WORKFLOWS`，即使调用方绕过归一化也拿不到 Director 图。`AVATAR_OPTION_SCHEMA` 保持不变，前端创建栏按 schema 渲染，因此数字人口播不显示二采开关；`App.tsx` 切模式时 `setOptionValues(defaultOptionValues(workflow))` 且 `serializeOptionValues()` 只序列化当前 schema 的键，不会把上一个模式的 `refine_enabled` 带给 avatar。`episode_video_service.apply_confirmed_video_resolution()` 只在调用方已开启二采时改 `refine_quality`，不会为 avatar 打开二采。需要更清晰的口播成片走既有的成片手动超分（RTX VSR / SeedVR2）。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_refine_workflow.py`、`backend/tests/test_h3_refine.py`（5 处参数化改为 `H3_REFINE_WORKFLOWS`，新增 `test_avatar_stays_out_of_the_two_pass_contract`）、`backend/tests/test_core.py`（任务详情 `request_parameters` 的参考位标签断言按注册表现名「参考素材」对齐）、`backend/app/api_documentation.py`、`docs/API.md`、`README.md`、本文件、`功能说明与扩展指南.md`。
- 兼容性：不改 API 路径与请求体结构、数据库、任务队列、ComfyUI 节点与模型路径，不新增依赖；其他 H3 工作流的二采行为与参数完全不变。旧客户端对 avatar 传 `refine_*` 从原先的通用「不支持参数」422 变为更明确的 422 文案，状态码不变。真正支持音驱二采（保留 T8 音频链做一采、二采只精修视频 latent 并沿用一采音轨）是后续独立迭代，需要远端实跑出片验证。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_h3_refine backend.tests.test_workflow_avatar backend.tests.test_rtx_vsr`（73 项通过）；`python -X utf8 -m unittest discover -s backend/tests -p "test*.py"`（全量回归，avatar 相关 5 个 error 已消除）。
- 回滚方式：还原上述两个后端文件与测试、文档增量即可恢复原状态；无数据迁移。若后续实现 AV 感知二采，应新增工作流模式而不是原地改 `minimax-h3-avatar` 的图，以免既有任务回显不一致。


## 2026-11-02 图片任务固定列宽与紧凑操作

- 日期与原因：2026-11-02。用户确认 v003 设计稿，要求按即梦的单张固定宽度展示图片，并检验各种原图比例。旧结果区按数量铺满一 / 两列且设置较大的固定高度；按钮的完整布局仅定义在浅色主题，暗色出现图标文字挤压。
- 当前基线：`ImageStudioModule.tsx` 的每张结果固定 252px 列宽，网格按可用桌面宽度换行；图片使用原图自然高度，不采用请求比例撑大或裁切。图片放大、下载、生成视频使用紧凑悬停 / 键盘焦点工具；比例至少 3:1 时将生成视频与顶部工具同排，避免短画面内工具重叠。过期与加载失败明确占位，不显示破图，不允许用失效图片生成视频。
- 轮次信息：新增 `ImageRoundHeader.tsx`，展示小参考图入口、两行提示词、注册表模型名、最多三项 primary 参数、轮次、状态、用时和 Ant Design 详细信息弹层；创作参数与折叠的运行参数分开。任务操作高 36px、间距 8px、圆角 8px，在两种主题下共用语义变量。旧浅色图片覆盖样式已移除，视频轮结构保持原协议。
- 布局与状态：沿用 `isComposerCompact`，仅为图片任务添加结果流 ResizeObserver，在图片自然高度加载或网格行数变化时重新计算停靠栏收起状态；监听随轮次销毁。停靠栏宽度按桌面导航实际宽度计算。图片卡新增的加载失败 / 超宽识别状态只存在组件内存，不新增持久化字段。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/src/media/ImageStudioModule.tsx`，新增 `frontend/src/media/{ImageRoundHeader.tsx,image-results.css,image-results.test.tsx}`；同步 `README.md`、`功能说明与扩展指南.md`、本文件和 `docs/design-ref-generation/image-task-20261102/DESIGN.md`。
- 兼容性：不改 API、路由、数据库、工作流注册表、ComfyUI 地址 / 节点 / 模型路径、任务队列及真实任务参数。旧任务无需迁移，原图 URL 和多图预览链路继续复用。没有新增依赖或部署第二套服务。
- 验证：`pnpm --dir frontend build`（测试、TypeScript、clean-dist 与 Vite）；`python -X utf8 -m unittest backend.tests.test_core backend.tests.test_job_list_payload backend.tests.test_ai_studio -q`（150 项通过）。5173 的 1536×864 和 1324×745 桌面逻辑视口，使用标签页内受控 API / SVG 测试图及一张原始拼图，核对 1:1、16:9、9:16、4:3、3:4、3:2、2:3、21:9、9:21、4:1、1:4，浅暗主题、4 / 8 张混合网格、大图切换、长提示词、参数层级、失效占位、重新编辑 / 再次生成接线和停靠栏避让。没有执行真实生图、数据库写入或移动端检查。详细尺寸记录见同轮 DESIGN.md。
- 回滚：仅撤回上述前端及文档的本轮增量，恢复原图片结果 / 头部 / 浅色图片样式并重新执行 `pnpm --dir frontend build`；不要覆盖工作区其他已有改动，无数据或 ComfyUI 迁移需要回滚。

## 2026-11-02 助手全链路实测暴露的四项提示词 / 造型判定缺陷修复

- 日期与原因：2026-11-02。用管理员账号把导演台助手链路 剧本 → 资产库 → 剧集工坊（H3 六段式提示词）→ 逐镜出片 → 合成 在真实数据上完整跑通（6/6 镜头出片 + 整集合成成片），视觉模型切到七牛云免费模型 `qiniu/conatus-free`。过程中暴露四项判定缺陷（舞台备注被当台词、引号台词被标签解析污染、单造型时代甄别过严、ComfyUI 报错不带节点名），全部是代码缺陷并已配测试；出片阶段另外撞到两处环境 / 架构问题：远端 ComfyUI 的失效 stderr（已在该机重启修复，见下）和共享库下的启动期全局任务清理（待决策）。
- 舞台备注（写作备注）统一判定：新增 `H3PromptBuilder.is_stage_note()` 与模块级 `_STAGE_NOTE_RE = ^[（(][^：:]*[)）]\s*$`，并在 `_clean_dialogue()` 入口把「整段被括号包住且内部没有说话人冒号」的 `dialogue`（如 `（无台词，仅内心活动暗示）`）清洗为空串。效果：该条不再进入 `skill_packs/handlers._required_speech_atoms` 的逐字校验，也不再被 `EpisodeVideoService._prepare_shots` 视为可配音台词。`episode_video_service` 原先自带一份同名局部正则，两处规则会漂移，现只保留 `H3PromptBuilder` 一处，`_prepare_shots` 改为调用 `H3PromptBuilder.is_stage_note`。
- 引号台词优先于标签回退解析：`H3PromptBuilder._parse_script_turns()` 的优先级由「回退结果达到 2 条即胜出」改为「行内引号轮次不少于回退轮次时直接采用引号结果；回退结果只有在轮次严格更多且不少于 2 条时才胜出」。旧的 `len(label_turns) >= 2` 判定会把下一位说话人的引号内容连同换行和 `名字：` 一起粘进上一条 turn，逐字校验因此要求原文中并不存在的碎片——实测 Beat 4 报「台词未逐字出现：”\n工作人员：“…」」；修复后同一条对白解析出 5 条干净 turn 并装箱通过。
- 单条造型的时代冲突回退：`EpisodeVideoService._select_character_look()` 在只有一条造型时不再无条件采用，也不再一律拒绝——`single_look_without_conflict(conflict)` 仅当该造型描述里没有出现相反时代线索（现代 ↔ `古代|长衫|粗布|发髻|17岁`）时才使用它；多造型仍按 `modern_look` / `ancient_look` 正则甄别，冲突或线索缺失时返回 `None`，由预检报「缺少造型图」。这样刚建好资产、只有一条「默认造型」的真实项目可以出片，同时保留 `LookSelectionTests.test_rejects_modern_shot_without_modern_look` 等原有约束。
- 失败文案带节点名：`ComfyVideoClient._history_error()` 读取 `execution_error` 详情里的 `node_type` 并前置，文案变为 `ComfyUI 执行失败: [MiniMaxH3Director 节点] <exception_message>`，避免只剩一句无法定位的 `[Errno 22] Invalid argument`。
- 视觉模型被真实调用的前提（排障基线）：`vision_status / vision_model / vision_image_count / vision_source` 只由 `vision_runtime.VisionCallMeta.as_dict()` 写入，且只在 `h3_prompt` 走到 `Ref2VA` + 技能包分支（`llm_service` 调 `skill_packs.run_workshop_prompt`）时产生；项目未绑定技能包时走纯文本装箱分支，看图根本不会发生，这些字段保持为空。绑定入口是 `PUT /api/projects/{pid}` 的 `extra.skill_pack_id`，由 `skill_packs/binding.resolve_skill_pack_id()` 读取。另注意 `vision_status="failed_text_fallback"` 表示视觉调用抛异常后被静默降级为纯文本。
- 远端渲染阻塞的根因与处置（环境侧，已修复）：6 个逐镜任务与 2 次单镜探针全部失败于实际生效的远端实例 `192.168.10.54:8188`（本机 192.168.10.32，ComfyUI 0.43.0，宿主便携包 `D:\ZlyFlow-ComfyUI-Portable-20260827-152136\Comfyui`）。`/history` 显示 `node_id=12`、`node_type=MiniMaxH3Director`、`executed=['14','1','3','2','15','4']`（UNET / CLIP / 双 VAE / SageAttention 补丁均已加载）、`OSError: [Errno 22] Invalid argument`，栈落在 `tqdm/std.py status_printer → sys.stderr.flush → Comfyui/app/logger.py:73 flush`。经该机的 SSH（`.ssh/config` 里的 `sfp-remote-dev`）核实：ComfyUI 挂在一条 `cmd.exe /c … --no-browser 2>&1` 的进程链上（`cmd 8372 → launch_comfyui.py 28804 → main.py 26848`），其父进程 5748 已退出，整条 stdout/stderr 变成失效管道，所以任何进入采样的节点一 flush 进度条就崩——与 graph、参考图、提示词 payload 无关。处置：确认 `/queue` 与 GPU 空闲后用 `taskkill /T /F` 终止该链，再以官方 `Start-ComfyUI.cmd` 的同参数命令行重新启动，并把 stdout/stderr 重定向到 `Comfyui\comfyui-console.log`；启动方式必须用 `Invoke-CimMethod Win32_Process Create`（父进程是 WmiPrvSE），因为 `Start-Process` 拉起的子进程仍属于 sshd 的作业对象，SSH 会话一关就跟着被杀（第一次重启就是这样死掉的）。重启后采样恢复正常，六镜全部出片。全程未切换 ComfyUI 地址、未另起第二套实例。
- 当时发现的共享库缺陷（同日已修，见下面「出片任务的实例归属与心跳租约」）：`recover_orphaned_jobs()` 只在 `main.py` 的 lifespan 启动时执行，且 UPDATE 不带任何实例归属条件，只按 `job_type='video_generation'` 和活跃状态过滤。本工作台连的是团队共享的远端 MySQL `ai-media`，因此**任何一套**后端实例启动都会把其它实例正在渲染的视频任务一律标成「服务进程重启，后台视频任务已中断」——实测 13:59:53 就是这样误标了 4 个在途任务（执行线程其实还活着，Beat 1 随后照样跑完成片并回写 `beat.video_url`，说明状态与真相不一致但结果可恢复）。正确修法是给出片任务加实例归属或租约（`worker_id` + 心跳），启动时只收敛认领进程已停心跳的行——该修法已于同日落地，见下面「出片任务实例归属与心跳租约」章节。
- 受影响文件：`backend/app/media_studio/services/{h3_prompt_builder,episode_video_service,comfy_video_client}.py`、`backend/tests/media_studio_test_h3_video.py`（新增 `DialogueTurnParsingTests`、`ComfyHistoryErrorTests`，并补齐造型回退用例）。
- 兼容性：不改接口路径、数据库结构、工作流注册表、ComfyUI 地址 / 节点 ID 与任务队列；舞台备注清洗和引号优先级只影响提示词生成与逐字校验的判定，历史已生成提示词不重写；单造型回退只在描述无冲突线索时放行，真正缺造型仍然拦下。本轮前端零改动。
- 验证命令：`python -X utf8 backend/tests/media_studio_test_h3_video.py`（167 项通过）、`python -X utf8 backend/tests/test_skill_packs.py`（48 项通过）、全量 `python -X utf8 -m unittest discover -s backend/tests -t . -p "test*.py"`（1218 项通过，skipped=1）、`pnpm --dir frontend build`（通过）。注意 `python -m unittest backend.tests.xxx` 这种写法在本仓库会报 `No module named 'backend'`，只能用 discover 或直接跑测试文件。真实数据证据：`_prepare_shots` 预检通过（6 镜、合计 1917 帧、每镜 2–4 张参考图、说话人 张伟 / 厉景深 / 苏念 / 厉景深 / 厉景深 / 空、Beat 4 `turns=5`）；六条 Beat 全部 `vision_status="used"`、`vision_model="qiniu/conatus-free"`、`vision_image_count` 2–4、`vision_source="vlm"`，中文时间码提示词长度 827–1085 字。
- 出片与合成结果：六个逐镜任务全部 `completed` 并回写 `beat.video_url`（七牛 `zly-ai-video-studio/video/20261102/`，ffprobe 实测 864×480 / 24fps / h264 + **aac 音轨**，时长 12.25 / 15.084 / 12.25 / 15.084 / 15.084 / 10.125 秒，与预检帧数 294 / 362 / 294 / 362 / 362 / 243 一一对应）；`POST /episodes/{eid}/compose` 成片 79.909 秒、同样带 aac 音轨，即 1917 帧 ÷ 24fps 的整集长度。配音全程由 H3 原生音频直出，未调用任何 TTS 供应商。
- 回滚方式：撤回上述三个 service 的增量与 `media_studio_test_h3_video.py` 的新增测试类，重启后端即可；无数据迁移。渲染机侧的回滚是把 ComfyUI 改回用户习惯的启动方式（双击 `Start-ComfyUI.cmd`，参数 `--port 8188 --no-browser`），并删除本轮新增的 `Comfyui\comfyui-console.log`；实例地址、端口、模型目录与自定义节点均未改动。
- 运行注意：全量后端测试包含 `backend/tests/test_dev_reloader.py`，会让开发重载器重启 7865 后端；不要在视频 / 提示词任务在途时跑全量（重载器的延迟重启只保护付费视频任务，不保护 `h3_prompt` 任务），外部驱动脚本统一带 `PYTHONDONTWRITEBYTECODE=1`。

## 2026-11-02 出片任务的实例归属与心跳租约（共享库误标修复）

- 日期与原因：2026-11-02。任务表 `ai_project_jobs` 在 `docs/存储配置.md` 的远端 MySQL `ai-media` 上，由多套后端实例共享；原来的 `EpisodeVideoService.recover_orphaned_jobs()` 在每次进程启动时无条件把所有「进行中」的 `video_generation` 行判为中断，实测 13:59:53 就把别的实例正在渲染的 4 个在途任务误标成 `failed`，而执行线程其实还活着并照常回写 `beat.video_url`。本次给视频任务加实例归属 + 心跳租约，启动扫描只收敛认领进程已经停止心跳的行。
- 数据库基线（新增）：`ai_project_jobs` 增加两列——`worker_id VARCHAR(96) NOT NULL DEFAULT ''`（认领该行的进程）与 `lease_updated_at VARCHAR(64) DEFAULT NULL`（该进程最后一次续租时间，沿用本表的 `VARCHAR(64)` 时间串口径），并新增索引 `idx_ai_job_lease (job_type, status)`。新库由 `sql/013_media_studio_init.sql` 内联建好；已存在的共享库走 `backend/app/media_studio/services/job_lease.ensure_lease_schema()`，它复用 `MysqlDatabase.ensure_column / ensure_index` 的幂等实现（`information_schema` 先检测再 `ALTER`，可重复启动重放）。`main.py` lifespan 中的顺序固定为 `ensure_schema()` → `ensure_lease_schema()` → `EpisodeVideoService.recover_orphaned_jobs()`，保证扫描前新列一定存在。索引只建两列：三列（含 `worker_id`）在 utf8mb4 下会逼近 767 字节的历史键长上限，而 `(job_type, status)` 已足以让心跳与扫描走索引。
- worker_id：`hostname-pid-uuid8`（截断到 96 字符），进程内只生成一次，因此同一台机器上的两个后端进程互不相认；这也意味着「本进程重启后收敛自己上一份遗留行」不能靠 worker_id 匹配，必须靠租约超时。
- 心跳（续租）：`start_heartbeat(job_type, statuses)` 登记状态集并惰性拉起一个进程级守护线程 `job-lease-heartbeat`，每 20 秒执行 `UPDATE ai_project_jobs SET lease_updated_at = %s WHERE job_type = %s AND worker_id = %s AND status IN (...)`。只写 `lease_updated_at`，**不碰 `updated_at`**：后者参与任务列表排序与界面时间显示，每 20 秒刷一次会让列表一直「刚刚更新」。此外 `_set_state()` 在每次状态流转时顺带续租并把 `worker_id` 写成当前进程，所以从队列里被别的实例 `retry` 认领后归属会立刻易主。心跳线程吞掉异常只记续租失败——数据库抖动不能影响出片线程，最坏是该行租约变旧。
- 认领点：三处 INSERT（`create_job`、`_enqueue_upscale_job`、`create_compose_job`）写入 `worker_id / lease_updated_at`；`retry_job`、`confirm_refine` 回到 `queued` 时重新认领；五处 `_EXECUTOR.submit(...)` 统一收敛为 `cls._submit_job(job_id)`，先 `start_heartbeat` 再入队。
- 收敛规则（`converge_orphaned_jobs`）：SELECT 出该 job_type 的活跃行后逐行判定——① 有 `worker_id` 的行按 `lease_updated_at`（缺失时回退 `updated_at`）超过 **300 秒** 判为 `lease_expired`；② 无 `worker_id` 的行（旧版本实例或本次改动之前写入的存量行）按 `updated_at` 超过 **24 小时** 判为 `unowned_stale`；③ `worker_id` 等于当前进程的行直接跳过。每行 UPDATE 都带 `AND status = %s AND worker_id = %s` 的 compare-and-set，避免在扫描与别的实例重新认领之间踩掉别人的在途任务；`payload.recovery` 写入 `reason / owner_worker_id / lease_updated_at / converged_at` 便于事后核对。
- 状态集变化：扫描与心跳的状态集是 `_ACTIVE_VIDEO_STATUSES` 去掉 `awaiting_refine`。排除它有两个原因：一采预览在等人点确认，本进程的线程已经退出，继续续租等于骗过租约判定；旧扫描本来也不含它。相对旧实现**新增** `upscaling`——超分被打断过去会永久停在 `upscaling`，现在能按租约收敛。
- 兼容性：两列均为附加列且带默认值，旧代码不读它们；`job_payload._JOB_PUBLIC_COLUMNS` 白名单未包含新列，接口响应与前端零改动。混跑期（其他实例还没升级到本次代码）它们写入的行 `worker_id=''`，因此最坏要等 24 小时宽限才会被收敛，不会再被误标——这是有意选择保守阈值而非按 `updated_at` 短窗口判定。视频任务的报错文案由「服务进程重启，后台视频任务已中断」改为「渲染实例 … 心跳已超过 5 分钟 …」/「任务超过 24 小时没有进展且无实例心跳 …」，不再有针对别台实例的误标。其余五处启动扫描（`image_generation` / `h3_prompt` / `shot_plan` / `tts_generation` / `ai_pipeline`）仍是全局扫描，本次未改，需要时可直接复用 `job_lease` 的注册与收敛函数。
- 受影响文件：新增 `backend/app/media_studio/services/job_lease.py`、`backend/tests/test_job_lease.py`；改动 `backend/app/media_studio/services/episode_video_service.py`（导入、`_HEARTBEATED_VIDEO_STATUSES`、`_submit_job`、三处 INSERT、`retry_job` / `confirm_refine`、`_set_state`、`recover_orphaned_jobs`）、`backend/app/main.py`（lifespan 调用 `ensure_lease_schema()`）、`sql/013_media_studio_init.sql`。
- 验证命令：`python -X utf8 backend/tests/test_job_lease.py`（14 项通过，覆盖租约判定、心跳只写租约列、CAS 条件、本进程行豁免、无主宽限）、`python -X utf8 backend/tests/media_studio_test_h3_video.py`（167 项）、`python -X utf8 backend/tests/test_skill_packs.py`（48 项）、全量 `python -X utf8 -m unittest discover -s backend/tests -t . -p "test*.py"`（1245 项通过，skipped=1）、`pnpm --dir frontend build`（通过）。共享库真机探针（用后即删，探针前后总行数均为 1001）：插入三行 `running` 且 `project_id='proj-lease-probe-nonexistent'`——他实例新鲜租约 → 不动；他实例租约超时 600 秒 → `failed` 且 `recovery.reason="lease_expired"`；无主行 30 小时 → `failed` 且 `recovery.reason="unowned_stale"`。另以一行 `running` 探针验证守护心跳确实生效：26 秒后 `lease_updated_at` 由 `16:04:32` 续到 `16:04:52`，同一行的 `updated_at` 保持不变，且本进程认领的这行没有被扫描收敛。
- 回滚方式：代码侧撤回 `job_lease.py`、`test_job_lease.py`、`episode_video_service.py` 的租约接线与 `main.py` 的 `ensure_lease_schema()` 调用，重启后端即恢复旧的全局扫描。数据库侧的两个附加列与索引可以留着不管（旧代码不读）；确需清理时执行 `ALTER TABLE ai_project_jobs DROP COLUMN worker_id, DROP COLUMN lease_updated_at; DROP INDEX idx_ai_job_lease ON ai_project_jobs;`，但该库由多套实例共享，删列前要先确认没有别的服务已在读它们。`sql/013` 的内联定义只在建库时生效，无需回滚。

## 2026-11-02 内容库分析结果按原文自愈 + 标准解析器章节别名

- 日期与原因：2026-11-02。用户在 `proj-a342bfd034eb4b20`（剧本《闪婚蜜爱：厉总的独宠娇妻》第一集）看到「识别人物 0」「关键道具 0」「视觉与全局设定」两格空白，而「剧本原文预览」里明确写了 `## 主要人物` 与整段故事定位。排查结论分三层：① **人物 0 是存量数据**：`ai_project_documents.analysis_json` 存的是导入当时那版解析器的结果，`主要人物` 裸标题当时认不出，而读路径 `_analysis_for_document_row()` 只对场景（`_recover_scene_analysis`）和配方资产（`_merge_pipeline_recipe_assets`）做自愈，从不重算人物，所以界面永久停在 0；② **定位与画风为空是章节名不匹配**：`StandardScriptParser` 的正则只认「标准剧本规范」里的 `视频定位 / 二、统一视觉风格 / 五、视频制作建议`，模型直出普遍写成 `故事定位 / 视觉风格 / 拍摄建议`，整节内容被静默丢掉；此外 `_extract_positioning()` 把带字段名的行也塞进 `items`，而界面根本不渲染 `items`，于是模型写成整段散文时前端没有任何东西可显示；③ **道具 0 与 429 不是缺陷**：该剧本没有可识别的道具标注，`关键道具 (0)` 是真实值；`规划失败` 提示来自上游大模型限流（HTTP 429 `Too many requests for this free model`），只中断镜头规划，不影响解析。本次补上①的读路径自愈与②的章节别名 + `items` 渲染，③只记录不改代码。
- 解析器基线（`backend/app/media_studio/services/script_parser.py`）：新增三个类常量作为章节标题白名单——`_POSITIONING_HEADINGS = 视频定位|故事定位|题材定位|剧情定位|作品定位|项目定位`、`_VISUAL_STYLE_HEADINGS = 统一视觉风格|视觉风格|画面风格|视觉基调|画面基调|整体风格`、`_PRODUCTION_ADVICE_HEADINGS = 视频制作建议|制作建议|拍摄建议|制作控制策略`；三处 `re.search` 统一为 `#{1,3}\s*(?:[一二三四五六][、.])?\s*(?:别名组)\s*\n(.*?)(?=...)`，即支持 1–3 级标题与中文数字序号前缀，截断条件保持各自原样（定位/风格用 `(?=\n#{1,2}\s+[^\n#]|\Z)`，建议用 `(?=\n#|\Z)`）。行为变化两点：`_extract_positioning()` 只在 `else` 分支把**没有字段名**的行 append 进 `items`（带 `类型：/世界观：/时长：/主线：` 等前缀的行已进对应具名键，重复进 `items` 会让界面把同一段显示两遍）；`_extract_visual_style()` 逐行先 `line.strip().lstrip("-* ").strip()`，使 `- 禁止：…` 这类列表项仍能被识别为 `prohibited`，而不是并进阶梯式描述里。章节正文遇到 `###` 子标题不截断（`### 角色` 块是既有约定），因此定位段落可能包含后续子块文字，测试用例按真实剧本形态加 `## 第N集` 分隔。
- 读路径自愈（`backend/app/media_studio/services/project_detail_service.py`）：新增模块级纯函数 `_has_analysis_content(value)`（列表看元素、字典看任意非空字段、字符串看去空白，用于回答「这一节到底有没有内容」），并在 `_analysis_for_document_row()` 里、场景恢复之后配方合并之前插入 `cls._recover_analysis_sections(row, analysis, persist=persist)`。该方法只处理 `characters / positioning / visual_style / production_advice` 四个键：**先取空位列表 `pending`，非空才 `StandardScriptParser.parse(row["raw_text"])` 一次，然后只把非空结果写进仍为空的键，已有值一律不覆盖**（镜头可能是 `LlmService.plan_episode_shots` 的规划结果，道具可能本来就没写，覆盖会造成真实数据损失）。补齐后置标记 `analysis["analysis_sections_revision"] = 1`、调 `_refresh_analysis_shot_summary()` 重算摘要，并在 `persist=True` 且有 `row["id"]` 时 `UPDATE ai_project_documents SET analysis_json = %s`；什么都没填上时（剧本确实没写这些章节）**不打标记也不回写**，避免每次读内容库都多一条 UPDATE——代价是这类文档每次读都重跑一遍正则，远小于把旧文档永久标成「已处理」后新解析器再也无法回填的风险。跳过条件只有两个：`analysis` 为空、或已带 `analysis_sections_revision`。`raw_text` 为空同样直接返回。
- 前端（`frontend/src/director2/panes/`）：新增纯函数模块 `content-library-globals.ts`（配套 `content-library-globals.test.ts`）：`positioningEntries(positioning)` 按固定顺序输出「作品类型 / 世界观设定 / 单集时长 / 镜头规划 / 主线剧情」具名条目，再追加无字段名的 `items`（`label: null`），空文字跳过；`hasVisualStyleContent(style)` 判断画风节是否有内容。`ContentLibraryPane.tsx` 的「视觉与全局设定」Tab 用 `positioningList.map()` 渲染（无 label 的散文条目走 `v storyline-v` 样式，不显示空的 `k：`），并在两格各补一条 `.global-empty`：定位节「剧本未写「视频定位 / 故事定位」章节，或该章节没有可识别条目。完整原文见「剧本原文预览」。」、画风节「剧本未写「统一视觉风格」章节。生图与分镜的画风取项目与资产上的画风设置，本节只作阅读。」。`content-library.css` 新增 `.d2-content-library .global-empty`（12px、`var(--studio-text-muted)`、`var(--studio-border)` 虚线边框、6px 圆角），成对主题变量自动继承，无新增主题状态。本 Tab 仍是只读展示：生图与分镜画风取项目/资产的 `visual_style`、`art_style_id`，本节点击不写任何生成参数。
- 兼容性：不改 API 形状、不新增数据库列、不动 ComfyUI 节点与模型路径；`analysis_json` 只多一个 `analysis_sections_revision` 键，旧客户端与旧代码忽略即可。解析器别名是纯扩集，原先能解析的文档结果不变；`items` 语义收窄（不再重复具名字段）只影响本 Tab 渲染。自愈只在读内容库时发生，写入型接口与任务链路未接入。
- 受影响文件：`backend/app/media_studio/services/{script_parser,project_detail_service}.py`、`backend/tests/{test_standard_script_parser,test_document_analysis_recovery}.py`、`frontend/src/director2/panes/{content-library-globals.ts,content-library-globals.test.ts,ContentLibraryPane.tsx,content-library.css}`（前两个为新增）。
- 验证命令：`python -X utf8 backend/tests/test_standard_script_parser.py`（13 项通过，含新增 `StandardScriptParserSectionHeadingTests` 4 项：散文式故事定位保留在 `items`、具名字段不重复进 `items`、`视觉风格`+`拍摄建议` 别名与 `- 禁止：` 归位、`## 二、统一视觉风格` 序号写法）、`python -X utf8 backend/tests/test_document_analysis_recovery.py`（9 项通过，含 `DocumentAnalysisSectionRecoveryTests` 4 项：填陈旧空位并只回写一次、绝不覆盖已有节、已盖章后不再重解析、剧本没写这些章节时零写入）、`npx vitest run src/director2/panes/content-library-globals.test.ts`（5 项）、`npx vitest run`（82 文件 / 591 项）、`npx tsc -b`（通过）、`pnpm --dir frontend build`（通过）、后端全量 `python -X utf8 -m pytest backend/tests -q -k "not dev_reloader"`（1240 passed / 1 skipped / 12 deselected，`test_dev_reloader` 有意排除，它会重启本机 7865；注意 `-m unittest discover` 在本机 Python 3.10 下用 `-k "!dev_reloader"` 会匹配到 0 条，只有 pytest 支持 `not` 语法）。5173 桌面端实测同一工程（另开标签页，不动并发会话的页面）：摘要「共解析出 1 集剧情、6 个分镜头；识别到 2 位主要人物、4 处拍摄场景、0 件核心道具。」，Tab 计数 `识别人物 (2)` 列出苏念/厉景深的年龄、性别、设定与一致性生图 Prompt，`视觉与全局设定` 渲染出整段故事定位（`pos-item` 1 条、无 `label`）与画风空态；浅色下 `.global-empty` 计算色 `rgb(107,114,128)`（`--studio-text-muted=#6b7280`），临时置 `data-theme=dark` 后为 `rgb(155,165,177)` 并已还原，双主题对比度达标。未做移动端检查。
- 回滚方式：删除 `_recover_analysis_sections()` 调用与方法本身、`_has_analysis_content()`，还原 `script_parser.py` 三处 `re.search`、`items.append` 位置与 `line_str` 归一化，前端还原 `ContentLibraryPane.tsx` 的 `positioningList` 渲染与两条空态、删除 `content-library-globals.{ts,test.ts}` 与 `.global-empty` 规则，并移除两组新测试后重新构建。数据侧无需回滚：已回填的 `analysis_json` 是解析器从同一份 `raw_text` 得到的合法结果，多余的 `analysis_sections_revision` 键可留着（旧代码不读），确需还原要把对应文档的该节改回空并去键——不建议，因为这只会把界面重新变回 0。

## 2026-11-02 「智能超清」改为复放本镜生成图只跑二采

- 日期与原因：2026-11-02。用户实测独立 RTX 2x / SeedVR2 超分「视频并没有变清晰」——它只对已解码像素做后处理放大，不重新采样，对 H3 生成细节没有增益，因此该入口长期鸡肋。同日 FaceRefine 单镜 A/B（张伟特写 / 苏念近景，远端 `192.168.10.54:8188`）结论是细节改善局限于脸部、代价是多一轮采样与一个 `ultralytics` 依赖，**不进默认链路**。产品形态最终定为即梦式的单一动作「智能超清」：**只做二采**，放大方式（`h3_latent` / `nvidia_rtx_vsr`）由平台内部决定，不再向界面暴露引擎下拉。上游 `ComfyUI_MiniMaxH3_Director` 的 `MiniMaxH3DirectorRefine` 实测提供 `upscale_method` 枚举 `["lanczos","nvidia_rtx_vsr","h3_latent"]`，远端 `/object_info` 已核对，不存在「不支持单镜二采」的能力缺口。
- 复放基线（核心决策）：智能超清不新建一次生成任务，而是取该镜头**原始生成任务** `payload["workflow_request"]`（已带 seed、提示词快照、时间线与节点连线）的深拷贝，用 `minimax_h3_refine_workflow.build_refine_nodes()` 挂上同一套二采节点（`44` `BasicScheduler` beta / 3 步 / denoise 0.2 + `45` `MiniMaxH3DirectorRefine`，`mode=upscale`），再把 Director 节点的可选输入 `refine` 接到该链接并置 `clear_vram_before_refine=true`。入口是 `episode_video_service.build_smart_clarify_workflow(source_payload)`，**只读源任务、只返回 `(clarified_graph, summary)`，不接受请求侧设置**。这样做的两个理由：① ComfyUI 的输入哈希缓存命中时可跳过一采（13 秒镜头实测一采约 6 分钟、二采约 11 分钟），缓存已被驱逐时两段重跑，产物仍是**同一条 Take**；② 清晰度策略取源自本镜生成时的快照，两人对同一镜点智能超清得到同一画幅，不会出现点一次改一次参数。直接重提生成任务无法复现同一 Take——`resolve_generation_options()` 每次都重新随机 seed。
- 留存约束与拒绝清单：`workflow_request` 只在任务恰好产出一个 chunk 时落盘，因此整集直出（`render_scope=episode`）、拼接片（`compose`）与多段镜头没有可复放图，必须拒绝。`build_smart_clarify_workflow` 依次抛出：「整集直出和拼接片不能智能超清，请到剧集工坊对单个镜头操作。」「原任务没有留存可复用的生成图，无法智能超清；请重新生成该镜头。」「只有 H3 Director 工作流的镜头支持智能超清。」「数字人口播镜头不支持智能超清：二采会脱离口播音频驱动。」「本镜生成时已开启二采精修，无需再次智能超清。」以及模型链路缺失 / 帧数缺失两条兜底。路由层 `project_router.py` 保留既有约定：文案含「进行中」→ 409，其余 `ValueError` → 422，其他异常 → 500「创建智能超清任务失败」。找不到源任务时由 `_enqueue_upscale_job` 抛「找不到本镜头的原始生成任务，无法智能超清…」。
- 任务与执行基线：`_enqueue_upscale_job` 先把请求里的 `beat_ids` / `force` / `engine` / `upscale_engine` 以及全部 `H3_REFINE_OPTION_NAMES` 弹出——清晰度策略来自快照，请求侧一律忽略；不弹 `refine_*` 会让数字人口播因为出现这些键被注册表 422。新任务仍是 `ai_project_jobs` 的一行 `video_generation`（不建表、不加列），标题「智能超清：第 N 集 Beat X」，`payload.model="智能超清（H3 二采）"`、`render_scope="upscale"`、`refine_enabled=true`、`refine_preview=false`、`refine_quality` / `refine_quality_mode` / `refine_upscale_method` 取快照值，另存 `clarify_workflow` 与 `clarify_summary`（frames / megapixels / width / height / upscale_method / 画质档位）。INSERT 时写 `worker_id / lease_updated_at` 并走 `cls._submit_job()`，因此智能超清同样纳入租约心跳与中断收敛。`_run_job` 在 `compose` 分支之后、任何生成分支之前按 `render_scope == "upscale"` 分发到 `_run_upscale_job` → `_run_smart_clarify`；状态串沿用 `upscaling`（已在 `_ACTIVE_VIDEO_STATUSES` 内），进度由旧的 30→100 收窄为 `30 + v*69//100`（30→99），提交成功后把 `clarify_client_id` / `clarify_prompt_id` 写进 payload 便于排障。产物经 `_store_upscaled_video` 落到 `video/{project}/{episode}/{job}/clarify` 前缀，成功后挂到该镜**当前采用的 Take**（`_attach_upscaled_to_adopted_take`），写 `beat.upscaled_video_url` 与 `payload.upscaled_video_url`，原片 `video_url` 不动，并回标源任务。
- 平台内部放大方式：`workflow_registry.refine_upscale_method_option()` 声明 `ui_group=internal`（枚举 `lanczos` / `nvidia_rtx_vsr` / `h3_latent`，默认 `h3_latent`），`refine_upscale_method_value(values)` 只做白名单校验并回落默认值，创建表单与「更多设置」都不出现该项。生成期（`comfy_video_client.py:434`）与智能超清（`episode_video_service.py:452`）共用这一个解析函数，因此「用哪条放大链」是平台决策而不是用户选项；`nvidia_rtx_vsr` 需要渲染机装 `nvidia-vfx`，故默认走 `h3_latent`。
- 引擎能力探测下线：`GET /api/upscale/capabilities`（30 秒缓存的节点/模型探测）与 `POST /api/jobs/{job_id}/upscale` 保留但前端已无调用方；旧生成页视频卡的「2× 超分」下拉、RTX / SeedVR2 两档拆分按钮全部删除。`rtx_vsr_workflow.py`、`seedvr2_upscale_workflow.py`、`JobMode.NVIDIA_RTX_VSR` / `SEEDVR2_UPSCALE` 与历史任务里已存在的 2x 输出**不删除**：共享库 `ai-media` 里仍有这些 mode 的任务行，前端保留只读回显（`video-upscale.ts` 只剩 `isUpscaleJob` / `isUpscaleOutput` / `upscaleOutputLabel` / `relatedUpscaleJobs` / `activeUpscaleJob` / `extraUpscaleResults` 这类读取函数，写侧的 `UpscaleEngine`、`upscaleJobEngine`、`canRequestJobUpscale`、`upscaleDisabledReason`、`hasOriginalVideo` 已删）。
- 前端形态：剧集工坊镜头条与「全部任务」的操作列/详情各只有**一个**「智能超清」按钮，点击先出 Ant Design `Modal.confirm`，正文由 `smartClarifyConfirmText(durationSec, aspectRatio, refineQuality, qualityMode)` 生成——「用同一 seed 复放本镜生成图，只跑二采：放大后重新采样，表演和构图不变，原片保留。目标画布 …（x.x MP）。预计 …；渲染机若还缓存着本镜一采，只需跑二采会更快。」预估沿用生成页二采的同一算法 `refinePlan`（片长×像素预算 `REFINE_MIN_MEGAPIXELS=0.4` / `REFINE_FRAME_MEGAPIXEL_BUDGET=200.0`），超预算时改为「片长×像素超出平台预算…可能因显存不足失败」。禁用原因由 `beatUpscaleDisabledReason` / `jobUpscaleDisabledReason` 给出，与后端拒绝清单逐条对应（镜头未出片、出片进行中、正在智能超清、整集直出/拼接片、多镜 selection、`render_plan.chunks` 多段、任务本身是超清结果），使前端不会出现「点了必失败」的 11 分钟任务；镜头条上已有超清版本时不禁用，重跑只覆盖 `upscaled_video_url`；进行中徽章与进度文案为「智能超清中」，结果标记统一为「超清」（不再有「2x」「2× 超分」字样）。
- 受影响文件：后端 `media_studio/services/episode_video_service.py`（`_source_generation_job_for_beat`、`build_smart_clarify_workflow`、`_enqueue_upscale_job`、`_run_smart_clarify`、`_run_upscale_job`）、`media_studio/services/comfy_video_client.py`（`run_director_refine`）、`media_studio/routers/project_router.py`、`workflow_registry.py`、`api_documentation.py`；前端 `director2/panes/EpisodeWorkshopPane.tsx`、`director2/panes/JobsCenterPane.tsx`、`director2/director2-video-settings.ts`、`director2/workshop-video-progress.ts`、`media/VideoStudioModule.tsx`、`media/video-results.css`、`video-upscale.ts`、`video-upscale.test.ts`、`App.tsx`；文档 `docs/API.md`、`README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。
- 兼容性：不改接口路径、请求体形状、数据库结构、H3 节点 ID、模型路径或 ComfyUI 地址。两个 `…/upscale` 路由的响应结构不变（仍返回 `job_id` / `status=queued` / `render_scope` / `render_mode` / `shot_count`），只是 body 里的 `engine` 与 `refine_*` 从此被忽略。旧任务与旧超分产物继续可读；未留存 `workflow_request` 的历史镜头点击后得到 422 说明而不是静默失败。已开启二采的镜头被显式拒绝，不重复消耗 GPU。
- 验证命令：`python -X utf8 -m pytest backend/tests -q -k "not dev_reloader"`（1243 passed / 1 skipped / 12 deselected；`test_dev_reloader` 会重启本机 7865，有意排除）、`python -X utf8 -m pytest backend/tests/test_h3_refine.py -q`（46 passed）、`pnpm --dir frontend exec vitest run`（83 文件 / 593 passed）、`pnpm --dir frontend exec tsc -b`、`pnpm --dir frontend build`。5173 桌面端检查镜头条与全部任务的按钮、确认文案与禁用原因（浅/暗双主题）。**未做远端真实出片验收**：一次 13 秒 / 0.6 MP 智能超清约占 GPU 11 分钟，需用户确认后再跑；另有一项待实测的疑点——`comfy_video_client.run_director_refine()` 提交前仍调用 `free_resources(force=True)`，它会卸载模型并可能驱逐渲染机的一采缓存，从而让「只跑二采」退化为两段重跑（结果仍正确，只是慢）。图内的 `clear_vram_before_refine=true` 已负责二采前的显存清理，是否去掉这次提交前释放要在真机上按耗时判定（校准值：2 秒 / 1.0 MP ≈ 174 秒，13 秒 / 0.6 MP ≈ 674 秒；接近其两倍即为重跑了两段）。
- 回滚方式：代码侧撤回 `build_smart_clarify_workflow` 与 `_enqueue_upscale_job` / `_run_smart_clarify` 的复放分支、恢复 `run_upscale_job` 走 RTX/SeedVR2 graph 与引擎探测，前端恢复拆分按钮与引擎下拉即可；`docs/API.md`、`api_documentation.py` 与本文档对应章节同步回退。无数据库迁移，已提交的智能超清任务按其 payload 继续跑完或按 `retry` 重放，产物只是多一条 `upscaled_video_url`，删除该字段值即可视为未超清。

## 2026-11-03 智能助手采纳后剧本栏目空白修复

- 原因：助手产物使用 `## 【第1集：标题】`、`## 【全剧故事设定】` 和开头的加粗「类型 / 视觉基调」标签，旧解析器未识别，保存为 `primary_script=true`、`episodes=[]`；正文页又对主稿隐藏原文兜底，形成“2620 字已保存、0 集、三个栏目空白”。
- 当前基线：`script_parser.py` 的分集标题与原文偏移规则同时供解析、采纳、按集更新及锁定校验使用，兼容中文集号、方括号和加粗标题。集尾标记不作为新集，人物与资产设计等全局附录不并入最后一集正文。剧情摘要优先读取原文的「剧情」字段，否则使用最多 300 字原文摘录；散文剧本不凭空生成制作镜头。
- 故事设定只从第一集前的真实设定与标签提取；题材、核心悬念、视觉基调可直接展示，原文没有的受众和一句话故事仍为「未提供」。前端在分集正文为空时显示 `raw_text`，避免解析能力有限导致已保存内容不可见；编辑与阅读识别同类带括号标题。
- 历史恢复：沿用文档读路径的空分集补解析，补齐结果时保留 `primary_script`、独立大纲、独立设定、来源稿及其他已有元数据；写回增加原文与旧解析 JSON 的并发条件。用户 `proj-ed7e739b91ac4bf3` 已恢复 3 集，原文 SHA-256 `120e27a3d6a5e2f0296fa828b3783a72dcd075e35757f5d9411fb959c701dca1` 不变；本次针对该文档事务修复解析 JSON，没有重跑模型或修改制作任务。
- 文件：`backend/app/media_studio/services/{script_parser,project_detail_service}.py`、`backend/app/director_assistant/script_documents.py`；`frontend/src/director2/{script-document.ts,panes/ScriptWorkspace.tsx}`；后端括号剧本 fixture / 解析恢复 / 采纳测试及前端 `script-document.test.ts`。无 API、SQL 表结构、端口、队列和 ComfyUI 配置变更。
- 验证：`python -X utf8 -m unittest backend.tests.test_director_bracketed_script backend.tests.test_director_assistant backend.tests.test_standard_script_parser backend.tests.test_document_analysis_recovery backend.tests.test_director_compact_script backend.tests.test_director_project_info` 对应 171 项通过；`pnpm --dir frontend build` 的 108 文件 / 712 项、TypeScript 与 Vite 通过，`git diff --check` 通过。5173 真实项目桌面双主题的故事设定、大纲、三集正文及编辑取消已检查；包括保留 Windows 原文换行及正文编辑不覆盖后采纳设定的回归。参考截图基线为 `docs/design-ref-director/script-adoption-20261103/`。有活动视频任务时，既有监督器继续延后代码重启，本次不强制打断。
- 兼容与回滚：既有普通标题、镜头格式、人工元数据和 LLM 规划结果保留；仅撤回本节解析、补解析合并与正文兜底增量即可。已恢复的解析元数据可继续读取；不回滚原文、资产或媒体，不用整文件覆盖同期修改。

## 2026-11-03 叙事剧本制作资产完整提取

- 原因：分集展示修复后，《凶宅回溯》仍只转入一个场景。旧路径只复制标准分镜解析结果；叙事稿的主角、分场标题、动作和末尾资产备注未进入 catalog，开头整段环境说明反而成了场景名。旧 `assets_extracted_episode_nums` 又让主按钮直接跳转，无法补提取。
- 当前基线：标准分镜稿沿用原解析转入；存在带正文且未拆为镜头的叙事分集时，在显式 `transfer-assets` 操作中复用已配置的 `LlmService` 通读全剧及独立设定，提取角色、具体空间、关键道具。姓名和物品名须在原文出现，地点短名可组合引用段落中的原词区分上下文（如「现实房间」）；引文若被模型改写，由程序定位实际原文段落。缺少分类、名称无依据、遗漏明确主角或把多个分场仍合成一个场景时不写资产。
- 持久化与兼容：`analysis.script_asset_extraction` 保存 revision / source_hash / created_at，哈希包含原文和独立设定；未变化时复用结果，追加正文或改设定后重新提取。只合并资产 catalog，保留分集、手动设定、主稿和锁定元数据，保存时检查原文及旧 JSON，并发变化则停止。原 append 去重继续保留已有资产行与媒体；道具转入保留提取的用途、视觉描述。没有数据库表迁移、端口、供应商或 ComfyUI 变更。
- 接口与界面：文档列表新增可选 `asset_extraction_required` 布尔值，只做本地判断、不触发模型；已锁定但尚未完整提取的叙事稿显示「补充拆解资产」。原接口、body 与 response 兼容，读取文档或资产不产生 LLM 请求；提取失败仍可重试，且不提前更新锁定标记。
- 文件：新增 `media_studio/services/script_asset_extraction.py`；修改 `llm_service.py`、`project_detail_service.py`、`frontend/src/director2/api.ts` 与 `panes/ScriptWorkspace.tsx`；新增 `backend/tests/test_script_asset_extraction.py`，复用括号叙事剧本 fixture。
- 当前项目修复：`proj-ed7e739b91ac4bf3` 已补入 4 角色、6 新场景、12 道具，总计 4 / 7 / 12。原场景 `ast-af497b00795a` 保留 ID 并更名为「凶宅」，继续作为整体环境；玄关、客厅、走廊、主卧、厨房、现实房间分别列出。核对原稿后未将红裙身影与镜中女人擅自合并，装饰镜与落地镜分别保留。原文及制作分集行哈希未变，重复 append 新增为 0；本次没有启动媒体生成。
- 验证命令：`python -X utf8 -m unittest backend.tests.test_script_asset_extraction backend.tests.test_director_bracketed_script backend.tests.test_director_assistant backend.tests.test_standard_script_parser backend.tests.test_document_analysis_recovery backend.tests.test_director_compact_script backend.tests.test_director_project_info` 对应 187 项通过；`pnpm --dir frontend build`（108 文件 / 712 项、类型检查和构建通过）；`git diff --check` 通过。5173 真实工程桌面检查三类资产、双主题与刷新完成，原文和制作数据哈希未变，重复 append 为 0。资产截图基线为 `docs/design-ref-director/script-assets-20261103/`；活动视频保留运行，监督器继续延后后端加载。
- 回滚：仅撤回语义提取入口、缓存与补充按钮增量，恢复旧标准解析转入；可忽略新增 JSON 标记。保留已经补入的资产、原文、图片及制作数据，不用整文件覆盖同期修改。

## 2026-11-03 无限画布按 WorkRally 参考与完整节点设计落地

- 原因与基线：用户确认 `docs/design-ref-canvas/workrally-redesign-20261102/` 的主稿及八张节点图后要求开发。编辑器改为连续点阵画布、上缘悬浮标题 / 操作、窄工具轨、紧凑缩放栏和默认收起的属性面板。文字、图片、视频、生成、画板五种注册类型与 unknown 兼容占位保留；生成节点按注册表工作流区分图片 / 视频，未新增虚构节点类型。
- 节点与交互：普通媒体以内容、封面和预览为主，空态进入既有作品库或属性地址编辑，等待上游与失效不丢节点数据。生成节点只常驻媒体、任务状态与版本条，选中时通过 React Flow NodeToolbar 在下方展示固定字号生成区，缩放不会把输入控件缩成不可读。参考图按真实连线顺序显示，可从作品库添加、替换、前后排序、移除或插入 `<Picture n>`；替换创建新的素材引用，保留原上游节点与其它下游关系。首尾帧槽位、必填提示、参数层级和限制来自当前工作流能力，不按模型 / 参数名称硬编码。
- 参数与任务：复用 `GeneratorOptionField` 的 Ant Design 控件，primary 进入紧凑参数弹层，advanced 用“更多设置”，internal 不进入创作表单；运行快照仍在折叠追溯中。`CanvasGeneratorLive` 新增仅内存的成功结果数组与已完成 / 总数，来自真实任务 outputs / generation_items；部分完成不编造分母。多个成功输出进入原有 resultHistory（上限 12），重复轮询不重置用户已选版本。已结束任务在打开草稿时补读一次明细以恢复部分完成计数，之后仅轮询进行中的任务。排队 / 生成中锁定编辑并可停止；一采待确认明确提供“确认二采 / 保留一采”，不自动确认。
- 兼容性：草稿 schemaVersion 仍为 2，节点 ID、端口 ID、工作流 graph、API、数据库、队列及 ComfyUI 配置不变。新增的参考图选择目标 / 待替换来源为编辑器临时状态，不进入草稿。只有新建生成节点和缺尺寸时的回退改为 400×290；已有草稿明确保存的坐标和尺寸不自动重排。画板仍为视觉分区，不移动内部节点；底色透明以免遮住连线。默认属性栏关闭、通过顶栏打开；手动保存保留在更多菜单、Ctrl/⌘S 及生成区快捷保存中。
- 受影响文件：`frontend/src/canvas/CanvasNodes.tsx`、新增 `CanvasGeneratorComposer.tsx` / `canvas-composer.ts`、`CanvasEditor.tsx`、`CanvasGeneratorInspector.tsx`、`CanvasSidePanel.tsx`、`CanvasFlowEdge.tsx`、`canvas-generation.ts`、`canvas-model.ts`、`canvas-view-modes.ts`、`canvas-fidelity.css` 及相应测试。图片预览补充缩放 / 适配 / 下载；视频保留真实 metadata 时长、原生播放器和封面工具。没有新增 UI 依赖，根级主题 Provider 不变。
- 验证命令：`pnpm --dir frontend build`（包含全量 Vitest、TypeScript、clean-dist 与 Vite）；`python -X utf8 -m unittest backend.tests.test_canvas_store backend.tests.test_library_query -q`。5173 桌面端检查使用真实 Root / 路由 / ThemeProvider / CanvasEditor 和隔离接口数据，覆盖浅暗主题、节点、参数弹层、参考排序 / 替换、版本、预览、状态与一采决策；全部写请求仅在验收会话中模拟，不提交真实生成任务。最终前端构建为 97 个测试文件 / 647 项通过，TypeScript 与 Vite 通过；上述后端定向测试 30 项通过。最终截图与 23 项交互场景记录在本轮设计目录 DESIGN.md 的实施章节；独立模式沿用首个结果自动插入，其余版本手动插入，菜单文案已同步真实行为。
- 回滚：只撤回上述画布文件的本次增量与新增组件 / 测试，恢复旧节点默认尺寸及属性栏默认值，再执行 `pnpm --dir frontend build`；不整文件回滚同时进行的用户改动，不改业务草稿、供应商配置、数据库或历史任务。

## 2026-11-03 多组出片改为逐镜可见（段级发布与镜头级进度）

- 日期与原因：2026-11-03。用户在 `proj-a342bfd034eb4b20 / ep-abd1a4a1f072`（第 2 集，15 镜一次 selection 提交）看到「远端 ComfyUI 已出好几镜，工坊里所有镜头仍显示生成中」。排查确认这不是远端或轮询故障，而是三个设计事实叠加：① `mapWorkshopVideoProgress()` 把一个 `selection` 任务平摊给 `payload.beat_ids` 的每个镜头，同一 `job.status` / `job.progress`，因此 15 镜永远同步；② 后端各镜 `video_url` 只在**整批全部 chunk 渲染完成**后由 `_write_selected_beat_videos()` 下载合并片再 ffmpeg 拆分写入，中途数据库与 payload 里没有任何单镜地址；③ `job.progress` 是「当前这一段」的 ComfyUI 采样百分比，多段任务每段从 40→90 重爬，实测出现 15→25→30→45→90 的锯齿。另外当时 7865 由 `启动本地视频工作台.bat` 以**无 `--reload`** 方式启动（PID 188608，13:07:52 起），同日 13:35 已写入的 `slim_job_payload()` 分组进度从未被加载——用同一行 `payload_json` 直接调 `serialize_job_row()` 能算出 `{total: 8, completed: 5, current: 6}`，而 `/api/projects/.../jobs` 响应里没有 `render_progress`，据此确认是进程未重启而不是代码未生效。
- 当前基线（段级发布）：`_run_timeline_job()` 在每一个 chunk 采样成功、写回 `status="succeeded"` 与各镜 `renderStatus` 之后，立即调用新增的 `EpisodeVideoService._publish_chunk_shots(job_id, payload, comfy, index, generated_shots, beats_by_id)`。它服务范围由 `_CHUNK_SHOT_PUBLISH_SCOPES`（2026-11-04 起为 `shot` / `selection` / `episode`，见下方「整集直出也按镜落地」）决定，拼接片与智能超清继续按整条产物处理。流程是：从 `render_plan.chunks[index]` 取 `output` → `comfy.download_output(output)`（本段产物通常只有十几 MB，不下载整片）→ `_split_and_publish_shots()` 按 `timeline_output_durations()` 的**实际提交帧跨度**切段并逐镜 `QiniuService.store_bytes` → `_persist_beat_shot()` 走既有 `_persist_shot_original_video()` 采纳 Take。成功后在 chunk 上打 `shots_published=True`，并把 `{beat_id: url}` 累积进 `payload["shot_clip_urls"]`。`beats_by_id` 在整批循环外只拉一次 `ProjectDetailService.get_episode_detail()` 并在每次采纳后就地更新，避免每镜一次详情查询。
- 失败隔离（关键约束）：段级发布只是「更早可看」，不能推翻远端已经成功的分段。`_publish_chunk_shots()` 把下载、ffmpeg、七牛写入和 Beat 回写整体包在 `try/except` 内，异常只写 `payload["beat_update_warning"]` 并保留 chunk 的 `succeeded` 状态；未配置七牛时写 `payload["storage_warning"]`（「七牛云存储未配置，本段暂不能提前按镜发布」）后直接返回，收尾仍按原路径处理合并片。因此提前发布失败的最坏结果只是退回旧行为。单段的 `shot` / `selection` 任务直接跳过段级发布——下一步就是整批收尾，提前落地只会把同一个文件再传一次并给同一镜多出一条 Take（`episode` 单段不跳过，见下方 2026-11-04 记录）。
- 收尾与重试不重复出片：`_write_selected_beat_videos()` 抽出 `_episode_beats_by_id()` / `_persist_beat_shot()` / `_split_and_publish_shots()` 三个复用函数后，重切整片的循环改为**沿用已落地地址**——镜头已有 `video_url` 就跳过 `store_bytes` 与 Take 采纳，只补写还缺地址的镜头，最后 `payload["shot_video_urls"]` 汇总全部地址。这样同一镜不会因为「段级发布 + 整批收尾」生成两条 Take。重试侧：`retry_job()` 只弹 `shots` 而保留 `render_plan` 与 `shot_clip_urls`，`_run_timeline_job()` 命中已渲染 chunk 时从 `clip_urls` 回填 `shot["video_url"]`，**并且同样调用 `_publish_chunk_shots()`**——旧批次（本次改造之前跑的、没有逐镜地址的）重试时不需要重跑远端，也能一边复用分段一边逐镜落地。为此 `_publish_chunk_shots()` 增加 `chunk["shots_published"]` 幂等守卫，`_run_timeline_job()` 重建 `render_plan` 时把 `shots_published` 一并从上次快照带回，已落地的段不会因重试再传一次、再采纳一条 Take。
- 进度语义：新增 `_overall_render_progress(segment_percent, *, completed_units, total_units)`，把单段采样百分比折算进整批区间（40→95 线性推进，`int(40 + 55 * (done + frac) / total)`）。`_await_comfy()` 增加 `completed_units` / `total_units` 两个可选关键字参数并在 `on_progress` 里调用该映射；`_run_timeline_job()`、`_run_shot_graph_job()`、`_run_refine_continuation()` 三处调用点分别按 `index` / `position` 传入。4 段任务的进度序列实测为 42 → 62 → 81 → 95，不再每段回落。chunk 完成后仍显式打一个 `_overall_render_progress(0, completed_units=index + 1, ...)` 断点，让逐镜地址与分组序号同批落库。
- 接口下发：`slim_job_payload()` 新增模块级 `_shot_render_status(chunks)` 与 `_CHUNK_SHOT_STATUS`（`succeeded`→`succeeded`、`awaiting_refine`→`awaiting_refine`、`submitted`/`running`→`running`、其余→`queued`），把 chunk 状态摊成 `slim["shot_status"] = {beat_id: stage}`；同批已有的 `render_progress`（`{total, completed, current}`）继续来自 chunk 计数。各镜地址不在 `shot_status` 里，而是复用既有 `slim["shots"]`（`_slim_shots()` 已输出 `beat_id` + `video_url`），因此不新增大字段、不泄露 `render_plan` 草稿与 `author_zh_draft`。响应形状仍兼容：无 `render_plan.chunks` 的任务不出现 `shot_status` 键。
- 前端基线：`workshop-video-progress.ts` 的 `WorkshopVideoJobLike.payload` 增加 `shot_status` 与 `shots[]`，`WorkshopShotVideoProgress` 增加可选 `shotStage` / `shotUrl`；`mapWorkshopVideoProgress()` 按 `beat_id` 分别查 chunk 阶段与已落地地址。文案上 `workshopVideoStageLabel()` 在 `shotStage==="succeeded"` 时给「本镜已出片」（多组时附「整批 N / M 组」），`shotStage==="queued"` 且多组时给「排队中 · 第 current / total 组」；`workshopVideoOverlayLabel()` 对这两态直接返回阶段名不再追加百分比（已出片的镜头不该再有进度条），其余仍显示「正在生成第 N / M 组 · 当前步骤 X%」。新增导出 `isWorkshopShotRendered()`（仅在 `shotStage==="succeeded"` 即为真）。诚实性兜底：后端 `shot_status` 的 `succeeded` 只代表远端分段渲染完，成片地址可能还没写进任务，`mapWorkshopVideoProgress()` 在任务暴露了 `shots[]` 却没有本镜地址时把它降级为客户端阶段 `saving`，文案「画面已渲染 · 正在保存成片」并保留进度条——避免出现「已出片却放不出画面」；`shotStage` 一旦拿到地址立即回到 `succeeded`。`WorkshopWorkspace.tsx` 用 `playbackBeats`（把 `props.progress[beat.id].shotUrl` 覆盖进 beat 副本）驱动播放器、元信息、下载与「重拍片段」判定，使逐镜地址不依赖整集详情刷新；进度条在已出片时换成 `Check` 图标，镜头条卡片在已出片时显示 `ws-ready-dot` 圆点而不是百分比。`EpisodeWorkshopPane.tsx` 的 `pollImageJobs()` 在 `shotStage` 首次转为 `succeeded` 且地址变化时调 `updateBeatById()` 合并该镜的 `video_url` / `upscaled_video_url=null` / `render_status` / `status`（与后端 `_archive_and_adopt_beat_video()` 返回的更新集一致），只改本地草稿、不触发整集 `loadEpisodeDetail()`，避免打断正在编辑的正文。
- 受影响文件：后端 `media_studio/services/episode_video_service.py`（`_publish_chunk_shots`、`_split_and_publish_shots`、`_persist_beat_shot`、`_episode_beats_by_id`、`_overall_render_progress`、`_await_comfy` 签名、`_write_selected_beat_videos` 复用与跳过、`_run_timeline_job` 回填）、`media_studio/services/job_payload.py`（`_shot_render_status` / `shot_status`）；前端 `director2/workshop-video-progress.ts`、`director2/panes/WorkshopWorkspace.tsx`、`director2/panes/EpisodeWorkshopPane.tsx`；测试 `backend/tests/test_workshop_video_preparation.py`（新增 9 项：段级发布、失败隔离、单段任务不重复上传、episode 范围当时不提前拆镜（2026-11-04 改为按镜落地，该用例已换成「整集多组落地 / 整集单组落地 / compose 与 upscale 仍不落地」三项加一条 Take 归一断言）、收尾沿用已落地地址、多段进度单调、`shot_status` 下发、重试复用分段时逐镜落地、已落地分段不重复上传；并在既有的缓存重试用例上增加 `shot_clip_urls` 回填断言）、`frontend/src/director2/workshop-video-progress.test.ts`（逐镜阶段与文案 3 项，含 `saving` 兜底）；文档 `README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。顺带清理：`EpisodeWorkshopPane.tsx` 里合成 Tab 瘦身遗留的两处孤立引用——`useEffect(() => setEpisodeFilmMeasured(undefined))`（该 state 已随瘦身删除）与 `openToolPanel()` 内的 `setCurrentTab(...)`（Tab 状态已被 `toolPanel` 抽屉取代），两者都会让 `tsc -b` 报错。
- 兼容性：不改接口路径、请求体形状、数据库结构与 ComfyUI 节点/地址配置，`/jobs` 只多一个可选 `shot_status` 键。旧任务（无 `shot_clip_urls` / `shots_published`）继续按整批收尾写各镜，界面退回整批进度文案；`compose` / `upscale` 两类范围行为不变（`episode` 于 2026-11-04 起也纳入段级按镜落地，见下方记录）。逐镜产物仍是既有 Take 模型（`video_takes` + `video_take_id`），历史版本与「智能超清」入口按同一 `video_url` 判定，无需迁移。
- 验证命令：`python -X utf8 -m pytest backend/tests -q`（1492 passed / 1 skipped）、`python -X utf8 -m pytest backend/tests/test_workshop_video_preparation.py backend/tests/test_job_list_payload.py -q`（32 passed）、`pnpm --dir frontend build`（109 文件 / 720 项 Vitest、`tsc -b` 与 Vite 通过）。**生效方式**：本机 7865 由 `backend/dev_reloader.py` 托管，它监听 `backend/app` 的 `.py` 变化，但 `count_active_video_jobs()` 一旦发现有进行中的 `video_generation` 就延后重启（日志 `… deferring backend restart`），直到队列清空才 `applying deferred restart`——这正是本次改动前 `render_progress` 一直没出现在 `/jobs` 响应里的原因（批次在跑，重启被挂起）。因此本轮无需手工重启：第 2 集 15 镜批次（`job-4891e7a90fc2`，8 组）于 15:53:16 失败后队列清空，监督器 15:53:33 自动加载新代码，本轮补充改动后 16:01 再次自动重启（7865 监听进程 188608 → 297208 → 560408）。接口形状用远端 `ai-media` 里该任务的真实 payload 直接过 `slim_job_payload()` 验证：`render_progress = {8, 8, 8}`、`shot_status` 覆盖 15 个 beat 全为 `succeeded`、`shots[]` 15 条 `video_url` 全为空——该批次 8 段远端成片全部渲染完成，只在最后一步「合并整片后上传七牛」超时（`up-z0.qiniup.com:443 Read timed out`）。正是这份真实数据暴露了「分段成功但没有地址」的谎报风险，据此补上客户端 `saving` 阶段。界面自查：5173 工坊页需要已登录会话，自动化浏览器被重定向到 `/login`（`/api/.../jobs` 返回 401），未使用猜测账号，因此逐镜「本镜已出片」的桌面端实机确认待用户登录后进行；对该失败批次点「重试」不会重新提交远端（8 段全部命中缓存复用），可作为端到端验证。
- 回滚方式：删除 `_publish_chunk_shots()` 在 `_run_timeline_job()` chunk 成功后的调用即回到「整批收尾才按镜写入」；`_write_selected_beat_videos()` 的三个辅助函数与 `shot_clip_urls` 回填可一并撤回（回填只影响重试路径的性能，不回滚也不影响正确性）。进度侧把 `_await_comfy()` 的 `on_progress` 恢复为直接写 `value` 并去掉两个新关键字参数。`shot_status` 删除后前端 `shotStage` 恒为空，界面自动退回既有整批文案，无需回滚前端。已提前落地的各镜 `video_url` 与 Take 是正常产物，回滚代码不需要清理数据；如需还原某个镜头，用「历史版本」重新采纳旧 Take 即可。

## 2026-11-03：人脸高清修复（KEEP）

- 原因与行为：用户接受 v014 单人脸 KEEP 试片，新增 AI 工具「人脸高清修复」及成片「更多视频操作」入口。每次只点选一个人脸，默认完整视频，可先试前 5 秒，保留原声。成片入口按实际选中的 generation/output 关联来源；SeedVR2 / RTX 高清结果可自动补充其高清前原片作为第二份素材，避免再次把增强后的脸送进修复器。第一份素材始终作为输出底片。
- 协议：新增 `JobMode.KEEP_FACE_RESTORE = keep-face-restore`，注册表完整定义两份 video 槽位（第 2 份可选）与所有参数；仅 `duration/preserve_audio` 为 primary，其余为 internal。`target_point` 是首帧归一化单脸中心 JSON 字符串，校验有限数、边界与时序窗口关系。上传单份上限 500 MiB，探测两份素材的有效尺寸、帧率、同比例和相符时长；有效 width/height/fps/frames 写入任务及轮次快照。`GET /api/face-restore/capabilities` 查询当前实例的节点与固定模型，`POST /api/jobs` 继续通用创建协议，`source_*` 对此模式允许确切视频输出，原有图片转视频约束不变。
- 执行：复用串行 Comfy 视频 worker。后端上传底片和可选原片，生成新节点 `ZLYKeepFaceRestore` 的单节点 API graph，输出 ID 固定为 `1`；不修改已接入工作流的节点 ID。原生 ComfyUI V3 节点位于仓库 `comfyui_nodes/zly_keep_face_restore/`，部署到既有实例 `custom_nodes/ComfyUI-ZLY-KeepFaceRestore/`。原生队列承担进度、停止、历史及重连；工作台继续负责云端归档与输出权限，不另启动 GPU 服务或 ComfyUI。
- 算法边界：点选附近 RetinaFace 五点检测，受空间与尺度门限约束的单脸跟踪；丢失帧不修复，持续丢失后保留余下原画面。原片对齐到 512×512 后使用标准 KEEP FP32，默认窗口 12 / 重叠 4 / 关键点平滑 sigma 2；原片 ParseNet 面部标签软遮罩排除头发、耳朵、颈部和衣服。按逆仿射贴回第一份视频，遮罩外编码前像素保留，H.264 编码后不承诺逐像素相同。视频尺寸与帧率保持，奇数边长只为 yuv420p 补齐 1 像素；原声尽量封装复制，不支持的音频编码转 AAC。未引入身份参考图或换脸功能，五官细节仍可能重建。
- 运行补验（本轮用户明确授权重启）：既有远端与本机后端已加载 KEEP，无新增实例。Windows OpenSSH 维护启动须保留原命令、目录和环境，并通过 `CREATE_BREAKAWAY_FROM_JOB` 脱离 SSH Job，使用隐藏进程，确认 SSH 断开后服务持续运行。实际执行修正 NumPy float64 裁脸映射兼容性，传给 OpenCV 的坐标明确为 float32；`KEEP_NODE` 纳入处理进度阶段，使用修复阶段名称与实际百分比。原生队列 `f4573926-07e1-41e4-9ca5-90ea583e0205` 为 1024×1792 / 24fps / 124 帧，全部检出并修复，KEEP 耗时 56.25 秒，原 AAC 一致，历史输出恢复通过。后端定向 61 项通过；此前完整后端 1497 项与前端 733 项 / 构建通过。未创建生产 HTTP 任务，具体范围与失败修正记录见动作迁移验收。
- 当前部署依赖：生效实例继续为 `http://192.168.10.54:8188`（读取供应商配置确认），远端根目录 `D:/ZlyFlow-ComfyUI-Portable-20260827-152136/Comfyui`。复用 v014 缓存 `extra_tools/KEEP_ComfyCompat`，上游兼容代码 `wildminder/ComfyUI-KEEP` 固定提交 `70d2e1498cd72923898d3cd63570c99b6ca69031`；四个附加依赖仅在其 `isolated_dependencies`，不升级共享 Torch / NumPy。标准模型 `models/keep_models/KEEP/KEEP-b76feb75.pth`（SHA256 `b76feb75f3ed782f4e91eda85c03018241827bba8693532dc10351bab5052c1a`），检测和解析模型在 `models/facedetection/`；不得把模型下载到工作台或临时目录。执行器不联网取代码或模型，缺失时明确报错。新节点仅在队列无任务时加载，不能中断已有出片。
- 受影响文件：后端 `models.py/workflow_registry.py/keep_face_restore_workflow.py/comfy_service.py/main.py/api_documentation.py`、上述 Comfy 节点目录；前端 `generation/face-restore.ts`、`tools/FaceRestoreTool.tsx`、人脸点选器、工具注册表、路由及 `App.tsx/media/VideoStudioModule.tsx/video-result-model.ts`。无需数据库迁移、端口或供应商配置变更，旧任务与旧工具兼容。
- 验证命令：`python -X utf8 -m pytest backend/tests/test_keep_face_restore.py backend/tests/test_h3_motion_transfer.py backend/tests/test_scail2_replacement.py -q`；`python -X utf8 -m pytest backend/tests -q --ignore=backend/tests/test_dev_reloader.py`；`pnpm.cmd --dir frontend build`。桌面在 5173 检查浅暗主题、首帧选脸、两个素材角色、精确来源版本、再次编辑及任务运行参数；原生队列真实出片证据与执行状态记入动作迁移 `ACCEPTANCE.md`，不能将独立试片冒充平台任务通过。
- 回滚：只撤回 KEEP 模式、工具与成片入口增量；远端队列空闲时禁用新增 `ComfyUI-ZLY-KeepFaceRestore` 节点并按原参数重启既有实例。原有 H3、SCAIL、智能高清及 v014 试片无需改动；保留已生成媒体与历史记录，模型和隔离缓存可保留，不迁移或清理其他节点。

## 2026-11-04 整集直出也按镜落地（段级发布范围扩到 episode）

- 日期与原因：2026-11-04。用户在 `proj-a342bfd034eb4b20 / ep-d5f039b6f113`（第 4 集「深夜对峙，谁是猎物」整集直出 `job-2baa3c11daf9`，13 镜 / 4 组）看到「所有镜头进度仍然统一，远端其实已经出片」。库里该行确认后端当时并无故障：`slim_job_payload()` 已给出 `render_progress = {total: 4, completed: 3, current: 4}` 与覆盖 13 个 beat 的 `shot_status`（9 `succeeded` + 4 `running`），但 `shots[]` 里 0 条 `video_url`。根因是两处刻意的范围限制叠加：① `_publish_chunk_shots()` 只认 `_SHOT_TAKE_SCOPES`（`shot` / `selection`），整集直出被排除在段级按镜落地之外；② 前端 `mapWorkshopVideoProgress()` 对 `episode` 只产出整集横幅、不把逐镜状态铺到镜头卡。用户选择「整集也按镜落地」。
- 当前基线（发布范围）：新增模块级 `_CHUNK_SHOT_PUBLISH_SCOPES = _SHOT_TAKE_SCOPES | {"episode"}`，`_publish_chunk_shots()` 改用它作入口守卫；`_SHOT_TAKE_SCOPES` 继续只回答「哪些范围产出镜头 Take」，两个概念分开。单段守卫改为 `if len(chunks) == 1 and scope in _SHOT_TAKE_SCOPES: return`——`shot` / `selection` 单段仍交给整批收尾（`_write_selected_beat_videos()` 会按镜落地，提前发布只会重复上传同一个文件并多出一条 Take），而 `episode` 的收尾只走 `_publish_timeline_result()` + `_write_episode_video()`、从不拆镜，所以单段整集也必须在这里落地，否则那一集永远只有整片、没有逐镜地址。
- Take 与历史版本口径不变：整集范围的每一镜仍走既有 `_persist_beat_shot()` → `_persist_shot_original_video(scope="episode")` → `_archive_and_adopt_beat_video()`，后者把非镜头范围归一成 `take_scope = "shot"`，`_normalize_video_takes()` 按同一口径过滤，因此整集批次产出的 Take 与逐镜出片在「历史版本」列表、采纳和智能超清复放上完全一致。不改表、不加列，`_EXCLUDED_TAKE_SCOPES` 对整片 / 拼接片的排除语义不变，任务结果仍是 `result_kind = "episode_video"`。
- 副作用与边界：段级落地会把该 beat 写成 `video_url` + `render_status/status = "completed"`（与逐镜出片同一更新集），所以整集批次跑到一半时已出片的镜头在智能剪辑等下游也视为可用素材，这与 `selection` 的既有行为一致。整片仍只有一条：收尾沿用 `payload["shot_clip_urls"]` 已落地地址不重切，`chunk["shots_published"]` 幂等守卫让重试既不重传也不重复采纳；一采待确认分支不受影响（整集直出禁用中途确认，见 `backend/tests/test_h3_refine.py`）。
- 前端基线：`workshop-video-progress.ts` 把逐镜铺卡逻辑抽成 `stampShotBeats()`，`shot / selection / upscale` 与 `episode` 共用；整集批次进入分段渲染后按 `shot_status` 键与 `shots[].beat_id` 的并集回填镜头卡（提示词整理阶段还没有 `shot_status`，卡片保持空白，进度由顶部整集横幅承载），`saving`（「画面已渲染 · 正在保存成片」）诚实性兜底与地址到位后转 `succeeded` 的口径不变；整集横幅文案统一走 `workshopEpisodeStageLabel()`。另修正 `director2-video-settings.ts` 的 `beatUpscaleDisabledReason()`：本镜 `shotStage === "succeeded"` 时放行「智能超清」，此前只要整批任务还在跑就一律回「出片进行中」，与 2026-11-03 已上线并写进文档的「已出片镜头立即可超清」不一致；仍在超清中、以及本镜尚未出片时照旧禁用并给出原因。顶部横幅文案再抽一层 `workshopEpisodeBannerLabel()`：非拼接任务保持「整集生成中 · <阶段>」，`compose` 的阶段文案「整集合片中」本身自带「整集」，此前硬拼前缀会显示成「整集生成中 · 整集合片中」，现在只显示「整集合片中」。
- 受影响文件：后端 `media_studio/services/episode_video_service.py`（`_CHUNK_SHOT_PUBLISH_SCOPES`、`_publish_chunk_shots` 守卫）；测试 `backend/tests/test_workshop_video_preparation.py`（原 `test_episode_scope_batch_never_publishes_shots_early` 换成三项：整集多组按镜落地并断言回写 scope 为 `episode`、整集单组也落地、`compose` / `upscale` 仍不落地，另加一项 `_archive_and_adopt_beat_video(scope="episode")` 的 Take 归一断言）；前端 `director2/workshop-video-progress.ts`（`workshopEpisodeBannerLabel`）、`director2/panes/WorkshopWorkspace.tsx`（顶部横幅改用整句）、`director2-video-settings.ts` 与各自 `*.test.ts`；文档 `README.md`、`功能说明与扩展指南.md`、`docs/导演台流程与界面结构.md` 与本文件。
- 兼容性：不改接口路径与响应形状（`shot_status` / `render_progress` / `shots[]` 早已下发），不改数据库、端口与 ComfyUI 供应商配置。旧任务没有逐镜地址时界面自动退回整批文案；**已在跑与已跑完的整集批次不会自动追溯落地**，需等后端加载新代码后重新提交的批次生效——已跑完的批次可用下一节的分段回写方式补齐，不需要重跑远端。
- 验证命令：`python -X utf8 -m pytest backend/tests/test_workshop_video_preparation.py -q`、`python -X utf8 -m pytest backend/tests -q`（仓库根目录执行；在 `backend/` 下执行会有 8 项因相对路径读文件而假失败）、`npx vitest run` 与 `npx tsc -b`（`frontend`）、`pnpm --dir frontend build`。实测结果：后端 1535 passed / 1 skipped / 1 failed（唯一失败 `test_missing_prompt_can_enqueue_without_calling_llm_in_request` 属另一会话正在删除 `prepare_keyframes` 的未提交改动，与本轮无关）、前端 738 项 / 112 文件通过、构建通过。生效方式沿用 2026-11-03 记录：`backend/dev_reloader.py` 只在 `count_active_video_jobs()` 归零后重启 7865，本次队列已清空并自动加载新代码。
- 桌面端实机确认（2026-11-04 已完成）：用已登录会话打开 `http://127.0.0.1:5173/director/projects/proj-a342bfd034eb4b20/workshop/ep-d5f039b6f113`，13 张镜头卡全部显示绿色就绪圆点与「NNs · 已出片」，整集播放器时长为各镜之和 02:14、点定位片段 10 自动 seek 到 01:33 并播放该镜自己的成片，「片段更多操作 → 智能超清」在本镜已出片时可点（不再回「出片进行中」）；浅色与暗色主题下圆点与文案对比均已检查。
- 历史批次回写（用户选定「按远端分段回写」）：新代码只影响之后提交的批次，`job-2baa3c11daf9` 已跑完但 13 镜无地址，因此以 `EpisodeVideoService._publish_chunk_shots()` 对 chunk 0..3 逐段执行一次——从远端 `192.168.10.54:8188` 下载该段产物、按 `timeline_output_durations()` 的提交帧跨度切镜、上传七牛并采纳 Take，不占 GPU、不重新提交远端。回写后 `payload["shot_clip_urls"]` 13/13、各 chunk `shots_published=True`，任务 `status/progress/result_url/completed_at` 与整片地址未改动；ffprobe 实测四段帧数 277 / 192 / 362 / 192 @24fps 与提交跨度完全一致。中间文件只落在系统临时目录（`TemporaryDirectory`），未在仓库内留下产物。
- 回滚方式：把 `_publish_chunk_shots()` 的入口守卫换回 `_SHOT_TAKE_SCOPES` 并恢复 `if len(chunks) == 1: return` 即回到「整集只产整片」；前端 `stampShotBeats()` 的 `episode` 分支删除后镜头卡不再显示逐镜阶段，`beatUpscaleDisabledReason()` 去掉 `shotStage === "succeeded"` 放行即恢复整批闸门；`WorkshopWorkspace.tsx` 的横幅把 `workshopEpisodeBannerLabel(...)` 换回字面量 `整集生成中 · ` + `workshopEpisodeStageLabel(...)` 即恢复拼接片的重复前缀（纯文案，无数据影响）。已提前落地的各镜 `video_url` 与 Take 是正常产物，回滚代码不需要清理数据；如需还原某一镜，用「历史版本」重新采纳旧 Take。

## 2026-11-04 TTS 新增小米 MiMo 供应商分支（限时免费，走 /chat/completions）

- 变更原因：线上 TTS 未启用导致导演台配音不可用；小米 MiMo TTS 官方当前标注「限时免费」，无需本机 GPU，适合作为云端配音回退。其接口虽标 OpenAI 兼容，但实际走 `/v1/chat/completions`，音频以 base64 放在 `choices[0].message.audio.data`，现有 `/v1/audio/speech` 适配层无法直接使用。
- 当前基线：`detect_tts_provider()` 识别 `api.xiaomimimo.com` 与 `mimo-v2.5-tts*` 模型名；`MIMO_TTS_VOICES` 收录 9 个预置音色（中文女声冰糖/茉莉、中文男声苏打/白桦、英文女声 Mia/Chloe、英文男声 Milo/Dean、默认 mimo_default）；配音台资产声线为 IndexTTS `clone` 或 OpenAI 音色时按角色性别回落冰糖/苏打。`OpenAICompatibleClient.speech_via_chat()` 负责 chat/completions 请求与 base64 解码；`TtsProviderService.test()` 真实合成「试听。」；`/admin/tts` 新增「小米 MiMo TTS（限时免费，无需 GPU）」预设，强制独立 Key、不复用大模型凭据。参考音克隆与 voicedesign 暂未接入。
- 受影响文件：`backend/app/{tts_provider,llm_client}.py`、`backend/app/media_studio/services/dubbing_service.py`、`backend/tests/test_tts_mimo.py`、`frontend/src/admin/TtsProviderSettings.tsx`。
- 兼容性：不改数据库、端口、接口路径、工作流与 ComfyUI 配置；IndexTTS / 硅基 / OpenAI / 自定义分支行为不变。MiMo 免费为厂商限时活动，结束后需切回其它供应商。
- 验证：`python -m unittest backend.tests.test_tts_mimo -v`（8 项通过）；真实 MiMo API 以 `mimo-v2.5-tts` 合成冰糖/苏打两句成功（3.36s / 2.56s MP3，ffprobe 校验）；服务层 `test()` 与 `synthesize()` 走临时 SQLite 成功；`pnpm --dir frontend build` 通过；5173 `/admin/tts` 自查预设、Base URL、音色与复用开关禁用状态正常。
- 回滚方式：还原上述源文件并删除 `backend/tests/test_tts_mimo.py`；已保存的 MiMo 配置切回 IndexTTS 或硅基即可，无需删表。

## 2026-11-04 剧本资产拆解改为后台任务 + 两遍法（进度可见、单项跳过）

- 变更原因：内容库「拆解资产」是同步 HTTP 请求，前端只能显示一个不透明的 Loading，用户无法判断任务是否仍在运行；拆解由单次 LLM 一次性输出全部角色/场景/道具，任何名称不在原文都会整单失败（用户实际遇到「资产拆解包含原文未出现的名称，请重试」），失败即全部重跑。后台任务化解决可见性，两遍法把「名称幻觉」从致命错误降级为单条资产跳过。
- 任务基线：新增 `job_type=asset_extraction`，由 `AssetExtractionJobService` 托管。`POST /api/projects/{project_id}/documents/{doc_id}/asset-extraction` 入队（202）；同一文档已有 queued/preparing/running 任务时返回原 `job_id` 并标 `duplicate`。执行线程复用 `ProjectDetailService.transfer_assets_from_document(mode="append", on_phase=...)`，因此拆解与写库仍是同一条事务链，重复拆解只补新增资产。任务行 `payload` 记录 `document_id/filename/phase/message/chars/transferred/total/skipped/skipped_count`；启动 `recover_interrupted_jobs()` 把服务重启前未完成的拆解标记失败。
- 进度通道：复用 `DirectorOperationEventBus` 与 `GET /api/projects/{project_id}/jobs/{job_id}/events`（新增 `asset_extraction` 分支）。阶段固定为 `prepare`（通读/确定名称）/ `extract`（名称核对与重试）/ `describe`（角色 35、场景 55、道具 72）/ `save`（写入 94）；`_progress()` 以 1.2s 节流推送 `status`，同时把 `stream` 快照写回 `payload_json`，这样任务中心瘦列表和断线重连都能恢复。`LlmStreamHook` 把模型增量转成 `chars` 计数，进度在地板值之上按接收字数缓慢增长且不回退；`on_phase(..., reset=True)` 在每次模型调用开始时清零字符数，保证 Alert 文案始终显示当前阶段而不是整轮总字数。
- 两遍法：`LlmService.extract_script_assets()` 第一遍只确定名称——提示词要求每个名称必须在剧本原文逐字出现，返回 `name/evidence`；程序侧做确定性地名与道具提示、剔除原文无法命中的名字（保留 `skipped` 记录），最多纠正重试 2 次后冻结名单。第二遍按 `asset_extraction_skills.py` 定义的角色 / 场景 / 道具三个 skill 分别整理描述与造型提示，只允许使用冻结名单，组内逐项校验、失败单组重试；未通过项记入 `ExtractedAssets.skipped`，其他资产照常落库。回执写入 `analysis.script_asset_extraction = {revision, source_hash, skipped, ...}`，同稿重复拆解命中回执时不再调用大模型。
- 前端基线：`ScriptWorkspace.tsx` 的底部按钮调用 `enqueueAssetExtraction()` 后立即显示 Ant Design `Alert`（`Spin` + 阶段文案 + 已用时 + 已接收字数 + 「可切换到其他页面，任务会在后台继续」），同时订阅 SSE，并以 `listJobs()` 2 秒轮询兜底；文档 `asset_extraction_job_id` 或页面内状态可让刷新/重新进入时续接进度，终态后自动跳转制作资产库。任务中心 `JobsCenterPane` 新增「资产拆解」页签：列表显示阶段与完成结果，详情抽屉显示内容库文档、已写入（角色/场景/道具）与跳过项，并提供「打开内容库文档」，不再渲染调用参数、参考图与 GRS 请求体这些无关区块。`job_payload.py` 的瘦列表白名单补充 `transferred/total/skipped/skipped_count`，否则抽屉计数会全是 0。
- 受影响文件：`backend/app/media_studio/services/asset_extraction_job_service.py`（新增）、`asset_extraction_skills.py`（新增）、`script_asset_extraction.py`、`llm_service.py`、`project_detail_service.py`、`job_payload.py`；`backend/app/media_studio/routers/project_router.py`；`backend/app/main.py`；`frontend/src/director2/api.ts`、`asset-extraction-live.ts`（新增）、`director2-job-types.ts`、`panes/ScriptWorkspace.tsx`、`panes/JobsCenterPane.tsx`；测试 `backend/tests/test_asset_extraction_job.py`（新增）、`test_script_asset_extraction.py`、`test_job_list_payload.py`、`frontend/src/director2/asset-extraction-live.test.ts`（新增）、`director2-job-types.test.ts`。
- 兼容性：不改数据库表结构、端口、工作流注册表与 ComfyUI 配置；`asset_extraction` 只是新的任务类型，历史任务行原样可读。同步 `POST …/transfer-assets` 保留给 MCP 与脚本，响应新增 `total/skipped/skipped_count`，原有 `transferred` 不变。拆解结果仍是普通 `ai_project_assets` 行，资产库、出片与历史数据零迁移。回滚后已写入的资产和失败任务行可保留。
- 验证：`python -X utf8 -B -m unittest discover -s backend/tests -t .`（1627 项通过，skipped=1）；定向 `python -X utf8 -B -m unittest backend.tests.test_asset_extraction_job backend.tests.test_script_asset_extraction backend.tests.test_job_list_payload`（44 项通过）；`npx vitest run`（117 文件 / 776 项）与 `npx tsc -b --force` 通过；5173 桌面端实测 `proj-055492fd2d34406b` 的第 1 集拆解：进度 Alert 全程可见、约 2 分 46 秒完成、写入 8 角色 / 3 场景 / 11 道具且 0 跳过，完成后自动进入制作资产库；任务中心页签与详情抽屉、内容库完成态、浅暗双主题均已检查。未做移动端检查。
- 回滚方式：删除 `asset_extraction_job_service.py` 与路由中的 `asset-extraction` 端点，`ScriptWorkspace.tsx` 的 `nextStage()` 改回直接调用 `transferAssets()` 同步端点并移除 SSE/轮询即可恢复旧行为；`job_payload.py` 白名单可保留（旧任务没有这些键时不会被序列化）。两遍法如需回退，把 `LlmService.extract_script_assets()` 换回单次调用与整单校验的旧实现；已落库资产无需清理，重新拆解会按 append 语义合并。

## 2026-11-05 H3 装箱缺 camera/lighting/sound 关键词改为按场景确定性兜底

- 变更原因：工坊「生成 H3 提示词」出片走 `LlmService.generate_h3_prompt` 的非技能包 Ref2VA 路径时以 `pad_thickness=False` 关闭了 `_repair_thickness_terms`，两次 LLM 重试后只要英文六段仍缺 camera / lighting / sound 任一关键词，就命中 `thickness_errors`「缺少 lighting 描述」并直接抛错，提示「重试会继续本次提交；修改正文后请重新生成」，逼用户手动往正文补灯光。这是纯关键词门槛（画面内容其实已够），不该整单报废。
- 当前基线：新增 `H3PromptBuilder.ensure_thickness_terms(text, shot)`——只补缺失的 camera / lighting / sound 关键词，绝不补英文字数（真·薄稿仍会因「英文描述过短」失败），其中 lighting 句按 `shot.scene / scene_description / visual_prompt / action` 里的时段与室内外线索（`_LIGHTING_TIME_RULES`）推导，如「烈日 / 工地」补硬顶光、「夜」补月光、「黄昏」补 golden-hour、「室内」补动机光，无匹配时用中性 `Soft cinematic lighting …`。`LlmService._rescue_thickness()` 在每次 `raise "H3 提示词未通过规则校验"` 之前对已装箱稿做最后一次确定性兜底：仅当补完能整体通过 `_validate_h3_prompt` 才放行，否则原样抛错。四个 raise 站点（非包 Ref2VA、技能包合并、T2VA/I2VA 通用）统一接入；对白逐字、`<Picture N>`、六段标题顺序、字数等内容级错误仍硬失败。
- 受影响文件：`backend/app/media_studio/services/h3_prompt_builder.py`、`backend/app/media_studio/services/llm_service.py`、`backend/tests/media_studio_test_h3_video.py`。
- 兼容性：不改表结构、jobs API、工作流注册表与 ComfyUI 配置；只改变「缺关键词」这一子集的结局（由抛错变为按场景补一句后放行），其余校验语义不变；已能通过的提示词行为完全一致。回滚即移除 `_rescue_thickness` 调用与 `ensure_thickness_terms`。
- 验证：`python -m unittest backend.tests.media_studio_test_h3_video.H3PromptTests backend.tests.test_skill_packs`（120 项通过），新增 `test_ensure_thickness_terms_fills_scene_lighting`、`test_generate_h3_prompt_rescues_missing_lighting_without_pack`。`EpisodeVideoUpscaleTests` 的 ERROR 为工作区既有测试/源码漂移（`EpisodeVideoService._upscale_source_url` 属性缺失），与本次改动无关。未做移动端检查。
- 回滚方式：删除 `h3_prompt_builder.py` 的 `ensure_thickness_terms` / `_scene_lighting_sentence` / `_scene_camera_sentence` / `_LIGHTING_TIME_RULES`，去掉 `llm_service.py` 的 `_rescue_thickness` 及四处调用，恢复 raise 前直接抛错即可。

## 2026-11-05 管理设置凭据一键复制（新增超管专用明文取回接口）

- 变更原因：管理设置六个页签的 API Key / Access Key / Secret Key 一律只回显掩码，超级管理员想把已保存的 Key 搬到另一个页签、另一台机器或外部工具时只能重新粘贴，七牛 AK/SK 甚至连掩码都没有。用户要求「所有配置的 Key 支持一键复制」。明文只存在于服务端的 `*_encrypted` 列，前端拿不到，因此必须新增一条受控的明文出口，而不是纯前端改造。
- 当前基线：新增 `POST /api/admin/providers/secret`（`backend/app/main.py`），依赖 `mutating_super_admin_user`（超级管理员 + 会话 Cookie + X-CSRF-Token），请求 `{provider: llm|vlm|tts|grs|qiniu, field: api_key|access_key|secret_key}`，响应 `{provider, field, value}`；带 `Cache-Control: no-store`，每次调用写 `reveal_provider_secret` 审计（`target_id` 为 `provider.field`，`detail` 只记 `revealed`/`empty`，不含密钥）。新增 `backend/app/provider_secret.py` 作为服务端唯一分发点：`SECRET_FIELDS` 白名单决定哪个服务商能复制哪个字段，再按 `{provider}_provider` 取服务。五个 provider service 各加 `reveal_secret(field)`：llm/grs 直接解密主配置列；vlm 走 `_effective_config()`，勾选「复用大模型凭据」时自然取到 LLM 的 Key；tts 按 `use_llm_credentials` 分支取 LLM 或自身列；qiniu 返回 access/secret 二元组对应项。与既有 `api_key()` 的关键差别是本地服务的 `ollama` 虚拟 Key 不返回（返回 null，界面提示「还没有已保存的 Key」）。`models.py` 新增 `ProviderSecretRevealRequest` / `ProviderSecretRevealResponse`；`api_documentation.py` 补该路由说明并改写 `api_key` / `api_key_masked` / `access_key` / `secret_key` 四条字段文档，避免继续声称「任何接口都不返回原文」。
- 前端：新增 `frontend/src/admin/FieldCopy.tsx`（antd `Button` + `Tooltip` + lucide `Copy`，挂在 `Input` / `Input.Password` 的 `suffix`）。输入框有值时直接复制该值，不发请求；为空且声明了 `provider` 时才取回已保存明文。已接入 `ComfyProviderSettings`（连接地址）、`GrsProviderSettings`（Base URL、API Key）、`LlmProviderSettings`（Base URL、模型名称、API Key）、`VlmProviderSettings`（Base URL、模型名称、API Key）、`TtsProviderSettings`（TTS Base URL、模型、API Key）、`QiniuStorageSettings`（Access Key、Secret Key、Bucket、访问域名、对象前缀）。antd 的 `AutoComplete` 没有 affix 槽，模型名称的复制按钮放在标签行右侧、与「拉取官方列表」并排；`Select`（存储区域、助手可选模型、默认音色）不加复制。
- 受影响文件：`backend/app/main.py`、`backend/app/models.py`、`backend/app/provider_secret.py`（新）、`backend/app/llm_provider.py`、`backend/app/vlm_provider.py`、`backend/app/tts_provider.py`、`backend/app/grs_provider.py`、`backend/app/qiniu_provider.py`、`backend/app/api_documentation.py`、`backend/tests/test_provider_secret_reveal.py`（新）、`frontend/src/admin/FieldCopy.tsx`（新）及上述六个设置组件。
- 兼容性：`GET /api/admin/providers/*` 仍只返回 `api_key_masked` / `has_*_key`，掩码语义与所有保存、测试接口字段完全不变；不新增表、不改列，密钥继续只以 `*_encrypted` 保存。变更的实质是新增「按需、需 CSRF、留审计」的明文读取能力：明文会经 HTTPS 进入浏览器剪贴板，任何能操作超管已登录会话的人或脚本都能取回已保存凭据，因此 `provider_secret.py` 不得被其他模块复用，前端也不得把返回值渲染进 DOM、URL 或本地存储。回滚即删除该路由、`provider_secret.py`、五个 `reveal_secret` 与前端 `FieldCopy.tsx` 及六处 `suffix`，行为回到只读掩码。
- 验证：`python -m unittest backend.tests.test_provider_secret_reveal`（7 项通过：明文取回、三个配置接口仍不含原文、VLM 复用凭据取到 LLM Key、本地端点返回 null、七牛 AK/SK 各自可复制、provider/field 组合非法返回 422、缺 CSRF 与非超管返回 403、审计只记字段名不记密钥）；`python -m unittest discover -s backend/tests -t .`（1693 项通过，skipped=1）；`npx tsc -b --force` 通过；5173 桌面端实测六个页签的复制按钮全部渲染，LLM 页 Key 输入框为空时点击「复制API Key」发出 `POST /api/admin/providers/secret`（body `{"provider":"llm","field":"api_key"}`）并写入 67 位明文，七牛 AK/SK 各复制 40 位，`Input.Password` 内复制按钮与显示/隐藏小眼睛并排、不重叠也不裁切。未做移动端检查。
- 回滚方式：删除 `main.py` 的 `admin_reveal_provider_secret` 与两处 import、`provider_secret.py`、五个 service 的 `reveal_secret`、`models.py` 两个模型、`backend/tests/test_provider_secret_reveal.py`，再删 `frontend/src/admin/FieldCopy.tsx` 与六个组件里的 `suffix` / 标签行按钮，即恢复「密钥永不出后端」的旧基线；已写入的 `reveal_provider_secret` 审计行可保留，不影响任何业务数据。

## 2026-11-06 GRS 生图消耗积分、即梦式模型下拉与结果域名解析守卫

- 变更原因：创作页生图下拉此前只有一行模型名，既看不出模型之间的差别，也看不出要花多少积分；GRS 其实把每个模型的标价积分放在价目接口里，只是工作台从未取过。同时目录里历史入库的描述长句（「使用 GRS GPT Image 2.5 生成图片，支持 0–10 张有序参考图。」）由能力档模板批量生成，平台已经上线的 `gpt-image-2.6` 会被写成 2.5，描述与实际能力（可直出 GIF）不符。用户要求按即梦的形态把「模型 + 一句能力 + 消耗积分」放进下拉。
- 积分来源与链路（新增）：`GrsClient.model_costs()` 调 `POST {base_url}/client/openapi/getModelList`（请求体 `{"apiKey": ...}`，与 `balance()` 同族），只保留 `type == "image"` 的行，返回 `{ provider_model: 单次积分 }`。`grs_image_models` 新增 `credit_cost INTEGER NULL`，走 `storage.ensure_column`（共享远端 MySQL，禁止一次性 ALTER），新增 `set_grs_image_model_costs()` 按 `provider_model` 只更新已存在的行且不刷 `updated_at`（积分是平台侧数据，不是管理员编辑行为）；`update_grs_image_models` 仍只写 `display_name/enabled/sort_order/is_default`，保存顺序不会冲掉积分。`GrsProviderService.refresh_model_costs(force=)` 随余额快照 6 小时限频（`GRS_COSTS_REFRESH_SECONDS`），管理员拉取平台清单与导入模型时强制刷新；上游失败一律静默保留旧值——积分只用于展示，绝不阻塞出图。
- 出参（新增）：`WorkflowDefinition.credit_cost` → `payload()` → `ModeResponse.credit_cost`（严格 pydantic，必须显式声明否则被剥离）→ `GET /api/modes` 生图条目；`catalog_payload()` 与 `fetch_platform_models()` 条目同时带 `credit_cost` 与 `description`；`import_platform_models` 接受可选 `description`/`credit_cost`。字段文档见 `docs/API.md` 同日章节与 `api_documentation.py`。
- 能力文案基线（改造）：`grs_catalog` 删除 `PROFILE_DESCRIPTIONS`，改为 `PROFILE_CAPABILITIES`（六个能力档各一句，只写代码里可验证的分辨率/比例/画质/参考图数量）+ `MODEL_CAPABILITY_NOTES`（按 `provider_model` 覆盖同档内的真实差异：2.6 直出 GIF、Flare 三档画质、Sunburst 可选到 max、fast/lite 低价快出、2K/4K CL 固定档）+ `LEGACY_AUTO_DESCRIPTIONS`（旧模板文本，仅用于识别「这不是管理员自己写的」）。`model_description()` / `effective_description()` 是唯一出口，`catalog_record`、`platform_entry`、`workflow_registry.image_workflow_from_catalog`、`grs_provider.catalog_payload`、`grs_provider.fetch_platform_models` 五条读路径全部改走它：管理员自填描述优先，历史长句与空描述按当前档位文案现算，因此改文案不需要动共享库里的历史行。
- 前端（新增）：`App.tsx` 的 `WorkflowSelectOption` 带 `description/creditCost/isDefault`，`optionRender` 渲染 `WorkflowOptionRow`（图标磁贴 + 名称 +「默认」标记 + 一句能力 + 右侧「N 积分/张」），提交按钮左侧新增 `.studio-submit-cost`（antd `Tooltip` 说明「实际扣费以上游结算为准」）。`index.css` 弹层 `.studio-workflow-select-popup` 最小宽 340px、行高自适应，标题 `nowrap`、描述 `white-space: normal` + 两行 clamp + 父级 `min-width: 0`（缺任一条就会把右侧积分挤出可视区），并配 `[data-theme="light"]` 覆盖。antd v6 事实：`aria-label` 落在 `input.ant-select-input` 上、可点区域是 `.ant-select-content`、自定义字段在 `optionRender` 的 `option.data`。管理页 `GrsProviderSettings.tsx` 在目录表与平台拉取弹窗各加「消耗积分」列（取不到显示「未取到 / 未标价」）。
- GIF 能力实测（`gpt-image-2.6`）：提示词直接要求循环动图即可，无需任何额外提交参数——上游结果 URL 本身就是 `.gif`（`file3.aitohumanize.com/file/….gif`，`image/gif`、GIF89a、9 帧）。工作台链路无需改动：`grs_client.download_image` 已放行 GIF 文件签名并按 Content-Type 产出 `grs-result.gif`，`resource_storage.store_bytes` 保留后缀，七牛对象原样存储（`img.zlyun168.com/….gif`，412×413、9 帧、`image/gif`），不做转码。
- 顺带修复（线上阻断）：本机 fake-IP 代理开始为 `*.aitohumanize.com` 在 benchmark IPv4 之外追加 `2001:2::/48`（本机代理实际返回的保留段）解析，而 `GrsClient._validate_public_https` 是逐地址判定「非公共即拒绝」，例外网段清单里没有该前缀，于是 11-06 起每一次 GRS 出图都在下载阶段失败（库里最后一次成功是 11-04 18:24，本次实测报「GRS 图片地址指向非公共网络，已拒绝下载（file3.aitohumanize.com）」）。`GRS_BENCHMARK_RESULT_NETWORKS` 增加 `GRS_RESULT_TRANSLATED_IPV6_NETWORK = 2001:2::/48`，作用域仍只限 `aitohumanize.com` 域名，其他主机的私有/回环/链路本地地址照旧拒绝；`test_ai_studio` 补「benchmark 域名 + 2001:2:: 允许下载」与「非白名单域名只有 2001:2:: 仍拒绝」两条断言。
- 受影响文件：`backend/app/grs_client.py`、`backend/app/grs_catalog.py`、`backend/app/grs_provider.py`、`backend/app/storage.py`、`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/api_documentation.py`、`backend/tests/test_grs_model_costs.py`（新）、`backend/tests/test_ai_studio.py`、`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/src/admin/GrsProviderSettings.tsx`。
- 兼容性：`credit_cost` 与描述文案都是只读展示字段，提交参数、任务快照、历史任务与导演台出片链路完全不变；离线部署或未配置 GRS Key 时 `credit_cost` 为 `null`，界面显示「未取到」而不是 0。回滚积分功能只需删掉 `model_costs()`/`credit_cost` 列读写与前端两处展示，已加的 `credit_cost` 列可保留（`NULL` 不影响任何查询）。
- 验证：`python -m unittest backend.tests.test_grs_model_costs`（12 项，覆盖价目解析与非 image 过滤、`set_grs_image_model_costs` 只动已知行、保存顺序不冲掉积分、6 小时限频与上游失败保底、平台清单带 `credit_cost`/`description`、价格接口失败时 `credit_cost` 为 `null`、导入落库带描述、`/api/modes` 透传）；`backend.tests.test_grs_platform_models`（12 项）与 `backend.tests.test_ai_studio`（47 项，含新增「benchmark 域名 + `2001:2::` 允许下载」「非白名单域名只有 `2001:2::` 仍拒绝」两条）；项目根 `python -m unittest discover -s backend/tests -t .`（1733 项通过，skipped=1）；`pnpm --dir frontend build` 通过；`pnpm --dir frontend exec vitest run`（125 文件 / 851 项通过）。真实上游与真实任务：`getModelList` 返回 35 行、其中 17 个 `type=image` 带价（`gpt-image-2.6`=600、`flare`=2000、`sunburst`=2400、`nano-banana-2.1`=1200、`nano-banana-2-cl`=6000…），价目接口内无任何能力/描述字段，故文案只能来自本仓注册表；`grs-gpt-image-2.6` 真实任务 `eoXiflkQYZ7` 成功，产物 `image/gif`、412×413、9 帧，七牛对象同尺寸同帧数未被转码；守卫修复前的同一提示词任务 `f3vH3OMQRPG` 上游已成功（结果 URL 即 `.gif`，`image/gif`、410×413、9 帧），但被下载校验判为「指向非公共网络」而失败，库里最后一次 GRS 成功是 11-04 18:24。5173 桌面端暗色实拍：富行下拉首屏 6 行均为一行名称 + 一句能力 + 右侧「N 积分/张」且积分不被裁切，选 GPT Image 2.6 后提交按钮左侧显示「600 积分/张」、切到 Nano Banana 2.1 变「1200 积分/张」，搜索 `nano` 只剩 1 行。未做移动端检查。
- 回滚方式：还原 `backend/app/{grs_client,grs_catalog,grs_provider,storage,workflow_registry,models,api_documentation}.py`、`frontend/src/{App.tsx,index.css,admin/GrsProviderSettings.tsx}` 并删除 `backend/tests/test_grs_model_costs.py`，即回到「只有模型名、无积分、旧长句描述」；`grs_image_models.credit_cost` 列可保留（`NULL` 不影响任何查询，也不参与 `update_grs_image_models`）。`grs_client.py` 里 `GRS_RESULT_TRANSLATED_IPV6_NETWORK` 的域名例外修复与本条功能无关，回滚积分功能时不得一起还原，否则 GRS 出图会重新全部卡在下载阶段。接口口径回滚见 `docs/API.md` 同日章节。

## 2026-11-06：H3 长片一采画布按「帧 × 像素」预算收窄（16 GB 卡不再掉进权重换页）

- 变更原因：一采主路径此前只按用户选择的画布档位出图。15 秒（362 帧）在远端 RTX 4080 16 GB 上取 1.0 MP（1376×768）会触发 ComfyUI 动态显存换页：实测 20 步任务停在 `0/20` 超过 7 分钟、GPU 利用率 0%、显存 15.7 GB 常驻，`/interrupt` 之后显存也不释放，只能重启 ComfyUI；同一参考图与提示词改用 0.5 MP（960×544）6 分钟正常出片。
- 当前基线：`workflow_registry.budgeted_render_megapixels()` 在 `h3_dimensions()` 内按 `H3_FRAME_MEGAPIXEL_BUDGET = 200`（与二采 `REFINE_FRAME_MEGAPIXEL_BUDGET` 同一个实测预算）收窄画布：帧数 > `H3_SINGLE_WINDOW_FRAMES`(243，10 秒单窗口) 且 `frames × MP` 超预算时，按 0.1 MP 步进下调，下限 0.2 MP。10 秒以内画布契约不变（标准 H3 仍可用到 2.0 MP）。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/tests/test_core.py`（新增 `test_h3_long_clip_caps_canvas_to_the_frame_megapixel_budget`）。
- 兼容性：不改 API、数据库、节点 ID、模型路径与端口；1.0 MP / 5 秒等短片段尺寸不变；15 秒 1.0 MP 实际出 960×544（0.5 MP），任务「运行参数」里的 quality 仍是用户所选档位。
- 验证：`python -m unittest backend.tests.test_core`（121 项通过）；ComfyUI 实测 15 秒 0.5 MP 单条 369 秒、10 秒 0.8 MP 单条 378 秒；端到端回归复用任务 `l4YXI85nCme`（15 秒、quality 选 1.0）：下发的 ComfyUI 图为 960×544／362 帧／20 步／`res_multistep`，`execution_success` 用时 11 分 10 秒，任务状态 succeeded 并产出 15.08 秒成片；同一任务在修复前以 1376×768 提交，GPU 长时间 0% 占用、显存 15.7 GB 常驻且 `/interrupt` 无法释放。
- 回滚：删除 `budgeted_render_megapixels()` 及其在 `h3_dimensions()` 中的调用，并移除新增测试，即恢复「只按档位决定画布」。

## 2026-11-07 新增「动作与打斗」工作流族（作者打斗 V2 管线产品化）

- 变更原因：本机手工搭图加远端 ComfyUI 跑通了作者分享的打斗 V2 管线（三层 LoRA + 距离注意力 + 动态 CFG + Sigma 追步），连出 5 个打斗镜头验收通过。该能力此前只能靠一次性脚本 `.tmp/combat_generate.py` 调用，用户要求把它接入工作台，并明确选择「三路由全套」——T2V / I2V / R2V 都注册，生成页与导演台任意分镜都能用。
- 注册表（唯一能力来源）：`workflow_registry.py` 新增分组 `CATALOG_GROUP_ACTION = "h3_action"`（`CATALOG_GROUPS` 里 label「动作与打斗」、order 18）、`ACTION_OPTION_SCHEMA = action_option_schema()`、三条 `WorkflowDefinition`（`minimax-h3-action-t2v` / `-i2v` / `-r2v`，R2V 为 `collection`、1-9 张）。三条都声明 `catalog_group=CATALOG_GROUP_ACTION`，**不**声明 `supports_timeline` / `supports_multi_segment`：打斗图没有可复用的视频底片，导演台由此自动落到「逐镜」而不是「整集直出」。前端不需要新增选择器：`/api/modes` 的 `catalog_group*` 直接驱动生成页分组与工坊「视频工作流」下拉；`frontend/src/director/director-workflows.ts` 的三路由 family 兜底表补了 `h3_action`，接口不可用时也不会回落成官方 H3 T2V。
- 参数分层（`action_option_schema()`）：`primary` 只有 `aspect_ratio`（配 `quality` 作为 `ui_companion`）与 `duration`；`advanced` 只有 `quality`（默认 0.8 MP，16:9 约 1216×672）与 `action_intensity`（`intense`「打击感强（作者推荐）」/ `steady`「动作稳健（多人同框）」）；其余全部 `internal`：`megapixels`、`reference_image_size`、`ref_resize_size`、`steps`(8)、`extra_steps`(0-15)、`sampler_name`(euler_ancestral)、`shift_video`(12)/`shift_audio`(3)、`receptive_field_scale`、`temporal_weight`、`cfg_low`/`cfg_high`、`refiner_start_at_sigma`、`use_sage_attention`。三组调参节点的具体数值由 `apply_action_intensity_preset()` 按档位托管（intense 2.0/3.0/0.9/1.1，steady 1.5/2.0/0.95/1.05），客户端显式提交的单项参数优先，因此老任务重放与手工排障都不被档位覆盖。
- 时长上限 10 秒（硬约束）：远端 `H3DistanceAttentionPatcher.num_frames` 的 `max` 是 256，11 秒会推到 277 帧而整单被 ComfyUI 拒绝。`ACTION_DURATION_MAX_SEC = 10` 写进 schema（`duration` 2-10 秒），`ACTION_MAX_FRAMES = 243` 在 builder 里对 `h3_length()` 做 `min()` 封顶——导演台逐镜会把分镜时长直接写进 `duration`，分镜超 10 秒时靠这层 clamp 保证能出片而不是提交失败。
- 二采精修排除：打斗图的收敛由 `H3SigmaRefiner` 在单次采样内完成，没有可复用的视频底片。`H3_REFINE_WORKFLOWS` 用 `H3_WORKFLOWS - {AVATAR, LIP_SYNC} - ACTION_WORKFLOWS` 排除三条打斗路由，`normalize_options()` 对打斗显式拒绝 `refine_*`（「打斗与动作不支持二采精修」），前端因此不渲染二采开关。
- 构图（新增 `backend/app/minimax_h3_action_workflow.py`）：UNET `minimax_h3_hybrid_fl2va_ref2va_b25-49-int8`、CLIP `qwen3vl_32b_minimax_h3_int8_convrot`、三层 LoRA 顺序（Turbo ref2v 4step → FrameRush → H3_Combat_V2）；Sage → SigmaShift(12/3) → `H3DistanceAttentionPatcher` → `H3DynamicCFGScheduler` → `BasicGuider`(cfg 1.0) + `BasicScheduler`(8 步 simple) → `H3SigmaRefiner`(extra 1 / 0.7 / cosine) → `euler_ancestral` → `SamplerCustomAdvanced` → VAEDecode(音/画) → `CreateVideo`(24fps) → `SaveVideo`。**`SaveVideo` 固定在节点 `14`**：`comfy_service.completed_outputs` 对 H3 系列按该节点取产物，换号会让任务永远等不到成片；R2V 参考图经 `ImageResizeKJv2` 归一到 1536 后接 `ref_images`，LoadImage 从节点 20 起、resize 从 50 起。
- 双入口接线：生成页走 `ComfyService.run()` 新增的 `elif mode in ACTION_WORKFLOWS:` 分支；导演台逐镜走 `comfy_video_client.build_shot_workflow()` 的同名分支（该路径 `_find_video` 遍历所有输出、不依赖节点号）。两条路径共用同一个 builder，参数与画布口径不会分叉。
- 远端依赖（部署前必须存在）：`H3DistanceAttentionPatcher` / `H3DynamicCFGScheduler` / `H3SigmaRefiner` / `MiniMaxH3ReferenceToVideo` 四个自定义节点，以及 `minimax_h3_hybrid_fl2va_ref2va_b25-49-int8`、`qwen3vl_32b_minimax_h3_int8_convrot`、`minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16`、`FrameRush-MiniMax-H3_c1-st1300`、`H3_Combat_V2` 五个权重文件。缺任一项时新工作流会提交失败，但不影响其他工作流。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_action_workflow.py`（新）、`backend/app/models.py`（3 个 `JobMode`）、`backend/app/comfy_service.py`、`backend/app/media_studio/services/comfy_video_client.py`、`frontend/src/director/director-workflows.ts`、`backend/tests/test_core.py`、`frontend/src/director2/director2-video-settings.test.ts`。
- 兼容性：纯新增工作流族，不改端口、数据库、既有节点 ID、模型路径与其他工作流参数；既有任务快照与回显不受影响。历史生成页默认工作流仍是 `minimax-h3-director-accel-r2v`。参数范围已按远端 `/object_info` 实测收窄（`receptive_field_scale` 1.0-100 step 0.5、`temporal_weight` 0.1-10、`cfg_low/high` 0.5-2.0 step 0.05、`extra_steps` 0-15），提交时不会因越界被远端拒绝。
- 验证：`PYTHONPATH=. python .tmp/action_registry_check.py`（三路由 family 齐、steady 预设生效、10 秒 0.8→1216×672 / 1.0→1376×768、15 秒被拒、clamp 后 `num_frames=243`、`graph["14"]` 是 SaveVideo、三层 LoRA 顺序、R2V `ref_images.ref_image_1 == ["51",0]`）；`python -m unittest backend.tests.test_core`（126 项通过，新增 5 项）；`npx vitest run src/director2/director2-video-settings.test.ts`（39 项通过，新增逐镜标签与字段裁剪用例）；`pnpm --dir frontend build` 通过；`GET /api/modes` 返回 3 条「动作与打斗」；5173 桌面实测生成页下拉新分组三项、选中 R2V 后工具栏 `16:9 · 1216 × 672` / `10秒`、二采开关消失、「更多设置」只含分辨率与动作强度；导演台 `proj-ca0db5f9d98d440b` 第 1 集工坊「视频工作流」下拉中「动作与打斗 → 打斗与动作 多参考视频（逐镜）」与 H3 Director 加速版（整集直出）、官方 MiniMax H3（逐镜）并列。未做移动端检查。
- 回滚方式：删除 `minimax_h3_action_workflow.py`、`ACTION_WORKFLOW_IDS`/`ACTION_WORKFLOWS` 及其在 `H3_WORKFLOWS` 的并入、三条 `WorkflowDefinition`、`action_option_schema()`/`ACTION_OPTION_SCHEMA`/`apply_action_intensity_preset()`、`is_action_workflow()` 与两处 `elif mode in ACTION_WORKFLOWS:` 分支、`director-workflows.ts` 的 `h3_action` family 与 `CATALOG_GROUPS` 的 `h3_action` 行，并移除新增测试，即回到只有 LightX2V / 八步双加速 / Director 加速版 / 官方 H3 的分组结构；远端 LoRA 与节点可保留（不被引用时无副作用）。

## 2026-11-07 「AI 工具」新增「打斗镜头」工具卡（打斗工作流的产品化入口）

- 变更原因：「动作与打斗」工作流族接入后只能从生成页下拉与导演台工坊选到，普通用户不知道选哪条路由、也不会写 `<Picture n>` 引用。用户要求补一张与「视频换人」「角色替换」同形态的固定入口工具卡。
- 当前基线：新增路由 `/tools/action-shot`（`PATHS.toolActionShot`），页面 `frontend/src/tools/ActionShotTool.tsx` **锁定** `minimax-h3-action-r2v`，不在页面内提供工作流切换；参考图 1-9 张有序上传（上限/下限取注册表 `max_references` 同值常量 `ACTION_SHOT_MAX_REFERENCES`），参数控件全部由 `/api/modes/minimax-h3-action-r2v` 的 `options` schema 派生（复用 `motionToolOptions` / `motionToolDefaults` / `motionToolPayload`），页面只显示 `primary`（画面比例、时长 2-10 秒滑块）与折叠的 `advanced`（分辨率、动作强度），`internal` 参数继续由后端契约托管。
- 提示词协议：R2V 的 `<Picture n>` 与上传顺序强绑定，卡片角标显示 `Picture n`，每张卡片带「引用」按钮在光标处插入对应 token（`insertActionShotPicture`，与生成页 `addPictureTag` 同样的空格规则）；「填入打斗模板」按参考图数量生成「主体关系 → 动作节拍 → 镜头与打击感」结构（`actionShotPromptTemplate`）；提交前 `missingActionShotPicture` 校验提示词是否引用了 1..n 范围内的图片，避免远端构图阶段以 `missing <Picture n>` 整单失败。
- 注册位置：`frontend/src/tools/tool-registry.ts` 新增 `{ id: "action-shot", title: "打斗镜头", status: "available", category: "camera", cover: "/tool-covers/action-shot.jpg" }`（无 demo，形态与「人脸高清修复」一致），`tool-icons.ts` 映射 lucide `Swords`，`ToolsWorkspace.tsx` 挂载路由，`paths.ts` 同时登记 `STUDIO_ROUTE_PATHS`。封面取打斗 V2 第 4 镜 10 秒帧（`test-results/combat/s4_t10s.jpg` → `frontend/public/tool-covers/action-shot.jpg`，960×540）。
- 受影响文件：`frontend/src/generation/action-shot.ts`（新）、`frontend/src/tools/ActionShotTool.tsx`（新）、`frontend/src/tools/action-shot-tool.css`（新）、`frontend/src/tools/tool-registry.ts`、`frontend/src/tools/tool-icons.ts`、`frontend/src/tools/ToolsWorkspace.tsx`、`frontend/src/paths.ts`、`frontend/public/tool-covers/action-shot.jpg`（新）、`frontend/src/generation/action-shot.test.ts`（新）、`frontend/src/tools.test.ts`。
- 兼容性：纯新增页面与注册表条目，不改后端、工作流图、数据库、端口、节点 ID 与模型路径；生成页下拉、导演台工坊与既有工具卡行为不变。工具页提交与生成页走同一个 `POST /api/jobs`（`mode` + `prompt` + `options` + 重复 `references`），任务体与参数快照口径完全一致。
- 验证：`npx vitest run src/generation/action-shot.test.ts src/tools.test.ts`（16 项通过）；`npx tsc --noEmit` 无错误；5173 桌面端实测工具中心「镜头与动态」出现「打斗镜头」卡片（封面与图标正常），进入页面后参考图空态、画面比例（16:9 横屏）、时长滑块（默认 10）、「更多设置」展开后分辨率 0.8 MP 与动作强度「打击感强（作者推荐）」、模板填入与「引用」插入均正常；真实提交任务 `YnGuFKrzu06` 的参数快照为 `mode=minimax-h3-action-r2v`、2 张参考图、`aspect_ratio=16:9`、`duration=10`、`quality=0.8`、`action_intensity=intense`，后端补全 `receptive_field_scale=2`/`temporal_weight=3`/`cfg 0.9-1.1`/`extra_steps=1`；该单 428 秒 succeeded，成片 1216×672 / 10.125 秒 / h264 + AAC（七牛 `zly-ai-video-studio/minimax_h3/20261107/015652_1d33d7bdf2ad7262.mp4`）；浅色与暗色主题均实测：「画面比例 / 分辨率 / 动作强度」`Select` 与提示词 `Input.TextArea` 在浅色下为白底深字、暗色下为深底浅字（实测 `background` 分别 `rgb(255,255,255)` / `rgb(30,34,41)`，`color` 分别 `rgb(23,26,31)` / `rgb(243,245,247)`），下拉弹层随根级 `data-theme` 切换、无串色。未做移动端检查。
- 回滚方式：删除 `ActionShotTool.tsx`、`action-shot-tool.css`、`generation/action-shot.ts` 及其测试、`tool-covers/action-shot.jpg`，移除 `tool-registry.ts` 的 `action-shot` 条目与 `action-shot` 图标键、`tool-icons.ts` 的 `Swords` 映射、`ToolsWorkspace.tsx` 的 import 与分支、`paths.ts` 的 `toolActionShot` 两处登记、`tools.test.ts` 的新增用例，即回到只有生成页与导演台入口的状态；打斗工作流本身不受影响。


## 2026-11-07 资产生图：槽位模型与 identity 比例放开

- 变更原因：画布创作面板开始为资产槽位发送 `model` 与 identity 的 `aspect_ratio`（此前后端已支持 `payload.model`，但 identity 比例被 `IDENTITY_SHEET_ASPECT_RATIO` 强制 16:9）。
- 当前基线：`generate_asset_image` 的 identity 分支按 `GRS_VIP_SIZES` 校验请求比例（非法回退 16:9），2K 尺寸由 `asset_image_prompts.identity_sheet_dimensions()` 推导（16:9 仍为 2048×1152，其余取注册表 `GRS_VIP_SIZES[aspect]["2K"]`）；`build_identity_generation(..., aspect_ratio="16:9")` 把比例贯通到角色设定板提示词模板（英文 LAYOUT / REFERENCE ROLE、中文纯文生图指令参数化 + 非 16:9 版面适配指令）。`project_detail_service` 不再在 identity 分支覆盖 payload 比例；`grs_wire_aspect_ratio` 与 GRS 请求协议不变。
- 受影响文件：`backend/app/media_studio/services/asset_image_prompts.py`、`backend/app/media_studio/services/project_detail_service.py`、`backend/tests/test_asset_canvas_upload.py`（新增 model 按 workflow_id 解析、identity 9:16 生效、非法比例回退 3 项）。
- 兼容性：不传 `aspect_ratio` 的 identity 请求行为不变（16:9 / 2K / 2048×1152）；非 identity 槽位的 `payload.model` / `aspect_ratio` 逻辑无改动。无端口、数据库、任务队列与节点变更。
- 验证命令：`python -m pytest backend/tests/test_asset_canvas_upload.py backend/tests/test_asset_source_references.py backend/tests/test_canvas_character_design.py`。
- 回滚方式：还原 `asset_image_prompts.py` 与 `project_detail_service.py` 中 identity 分支的对应改动并移除新增测试即可，无数据迁移。
