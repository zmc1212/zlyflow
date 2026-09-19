"""Write-path and analysis-path vision routing.

Authoring / polish: use the enabled LLM when its name can see images; otherwise
the enabled VLM. Pure-text models (7B) never receive ``image_url``.

Analysis (asset reverse, subject, replication): prefer the VLM page; fall back
to the LLM only when it can see images and VLM is off.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .llm_client import LlmError, OpenAICompatibleClient, is_openai_reasoning_chat_model
from .llm_provider import is_local_base_url, model_supports_vision

VISION_STATUS_USED = "used"
VISION_STATUS_FAILED_TEXT_FALLBACK = "failed_text_fallback"
VISION_STATUS_UNAVAILABLE = "unavailable"
VISION_IMAGE_LIMIT = 8

DecryptFn = Callable[[Any], str | None]


@dataclass(frozen=True)
class VisionEndpoint:
    source: str
    base_url: str
    model: str
    api_key: str
    attach_images: bool


@dataclass(frozen=True)
class VisionCallMeta:
    status: str
    model: str = ""
    image_count: int = 0
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "vision_status": self.status,
            "vision_model": self.model,
            "vision_image_count": self.image_count,
            "vision_source": self.source,
        }


def overlay_vlm_credentials(vlm: dict[str, Any] | None, llm: dict[str, Any] | None) -> dict[str, Any]:
    """Reuse LLM Base URL / Key on the VLM row when the admin toggle is on."""
    row = dict(vlm or {})
    llm_row = dict(llm or {})
    if not row.get("use_llm_credentials"):
        return row
    llm_url = str(llm_row.get("base_url") or "").strip()
    if llm_url:
        row["base_url"] = llm_url
    if llm_row.get("api_key_encrypted"):
        row["api_key_encrypted"] = llm_row.get("api_key_encrypted")
    if llm_row.get("api_key") and not row.get("api_key"):
        row["api_key"] = llm_row.get("api_key")
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
) -> dict[str, Any]:
    if llm_available and model_supports_vision(llm_model):
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
) -> dict[str, Any]:
    if vlm_available:
        return public_vision_route(available=True, model=vlm_model, attach_images=True, source="vlm")
    if llm_available and model_supports_vision(llm_model):
        return public_vision_route(available=True, model=llm_model, attach_images=True, source="llm")
    return public_vision_route(available=False, model=None, attach_images=False, source=None)


def llm_status_vision_fields(
    *,
    llm_available: bool,
    llm_model: str | None,
    vlm_available: bool,
    vlm_model: str | None,
) -> dict[str, Any]:
    authoring = authoring_vision_public(
        llm_available=llm_available,
        llm_model=llm_model,
        vlm_available=vlm_available,
        vlm_model=vlm_model,
    )
    analysis = analysis_vision_public(
        llm_available=llm_available,
        llm_model=llm_model,
        vlm_available=vlm_available,
        vlm_model=vlm_model,
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
) -> VisionEndpoint | None:
    data = dict(row or {})
    if not _row_enabled(data):
        return None
    base_url = str(data.get("base_url") or "").strip().rstrip("/")
    model = str(data.get("model") or "").strip()
    if require_vision and not model_supports_vision(model):
        return None
    api_key = _decrypt_api_key(data, decrypt_fn)
    if not api_key and is_local_base_url(base_url):
        api_key = "ollama"
    if not base_url or not model or not api_key:
        return None
    attach = model_supports_vision(model)
    if require_vision and not attach:
        return None
    return VisionEndpoint(
        source=source,
        base_url=base_url,
        model=model,
        api_key=api_key,
        attach_images=attach,
    )


def resolve_authoring_endpoint(
    llm_row: dict[str, Any] | None,
    vlm_row: dict[str, Any] | None,
    decrypt_fn: DecryptFn | None = None,
) -> VisionEndpoint | None:
    llm = endpoint_from_row("llm", llm_row, decrypt_fn, require_vision=False)
    vlm = endpoint_from_row(
        "vlm",
        overlay_vlm_credentials(vlm_row, llm_row),
        decrypt_fn,
        require_vision=True,
    )
    if llm and model_supports_vision(llm.model):
        return VisionEndpoint(
            source="llm",
            base_url=llm.base_url,
            model=llm.model,
            api_key=llm.api_key,
            attach_images=True,
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
        )
    return None


def resolve_analysis_endpoint(
    llm_row: dict[str, Any] | None,
    vlm_row: dict[str, Any] | None,
    decrypt_fn: DecryptFn | None = None,
) -> VisionEndpoint | None:
    vlm = endpoint_from_row(
        "vlm",
        overlay_vlm_credentials(vlm_row, llm_row),
        decrypt_fn,
        require_vision=True,
    )
    if vlm:
        return vlm
    llm = endpoint_from_row("llm", llm_row, decrypt_fn, require_vision=True)
    if llm:
        return VisionEndpoint(
            source="llm",
            base_url=llm.base_url,
            model=llm.model,
            api_key=llm.api_key,
            attach_images=True,
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
) -> tuple[str, VisionCallMeta]:
    urls = normalize_image_urls(image_urls)
    endpoint = resolve_authoring_endpoint(llm_row, vlm_row, decrypt_fn)
    text_endpoint = resolve_text_endpoint(llm_row, decrypt_fn)
    if endpoint is None and text_endpoint is None:
        raise LlmError("大模型服务尚未启用，请先在管理后台启用大模型服务。")
    wanted_vision = bool(urls) and endpoint is not None and endpoint.attach_images
    if wanted_vision and endpoint is not None:
        try:
            text = chat_on_endpoint(
                endpoint,
                system_prompt,
                user_prompt,
                urls,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            return text, VisionCallMeta(
                status=VISION_STATUS_USED,
                model=endpoint.model,
                image_count=len(urls),
                source=endpoint.source,
            )
        except Exception:
            fallback = text_endpoint or VisionEndpoint(
                source=endpoint.source,
                base_url=endpoint.base_url,
                model=endpoint.model,
                api_key=endpoint.api_key,
                attach_images=False,
            )
            text = chat_on_endpoint(
                fallback,
                system_prompt,
                user_prompt,
                urls,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            return text, VisionCallMeta(
                status=VISION_STATUS_FAILED_TEXT_FALLBACK,
                model=endpoint.model,
                image_count=len(urls),
                source=endpoint.source,
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
    text = chat_on_endpoint(
        fallback,
        system_prompt,
        user_prompt,
        urls,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    return text, VisionCallMeta(
        status=VISION_STATUS_UNAVAILABLE,
        model=fallback.model,
        image_count=len(urls),
        source=fallback.source,
    )
