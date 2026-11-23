"""企业管理域服务：企业模型访问策略与策略目录。

企业是平台的结算与管控单元：
- 成员归属：users.enterprise_id 绑定企业，绑定期间个人钱包不参与计费（企业钱包结算）；
- 模型访问策略：按四类开放——video（视频工作流）/ image（生图工作流）/ llm（大语言能力）/
  vlm（视觉理解能力）。mode = all（全部开放）/ whitelist（仅开放 models 清单）/ none（全部关闭）。
  未配置的类型默认 all（不限制），与既有行为兼容。
- 校验收口：视频/生图任务提交走 ensure_mode_allowed（submit_generation 与导演台
  create_queued_job 两个统一入口），LLM/VLM 调用走 ensure_call_allowed
  （CreditService.require_call_balance / consume_call 统一触发）。

EnterpriseModelForbiddenError 由 main.py 全局异常处理器转换为 403。
"""

from __future__ import annotations

from typing import Any

MODEL_KINDS = ("video", "image", "llm", "vlm")
POLICY_MODES = ("all", "whitelist", "none")

MODEL_KIND_LABELS = {
    "video": "视频模型",
    "image": "生图模型",
    "llm": "大语言模型",
    "vlm": "视觉理解模型",
}

# LLM/VLM 能力键 → 管理端展示文案（与 credit_service.LLM_BILLING_KINDS / VLM_BILLING_KINDS 对齐）
LLM_FEATURE_LABELS = {
    "optimize_prompt": "提示词优化",
    "split_script": "剧本拆解",
    "repair_continuity": "连贯性修复",
    "director_plan": "导演台写稿",
    "director_clarify": "导演台创作确认",
    "assistant_chat": "导演助手对话",
    "music_chat": "音乐对话",
}
VLM_FEATURE_LABELS = {
    "analyze_subject": "主体分析（看图）",
    "reverse_prompt": "图片反推提示词",
}

POLICY_MODE_LABELS = {
    "all": "全部开放",
    "whitelist": "仅开放选中",
    "none": "全部关闭",
}


class EnterpriseModelForbiddenError(Exception):
    """企业模型策略禁止当前操作；main.py 全局异常处理器转换为 403。"""

    def __init__(self, message: str, *, kind: str, model_key: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.model_key = model_key


def user_enterprise_id(store: Any, user_id: str | None) -> str | None:
    """用户当前绑定的企业 ID；未绑定或纯 JobStore 环境返回 None。"""
    if not user_id:
        return None
    getter = getattr(store, "get_user_enterprise_id", None)
    if getter is None:
        return None
    return getter(user_id)


def policies_map(store: Any, enterprise_id: str) -> dict[str, dict[str, Any]]:
    """归一化后的企业策略表：缺失类型补 all（不限制）。"""
    raw = store.get_enterprise_model_policies(enterprise_id)
    policies: dict[str, dict[str, Any]] = {}
    for kind in MODEL_KINDS:
        entry = raw.get(kind) or {}
        mode = str(entry.get("mode") or "all")
        if mode not in POLICY_MODES:
            mode = "all"
        models = entry.get("models") or []
        policies[kind] = {"mode": mode, "models": [str(key) for key in models]}
    return policies


def user_policies(store: Any, user_id: str | None) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """一次性取回用户企业绑定与策略表；未绑定企业返回 (None, {})。"""
    enterprise_id = user_enterprise_id(store, user_id)
    if not enterprise_id:
        return None, {}
    return enterprise_id, policies_map(store, enterprise_id)


def policy_allows(policy: dict[str, Any], key: str) -> bool:
    mode = policy.get("mode") or "all"
    if mode == "all":
        return True
    if mode == "none":
        return False
    return key in set(policy.get("models") or [])


def workflow_policy_kind(definition: Any) -> str:
    """工作流 → 策略类型：图片工作流归 image，其余（视频/视频工具）归 video。"""
    return "image" if getattr(definition, "media_type", "") == "image" else "video"


def mode_allowed(store: Any, user_id: str | None, mode: str) -> bool:
    """企业用户是否允许使用该工作流；未绑定企业恒为 True。"""
    enterprise_id, policies = user_policies(store, user_id)
    if not enterprise_id:
        return True
    from .workflow_registry import workflow_for

    try:
        definition = workflow_for(mode)
    except KeyError:
        return True  # 未知工作流交给上游 404 逻辑
    return policy_allows(policies.get(workflow_policy_kind(definition)) or {}, definition.id)


def ensure_mode_allowed(store: Any, user_id: str | None, mode: str) -> None:
    enterprise_id, policies = user_policies(store, user_id)
    if not enterprise_id:
        return
    from .workflow_registry import workflow_for

    try:
        definition = workflow_for(mode)
    except KeyError:
        return
    kind = workflow_policy_kind(definition)
    policy = policies.get(kind) or {"mode": "all", "models": []}
    if policy_allows(policy, definition.id):
        return
    if policy["mode"] == "none":
        raise EnterpriseModelForbiddenError(
            f"当前企业未开放{MODEL_KIND_LABELS.get(kind, kind)}能力，无法使用「{definition.name}」",
            kind=kind, model_key=definition.id,
        )
    raise EnterpriseModelForbiddenError(
        f"当前企业未开放模型「{definition.name}」，仅开放企业管理员勾选的{MODEL_KIND_LABELS.get(kind, kind)}",
        kind=kind, model_key=definition.id,
    )


def call_allowed(store: Any, user_id: str | None, scope: str, kind: str) -> bool:
    """企业用户是否允许本次 LLM/VLM 能力调用（scope = llm / vlm）。"""
    enterprise_id, policies = user_policies(store, user_id)
    if not enterprise_id:
        return True
    policy = policies.get(scope) or {"mode": "all", "models": []}
    return policy_allows(policy, kind)


def ensure_call_allowed(store: Any, user_id: str | None, scope: str, kind: str) -> None:
    enterprise_id, policies = user_policies(store, user_id)
    if not enterprise_id:
        return
    policy = policies.get(scope) or {"mode": "all", "models": []}
    if policy_allows(policy, kind):
        return
    labels = LLM_FEATURE_LABELS if scope == "llm" else VLM_FEATURE_LABELS
    kind_label = labels.get(kind, kind)
    scope_label = MODEL_KIND_LABELS.get(scope, scope)
    if policy["mode"] == "none":
        raise EnterpriseModelForbiddenError(
            f"当前企业未开放{scope_label}能力，无法使用「{kind_label}」",
            kind=scope, model_key=kind,
        )
    raise EnterpriseModelForbiddenError(
        f"当前企业未开放能力「{kind_label}」，仅开放企业管理员勾选的{scope_label}",
        kind=scope, model_key=kind,
    )


def filter_workflow_definitions(store: Any, user_id: str | None, definitions: list[Any]) -> list[Any]:
    """按企业模型策略过滤工作流目录（/api/modes 展示层过滤；提交层另有强制校验）。"""
    enterprise_id, policies = user_policies(store, user_id)
    if not enterprise_id:
        return list(definitions)
    result = []
    for definition in definitions:
        policy = policies.get(workflow_policy_kind(definition)) or {"mode": "all", "models": []}
        if policy_allows(policy, definition.id):
            result.append(definition)
    return result


def policy_catalog() -> dict[str, list[dict[str, str]]]:
    """管理端模型清单：各策略类型下可勾选的模型/能力键与展示名。"""
    from .credit_service import LLM_BILLING_KINDS, VLM_BILLING_KINDS
    from .workflow_registry import WORKFLOWS

    video, image = [], []
    for definition in WORKFLOWS:
        entry = {"key": definition.id, "label": definition.name}
        (image if workflow_policy_kind(definition) == "image" else video).append(entry)
    return {
        "video": video,
        "image": image,
        "llm": [
            {"key": kind, "label": LLM_FEATURE_LABELS.get(kind, kind)}
            for kind in LLM_BILLING_KINDS
        ],
        "vlm": [
            {"key": kind, "label": VLM_FEATURE_LABELS.get(kind, kind)}
            for kind in VLM_BILLING_KINDS
        ],
    }


def normalize_policies_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """校验管理端提交的策略载荷（结构校验；键级合法性由 store 落库时再校验）。"""
    if not isinstance(items, list):
        raise ValueError("policies 必须为数组")
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("policies 项必须为对象")
        kind = str(item.get("model_kind") or "").strip()
        mode = str(item.get("mode") or "").strip()
        if kind not in MODEL_KINDS:
            raise ValueError(f"未知的模型类型：{kind or '(空)'}")
        if mode not in POLICY_MODES:
            raise ValueError(f"未知的开放模式：{mode or '(空)'}")
        models = item.get("models") or []
        if not isinstance(models, list):
            raise ValueError("models 必须为数组")
        normalized.append({
            "model_kind": kind,
            "mode": mode,
            "models": [str(key).strip() for key in models if str(key).strip()],
        })
    return normalized
