# zly-studio-dsh-plugin

DeepSeek Harness 的 ZLY 视频工作台插件：在 DSH 左侧栏增加「ZLY 视频工作台」入口，并在主面板内嵌工作台站点。

## 结构

| 文件 | 作用 |
|---|---|
| `package.json` | bundle 清单：`dsh.bundle.patch` + `dsh.client` |
| `cordis.patch.yml` | 插入 Host 行（`zly-studio`） |
| `index.js` | Host 半边：OAuth 授权、令牌刷新、注册本地 MCP 服务与状态路由 |
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

## MCP 工具接入

Host 侧实现两条连接路径，最终都拿到 OAuth 令牌并发起同一个 `zlystudio` MCP 服务：

- **一键连接（默认）**：面板输入工作台账号密码 → 调登录接口拿会话 → 自动发起并同意 OAuth 授权 → 换令牌。不开浏览器、不需要手动点授权，密码不落盘。
- **浏览器授权（备选）**：标准 OAuth 授权码 + PKCE，回调到 DSH 本机页面。

refresh token 存进 DSH 凭据，用 `${credential:ZLY_STUDIO_MCP_TOKEN}` 注册 MCP 服务；令牌自动刷新，
mcp-client 随凭据变化重连。工具以 `mcp__zlystudio__*` 出现在会话里（工作台共 44 个 `studio_*`）。

状态/操作路由（仅本机回环可访问）：

- `GET  /zly-studio/mcp/status`
- `POST /zly-studio/mcp/login`（账号密码一键连接）
- `POST /zly-studio/mcp/start`（浏览器授权）
- `POST /zly-studio/mcp/refresh`
- `POST /zly-studio/mcp/disconnect`
- `GET  /zly-studio/mcp/callback`（OAuth 回调）

## 后续

账号登录、积分余额、充值（微信支付）与订阅会先落在工作台后端，再由内嵌页面直接使用；插件层只负责入口与展示。