"""积分用量/毛利报表：把个人与企业消费流水按维度聚合成运营可读的报表。"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

BEIJING = timezone(timedelta(hours=8))
GROUP_BYS = ("price_key", "model", "user", "enterprise", "day")
ReportGroupBy = Literal["price_key", "model", "user", "enterprise", "day"]
ReportScope = Literal["user", "enterprise", "all"]


def _number(value: Any) -> float | None:
    if type(value) not in {int, float}:
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def resolve_range(
    start: date | None, end: date | None, *, today: date | None = None,
) -> tuple[date, date, str, str]:
    """默认最近 30 天；按北京时间自然日换算成流水使用的 UTC ISO 边界。"""
    end_day = end or today or datetime.now(BEIJING).date()
    start_day = start or (end_day - timedelta(days=29))
    if start_day > end_day:
        raise ValueError("开始日期不能晚于结束日期")
    if (end_day - start_day).days > 365:
        raise ValueError("报表时间范围最多 366 天")
    start_at = datetime.combine(start_day, time.min, tzinfo=BEIJING).astimezone(timezone.utc).isoformat()
    end_at = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=BEIJING).astimezone(timezone.utc).isoformat()
    return start_day, end_day, start_at, end_at


def _day_label(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(BEIJING).date().isoformat()
    except (TypeError, ValueError):
        return "未知日期"


def _group(row: dict[str, Any], group_by: str) -> tuple[str, str]:
    meta = row.get("meta") or {}
    if group_by == "day":
        key = _day_label(row.get("created_at"))
        return key, key
    if group_by == "model":
        model = str(meta.get("model") or "").strip()
        return (model or "未记录模型"), (model or "未记录模型")
    if group_by == "price_key":
        key = str(row.get("price_key") or "").strip() or "未分类"
        return key, key
    if group_by == "user":
        key = str(row.get("user_id") or "").strip() or "未知用户"
        label = str(row.get("display_name") or row.get("username") or key)
        return key, label
    if row.get("scope") == "enterprise":
        key = str(row.get("enterprise_id") or "").strip() or "未知企业"
        return key, str(row.get("enterprise_name") or key)
    return "personal", "个人钱包"


class _Bucket:
    def __init__(self, key: str, label: str) -> None:
        self.key = key
        self.label = label
        self.calls = 0
        self.credits = 0
        self.cost_cny = 0.0
        self.costed_calls = 0
        self.actual_cost_calls = 0
        self.estimated_cost_calls = 0
        self.token_calls = 0
        self.tokens = 0
        self.refunds = 0
        self.refunded_credits = 0

    def consume(self, row: dict[str, Any]) -> None:
        meta = row.get("meta") or {}
        self.calls += 1
        self.credits += abs(int(row.get("delta") or 0))
        cost = _number(meta.get("cost_cny"))
        if cost is not None:
            self.cost_cny += cost
            self.costed_calls += 1
        if meta.get("cost_basis") == "actual":
            self.actual_cost_calls += 1
        elif meta.get("cost_basis") == "estimated":
            self.estimated_cost_calls += 1
        if meta.get("billing_basis") == "actual_tokens":
            self.token_calls += 1
        self.tokens += _int(meta.get("total_tokens")) or (
            _int(meta.get("prompt_tokens")) + _int(meta.get("completion_tokens"))
        )

    def refund(self, row: dict[str, Any]) -> None:
        self.refunds += 1
        self.refunded_credits += _int(row.get("delta"))

    def payload(self) -> dict[str, Any]:
        revenue = self.credits / 100
        net_credits = self.credits - self.refunded_credits
        net_revenue = net_credits / 100
        margin = net_revenue - self.cost_cny
        return {
            "key": self.key,
            "label": self.label,
            "calls": self.calls,
            "credits": self.credits,
            "revenue_cny": round(revenue, 6),
            "cost_cny": round(self.cost_cny, 6),
            "costed_calls": self.costed_calls,
            "uncosted_calls": max(0, self.calls - self.costed_calls),
            "actual_cost_calls": self.actual_cost_calls,
            "estimated_cost_calls": self.estimated_cost_calls,
            "token_calls": self.token_calls,
            "tokens": self.tokens,
            "refunds": self.refunds,
            "refunded_credits": self.refunded_credits,
            "net_credits": net_credits,
            "net_revenue_cny": round(net_revenue, 6),
            "margin_cny": round(margin, 6),
            "margin_rate": round(margin / net_revenue, 6) if net_revenue > 0 else None,
            "coverage": round(revenue / self.cost_cny, 4) if self.cost_cny > 0 else None,
        }


def build_usage_report(
    rows: list[dict[str, Any]], *, start: date, end: date, group_by: str, scope: str,
) -> dict[str, Any]:
    buckets: dict[str, _Bucket] = {}
    totals = _Bucket("all", "全部")
    for row in rows:
        kind = row.get("type")
        if kind not in {"consume", "refund"}:
            continue
        if kind == "consume":
            totals.consume(row)
            key, label = _group(row, group_by)
            buckets.setdefault(key, _Bucket(key, label)).consume(row)
        else:
            totals.refund(row)
            # 退款没有模型/用量明细，只有按价格条目分组时能准确归属。
            if group_by == "price_key":
                key, label = _group(row, group_by)
                buckets.setdefault(key, _Bucket(key, label)).refund(row)
    entries = [bucket.payload() for bucket in buckets.values()]
    if group_by == "day":
        entries.sort(key=lambda item: item["key"])
    else:
        entries.sort(key=lambda item: (-item["credits"], item["label"]))
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "group_by": group_by,
        "scope": scope,
        "totals": totals.payload(),
        "rows": entries,
        "refunds_grouped": group_by == "price_key",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }