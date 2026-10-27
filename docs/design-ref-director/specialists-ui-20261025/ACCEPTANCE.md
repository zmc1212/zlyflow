# 批量与参考片复刻 · 补充验收

2026-10-25，继续精修导演台子页面。已按先设计、再实现的顺序完成两页创作设置层级，并在真实 Vite **5173** 页面验证浅暗主题。

## 设计与实现

先由内置 ImageGen 生成 [双页设计总览](01-concept-board.png)，再用当前 Ant Design 与根级主题在浏览器中制作四张逐页冻结稿，之后才修改业务源码。生成总览负责表达层级，逐页冻结稿负责精确坐标；未把设计图片嵌入业务界面。[设计规格](DESIGN.md)、[提示词摘要](PROMPT.md)

| 页面 | 浅色设计 | 浅色实现 | 暗色设计 | 暗色实现 |
| --- | --- | --- | --- | --- |
| 短视频批量 | [设计](design-batch-light.png) | [实现](actual-batch-light.png) | [设计](design-batch-dark.png) | [实现](actual-batch-dark.png) |
| 参考片复刻 | [设计](design-replication-light.png) | [实现](actual-replication-light.png) | [设计](design-replication-dark.png) | [实现](actual-replication-dark.png) |

批量「创作设置」集中展示数量、画幅、单条时长、视频工作流及可选画风，移除模型体积控件。复刻将切镜灵敏度收进「更多设置」，固定分段时显示每段秒数，移除采样步数和深度控制强度控件；保留原进度与错误反馈。标签、键盘可访问名称和全宽开始按钮已补齐。

## 还原结果

四张默认画面均为 **1600×1000 / DPR 1 / CSS 像素截图**，同一数据、根主题、字体就绪与冻结动画条件下采集。与各自冻结稿比较，四张图的 RGB 像素差均为 **0**；16 个关键区域的外框最大绝对偏差均为 **0 CSS px**。这是对这四张有界默认画面的结论，不扩大为全站、全部动态状态或生成总览的还原百分比。[像素记录](evidence/pixel-comparisons.json)、[几何汇总](evidence/geometry-summary.json)

| 页面 / 主题 | 区域数 | 原始几何报告 | 同坐标差异图 |
| --- | ---: | --- | --- |
| 批量 / 浅色 | 4 | [报告](evidence/batch-light/geometry.md) | [差异](evidence/batch-light/verify-full-diff.png) |
| 批量 / 暗色 | 4 | [报告](evidence/batch-dark/geometry.md) | [差异](evidence/batch-dark/verify-full-diff.png) |
| 复刻 / 浅色 | 4 | [报告](evidence/replication-light/geometry.md) | [差异](evidence/replication-light/verify-full-diff.png) |
| 复刻 / 暗色 | 4 | [报告](evidence/replication-dark/geometry.md) | [差异](evidence/replication-dark/verify-full-diff.png) |

每组附测量、SVG 标注、真实 DOM 采集和验证结果。已查看完整截图与标注范围；浏览器 CDP 确认中文标签实际使用 **Microsoft YaHei**，英文 / 空白混排使用 Segoe UI。[字体与采集](evidence/captures.json)

## 操作与桌面验证

**48 项检查通过**，JavaScript 运行异常与未接管的 API 路由均为 0。[逐项结果及请求](evidence/interactions.json)

- 两主题均验证批量表单的数量、时长、画幅、注册表工作流与画风选择，以及主题为空时禁止提交。提交的创作参数、CSRF 与表单保存中的旧 `weightProfile` 均正确。
- 两主题均验证“更多设置”默认折叠、Enter 展开、键盘调整切镜灵敏度、自动保存及刷新恢复；固定分段显示秒数，切回智能分镜保留灵敏度。
- 复刻自动保存后，旧工程的 `steps=42`、`vaceStrength=0.6`、`seed=1234` 保留，目标风格更新正确；进行中锁住分镜方式，失败信息继续显示。
- **1440×900 / 1920×1080**、两页、两主题共 8 张补充桌面截图均无文档横向溢出。1440 下展开设置并滚动后，开始按钮完整处于底栏之上、没有遮挡。没有执行移动端适配或回归。

代表状态：[批量结果](batch-result-dark.png)、[更多设置展开](replication-expanded-dark.png)、[固定分段](replication-fixed-light.png)、[进行中](replication-running-light.png)、[失败](replication-error-light.png)、[1440 展开并滚动](desktop-1440-expanded-dark.png)。全部图片见[文件索引](evidence/artifact-index.json)。

## 静态验证

| 检查 | 结果 |
| --- | --- |
| `pnpm --dir frontend build` | **63 文件 / 430 项测试通过**，TypeScript、clean 与 Vite 构建通过；[输出](evidence/frontend-build.txt) |
| 相关后端 unittest | **33 项通过**，覆盖工作流约束、VACE 分层与 graph 映射、复刻载荷归一化及工程信息；[命令与输出](evidence/backend-tests.txt) |
| `git diff --check` | 本轮涉及文件通过；仅保留已有的 LF / CRLF 提示 |

## 边界与兼容

浏览器使用隔离 API fixture，页面由真实 React / Ant Design 代码在 5173 渲染。内置工作流元数据取自当前注册表，34 条画风取自当前静态目录；画风预览图在 fixture 中以 204 省略，本轮不验证其下载服务。保存和批量创建检查证明前端请求合同，未据此宣称生产数据库或模型出片端到端通过。未建立测试账号或生产样例，未访问用户工程、切换 ComfyUI、调用模型或提交真实生成。

UI 不主动改写旧载荷中的内部设置；重新生成批量内容仍由既有后端创建流程处理，本轮没有改变该行为。新增控件均直接使用 Ant Design，无新依赖、API、路由、迁移或生成图变化；Prompt Bar 的内部样式与官方 token 没有改动。构建保留原有大体积 chunk 提示，已有 Ant Design 弃用属性提示未作为本轮视觉重绘范围。

源文件摘要见 [source-snapshot.json](evidence/source-snapshot.json)。本轮只改两页和其局部布局样式，保留其他同期工作；验证临时文件及独立浏览器清理结果见 [cleanup.json](evidence/cleanup.json)。兼容与回滚说明见[架构记录](../../ARCHITECTURE.md#2026-10-25-批量与复刻创作设置精修)。
