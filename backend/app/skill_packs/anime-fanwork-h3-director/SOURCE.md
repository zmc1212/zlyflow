# 来源与适配说明

## 联网核实结论（2026-11-11）

`MiniMax-AI/MiniMax-H3` 官方仓库共发布 9 个 skill：

- `h3-prompt-writing` —— 通用提示词底座，唯一可移植到通用 Agent 的一个。含 `references/base-en.txt`（T2VA / I2VA / FL2VA / L2VA）与 `references/ref-en.txt`（Ref2VA 六段式）。
  - Ref2VA 固定六段：`subject_definitions` → `summary` → `retention_analysis` → `detailed_description` → `overall_soundscape` → `non_diegetic_music`。
  - 多镜头用 `[Shot 1]` 无时间戳起手，后续镜以严格递增的切点时间开头；运镜写「类型 + 幅度 + 速度」；对白用稳定 speaker id，台词保留原语言；提示词上限 7000 字符。
  - 安装命令：`npx skills add https://github.com/MiniMax-AI/MiniMax-H3 --skill h3-prompt-writing`
- 其余 8 个是 **MiniMax Hub canvas 工作流专用**的风格生成器，依赖 `hub_generate_video` / `hub_generate_image` / canvas 节点，不能移植到本工作台：
  `minimalist-product-ad-generator`、`3d-animation-short-generator`、`papercraft-stop-motion-explainer`、`brand-promo-video-generator`、`music-video-subtitle-generator`、`co-op-game-intro-generator`、`paper-collage-explainer-generator`、`handdrawn-live-video-generator`。

**结论：官方没有「二创动漫 / 同人动画」专用 skill。** 最接近的 `3d-animation-short-generator` 是 3D 动画短片、`handdrawn-live-video-generator` 是真人实拍叠手绘涂鸦，都不是 2D 原作画风同人短剧。社区另有若干 `h3-prompt-writing` 派生版（分镜／状态账本向），本质仍是通用底座，不是二创动漫专用。

已有本地配方 `half-narrated-live-action-short-drama` 的官方 SKILL.md 明确写着「This is not … animation, anime …」，且 `visual_lock=photoreal-live-action-short-drama`，用在本项目会把 2D 赛璐璐资产图带偏，因此不采用。

## 本配方的做法

按用户「学思路、不复制代码」的约定，只取官方 `h3-prompt-writing` 的 Ref2VA 六段式与标签／时间线规则，自行编写二创动漫专用约束：

- 原作画风锁定与跨镜身份一致性（角色设定板 + 场景卡只锁身份与环境，不锁构图）
- 形态变化角色必须保留常态辨识锚点，杜绝「画成另一个怪物」
- 16:9 横屏、单镜 5–15 整数秒、中文八块分秒稿 + 英文六段
- 负向约束显式排除写实化、3D 化、漫画截图、文字水印、形象漂移
- 非官方同人二创标注与合规边界

工作台接线（与另两个本地配方一致）：

- `meta.yaml` → `surfaces: [director2, workshop, optimize]`，各阶段 `inject_craft`；`workshop_shot` 用已注册步骤 `write_timestamped_zh_prompt` → `polish_ref2va` → `bind_r2v_slots`。
- `SKILL.md` 的章节标题刻意包含 handlers.py `STAGE_SECTION_HEADINGS` 的匹配词（灵感／故事与剧本／角色卡／场景卡／分镜／镜头合同／提示词），使各阶段只注入对应章节。
- `references/h3-video-prompt-template.md` 由 `write_timestamped_zh_prompt` 读取，作为中文分秒稿模板。**只有第一个 ```text 围栏内的文本会经 `_extract_official_fill_skeleton` 进入双稿作者 system prompt**，围栏外的说明模型看不到；所有硬规则都必须写在围栏内。

## 首轮写稿失败复盘（2026-11-11）

首轮三集视频任务全部在 `prompt_generation` 阶段被写稿校验拦下，与生成模型无关，是配方模板与工作台校验器没对齐：

| 任务 | 报错 | 根因 |
|---|---|---|
| 第 1 集 | `speech tags missing or out of performance order` | 旧剧本台词书写顺序是 路飞/西格/香克斯，而模型按画面时间码把 `<d>` 写成 香克斯/西格/路飞。`ordered_speech_events()` 以**剧本台词顺序**为表演顺序，两者不一致即失败。 |
| 第 2 集 | `missing <Picture 1>；missing <Picture 2>；missing <Picture 3>` | 英文 `subject_definitions` 写成 `Black Ape (Picture 1)`、`Retain Picture 2`，**丢了尖括号**；`llm_service._validate_h3_prompt` 按 `<Picture n>` 正则硬查。 |
| 第 3 集 | `多轮对白必须拆进不同时间段，禁止整段落在同一段` | 日语长句被 `split_speech_atoms` 按 `！！` 切碎，模型把残句写成「！」；且「按旁白和画面内容切镜」段里没有台词原文，`_speech_split_errors` 判定多轮对白落在同一时间段。 |

对应修复：

1. 剧本侧：台词按表演时间顺序书写、改成单句单标点（句中不再有 `。！？`）、每镜开口不超过 3 句；`_beats_from_document_shots` 不带 subtitle，独立「旁白：」行会被解析器吃掉，改为在台词块里写 `画外音：「…」`（`_INNER_MARK_RE` 命中「画外音」→ 画外音通道，且不以 `旁白：` 开头所以不会被当成字幕字段）。
2. 模板侧：把「顺序 / 逐字 / 分秒落位 / 三通道 / 尖括号参考标签 / 六段顺序 / 对白标签 / 画幅」八条硬规则写进代码围栏内。
3. `_han_only` 只取汉字，日语台词靠汉字片段做逐字匹配；因此**禁止翻译或截断日语原文**比要求「更多汉字」更关键。

## 生效条件

`skill_packs.recipe` 有**进程级配方缓存**，且 7865 后端以 `uvicorn ... --host 0.0.0.0 --port 7865` 启动、**未开 `--reload`**。新增目录后必须重启后端（或进程内调用 `reset_pack_cache()`）才能出现在 `GET /api/skill-packs`，否则 `PUT /api/projects/{id}` 绑定时会返回「未知技能包」。
