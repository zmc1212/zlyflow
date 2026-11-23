"""供应商 LLM/VLM 价目拉取与积分换算。

设计目标：积分单价不再由人工凭经验填写，而是先取供应商价目，再按
「100 积分 = 1 元 × 加价系数」换算；供应商不提供价格接口时，回退到带
核验日期与来源链接的内置核验价目表，绝不猜测价格。

三类价格来源，按优先级：
1. upstream：供应商 /models 自带 pricing（OpenRouter 等 OpenAI 兼容网关）；
2. builtin：本项目维护的官方刊例价（含 source_url / verified_at）；
3. manual：管理端在价格表里手工填写的 cost_reference（同步逻辑不覆盖）。

金额单位统一为「元 / 百万 tokens」。上游按美元计价时，用 usd_cny 参数折算，
该汇率由调用方传入，不在代码里假定真实汇率。
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

# 100 积分 = 1 元，与 credit_service.CREDIT_PER_YUAN 保持一致。
CREDIT_PER_YUAN = 100

# 免费额度/免费模型的统一口径：三项单价均为 0。
ZERO_PRICE = {"input_per_mtok": 0.0, "cached_input_per_mtok": 0.0, "output_per_mtok": 0.0}


def _entry(
    model: str,
    *,
    providers: tuple[str, ...],
    pattern: str,
    input_per_mtok: float,
    cached_input_per_mtok: float,
    output_per_mtok: float,
    source_url: str,
    verified_at: str,
    note: str,
    off_peak: dict[str, Any] | None = None,
    free: bool = False,
) -> dict[str, Any]:
    return {
        "model": model,
        "providers": providers,
        "pattern": pattern,
        "input_per_mtok": 0.0 if free else input_per_mtok,
        "cached_input_per_mtok": 0.0 if free else cached_input_per_mtok,
        "output_per_mtok": 0.0 if free else output_per_mtok,
        "currency": "CNY",
        "source": "builtin",
        "source_url": source_url,
        "verified_at": verified_at,
        "note": note,
        "free": free,
        "off_peak": off_peak,
    }


# 内置核验价目：只收录能给出处与核验日期的条目；未收录模型明确返回“需手工填写”。
BUILTIN_PRICES: list[dict[str, Any]] = [
    # 阿里云百炼 / DeepSeek 官方：2026-09-10 起执行分时价，空闲为半价。
    # 这里存高峰价（2/0.04/8），off_peak 命中 00:30-08:30 时按 0.5 折算，
    # 两个时段都能覆盖；若只存空闲价，白天会少算一半成本。
    _entry(
        "deepseek-v4.1-flash",
        providers=("dashscope", "deepseek", "custom"),
        pattern=r"deepseek-v4[.-]1-flash(?:-\d{4})?$",
        input_per_mtok=2.0,
        cached_input_per_mtok=0.04,
        output_per_mtok=8.0,
        source_url="https://www.ithome.com/1/000/222.htm",
        verified_at="2026-09-10",
        note="官方分时价：空闲输入 ¥1 / 缓存 ¥0.02 / 输出 ¥4；高峰为 2 倍。",
        off_peak={
            "enabled": True,
            "discount": 0.5,
            "timezone": "Asia/Shanghai",
            "windows": [{"start": "00:30", "end": "08:30"}],
        },
    ),
    _entry(
        "deepseek-v4-flash",
        providers=("dashscope", "deepseek", "custom"),
        pattern=r"deepseek-v4-flash(?:-\d{4})?$",
        input_per_mtok=1.0,
        cached_input_per_mtok=0.02,
        output_per_mtok=2.0,
        source_url="https://business.china.com/industrial/13004644/20260428/49455454.html",
        verified_at="2026-04-26",
        note="官方价：输入 ¥1 / 缓存 ¥0.02 / 输出 ¥2 每百万 tokens。",
    ),
    # 智谱官方刊例（2026-08 上线，GLM-5.3 与 GLM-5.2 同价）。
    _entry(
        "glm-5.3",
        providers=("zhipu",),
        pattern=r"glm-5[.-]3$",
        input_per_mtok=8.0,
        cached_input_per_mtok=8.0,
        output_per_mtok=28.0,
        source_url="https://juejin.cn/post/7706350973791764480",
        verified_at="2026-11-10",
        note="官方刊例输入 ¥8 / 输出 ¥28；缓存读取未单列，按输入价保守计。",
    ),
    _entry(
        "glm-5.3-flash",
        providers=("zhipu",),
        pattern=r"glm-5[.-]3-flash$",
        input_per_mtok=0.8,
        cached_input_per_mtok=0.23,
        output_per_mtok=2.8,
        source_url="https://juejin.cn/post/7706350973791764480",
        verified_at="2026-11-10",
        note="官方标准价 ¥0.8 / 缓存 ¥0.23 / 输出 ¥2.8；限时五折未计入，按刊例计更稳。",
    ),
    _entry(
        "glm-4.5v",
        providers=("zhipu",),
        pattern=r"glm-4[.-]5v$",
        input_per_mtok=2.0,
        cached_input_per_mtok=2.0,
        output_per_mtok=6.0,
        source_url="https://www.jiemian.com/article/13161265.html",
        verified_at="2025-08-11",
        note="官方视觉模型价：输入 ¥2 / 输出 ¥6；缓存未单列，按输入价计。",
    ),
    # 官方免费模型：成本为 0，仅作档位说明；同步时不会写入按 token 规则。
    _entry("glm-4.7-flash", providers=("zhipu",), pattern=r"glm-4[.-]7-flash$",
           input_per_mtok=0, cached_input_per_mtok=0, output_per_mtok=0,
           source_url="https://docs.bigmodel.cn/cn/guide/start/pricing",
           verified_at="2026-10-20", note="智谱官方免费模型。", free=True),
    _entry("glm-4.6v-flash", providers=("zhipu",), pattern=r"glm-4[.-]6v-flash$",
           input_per_mtok=0, cached_input_per_mtok=0, output_per_mtok=0,
           source_url="https://docs.bigmodel.cn/cn/guide/start/pricing",
           verified_at="2026-10-20", note="智谱官方免费视觉模型。", free=True),
    _entry("glm-4v-flash", providers=("zhipu",), pattern=r"glm-4v-flash$",
           input_per_mtok=0, cached_input_per_mtok=0, output_per_mtok=0,
           source_url="https://docs.bigmodel.cn/cn/guide/start/pricing",
           verified_at="2026-10-20", note="智谱官方免费视觉模型。", free=True),
    _entry("conatus-free", providers=("qiniu",), pattern=r"conatus-free$",
           input_per_mtok=0, cached_input_per_mtok=0, output_per_mtok=0,
           source_url="https://qnaigc.com/pricing",
           verified_at="2026-10-20", note="七牛云免费视觉模型。", free=True),
]


def provider_key_for_base_url(base_url: str) -> str:
    """复用模型目录的供应商识别口径，避免两套 host 判断。"""
    try:
        from .llm_client import catalog_provider_key
    except Exception:  # 独立使用本模块做离线换算时不应因导入失败中断
        catalog_provider_key = None
    if catalog_provider_key is not None:
        return catalog_provider_key(base_url)
    host = (urlparse(base_url).hostname or "").lower()
    return "custom" if host else ""


def _model_name_variants(model: str) -> list[str]:
    name = str(model or "").strip()
    if not name:
        return []
    variants = [name, name.lower()]
    short = name.rsplit("/", 1)[-1].lower()
    if short not in variants:
        variants.append(short)
    if ":" in short:
        variants.append(short.rsplit(":", 1)[-1])
    return variants


def _matches(entry: dict[str, Any], model: str) -> bool:
    pattern = str(entry.get("pattern") or "").strip()
    if not pattern:
        return False
    candidates = _model_name_variants(model)
    return any(re.search(pattern, candidate, re.IGNORECASE) for candidate in candidates)


def builtin_price(provider: str, model: str) -> dict[str, Any] | None:
    """按供应商 + 模型匹配内置核验价目；优先精确名，再按正则。"""
    candidates = _model_name_variants(model)
    for entry in BUILTIN_PRICES:
        if provider not in entry["providers"]:
            continue
        if str(entry["model"]).lower() in {candidate.lower() for candidate in candidates}:
            return _public_entry(entry)
    for entry in BUILTIN_PRICES:
        if provider not in entry["providers"]:
            continue
        if _matches(entry, model):
            return _public_entry(entry)
    return None


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """输出给前端的字段，去掉内部 providers/pattern，避免把匹配规则当业务字段。"""
    return {
        "model": entry["model"],
        "input_per_mtok": entry["input_per_mtok"],
        "cached_input_per_mtok": entry["cached_input_per_mtok"],
        "output_per_mtok": entry["output_per_mtok"],
        "currency": entry.get("currency") or "CNY",
        "source": entry.get("source") or "builtin",
        "source_url": entry.get("source_url"),
        "verified_at": entry.get("verified_at"),
        "note": entry.get("note") or "",
        "free": bool(entry.get("free")),
        "off_peak": entry.get("off_peak"),
    }


def _to_number(value: Any) -> float | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if math.isfinite(amount) and amount >= 0 else None


def parse_upstream_prices(
    payload: Any, *, base_url: str, usd_cny: float = 7.2,
) -> list[dict[str, Any]]:
    """解析 /models 响应里自带的 pricing（单价按 token 计）。

    OpenRouter 等网关按美元/ token 返回，折算成元/百万 tokens；供应商若直接
    给人民币，则原样保留。没有 pricing 的条目一律跳过，交给内置价目兜底。
    """
    if isinstance(payload, dict):
        raw_items = payload.get("data")
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = None
    if not isinstance(raw_items, list):
        return []
    host = (urlparse(base_url).hostname or "").lower()
    default_currency = "USD" if "openrouter" in host else "CNY"
    entries: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        pricing = item.get("pricing")
        if not isinstance(pricing, dict):
            continue
        prompt = _to_number(pricing.get("prompt"))
        completion = _to_number(pricing.get("completion"))
        if prompt is None and completion is None:
            continue
        cached = None
        for key in ("input_cache_read", "cache_read", "cached_input", "prompt_cache_read"):
            cached = _to_number(pricing.get(key))
            if cached is not None:
                break
        currency = str(pricing.get("currency") or default_currency).upper()
        factor = usd_cny if currency == "USD" else 1.0
        model = str(item["id"]).strip()
        if not model:
            continue
        input_price = (prompt or 0.0) * 1_000_000 * factor
        output_price = (completion or 0.0) * 1_000_000 * factor
        cached_price = (cached if cached is not None else (prompt or 0.0)) * 1_000_000 * factor
        entries.append({
            "model": model,
            "input_per_mtok": round(input_price, 6),
            "cached_input_per_mtok": round(cached_price, 6),
            "output_per_mtok": round(output_price, 6),
            "currency": "CNY",
            "source": "upstream",
            "source_url": f"{base_url.rstrip('/')}/models",
            "verified_at": date.today().isoformat(),
            "note": (
                f"上游价目按 {currency} 计，已按 1 {currency} = {usd_cny} 元折算"
                if currency == "USD" else "上游 /models 自带价目"
            ),
            "free": input_price == 0 and output_price == 0,
            "off_peak": None,
        })
    return entries


def fetch_upstream_prices(
    base_url: str, api_key: str | None, *, usd_cny: float = 7.2, timeout: float = 10.0,
) -> tuple[list[dict[str, Any]], str | None]:
    """拉取供应商模型目录自带价格；失败时返回空列表 + 人话原因，由调用方回退。"""
    if not base_url:
        return [], "未配置 Base URL"
    try:
        from .llm_client import OpenAICompatibleClient
    except Exception as error:  # pragma: no cover - 正常安装不会走到
        return [], f"价格目录模块不可用：{error}"
    client = OpenAICompatibleClient(base_url=base_url, api_key=api_key or "")
    try:
        response = client.session.get(
            f"{client.base_url}/models", headers=client.headers, timeout=timeout,
        )
    except Exception as error:
        return [], f"拉取供应商模型目录失败：{error}"
    if response.status_code >= 400:
        return [], f"供应商模型目录返回 HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return [], "供应商模型目录返回了无效 JSON"
    entries = parse_upstream_prices(payload, base_url=base_url, usd_cny=usd_cny)
    if not entries:
        return [], "供应商模型目录未返回 token 单价"
    return entries, None


def resolve_price(
    provider: str, model: str, upstream: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """上游精确命中优先，其次内置核验价目；都未命中返回 None（不猜价）。"""
    for entry in upstream or []:
        if str(entry.get("model") or "").lower() == str(model or "").strip().lower():
            return dict(entry)
    return builtin_price(provider, model)


def credits_for_price(amount_per_mtok: float, margin: float) -> int:
    """元/百万 tokens 换算成积分/百万 tokens：ceil(金额 × 100 × 加价系数)。"""
    price = _to_number(amount_per_mtok) or 0.0
    factor = _to_number(margin) or 1.0
    if factor <= 0:
        factor = 1.0
    return max(0, math.ceil(round(price * CREDIT_PER_YUAN * factor, 6)))


def price_to_credits(entry: dict[str, Any], margin: float) -> dict[str, int]:
    return {
        "input_credits_per_mtok": credits_for_price(entry.get("input_per_mtok"), margin),
        "cached_input_credits_per_mtok": credits_for_price(entry.get("cached_input_per_mtok"), margin),
        "output_credits_per_mtok": credits_for_price(entry.get("output_per_mtok"), margin),
    }


def public_price(entry: dict[str, Any], margin: float) -> dict[str, Any]:
    """在价目上附加“换算后的积分单价”，管理端与价格页共用同一口径。"""
    result = dict(entry)
    result.update(price_to_credits(entry, margin))
    return result


def catalog_for_provider(
    provider: str, upstream: list[dict[str, Any]] | None, *, margin: float,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """该供应商可用的价目清单：上游优先、内置补齐，按模型名去重。"""
    merged: dict[str, dict[str, Any]] = {}
    for entry in upstream or []:
        if entry.get("free"):
            continue
        merged[str(entry.get("model") or "").lower()] = public_price(entry, margin)
    for entry in BUILTIN_PRICES:
        if provider not in entry["providers"] or entry.get("free"):
            continue
        key = str(entry["model"]).lower()
        if key in merged:
            continue
        merged[key] = public_price(_public_entry(entry), margin)
    return sorted(merged.values(), key=lambda row: str(row.get("model") or ""))[:limit]


DEFAULT_ASSUMED_TOKENS: dict[str, tuple[int, int, int]] = {
    # 与 storage.py 种子口径一致：输入 / 缓存命中 / 输出（tokens）。
    "optimize_prompt": (1500, 0, 600),
    "split_script": (8000, 0, 3000),
    "repair_continuity": (6000, 0, 2000),
    "director_plan": (120000, 0, 30000),
    "director_clarify": (2000, 0, 400),
    "assistant_chat": (6000, 0, 800),
    "music_chat": (2000, 0, 500),
    "analyze_subject": (2000, 0, 300),
    "reverse_prompt": (2000, 0, 300),
}


def assumed_tokens_for(rule_key: str) -> tuple[int, int, int]:
    kind = str(rule_key or "").split(":", 1)[-1]
    return DEFAULT_ASSUMED_TOKENS.get(kind, (6000, 0, 800))


def build_reference(
    existing: dict[str, Any] | None, entry: dict[str, Any], *, model: str,
) -> dict[str, Any]:
    """生成新的 cost_reference：保留典型用量，替换上游单价并写入模型档位。

    off_peak 只在价目自带分时价时替换；否则保留管理端原有配置，避免误删。
    """
    reference = dict(existing or {})
    if "assumed_input_tokens" not in reference:
        reference["assumed_input_tokens"] = 6000
    if "assumed_output_tokens" not in reference:
        reference["assumed_output_tokens"] = 800
    reference.setdefault("assumed_cached_tokens", 0)
    reference["input_per_mtok"] = entry["input_per_mtok"]
    reference["cached_input_per_mtok"] = entry["cached_input_per_mtok"]
    reference["output_per_mtok"] = entry["output_per_mtok"]
    reference["estimated"] = bool(reference.get("estimated", True))
    reference["reference_source"] = "provider_catalog"
    note_parts = [
        f"{entry.get('source_url') or '供应商价目'}（{entry.get('verified_at') or '未标注核验日期'} 核验）",
        f"输入 ¥{entry['input_per_mtok']:g} / 缓存 ¥{entry['cached_input_per_mtok']:g} / "
        f"输出 ¥{entry['output_per_mtok']:g} 每百万 tokens",
    ]
    if entry.get("note"):
        note_parts.append(str(entry["note"]))
    reference["reference_note"] = "；".join(note_parts)
    tiers = reference.get("model_prices")
    model_prices = dict(tiers) if isinstance(tiers, dict) else {}
    model_prices[model] = {
        "input_per_mtok": entry["input_per_mtok"],
        "cached_input_per_mtok": entry["cached_input_per_mtok"],
        "output_per_mtok": entry["output_per_mtok"],
    }
    reference["model_prices"] = model_prices
    if entry.get("off_peak"):
        reference["off_peak"] = dict(entry["off_peak"])
    elif isinstance(reference.get("off_peak"), dict):
        # 新供应商不是分时价：关闭旧折扣，避免继续按错峰半价低估成本。
        reference["off_peak"] = {**reference["off_peak"], "enabled": False}
    return reference


def plan_rule_sync(
    rule: dict[str, Any], entry: dict[str, Any], *, model: str,
    margin: float, min_credits: int, billing_mode: str,
) -> dict[str, Any]:
    """计算单条价格规则的同步结果：新 extra_config 与按典型用量的兜底单价。

    同时写 unit_credits，既是 per_call 模式的报价，也是 per_token 模式在
    未采集到 usage 时的回退价；不会出现“价格表显示按 token、兜底仍是旧 1 积分”。
    """
    extra = dict(rule.get("extra_config") or {})
    existing = extra.get("cost_reference")
    reference = build_reference(
        existing if isinstance(existing, dict) else None, entry, model=model,
    )
    new_extra = {
        **extra,
        "billing_mode": billing_mode,
        "billing_margin": margin,
        "min_credits": min_credits,
        "cost_reference": reference,
    }
    preview_rule = {**rule, "unit_credits": 0, "extra_config": new_extra}
    from .credit_service import token_charge

    preview = token_charge(preview_rule, allow_estimated=True)
    return {
        "unit_credits": int(preview["credits"]) if preview is not None else 0,
        "extra_config": new_extra,
    }
