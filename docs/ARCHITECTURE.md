# ZLY AI Video Studio 架构快照

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
- 当前视觉基线：画布专用全局顶栏 60px、导航 86px、命令栏 64px；58px 工具轨、226×327px 添加菜单、360px 属性面板、375×49px 视图栏、174×101px 小地图。`canvas-fidelity.css` 只扩展画布语义变量和主题样式；浅暗主题仍由根 Provider 驱动。原图保持不变，截图与测量记录在 `docs/design-ref-canvas/`。
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
- 当前基线：逐镜/选中镜写入时把旧原片归档进 `beat.video_takes`（`data_json`，不新建表），`video_url` 默认采用最新。成片 Tab 列出本镜全部成功 Take，预览任意一条，`POST …/video-takes/adopt` 才把它变成正式成片。合成、配音提取、顶栏超分仍只读采用版 `video_url`。2x 挂在对应原片 Take 的 `upscaled_url`，不单独成 Take。整集直出 / 拼接不进单镜条带。历史任务由工坊已有 `listJobs` 按镜回填。不改 H3 节点，不引入已下线的 Recipe `shot.takes`。
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
        -> OpenAI 兼容 TTS（/v1/audio/speech，可复用 LLM 凭据或独立配置）
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
| `backend/app/rtx_vsr_workflow.py` | 独立 RTX 2x 超分 API graph（不占用 H3 节点 ID） |
| `backend/app/minimax_h3_t8_workflow.py` | 生成全能参考多速率与双时钟 T8 API graph |
| `backend/app/comfy_provider.py` | 超级管理员可配置的 ComfyUI 连接地址、连接测试与运行时解析 |
| `backend/app/comfy_service.py` | 上传素材、提交 ComfyUI prompt、轮询、下载结果；队列空闲时 `POST /free` 卸载模型 |
| `backend/app/director_compiler.py` | 导演台按 MiniMax H3 官方 skill 编译提示词、Recipe 参考图装箱，按所选工作流族自动路由 T2V/I2V/R2V |
| `backend/app/director_catalog/` | 9 类 34 条画风 JSON 种子与查询 |
| `backend/app/director_recipe.py` | Recipe / 批量 payload 规范化、画风目录校验、旧时间轴转 Recipe |
| `backend/app/director_library.py` | 员工级人物/场景/道具资产库规范化、从 Recipe 快照、插入工程 |
| `backend/app/voice_bank/` | 内置短剧配音声线：IndexTTS 官方示例 wav + 产品侧角色名 |
| `backend/app/tts_provider.py` | 独立 TTS 供应商；硅基 CosyVoice 走 OpenAI 兼容 `/audio/speech`；本机 IndexTTS-2.5 走旁路 `/v1/tts/clone` 与 `/health` `/free` |
| `backend/app/gpu_runtime.py` | H3（ComfyUI）与 IndexTTS 同卡互斥：领取前卸载对方；空闲 `/free` 不得打断占用中的一方 |
| `backend/app/media_studio/services/dubbing_mix.py` | 台词混音策略与 ffmpeg 叠轨；半解说包旁白门闩 |
| `backend/app/worker.py` | 单任务串行执行；Comfy 跑前 `occupy_gpu("comfy")` 卸载 IndexTTS；队列空闲且 GPU 未被 TTS/H3 占用时才 `POST /free` |
| `tools/indextts_sidecar/` | IndexTTS-2.5 旁路 HTTP 服务（不进 FastAPI venv，权重在父级整合包） |
| `backend/app/media_studio/services/dubbing_service.py` | 导演台2 台词轨展开、单句导演参数、配音生成调度 |
| `backend/app/director_export.py` | 逐镜 TTS、BGM、ffmpeg 成片、FCPXML/EDL；失败镜头不进入成片 |
| `backend/app/director_agents.py` | 顺序调度；导演对话走 SSE 流式读取（连接 20 秒、分块空闲 300 秒）；独立 `episodes` agent 写集大纲，分镜优先消费已确认结构；分镜读取官方 h3-prompt-writing，并依次做时长润色与 Seedance 风格衔接润色；配音/配乐写可播放媒体元数据；绑定技能包时 `_system` 注入 `inject_craft` |
| `backend/app/skill_packs/` | 技能包配方（Hub 官方 Markdown + `meta.yaml` + `summary`）与步骤注册表；首页/顶栏绑定项目 `extra.skill_pack_id`；工坊一次写官方八块中文分秒稿和英文六段；半解说包临时 `skip_program_pack` 出片用 GPT 英文、不程序装箱；R2V 绑角色卡+场景卡+三联三格成片画幅构图（不送 16:9 母图）；导台2 四阶段按官方标题 `inject_craft` |
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
- 隐藏：`nvidia-rtx-vsr` 不出现在创作页模型列表。把已成功成片交给当前连接 ComfyUI 的 `RTXVideoSuperResolution`（固定 2x / ULTRA），由已成功视频结果卡的「超分」、`POST /api/jobs/{job_id}/upscale`、工坊逐镜 `POST …/beats/{id}/upscale`，或全部任务 `POST …/projects/{id}/jobs/{job_id}/upscale` 触发。H3 生成选项不再自动接跑 RTX 超分；整集直出与拼接片可在全部任务手动点。显存门闸读当前连接 GPU 的 `vram_total`，过长可能被拒绝。

H3 options 使用 JSON：`aspect_ratio`、`quality`、`duration`、`speed`、`weight_profile`，以及自定义时的 `custom_steps`。全部 H3 工作流另有 `refine_enabled` / `refine_quality`，且不再向界面或标准化结果暴露 `upscale_after`（旧客户端传入会被忽略）。比例接受任意有限正数的 `宽:高` 格式；分辨率由注册表提供可用尺寸档位并映射到内部 `megapixels`。`speed` 为语义预设：`fast`（4 步加速）、`balanced`（8 步加速，默认）、`quality`（20 步、关闭加速 LoRA）、`custom`（1–40 步）。`weight_profile` 为 `full`（默认，约 32 GB 全量 INT8，可挂加速 LoRA）或 `pruned`（约 20 GB 精简 INT8，强制关闭加速 LoRA，步数仍由 `speed` 决定）。开启 `refine_enabled` 后，一采固定 0.4 MP，二采目标 `refine_quality` 取 `1.0` / `2.0`；一采步数、LoRA、unet、采样器与 Sage 由平台按工作流族锁定，用户提交的 `speed` / `weight_profile` / `custom_steps` 会被覆盖（官方 H3 精简权重 8 步 FL2V LoRA；LightX2V 完整权重 4 步；八步双加速完整权重 8 步；Director 加速精简权重 20 步；T8 完整权重 8 步并改用 Director 管线）。`quality`、`speed`、`weight_profile`（及 T8 `custom_steps`）在二采开启时隐藏，运行参数快照回写实际生效的一采值与二采目标。RTX 2x 超分仍是已成功成片的独立手动操作，不再由 H3 创建选项自动触发。界面按当前比例显示实际输出尺寸，尺寸会按 32 的倍数计算并保持模型画布上限，时长为 2–15 秒，帧数按 H3 的 24fps、17n+5 时间网格对齐。

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
