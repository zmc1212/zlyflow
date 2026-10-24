# WorkRally 智能剪辑对照分析（REA 证据版）

日期：2026-10-21
目标：用 [REA](https://github.com/morluto/rea) 与线上页面、前端 bundle 原文分析 [WorkRally Smart Clip](https://workrally.qq.com/smart-clip) 的做法，判断哪些能力可以完善本工作台的智能助手，并记录本次已实现与明确未实现的边界。

## 结论摘要

- WorkRally 的关键不是“让模型直接剪片”，而是四段式：**用户发起 → 视频理解 → 宿主生成策略卡 → 用户点「确认剪辑」→ 确定性执行**。模型被禁止在理解完成前改时间线，也被禁止用 `split_elements` / `resize_elements` / `delete_elements` / `move_elements` 自行执行。
- 本工作台的智能剪辑助手已经具备同样重要的授权、版本校验、幂等执行和账号隔离。本次先补“理解依据”和 WorkRally 的五种引流剪辑策略，再补上用户显式触发的真实关键帧画面理解。
- 本次已补：`editor_read` 返回结构化理解摘要（分镜/对白/高光候选与理由）；新增 `hook_cut` 引流剪辑与 `conflict_3s`、`climax_only`、`quote_open`、`ending_hook`、`trailer` 五种策略；授权弹窗显示策略、逐镜理由和策略原则。
- 后续已补：新增「视频理解」卡片，用户确认后按镜头下载时间线素材，先用 FFmpeg 检测素材内部镜头边界，再对采样镜头各取 2 个关键帧并调用已配置的 VLM，逐镜保存画面描述、机位与主体（每条素材最多 4 镜、全时间线最多 40 镜）；理解结果进入 `editor_read.analysis.understanding`，并参与剪辑评分和授权弹窗的「理解依据」回显。没有伪造 ASR 或完整 `understand_full`：音频不转写，素材变化后旧证据自动失效。
- 仍未实现：ASR 字幕、去废片、智能拆条、一键调色、按轨导出，以及 WorkRally 对整条成片的逐段 `understand_full`。

## 1. 证据与方法

### 1.1 REA 静态分析

- 工具：`rea-agents@6.7.0`，分析器 `REA JavaScript application analyzer` v1。
- 命令：`npx -y rea-agents@latest analyze-javascript-application .tmp/rea-smartclip --artifact-format directory --source-path umi.js --format json`。
- 分析对象：线上 `/smart-clip` 的 Umi bundle `umi.js`，19,924,101 字节。
- 目录摘要 SHA-256：`4c76261c4058dc9dce2ee08f22baa5ac827631d651b543be3741f8462c0b7f13`。
- JavaScript 资产摘要 SHA-256：`6762bcd37ab70a4a624a9690c4aa8005ebaa76e70452c42589936e55e6d2f463`。
- Evidence ID：`ev_33af01c3f766d8e020831f74859563e8ac73fd3c7e6c2f20cb090432848b2c53`。
- 分析器明确记录的限制：

> `umi.js: Resource constraint during analyze_javascript_application: Owned JavaScript worker exhausted its heap while analyzing umi.js during parse`

> `Graph coverage is incomplete; unavailable facts remain explicit and must not be read as absence.`

> `JavaScript and HTML were parsed as inert text; bundle bootstrap code was never executed.`

使用 `--max-heap-mb 8192 --max-semantic-nodes 200000 --analysis-timeout-ms 600000` 复跑后仍停留在 `Parsing and projecting umi.js (1/1)`，已停止。因此本文把 REA 证据当作线索，并用线上可见文本和 bundle 原文交叉验证，不把静态字符串等同于服务器真实行为。

### 1.2 线上页面可见文本

2026-10-21 直接打开无需登录的 `/smart-clip` 读取可见文本，页面标题为“WorkRally-漫剧视频创作全流程-腾讯视频智能制作平台”。页面可见：

- 顶栏：`选择剧集`、`自适应窗口`、`智能助手`、`Skill`、`新对话`。
- 欢迎语：`Hi，我是您的智能剪辑助手` / `基于音视频理解与AI剪辑工程，我能帮您：`
- 能力入口：`素材归位`、`视频铺轨`、`素材拼接`、`智能剪辑`、`成片速剪`、`引流剪辑`、`高光合集`、`智能拆条`、`智能分镜`、`去掉废片`、`收尾导出`、`一键调色`、`字幕转写`、`按轨导出`。
- 输入区：`引用`、`Skill`、`专家`、`知识库`、`模型`。

可见其助手外壳与本工作台 V2 的 Skill / 专家 / 知识库 / 模型组合一致，差距主要在剪辑媒体能力和操作数量。

### 1.3 Bundle 原文

以下为 bundle 中的原字符串（节选）：

- 引流剪辑流程：

> 用户确认后必须先出现“视频理解”状态卡（宿主先跑 understand_timeline_media）。理解成功后宿主按授权卡所选方式、结合 understand_full 出钩子策略和“确认剪辑”按钮。……不要替用户选方式。不要调用 propose_cut_plan 另写一份，不要自己调 split_elements / resize_elements / delete_elements / move_elements，不要只在对话里写策略。理解完成前不要自己改时间线。

- 成片速剪流程：

> 用户确认后必须先出现“视频理解”状态卡（宿主先跑 understand_timeline_media）。理解成功后宿主按每条成片的 understand_full 先出剪辑策略和“确认剪辑”按钮。原则：砍废片、压过程、留对白。不保证故事讲完。禁止全部整段保留。

- 理解限制：

> 成片超过 20MB，请先裁短再理解
>
> 时间线上没有可理解的成片素材
>
> 视频理解结果获取失败，请重试
>
> 视频理解没有找到可保留的钩子片段

- 功能名：`QUICK_CUT_HIGHLIGHTS_NAME="引流剪辑"`、`QUICK_CUT_REEL_NAME="高光合集"`、`QUICK_CUT_SHORTS_NAME="智能拆条"`、`SMART_SPLIT_NAME="智能分镜"`、`CUT_WASTE_NAME="去掉废片"`。

## 2. WorkRally 的做法

1. 用户在剪辑页选择操作（如成片速剪、引流剪辑）并发起。
2. 用户确认后，宿主先显示“视频理解”状态卡并执行 `understand_timeline_media`；成片类操作再逐条执行 `understand_full`。
3. 理解成功后，宿主依据理解结果和用户在授权卡中选择的方式生成策略卡与「确认剪辑」按钮。
4. 用户点击「确认剪辑」后才执行；模型不能自行改时间线，也不能另写一份方案。
5. 理解失败、素材缺失、超过 20MB 等都有明确失败文案，不进入执行。

策略原文（WorkRally 使用连字符 ID，本工作台使用下划线 ID）：

| WorkRally ID | 本工作台 ID | 中文 | 规则 |
| --- | --- | --- | --- |
| `conflict-in-3s` | `conflict_3s` | 3秒进冲突 | 从冲突起刀，丢掉开场铺垫和不重要剧情，约裁一半，超过 1 分钟压到约 30 秒 |
| `climax-only` | `climax_only` | 只留高潮 | 只留理解分最高的高光场次 |
| `quote-open` | `quote_open` | 金句开场 | 先出最重要的对白金句，再接其余对白高光 |
| `ending-hook` | `ending_hook` | 结尾悬念 | 只留后半段高光，掐掉结局收束 |
| `trailer` | `trailer` | 预告片 | 爆点冷开，金句对切，结尾不给答案 |

核心设计：**策略由宿主锁定并执行，模型只负责对话和解释**。这与本工作台“模型只能提案、不能跳过授权”的既有约束一致。

## 3. 与本工作台的差距

| 能力 | WorkRally | 本次变更前 | 本次处理 |
| --- | --- | --- | --- |
| 剪辑页专属助手、工程/分集上下文 | 有 | 有 | 保留 |
| 智能铺轨 | 有 | 有 | 保留 |
| 对白精剪/成片速剪/高光合集 | 有 | 有（确定性规则） | 保留 |
| 自动字幕 | 有（音轨转写） | 有（按剧本对白铺字幕，非 ASR） | 保持边界说明 |
| 视频理解 | `understand_timeline_media` + `understand_full` | 有关键帧 + VLM 的逐镜画面理解 | 本版补 FFmpeg 镜头边界检测与镜头级采样（每素材最多 4 镜、全片最多 40 镜）；仍需用户显式触发，不做 ASR |
| 理解证据回显 | 有 | 无 | `editor_read.analysis` 返回高光候选、对白秒数、素材与镜头级画面理解；授权弹窗显示镜头边界检测后的“理解依据” |
| 引流剪辑五种策略 | 有 | 无 | 新增 `hook_cut` 与五种策略 |
| 逐镜保留理由 | 有 | 无 | 授权清单显示每镜 `reason` |
| 用户确认 + 确定性执行 | 有 | 有（revision CAS、幂等） | 保留，并扩展同一流程 |
| 模型不得直接改时间线 | 有 | 有 | 保留；策略未指定时必须先问用户 |
| 智能分镜/去废片/智能拆条/一键调色/按轨导出 | 有 | 无 | 未实现；需要额外媒体/渲染能力 |

## 4. 本次实现

### 4.1 理解摘要

`backend/app/director_assistant/editing.py` 的 `editor_read` 现在返回 `analysis`：

- 自由剪辑：`{kind:"free", video_count, clip_count}`。
- 分集：`{kind:"episode", beat_count, video_count, dialogue_beat_count, dialogue_seconds, highlight_candidates}`。
- `highlight_candidates` 最多 8 项，字段为 `beat_id, sequence, heading, duration, dialogue_seconds, score, reasons`。
- 评分基于高光关键词、对白秒数和文本信息量；理由如“冲突/高光：冲突、真相”“对白 2.8 秒”“常规叙事镜头”。

边界：这是**文本/元数据摘要**；画面识别由 4.2 的独立「视频理解」补充，二者在 `analysis` 中分别返回。

### 4.2 视频画面理解（关键帧 + VLM）

`backend/app/director_assistant/understanding.py` 新增账号隔离的 `MediaUnderstanding`：

- 用户必须显式触发，入口为智能剪辑助手的「视频理解」卡片；开始前明确说明会检测素材内部镜头、对采样镜头各抽取 2 个关键帧并调用视觉模型，不转写音频、不改时间线。
- 只处理当前分集时间线已使用的视频：从七牛云可信域名下载，`ffprobe` 校验画面；`video_analysis.detect_scenes` 以 FFmpeg `select='gt(scene,0.32)',showinfo` 解析镜头边界，最短镜头 0.8 秒，异常或未检出时回退整段素材。
- 每条素材最多采样 4 个镜头、全时间线最多 40 个；超限按等距抽样且每条素材至少 1 个。每个采样镜头在 0.2 秒和中点抽 2 帧，以 data URL 调用已配置的 VLM `analyze_video_shot`。
- 每个采样镜头独立失败隔离；单镜最多重试 2 次。镜头保存 `index/start/end/duration/status/description/camera/subjects/frames/error`，素材保存 `detected_count/sampled_count/shots[]` 与聚合描述，总记录保存 `summary/progress/model/finished_at`。记录写入既有 `ai_assistant_records` 的 `media_understanding` 类型，无新表或迁移。
- 成功后 `editor_read.analysis.understanding` 返回素材与镜头级摘要；`hook_cut` 等剪辑操作把成功镜头的画面关键词、机位和主体并入评分与 `reason`，授权弹窗显示「理解依据：镜头边界检测后采样的 N 个镜头关键帧描述」。
- 素材地址或时长变化时，`source_signature` 不匹配，`read` 标记 `stale`，`summary` 不再返回逐镜证据，`evidence` 返回空，避免用旧画面给新素材背书。运行中重复启动返回 409；超过 15 分钟的 queued/running 记录按中断恢复为 failed。
- 前端卡片显示状态、进度、模型与完成时间，并统计检测/采样/成功镜头数；可展开「逐镜画面依据」，在每条素材下列出内部镜头的时间范围、描述、机位、主体与失败原因，失败镜头可「重新理解」。轮询仅在 queued/running 时进行。

边界：每个采样镜头 2 帧；镜头检测只按画面变化切分，不做全片语义分段、质量/废片识别或 ASR；不是 WorkRally 的完整 `understand_full`。未开始或失败的卡片不会阻塞手动剪辑与确定性工具。

### 4.3 引流剪辑 `hook_cut`

新增操作与五种策略，全部由工作台确定性生成，不调用生成模型：

- 目标时长：`min(30s, max(6s, 总时长 × 50%))`。
- `conflict_3s`：最高分镜头开场，再按分数补后续镜头；不足时回补更早镜头。
- `climax_only`：只取分数最高的约 30% 镜头。
- `quote_open`：最高分对白镜头开场，再接对白高光，最后补中位数以上镜头。
- `ending_hook`：只取后半段（约后 60%）并排除最后一个镜头。
- `trailer`：最高分镜头冷开，排除结尾镜头，对白/非对白交替组接。
- 每个入选镜头带 `role`、`reason`、`trim`；确认后重建画面与配音轨，保留手工文字。

### 4.4 协议与安全边界

- `EditDraft` 只接受上述五种策略；`hook_cut` 必须带策略，其它操作不允许带策略。
- 模型和按钮共用同一 `preview` 流程；策略在后端白名单校验，不能由模型指定工程或分集。
- 用户只说“引流剪辑/钩子剪辑/预告片”但没有选方式时，助手必须先问一个问题，不得替用户选择。
- 继续复用 `ai_assistant_records` 的 `edit_proposal`、revision CAS、事务保存和幂等确认；没有新表或数据库迁移。
- 新增接口字段：`POST /actions/preview` 的可选 `strategy`，仅 `hook_cut` 使用；新增 `GET/POST /{sequence_id}/understanding`，读登录、写 CSRF，均按当前账号隔离。理解响应含素材级 `detected_count/sampled_count/shots[]` 与 `summary` 的四个镜头计数，预览的 `extra.understanding` 含 `shot_count/shot_analyzed_count/shot_used_count`。理解任务不修改剪辑文档，且不提供跳过授权执行剪辑的入口。

### 4.5 前端交互

- 「智能成片」组新增「引流剪辑」；点击后弹出五种策略菜单，选择后直接生成预览。
- 授权弹窗标题为「引流剪辑 · 需要你的授权」，正文包含策略名、逐镜 `截取/保留` 时长与理由，以及「策略原则」。
- 空素材、策略未选等错误在助手内显示明确文案，不写入时间线。
- 理由文字使用 12px、无透明度，浅暗主题均保持可读。

### 4.6 涉及文件

- 后端：`backend/app/director_assistant/protocol.py`、`editing.py`、`service.py`、`understanding.py`、`backend/app/video_analysis.py`、`backend/app/llm_client.py`、`backend/app/media_studio/routers/smart_edit_router.py`、`backend/tests/test_editing_assistant.py`、`backend/tests/test_media_understanding.py`、`backend/tests/test_video_analysis.py`。
- 前端：`frontend/src/director2/smart-edit/api.ts`、`frontend/src/director2/assistant/editing-tools.ts`、`editing-tools.test.ts`、`DirectorAssistant.tsx`、`assistant.css`。
- 文档与截图：本文件、助手 V2 说明、架构快照、扩展指南、README、流程快照；`docs/design-ref-director/61-smart-edit-hook-approval-light.png`、`62-smart-edit-hook-approval-dark.png`、`63-smart-edit-hook-result-light.png`、`64-smart-edit-hook-result-dark.png`、`65-smart-edit-hook-result-light-1920.png`。

## 5. 验证

- 后端：`python -X utf8 -m unittest backend.tests.test_video_analysis backend.tests.test_media_understanding backend.tests.test_editing_assistant backend.tests.test_director_assistant backend.tests.test_smart_edit -q`。新增镜头专项覆盖 `showinfo` 时间解析与 stderr 合并、内部镜头逐镜分析聚合、检测失败回退整段、每素材采样上限等距抽样、全时间线 40 镜上限；理解专项还覆盖逐镜成功与部分失败、空时间线不调模型、视觉模型不可用、成功复用与强制重跑、运行中重复启动 409、账号隔离、自由剪辑读取时间线素材、素材变化后旧证据失效、HTTP 路由登录/CSRF、超时运行记录恢复，以及 GLM 包裹在 `<|begin_of_box|>` 标记中的 JSON 解析。
- 前端：`pnpm --dir frontend build`（含 vitest、tsc、clean-dist、vite build）通过；`pnpm --dir frontend test` 为 55 个测试文件、294 项通过。新增 `editing-tools.test.ts` 覆盖六种工具与五种策略。`api.ts` 增加理解状态、逐镜项与 `EditingAction.understanding` 类型。
- Vite 开发页桌面实测（2026-10-21）：
  - 镜头边界检测：2 条时间线素材（6 秒红蓝绿三段、4 秒黄紫两段）由 FFmpeg 检测到 5 个内部镜头（3+2），采样分析 5/5；卡片显示「已从 2 条素材检测到 5 个镜头，采样分析 5/5 个」，展开后逐镜时间范围为 0–2、2–4、4–6 与 0–2、2–4 秒；浅暗截图归档为 `70`–`71`。
  - 「引流剪辑 → 3秒进冲突」授权弹窗显示「理解依据：镜头边界检测后采样的 5 个镜头关键帧描述，结合分镜对白与配音时长」，逐镜理由包含内部镜头聚合的「画面理解：…」；浅暗截图归档为 `72`–`73`。确认后时间线为 2 个片段、6.38 秒，刷新后仍保留。
  - 较早的素材级验收：真实配置 `zai-org/GLM-4.5V` 对 3 个时间线镜头完成 3/3 理解，素材级卡片与授权依据归档为 `66`–`69`。
  - 首轮真实调用暴露 GLM 返回带 `<|begin_of_box|>` 标记的 JSON 与非 JSON 错误；解析器改为提取首尾花括号，并对单镜增加 2 次尝试后，重跑成功。
  - 验证工程、账号、助手记录与云端临时视频在验收后按 ID 清理。
- 同一日较早的五策略验收仍有效：五策略菜单、`conflict_3s` 与 `trailer` 授权理由、确认后 8.75 秒时间线与刷新持久化；授权与结果截图归档为 `61`–`65`，工程与账号同样已清理。

## 6. 未实现与后续方向

持续开发计划、决策门与交接清单见 [智能剪辑助手开发计划](智能剪辑助手开发计划.md)。

需要真实媒体能力，不能靠文本规则伪造：

1. `understand_full` 的完整逐段理解：当前已做镜头边界检测并对采样镜头各取 2 帧，但缺全片语义分段、质量/废片识别与逐段叙事理解。
2. ASR 字幕转写：当前自动字幕仍以剧本对白为依据，音频不转写；「视频理解」也明确不处理声音。
3. 智能分镜、去废片、智能拆条：已有基础镜头边界检测，但缺语义分段、质量评分与自动拆条策略。
4. 一键调色、按轨导出：需要渲染管线和分轨封装。
5. 策略生成：WorkRally 由宿主结合完整理解结果生成；当前为确定性启发式 + 逐镜画面证据，未引入生成式剪辑策略。

因此本工作台现在的定位是“可解释的确定性剪辑助手，带用户显式触发的镜头级关键帧画面证据”；不宣称与 WorkRally 的 `understand_full` 等价，也不把画面理解自动当作全局授权。

## 7. 兼容与回滚

- 兼容：旧 `video_arrange` / `subtitle_arrange` / `dialogue_cut` / `quick_cut` / `highlight_cut` 请求不变；`strategy` 为可选字段，旧客户端无需修改；旧提案没有 `reason/strategy_title` 时前端按原样显示。视频理解为独立可选能力，旧客户端不调用即保持原行为。
- 无 SQL 迁移、无新表、无 ComfyUI/FFmpeg 导出任务；历史 pending 提案不会自动执行。视频理解会下载时间线已使用的素材，调用本机 FFmpeg/ffprobe 做镜头检测与抽帧，并调用 VLM；需在管理设置中配置可用视觉模型，服务器需有 FFmpeg；未配置时开始接口返回 failed 与明确文案，不影响手动剪辑。
- 回滚：撤销镜头检测（`video_analysis.detect_scenes`）、逐镜采样、理解路由、`llm_client.py` 的 JSON 容错、前端卡片与 `api.ts` 字段，并撤销 `editing.py` 对 understanding 的接线；保留 `ai_assistant_records` 中的历史理解记录和剪辑文档（回滚后不再读取）。无需删除数据或切换供应商。
