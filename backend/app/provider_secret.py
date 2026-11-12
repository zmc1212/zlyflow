"""管理设置「一键复制 Key」的明文出口。

各 provider 的 ``public_config()`` 一律只回显掩码；本模块是服务端唯一把已保存
凭据解密成明文的入口，只允许被超级管理员 + CSRF 鉴权、且每次调用都写审计日志的
那条路由调用，不得被其他模块复用。
"""

from __future__ import annotations

from typing import Any

SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    "llm": ("api_key",),
    "vlm": ("api_key",),
    "tts": ("api_key",),
    "grs": ("api_key",),
    "qiniu": ("access_key", "secret_key"),
    "mail": ("password",),
}


def reveal_secret(app_state: Any, provider: str, field: str) -> str | None:
    if field not in SECRET_FIELDS.get(provider, ()):
        raise ValueError("该服务商不支持复制此凭据字段")
    service = getattr(app_state, f"{provider}_provider", None)
    if service is None:
        raise ValueError("服务商尚未初始化，请重启工作台后端")
    return service.reveal_secret(field)
