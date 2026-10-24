# 导演台细节校准验收 · 2026-10-24

**结论：本轮通过。** 沿用原 `home-design.png` / `project-design.png`，修复上一轮复核的 F1–F3。原设计图片保持不变；真实 Vite 5173 页面自动截图、内部控件测量、操作和人工局部复核均通过。

## 三处问题的修正

坐标与尺寸为 `[x,y,width,height]` CSS px，视口 1505×1045、DPR 1。设计蓝色实填边界与实际 DOM 外框可能有约 1px 差异；搜索设计边框为人工标注，精度约 ±2px。

| 对象 | 原设计 | 修正前 | 当前实际 |
| --- | --- | --- | --- |
| 首页主按钮 | `[188,381,212,52]` | `[177.5,367,154,44]` | `[188.5,381,212,52]` |
| 内容库导入主按钮 | `[655,597,174,47]` | `[715.5,571,126,42]` | `[666.5,597,174,48]` |
| 首页搜索框 | `[732,639,200,35]` | `[809.5,637,190,34]` | `[734.4,636,200,36]` |

主入口同步校准 70px 图标、26px 标题、30px 步骤圆点、18px 按钮字、步骤间距和电影格比例。次入口图标由 48px 调整为 62px；诊断标题与说明之间恢复分隔线。最近工程的标题、卡片文字、30px 操作按钮与蓝色选中筛选项一起调整。

内容库按字体和内容顺序重建间距：34px 页面标题；主面板 y=232；100px 图标 y=343；24px 空态标题 y=475；17px 说明 y=521；48px 按钮 y=597；14px 文件格式 y=689。项目条配方标签、208×58px 模式切换、40px 主题按钮、22px 项目标题和五项 50px 导航一并校准；内容库导航改用文档图标。

以下三联图依次为原设计、修正前、当前界面的同坐标裁图，没有缩放：

- [首页主按钮](home-cta-comparison.png)
- [内容库按钮组](project-actions-comparison.png)
- [首页搜索与筛选](home-toolbar-comparison.png)

## 截图与自动验证

| 页面 | 1505×1045 | 1440×1000 | 1920×1080 |
| --- | --- | --- | --- |
| 首页 | [浅色](home-light-1505.png) / [暗色](home-dark-1505.png) | [浅色](home-light-1440.png) / [暗色](home-dark-1440.png) | [浅色](home-light-1920.png) / [暗色](home-dark-1920.png) |
| 项目内容库 | [浅色](project-light-1505.png) / [暗色](project-dark-1505.png) | [浅色](project-light-1440.png) / [暗色](project-dark-1440.png) | [浅色](project-light-1920.png) / [暗色](project-dark-1920.png) |

本轮 **198 项检查通过，0 项失败**，没有累加旧 106 项。明细见 [verification.json](verification.json)：

- 12 张主页面截图各核对身份、CSS 视口与实际 PNG 尺寸、DPR、资源就绪、横向溢出和关键控件边界，共 60 项。
- 原外框与新增按钮、搜索框、图标、菜单、模式切换共 18 个几何锚点，继续使用最大绝对偏差 ≤20px。F1–F3 另加三项按坐标轴限制的检查，按钮宽高、纵向位置与搜索位置单独判断。
- 60 项真实操作：搜索/清空、五类筛选、查看更多/收起、新建配方弹层及异步选项、配方下拉、基本信息与空名称校验、导入/规范弹层、主题刷新持久化、菜单 Enter 导航、助手开关、删除确认取消、智能剪辑停靠。只在临时 QA 工程操作，没有提交生成、视频理解或音频转写任务。
- 56 项可见边界与文字对比度检查，抽检正文最低 4.586:1。CDP 确认实际中文字体为 Microsoft YaHei，空态标题使用 MicrosoftYaHei-Bold。
- 浏览器运行异常检查 1 项，`pageerror` 为 0；Ant Design 既有旧属性弃用信息与运行异常分开记录。

证据：[采集元数据](capture.json)、[真实操作](interactions.json)、[对比度与实际字体](quality.json)、[首页几何](home-geometry.md)、[项目几何](project-geometry.md)、[首页原始校准](home-verification.json)、[项目原始校准](project-verification.json)。校准工具通过只证明身份、条件和测量完整；本报告另加入内部几何门槛、真实操作与画面复核。

## 差异与范围

首页 11 个锚点的最大绝对偏差为 **3.75px**；项目 7 个锚点最大为 **16.5px**。内容库按钮宽度与纵向位置已校准，内容组保持面板数学居中，因此主按钮 x 比生图参考右 11.5px，图标右 16.5px。全局导航继续保留 76px，参考生图约 88px，项目条有已声明的 12px 差异。系统字体字形、抗锯齿、语义主题色与真实工程数据不要求逐像素完全相同。未将像素差异换算为「还原度百分比」。

智能剪辑在 1440×1000 两种主题下重验：工程图标轨 62px；素材库标题单行；引用本机/上传操作完整；项目条没有碰撞。见[浅色](light-edit.png)、[暗色](dark-edit.png)与[模拟长项目名](simulated-long-title.png)。对话创作室和助手的官方 `--director-*` 样式未修改。本轮没有移动端或真实出片验证。

## 代码与清理

- `pnpm --dir frontend build`：**60 个文件、397 项测试**、TypeScript 和规定的 clean-dist / Vite 构建通过。[日志](frontend-build.txt)
- `python -X utf8 -m unittest backend.tests.test_director_project_info backend.tests.test_director2_ai_generation -q`：**51 项通过**。[日志](backend-tests.txt)
- 直接修改四个 UI 文件，指纹见 [source-sha256.json](source-sha256.json)。没有新增依赖、API、路由、数据库或业务状态。
- 临时 QA 工程删除后 GET 为 404，首页原有首项恢复；临时员工账号与会话已删除。[清理记录](cleanup.json)
- 初轮自动化出现 Ant Design 两字按钮空格、查看更多带箭头、异步配方尚未到达等定位/等待失败；修正脚本后完整重跑，最终 60 项操作全通过。一次项目校准因 URL 占位值被拒绝，已在真实 QA URL 上重建测量轮次并重新采集。Windows 子进程编码设为 UTF-8 后重新运行校准。失败记录保留在忽略目录 `test-results/director-ui-details-20261024/`，没有作为通过证据。

参考设计、旧复核结论和本轮证据均保留。回滚仅撤回 `director-home.css`、`project-detail.css`、`panes/content-library.css`、`Director2ProjectDetail.tsx` 的本轮样式/图标增量后构建，保留用户原有修改与历史数据。
