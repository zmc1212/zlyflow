"""画布提案校验器：把模型输出的 ops 校验/归一化为可安全执行的方案。

校验是安全网（工作流存在性、参数白名单、连线类型、ref 引用一致性）；
参考槽位数量与最终连线仍由前端在应用时通过既有连线规则二次把关。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .protocol import OpsProposal

# 画布节点输出类型（对齐 frontend/src/canvas/canvas-connections.ts 的 canvasOutputKind）：
# text 节点输出文字，其余按素材类型；generator 输出其媒体类型。
_GENERATOR_MEDIA = {"image", "video"}
# 目标节点可接受的入边来源类型（target ← sources）。
_TARGET_INPUTS: dict[str, set[str]] = {
    "text": {"text", "video", "audio"},
    "audio": {"text", "audio"},
    "generator": {"text", "image", "video", "audio"},
    "image": {"generator"},
    "video": {"generator"},
}

WorkflowLookup = Callable[[str], Any | None]


def _option_schema(definition: Any) -> dict[str, Any]:
    """提取工作流 options 参数的 properties（无则视为无可调参数）。"""
    try:
        parameters = definition.payload().get("parameters") or []
    except Exception:
        return {}
    for entry in parameters:
        if entry.get("name") == "options":
            schema = entry.get("schema") or {}
            return schema.get("properties") or {}
    return {}


def _validate_option_values(definition: Any, values: dict[str, Any]) -> dict[str, Any]:
    """只放行 primary/advanced 用户参数；internal 参数由工作台托管。"""
    schema = _option_schema(definition)
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        prop = schema.get(key)
        if prop is None:
            raise ValueError(f"工作流 {definition.id} 没有参数「{key}」，请只使用 workflow_catalog 列出的参数名")
        if prop.get("ui_group") == "internal":
            raise ValueError(f"参数「{key}」由工作台托管（internal），提案中不能指定")
        expected = str(prop.get("type") or "string")
        if isinstance(value, bool):
            actual = "boolean"
        elif isinstance(value, (int, float)):
            actual = "number"
        elif isinstance(value, str):
            actual = "string"
        else:
            actual = "object"
        if expected == "boolean" and actual != "boolean":
            raise ValueError(f"参数「{key}」需要布尔值")
        if expected == "number" and actual != "number":
            raise ValueError(f"参数「{key}」需要数字")
        if expected == "string" and actual != "string":
            raise ValueError(f"参数「{key}」需要字符串")
        choices = prop.get("ui_options") or []
        if choices and expected == "string":
            allowed = [str(item.get("value") if isinstance(item, dict) else item) for item in choices]
            if str(value) not in allowed:
                raise ValueError(f"参数「{key}」的可选值为：{'、'.join(allowed)}")
        low = prop.get("min")
        high = prop.get("max")
        if actual == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            if low is not None and value < low:
                raise ValueError(f"参数「{key}」不能小于 {low}")
            if high is not None and value > high:
                raise ValueError(f"参数「{key}」不能大于 {high}")
        normalized[key] = value
    return normalized


def _connection_error(source_kind: str | None, target_kind: str) -> str | None:
    if source_kind is None:
        return f"来源节点的类型「{source_kind}」不能作为连线起点"
    if source_kind not in _TARGET_INPUTS.get(target_kind, set()):
        return f"「{source_kind}」不能连到「{target_kind}」类型节点（连线规则与画布一致）"
    return None


class CanvasActions:
    def __init__(self, repo: Any, workflow_lookup: WorkflowLookup):
        self.repo = repo
        self.workflow_lookup = workflow_lookup

    # ------------------------------------------------------------------ 校验

    def validate_ops(self, ops: list[Any], content: dict[str, Any]) -> tuple[list[dict], dict]:
        """逐条校验 ops 并返回归一化结果与摘要。

        ref 解析规则：已在提案中创建的临时 ref（n1/n2…）或画布已有节点真实 ID，
        必须先定义后引用；锚点 position 指向的 ref 亦同。
        """
        nodes = content.get("nodes") if isinstance(content, dict) else None
        existing: dict[str, dict] = {}
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            data = node.get("data") or {}
            existing[str(node.get("id"))] = {
                "kind": str(node.get("type") or "unknown"),
                "media_kind": str(data.get("mediaKind") or "") or None,
                "workflow_id": str(data.get("workflowId") or "") or None,
            }
        known: dict[str, dict] = {ref: dict(info) for ref, info in existing.items()}
        normalized: list[dict] = []
        counts: dict[str, int] = {}
        credit_estimate = 0
        created_refs: set[str] = set()
        deleted_refs: set[str] = set()
        for index, op in enumerate(ops, start=1):
            payload = op.model_dump()
            op_type = payload["op"]
            counts[op_type] = counts.get(op_type, 0) + 1
            if op_type == "create_text":
                text = str(payload.get("text") or "")
                payload["label"] = str(payload.get("label") or (text[:24] if text else "文字节点"))[:160]
                payload["text"] = text
                payload["position"] = payload.get("position") or "new"
                known[op.ref] = {"kind": "text", "media_kind": None, "workflow_id": None}
                created_refs.add(op.ref)
            elif op_type == "create_generator":
                definition = self.workflow_lookup(str(payload.get("workflow_id") or ""))
                if definition is None:
                    raise ValueError(f"工作流「{payload.get('workflow_id')}」不存在或已停用，请先调用 workflow_catalog 获取有效 ID")
                media_type = str(getattr(definition, "media_type", "") or "video")
                if media_type not in _GENERATOR_MEDIA:
                    raise ValueError(f"工作流「{definition.id}」是 {media_type} 工作流，画布生成器只支持图片/视频工作流")
                media_kind = payload.get("media_kind") or media_type
                if media_kind != media_type:
                    raise ValueError(f"工作流「{definition.id}」的媒体类型是 {media_type}，与声明的 media_kind 不符")
                payload["media_kind"] = media_kind
                payload["option_values"] = _validate_option_values(definition, dict(payload.get("option_values") or {}))
                payload["workflow_name"] = str(getattr(definition, "name", "") or definition.id)[:160]
                payload["workflow_id"] = definition.id
                payload["position"] = payload.get("position") or "new"
                for ref in payload.get("connect_from") or []:
                    source = known.get(str(ref))
                    if source is None:
                        raise ValueError(f"connect_from 里的「{ref}」既不在提案中创建，也不是画布已有节点")
                    source_kind = source["kind"] if source["kind"] != "generator" else (source.get("media_kind") or "image")
                    error = _connection_error(source_kind, "generator")
                    if error:
                        raise ValueError(f"connect_from {ref}→{op.ref}：{error}")
                known[op.ref] = {"kind": "generator", "media_kind": media_kind, "workflow_id": definition.id}
                created_refs.add(op.ref)
            elif op_type == "connect":
                source_ref = str(payload.get("source_ref") or "")
                target_ref = str(payload.get("target_ref") or "")
                source, target = known.get(source_ref), known.get(target_ref)
                if source is None:
                    raise ValueError(f"connect 的 source_ref「{source_ref}」既不在提案中创建，也不是画布已有节点")
                if target is None:
                    raise ValueError(f"connect 的 target_ref「{target_ref}」既不在提案中创建，也不是画布已有节点")
                source_kind = source["kind"] if source["kind"] != "generator" else (source.get("media_kind") or "image")
                # 文字生成器（生成器节点带提示词）也可作为提示词来源，交给前端
                # canvasPromptEligible 精判；后端只拦明显类型冲突。
                error = _connection_error(source_kind, target["kind"])
                if error:
                    raise ValueError(f"connect {source_ref}→{target_ref}：{error}")
                payload["source_ref"], payload["target_ref"] = source_ref, target_ref
            elif op_type == "update_generator":
                target = known.get(op.ref)
                if target is None:
                    raise ValueError(f"update_generator 的「{op.ref}」既不在提案中创建，也不是画布已有节点")
                if target["kind"] != "generator":
                    raise ValueError(f"「{op.ref}」不是生成器节点，无法更新生成参数")
                if payload.get("workflow_id"):
                    definition = self.workflow_lookup(str(payload["workflow_id"]))
                    if definition is None:
                        raise ValueError(f"工作流「{payload['workflow_id']}」不存在或已停用")
                    payload["workflow_id"] = definition.id
                    payload["workflow_name"] = str(getattr(definition, "name", "") or definition.id)[:160]
                if payload.get("option_values"):
                    definition = self.workflow_lookup(payload.get("workflow_id") or target.get("workflow_id") or "")
                    if definition is not None:
                        payload["option_values"] = _validate_option_values(definition, dict(payload["option_values"]))
            elif op_type == "submit":
                target = known.get(op.ref)
                if target is None:
                    raise ValueError(f"submit 的「{op.ref}」既不在提案中创建，也不是画布已有节点")
                if target["kind"] != "generator":
                    raise ValueError(f"「{op.ref}」不是生成器节点，无法提交生成任务")
                definition = self.workflow_lookup(target.get("workflow_id") or "")
                if definition is not None:
                    cost = getattr(definition, "credit_cost", None)
                    if isinstance(cost, int):
                        credit_estimate += cost
            elif op_type == "insert_library_item":
                item = dict(payload.get("item") or {})
                kind = str(item.get("kind") or "")
                payload["item"] = {key: item.get(key) for key in (
                    "job_id", "generation_item_id", "output_index", "kind", "label",
                    "prompt", "job_title", "download_url", "url", "path", "delivery_status",
                    "width", "height", "created_at",
                ) if item.get(key) is not None}
                known[op.ref] = {"kind": kind, "media_kind": kind, "workflow_id": None}
                created_refs.add(op.ref)
                if payload.get("as_reference_of"):
                    anchor = known.get(str(payload["as_reference_of"]))
                    if anchor is None:
                        raise ValueError(f"as_reference_of 指向的「{payload['as_reference_of']}」不存在")
                    if anchor["kind"] != "generator":
                        raise ValueError("素材只能作为生成器的参考图插入")
            elif op_type == "update_text":
                # 修改画布已有文字节点：同提案新建又更新是冗余操作（直接在 create_text 写最终内容）。
                if op.ref in created_refs:
                    raise ValueError(f"「{op.ref}」是本提案新建的节点，请直接在 create_text 中写最终内容，不要新建后再更新")
                target = existing.get(op.ref)
                if target is None:
                    raise ValueError(f"update_text 的「{op.ref}」不是画布上的节点，请先 canvas_read 获取真实节点 ID")
                if target["kind"] != "text":
                    raise ValueError(f"「{op.ref}」不是文字节点，无法更新文字内容")
            elif op_type == "delete_node":
                # 只能删除画布已有节点：提案内新建又删除是矛盾操作；同一提案内不能重复删除。
                if op.ref in created_refs:
                    raise ValueError(f"「{op.ref}」是本提案新建的节点，不能在同一提案里删除；请直接从提案中移除该项")
                target = existing.get(op.ref)
                if target is None:
                    raise ValueError(f"delete_node 的「{op.ref}」不是画布上的节点，请先 canvas_read 获取真实节点 ID")
                if op.ref in deleted_refs:
                    raise ValueError(f"「{op.ref}」在本提案中已被删除，不能重复删除")
                deleted_refs.add(op.ref)
                known.pop(op.ref, None)
            position = payload.get("position")
            if position and ":" in str(position):
                anchor = known.get(str(position).split(":", 1)[1])
                if anchor is None:
                    raise ValueError(f"position 锚点「{position}」指向的节点不存在")
            payload["op_index"] = index
            normalized.append(payload)
        summary = {"counts": counts, "total": len(normalized), "credit_estimate": credit_estimate or None}
        return normalized, summary

    # ------------------------------------------------------------------ 提案

    def propose_ops(self, owner: str, session: dict, run: dict, args: dict, canvas_content: dict[str, Any]) -> dict:
        proposal = OpsProposal.model_validate(args)
        normalized, summary = self.validate_ops(proposal.ops, canvas_content)
        record = self.repo.insert(owner, "proposal", {
            "canvas_id": session.get("canvas_id"),
            "title": proposal.title,
            "ops": normalized,
            "summary": summary,
            "run_id": run["id"],
        }, parent=session["id"], status="awaiting_approval")
        return record

    def apply_result(self, owner: str, proposal_id: str, result: str, detail: dict | None = None) -> dict:
        if result not in {"applied", "partial", "failed", "dismissed"}:
            raise ValueError("无效的应用结果")
        proposal = self.repo.get(owner, proposal_id, "proposal")
        if proposal["status"] != "awaiting_approval":
            raise ValueError("该提案已处理过，无需重复上报")
        return self.repo.update(owner, proposal, {"apply_result": dict(detail or {})}, status=result)


def parse_canvas_content(content: str | None) -> dict[str, Any]:
    """安全解析画布草稿 JSON；空/坏内容按空画布处理。"""
    if not content:
        return {}
    try:
        data = json.loads(content)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
