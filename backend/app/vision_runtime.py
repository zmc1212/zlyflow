"""Write-path and analysis-path vision routing.

Authoring / polish: use the enabled LLM when endpoint-scoped evidence confirms
vision support; otherwise use a verified VLM. Names never authorize images.

Analysis (asset reverse, subject, replication): prefer the VLM page; fall back
to the LLM only when it can see images and VLM is off.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .llm_client import LlmError, OpenAICompatibleClient, is_openai_reasoning_chat_model
from .llm_provider import is_local_base_url
from .vision_capability import row_supports_vision, row_vision_capability, ensure_vision_capability, sanitize_probe_error, unknown_vision_fields

VISION_STATUS_USED = "used"
VISION_STATUS_FAILED_TEXT_FALLBACK = "failed_text_fallback"
VISION_STATUS_UNAVAILABLE = "unavailable"
VISION_IMAGE_LIMIT = 8

VISION_FAILURE_BLOCK = "block"
VISION_FAILURE_WARN_AND_TEXT = "warn_and_text"
VISION_FAILURE_STRATEGIES = (VISION_FAILURE_BLOCK, VISION_FAILURE_WARN_AND_TEXT)

DecryptFn = Callable[[Any], str | None]


@dataclass(frozen=True)
class VisionEndpoint:
    source: str
    base_url: str
    model: str
    api_key: str
    attach_images: bool
    decision_reason: str = ""


@dataclass(frozen=True)
class VisionCallMeta:
    status: str
    model: str = ""
    image_count: int = 0
    source: str | None = None
    requested_model: str | None = None
    fallback_from: str | None = None
    provider_request_id: str | None = None
    usage: dict[str, Any] | None = None
    elapsed_ms: int | None = None
    warning: str | None = None
    decision_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "vision_status": self.status,
            "vision_model": self.model,
            "vision_image_count": self.image_count,
            "vision_source": self.source,
            "requested_model": self.requested_model,
            "actual_model": self.model,
            "status": self.status,
            "fallback": self.fallback_from,
            "request_id": self.provider_request_id,
            "attach_images": self.status == VISION_STATUS_USED,
            "warning": self.warning,
            "decision_reason": self.decision_reason,
        }
        if self.requested_model is not None:
            result["vision_requested_model"] = self.requested_model
        if self.fallback_from is not None:
            result["vision_fallback_from"] = self.fallback_from
        if self.provider_request_id is not None:
            result["vision_request_id"] = self.provider_request_id
        if self.usage is not None:
            result["vision_usage"] = self.usage
        if self.elapsed_ms is not None:
            result["vision_elapsed_ms"] = self.elapsed_ms
        return result


def overlay_vlm_credentials(vlm: dict[str, Any] | None, llm: dict[str, Any] | None) -> dict[str, Any]:
    """Reuse the complete LLM endpoint and its evidence, not a mixed tuple."""
    row = dict(vlm or {})
    llm_row = dict(llm or {})
    if not row.get("use_llm_credentials"):
        return row
    # Never keep a VLM key when the borrowed connection is incomplete.
    row["base_url"] = str(llm_row.get("base_url") or "").strip()
    row["api_key_encrypted"] = llm_row.get("api_key_encrypted")
    row["api_key"] = llm_row.get("api_key")
    row["model"] = str(llm_row.get("model") or "").strip()
    row["profile_id"] = llm_row.get("profile_id")
    for field in (*unknown_vision_fields(), "last_test_status", "last_test_message", "last_test_at"):
        row[field] = llm_row.get(field)
    return row


def public_vision_route(
    *,
    available: bool,
    model: str | None,
    attach_images: bool,
    source: str | None,
) -> dict[str, Any]:
    return {
        "available": bool(available),
        "model": (str(model).strip() or None) if model else None,
        "attach_images": bool(attach_images),
        "source": source,
    }


def authoring_vision_public(
    *,
    llm_available: bool,
    llm_model: str | None,
    vlm_available: bool,
    vlm_model: str | None,
    llm_supports_vision: bool = False,
) -> dict[str, Any]:
    if llm_available and llm_supports_vision:
        return public_vision_route(available=True, model=llm_model, attach_images=True, source="llm")
    if vlm_available:
        return public_vision_route(available=True, model=vlm_model, attach_images=True, source="vlm")
    if llm_available:
        return public_vision_route(available=True, model=llm_model, attach_images=False, source="llm")
    return public_vision_route(available=False, model=None, attach_images=False, source=None)


def analysis_vision_public(
    *,
    llm_available: bool,
    llm_model: str | None,
    vlm_available: bool,
    vlm_model: str | None,
    llm_supports_vision: bool = False,
) -> dict[str, Any]:
    if vlm_available:
        return public_vision_route(available=True, model=vlm_model, attach_images=True, source="vlm")
    if llm_available and llm_supports_vision:
        return public_vision_route(available=True, model=llm_model, attach_images=True, source="llm")
    return public_vision_route(available=False, model=None, attach_images=False, source=None)


def llm_status_vision_fields(
    *,
    llm_available: bool,
    llm_model: str | None,
    vlm_available: bool,
    vlm_model: str | None,
    llm_supports_vision: bool = False,
) -> dict[str, Any]:
    authoring = authoring_vision_public(
        llm_available=llm_available,
        llm_model=llm_model,
        vlm_available=vlm_available,
        vlm_model=vlm_model,
        llm_supports_vision=llm_supports_vision,
    )
    analysis = analysis_vision_public(
        llm_available=llm_available,
        llm_model=llm_model,
        vlm_available=vlm_available,
        vlm_model=vlm_model,
        llm_supports_vision=llm_supports_vision,
    )
    return {
        "supports_vision": bool(authoring.get("attach_images")),
        "authoring_vision": authoring,
        "analysis_vision": analysis,
    }


def normalize_image_urls(urls: list[str] | None, *, limit: int = VISION_IMAGE_LIMIT) -> list[str]:
    seen: list[str] = []
    for raw in urls or []:
        text = str(raw or "").strip()
        if not text.startswith(("http://", "https://", "data:")):
            continue
        if text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def build_user_content(
    text: str,
    image_urls: list[str] | None,
    *,
    attach_images: bool,
) -> str | list[dict[str, Any]]:
    """Attach ``image_url`` only when the chosen model can see pictures.

    7B / other text models get the URLs as plain text so they are never sent a
    multimodal payload they cannot consume.
    """
    urls = normalize_image_urls(image_urls)
    prompt = str(text or "")
    if attach_images and urls:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for url in urls:
            content.append({"type": "image_url", "image_url": {"url": url}})
        return content
    if urls:
        notes = "\n".join(f"- {url}" for url in urls)
        return (
            f"{prompt}\n\n参考图 URL（当前模型不能看图，仅作文字记录，不要假装已经看见画面）：\n{notes}"
        )
    return prompt


def _row_enabled(row: dict[str, Any] | None) -> bool:
    return bool((row or {}).get("enabled"))


def _decrypt_api_key(row: dict[str, Any], decrypt_fn: DecryptFn | None) -> str | None:
    direct = str(row.get("api_key") or "").strip()
    if direct:
        return direct
    encrypted = row.get("api_key_encrypted")
    if encrypted and decrypt_fn:
        try:
            return decrypt_fn(encrypted)
        except Exception:
            return None
    return None


def endpoint_from_row(
    source: str,
    row: dict[str, Any] | None,
    decrypt_fn: DecryptFn | None,
    *,
    require_vision: bool,
    probe_unknown: bool = False,
) -> VisionEndpoint | None:
    data = dict(row or {})
    if not _row_enabled(data):
        return None
    base_url = str(data.get("base_url") or "").strip().rstrip("/")
    model = str(data.get("model") or "").strip()
    # Only fresh evidence for this connection/model/key can authorize images.
    api_key = _decrypt_api_key(data, decrypt_fn)
    if not api_key and is_local_base_url(base_url):
        api_key = "ollama"
    if not base_url or not model or not api_key:
        return None
    if probe_unknown:
        data = ensure_vision_capability(data, api_key)
    attach = row_supports_vision(data)
    if require_vision and not attach:
        return None
    return VisionEndpoint(
        source=source,
        base_url=base_url,
        model=model,
        api_key=api_key,
        attach_images=attach,
        decision_reason=f"{source}: {row_vision_capability(data)} ({data.get('vision_capability_source') or 'unverified'})",
    )


def resolve_authoring_endpoint(
    llm_row: dict[str, Any] | None,
    vlm_row: dict[str, Any] | None,
    decrypt_fn: DecryptFn | None = None,
    *, probe_unknown: bool = False,
) -> VisionEndpoint | None:
    llm = endpoint_from_row("llm", llm_row, decrypt_fn, require_vision=False, probe_unknown=probe_unknown)
    if llm and llm.attach_images:
        return VisionEndpoint(
            source="llm",
            base_url=llm.base_url,
            model=llm.model,
            api_key=llm.api_key,
            attach_images=True,
            decision_reason=llm.decision_reason,
        )
    vlm = endpoint_from_row(
        "vlm",
        overlay_vlm_credentials(vlm_row, llm_row),
        decrypt_fn,
        require_vision=True,
        probe_unknown=probe_unknown,
    )
    if vlm:
        return vlm
    if llm:
        return VisionEndpoint(
            source="llm",
            base_url=llm.base_url,
            model=llm.model,
            api_key=llm.api_key,
            attach_images=False,
            decision_reason=llm.decision_reason,
        )
    return None


def resolve_analysis_endpoint(
    llm_row: dict[str, Any] | None,
    vlm_row: dict[str, Any] | None,
    decrypt_fn: DecryptFn | None = None,
    *, probe_unknown: bool = False,
) -> VisionEndpoint | None:
    vlm = endpoint_from_row(
        "vlm",
        overlay_vlm_credentials(vlm_row, llm_row),
        decrypt_fn,
        require_vision=True,
        probe_unknown=probe_unknown,
    )
    if vlm:
        return vlm
    llm = endpoint_from_row("llm", llm_row, decrypt_fn, require_vision=True, probe_unknown=probe_unknown)
    if llm:
        return VisionEndpoint(
            source="llm",
            base_url=llm.base_url,
            model=llm.model,
            api_key=llm.api_key,
            attach_images=True,
            decision_reason=llm.decision_reason,
        )
    return None


def resolve_text_endpoint(
    llm_row: dict[str, Any] | None,
    decrypt_fn: DecryptFn | None = None,
) -> VisionEndpoint | None:
    llm = endpoint_from_row("llm", llm_row, decrypt_fn, require_vision=False)
    if not llm:
        return None
    return VisionEndpoint(
        source="llm",
        base_url=llm.base_url,
        model=llm.model,
        api_key=llm.api_key,
        attach_images=False,
    )


def chat_on_endpoint(
    endpoint: VisionEndpoint,
    system_prompt: str,
    user_prompt: str,
    image_urls: list[str] | None = None,
    *,
    max_tokens: int = 16000,
    temperature: float = 0.3,
    timeout: float = 240.0,
    reasoning_effort: str | None = "none",
    meta_out: dict[str, Any] | None = None,
) -> str:
    content = build_user_content(
        user_prompt,
        image_urls,
        attach_images=bool(endpoint.attach_images),
    )
    client = OpenAICompatibleClient(base_url=endpoint.base_url, api_key=endpoint.api_key)
    extra: dict[str, Any] = {}
    if is_openai_reasoning_chat_model(endpoint.model) and reasoning_effort:
        extra["reasoning_effort"] = reasoning_effort
    raw = client.chat_completion(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        model=endpoint.model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        stream=True,
        meta_out=meta_out,
        **extra,
    )
    text = str(raw or "").strip()
    if not text:
        raise LlmError("大模型未返回内容")
    return text


def complete_authoring(
    llm_row: dict[str, Any] | None,
    vlm_row: dict[str, Any] | None,
    decrypt_fn: DecryptFn | None,
    system_prompt: str,
    user_prompt: str,
    image_urls: list[str] | None,
    *,
    max_tokens: int = 16000,
    temperature: float = 0.3,
    timeout: float = 240.0,
    on_failure: str = VISION_FAILURE_BLOCK,
) -> tuple[str, VisionCallMeta]:
    if on_failure not in VISION_FAILURE_STRATEGIES:
        raise ValueError(f"未知的带图失败策略：{on_failure}")
    llm_reasoning_effort = str((llm_row or {}).get("reasoning_effort") or "low").strip().lower()

    def effort_for(candidate: VisionEndpoint) -> str | None:
        if candidate.source != "llm":
            return "none"
        return None if llm_reasoning_effort == "auto" else llm_reasoning_effort

    urls = normalize_image_urls(image_urls)
    endpoint = resolve_authoring_endpoint(llm_row, vlm_row, decrypt_fn, probe_unknown=bool(urls))
    text_endpoint = resolve_text_endpoint(llm_row, decrypt_fn)
    if endpoint is None and text_endpoint is None:
        raise LlmError("大模型服务尚未启用，请先在管理后台启用大模型服务。")
    requested = (llm_row or {}).get("model")
    wanted_vision = bool(urls) and endpoint is not None and endpoint.attach_images
    if urls and not wanted_vision and on_failure == VISION_FAILURE_BLOCK:
        raise LlmError("没有已验证可看图的模型；请在管理设置中重新探测视觉能力。复用连接时请确认模型与地址匹配。")
    if wanted_vision and endpoint is not None:
        try:
            call_meta: dict[str, Any] = {}
            text = chat_on_endpoint(
                endpoint,
                system_prompt,
                user_prompt,
                urls,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                reasoning_effort=effort_for(endpoint),
                meta_out=call_meta,
            )
            return text, VisionCallMeta(
                status=VISION_STATUS_USED,
                model=endpoint.model,
                image_count=len(urls),
                source=endpoint.source,
                decision_reason=endpoint.decision_reason,
                requested_model=requested,
                provider_request_id=call_meta.get("provider_request_id"),
                usage=call_meta.get("usage"),
                elapsed_ms=call_meta.get("elapsed_ms"),
            )
        except Exception as exc:
            if on_failure == VISION_FAILURE_BLOCK:
                raise
            fallback = text_endpoint or VisionEndpoint(
                source=endpoint.source,
                base_url=endpoint.base_url,
                model=endpoint.model,
                api_key=endpoint.api_key,
                attach_images=False,
            )
            fallback_meta: dict[str, Any] = {}
            text = chat_on_endpoint(
                fallback,
                system_prompt,
                user_prompt,
                urls,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                reasoning_effort=effort_for(fallback),
                meta_out=fallback_meta,
            )
            return text, VisionCallMeta(
                status=VISION_STATUS_FAILED_TEXT_FALLBACK,
                model=fallback.model,
                image_count=len(urls),
                source=fallback.source,
                requested_model=requested,
                fallback_from=endpoint.model,
                warning="带图调用失败，已明确降级为纯文本：" + sanitize_probe_error(exc, endpoint.api_key),
                provider_request_id=fallback_meta.get("provider_request_id"),
                usage=fallback_meta.get("usage"),
                elapsed_ms=fallback_meta.get("elapsed_ms"),
            )
    fallback = text_endpoint or (
        VisionEndpoint(
            source=endpoint.source,
            base_url=endpoint.base_url,
            model=endpoint.model,
            api_key=endpoint.api_key,
            attach_images=False,
        )
        if endpoint
        else None
    )
    if fallback is None:
        raise LlmError("大模型服务尚未启用，请先在管理后台启用大模型服务。")
    fallback_meta = {}
    text = chat_on_endpoint(
        fallback,
        system_prompt,
        user_prompt,
        urls,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        reasoning_effort=effort_for(fallback),
        meta_out=fallback_meta,
    )
    return text, VisionCallMeta(
        status=VISION_STATUS_UNAVAILABLE,
        model=fallback.model,
        image_count=len(urls),
        source=fallback.source,
        warning="视觉能力不可用，已明确降级为纯文本" if urls else None,
        requested_model=requested,
        provider_request_id=fallback_meta.get("provider_request_id"),
        usage=fallback_meta.get("usage"),
        elapsed_ms=fallback_meta.get("elapsed_ms"),
    )
