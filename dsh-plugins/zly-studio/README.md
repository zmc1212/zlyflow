# zly-studio-dsh-plugin

DeepSeek Harness 的 ZLY 视频工作台插件：在 DSH 左侧栏增加「ZLY 视频工作台」入口，并在主面板内嵌工作台站点。

## 结构

| 文件 | 作用 |
|---|---|
| `package.json` | bundle 清单：`dsh.bundle.patch` + `dsh.client` |
| `cordis.patch.yml` | 插入 Host 行（`zly-studio`） |
| `index.js` | Host 半边（当前为空实现，账号/计费桥接后扩展） |
| `client.js` | Client 半边：注册 `sidebar.panellist` 图标与 `main` 整页面板 |
| `locale/{zh,en}.json` | 插件管理页展示文案 |
| `icon.svg` | 插件图标 |
| `docs/DETAIL.md` | 插件详情页文档 |

## 开发

- 客户端改动：改 `client.js` 后重新安装 bundle 或刷新 DSH 页面。
- Host 改动：需要重启 DSH。
- 语法检查：`ELECTRON_RUN_AS_NODE=1 "$DSH_NODE_EXECUTABLE" --check client.js`。

## 安装

DSH → Plugins → Add plugin → 选择本目录；或由 agent 执行 `plugin_manager install_bundle`（target 为本目录绝对路径）。

## 后续

账号登录、积分余额、充值（微信支付）与订阅会先落在工作台后端，再由内嵌页面直接使用；插件层只负责入口与展示。