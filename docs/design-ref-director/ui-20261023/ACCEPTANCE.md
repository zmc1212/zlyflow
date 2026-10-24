# 导演台 UI 验收

**当前结论：细节校准后通过。** 2026-10-24 已修复首页主按钮、内容库按钮组与搜索工具栏三处差异，原设计图不变。本轮 12 张桌面浅暗截图、内部控件测量与真实操作共 198 项检查通过；397 项前端测试、类型检查、构建与 51 项相关后端测试通过。完整证据及保留差异见[本轮验收报告](details-20261024/REPORT.md)。

当前界面：[首页浅色](details-20261024/home-light-1505.png) / [暗色](details-20261024/home-dark-1505.png)，[内容库浅色](details-20261024/project-light-1505.png) / [暗色](details-20261024/project-dark-1505.png)。首页主按钮 212×52px，内容库主按钮 174×48px、y=597，首页搜索宽 200px、x≈734。全局 76px 导航和内容组数学居中的已声明差异保留；不声称像素完全相同。

以下是首轮历史记录，以本轮报告为当前结论。原先外框最大 12px 不能独立证明内部控件已还原；[当时的未通过复核](recheck-20261024/RECHECK.md)继续保留，三项问题在本轮关闭。

## 首轮设计与真实界面（历史）

| 页面 | 设计图 | 实际浅色 | 实际暗色 |
| --- | --- | --- | --- |
| 导演台首页 | [设计](home-design.png) | [浅色](home-actual-light.png) | [暗色](home-actual-dark.png) |
| 项目内容库 | [设计](project-design.png) | [浅色](project-actual-light.png) | [暗色](project-actual-dark.png) |

设计对照采用相同 1505×1045 CSS 视口、DPR 1；未拉伸截图，页面身份、字体和图片就绪检查均通过。

| 测量对象 | 最大绝对外框偏差 | 预设上限 | 结果 |
| --- | --- | --- | --- |
| 首页七个关键区域 | 8.5 CSS px | 20 CSS px | 通过 |
| 内容库主面板 | 6 CSS px | 20 CSS px | 通过 |
| 项目顶栏 | 12 CSS px | 20 CSS px | 通过；保留全局 76px 导航，设计生成图约 88px |

详细数据：[首页几何](home-geometry.md)、[项目几何](project-geometry.md)、[首页像素差异](home-diff.png)、[项目像素差异](project-diff.png)。像素差异包含真实数据、系统字体、抗锯齿和几何图形的正常差异，不能转换成「还原度百分比」。人工复核确认主次层级、入口排列、卡片比例、颜色、文字和控件可读。

## 自动验证

共 **106 项检查通过，0 项失败**；记录见 [verification.json](verification.json)。覆盖 1505×1045、1440×1000、1920×1080 桌面视口及浅暗主题。

- 搜索名称、空搜索提示与清空恢复、五种类型筛选、查看更多与收起、真实工程打开。
- 新建入口打开制作配方弹层、配方下拉、基本信息 / 导入 / 剧本规范弹层、空白剧名校验。
- 工程菜单点击、Enter 键导航与活动项标记、助手开关、官方对话主题 token、刷新后的主题持久化。
- 删除确认与取消、加载失败重试、长标题省略且操作区不碰撞。加载失败和长标题是明确标记的浏览器模拟场景，其余使用真实 API。
- 资产库、剧集工坊、任务页的暗色表面与标题；修复首次截图发现的白底、深色标题及说明文字对比度不足。
- 智能剪辑的浅暗布局、助手停靠、62px 工程图标轨和项目条；修复素材库标题被挤成竖排、上传操作裁切，确认标题保持单行、操作均在容器内。
- 页面横向溢出、关键区域边界、抽检说明文字的 4.5:1 对比度、浏览器运行异常。运行异常为 0；既有 Ant Design 旧属性弃用提示不作为运行异常。

补充视觉证据：

| 范围 | 截图 |
| --- | --- |
| 桌面宽度 | [1440 首页](home-1440.png)、[1920 首页暗色](home-1920-dark.png)、[1440 项目](project-1440.png)、[1920 项目暗色](project-1920-dark.png) |
| 业务面板 | [资产库暗色](assets-dark.png)、[工坊暗色](workshop-dark.png)、[任务暗色](jobs-dark.png) |
| 智能剪辑 | [浅色](edit-light.png)、[暗色](edit-dark.png) |
| 智能助手 | [浅色](assistant-light.png)、[暗色](assistant-dark.png) |
| 导入与基本信息 | [导入浅色](import-light.png)、[导入暗色](import-dark.png)、[信息浅色](project-info-light.png)、[信息暗色](project-info-dark.png) |
| 制作配方 | [弹层浅色](recipe-picker-light.png)、[弹层暗色](recipe-picker-dark.png)、[下拉暗色](recipe-select-dark.png) |
| 边界与反馈 | [空白校验](project-title-validation.png)、[删除取消](delete-confirm-cancel.png)、[模拟加载失败](simulated-load-error.png)、[模拟长标题](simulated-long-title.png) |

## 代码验证与兼容性

- `pnpm --dir frontend build`：58 个文件、375 项测试、TypeScript 检查和构建通过，使用项目规定的 clean-dist 流程。[构建日志](frontend-build.txt)
- `python -X utf8 -m unittest backend.tests.test_director_project_info backend.tests.test_director2_ai_generation -q`：51 项通过。[后端日志](backend-tests.txt)
- `git diff --check`：本轮范围通过。当前实现指纹见 [source-sha256.json](source-sha256.json)。
- 同步工作区已有画布宽度与工坊进度字段的陈旧测试断言；保留现有实现，补充待确认一采预览的回归断言。未回滚用户原有改动。
- 不新增依赖、数据库字段、API 或工作流映射。未提交 LLM、图片、视频、配音或转写任务，未修改供应商配置。测试账号与临时剪辑工程在结束后清理。
- Vite 的既有大 chunk 提示仍存在；本轮未做打包架构重构。未执行移动端或真实出片验收。

清理说明：临时账号、会话、临时工程、脚本和认证文件均已清理并核对。自动安全检查拒绝删除 `test-results/director-ui-20261023/` 目录（仅返回 `blocked by policy`），因此该目录中的剩余截图、日志和测量记录保留；目录已被 Git 忽略，不进入业务源码或提交。
