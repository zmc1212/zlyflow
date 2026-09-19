# ZLY AI Video Studio 架构快照

更新时间：2026-09-19

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
- 当前基线：新 payload kind `hypit_replication`，路由 `/director/hypit/:projectId`。导演台与导演台2 首页第四张卡「Hypit 复刻」文案为拆结构、换内容、合字幕图形。后端子进程调本机 `hypit` CLI（默认 `D:\zlyun\hypit-poc`，工程目录 `data/hypit/{user}/{project}`），不 vendoring monorepo。拉片 `hypit_transcribe`（WhisperX），编译 `hypit_compile`（check/plan/build）；H3 走现有 8188，编译期间 `occupy_gpu("comfy")`。没有 `.svrun` 时提示用 Coding Agent 写 SVML。VACE `analyze_reference_video` / `replicate_shots` / `/director/replication/:id` 零改动。CLI 报告保留 Hypit 名称。
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
- 当前基线：`build_dual_author_system` 不再拼接 `packing_system_prompt`。半解说包 `skip_program_pack` 时，中文八块与英文六段都必须通过校验才写回 Beat；出片英文只规范化 `<Picture>` / `<Subject>`，不再 `render_ref2va`、不再灌水句。LLM 或校验失败则 `h3_prompt` 任务 `failed`，`payload` 保留 `author_errors`、`vision_*` 与截断残稿，不覆盖上一版 `h3_prompt` / `timestamped_zh_prompt`，禁止骨架填空当成功。工坊失败 toast 显示真实原因，直播残稿保留，状态芯片为「生成失败」。`fill_timestamped_zh_prompt` 只给模板单测，不进入工坊成功路径。未绑技能包仍走默认程序装箱。
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
- 当前基线：配方 `packing_overrides.skip_program_pack`。半解说包临时为 `true`。打开后：`polish_ref2va` 只有合法 `authored_en_prompt`（六段标题且校验通过）才出片，不再 `render_ref2va` + 灌时间码；英文缺失、无六段标题或校验失败则任务失败，不回退无时间码骨架、不覆盖 Beat。`generate_h3_prompt` 与双稿写稿不再 `prepare` / overlay / 第二次装箱 LLM。工坊 `h3_prompt` 落库与出片只规范化 `<Picture>` / `<Subject>`。校验放宽到六段标题、台词逐字、`<Picture n>`，280 英文词不再挡短稿。中文分秒仍写入 `timestamped_zh_prompt`。未绑技能包仍走默认程序装箱。把 `meta.yaml` 该行改回 `false` 即恢复。
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
| `frontend/src/App.tsx` | 已登录创作台壳：由 URL 驱动生成/导演台（/director2）/导演台2（/director）/资产、图/视频与选中任务；工作流、参考图草稿仍在组件 state |
| `frontend/src/xiaji/XiajiStudioModule.tsx` | 导台2：项目内内容库、资产库、剧集工坊、全部任务 |
| `frontend/src/xiaji/XiajiHome.tsx` | 导台2 项目列表与新建 |
| `frontend/src/xiaji/XiajiAssetsModule.tsx` | 导台2 资产库：角色/场景/道具/声线定义与生成 |
| `frontend/src/xiaji/XiajiWorkshopModule.tsx` | 导台2 剧集工坊：规划落库、脚本 Beat、镜头与成片合成 |
| `frontend/src/xiaji/XiajiShotsWorkbench.tsx` | 导台2 镜头工作台：左 Beat 网格、右文案/单帧/参考图 |
| `frontend/src/director/DirectorRecipeStudio.tsx` | 导演创作工作面：方案/剪辑双视图共用同一份 `director_recipe`；`?stage=` 与桌面 `?view=` |
| `frontend/src/director/components/DirectorStageNav.tsx` | 方案视图左栏四组任务导航（故事与风格 / 视觉素材 / 镜头设计 / 声音与交付）与 readiness 徽标 |
| `frontend/src/director/components/DirectorTimelineView.tsx` | 桌面剪辑视图：素材栏 + 预览/串播 + 镜头轨 + Inspector |
| `frontend/src/director/types.ts` | Recipe 类型、`recipeReadiness` 派生、`?view=` / `?stage=` 解析 |
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
| `backend/app/skill_packs/` | 技能包配方（Hub 官方 Markdown + `meta.yaml`）与步骤注册表；工坊一次写官方八块中文分秒稿和英文六段；半解说包临时 `skip_program_pack` 出片用 GPT 英文、不程序装箱；R2V 绑角色卡+场景卡+起幅；导台2 四阶段按官方标题 `inject_craft`；项目 `extra.skill_pack_id` 绑定 |
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

- LightX2V：`minimax-h3-lightx2v-t2v`（0 张）、`minimax-h3-lightx2v-i2v`（1-2 张首尾帧）、`minimax-h3-lightx2v-r2v`（1-9 张参考图）。默认 1.0 MP、快速 4 步、euler 采样，加载 `G:\ComfyUI-Models\lightx2v` 下的 LightX2V LoRA；官方 H3 三个模式的节点 ID 不改动。
- 八步双加速：`minimax-h3-dual-accel-t2v`（0 张）、`minimax-h3-dual-accel-i2v`（1-2 张首尾帧）、`minimax-h3-dual-accel-r2v`（1-9 张参考图）。复用参考 JSON 的加速链：`LoraLoaderModelOnly`（`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`，强度 1.0）→ `PathchSageAttentionKJ`（`auto` / 禁止 compile）→ `MiniMaxH3MemoryEfficientSageAttentionPatch`，默认 0.4 MP、8 步 `res_multistep` 与 video/audio Shift 12/3。不接入 `MiniMaxH3Director` 节点；文生/首尾帧用全量 INT8 FL2VA，多参考用全量 INT8 Ref2VA。
- 官方 MiniMax H3：`minimax-h3-t2v`、`minimax-h3-i2v`、`minimax-h3-r2v`。动态 API graph 在既有节点 1–15 之后接入 `ReservedVRAMSetter`（预留 3 GB 并在采样前清缓存）与 `MiniMaxH3MemoryEfficientSageAttentionPatch`，避免 16GB 显卡在 `SamplerCustomAdvanced` 的 INT8 QKV 上 OOM。既有节点 ID 不变。
- 自定义：`minimax-h3-t8-all-reference`（0-9 张；无图 `T2VA`+FL2VA，有图 `Ref2VA`+Ref2VA，`MiniMaxH3MultiRateSamplerEXPT8`）、`minimax-h3-t8-dual-clock`（0-1 张；无图 `T2VA`，单图 `I2VA` 首帧，`MiniMaxH3DualClockSamplerT8`）。
- 隐藏：`nvidia-rtx-vsr` 不出现在创作页模型列表。把已成功成片交给当前连接 ComfyUI 的 `RTXVideoSuperResolution`（固定 2x / ULTRA），由创作页「出片后 2x 超分」、`POST /api/jobs/{job_id}/upscale`、工坊逐镜 `upscale_after` / `POST …/beats/{id}/upscale`，或全部任务 `POST …/projects/{id}/jobs/{job_id}/upscale` 触发。整集直出与拼接片不自动超分，可在全部任务手动点。显存门闸读当前连接 GPU 的 `vram_total`，过长可能被拒绝。

H3 options 使用 JSON：`aspect_ratio`、`quality`、`duration`、`speed`、`weight_profile`，以及自定义时的 `custom_steps`，可选 `upscale_after`。比例接受任意有限正数的 `宽:高` 格式；分辨率由注册表提供可用尺寸档位并映射到内部 `megapixels`。`speed` 为语义预设：`fast`（4 步加速）、`balanced`（8 步加速，默认）、`quality`（20 步、关闭加速 LoRA）、`custom`（1–40 步）。`weight_profile` 为 `full`（默认，约 32 GB 全量 INT8，可挂加速 LoRA）或 `pruned`（约 20 GB 精简 INT8，强制关闭加速 LoRA，步数仍由 `speed` 决定）。`upscale_after` 为更多设置中的布尔开关，成片成功后卸载 H3 再跑独立 2x 超分（工坊仅逐镜/选中镜自动接跑）。界面按当前比例显示实际输出尺寸，尺寸会按 32 的倍数计算并保持模型画布上限，时长为 2–15 秒，帧数按 H3 的 24fps、17n+5 时间网格对齐。

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
- 当前基线：`App.tsx` 在 `generate` 与 `director` 工作区启用任务列表轮询（资产页、导台2 仍关闭）。有排队/运行/中断任务时约 4 秒刷新，空闲约 15 秒。`DirectorRecipeStudio` 在镜头出片或静帧进行中也会 1.5 秒轮询工程，打开工程时后端 `sync_recipe_asset_images` 继续把 `jobs.progress` 写回 Recipe。
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
