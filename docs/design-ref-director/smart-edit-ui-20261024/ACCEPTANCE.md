# 智能剪辑 UI 验收 · 2026-10-24

先生成设计图，再在现有工程中实现，最后使用真实 5173 页面截图、DOM 测量与实际操作校准。本轮按原图还原主要布局与控件，未把图片当作页面背景。

## 结果

- 原图：1672×941 px，保留内置 imagegen 原始文件；同坐标对照采用 1672×941 CSS 视口、DPR 1、视口截图。原图 SHA-256：`04ea5bb669d1791a815e5b4fbd58b78277f0ed5e4b93c31e644a82548e910bbe`。
- 23 个 DOM 区域全部采集，前 12 个主要布局区域最大偏差 2 CSS px，含搜索、分段筛选、导入、播放键、三个属性标签及重置按钮的整体最大偏差 4 CSS px。具体差值见 [geometry.md](evidence/geometry.md)。
- 128 项桌面检查通过：49 项核心交互、72 项跨主题 / 视口检查、7 项保存失败恢复与长标题检查。三个桌面宽度为 1440×900、1672×941、1920×1080，各含浅色和暗色；不包含移动端。
- 132 个文字对比度样本均达到 AA，最低 4.59:1；实际中文字体为 Microsoft YaHei，来自 Chrome 的平台字体信息。浏览器页面错误为 0。
- `pnpm --dir frontend build` 通过：60 个测试文件 / 414 项测试、TypeScript、清理和 Vite 构建全部完成。
- `python -X utf8 -m unittest backend.tests.test_smart_edit backend.tests.test_editing_assistant -q` 通过：52 项。

## 设计与真实页面

| 文件 | 用途 |
| --- | --- |
| [00-before-light.png](00-before-light.png) | 设计生成时使用的既有 1440×1000 截图；仅作原始输入参考，不与不同视口做几何比较 |
| [01-design-light.png](01-design-light.png) | 首先生成并冻结的设计图 |
| [02-implementation-light.png](02-implementation-light.png) / [03-implementation-dark.png](03-implementation-dark.png) | 最终真实桌面浅暗界面 |
| [04-comparison.png](04-comparison.png) | 原图与真实页面并列；保留像素，不将实现反向替换为设计基线 |
| [05-controls-comparison.png](05-controls-comparison.png) | 命令栏、素材、属性、播放和时间线的原始大小控件对照与绝对差异 |
| [06-difference.png](06-difference.png) | 未屏蔽媒体与字形差异的整页差异图 |
| `desktop-light/dark-1440/1672/1920.png` | 六种桌面主题 / 尺寸实拍 |
| `local-import-light/dark.png` | 继承当前主题的本机引用弹窗 |
| `assistant-tools-light/dark.png` | AI 剪辑工具下拉与原有动作 |
| `export-light/dark.png`、`effects-light/dark.png` | 导出与特效面板 |
| `empty-light/dark.png` | 未导入素材的真实空态，默认没有片段属性栏 |

## 已实际操作

素材分类 / 搜索 / 无结果、选择片段打开属性、关闭并扩宽预览、属性重置、画面 / 声音 / 变速三个标签、真实保存并硬刷新恢复、按播放头拆分、撤销 / 重做、复制 / 删除、输入文字时的快捷键隔离、八种特效、三个文字预设、工程设置、四种交换格式与 JSON 备份下载、本机错误路径、理解确认取消、所有成片 / 字幕 / 引流策略菜单、助手关闭 / 重新停靠、五个工程模块与跳转后返回时间线，均有实际浏览器检查。保存失败测试确认云端未覆盖、本地修改保留、重试后确实入库；长工程名在 1440 桌面省略并保留完整标题。

检查明细见 [interaction-checks.json](evidence/interaction-checks.json)、[desktop-meta.json](evidence/desktop-meta.json) 和 [extra-checks.json](evidence/extra-checks.json)。

## 范围与保留差异

生成图中的照片、文件名、时长、计数与部分字形是示例。实际页面继续显示真实数据，测试照片从设计图干净图片区域提取后仅制作隔离素材；部分图片细节 / 构图和媒体标题底框保留工作台真实预览与 FFmpeg 的一致行为。原图的全局导航宽度和按钮字形受到现有工作台规范约束。完整差异图保留这些差异，不将几何偏差或图片比较转换成“还原度百分比”，也不宣称逐个像素完全相同。

画面属性按图拆成三个标签；音量 / 静音 / 淡入淡出在「声音」，速度 / 时间 / 素材入点在「变速」，原有设置全部保留。主题由根 Provider 管理，业务控件为 Ant Design，AI 助手 token 与控件语法来自已读取的[官方源码](https://github.com/TurboKach/ai-native-react-components)。未新增 UI 依赖、API、表或剪辑版本。

界面始终从 5173 验证，API 仅转发到隔离 SQLite 后端；健康状态为 UI 验收桩，没有访问真实账号工程、切换供应商、启动 ComfyUI、调用生成模型或外发音轨。空态、导出和菜单截图在有限动画结束后采集。临时脚本、测试账号 / 数据库与媒体在验收后清理，保留本目录中的正式证据。

## 复核与日志

已有元数据与固定图片可离线重新验证：

```powershell
python -X utf8 G:/AppData/.codex/skills/draw-ui/scripts/verify_capture.py --manifest docs/design-ref-director/smart-edit-ui-20261024/RECHECK.json --out-dir test-results/smart-edit-ui-recheck
pnpm --dir frontend build
python -X utf8 -m unittest backend.tests.test_smart_edit backend.tests.test_editing_assistant -q
```

[前端构建日志](evidence/frontend-build.txt)、[后端测试日志](evidence/backend-tests.txt)、[真实截图元数据](evidence/capture.json)、[原图测量](evidence/measurements.json)、[完整几何验证](evidence/verification.json)、[字体](evidence/platform-fonts.json) 与 [摘要](evidence/summary.json) 已归档。原始验证记录中的临时执行路径按原样保留，图像和元数据已复制到本目录；`RECHECK.json` 使用当前位置的相对路径。

现有 Vite 大分块构建提示不影响本次构建通过。回滚只逆向撤回本轮界面增量，保留既有未提交改动，无需数据库或工作流回滚。
