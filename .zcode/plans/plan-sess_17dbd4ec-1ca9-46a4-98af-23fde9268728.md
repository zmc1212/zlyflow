# 「参考片转绘复刻台」实施计划（已融合 AniShort 文章借鉴项）

## 定位

导演台新增第三种工程类型 `shot_replication`（复刻台）：上传参考片（短视频/电影片段）→ 智能拉片（分镜反推提示词 + 深度视频提取 + 主体清单）→ 人工确认与微调 → 本地 Wan2.1 VACE 深度控制批量转绘 → 原片/成片并排对比 → 导出。产品叙事对标 AniShort："保留原片叙事骨架与运镜，替换画面主体/风格"；差异化是本地、零算力费、可换引擎、数据不出本机。台词 ASR/翻译/TTS 重配明确放二期。

## 已验证的技术前提

- 整合包 ComfyUI 含 Wan2.1 VACE 1.3B 全套模型（`vace-native-checkpoint/`：扩散模型+VAE+umt5-xxl）、核心 DA3 深度节点（comfy_extras/nodes_depth_anything_3.py）、VHS、`toonflow_vace_multi_reference` 自定义节点（原生支持 `control_video` 输入，即深度视频）。
- 项目根 `local_video_studio.py:240` 的 `build_vace_multi_reference_workflow` 是完整可抄的图模板（UNETLoader→ModelSamplingSD3 shift16→WanVaceMultiReference→KSampler uni_pc/simple cfg5→SaveVideo 定死输出节点）。
- 复用设施：operations+SSE（`director_operations.py`/`director_stream.py`）、jobs 串行队列、payload kind 判别、资产库 `director_library_assets`、GRS 图像生成、Qiniu 交付、MuxService 拼接、前端流式面板组件模式。

## 阶段 0 — 预研验证（半天，先行）

1. 核对 VACE 模型加载：diffusers 格式 checkpoint 能否被 `UNETLoader` 直接加载，否则按规则经 `extra_model_paths.yaml`/ComfyUI 目录归位（禁止下到工作台目录）；
2. 预取 Depth Anything 3 模型，手跑整合包"Video Depth Estimation"蓝图验证视频深度输出；
3. 验证 mp4 经 ComfyUI `/upload/image` 进入 `input/` 供 VHS LoadVideo 读取；
4. 读 `toonflow_vace_multi_reference` 节点源码，敲定 control_video 帧率/分辨率/帧数（4n+1）对齐策略。
产出：可行的图结构记录 + 模型归位结论。不通则回调方案（如 1.3B 换加载方式）。

## 阶段 1 — 视频基础设施

- 视频上传端点 `POST /api/director/replications/{project_id}/source-video`（multipart，白名单 mp4/mov/webm，上限约 2GB，流式落盘 `data/uploads/{user}/{project}/source/`，仿 `save_recipe_shot_frame` 原子写入）；
- 新 `video_analysis.py` ffmpeg 工具模块（复用 `director_export.find_ffmpeg`）：`detect_scenes()`（智能分镜）、`fixed_segments()`（固定分段）、`extract_keyframes()`、`cut_segment()`、`probe()`；
- 深度提取工作流 builder + internal 注册：全片一次 DA3 深度提取 → ffmpeg 按镜头切段，输出经现有 `MediaOutput` 通道记录路径。

## 阶段 2 — 拉片分析管线（借鉴项：标准化拉片报告 + 双模式分镜）

- 新 operation kind `analyze_reference_video`（`models.py` + `DirectorOperationService` 分发），流程：分镜切分（智能/固定双模式）→ 逐镜关键帧 → 视觉 LLM 反推 → 组装 payload；
- 每镜产出：起止时间/时长、关键帧、结构化提示词（H3 语法，仿 `llm_minimax_skills.py` 新增 skill）、**主体清单**（人物/场景/道具 + 参考帧 + 出镜区间——同一视觉调用顺带产出）、深度视频段路径；
- 新 payload kind `shot_replication` 独立 normalize（新 `director_replication.py`，不动 `director_recipe.py`）：`shots[]`（id/shotNumber/timeStart/timeEnd/keyframeUrl/depthVideoUrl/promptText/compiledPrompt/subjectBindings/status/jobId/takes）+ `subjects[]`；
- 视觉模型不可用时降级：分析只出分段+关键帧，提示词手动填写，UI 给配置指引（`/api/llm/status` 检测）；
- 进度经 `AgentStreamTracker` 逐镜流式推送 SSE。

## 阶段 3 — 转绘引擎接入（借鉴项：同源多引擎）

- `JobMode` 新增 `vace_depth_v2v`；`workflow_registry.py` 注册 `wan21-vace-depth-v2v`（`WorkflowDefinition` 增 `control_video` 能力位与校验）；新 builder `wan_vace_depth_workflow.py`（抄遗留模板，SaveVideo 输出节点定死）；`ComfyService.run` 加分发分支（`completed_outputs` 遗留 VACE 分支复用）；
- 引擎双路：VACE 深度复刻（运镜构图锁定）与 H3 r2v（原片首帧+参考图重绘），同一镜头可选引擎或双引擎对比，take 记录 `workflowId/videoWorkflowFamily`；
- 参数产品化：`primary` ≤4 = 深度控制强度、保留原片首帧开关、生成引擎、输出数量；`advanced` ≤4 = 种子、步数、创意偏移；其余（加载器、shift、采样器、帧对齐）`internal` 托管；
- 每镜走现有 jobs 串行队列；**局部修复**：单镜重跑/换 take/失败重试，沿用 batch 的重试端点模式。

## 阶段 4 — 主体库与主体映射（借鉴项：跨镜头一致性）

- 分析产出的主体入库复用 `director_library_assets`（CRUD+图片上传已有）；
- 复刻 payload 加 `subjectBindings`（镜头→主体映射，仿 recipe 的 characterBindings）；VACE 参考图输入承载一致性，提示词编译时注入主体描述（复用 `director_compiler.py` 的打包模式）；
- 换主体：GRS 图像生成按语义预设重绘参考图（市场/风格本地化为语义选项，不暴露技术参数），生成结果回填资产库；
- 主体面板支持筛选（删除低价值主体）、换参考帧（选择五官清晰/光线协调的帧）。

## 阶段 5 — 前端复刻台

- `director-api.ts` 加 `isReplicationPayload` 守卫与上传/分析/复刻 API；`DirectorStudioModule` 加 `/director/replication/:id` 路由；`DirectorHome` 加第三张创建卡；
- 新 `DirectorReplicationStudio.tsx`：上传区（antd Upload.Dragger）→ 三参数极简入口（风格预设/画幅/生成引擎）→ 分析直播（复用 `DirectorTaskRows`+SSE 模式）→ 拉片报告（分镜列表：原片段播放/深度预览/可编辑提示词/**分镜起止手动微调**）→ 主体面板 → 批量转绘 → 原片与成片并排对比 → 单镜重试 → MuxService 拼接导出；
- 文案进 `action-copy.ts`，样式用 `--studio-*` 令牌进 `guided-flow.css`，自动兼容双主题；Alert/弹层跟随主题。

## 阶段 6 — 文档与回归（AGENTS.md 强制项）

- 更新 `docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`（末尾带日期变更章节：原因/受影响文件/兼容性/验证命令/回滚方式）、`README.md`；
- 后端 unittest（临时 SQLite）：registry 参数层级与校验、builder 图快照、分镜切分、operation 流转、主体映射序列化；
- 前端构建 + 桌面/移动端检查。

## 风险与边界

- 反推质量依赖管理员配置的视觉模型（vision 能力），入口前检测并给指引，不可用时允许纯手动模式；
- 1.3B 复刻质量低于 H3 属预期；后续显存允许换 14B 或加云端引擎 family（registry 已按 family 预留）；
- 版权：UI 注明"分镜学习与参考复刻"定位，发布合规责任在用户；
- 大文件上传配额与深度/片段临时文件定期清理；
- 单实例 ComfyUI：所有转绘与深度提取走串行队列，分析（LLM）不占 ComfyUI。

## 验证命令

后端：`python -m pytest backend/tests -x -q`；前端：`cd frontend && npm run build`；阶段 0 预研以真实工作台页面 + ComfyUI 实跑为准。