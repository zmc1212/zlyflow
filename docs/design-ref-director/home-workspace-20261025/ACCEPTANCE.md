# 导演台首页验收 · 2026-10-25

已实现「左侧创作启动台 + 右侧工程工作区」。先生成并冻结 `01-design-dark.png`，再在真实 5173 页面还原，验证桌面浅暗与业务操作。创建与继续工程已成为两个独立工作区；欢迎区、横向诊断条与三列工程卡已由新结构替换。

## 结果

| 项目 | 实际证据 |
| --- | --- |
| 设计 / 采集 | 1505×1045，DPR 1，同尺寸；原图 SHA256 见 `evidence/summary.json` |
| 主体几何 | 19 个人工从设计图标注的主体 DOM 锚点，全部实测，最大绝对偏差 2 CSS px |
| 桌面浅暗 | 1505×1045、1440×1000、1920×1080，共 6 组；无横向溢出、主按钮遮挡 |
| 文本对比 | 132 个样本，最低 4.63:1；使用根主题与 Ant Design 浮层主题 |
| UI 运行检查 | 71 项通过，页面错误 0，未知 API 路由 0 |
| 前端 | `pnpm --dir frontend build`：63 个测试文件、429 项测试、TypeScript、清理与 Vite 构建通过 |
| 后端 | `python -X utf8 -m unittest backend.tests.test_director_project_info backend.tests.test_skill_packs -q`：55 项通过 |
| 实际中文字体 | CDP `CSS.getPlatformFontsForNode`，Microsoft YaHei / MicrosoftYaHei-Bold，详见字体证据 |
| 独立视觉复核 | 主体结构通过；镜头材质按唯一 finding 修复，再复拍六组，verdict 为 resolved / ship；该次 verdict 仅评分该项修复 |

71 项检查覆盖模式选择不创建空工程、模式说明与三步清单、名称/简介搜索、空结果和清空、四种类型筛选、查看全部/收起、长标题省略及完整 title、键盘打开制作配方、取消不创建、创建失败保留选择并重试、配方载荷和三种目标路由、打开工程、复制、删除取消/失败/确认、刷新加载态、加载失败重试、三类空态、主题切换与刷新持久化、CSRF、桌面布局与文字对比度。逐项记录见 `evidence/ui-checks.json`。

## 实际边界

- 实际页面运行于 `http://127.0.0.1:5173/director`。全部 `/api` 请求被浏览器层隔离 fixture 接管，样例工程未写入生产；创建/复制/删除验证的是前端请求与路由合同。后端真实处理由上述临时数据库测试覆盖。未据此宣称生产 MySQL / 七牛云或实际出片已端到端验证。
- 生成稿的全局导航约 92px、顶栏约 69px，与产品既有 76px / 64px 外壳不符；实现保留产品外壳。主体在原图标注位置还原，19 个锚点不包含这一外壳差异。
- SVG 镜头核心已补齐径向明暗、玻璃反光与青色边缘；原图的细微纹理、辉光、字形仍有差异。几何偏差不等于还原率，不声称全图逐像素一致。
- 只验证桌面，没有执行手机适配或手机回归。没有调用实际模型、转写、ComfyUI 或出片服务。
- Vite 保留现有的大 chunk 提示；构建退出码为 0。设计 detector 被全局 `COMP_ROUND_OPEN` 门禁拒绝，未形成有效自动设计检测；没有把其空数组当作通过。验收依据实际截图、几何、对比度、运行检查与独立复核。

## 图片与复查

- [冻结设计](01-design-dark.png)、[暗色实现](02-implementation-dark.png)、[浅色实现](03-implementation-light.png)
- [整屏对照](04-comparison.png)、[局部原像素对照](05-detail-comparison.png)、[未遮罩差异图](06-difference.png)
- 六张 `home-{light,dark}-{1505,1440,1920}.png`；另有配方、长标题、错误和浅暗空态截图。
- `regions.json` 保存人工选区；`evidence/{capture.json,measurements.json,geometry.md,capture-verification.json,ui-checks.json,summary.json}` 保存原始证据。`RECHECK.json` 使用相对输入路径，可运行 `python -X utf8 G:/AppData/.codex/skills/draw-ui/scripts/verify_capture.py --manifest docs/design-ref-director/home-workspace-20261025/RECHECK.json --out-dir test-results/home-workspace-recheck` 离线复核同一截图。Windows 子进程需设置 `PYTHONIOENCODING=utf-8`。

开源参照仅提炼结构与功能关系：[Toonflow](https://github.com/HBAI-Ltd/Toonflow-app)、[ComfyUI frontend](https://github.com/Comfy-Org/ComfyUI_frontend)、[OpenCut](https://github.com/OpenCut-app/OpenCut)。未复制其组件源码或图片；完整生图输入与来源见 [PROMPT.md](PROMPT.md)。

最终源码为 `frontend/src/director2/Director2StudioHome.tsx` 与 `director-home.css`，哈希见 summary。证据归档后尝试清理 `test-results/director-home-tech-20261025/` 与已弃用的 `docs/design-ref-director/home-tech-20261025/`，自动审批返回 `blocked by policy`，包含逐文件安全清理的替代操作也被拒绝；两个目录仍保留且被 `.gitignore` 忽略，`cleanup_verified` 为 false。没有绕过策略或删除其他目录。其他并行工作保留，未创建提交。
