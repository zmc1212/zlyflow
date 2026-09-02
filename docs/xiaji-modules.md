# 虾集五大模块功能说明

本文整理 DramaClaw 当前“虾集”工作区的五个业务模块：虾料、虾塘、虾镜、虾导和虾格。内容以现有前端路由、后端 API、任务执行器和文档为依据，用于产品理解、测试设计和独立产品重建。

> 本文是工程说明，不是许可证授权文件。当前仓库采用 Elastic License 2.0；若将这些能力重新实现为对外托管服务，必须单独进行许可证和知识产权审查。

## 1. 总体关系

```text
虾料：导入小说/剧本文本，形成章节和知识上下文
  ↓
虾塘：沉淀角色、场景、道具、声线等可复用资产
  ↓
虾镜：按剧集拆分场景和镜头，生成并审核视听素材
  ↓
导出：配音、字幕、时间线合成和成片交付

虾格：为虾塘和虾镜提供项目级视觉风格约束
虾导：围绕项目状态调用查询和写入工具，辅助推进上述流程
```

顶部导航将五个模块注册为项目级子路由：

| 模块 | 当前路由 | 主要后端入口 |
|---|---|---|
| 虾料 | `/projects/{project}/ingest` | `src/novelvideo/api/routes/ingest.py` |
| 虾塘 | `/projects/{project}/characters`，并包含场景、道具等资产页 | `characters.py`、`scenes.py`、`props.py`、`assets.py` |
| 虾镜 | `/projects/{project}/episodes` | `episodes.py`、`scripts.py`、任务 runners |
| 虾导 | `/projects/{project}/assistant` | `chat.py`、`chat/service.py`、MCP 插件 |
| 虾格 | `/projects/{project}/styles` | `styles.py`、`services/style_service.py` |

## 2. 虾料：文本导入与知识准备

### 2.1 定位

虾料是项目的输入模块，负责把小说、剧本或其他叙事文本变成可编辑的章节、摘要、人物和场景上下文。它不是简单文件上传，而是后续资产提取和剧集规划的起点。

### 2.2 用户流程

1. 用户进入项目的虾料页面。
2. 上传文本文件，系统检测文件名、格式、编码和大小。
3. 服务将文件保存到项目工作目录或对象存储，并返回上传结果。
4. 用户确认导入参数，启动异步导入任务。
5. 任务解析章节，生成统计信息和可供检索的知识图谱/索引。
6. 用户查看章节预览、字符数、预计剧集数和解析日志。
7. 用户修正章节标题、顺序或内容后，再进入资产提取和剧集规划。

### 2.3 主要能力

- 支持文本上传和不支持格式的明确错误提示。
- 长文本分块、章节标题识别、章节合并/拆分。
- 提取简介、人物候选、场景候选及章节元数据。
- 生成章节统计：总字符数、计费字符数、检测到的章节数、预计剧集数。
- 将解析结果写入知识库，供后续检索和 Agent 使用。
- 导入过程以任务形式运行，支持进度、日志、失败信息和重试。

### 2.4 代码入口

- API：`src/novelvideo/api/routes/ingest.py`
  - `GET /projects/{project}/ingest/graph`
  - `POST /projects/{project}/ingest/upload`
  - `POST /projects/{project}/ingest/start`
- 任务：`src/novelvideo/task_backend/runners/ingest.py`
- 解析与知识处理：`src/novelvideo/cognee/pipeline.py`、`script_parser.py`
- 页面：`frontend/src/routes/_app/projects.$project/ingest.tsx`

### 2.5 输入、输出与状态

输入包括文件、项目标识、导入选项和用户确认。输出包括原始文件记录、章节列表、摘要、候选实体、知识库索引和任务记录。

推荐状态：`uploaded → parsing → indexed → review_required → ready`；失败状态应携带可读原因，并允许从最近成功阶段恢复。

### 2.6 异常边界

- 编码无法识别或文件格式不受支持。
- 空文件、超大文件、重复导入。
- 章节标题格式不规则，导致章节数量或顺序异常。
- LLM 返回非结构化内容或知识库写入失败。
- 任务中断后重复提交，必须保证幂等。

### 2.7 独立重建建议

先实现 TXT/DOCX/Markdown 三种格式、规则章节识别和人工校正，再增加 LLM 提取。导入结果必须保存原文版本和解析版本，避免模型升级后无法复现历史结果。

## 3. 虾塘：统一资产与身份一致性

### 3.1 定位

虾塘是项目资产库，集中管理角色、场景、道具和声线，并把参考图、生成图、身份信息和版本历史绑定到实体。它的核心价值是让多个章节和镜头复用同一套视觉/听觉资产。

### 3.2 资产类型

| 类型 | 内容 | 典型用途 |
|---|---|---|
| 角色 | 姓名、别名、外观、身份图、肖像、声音 | 保持人物外观和声线稳定 |
| 场景 | 场景描述、环境方向信息、主图、全景/世界资产 | 统一空间和环境连续性 |
| 道具 | 名称、用途、参考图、别名 | 在镜头中复用关键物件 |
| 声线 | 音色、参考音频、语言和供应商参数 | 配音或声音克隆 |

### 3.3 用户流程

1. 从虾料解析结果中生成资产候选，或手动新建资产。
2. 用户补充描述、别名、分类和参考媒体。
3. 对角色、场景和道具生成一个或多个参考版本。
4. 用户选择正式版本，必要时恢复历史版本。
5. 在镜头/剧集生成时绑定资产，生成结果反向写回资产引用。
6. 资产变更时显示引用关系，避免无意破坏已有镜头。

### 3.4 主要能力

- 角色、场景、道具的增删改查和批量构建。
- 角色身份图、肖像、主图和历史版本管理。
- 场景主图、反向视角、全景、3D/世界包等扩展资产。
- 道具参考图单个生成和批量生成。
- 声线槽位、参考音频、角色/身份级声音配置。
- 资产引用查询：哪些剧集、场景、镜头正在使用该资产。
- 不同图片供应商和模型的项目级选择。

### 3.5 代码入口

- 角色 API：`src/novelvideo/api/routes/characters.py`
- 场景 API：`src/novelvideo/api/routes/scenes.py`
- 道具 API：`src/novelvideo/api/routes/props.py`
- 引用查询：`src/novelvideo/api/routes/assets.py`
- 任务：`task_backend/runners/character_image.py`、`scene_reference.py`、`prop_reference.py`、`episode_assets.py`
- 资产服务：`services/character_ref_service.py`、`character_promotion_service.py`、`prop_ref_service.py`
- 页面：`frontend/src/routes/_app/projects.$project/characters.lazy.tsx` 及相关资产组件

### 3.6 版本和一致性规则

- 原始上传、生成候选和正式资产必须区分存储。
- 设置正式版本不能删除历史版本。
- 恢复历史版本时同步数据库记录和媒体文件。
- 被镜头引用的资产删除前必须给出依赖提示或阻止删除。
- 资产生成必须记录 Prompt、模型、参数、时间、任务 ID 和成本。

### 3.7 异常边界

- 同名资产、别名冲突、重复候选。
- 参考图缺失、格式不支持或对象存储不可用。
- 图片/声音生成超时、内容安全拦截或供应商回调重复。
- 角色主身份重复、恢复版本后引用失效。
- 场景更名时媒体目录、镜头引用和衍生场景未同步。

### 3.8 独立重建建议

以“资产主表 + 资产版本表 + 引用表 + 生成任务表”作为最小模型。先实现角色和场景，再加入道具与声线。不要把媒体文件路径直接写入业务对象，使用不可变媒体记录和逻辑资产 ID，便于迁移存储和回滚。

## 4. 虾镜：剧集、分镜与成片生产线

### 4.1 定位

虾镜是主生产线，把章节或剧集内容转化为可执行的场景、脚本、Beat/镜头、草图、视频、音频和最终导出。它是五个模块中任务编排最复杂、成本和质量风险最高的部分。

### 4.2 用户流程

1. 选择章节范围并创建剧集。
2. 生成或编辑剧集大纲、场景列表和脚本。
3. 为每个场景绑定角色、场景、道具和风格。
4. 生成镜头/Beat：画面描述、对白、景别、运镜、时长和首帧提示。
5. 批量生成草图，用户选择或编辑候选。
6. 根据草图生成视频片段和 Beat 音频。
7. 在工作台中审核、重试、替换单个镜头。
8. 合成配音、字幕、背景音乐和视频，导出 MP4、SRT 或素材包。

### 4.3 主要对象和状态

- 剧集：编号、标题、来源章节、生产状态。
- 场景：地点、时间、环境、角色集合和视觉上下文。
- 脚本：旁白、对白、动作和节拍信息。
- Beat/镜头：镜头描述、时长、画幅、首帧、视频、音频和审核状态。
- 导出：时间线、编码参数、文件 URL、失败原因。

推荐生产状态：`draft → planned → script_ready → sketching → video_ready → audio_ready → composing → review → exported`。单个镜头失败必须与整集状态解耦。

### 4.4 代码入口

- API：`src/novelvideo/api/routes/episodes.py`、`scripts.py`、`generation.py`
- 规划与审核：`agents/episode_planner.py`、`episode_reviewer.py`、`episode_fixer.py`
- 任务：`task_backend/runners/script.py`、`episode_assets.py`、`sketch.py`、`video.py`
- 生成器：`generators/image_generator.py`、`video_generator.py`、`tts_generator.py`
- 导出：`src/novelvideo/export/episode_export.py`
- 页面：`frontend/src/routes/_app/projects.$project/episodes.tsx` 及 `episodes.$episode/*`

### 4.5 批量与恢复要求

- 批量任务必须有幂等键，重复点击不重复扣费。
- 支持单镜头取消、重试、替换和断点续跑。
- 供应商回调与轮询结果统一进入任务状态机。
- 任何最终导出都要能追溯到资产版本、风格版本和生成参数。
- 合成前检查视频、音频、字幕和时长是否完整。

### 4.6 异常边界

- 脚本结构不完整、角色未绑定、场景缺参考。
- 图片成功但视频失败，或视频成功但音频失败。
- 供应商限流、超时、回调丢失、返回内容不合规。
- 画幅、帧率、编码不兼容导致 FFmpeg 合成失败。
- 单集成本超预算、无限重试或用户同时提交冲突任务。

### 4.7 独立重建建议

第一版只做单集、单时间线和有限模型适配。优先完成“可编辑状态机 + 任务可恢复 + 结果可追溯”，再做复杂运镜、3D 场景、批量优化和高级转场。生成质量应通过固定测试集持续评估，而不是只看单次演示。

导台2 镜头生成的独立重建对应关系：草图 = 色块分镜草稿；渲染图 = 按草图上色写实（可重新生成）；视频 = 渲染图驱动的 LightX2V 多参考或 I2V（本仓库 GRS + MiniMax H3 / LightX2V，不复制 NanoBanana/Seedance）。参数来自 `GET /api/modes`。

## 5. 虾导：项目级 AI 制作助手

### 5.1 定位

虾导是围绕项目上下文工作的对话式助手。它可以查询项目状态、展示资产/镜头信息、启动受控任务并解释错误，但不应被设计成拥有任意服务器权限的通用代理。

### 5.2 当前交互流程

1. 前端通过 WebSocket 建立会话。
2. 后端校验用户、项目范围和助手访问权限。
3. 加载项目上下文、聊天历史、技能配置和可用工具。
4. 助手以流式事件返回文本、工具调用、进度和媒体展示信息。
5. 写操作经过工具参数校验，必要时要求用户确认。
6. 会话、工具轨迹和错误写入聊天存储及审计记录。

### 5.3 当前能力范围

- 查询项目、剧集、资产、镜头和任务状态。
- 给出缺失前置条件和下一步建议。
- 启动导入、资产生成、脚本/镜头生成等受控任务。
- 展示图片、视频、表格或状态卡片等 UI 规格。
- 支持取消当前对话轮次和处理供应商内容安全错误。

### 5.4 代码入口

- WebSocket/API：`src/novelvideo/api/routes/chat.py`
- 核心服务：`src/novelvideo/chat/service.py`
- 历史存储：`src/novelvideo/chat/store.py`
- Agent 工作区：`hermes_workspace.py`、`hermes_sdk.py`、`hermes_pool.py`
- 项目工具：`chat/dramaclaw_mcp.py`
- 页面与文案：`frontend/src` 中 assistant 相关路由和本地化资源

### 5.5 安全和可靠性边界

- 所有工具调用必须绑定用户和项目，禁止跨租户读取。
- 写操作采用白名单工具和强类型参数，禁止任意代码执行。
- 需要确认的操作不能仅凭自然语言隐式执行。
- 对话锁、心跳、取消和过期会话必须可恢复。
- Prompt 注入、恶意附件和工具返回内容都要经过过滤。
- 模型输出不可直接作为数据库更新语句或 Shell 命令执行。

### 5.6 独立重建建议

先做“只读助手”，再开放创建任务，最后开放可确认的写操作。第一版不接入任意终端、文件系统或自动多步循环；每个工具都定义输入 Schema、权限、幂等策略、超时和审计字段。

## 6. 虾格：项目级视觉风格中心

### 6.1 定位

虾格用于定义项目的视觉统一规则，并把这些规则注入角色、场景、草图和视频提示词。它管理的是可复用的风格参数，不是单张图片滤镜。

### 6.2 风格内容

- 风格 ID、名称、描述和预览图。
- 正向风格指令、避免指令和风格 Tag。
- 色彩、材质、摄影、光照、构图等结构化参数。
- 参考图分析得到的风格参数。
- 项目默认风格和风格版本。

### 6.3 用户流程

1. 浏览内置风格或创建自定义风格。
2. 上传参考图并执行 AI 分析。
3. 检查、修改正向/负向指令和 Tag。
4. 保存风格并设置为项目默认。
5. 在资产或镜头生成时选择继承项目默认，或显式指定其他版本。
6. 新版本只影响后续生成，不改写已生成结果。

### 6.4 代码入口

- API：`src/novelvideo/api/routes/styles.py`
- 服务：`src/novelvideo/services/style_service.py`
- 分析器：`src/novelvideo/generators/style_analyzer.py`
- 预设：`src/novelvideo/styles/presets/`
- 页面：`frontend/src/routes/_app/projects.$project/styles.tsx`

### 6.5 异常边界

- 参考图格式、大小或存储配置不满足要求。
- AI 分析返回空结果、不可解析 JSON 或不符合参数范围。
- 风格 ID/名称重复，或删除了仍被镜头引用的风格。
- 风格提示词过长，超过供应商限制。
- 项目默认风格变更导致后续生成不可复现。

### 6.6 独立重建建议

使用结构化风格 Schema，避免把全部信息塞进一段不可审计文本。每次生成保存最终展开后的 Prompt 和风格版本快照；内置预设、参考图和标签应重新创作或使用明确允许商业用途的素材。

## 7. 跨模块验收清单

### 功能

- 能从文本创建项目上下文并人工修正章节。
- 能创建和版本化角色、场景、道具、声线。
- 能创建单集、编辑镜头并生成至少一种图片和视频结果。
- 能应用风格并追溯风格版本。
- 能通过助手查询状态并启动一个受控任务。
- 能合成并下载视频和字幕。

### 任务与成本

- 所有长任务有唯一 ID、状态、进度、日志、取消和重试。
- 重复回调和重复点击不会重复扣费或生成脏数据。
- 每个生成结果记录供应商、模型、参数、耗时、错误和成本。
- 任务失败可区分可重试、需人工修正和不可重试。

### 数据与安全

- 所有查询强制执行用户/Workspace/项目隔离。
- 媒体使用对象存储和短时签名 URL，禁止泄露本地路径。
- Provider 密钥加密保存，不进入前端和日志。
- 资产、风格和镜头删除前检查引用关系。
- 用户可导出和删除自己的项目数据。

### 合规

- 新产品不复制当前项目源代码、界面、文案、Prompt、预设和品牌元素。
- 依赖、字体、模型服务、FFmpeg 和媒体素材均有许可证记录。
- 保留需求、架构、测试和提交历史，证明独立实现过程。

## 8. 实现级附录：模型、关键词与 Prompt

本节补充五个模块的调用级信息。模型名称分为两类：代码中的默认值，以及通过环境变量/Provider 配置覆盖的值。生产环境必须把最终使用的模型、版本、参数和 Prompt 版本写入生成记录，不能只记录“调用了 AI”。

### 8.1 虾料调用链

**原文导入**

1. `POST /projects/{project}/ingest/upload` 接收文件，程序先做扩展名、编码、大小和空内容检查。
2. `POST /projects/{project}/ingest/start` 创建异步任务，由 `task_backend/runners/ingest.py` 执行。
3. 任务将原文写入项目存储，再调用 Cognee 的数据摄取/索引能力，形成可检索图谱。
4. 章节解析优先使用 `script_parser.py` 的规则函数（例如 `extract_synopsis`、`parse_scenes`），避免让 LLM承担明显的格式解析工作。

**剧集规划 Prompt（当前实现的字段）**

```text
System：你是一个专业的剧集规划师。将小说内容规划为 {target_episodes} 集。
每集生成：number、title、content_summary（50字以内）、main_conflict、
cliffhanger、key_events。
规则：每集有明确冲突和悬念；情节连贯；高潮放在中后期。
User：{novel_text}
```

调用 `LLMGateway.acreate_structured_output(user_text, system_prompt, EpisodeList)`，思考级别读取 `COGNEE_LLM_THINKING_LEVEL`，默认 `high`。输出必须符合 `EpisodeList` Schema；解析失败不能直接接受模型原文，应记录原始响应并重试/转人工。

**角色提取 Prompt**

1. 先用 Cognee `GRAPH_COMPLETION` 检索人物上下文，关键词是“列出小说中所有人物角色、别名、人物关系和身份信息”。
2. 将检索结果拼接为 `context_text`，传入结构化角色 Prompt。
3. Prompt 要求只提取人类角色；合并别名和年龄变体；禁止把服装写入 `face_prompt`；对不确定字段采取保守推断。
4. 输出 `CharacterEnrichmentList`：`name`、`aliases`、`role`、`is_main`、`gender`、`age_group`、`body_type`、`description`、`face_prompt`。

**场景和道具 Prompt**

- 场景：程序先定位疑似场景块，再让结构化 Agent 输出 `name`、`aliases`、`scene_type`、`time_of_day`、`interior`、`characters`。User Prompt 包含程序猜测、场景块前 30 行原文、故事梗概和人物设定。默认模型由 `SCENE_BUILD_MODEL` 控制，未配置时为 `gemini-3-flash-preview`。
- 道具：先以 `列出小说中所有重要道具物件，包括武器、信物、文书、法宝等有情节意义的物品` 检索图谱，`top_k=30`、`only_context=True`，再用结构化输出筛选剧情道具，排除普通背景物件。

### 8.2 虾塘调用链

资产生成 Prompt 由后端按固定顺序拼接，不能让前端随意覆盖：

```text
1. style_instructions       # 当前虾格的正向风格
2. asset_kind + asset_name  # character / scene / prop
3. asset_description        # 资产自身描述
4. face_prompt 或环境描述   # 角色面部、场景环境、道具外观
5. reference_image_rules    # 参考图和一致性要求
6. framing/camera/quality   # 画幅、镜头、质量参数
7. avoid_instructions       # 虾格负向约束
```

角色生成任务名为 `character_portrait`、`identity_image`；场景和道具分别使用 reference 任务。图片模型不在业务代码中固定，而由项目 Provider 配置选择。每个任务必须保存输入资产版本、最终展开 Prompt、负向 Prompt、参考图 ID、模型、尺寸、seed、供应商任务 ID、费用和输出文件。

### 8.3 虾镜调用链

`EpisodePlannerAgent` 使用 PydanticAI Agent，输出 `EpisodePlannerOutput`，模型由 `get_pydantic_model()` 提供，结构化输出失败最多重试 3 次。其 System Prompt 要求按以下关键词顺序调用工具：

```text
tool_get_story_structure()
tool_get_all_characters_for_planning()
tool_search_plot_points("主要冲突和转折")
tool_search_timeline_events("从开篇到结局的主要事件")
tool_search_character_arcs(角色名)
tool_search_relationship_changes("主要角色之间的关系变化")
tool_search_chapter_summary(章节范围)
tool_search_cliffhanger_candidates(本集内容)
```

最终每集输出：`number`、`title`、`chapter_start`、`chapter_end`、`content_summary`、`main_conflict`、`cliffhanger`、`key_events`（3-5 个）和 `character_names`。Prompt 规定第一集建立世界观，中段推进冲突，末段完成高潮；角色数量建议 3-6 人，内容量适合 3-5 分钟；`character_names` 只能从已确认角色列表选择。

镜头级 Prompt 应由结构化字段生成：`scene_context`、`beat_action`、`character_refs`、`prop_refs`、`style_snapshot`、`dialogue`、`duration_seconds`。图片、视频、TTS 三类调用分别保存 Prompt 和供应商参数，视频失败时只能重试视频步骤，不能重新规划剧集或覆盖资产版本。

### 8.4 虾导调用链

当前支持 Hermes、Claude、Codex 等后端，具体模型由 `chat/service.py` 的运行时配置决定。项目会话 Prompt 至少注入：用户身份、项目 ID、当前项目摘要、聊天历史、技能说明和 MCP 工具描述。

助手的 Prompt 约束应明确：

- 查询项目状态必须调用读取工具，禁止凭空猜测。
- 创建/修改/删除/生成必须使用白名单工具，并在需要时等待用户确认。
- 工具参数不完整时先追问，不能猜测资产名、集数或项目 ID。
- 禁止 Shell、任意 Python、任意 SQL 和未注册 MCP 工具。
- 输出任务 ID、成功/失败原因和下一步建议。

WebSocket 事件包括文本增量、工具更新、媒体展示和完成/错误事件；对话取消使用独立 HTTP 接口。每次调用保存 `model`、`prompt_version`、工具名、参数摘要、结果摘要、确认人和耗时。

### 8.5 虾格调用链

`StyleAnalyzer` 对参考图执行视觉分析。图片先压缩到最长边 1024、JPEG quality 60，再上传临时 URL。默认模型为环境变量 `STYLE_ANALYZER_MODEL`，未配置时为 `gemini-3.5-flash`；输出类型为 `StyleAnalysisResult`。

视觉分析 Prompt 的精确要求为：

```text
style_instructions：以 Create... 开头，描述渲染技术、色彩、光线、纹理、镜头感和氛围，少于100词。
avoid_instructions：以 FORBIDDEN: 开头，列出冲突风格、伪影和质量问题，少于60词。
style_tag：2-4个英文大写词，只表示媒介和成像质感。
suggested_name：简短英文名称。
suggested_label：中文显示名称。
只返回合法 JSON，不要 Markdown。
```

Prompt 禁止 `PERIOD`、`REPUBLICAN`、`ERA`、`DYNASTY`、`MODERN`、`ANCIENT`、`DRAMA`、`古装`、`民国` 等时代/剧情词，避免风格标签覆盖场景和角色语义。服务端仍需校验 JSON、长度、前缀和禁用词；不能只相信模型遵守规则。

### 8.6 独立开发时的 Prompt 管理规范

- 每个模板采用独立文件和版本号，例如 `episode_plan.v1`、`character_extract.v1`。
- Prompt 中的业务规则、字段 Schema、用户内容和检索上下文分段保存。
- 记录输入摘要和哈希，避免把整本小说或密钥写入日志。
- 结构化输出先经过 Pydantic/JSON Schema 校验，再进入数据库。
- 对模型升级建立固定回归样本，比较字段完整率、角色合并准确率、镜头可执行性和成本。
- 任何供应商切换都通过 Provider Adapter，不修改业务层 Prompt 语义。
