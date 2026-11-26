# ZLY 视频工作台

把 ZLY AI 视频工作台（创作工作台、导演台、任务中心）作为 DeepSeek Harness 的侧边栏面板打开，不需要在浏览器和 DSH 之间来回切换。

## 当前功能

- **侧边栏入口**：安装并启用后，左侧栏出现「ZLY 视频工作台」图标，点击进入整页面板。
- **整站内嵌**：面板内直接加载工作台站点（默认 `https://comfyui.zlyun168.com`），创作、导演台、任务、管理设置都在同一页面内完成。
- **适应面板 / 原始比例**：工作台在 1280px 以下会切到窄屏布局（收起左侧导航）。默认「适应面板」按 1280px 桌面宽度渲染再等比缩放到面板宽度，保持桌面版式；点按钮可切到「原始比例」，完全跟随面板宽度使用工作台自身的响应式布局。
- **服务地址可切换**：面板顶部可改服务地址，本地调试填 `http://127.0.0.1:7865`；设置保存在本机浏览器，不会上传。
- **MCP 工具接入**：点面板顶部「连接 MCP」，直接输入工作台账号密码即可一键连接（不需要开浏览器、不需要手工点授权）；工作台的 44 个 `studio_*` 工具会以 `mcp__zlystudio__*` 出现在 DSH 里，智能体可以直接创建视频、查任务、操作导演台。访问令牌由插件自动刷新，不需要手动换 token。也保留「浏览器授权」作为备选。
- **重新加载 / 在浏览器打开**：内嵌页面异常时一键重载；也可在系统浏览器中打开完整工作台。

## 使用

1. 安装并启用本插件。
2. 点击左侧栏的「ZLY 视频工作台」图标。
3. 首次使用如需本地开发环境，点顶部「服务地址」改成 `http://127.0.0.1:7865` 并保存。

## 内嵌登录的前提

内嵌页面是独立的 Web 应用，登录态靠会话 Cookie。DSH 页面与工作台不同站，浏览器只在 Cookie 为 `SameSite=None; Secure` 时才会在跨站 iframe 中携带它。因此线上部署需要：

```dotenv
ZLY_AI_VIDEO_STUDIO_SECURE_COOKIES=true
ZLY_AI_VIDEO_STUDIO_CROSS_SITE_COOKIES=true
```

并确保工作台通过 HTTPS 访问。未开启时面板仍可打开站点，但可能停在登录页；此时请用「在浏览器打开」。

本地开发（`http://127.0.0.1:51354` 内嵌 `http://127.0.0.1:7865`）属于同一站点，`SameSite=Lax` 也能正常登录，无需开启该开关。

## 限制

- 站点必须允许被嵌入（不能返回 `X-Frame-Options: DENY` 之类禁止嵌入的响应头）。
- 本版本只负责展示与访问，尚未接入 DSH 内的账号、积分与付费流程。

## 安装（本地开发）

```bash
# DSH 侧：Plugins → Add plugin → 选择本目录
# 或由 agent 执行 plugin_manager install_bundle（target = 本目录绝对路径）
```

修改 `client.js` 后需要重新安装或等客户端 HMR 重载；Host 侧改动需重启。
## MCP 工具接入（Host 桥）

工作台的 MCP 只支持 OAuth 2.1，而 DSH 的 MCP 客户端只接受静态 header。插件在 Host 侧承担 OAuth 客户端：

1. 面板「连接 MCP」→ 输入工作台账号密码；插件调用工作台登录接口，再用同一个会话发起 OAuth 授权请求并自动同意（等价于你在授权页点"允许"），全程不开浏览器；
2. 插件用授权码换令牌，把 refresh token 存进 DSH 凭据（**密码不落盘**）；
3. 插件用 `${credential:ZLY_STUDIO_MCP_TOKEN}` 注册 `zlystudio` MCP 服务，令牌变化时 mcp-client 自动重连；
4. 访问令牌在到期前 1 分钟自动刷新，所以 44 个 `studio_*` 工具长期可用。

换账号前先断开（`POST /zly-studio/mcp/disconnect`），否则会沿用上一个账号的授权。也支持「浏览器授权」：点表单里的按钮走标准 OAuth 授权页，适合不想在插件里输入密码的用户。

## 常见错误

- **HTTP 503 `temporarily_unavailable` / `请配置 ZLY_AI_VIDEO_STUDIO_MCP_PUBLIC_BASE_URL`**
  服务器端 MCP 网关没有配置对外地址。登录部署机编辑 `/opt/zly-ai-video-studio/.env`：
  ```dotenv
  ZLY_AI_VIDEO_STUDIO_MCP_PUBLIC_BASE_URL=https://comfyui.zlyun168.com
  ZLY_AI_VIDEO_STUDIO_MCP_ENABLED=true
  ```
  然后 `docker compose up -d` 重建工作台容器。验证：`curl https://comfyui.zlyun168.com/.well-known/oauth-protected-resource/api/mcp` 返回 200 即恢复。
- **HTTP 400 `账号或密码不正确`**：确认用的是工作台账号，且账号已启用、不处于必须改密状态。
