# 动作迁移工作台验收（2026-11-02）

## 范围

- 只验证桌面 1536×864，不进行移动端适配或验收。
- 真实页面为 Vite 5173；自动化将 API 请求送入相同 FastAPI 代码的临时 SQLite 环境。登录/CSRF、媒体上传解析、任务存储、素材回读不是静态模拟；供应商展示信息为受控状态数据。
- Chromium 不提供原生文件 multipart 请求体，测试桥接读取实际 FormData 的字段、文件类型和完整字节，由 HTTPX 送入真实 multipart 解析器，并断言与原文件一致。
- 真实出片开关与普通界面测试分离；只有显式设置 `ZLY_MOTION_RENDER_E2E=1` 才调用一次远端 ComfyUI。地址从当前运行工作台的 `/api/health` 读取，不切换配置，不向生产 MySQL 创建账号或任务。

## 已覆盖

- 角色图 / 动作视频独立选择、视频本地预览及真实时长读取。
- 留空提示词、注册表 primary/advanced 层级；采样步数不在创建栏暴露，质量预设映射为内部 steps。
- 暗色和浅色语义表面、标签、数字输入、删除按钮及无横向溢出。
- 游客先选素材及参数，真实登录后草稿保留，不自动提交；手动生成仅创建一个任务。
- 服务端类型颠倒、缺视频、损坏视频、片长不足和超大文件校验，失败清理已保存部分。
- seed/尺寸/帧数写入生效快照，固定 seed 幂等，随机请求再次生成会产生新 seed。
- 任务参考视频正确返回 video/mp4；重新编辑同时还原两份素材。
- FFmpeg 实际集成测试：30fps / 6 秒源视频只输出 24fps / 124 帧动作窗口。

## 命令与证据

- `pnpm --dir frontend build`：81 个文件、581 项测试、TypeScript 与 Vite 构建通过；仅保留既有大包体积警告。
- 后端专项：30 项通过；全量后端结果及真实 GPU 验收完成后记录于本节。
- 默认跳过的桌面测试：`python -X utf8 -m unittest backend.tests.test_motion_transfer_browser -q`，需提供 `ZLY_MOTION_BROWSER_E2E=1`、`ZLY_MOTION_TEST_IMAGE`、`ZLY_MOTION_TEST_VIDEO`。
- 过程输出全部在已忽略的 `test-results/motion-transfer/`，数据库与预处理目录由测试自动删除；保留用于交付的样片及验收清单，不提交临时输入或日志。
- 封面、角色图和动作视频复用此前验收素材，本轮没有新增生图请求。Codex 的 `openai-api-image` 已复制到 OpenCode 全局 skills，使用原 Windows 凭据引用，没有复制或输出密钥。

## 回滚

仅撤回本次链路增量、双槽 UI、工具启动路径与新测试，恢复工具 coming_soon 状态后构建。当前 ComfyUI、既有图节点、生产数据库与历史素材不需要回滚。
