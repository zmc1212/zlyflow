# Director 分组与 MiniMax H3 镜头提示词重构计划

## 当前执行计划：2026-09-25

用户补充：保留原 UI。人物、场景、道具沿用照片墙；工坊沿用分集卡片网格；资产库和内容库尽量恢复既有布局；更多视频设置恢复原浮层。流程调整不得扩展成整站界面重做。

本计划已由 [导演台统一工坊 v7](导演台统一工坊-v7.md) 替代：规划集中在工坊，仅生成镜头结构和分组；H3 只在逐镜素材组写入；取消制作方案 Tab、独立 H3 工作区和全局 AI／手动模式；视频消费保存快照，采用关系统一。完整职责、数据合同、接口、历史保护、实施与验收见该文档。

## 以下为原设计存档（不再执行）

**日期：** 2026-09-24  
**状态：** 2026-09-24 界面入口与单镜编辑已落地；v6 读取兼容已接入，新方案仍默认写入 v5，完整切换与远端出片验收待完成  
**适用范围：** 导演台剧集工坊、制作方案、镜头提示词、MiniMax H3 Director 出片链路

## 1. 目标

建立一条清晰的生成链路：

```text
原始剧本 / Beat
    ↓
按场景和镜头数量分组
    ↓
Director 扩写公共设定、镜头意图、动作、表演和声景
    ↓
MINIMAXH3格式动作语气台词细化SKILL 生成最终提示词
    ↓
生成前检查事实、对白、时长、参考图和时间线
    ↓
提交 ComfyUI
```

最终视频提示词以 H3 技能格式为准。Director 负责创作扩写、分组和参数组织；Director 结构规则不直接改写 H3 正文。

## 2. 已确认的设计原则

### 2.1 分组功能保留

分组用于两个或三个镜头共享：

- `subject_definitions`
- 声音设定
- 场景、光线和服装一致性
- 参考图槽位
- 组内帧数和连续性参数

分组是生成和素材管理单元，不替代镜头级提示词。

### 2.2 Director 扩写保留

保留 Director 对以下内容的扩写：

- `dramatic_intent`
- `visual_strategy`
- 公共人物和场景设定
- 镜头景别和运镜
- 人物动作与表演
- 声景、环境和情绪

### 2.3 H3 技能负责最终正文

最终镜头提示词必须使用 H3 原生结构：

- `subject_definitions`
- `声音设定`
- `detailed_description`
- `[Shot N｜0–时长秒]`
- `[主体]`、`[动作]`、`[镜头]`、`[音效]`、`[约束]`
- `<d>[中文台词]</d>`
- `(S1)`、`(S2)` 等稳定说话人标记

每个独立 segment 内部时间从 `0秒` 开始。组内累计时间只存在于技术时间线，不写入镜头提示词正文。

## 3. Director 规则的调整

### 3.1 保留为生成前硬检查

以下问题影响任务参数或事实完整性，可以阻断提交：

- 动作事实缺失或重复
- 对白事实缺失或重复
- `dialogue_owner` 无法确定
- 参考图编号、数量或工作流不兼容
- 总帧数超出工作流容量
- segment 时长无效
- segment 内时间码不从 `0秒` 开始或出现重叠
- 台词没有基本安全尾部
- 组边界和 `continuityFromPrev` 参数不一致

### 3.2 改为警告，不阻断 H3 出片

- `start_state` 和 `handoff_state` 文字不完全相同
- 连续性描述和自然语言扩写存在措辞差异
- `continuity_from_prev=false` 与正文中出现连续动作描述
- 可能重复动作或提前出现下一镜动作
- 模型没有逐字复述源事实

这些信息继续显示在“生成前检查”中，但不再要求模型输出固定状态句，也不再因文字差异阻止保存和生成。

### 3.3 不再写入最终 H3 正文的内容

- `required_events`
- `dialogue_owner`
- `start_state` / `handoff_state` 元数据
- “无硬切。紧接上一段。”固定前缀
- Director 六段式结构标签
- 仅用于程序审查的事实 ID

事实 ID 和状态信息保留在内部数据中，用于检查和时间线编译。

## 4. 新的数据组织

建议在现有 `director_plan` 下引入新版本结构，例如 `schema_version: 6`：

```text
director_plan
├── groups
│   ├── id
│   ├── source_beat_ids
│   ├── common_prompt
│   ├── reference_slots
│   └── shots
│       ├── beat_id
│       ├── h3_prompt
│       ├── duration_seconds
│       ├── continuity_from_prev
│       └── video_takes
├── checks
├── revision
└── status
```

提交 ComfyUI 时：

```text
global_prompt = group.common_prompt
segment.prompt = shot.h3_prompt
```

公共设定只保存一次；镜头提示词单独保存、单独编辑、单独生成。

## 5. 最终界面设计

### 5.1 制作方案 Tab：管理分组

保留当前“制作方案”和“分组设置”，用于：

- 每组最多镜头数
- 组预览
- 公共主体定义
- 组参考图
- 组内时长和连续性
- 生成本组
- 组状态和失败重试

制作方案只展示每个镜头的摘要和跳转入口，不承担所有镜头提示词的主要编辑工作。

### 5.2 镜头检视器的“提示词与视频” Tab：单镜头工作区

恢复之前按镜头查看提示词的体验。选择镜头 1，只显示镜头 1；选择镜头 2，只显示镜头 2。

建议结构：

```text
镜头 1 · 提示词与视频

所属镜头组：第 1 组（镜头 1–2）
已继承组公共主体定义

本镜最终 H3 提示词
[可编辑的 H3 提示词正文]

[复制本镜完整提示词] [重新生成本镜提示词] [生成本镜视频]

参考素材组
视频 Take
```

公共主体定义默认折叠显示；复制完整提示词时再合并公共部分和镜头部分。

### 5.3 组件调整

- `ShotPromptSummary` 改为可编辑的 `ShotPromptPanel`
- Director 分组详情保留在制作方案 Tab
- 镜头检视器显示最终 `h3_prompt`，不再只显示 Director 摘要
- “AI 优化本集提示词”改为“按 H3 技能生成提示词”
- “生成本组”和“生成本镜视频”并列提供
- 旧的 Director 结构字段放入折叠的高级信息中

## 6. 主要代码改动

### 后端

- [`prompt_expansion_service.py`](../backend/app/media_studio/services/prompt_expansion_service.py)
  - 保留分组和扩写任务。
  - 通过 H3 编译器生成每个镜头的最终正文。
  - 移除固定连续性前缀和状态文本注入。

- [`director_story_design.py`](../backend/app/media_studio/services/director_story_design.py)
  - 保留公共设定、镜头意图和分组设计。
  - 降低模型必须输出的状态字段数量。

- [`director_reliable.py`](../backend/app/media_studio/services/director_reliable.py)
  - 保留分组、帧数、参考图和工作流路由。
  - 删除状态文本逐字继承作为阻断条件。

- [`director_plan_quality.py`](../backend/app/media_studio/services/director_plan_quality.py)
  - 将状态、连续性和重复动作问题改为 warning。
  - 保留事实覆盖、对白唯一归属、帧数和参考图硬检查。

- [`h3_prompt_builder.py`](../backend/app/media_studio/services/h3_prompt_builder.py)
  - 增加“组公共设定 + 镜头 H3 正文”的编译入口。
  - 统一对白、说话人、时间码和安全尾部处理。

- [`episode_video_service.py`](../backend/app/media_studio/services/episode_video_service.py)
  - 视频提交只消费最终 `h3_prompt`。
  - `continuityFromPrev`、帧数和组边界只作为时间线参数。

### 前端

- [`EpisodeWorkshopPane.tsx`](../frontend/src/director2/panes/EpisodeWorkshopPane.tsx)
  - 恢复镜头检视器中的单镜头提示词编辑。

- [`PromptAuthoringPanel.tsx`](../frontend/src/director2/panes/PromptAuthoringPanel.tsx)
  - 分离“制作方案分组视图”和“单镜头 H3 提示词视图”。

- [`ProductionPanes.tsx`](../frontend/src/director2/panes/ProductionPanes.tsx)
  - 在素材组中显示当前镜头的提示词状态、参考素材和 Take。

- [`api.ts`](../frontend/src/director2/api.ts)
  - 增加组公共提示词、镜头 H3 提示词、来源和状态字段。

## 7. 实施阶段

### 阶段一：提示词合同

- 定义 `schema_version: 6`。
- 确定 `common_prompt` 和 `shot.h3_prompt` 的保存位置。
- 旧 v4/v5 方案继续只读。

### 阶段二：H3 编译链路

- Director 扩写只产出创意素材和公共设定。
- H3 技能生成镜头最终提示词。
- 视频提交改读新字段。

### 阶段三：检查器改造

- 保留参数和事实硬检查。
- 将状态文本、重复动作和连续性措辞改成警告。
- 增加对白安全尾部检查。

### 阶段四：镜头级界面恢复

- 恢复镜头检视器的“提示词与视频”功能。
- 制作方案只负责分组管理。
- 支持单镜头重写、单镜头出片和复制完整提示词。

### 阶段五：验证和切换

- 使用第 4 集验证 2 镜头组、3 镜头组、对白镜头、硬切和连续镜头。
- 验证单镜头编辑不会破坏组公共设定。
- 新任务默认使用新链路。
- 历史 v4/v5 方案和旧成片继续可读，不迁移已有媒体。

## 8. 验收标准

- 选择任一镜头，可以直接看到该镜头最终 H3 提示词。
- 镜头 1、2 共用主体定义，但提示词正文可以分别编辑。
- 生成本组和生成本镜都能使用同一套参考图和公共设定。
- 每个 segment 的提示词时间从 `0秒` 开始。
- 台词结束后有安全尾部，避免最后几个字被截断。
- 状态措辞差异不会再造成截图中的大面积阻断提示。
- ComfyUI 收到的 `global_prompt` 与 segment H3 提示词职责清晰。
- 旧历史任务、视频和方案仍可查看。
