# Director 返修闭环实施记录

日期：2026-09-23。对应 [根因与整改方案](Director出片方案根因与整改方案.md) 的第一阶段，保留开发前已有改动。

## 本次实现

- 生成前检查确定性冲突：固定时长与对白、没有动作/对白、单元容量、明确独立场景仅一个事实。未知场景不臆断，不为凑段数增加剧情。
- 审稿问题按段落与类别形成稳定 ID，区分阻断/审美建议、局部可修/需要调整规划。用户修改意见跨版本保存。
- 服务端读取已保存方案或预览作为基础，锁定事实、对白、时长、起止状态、公共设定及未选段落，仅接收限定的摄影、表演和正文补丁。
- 每轮补丁重新编译、校验事实与结构、全局审稿。阻断集合未严格减少或出现新阻断时放弃候选，最多两轮。显示停止原因与差异。
- 已完成 Part、最佳草稿和待审候选保存检查点；来源变化和并发保存冲突拒绝采纳。新草稿不自动覆盖当前方案。
- 新质量版本的正文未复验或仍有阻断时禁止出片；可保存待修订稿。旧方案、工作流、ComfyUI 配置和媒体保持兼容。

## 关键文件

后端：`director_plan_quality.py`、`director_story_design.py`、`prompt_expansion_service.py`、`episode_video_service.py`、`project_router.py`。前端：`api.ts`、`director-plan-quality.ts`、`PromptAuthoringPanel.tsx`、`EpisodeWorkshopPane.tsx`（整集出片入口同步拦截待复验方案）。回归：`media_studio_test_director_quality.py`、既有提示词/导演设计测试、`director-plan-quality.test.ts`。

API：`POST /api/projects/{project_id}/episodes/{episode_id}/prompt-revisions`。新增质量及修订字段写入已有 JSON，不新增数据库表。

## 验证

2026-09-23 验证完成：媒体后端全量 275 项通过；质量服务与既有导演/时间线/AI 生成组合回归 217 项通过（与前者有重叠）；前端 59 个测试文件、295 项通过，TypeScript 检查和生产构建成功。构建仍有既有的大 chunk 提示；`git diff --check` 通过。

```text
python -X utf8 -m unittest discover -s backend/tests -p "media_studio_test_*.py"
python -X utf8 -m unittest backend.tests.media_studio_test_director_quality backend.tests.test_director backend.tests.test_timeline_rendering backend.tests.test_director2_ai_generation
pnpm --dir frontend build
```

桌面验证使用 5173 的「验收样例：旧站来信」第 99 集，1440×1000，检查返修入口、段落多选、修改意见、空意见拦截和取消。浅色/暗色均无文字遮挡或弹窗溢出；检查后恢复浅色及默认视口。未提交真实模型或视频任务，未改写样例方案。新增阻断、差异、检查点与并发保护由自动化测试覆盖，本次未以真实模型任务逐态复现。

参考截图：[浅色返修弹窗](design-ref-director/2026-09-23-director-revision-light.png)、[暗色返修弹窗](design-ref-director/2026-09-23-director-revision-dark.png)。截图保存在已有忽略的设计参考目录，不进入版本控制。

## 验收边界

本阶段改进的是可行性检查和可追溯返修机制，不承诺模型一次满足所有创作要求。当前事实抽取仍以原有句子边界为主，持物/站位等状态仍保留已有结构；完整语义事件抽取和状态字段化属于后续内核改造。涉及剧情、对白、时长或起止状态的变更仍需用户先调整分镜，不能靠改正文绕过。

自动审稿存在漏判可能，空问题列表不等于成片验证。真实模型新旧同稿盲评与远端视频遵循度对照需要独立验收，不能用单元测试或可播放视频替代。

## 回滚

只撤回本次新增质量服务及对应接入、UI、测试和文档补丁。无需删表、清库或删除媒体；JSON 中的质量与修订记录可保留。不要整文件回滚覆盖开发前已有的未提交功能改动。
