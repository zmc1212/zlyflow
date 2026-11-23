"""用户积分体系服务：计价、预扣、退款、按次扣费与管理员调整。

锚定 100 积分 = 1 元，余额为整数积分。计价来源是 credit_price_rules 表：
- cloud:<mode>      per_second，unit_by_variant 按分辨率/档位单价；
- grs_image:global  per_item，上游 credit_cost × 换算系数（自动跟随上游调价），
  extra_config.model_overrides 可按 provider_model / 工作流 ID 覆盖绝对单价；
- llm:<kind> / vlm:<kind>  per_call 按次扣费。

本地 ComfyUI 工作流计价恒为 0（不扣费不记流水）；所有账号（含 super_admin）一律按价格表结算。
任务采用「提交预扣、失败退款」：任务创建入口提供报价，JobStore 在入队事务内扣费，
退款收口在 JobStore.update_generation（FAILED/CANCELLED 终态同事务全额退回）。
"""

from __future__ import annotations

import math
from typing import Any

from .storage import CreditInsufficientError, JobCreditQuote, JobStore

# LLM/VLM 按次计费种类（price rule key 后缀）；调用方在成功完成后按 kind 扣费。
LLM_BILLING_KINDS = (
    "optimize_prompt",
    "split_script",
    "repair_continuity",
    "director_plan",
    "director_clarify",
    "assistant_chat",
    "music_chat",
)
VLM_BILLING_KINDS = (
    "analyze_subject",
    "reverse_prompt",
)

PRICE_SOURCE_NATIVE = "native"
PRICE_SOURCE_MANUAL = "manual"
BILLING_UNIT_LABELS = {"per_second": "秒", "per_item": "张", "per_call": "次"}
# 平台锚点：100 积分 = 1 元。成本参考与流水中的「≈¥」都按此换算。
CREDIT_PER_YUAN = 100.0
COST_REFERENCE_KEY = "cost_reference"
COST_STATUS_BELOW = "below_cost"
COST_STATUS_THIN = "thin"
COST_STATUS_HEALTHY = "healthy"
COST_STATUS_UNKNOWN = "unknown"
BILLING_MODE_PER_CALL = "per_call"
BILLING_MODE_PER_TOKEN = "per_token"
BILLING_MODES = (BILLING_MODE_PER_CALL, BILLING_MODE_PER_TOKEN)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def price_rule_price_source(rule: dict[str, Any]) -> str:
    """计价来源：native 由原生价×系数换算，manual 直接使用管理端填写的平台单价。"""
    extra = rule.get("extra_config") or {}
    source = str(extra.get("price_source") or "").strip().lower()
    if source in {PRICE_SOURCE_NATIVE, PRICE_SOURCE_MANUAL}:
        return source
    return PRICE_SOURCE_NATIVE if extra.get("native_variant_prices") else PRICE_SOURCE_MANUAL


def native_price_to_credits(native_price: Any, extra: dict[str, Any] | None) -> int:
    """原生单价 → 平台积分：ceil(原生价 × 每原生单位积分 × 供应商系数)。"""
    config = extra or {}
    price = _as_float(native_price)
    per_unit = _as_float(config.get("credits_per_native_unit"))
    coefficient = _as_float(config.get("provider_coefficient"), 1.0)
    if price <= 0 or per_unit <= 0 or coefficient < 0:
        return 0
    # 先收敛浮点误差（0.05×100 会得到 5.000000000000001），再向上取整。
    return max(0, math.ceil(round(price * per_unit * coefficient, 6)))


def resolve_price_rule_units(rule: dict[str, Any]) -> dict[str, int]:
    """解析价格表的实际扣费分档。

    原生价换算是唯一可解释的映射：
    平台单价 = ceil(原生单价 × credits_per_native_unit × provider_coefficient)。
    price_source=manual 时保留 unit_by_variant（运营直接改平台价），不被原生价覆盖。
    """
    stored = {
        str(key): max(0, _as_int(value))
        for key, value in (rule.get("unit_by_variant") or {}).items()
    }
    extra = rule.get("extra_config") or {}
    native_prices = extra.get("native_variant_prices") or {}
    if price_rule_price_source(rule) != PRICE_SOURCE_NATIVE or not native_prices:
        return stored
    per_unit = _as_float(extra.get("credits_per_native_unit"))
    coefficient = _as_float(extra.get("provider_coefficient"), 1.0)
    if per_unit <= 0 or coefficient < 0:
        return stored
    resolved = dict(stored)
    for variant, native_price in native_prices.items():
        price = _as_float(native_price, -1.0)
        if price < 0:
            continue
        resolved[str(variant)] = native_price_to_credits(price, extra)
    return resolved


def billing_summary(pricing_kind: str, units: dict[str, int] | None) -> str | None:
    """下拉/选项展示用的价格摘要，如「5-15 积分/秒」「26 积分/秒」。"""
    values = sorted({max(0, _as_int(value)) for value in (units or {}).values()} - {0})
    if not values:
        return None
    unit_label = BILLING_UNIT_LABELS.get(str(pricing_kind), "次")
    if len(values) == 1:
        return f"{values[0]} 积分/{unit_label}"
    return f"{values[0]}-{values[-1]} 积分/{unit_label}"


def _finite_number(value: Any, default: float = 0.0) -> float:
    """成本参考里的非负数值；非法值按默认值处理，避免一条坏配置影响整张价格表。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number) or number < 0:
        return default
    return number


def normalize_call_usage(usage: Any) -> dict[str, int]:
    """统一 LLM/VLM 用量字段；cached_tokens 不会超过输入 token。"""
    if not isinstance(usage, dict):
        return {}
    prompt = max(0, _as_int(usage.get("prompt_tokens", usage.get("input_tokens"))))
    completion = max(0, _as_int(usage.get("completion_tokens", usage.get("output_tokens"))))
    total = max(0, _as_int(usage.get("total_tokens"))) or prompt + completion
    cached = max(
        0,
        _as_int(
            usage.get("cached_tokens")
            or usage.get("cache_read_input_tokens")
            or usage.get("prompt_cache_hit_tokens")
        ),
    )
    cached = min(cached, prompt)
    if not any((prompt, completion, total, cached)):
        return {}
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
    }


def _cost_reference(rule: dict[str, Any] | None) -> dict[str, Any] | None:
    if not rule:
        return None
    extra = rule.get("extra_config") or {}
    reference = extra.get(COST_REFERENCE_KEY)
    return reference if isinstance(reference, dict) else None


def billing_mode(rule: dict[str, Any] | None) -> str:
    """LLM/VLM 结算方式：per_call（默认，兼容旧配置）或 per_token。"""
    extra = (rule or {}).get("extra_config") or {}
    mode = str(extra.get("billing_mode") or "").strip().lower()
    return mode if mode in BILLING_MODES else BILLING_MODE_PER_CALL


def _model_tier(reference: dict[str, Any], model: str | None) -> dict[str, Any]:
    """按模型取上游 token 单价；支持完整模型名、去 provider 前缀或去版本后缀的简名。"""
    tiers = reference.get("model_prices")
    if not isinstance(tiers, dict) or not tiers:
        return {}
    name = str(model or "").strip()
    candidates = [name] if name else []
    if "/" in name:
        candidates.append(name.rsplit("/", 1)[-1])
    if ":" in name:
        candidates.append(name.rsplit(":", 1)[-1])
    for candidate in candidates:
        tier = tiers.get(candidate)
        if isinstance(tier, dict):
            return tier
    return {}


def _minutes(value: Any) -> int | None:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 24 and 0 <= minute < 60) or hour * 60 + minute > 1440:
        return None
    return hour * 60 + minute


def off_peak_multiplier(reference: dict[str, Any] | None, at: Any = None) -> float:
    """错峰折扣系数；未命中时段返回 1.0。支持跨零点窗口与 IANA 时区。"""
    from datetime import datetime, timezone

    config = (reference or {}).get("off_peak")
    if not isinstance(config, dict) or not config.get("enabled"):
        return 1.0
    windows = config.get("windows")
    if not isinstance(windows, list) or not windows:
        return 1.0
    discount = _finite_number(config.get("discount"), 1.0)
    if not 0 <= discount < 1:
        return 1.0
    zone = None
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(str(config.get("timezone") or "Asia/Shanghai"))
    except Exception:
        zone = timezone.utc
    current = at or datetime.now(timezone.utc)
    if not isinstance(current, datetime):
        return 1.0
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(zone)
    minute = local.hour * 60 + local.minute
    for window in windows:
        if not isinstance(window, dict):
            continue
        start, end = _minutes(window.get("start")), _minutes(window.get("end"))
        if start is None or end is None or start == end:
            continue
        if start < end and start <= minute < end:
            return discount
        if start > end and (minute >= start or minute < end):
            return discount
    return 1.0


def compute_call_cost(
    rule: dict[str, Any] | None, usage: Any = None, *, model: str | None = None, at: Any = None,
) -> dict[str, Any] | None:
    """按成本参考与用量算单次上游成本（元）。

    有真实 usage 时按实际 tokens 计（cost_basis=actual）；否则用管理端填写的
    典型长度估算（cost_basis=estimated）。model 命中 model_prices 时使用该模型
    的上游单价，off_peak 命中时成本按折扣系数下调。
    """
    reference = _cost_reference(rule)
    if reference is None:
        return None
    tier = _model_tier(reference, model)
    merged = {**reference, **tier}
    input_price = _finite_number(merged.get("input_per_mtok"))
    cached_price = _finite_number(merged.get("cached_input_per_mtok"))
    output_price = _finite_number(merged.get("output_per_mtok"))
    if not any((input_price, cached_price, output_price)):
        return None
    coefficient = _finite_number(merged.get("provider_coefficient"), 1.0) or 1.0
    tokens = normalize_call_usage(usage)
    basis = "actual" if tokens else "estimated"
    if not tokens:
        prompt = max(0, _as_int(merged.get("assumed_input_tokens")))
        cached = min(max(0, _as_int(merged.get("assumed_cached_tokens"))), prompt)
        completion = max(0, _as_int(merged.get("assumed_output_tokens")))
        tokens = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cached_tokens": cached,
        }
    # cached 命中部分按缓存价计，其余输入按输入价；缓存价通常比输入价低很多。
    billable_input = max(0, tokens["prompt_tokens"] - tokens["cached_tokens"])
    raw_cost = (
        billable_input * input_price
        + tokens["cached_tokens"] * cached_price
        + tokens["completion_tokens"] * output_price
    ) / 1_000_000
    multiplier = off_peak_multiplier(reference, at)
    cost = raw_cost * multiplier
    return {
        "tokens": tokens,
        "cost_cny": round(cost, 6),
        "raw_cost_cny": round(raw_cost, 6),
        "cost_basis": basis,
        "input_per_mtok": input_price,
        "cached_input_per_mtok": cached_price,
        "output_per_mtok": output_price,
        "provider_coefficient": coefficient,
        "model_tier": bool(tier),
        "off_peak_applied": multiplier < 1,
        "off_peak_multiplier": multiplier,
    }


def _billing_margin(rule: dict[str, Any]) -> float:
    extra = rule.get("extra_config") or {}
    margin = _finite_number(extra.get("billing_margin"), 1.0)
    return margin if margin > 0 else 1.0


def token_charge(
    rule: dict[str, Any], usage: Any = None, *, model: str | None = None, at: Any = None,
    allow_estimated: bool = False,
) -> dict[str, Any] | None:
    """按 token 结算的积分：ceil(成本 × 100 × 加价系数 × 供应商系数)，不低于 min_credits。

    默认要求真实 usage；allow_estimated=True 时用典型用量做预检/管理端预览。
    没有成本参考时返回 None，调用方回退按次单价。
    """
    calculated = compute_call_cost(rule, usage, model=model, at=at)
    if calculated is None:
        return None
    if calculated.get("cost_basis") != "actual" and not allow_estimated:
        return None
    extra = rule.get("extra_config") or {}
    effective_cost = float(calculated["cost_cny"]) * float(calculated["provider_coefficient"])
    credits = math.ceil(round(effective_cost * CREDIT_PER_YUAN * _billing_margin(rule), 6))
    minimum = max(0, _as_int(extra.get("min_credits"), 1))
    return {
        **calculated,
        "credits": max(minimum, credits),
        "billing_margin": _billing_margin(rule),
    }


def billed_call_credits(
    rule: dict[str, Any] | None, usage: Any = None, *, model: str | None = None, at: Any = None,
) -> int:
    """本次调用实际扣减积分；per_token 缺真实用量时回退 unit_credits。"""
    if rule is None or not rule.get("enabled"):
        return 0
    if billing_mode(rule) == BILLING_MODE_PER_TOKEN:
        charged = token_charge(rule, usage, model=model, at=at)
        if charged is not None:
            return int(charged["credits"])
    return max(0, _as_int(rule.get("unit_credits")))


def compute_cost_preview(rule: dict[str, Any]) -> dict[str, Any] | None:
    """价格表管理端用：单次成本、当前扣费、覆盖率与建议积分。"""
    calculated = compute_call_cost(rule)
    if calculated is None:
        return None
    unit = max(0, _as_int(rule.get("unit_credits")))
    cost = float(calculated["cost_cny"])
    billed = unit / CREDIT_PER_YUAN
    coverage = round(billed / cost, 4) if cost > 0 else None
    if coverage is None:
        status = COST_STATUS_UNKNOWN
    elif coverage < 1:
        status = COST_STATUS_BELOW
    elif coverage < 1.2:
        status = COST_STATUS_THIN
    else:
        status = COST_STATUS_HEALTHY
    coefficient = float(calculated["provider_coefficient"])
    suggested = max(0, math.ceil(round(cost * coefficient * CREDIT_PER_YUAN, 6)))
    reference = _cost_reference(rule) or {}
    token_credits = None
    if billing_mode(rule) == BILLING_MODE_PER_TOKEN:
        preview_charge = token_charge(rule, allow_estimated=True)
        token_credits = int(preview_charge["credits"]) if preview_charge is not None else None
    return {
        **calculated,
        "unit_credits": unit,
        "billing_mode": billing_mode(rule),
        "billing_margin": _billing_margin(rule),
        "min_credits": max(0, _as_int((rule.get("extra_config") or {}).get("min_credits"), 1)),
        "model_tier_count": len(reference.get("model_prices") or {}),
        "token_credits": token_credits,
        "billed_cny": round(billed, 6),
        "coverage": coverage,
        "status": status,
        "suggested_unit_credits": suggested,
        "estimated": bool((_cost_reference(rule) or {}).get("estimated", True)),
    }


class CreditService:
    """挂载在 app.state.credits；所有方法依赖 JobStore 完成原子结算。"""

    def __init__(self, store: JobStore) -> None:
        self.store = store

    # ---------------- 计价 ----------------

    def price_rule(self, rule_key: str) -> dict[str, Any] | None:
        rule = self.store.get_credit_price_rule(rule_key)
        if rule is None or not rule.get("enabled"):
            return None
        return rule

    def estimate_job(
        self, mode: str, options: dict[str, Any] | None,
        *, reference_counts: list[int] | None = None,
    ) -> dict[str, Any]:
        """任务应扣积分估算；返回 credits（总额）、unit_credits（单条单价）与流水说明。

        reference_counts 为每个云端任务的输入图片张数（多镜批量按镜头分别计），
        用于在免费额度之外加收输入图片费；不传则不计算该项。
        """
        from .workflow_registry import is_cloud_video_workflow, is_grs_image_workflow, workflow_for

        options = options or {}
        try:
            definition = workflow_for(mode)
        except KeyError:
            return {"credits": 0, "breakdown": "", "price_key": None, "items": 0, "unit_credits": 0}

        if is_cloud_video_workflow(definition.id):
            return self._estimate_cloud_video(definition.id, options, reference_counts)
        if is_grs_image_workflow(definition.id):
            return self._estimate_grs_image(definition.id, options)
        return {"credits": 0, "breakdown": "", "price_key": None, "items": 0, "unit_credits": 0}

    def _estimate_cloud_video(
        self, mode: str, options: dict[str, Any], reference_counts: list[int] | None = None,
    ) -> dict[str, Any]:
        price_key = f"cloud:{mode}"
        rule = self.price_rule(price_key)
        if rule is None:
            return {"credits": 0, "breakdown": "", "price_key": price_key, "items": 1, "unit_credits": 0}
        try:
            duration = int(float(options.get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0
        if duration <= 0:
            duration = self._default_duration(mode)
        variants = resolve_price_rule_units(rule)
        from .workflow_registry import cloud_billing_variant, workflow_for

        # MiniMax 官方按「模型档位:分辨率」分档；其余云端工作流沿用 kling_mode / resolution。
        variant = cloud_billing_variant(mode, options)
        if not variant:
            # 预估兜底：提交前 normalize 会填充 schema 默认档；此处直接读默认档计价。
            variant = self._default_variant(mode)
        unit = self._cloud_variant_unit(variant, variants, rule)
        duration_credits = unit * max(0, duration)
        input_credits, input_count, input_unit = self._input_image_cost(
            rule, mode, options, reference_counts,
        )
        # 上游对参考视频也按输入秒数计费（总费用 = 生成秒数 + 输入视频秒数）；
        # 仅收视频参考的工作流按向上取整秒数计，避免少收。
        input_video_seconds = 0.0
        try:
            input_video_seconds = max(0.0, float(options.get("input_video_seconds") or 0))
        except (TypeError, ValueError):
            input_video_seconds = 0.0
        supports_video_reference = False
        try:
            supports_video_reference = workflow_for(mode).reference_video_limit > 0
        except KeyError:
            supports_video_reference = False
        billed_video_seconds = int(math.ceil(input_video_seconds - 1e-6)) if input_video_seconds > 0 else 0
        input_video_credits = unit * billed_video_seconds if supports_video_reference else 0
        credits = duration_credits + input_credits + input_video_credits
        breakdown = f"云端视频 {duration} 秒"
        if variant:
            breakdown = f"云端视频 {duration} 秒 · {variant}"
        if input_count:
            breakdown = f"{breakdown} + 参考图超出免费额度 {input_count} 张 × {input_unit} 积分"
        if input_video_credits:
            breakdown = f"{breakdown} + 参考视频 {billed_video_seconds} 秒 × {unit} 积分"
        return {
            "credits": credits,
            "breakdown": breakdown,
            "price_key": price_key,
            "items": 1,
            "unit_credits": unit,
            "input_image_credits": input_credits,
            "input_image_count": input_count,
            "input_image_unit_credits": input_unit,
            "input_video_seconds": billed_video_seconds,
            "input_video_credits": input_video_credits,
        }

    @staticmethod
    def _input_image_cost(
        rule: dict[str, Any], mode: str, options: dict[str, Any],
        reference_counts: list[int] | None,
    ) -> tuple[int, int, int]:
        """输入图片费：按每个任务的超免费额度张数 × 档位图片单价。

        免费额度按任务独立计算（如 3 张 × 3 镜 = 0 张计费）；未知模型档位按已配置
        最高图片单价兜底，避免漏收。
        """
        if not reference_counts:
            return 0, 0, 0
        extra = rule.get("extra_config") or {}
        prices = extra.get("input_image_price") or {}
        if not prices:
            return 0, 0, 0
        free_quota = max(0, _as_int(extra.get("input_image_free_quota")))
        billable = sum(max(0, _as_int(count) - free_quota) for count in reference_counts)
        if billable <= 0:
            return 0, 0, 0
        from .workflow_registry import cloud_model_for

        model = cloud_model_for(mode, options) or ""
        native_price = prices.get(model)
        if native_price is None:
            native_price = max((_as_float(value) for value in prices.values()), default=0.0)
        unit = native_price_to_credits(native_price, extra)
        if unit <= 0:
            return 0, 0, 0
        return unit * billable, billable, unit

    @staticmethod
    def _cloud_variant_unit(variant: str, variants: dict[str, int], rule: dict[str, Any]) -> int:
        """按精确档位取价；组合档缺失时按同模型/同分辨率的已有最低价兜底，避免漏价变成免费。"""
        if variant and variant in variants:
            return max(0, _as_int(variants[variant]))
        if variant and ":" in variant:
            model = variant.split(":", 1)[0]
            same_model = [
                max(0, _as_int(value))
                for key, value in variants.items()
                if str(key).startswith(f"{model}:") and _as_int(value) > 0
            ]
            if same_model:
                return min(same_model)
        if variant:
            resolution = variant.split(":", 1)[-1]
            same_resolution = [
                max(0, _as_int(value))
                for key, value in variants.items()
                if str(key).endswith(f":{resolution}") and _as_int(value) > 0
            ]
            if same_resolution:
                return min(same_resolution)
        return max(0, _as_int(rule.get("unit_credits")))

    def _default_variant(self, mode: str) -> str:
        from .workflow_registry import workflow_for

        try:
            definition = workflow_for(mode)
            properties = (definition.option_schema or {}).get("properties", {})
            for key in ("resolution", "kling_mode"):
                schema_def = properties.get(key) or {}
                default = schema_def.get("default")
                if default is not None and str(default).strip():
                    return str(default).strip()
        except (KeyError, TypeError, ValueError):
            pass
        return ""

    def _default_duration(self, mode: str) -> int:
        from .workflow_registry import workflow_for

        try:
            definition = workflow_for(mode)
            duration_schema = (definition.option_schema or {}).get("properties", {}).get("duration") or {}
            return int(duration_schema.get("default") or 0)
        except (KeyError, TypeError, ValueError):
            return 0

    def grs_image_unit_price(self, mode: str, provider_model: str | None = None) -> int:
        """生图模型当前生效的平台积分单价（换算系数或按模型覆盖）；未配置价返回 0（免费口径）。

        /api/modes 展示与预估共用，保证「N 积分/张」兜底展示与实扣一致。
        """
        rule = self.price_rule("grs_image:global")
        if rule is None:
            return 0
        config = rule.get("extra_config") or {}
        overrides = config.get("model_overrides") or {}
        override = overrides.get(str(provider_model or "").strip()) if provider_model else None
        if override is None:
            override = overrides.get(mode)
        if override is not None:
            try:
                return max(0, int(override))
            except (TypeError, ValueError):
                return 0
        upstream = self._grs_upstream_cost(mode)
        try:
            ratio = float(config.get("grs_credits_to_platform") or 0)
        except (TypeError, ValueError):
            ratio = 0.0
        return math.ceil(upstream * ratio) if upstream and ratio > 0 else 0

    def _estimate_grs_image(self, mode: str, options: dict[str, Any]) -> dict[str, Any]:
        price_key = "grs_image:global"
        rule = self.price_rule(price_key)
        if rule is None:
            return {"credits": 0, "breakdown": "", "price_key": price_key, "items": 0, "unit_credits": 0}
        try:
            count = max(1, int(options.get("count") or 1))
        except (TypeError, ValueError):
            count = 1
        provider_model = str(options.get("provider_model") or "").strip()
        unit = self.grs_image_unit_price(mode, provider_model)
        return {
            "credits": unit * count,
            "breakdown": f"生图 {count} 张 × {unit} 积分",
            "price_key": price_key,
            "items": count,
            "unit_credits": unit,
        }

    def _grs_upstream_cost(self, mode: str) -> int | None:
        from .workflow_registry import workflow_for

        record = self.store.get_grs_image_model(mode)
        if record is not None and record.get("credit_cost") is not None:
            return int(record["credit_cost"])
        try:
            definition = workflow_for(mode)
        except KeyError:
            return None
        return definition.credit_cost

    def estimate_call(self, scope: str, kind: str, model: str | None = None) -> int:
        """LLM/VLM 单次调用预检积分；per_token 按典型用量估算，缺成本参考时回退按次价。"""
        rule = self.price_rule(f"{scope}:{kind}")
        if rule is None:
            return 0
        if billing_mode(rule) == BILLING_MODE_PER_TOKEN:
            preview_charge = token_charge(rule, model=model, allow_estimated=True)
            if preview_charge is not None:
                return int(preview_charge["credits"])
        return max(0, int(rule.get("unit_credits") or 0))

    def billing_info(self, mode: str) -> dict[str, Any] | None:
        """/api/modes 展示用计价语义（不做具体估算，精确数值走 estimate 接口）。"""
        from .workflow_registry import is_cloud_video_workflow, is_grs_image_workflow, workflow_for

        try:
            definition = workflow_for(mode)
        except KeyError:
            return None
        rule: dict[str, Any] | None = None
        scope = ""
        if is_cloud_video_workflow(definition.id):
            scope = "cloud_video"
            rule = self.store.get_credit_price_rule(f"cloud:{definition.id}")
        elif is_grs_image_workflow(definition.id):
            scope = "grs_image"
            rule = self.store.get_credit_price_rule("grs_image:global")
        if rule is None:
            return None
        extra = rule.get("extra_config") or {}
        pricing_kind = rule.get("pricing_kind") or ("per_second" if scope == "cloud_video" else "per_item")
        resolved = resolve_price_rule_units(rule)
        return {
            "scope": scope,
            "pricing_kind": pricing_kind,
            "unit_credits": int(rule.get("unit_credits") or 0),
            # unit_by_variant 始终返回实际扣费口径，前端无需理解原生价换算。
            "unit_by_variant": resolved or rule.get("unit_by_variant"),
            "resolved_unit_by_variant": resolved or None,
            "native_unit": extra.get("native_unit"),
            "native_variant_prices": extra.get("native_variant_prices"),
            "credits_per_native_unit": extra.get("credits_per_native_unit"),
            "provider_coefficient": extra.get("provider_coefficient"),
            "input_image_price": extra.get("input_image_price"),
            "input_image_free_quota": extra.get("input_image_free_quota"),
            "price_source": price_rule_price_source(rule),
            "summary": billing_summary(pricing_kind, resolved),
            "enabled": bool(rule.get("enabled")),
        }

    # ---------------- 扣费 / 退款 ----------------

    def quote_job(
        self, user: dict | str, mode: str, options: dict[str, Any], *,
        reference_counts: list[int] | None = None,
    ) -> JobCreditQuote | None:
        """读取当前扣费规则，供存储层在任务事务中预扣。"""
        estimate = self.estimate_job(mode, options, reference_counts=reference_counts)
        cost = int(estimate.get("credits") or 0)
        if cost <= 0:
            return None
        items = max(1, int(estimate.get("items") or 1))
        return JobCreditQuote(cost, cost // items, estimate.get("price_key"), estimate.get("breakdown"))

    def bill_job(
        self, user: dict | str, mode: str, options: dict[str, Any], *,
        job_id: str, reference_counts: list[int] | None = None,
    ) -> dict[str, Any]:
        """在工作台任务表以外创建的云端任务，保留预扣钱包供退款。"""
        quote = self.quote_job(user, mode, options, reference_counts=reference_counts)
        if quote is None:
            return {"total": 0, "per_item": None}
        user_id = user["id"] if isinstance(user, dict) else user
        wallet = self.store.deduct_credits(
            user_id, quote.total, price_key=quote.price_key,
            ref_type="job", ref_id=job_id, reason=quote.reason,
        )
        return {
            "total": quote.total, "per_item": quote.per_item, "price_key": quote.price_key,
            "wallet_enterprise_id": wallet.get("enterprise_id", ""),
        }

    def billing_callback(self, user: dict | str):
        """导演台镜头渲染/批量提交的计价回调。"""
        def billing(
            mode: str, options: dict[str, Any], reference_count: int,
        ) -> JobCreditQuote | None:
            return self.quote_job(user, mode, options, reference_counts=[reference_count])
        return billing

    def refund_deduction(
        self, user_id: str, amount: int, *, price_key: str | None = None,
        job_id: str, reason: str = "任务创建失败，积分退回", wallet_enterprise_id: str | None = None,
    ) -> dict[str, Any]:
        """独立表的云端任务按任务 ID 退回预扣款。"""
        return self.store.refund_credits(
            user_id, amount, reason=reason, price_key=price_key,
            ref_type="job", ref_id=job_id, wallet_enterprise_id=wallet_enterprise_id, once=True,
        )

    def consume_call(
        self, user: dict | str, scope: str, kind: str, *,
        ref_type: str | None = None, ref_id: str | None = None,
        usage: dict[str, Any] | None = None, model: str | None = None,
    ) -> int:
        """LLM/VLM 调用成功后扣费；返回实际扣减（0 = 免费/豁免/未配置价格）。

        per_call 扣 unit_credits；per_token 按真实 usage 算积分，缺 usage 时回退按次。

        预检（require_call_balance）已前置；此处为容忍式扣费——预检后并发把余额
        花完时允许本次记为小额负余额，避免“算力已消耗但用户拿不到结果”。
        企业绑定用户扣企业钱包（store.adjust_credit 按归属路由），并校验企业模型
        访问策略（llm/vlm 能力键）。
        """
        user_id = user["id"] if isinstance(user, dict) else user
        self._ensure_enterprise_call_policy(user_id, scope, kind)
        price_key = f"{scope}:{kind}"
        rule = self.price_rule(price_key)
        if rule is None:
            return 0
        cost = billed_call_credits(rule, usage, model=model)
        if cost <= 0:
            return 0
        meta = self.call_usage_meta(scope, kind, usage=usage, model=model)
        token_billed = bool(meta and meta.get("billing_basis") == "actual_tokens")
        self.store.adjust_credit(
            user_id, -cost, type="consume", price_key=price_key,
            ref_type=ref_type or "llm_call", ref_id=ref_id,
            reason=f"{price_key} {'按 token 结算' if token_billed else '调用一次'}",
            meta=meta,
        )
        return cost

    def call_usage_meta(
        self, scope: str, kind: str, *,
        usage: dict[str, Any] | None = None, model: str | None = None,
    ) -> dict[str, Any] | None:
        """组装单次调用流水明细：模型、tokens、上游成本与计价依据。"""
        meta: dict[str, Any] = {}
        tokens = normalize_call_usage(usage)
        if tokens:
            meta.update(tokens)
        price_key = f"{scope}:{kind}"
        rule = self.price_rule(price_key)
        if rule is not None:
            mode = billing_mode(rule)
            charged = billed_call_credits(rule, usage, model=model)
            calculated = compute_call_cost(rule, usage, model=model)
            meta["billing_mode"] = mode
            meta["unit_credits"] = charged
            if mode == BILLING_MODE_PER_TOKEN and calculated is not None and calculated["cost_basis"] == "actual":
                meta["billing_basis"] = "actual_tokens"
            else:
                meta["billing_basis"] = "per_call"
            if calculated is not None:
                meta.update(calculated["tokens"])
                meta["cost_cny"] = calculated["cost_cny"]
                meta["cost_basis"] = calculated["cost_basis"]
                meta["provider_coefficient"] = calculated["provider_coefficient"]
                meta["model_tier"] = calculated["model_tier"]
                meta["off_peak_applied"] = calculated["off_peak_applied"]
                if calculated["off_peak_applied"]:
                    meta["off_peak_multiplier"] = calculated["off_peak_multiplier"]
            if mode == BILLING_MODE_PER_TOKEN:
                meta["billing_margin"] = _billing_margin(rule)
        if model:
            meta["model"] = str(model)[:200]
        return meta or None

    def require_call_balance(self, user: dict | str, scope: str, kind: str, model: str | None = None) -> None:
        """调用前预检：余额不足以支付单次调用时提前失败，避免先消耗算力再报错。

        企业绑定用户预检企业钱包余额，并校验企业模型访问策略（llm/vlm 能力键）。
        """
        user_id = user["id"] if isinstance(user, dict) else user
        self._ensure_enterprise_call_policy(user_id, scope, kind)
        cost = self.estimate_call(scope, kind, model=model)
        if cost <= 0:
            return
        account = self.store.billing_account_snapshot(user_id)
        if int(account.get("balance") or 0) < cost:
            raise CreditInsufficientError(int(account.get("balance") or 0), cost)
        # 企业成员的分配额度预检：避免先消耗算力、扣费时才发现超额。
        self.store.check_member_quota(user_id, cost)

    def _ensure_enterprise_call_policy(self, user_id: str, scope: str, kind: str) -> None:
        """企业成员的 LLM/VLM 能力访问策略校验；未绑定企业直接放行。"""
        from .enterprise_service import ensure_call_allowed

        ensure_call_allowed(self.store, user_id, scope, kind)

    # ---------------- 管理员 ----------------

    def adjust(
        self, user_id: str, delta: int, *, reason: str, actor_user_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self.store.adjust_personal_credit(
            user_id, delta, reason=reason, actor_user_id=actor_user_id, request_id=request_id,
        )

    def account(self, user_id: str) -> dict[str, Any]:
        return self.store.get_or_create_credit_account(user_id)
