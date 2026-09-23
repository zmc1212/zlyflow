# Hypit 复刻排查与换脸接入（2026-09-23）

## 用户要求与根因

用户要求保留参考视频的镜头、动作、声音、字幕和背景，仅替换人物面部。现有 `hypit_replication` 是结构改编：WhisperX 转写、Coding Agent 编写 SVML、H3 重新生成画面、Hypit 合成。它不具备原片逐帧换脸能力，调整提示词或画质无法改变这一点。

现有「沙丽丽换人复刻」工程将 H3 生成画面的音轨丢弃，并以原视频建立声音和语义时间轴；这是重新生成表演再配原声，存在动作、场景与口型不匹配的风险。参考片 11.285 秒，转写记录的 55 个词集中在 0.171–3.280 秒，时间对齐亦需核对。本轮未重写该工程、未替换其媒体、未重新提交生成。

## 已完成的可靠性修复

- `DirectorHypitStudio.tsx`：明确显示「Hypit 结构改编 · 非原片换脸」；需求保存串行化，任务启动、上传和打开工程前等待保存，失败不继续；上传期间锁住创作操作；失败时标记正在展示上次成功成片。
- `director_hypit.py` / `director_operations.py`：多个 Run 时仅自动选择唯一 `final.video` Run；从 XML 的 target 读取导出目标，避免取到注释、素材或旧 Run。编译必须有本次 Build ID，并先导出到独立临时文件，检查非空后替换成片；失败保留旧片，新 URL 带 Build ID 防缓存。
- 编译时从工作台 `ComfyProviderService.current_url()` 读取生效地址，覆盖本次 runtime overlay 的 H3 地址；不修改全局 runtime、不切换供应商配置。
- 打开工程、转写、编译时将需求写入 `notes/WORKBENCH_BRIEF.md`，保留 Agent 已有的 Analysis/Brief/Treatment。同步需求不等于自动改写 SVML。
- 未改变数据库、API 路由、既有工作流节点 ID 或模型路径。原有 payload 与工程兼容；存在多个不明确 Run 的工程现在会报错，需将归档版本移入子目录。

## 原片换脸仍待接入

读取实际供应商地址后，远端 `http://192.168.10.54:8188/system_stats` 返回 200。远端为 Windows、ComfyUI 0.30.0、Python 3.10.11。检查 1716 个已注册节点，无 ReActor/FaceFusion 等换脸节点；有 VideoHelperSuite 和人脸检测/遮罩节点，但这些不能替代身份换脸模型。

远端页面未显示 Manager，`/manager/version` 返回 404，启动参数没有 Manager 标志。用户允许通过 Manager 安装，并确认能直接操作远端电脑；用户提供的启动脚本使用 `python310/python.exe` 与 `bootstrap/launch_comfyui.py`。已提供 `scripts/enable-remote-comfy-manager.bat`，需复制到远端原启动脚本旁执行，检查目录及端口后用既有 Python 安装 `Comfyui/manager_requirements.txt` 并加 `--enable-manager` 启动；不改原启动脚本、不结束运行中任务。等待用户在远端执行。本轮未安装换脸节点、模型或新 ComfyUI，未重启远端。

后续换脸链路应独立于 H3 结构改编：原片 + 人脸照片 → 原片逐帧检测/跟踪与面部替换 → 保留帧率、尺寸、时序与原音频 → 同时间点对比验收。接入必须以安装后远端 `/object_info` 的真实 schema 和模型列表为准；多人镜头应明确目标人物，不默认替换所有人。

参考：[ComfyUI 官方 Manager 安装](https://github.com/Comfy-Org/docs/blob/main/zh/manager/install.mdx)、[ReActor 官方仓库](https://github.com/Gourieff/ComfyUI-ReActor)。

## 验证与回滚

- `python -m unittest backend.tests.test_director_hypit -q`：17 个测试通过，覆盖目标选择、需求交接、远端配置和新导出缺失/空文件/成功分支。
- 新增回归另归档到可版本控制的 `backend/tests/hypit_test_regressions.py`（原 `test_director_hypit.py` 被项目既有忽略规则排除）；运行 `python -m unittest backend.tests.hypit_test_regressions -q`。Hypit 工程 CRUD/API 回归另通过 1 项。
- `pnpm --dir frontend build`：59 个前端测试文件、295 个测试通过，TypeScript 与 Vite 构建完成；保留已有 bundle 体积提示。
- 桌面浏览器以 5173 验证，参考截图见导演台流程文档。未提交新的生成任务，未完成换脸出片验收。
- 回滚仅撤销本轮列出的改动及文档，保留用户原有未提交修改和全部工程/媒体；无数据迁移回滚。
