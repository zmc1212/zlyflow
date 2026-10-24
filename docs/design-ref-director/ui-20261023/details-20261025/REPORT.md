# 导演台首页 Hypit 下线后参考截图 · 2026-10-25

**范围：仅重拍导演台首页。** 2026-10-25 移除 Hypit 复刻后，首页从四张创作卡变为三张（导演创作主卡 + 短视频批量 + 参考片复刻），下方保留整行剧本诊断入口，最近工程筛选变为四项。项目壳、内容库、工坊、智能剪辑等页面未改动，项目参考图继续使用 [`details-20261024`](../details-20261024/REPORT.md)。

## 截图

真实 Vite `http://127.0.0.1:5173/director`，已登录既有管理员账号；DPR 1。未新建或删除工程，未触发 LLM、生成或转写任务。

| 视口 | 浅色 | 暗色 |
| --- | --- | --- |
| 1505×1045 | [home-light-1505.png](home-light-1505.png) | [home-dark-1505.png](home-dark-1505.png) |
| 1440×1000 | [home-light-1440.png](home-light-1440.png) | [home-dark-1440.png](home-dark-1440.png) |
| 1920×1080 | [home-light-1920.png](home-light-1920.png) | [home-dark-1920.png](home-dark-1920.png) |

## 几何与状态

原始数据见 [capture.json](capture.json)。

- 六个视口均渲染 **3 个创作入口**（`.dh-entry-primary` + 2 × `.dh-entry-card`），主卡计算样式为 `grid-row: 1 / 3`；剧本诊断入口为整行，位于创作卡下方。
- 筛选标签为 **导演创作 / 短视频批量 / 参考片复刻 / 全部**，共 4 项；默认选中导演创作，首屏 6 张工程卡。
- 六个视口 `documentElement.scrollWidth <= innerWidth`，无横向溢出；`data-theme` 分别为 `light` / `dark`，主题在截图前已完成切换。
- 1440×1000 下主卡边界 `[158, 202, 715.36, 324]`，诊断入口 `[158, 544, 1218, 64]`；1505 与 1920 宽度下主卡分别为 `[159.5, 202, 752.25, 324]` 与 `[367, 202, 752.25, 324]`。

## 验证与清理

- `pnpm --dir frontend build`：60 个测试文件、415 项测试、TypeScript、clean-dist 与 Vite 构建通过。
- 截图脚本与登录诊断脚本位于忽略目录 `.tmp/`，验收后删除；本目录只保留截图、`capture.json` 与本报告。原 `details-20261024` 首页截图作为历史基线保留，未覆盖。
