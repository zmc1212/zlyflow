# 无限画布：设计图与还原验收

更新：2026-10-28（视觉基线仍为 2026-10-24，当时先生成设计图，再还原真实 React / Ant Design / React Flow 界面，并通过 5173 自动截图对照、局部复核和桌面交互回归）。当前视觉基线为下表 06–11 与验收记录；01 为始终未改动的原图。

| 文件 | 内容 |
| --- | --- |
| [01-editor-concept-light.png](01-editor-concept-light.png) | 原始浅色设计图，1586×992 |
| [06-editor-fidelity-light.png](06-editor-fidelity-light.png) | 当前真实浅色界面，同视口、DPR 1 |
| [07-editor-fidelity-dark.png](07-editor-fidelity-dark.png) | 当前真实暗色界面 |
| [08-components-fidelity-light.png](08-components-fidelity-light.png) | 浅色小控件、菜单、浮层与弹窗 |
| [09-components-fidelity-dark.png](09-components-fidelity-dark.png) | 同组控件的暗色状态 |
| [10-reference-overlay.png](10-reference-overlay.png) | 原图 / 实拍各 50% 叠加，便于检查轮廓与间距 |
| [11-reference-heatmap.png](11-reference-heatmap.png) | 全图差异热图，保留数据和字形差异 |
| [12-export-library-light.png](12-export-library-light.png) | PNG 导出与素材库 · 浅色 |
| [13-export-library-dark.png](13-export-library-dark.png) | PNG 导出与素材库 · 暗色 |
| [14-panels-fidelity-light.png](14-panels-fidelity-light.png) | 属性、图层、历史面板 · 浅色 |
| [15-panels-fidelity-dark.png](15-panels-fidelity-dark.png) | 同组面板 · 暗色 |
| [FIDELITY.md](FIDELITY.md) | 布局、控件、兼容性、验证方式与差异说明 |
| [fidelity-report.json](fidelity-report.json) | 原图及截图摘要、几何、交互、对比度与测试记录 |
| [fidelity-geometry.md](fidelity-geometry.md) | 21 个区域的自动测量结果 |
| [fidelity-micro-ink.json](fidelity-micro-ink.json) | 22 处文字与图标的可见边界比较 |
| [fidelity-capture.json](fidelity-capture.json) | 实际 URL、标题、视口、DPR、字体及 DOM 采集元数据 |
| [generation-prompt.txt](generation-prompt.txt) | 最初设计图使用的生图提示词 |

当前规格：全局悬浮页头距顶 12px、两侧 16px、48px 高，画布工作区与导航从 76px 起始、导航 86px、命令栏 64px；工具轨 58×481px、添加菜单 226×327px、属性面板 360px、底部视图栏 375×49px、小地图 174×101px。21 个区域均可测量，外框最大偏差 2 CSS px。浅暗控件按根主题和语义变量继承，业务控件直接使用 Ant Design。2026-10-28 起画布删除 60px 专用顶栏，与生成页、导演台共用同一 `StudioHeader`；素材 Drawer 同步停在 76px 页头下方。

已检查浅暗主题 42 个弹层和面板截图状态，覆盖菜单、工作流、图片校验、视角、快捷键、属性、图层、历史、预览、PNG 导出及素材搜索/分页。完整测试与原图示意数据差异见 FIDELITY.md；不把像素差异转换成还原率。

可在 [5173 开发入口](http://127.0.0.1:5173/canvas) 查看界面。截图用隔离 SQLite 和验收浏览器的测试响应完成，摄影仅裁自设计稿的纯照片区域，没有把设计图铺作界面，也没有把示例模型或示例内容写入业务源码。

02–05 为初版历史截图，相关说明保存在 [初版记录](DESIGN-v44-history.md)，不再作为当前精确还原的验收依据。
