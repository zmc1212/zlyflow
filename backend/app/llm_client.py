from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse
import requests

LLM_CONNECT_TIMEOUT_SECONDS = 20.0
LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS = 300.0


class LlmError(RuntimeError):
    pass


class LlmTemporaryError(LlmError):
    pass


class LlmBillingError(LlmError):
    """Upstream refused the call because of quota, arrears, or insufficient balance."""


class LlmAuthError(LlmError):
    """Upstream refused the call because the API key is missing, invalid, or forbidden."""


_BILLING_HINTS = (
    "余额不足", "余额不够", "账户余额", "额度不足", "配额不足", "欠费", "欠费停用",
    "魔粒不足", "预付费", "费用不足", "请充值", "请先充值",
    "insufficient_quota", "insufficient quota", "insufficient balance",
    "account balance", "arrear", "arrearage", "overdue",
    "payment required", "please recharge", "please top up",
    "not enough fund", "exceeded your current quota", "quota exceeded",
)
_AUTH_HINTS = (
    "invalid api key", "incorrect api key", "invalid_api_key", "invalid token",
    "unauthorized", "authentication", "authentication_error",
    "api key 无效", "token 无效", "权限不足", "凭据无效",
)
_MODEL_HINTS = (
    "model_not_found", "model not found", "does not exist", "unknown model",
    "has no provider supported", "model not exist", "无可用渠道", "未找到模型",
)
_FILTER_HINTS = (
    "content_filter", "content management", "content_policy", "moderation",
    "responsibleai", "unsafe content", "违规", "敏感内容",
)


def looks_like_llm_billing(text: str | None) -> bool:
    return _hint_in(text, _BILLING_HINTS)


def looks_like_llm_auth(text: str | None) -> bool:
    return _hint_in(text, _AUTH_HINTS)


def _hint_in(text: str | None, hints: tuple[str, ...]) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    return any(hint.lower() in lowered for hint in hints)


def looks_like_llm_model_missing(text: str | None) -> bool:
    return _hint_in(text, _MODEL_HINTS)


def looks_like_llm_content_filter(text: str | None) -> bool:
    return _hint_in(text, _FILTER_HINTS)


def append_upstream_log(summary: str, upstream: str | None) -> str:
    snippet = (upstream or "").strip()[:400]
    if not snippet:
        return summary
    if "上游返回" in summary:
        return summary
    return f"{summary}上游返回：{snippet}"


def format_llm_billing_error(*, upstream: str, status: int | None = None, action: str = "对话推理") -> str:
    del action
    http = f"（HTTP {status}）" if status else ""
    return append_upstream_log(
        f"大模型上游余额不足或欠费{http}，请到供应商控制台充值后再试。",
        upstream,
    )


def repair_utf8_mojibake(text: str) -> str:
    """Fix UTF-8 Chinese that was decoded as Latin-1 (classic SSE/text/* default)."""
    raw = text or ""
    if not raw or any("\u3400" <= ch <= "\u9fff" for ch in raw):
        return raw
    try:
        repaired = raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw
    if any("\u3400" <= ch <= "\u9fff" for ch in repaired):
        return repaired
    return raw


def _decode_sse_line(raw_line: Any) -> str:
    if raw_line is None:
        return ""
    if isinstance(raw_line, bytes):
        try:
            return raw_line.decode("utf-8")
        except UnicodeDecodeError:
            return repair_utf8_mojibake(raw_line.decode("latin-1", errors="replace"))
    return repair_utf8_mojibake(str(raw_line))


def is_llm_timeout_error(error: BaseException | str) -> bool:
    text = str(error)
    lowered = text.lower()
    return "超时" in text or "timed out" in lowered or "read timeout" in lowered


def normalize_http_timeout(timeout: float | tuple[float, float]) -> tuple[float, float]:
    if isinstance(timeout, (tuple, list)) and len(timeout) >= 2:
        return (float(timeout[0]), float(timeout[1]))
    return (LLM_CONNECT_TIMEOUT_SECONDS, float(timeout))


def is_upstream_llm_failure(error: BaseException | str) -> bool:
    if isinstance(error, (LlmBillingError, LlmTemporaryError, LlmAuthError)):
        return True
    text = str(error)
    return (
        looks_like_llm_billing(text)
        or looks_like_llm_auth(text)
        or looks_like_llm_model_missing(text)
        or looks_like_llm_content_filter(text)
        or "上游返回" in text
    )


def raise_llm_http_error(*, action: str, status: int, upstream: str) -> None:
    msg = (upstream or "").strip()[:400] or f"HTTP {status}"
    if status == 402 or looks_like_llm_billing(msg):
        raise LlmBillingError(format_llm_billing_error(upstream=msg, status=status, action=action))
    if looks_like_llm_content_filter(msg):
        raise LlmError(append_upstream_log(f"大模型拒绝了本次内容（HTTP {status}），请修改后再试。", msg))
    if status in {401, 403} or looks_like_llm_auth(msg):
        raise LlmAuthError(append_upstream_log(
            f"大模型鉴权失败（HTTP {status}），请检查管理设置中的 API Key。", msg,
        ))
    if status == 404 or looks_like_llm_model_missing(msg):
        raise LlmError(append_upstream_log(f"大模型服务未找到指定模型（HTTP {status}）。", msg))
    if status in {408, 425, 429} or status >= 500:
        raise LlmTemporaryError(append_upstream_log(
            f"大模型服务{action}暂时不可用（HTTP {status}）。", msg,
        ))
    raise LlmError(append_upstream_log(f"大模型服务{action}失败（HTTP {status}）。", msg))


def _payload_error_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("error", "errors", "error_message", "message", "Message", "err_msg", "msg", "detail"):
        value = payload.get(key)
        if isinstance(value, dict):
            for inner_key in ("message", "msg", "detail", "code", "type"):
                inner = value.get(inner_key)
                if inner and str(inner).strip() and str(inner).lower() not in {"success", "ok"}:
                    return str(inner).strip()
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                nested = _payload_error_text(first)
                if nested:
                    return nested
            if isinstance(first, str) and first.strip():
                return first.strip()
        if isinstance(value, str) and value.strip() and value.lower() not in {"success", "ok", "true"}:
            return value.strip()
    code = payload.get("code")
    if code not in (None, 0, "0", 200, "200", "ok", "OK"):
        return str(code).strip()
    return ""


_FREE_WORD = re.compile(r"(?<![a-z])free(?![a-z])", re.I)
_SKIP_FREE_TEXT_KEYS = {
    "description", "intro", "content", "about", "readme", "summary", "detail", "about_the_model",
}
SILICONFLOW_PLAZA_URL = "https://cloud.siliconflow.cn/open/models"
_PLAZA_MODEL_NAME_RE = re.compile(r'"modelName"\s*:\s*"([^"]+)"')
_PLAZA_PRICE_RE = re.compile(r'"price"\s*:\s*"([^"]+)"')
_PLAZA_STATUS_RE = re.compile(r'"status"\s*:\s*"([^"]+)"')
_PLAZA_HTML_MODEL_RE = re.compile(
    r'text-base">\s*((?:Pro/)?[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)\s*<'
)
_PLAZA_FREE_BADGE_RE = re.compile(r">\s*(Free|免费)\s*<", re.I)
_DISABLED_STATUS = {"disable", "disabled", "deprecated", "offline"}


def catalog_provider_key(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    if "siliconflow" in host:
        return "siliconflow"
    if "modelscope" in host:
        return "modelscope"
    if host in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
        return "ollama"
    if "deepseek.com" in host:
        return "deepseek"
    if "dashscope" in host or "aliyuncs.com" in host:
        return "dashscope"
    return "custom"


def _strings_for_free_label(item: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key, value in item.items():
        if str(key).lower() in _SKIP_FREE_TEXT_KEYS:
            continue
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    found.append(entry)
                elif isinstance(entry, dict):
                    found.extend(_strings_for_free_label(entry))
        elif isinstance(value, dict):
            found.extend(_strings_for_free_label(value))
    return found


def item_has_free_label(item: dict[str, Any]) -> bool:
    for text in _strings_for_free_label(item):
        stripped = text.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered in {"free", "免费"}:
            return True
        if "免费" in stripped and len(stripped) <= 24:
            return True
        if _FREE_WORD.search(stripped) and len(stripped) <= 80:
            return True
    return False


def parse_siliconflow_plaza_free_ids(html: str) -> set[str]:
    """Read Free / price-0 model IDs from SiliconFlow's public model plaza HTML."""
    if not html or not isinstance(html, str):
        return set()
    text = html.replace('\\"', '"')
    free_ids: set[str] = set()
    paid_ids: set[str] = set()
    matches = list(_PLAZA_MODEL_NAME_RE.finditer(text))
    for index, match in enumerate(matches):
        model_id = match.group(1).strip()
        if not model_id or model_id.lower().startswith("pro/"):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), match.end() + 4000)
        window = text[match.start():end]
        status = _PLAZA_STATUS_RE.search(window)
        if status and status.group(1).strip().lower() in _DISABLED_STATUS:
            continue
        prices = _PLAZA_PRICE_RE.findall(window)
        if prices:
            if all(item in {"0", "0.0", "0.00"} for item in prices):
                free_ids.add(model_id)
            else:
                paid_ids.add(model_id)
            continue
        if _PLAZA_FREE_BADGE_RE.search(window) or re.search(r'"(Free|免费)"', window):
            free_ids.add(model_id)

    html_matches = list(_PLAZA_HTML_MODEL_RE.finditer(html))
    for index, match in enumerate(html_matches):
        model_id = match.group(1).strip()
        if not model_id or model_id.lower().startswith("pro/"):
            continue
        end = html_matches[index + 1].start() if index + 1 < len(html_matches) else min(len(html), match.end() + 2500)
        card = html[match.start():end]
        if _PLAZA_FREE_BADGE_RE.search(card):
            free_ids.add(model_id)
    return free_ids - paid_ids


def apply_plaza_free_ids(models: list[dict[str, Any]], free_ids: set[str]) -> list[dict[str, Any]]:
    if not free_ids:
        return models
    for row in models:
        if row.get("id") in free_ids:
            row["free"] = True
    return models


_NON_CHAT_MARKERS = (
    "ocr",
    "bge-",
    "embed",
    "rerank",
    "asr",
    "tts",
    "whisper",
    "sensevoice",
    "kolors",
    "stable-diffusion",
    "flux-1",
    "flux.1",
    "hunyuanvideo",
    "index-tts",
    "indextts",
)


def is_llm_chat_model(model_id: str) -> bool:
    lowered = (model_id or "").strip().lower()
    if not lowered:
        return False
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


def filter_llm_catalog_models(models: list[dict[str, Any]], *, provider: str) -> list[dict[str, Any]]:
    if provider != "siliconflow":
        return models
    return [row for row in models if is_llm_chat_model(str(row.get("id") or ""))]


def _model_display_label(item: dict[str, Any], model_id: str) -> str:
    for key in ("display_name", "show_name", "showName", "name", "label"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return model_id


def _to_unit_price(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_model_free(item: dict[str, Any], *, provider: str) -> bool | None:
    model_id = str(item.get("id") or "").strip()
    if not model_id:
        return None
    if model_id.lower().startswith("pro/"):
        return False
    if provider in {"ollama", "lmstudio"}:
        return True

    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else None
    if pricing:
        amounts = [
            parsed
            for key in ("prompt", "completion", "input", "output")
            if (parsed := _to_unit_price(pricing.get(key))) is not None
        ]
        if amounts:
            return all(amount == 0 for amount in amounts)

    for flag in ("is_free", "free"):
        if flag in item:
            return bool(item[flag])
    if item_has_free_label(item):
        return True
    return None


def parse_model_catalog(payload: Any, *, provider: str, free_only: bool) -> list[dict[str, Any]]:
    raw_items: list[Any]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        raw_items = payload["data"]
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        model_id = str(item["id"]).strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        free = classify_model_free(item, provider=provider)
        if free_only and free is not True:
            continue
        owned_by = item.get("owned_by")
        models.append({
            "id": model_id,
            "label": _model_display_label(item, model_id),
            "free": free,
            "owned_by": str(owned_by) if owned_by else None,
        })
    models.sort(key=lambda row: (row["free"] is not True, row["id"].lower()))
    return models


SYSTEM_PROMPT_OPTIMIZE_VIDEO = """你是一位顶级的 AI 视频生成提示词专家（精通 MiniMax、Runway、Sora、LTX-Video 等模型）。
你的任务是将用户输入的简短粗糙的视频想法，扩写并优化为高质量、高表现力、电影级质感的提示词。

优化原则：
1. 画面主体与动作：清晰描述主体外观特征、具体动作变化及动态过程。
2. 镜头与运镜：明确景别（特写/中景/全景）与镜头运动方式（缓慢推近、平移跟随、低角度仰拍、航拍俯瞰等）。
3. 光影与色彩：描述光线来源与质感（如晨光侧逆光、丁达尔光效、冷暖对比色调、电影级调色）。
4. 氛围与细节：补充环境动态细节（如微风拂动、粒子漂浮、雨滴水花等）。
5. 结构保留：若原提示词中包含 `<Picture 1>`、`<Picture 2>` 等参考图标记，必须在对应主体位置原样保留这些标记，不得删除或更改序号。
6. 输出格式：直接输出优化后的提示词文本，严禁包含任何前言、解释、分析或 markdown 格式块。输出纯文本。

重要：你不需要也不允许输出任何思考过程、分析过程、推理过程或内心独白。直接输出最终结果即可。"""

SYSTEM_PROMPT_OPTIMIZE_IMAGE = """你是一位顶级的 AI 绘画与图像生成提示词专家（精通 Midjourney、Stable Diffusion、FLUX、GPT-Image 等模型）。
你的任务是将用户输入的简短粗糙的图像创意，优化为具有丰富细节、高审美构图与强烈艺术氛围的高质量提示词。

优化原则：
1. 画面主体：精准刻画主体的形态、材质、服饰、姿态与神情。
2. 构图与视角：明确构图法则（黄金分割、对称构图、主观视角等）与空间景深。
3. 光影与色彩：细化光源方向、光质（柔光、强光、戏剧性高光）与色彩搭配方案。
4. 细节与质感：增强材质纹理细节与环境真实感/艺术质感。
5. 输出格式：直接输出优化后的提示词文本，严禁包含任何前言、解释、分析或 markdown 格式块。输出纯文本。

重要：你不需要也不允许输出任何思考过程、分析过程、推理过程或内心独白。直接输出最终结果即可。"""


SYSTEM_PROMPT_ANALYZE_SUBJECT = """你是影视美术指导。用户会提供一张参考图。
请根据图像本身撰写适合 MiniMax H3 识别的高精度外貌、服饰、材质或空间特征描述，控制在 40 个汉字以内。
只输出描述本身，不要前言、标题或 markdown。"""


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _json(self, response: requests.Response, action: str) -> dict[str, Any]:
        if response.status_code >= 400:
            payload: dict[str, Any] | None = None
            try:
                parsed = response.json()
                payload = parsed if isinstance(parsed, dict) else None
            except Exception:
                payload = None
            msg = _payload_error_text(payload) or (response.text or "").strip()[:400] or f"HTTP {response.status_code}"
            raise_llm_http_error(action=action, status=response.status_code, upstream=msg)
        try:
            payload = response.json()
        except ValueError as error:
            raise LlmError(f"大模型服务 {action} 返回了无效 JSON 响应") from error
        if not isinstance(payload, dict):
            raise LlmError(f"大模型服务 {action} 返回格式异常")
        return payload

    def list_models(self, timeout: float = 10.0) -> list[str]:
        url = f"{self.base_url}/models"
        try:
            response = self.session.get(url, headers=self.headers, timeout=timeout)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                    return [str(item["id"]) for item in data["data"] if isinstance(item, dict) and "id" in item]
        except Exception:
            pass
        return []

    def list_model_catalog(self, *, free_only: bool = False, timeout: float = 15.0) -> dict[str, Any]:
        provider = catalog_provider_key(self.base_url)
        url = f"{self.base_url}/models"
        params = {"sub_type": "chat"} if provider == "siliconflow" else None
        try:
            response = self.session.get(url, headers=self.headers, params=params, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            raise LlmTemporaryError(f"无法拉取模型目录：{exc}") from exc
        if response.status_code >= 400:
            payload: dict[str, Any] | None = None
            try:
                parsed = response.json()
                payload = parsed if isinstance(parsed, dict) else None
            except Exception:
                payload = None
            msg = _payload_error_text(payload) or (response.text or "").strip()[:400] or f"HTTP {response.status_code}"
            raise_llm_http_error(action="拉取模型目录", status=response.status_code, upstream=msg)
        try:
            payload = response.json()
        except ValueError as error:
            raise LlmError("模型目录返回了无效 JSON") from error
        models = parse_model_catalog(payload, provider=provider, free_only=False)
        plaza_ok = False
        if provider == "siliconflow":
            plaza_ids = self._fetch_siliconflow_plaza_free_ids(timeout=timeout)
            plaza_ok = plaza_ids is not None
            apply_plaza_free_ids(models, plaza_ids or set())
            models = filter_llm_catalog_models(models, provider=provider)
        if free_only:
            models = [row for row in models if row.get("free") is True]
            models.sort(key=lambda row: (row["free"] is not True, row["id"].lower()))
        message = None if models else "上游未返回可用模型。"
        if free_only and not models:
            if provider == "siliconflow" and plaza_ok:
                message = "官方 /v1/models 不含 Free 字段。已对照模型广场价格为 0 的条目，但当前账号目录中没有可调用的免费模型。"
            elif provider == "siliconflow":
                message = "官方 /v1/models 不含 Free 字段，且无法读取硅基流动模型广场。请稍后重试，或手动填写 Qwen/Qwen2.5-7B-Instruct。"
            else:
                message = "上游完整目录中没有带 Free / 免费 标记的模型。"
        return {
            "models": models,
            "provider": provider,
            "free_only": free_only,
            "message": message,
        }

    def _fetch_siliconflow_plaza_free_ids(self, *, timeout: float) -> set[str] | None:
        try:
            response = self.session.get(
                SILICONFLOW_PLAZA_URL,
                headers={"User-Agent": "ZLY-AI-Video-Studio"},
                timeout=max(timeout, 20.0),
            )
        except requests.exceptions.RequestException:
            return None
        if response.status_code >= 400:
            return None
        html = response.text if isinstance(getattr(response, "text", None), str) else ""
        if not html:
            return None
        free_ids = parse_siliconflow_plaza_free_ids(html)
        if not free_ids:
            unescaped = html.replace('\\"', '"')
            if not _PLAZA_MODEL_NAME_RE.search(unescaped) and not _PLAZA_HTML_MODEL_RE.search(html):
                return None
        return free_ids

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | tuple[float, float] = 60.0,
        stream: bool = False,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        connect_timeout, read_timeout = normalize_http_timeout(timeout)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 关闭 Qwen3 / Qwen2.5 思考模式（enable_thinking=False），
            # 不支持此参数的模型会忽略该字段，不影响兼容性
            "enable_thinking": False,
            **self._thinking_control_fields(model),
        }
        if stream:
            payload["stream"] = True
        try:
            response = self.session.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=(connect_timeout, read_timeout),
                stream=stream,
            )
        except requests.exceptions.ConnectTimeout as exc:
            raise LlmTemporaryError(
                f"无法在 {connect_timeout:.0f} 秒内连上大模型服务 {self.base_url}。"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise LlmTemporaryError(
                f"请求大模型服务超时（等待 {read_timeout:.0f} 秒仍无响应）。"
                "模型可能仍在生成或首次装入显存，请稍后重试。"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise LlmTemporaryError(f"无法连接大模型服务 {self.base_url}：{exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise LlmTemporaryError(f"请求大模型服务异常：{exc}") from exc

        try:
            if stream:
                raw = self._read_chat_completion_body(response, stream=True, on_chunk=on_chunk)
            else:
                data = self._json(response, "对话推理")
                raw = self._extract_response_content(data)
        except LlmError as error:
            err_text = str(error)
            if "has no provider supported" in err_text or "not found" in err_text.lower():
                available_models = self.list_models()
                if available_models:
                    top_models = ", ".join(available_models[:6])
                    raise LlmError(
                        f"模型 '{model}' 当前平台未开放或不支持直接推理。平台当前开放可用模型推荐：{top_models}"
                    ) from error
            raise

        content = self._strip_thinking(raw)
        if not content:
            raise LlmError("大模型返回的内容为空")
        return content

    def _read_chat_completion_body(
        self,
        response: requests.Response,
        *,
        stream: bool,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        if response.status_code >= 400:
            data = self._json(response, "对话推理")
            return self._extract_response_content(data)
        content_type = (response.headers.get("Content-Type") or "").lower()
        if stream and "json" in content_type and "event-stream" not in content_type:
            data = self._json(response, "对话推理")
            return self._extract_response_content(data)
        if stream:
            try:
                response.encoding = "utf-8"
                return self._read_sse_chat(response, on_chunk=on_chunk)
            except requests.exceptions.Timeout as exc:
                raise LlmTemporaryError(
                    "请求大模型服务超时（等待过程中上游停止返回）。"
                    "模型可能仍在生成或首次装入显存，请稍后重试。"
                ) from exc
            finally:
                response.close()
        data = self._json(response, "对话推理")
        return self._extract_response_content(data)

    def _read_sse_chat(
        self,
        response: requests.Response,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        pieces: list[str] = []
        last_emit = 0.0
        last_n = 0

        def notify(force: bool = False) -> None:
            nonlocal last_emit, last_n
            if not on_chunk or not pieces:
                return
            text = "".join(pieces)
            n = len(text)
            now = time.monotonic()
            if not force and last_n > 0 and now - last_emit < 1.5 and n - last_n < 400:
                return
            last_emit = now
            last_n = n
            on_chunk(text)

        for raw_line in response.iter_lines(decode_unicode=False):
            if raw_line is None:
                continue
            line = _decode_sse_line(raw_line)
            text = line.strip()
            if not text or text.startswith(":"):
                continue
            if text.startswith("event:"):
                continue
            payload_text = text[5:].strip() if text.startswith("data:") else text
            if payload_text == "[DONE]":
                break
            if not payload_text.startswith("{") and not payload_text.startswith("["):
                continue
            try:
                data = json.loads(payload_text)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            self._raise_if_embedded_stream_error(data)
            delta = self._stream_delta_text(data)
            if delta:
                pieces.append(delta)
                notify()
        if not pieces:
            raise LlmError("大模型返回的内容为空")
        notify(force=True)
        return "".join(pieces)

    def _raise_if_embedded_stream_error(self, data: dict[str, Any]) -> None:
        embedded_error = _payload_error_text(data)
        if not embedded_error:
            return
        if looks_like_llm_billing(embedded_error):
            raise LlmBillingError(format_llm_billing_error(upstream=embedded_error, action="对话推理"))
        if looks_like_llm_auth(embedded_error):
            raise LlmAuthError(append_upstream_log("大模型鉴权失败，请检查管理设置中的 API Key。", embedded_error))
        if looks_like_llm_content_filter(embedded_error):
            raise LlmError(append_upstream_log("大模型拒绝了本次内容，请修改后再试。", embedded_error))
        raise LlmError(append_upstream_log("大模型返回错误。", embedded_error))

    @staticmethod
    def _stream_delta_text(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        delta = first.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if content:
                return str(content)
        message = first.get("message")
        if isinstance(message, dict) and message.get("content"):
            return str(message["content"])
        if first.get("text"):
            return str(first["text"])
        return ""

    @staticmethod
    def _thinking_control_fields(model: str) -> dict[str, Any]:
        """DeepSeek V4 默认开启思考，会显著增加 token / 魔粒消耗。

        官方 Chat Completions 需显式传入 thinking.type=disabled；
        Qwen 的 enable_thinking=False 对 V4 无效。
        """
        lowered = (model or "").strip().lower()
        official_aliases = {"deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash", "deepseek-v4-pro"}
        if "deepseek" in lowered and ("v4" in lowered or lowered in official_aliases):
            return {"thinking": {"type": "disabled"}}
        return {}

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """清洗推理模型在 content 中混入的思考过程。

        处理以下已知格式：
        1. <think>…</think> 标签块（Qwen3 / DeepSeek 等）
        2. /think 截断标记（部分平台将 </think> 替换为 /think）
        3. 思考块结束后的空白
        """
        if not text:
            return text

        # 1. 去掉 <think>…</think> 完整块（可能多个，允许跨行）
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)

        # 2. 去掉 /think 截断标记及其之前的所有内容（部分平台格式）
        if "/think" in cleaned.lower():
            parts = re.split(r"/think", cleaned, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                cleaned = parts[1]

        # 3. 去掉未被标签包裹但以「用户提供的是」「我需要」「让我」等中文推理前缀开头的段落
        #    策略：若整体内容以 <think> 开头但没有闭合标签，取最后一个空行之后的部分
        if cleaned.strip().startswith("<think"):
            # 未闭合的思考块，取最后连续非空段落
            paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
            if paragraphs:
                cleaned = paragraphs[-1]

        return cleaned.strip()

    def _extract_response_content(self, data: dict[str, Any]) -> str:
        embedded_error = _payload_error_text(data)
        if looks_like_llm_billing(embedded_error):
            raise LlmBillingError(format_llm_billing_error(upstream=embedded_error, action="对话推理"))

        # 1. 标准 OpenAI 格式: data["choices"][0]["message"]["content"]
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                msg = first_choice.get("message")
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if content and str(content).strip():
                        return str(content).strip()
                    # 兼容深度思考/推理模型 (如 DeepSeek R1)
                    reasoning = msg.get("reasoning_content")
                    if reasoning and str(reasoning).strip():
                        return str(reasoning).strip()
                # 兼容 completions 格式: choices[0]["text"]
                if "text" in first_choice and first_choice["text"]:
                    return str(first_choice["text"]).strip()

        # 2. 阿里云 DashScope / ModelScope 任务格式: data["output"]["text"] 或 data["output"]["choices"]
        output = data.get("output")
        if isinstance(output, dict):
            if "text" in output and output["text"]:
                return str(output["text"]).strip()
            nested_choices = output.get("choices")
            if isinstance(nested_choices, list) and nested_choices:
                first_nc = nested_choices[0]
                if isinstance(first_nc, dict):
                    msg = first_nc.get("message")
                    if isinstance(msg, dict) and msg.get("content"):
                        return str(msg["content"]).strip()
                    if "text" in first_nc and first_nc["text"]:
                        return str(first_nc["text"]).strip()

        # 3. 常见直接返回字段: response, result, content, text, generated_text
        for key in ("response", "result", "content", "text", "generated_text"):
            val = data.get(key)
            if val and isinstance(val, str) and val.strip():
                return val.strip()

        # 4. 如果上游在 HTTP 200 中返回了错误对象
        if embedded_error:
            if looks_like_llm_billing(embedded_error):
                raise LlmBillingError(format_llm_billing_error(upstream=embedded_error, action="对话推理"))
            if looks_like_llm_auth(embedded_error):
                raise LlmAuthError(append_upstream_log("大模型鉴权失败，请检查管理设置中的 API Key。", embedded_error))
            raise LlmError(append_upstream_log("大模型返回错误。", embedded_error))

        # 5. 若无法解析，输出清晰响应摘要以便排查
        data_preview = str(data)[:300]
        raise LlmError(f"大模型响应格式不匹配（未找到 choices 或 output 内容）。返回数据：{data_preview}")

    def test_connection(self, model: str, *, timeout: float = 15.0) -> str:
        available = self.list_models(timeout=min(8.0, timeout))
        if available and model not in available:
            sample = ", ".join(available[:8])
            raise LlmError(
                f"服务已连通，但未找到模型 '{model}'。当前可用：{sample}。"
                "请把模型名称改成与 ollama list / 平台目录完全一致。"
            )
        messages = [
            {"role": "user", "content": "你好，请仅回复两个字：收到。"}
        ]
        try:
            return self.chat_completion(
                messages, model=model, temperature=0.1, max_tokens=8, timeout=timeout,
            )
        except LlmTemporaryError as error:
            if is_llm_timeout_error(error):
                raise LlmTemporaryError(
                    f"大模型在 {int(timeout if not isinstance(timeout, tuple) else timeout[-1])} 秒内没有返回。"
                    "若使用 Ollama，通常是模型正在首次加载进显存；请等 `ollama ps` 显示模型已占用 GPU/内存后再点一次测试。"
                    "若 ComfyUI 正在占满显卡，可先等其空闲。"
                ) from error
            raise

    def speech(
        self,
        *,
        text: str,
        model: str,
        voice: str,
        response_format: str = "mp3",
        timeout: float = 60.0,
    ) -> bytes:
        url = f"{self.base_url}/audio/speech"
        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
        }
        try:
            response = self.session.post(url, headers=self.headers, json=payload, timeout=timeout)
        except requests.exceptions.Timeout as exc:
            raise LlmTemporaryError(f"语音合成超时（等待 {timeout:.0f} 秒仍无响应）：{exc}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise LlmTemporaryError(f"无法连接语音合成服务 {self.base_url}：{exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise LlmTemporaryError(f"请求语音合成服务异常：{exc}") from exc
        if response.status_code >= 400:
            payload: dict[str, Any] | None = None
            try:
                parsed = response.json()
                payload = parsed if isinstance(parsed, dict) else None
            except Exception:
                payload = None
            msg = _payload_error_text(payload) or (response.text or "").strip()[:400] or f"HTTP {response.status_code}"
            raise_llm_http_error(action="语音合成", status=response.status_code, upstream=msg)
        body = response.content or b""
        if not body:
            raise LlmError("语音合成返回了空音频")
        return body

    def optimize_prompt(
        self,
        prompt: str,
        *,
        media_type: str = "video",
        workflow_name: str | None = None,
        skill_id: str | None = None,
        reference_count: int = 0,
        workflow_id: str | None = None,
        model: str,
    ) -> str:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise LlmError("提示词内容不能为空")

        from .llm_minimax_skills import build_h3_system_prompt

        system_instruction = build_h3_system_prompt(
            skill_id=skill_id,
            reference_count=reference_count,
            media_type=media_type,
            workflow_name=workflow_name,
        )
        user_content = f"原始创意需求：{clean_prompt}"
        if workflow_name:
            user_content += f"\n当前工作流名称：{workflow_name}"
        if workflow_id:
            user_content += f"\n当前工作流 ID：{workflow_id}"
        if reference_count > 0:
            user_content += f"\n已上传参考图数量：{reference_count} 张"

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ]
        optimized = self.chat_completion(messages, model=model, temperature=0.7, max_tokens=1536, timeout=60.0)
        # 移除模型可能包裹的 markdown 代码块标签（如 ``` 或 ```markdown ）
        if optimized.startswith("```") and optimized.endswith("```"):
            lines = optimized.splitlines()
            if len(lines) >= 3:
                optimized = "\n".join(lines[1:-1]).strip()
        return optimized

    def analyze_subject(
        self,
        *,
        image_data_url: str,
        kind: str,
        name: str,
        model: str,
    ) -> str:
        if not image_data_url or not image_data_url.startswith("data:image/"):
            raise LlmError("缺少有效的参考图，无法提取外貌特征")
        kind_label = (kind or "主体").strip() or "主体"
        name_label = (name or kind_label).strip() or kind_label
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT_ANALYZE_SUBJECT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"请描述这个{kind_label}（{name_label}）的外观特征。"},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ]
        description = self.chat_completion(messages, model=model, temperature=0.2, max_tokens=256, timeout=60.0)
        if description.startswith("```") and description.endswith("```"):
            lines = description.splitlines()
            if len(lines) >= 3:
                description = "\n".join(lines[1:-1]).strip()
        return description

    def split_script(
        self,
        script: str,
        *,
        shot_count: int = 4,
        style_vibe: str | None = None,
        cast_names: list[str] | None = None,
        model: str,
    ) -> dict[str, Any]:
        clean_script = script.strip()
        if not clean_script:
            raise LlmError("剧本或故事内容不能为空")

        from .llm_minimax_skills import build_h3_split_script_prompt

        system_instruction = build_h3_split_script_prompt()

        user_content = f"待拆解剧本内容：\n{clean_script}\n\n期望镜头数量：{shot_count} 个镜头"
        if style_vibe:
            user_content += f"\n指定整体风格基调：{style_vibe}"
        if cast_names:
            user_content += f"\n已知角色/资产列表：{', '.join(cast_names)}"

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ]
        raw_reply = self.chat_completion(messages, model=model, temperature=0.7, max_tokens=8192, timeout=120.0)
        
        # 解析 JSON
        clean_text = raw_reply.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```", 1)[1].split("```", 1)[0].strip()

        # 尝试查找首个 { 到 最后一个 }
        first_brace = clean_text.find("{")
        last_brace = clean_text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            clean_text = clean_text[first_brace:last_brace + 1]

        import json
        try:
            parsed = json.loads(clean_text)
        except Exception as err:
            # 容错降级：如果大模型没有返回完全合法的 JSON，生成兜底结构
            title_match = clean_script.splitlines()[0][:20] if clean_script else "AI 导演分镜项目"
            return {
                "project_title": title_match,
                "summary": clean_script[:80],
                "shots": [
                    {
                        "shot_number": i + 1,
                        "title": f"分镜 {i + 1}",
                        "prompt": f"电影级场景，{clean_script[:60]}，镜头平稳推进，精致光影细节。",
                        "scale": "WS" if i == 0 else "MS" if i == 1 else "CU",
                        "movement": "zoom_in" if i % 2 == 0 else "pan_right",
                        "angle": "eye_level",
                        "speed": "smooth",
                        "lighting": "cinematic_soft",
                        "sfx": "环境背景音",
                    }
                    for i in range(max(2, min(shot_count, 6)))
                ],
            }

        if not isinstance(parsed, dict) or "shots" not in parsed or not isinstance(parsed["shots"], list):
            raise LlmError("大模型返回的分镜数据格式不正确")

        title_match = str(parsed.get("project_title") or (clean_script.splitlines()[0][:20] if clean_script else "AI 导演分镜项目")).strip()
        summary_match = str(parsed.get("summary") or clean_script[:80]).strip()

        normalized_shots = [
            self._normalize_director_shot(shot, i, clean_script[:60])
            for i, shot in enumerate(parsed["shots"])
            if isinstance(shot, dict)
        ]

        if not normalized_shots:
            raise LlmError("大模型未返回有效的镜头列表")

        return {
            "project_title": title_match or "AI 导演分镜项目",
            "summary": summary_match or "分镜剧本大纲",
            "shots": normalized_shots,
        }

    @staticmethod
    def _normalize_director_shot(shot: dict[str, Any], idx: int, default_prompt_seed: str) -> dict[str, Any]:
        scale_map = {
            "els": "ELS", "大远景": "ELS", "远景": "ELS", "extreme_wide": "ELS", "extreme_wide_shot": "ELS",
            "ws": "WS", "全景": "WS", "wide": "WS", "wide_shot": "WS",
            "ms": "MS", "中景": "MS", "medium": "MS", "medium_shot": "MS", "mid": "MS",
            "cu": "CU", "特写": "CU", "close_up": "CU", "closeup": "CU", "close-up": "CU",
            "ecu": "ECU", "大特写": "ECU", "extreme_close_up": "ECU", "extreme_closeup": "ECU",
        }
        movement_map = {
            "zoom_in": "zoom_in", "前推": "zoom_in", "推近": "zoom_in", "push_in": "zoom_in", "push": "zoom_in", "in": "zoom_in",
            "zoom_out": "zoom_out", "后拉": "zoom_out", "拉远": "zoom_out", "pull_out": "zoom_out", "pull": "zoom_out", "out": "zoom_out",
            "pan_left": "pan_left", "左移": "pan_left", "左摇": "pan_left", "向左": "pan_left",
            "pan_right": "pan_right", "右移": "pan_right", "右摇": "pan_right", "向右": "pan_right",
            "tilt_up": "tilt_up", "仰拍": "tilt_up", "向上": "tilt_up",
            "tilt_down": "tilt_down", "俯拍": "tilt_down", "向下": "tilt_down",
            "orbit": "orbit", "环绕": "orbit", "旋转": "orbit", "360": "orbit",
            "tracking": "tracking", "跟拍": "tracking", "跟随": "tracking", "track": "tracking", "follow": "tracking",
            "static": "static", "定焦": "static", "静止": "static", "固定": "static", "still": "static",
        }
        angle_map = {
            "eye_level": "eye_level", "平视": "eye_level", "视平线": "eye_level", "平拍": "eye_level", "正常": "eye_level",
            "low_angle": "low_angle", "仰角": "low_angle", "低机位": "low_angle", "仰视": "low_angle", "低角度": "low_angle",
            "high_angle": "high_angle", "俯角": "high_angle", "高机位": "high_angle", "俯视": "high_angle", "高角度": "high_angle",
            "dutch": "dutch", "倾斜": "dutch", "荷兰角": "dutch", "斜角": "dutch",
            "pov": "pov", "第一人称": "pov", "主观": "pov", "主观视角": "pov",
        }
        speed_map = {
            "smooth": "smooth", "平稳": "smooth", "电影感": "smooth", "normal": "smooth", "standard": "smooth",
            "dynamic": "dynamic", "快动态": "dynamic", "激烈": "dynamic", "快": "dynamic", "fast": "dynamic", "rapid": "dynamic",
            "slow": "slow", "慢": "slow", "微动": "slow", "柔和": "slow", "gentle": "slow",
        }
        lighting_map = {
            "cinematic_soft": "cinematic_soft", "电影柔光": "cinematic_soft", "柔光": "cinematic_soft", "电影级": "cinematic_soft", "natural": "cinematic_soft",
            "cyberpunk": "cyberpunk", "赛博": "cyberpunk", "赛博朋克": "cyberpunk", "霓虹": "cyberpunk", "neon": "cyberpunk",
            "golden_hour": "golden_hour", "黄金时段": "golden_hour", "日落": "golden_hour", "逆光": "golden_hour", "夕阳": "golden_hour", "sunset": "golden_hour",
            "dramatic_low_key": "dramatic_low_key", "低调": "dramatic_low_key", "暗调": "dramatic_low_key", "悬疑": "dramatic_low_key", "高反差": "dramatic_low_key", "dark": "dramatic_low_key",
            "studio": "studio", "影棚": "studio", "棚拍": "studio", "明亮": "studio", "bright": "studio",
        }

        scale_raw = str(shot.get("scale", "")).lower().strip()
        movement_raw = str(shot.get("movement", "")).lower().strip()
        angle_raw = str(shot.get("angle", "")).lower().strip()
        speed_raw = str(shot.get("speed", "")).lower().strip()
        lighting_raw = str(shot.get("lighting", "")).lower().strip()

        fallback_prompt = f"电影级场景，{default_prompt_seed}，精致光影细节。"
        title_raw = str(shot.get("title") or f"分镜 {idx + 1}").strip()
        prompt_raw = str(shot.get("prompt") or fallback_prompt).strip()

        return {
            "shot_number": int(shot.get("shot_number") or idx + 1),
            "title": title_raw or f"分镜 {idx + 1}",
            "prompt": prompt_raw or fallback_prompt,
            "scale": scale_map.get(scale_raw, "MS"),
            "movement": movement_map.get(movement_raw, "zoom_in"),
            "angle": angle_map.get(angle_raw, "eye_level"),
            "speed": speed_map.get(speed_raw, "smooth"),
            "lighting": lighting_map.get(lighting_raw, "cinematic_soft"),
            "sfx": str(shot.get("sfx") or "").strip(),
        }

