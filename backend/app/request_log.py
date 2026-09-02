from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOGGER = logging.getLogger("zly.request")
LOG_PATH = Path(__file__).resolve().parents[2] / "dev-log" / "api-requests.log"
_SECRET_KEY = re.compile(r"(password|passwd|secret|token|api[_-]?key|authorization|cookie)", re.I)
_MAX_BODY = 4000


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("***" if _SECRET_KEY.search(str(key)) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value[:20]]
    if isinstance(value, str) and len(value) > _MAX_BODY:
        return value[:_MAX_BODY] + f"...(截断,共{len(value)}字)"
    return value


def _decode_body(raw: bytes, content_type: str) -> Any:
    if not raw:
        return ""
    if "application/json" in content_type:
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as error:
            return {"_json_error": str(error), "_raw": raw[:_MAX_BODY].decode("utf-8", errors="replace")}
    if "multipart/" in content_type or "octet-stream" in content_type:
        return f"<binary {len(raw)} bytes>"
    text = raw.decode("utf-8", errors="replace")
    return text if len(text) <= _MAX_BODY else text[:_MAX_BODY] + f"...(截断,共{len(text)}字)"


def write_request_log(event: str, payload: dict[str, Any]) -> None:
    line = json.dumps({"event": event, **_redact(payload)}, ensure_ascii=False)
    LOGGER.info("%s %s", event, line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        LOGGER.exception("写入请求日志失败")


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        method = (scope.get("method") or "GET").upper()
        if not str(path).startswith("/api/"):
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        more = True
        while more:
            message = await receive()
            chunks.append(message.get("body") or b"")
            more = bool(message.get("more_body"))
        body = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope.get("headers") or []}
        content_type = headers.get("content-type", "")
        status_box: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_box["status"] = int(message.get("status") or 0)
            await send(message)

        await self.app(scope, replay, send_wrapper)
        write_request_log(
            "http",
            {
                "method": method,
                "path": path,
                "query": scope.get("query_string", b"").decode("latin-1"),
                "content_type": content_type,
                "body_bytes": len(body),
                "body": _decode_body(body, content_type) if method in {"POST", "PUT", "PATCH"} else "",
                "status": status_box.get("status"),
            },
        )
