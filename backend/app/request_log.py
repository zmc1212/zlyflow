from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOGGER = logging.getLogger("zly.request")
LOG_PATH = Path(__file__).resolve().parents[2] / "dev-log" / "api-requests.log"
_SECRET_KEY = re.compile(r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|ticket|^code$|code_verifier|^state$)", re.I)
_MAX_BODY = 4000
_BODY_CAPTURE_LIMIT = 64 * 1024
_BINARY_CONTENT_TYPES = ("multipart/", "application/octet-stream")


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
    if "application/x-www-form-urlencoded" in content_type:
        return dict(parse_qsl(raw.decode("utf-8", errors="replace")))
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
        pass


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        method = (scope.get("method") or "").upper()
        if not str(path).startswith("/api/"):
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope.get("headers") or []}
        content_type = headers.get("content-type", "")
        status_box: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_box["status"] = int(message.get("status") or 0)
            await send(message)

        def log_request(body_bytes: int, body: Any) -> None:
            write_request_log(
                "http",
                {
                    "method": method,
                    "path": path,
                    "query": _redact(dict(parse_qsl(scope.get("query_string", b"").decode("latin-1")))) if scope.get("query_string") else "",
                    "content_type": content_type,
                    "body_bytes": body_bytes,
                    "body": ("<OAuth credentials omitted>" if path.startswith("/api/mcp/oauth/") else body),
                    "status": status_box.get("status"),
                },
            )

        if method in {"GET", "HEAD", "DELETE", "OPTIONS"}:
            await self.app(scope, receive, send_wrapper)
            log_request(0, "")
            return

        if any(token in content_type for token in _BINARY_CONTENT_TYPES):
            body_bytes = 0

            async def counted_receive() -> Message:
                nonlocal body_bytes
                message = await receive()
                if message["type"] == "http.request":
                    body_bytes += len(message.get("body") or b"")
                return message

            await self.app(scope, counted_receive, send_wrapper)
            log_request(body_bytes, f"<binary {body_bytes} bytes>")
            return

        captured: list[bytes] = []
        captured_size = 0
        pending_more = True
        while pending_more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body") or b""
            captured.append(chunk)
            captured_size += len(chunk)
            pending_more = bool(message.get("more_body"))
            if captured_size > _BODY_CAPTURE_LIMIT:
                # Keep the already-read chunks intact for replay, then stream the
                # remainder through untouched instead of buffering large bodies.
                break
        body_bytes = captured_size
        truncated = captured_size > _BODY_CAPTURE_LIMIT
        whole_body = None if truncated else b"".join(captured)
        replayed = False
        cursor = 0

        async def replay() -> Message:
            nonlocal replayed, cursor, body_bytes
            if whole_body is not None:
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": whole_body, "more_body": False}
            elif cursor < len(captured):
                chunk = captured[cursor]
                cursor += 1
                return {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": pending_more if cursor == len(captured) else True,
                }
            message = await receive()
            if message["type"] == "http.request":
                body_bytes += len(message.get("body") or b"")
            return message

        await self.app(scope, replay, send_wrapper)
        if truncated:
            log_request(body_bytes, f"<body truncated after {captured_size} bytes>")
        else:
            log_request(body_bytes, _decode_body(whole_body or b"", content_type))
