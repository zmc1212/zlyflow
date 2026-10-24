from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

SCOPES = ["studio:read", "studio:generate", "studio:edit"]
SCOPE_LABELS = {
    "studio:read": "查看自己的工作流、参考图、任务、结果和剪辑时间线",
    "studio:generate": "生成图片、视频和停止自己的任务",
    "studio:edit": "预览、确认并修改自己的智能剪辑时间线",
}
CODE_TTL = 300
REQUEST_TTL = 600
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600


@dataclass(frozen=True)
class McpConfig:
    public_base_url: str = ""
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "McpConfig":
        return cls(os.getenv("ZLY_AI_VIDEO_STUDIO_MCP_PUBLIC_BASE_URL", "").strip().rstrip("/"),
                   os.getenv("ZLY_AI_VIDEO_STUDIO_MCP_ENABLED", "true").lower() not in {"0", "false", "off"})

    @property
    def error(self) -> str | None:
        if not self.enabled:
            return "管理员已关闭 MCP 连接"
        if not self.public_base_url:
            return "请配置 ZLY_AI_VIDEO_STUDIO_MCP_PUBLIC_BASE_URL；本地开发可填写 http://127.0.0.1:5173"
        try:
            parsed = urlsplit(self.public_base_url)
            _ = parsed.port
            if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
                raise ValueError()
            if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
                raise ValueError()
        except ValueError:
            return "MCP 对外地址必须是 HTTPS origin；仅本机回环地址允许 HTTP，不能包含路径、凭据或查询参数"
        return None

    @property
    def base(self) -> str:
        # The SDK needs a URL at construction time; the guard rejects requests
        # until an explicit, valid public origin has been configured.
        return self.public_base_url if not self.error else "http://127.0.0.1:5173"

    @property
    def issuer(self) -> str:
        return self.base + "/api/mcp/oauth"

    @property
    def resource(self) -> str:
        return self.base + "/api/mcp"

    @property
    def resource_metadata(self) -> str:
        return self.base + "/.well-known/oauth-protected-resource/api/mcp"

    @property
    def auth_metadata(self) -> str:
        return self.base + "/.well-known/oauth-authorization-server/api/mcp/oauth"

    def public_info(self) -> dict:
        return {"enabled": self.enabled, "configured": self.error is None, "message": self.error,
                "url": self.resource if not self.error else None, "transport": "streamable-http",
                "authorization": "oauth2.1", "scopes": SCOPE_LABELS}
