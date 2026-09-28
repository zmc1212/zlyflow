"""Optional, single-call semantic review. Originals never become mutable working copies."""
from copy import deepcopy
from difflib import unified_diff
import json
from pathlib import Path
import time

from . import workshop_contract as contract
from .workshop_direct_input import sha
from .workshop_h3_skill import split_complete_group_draft
from .llm_service import LlmService

VERSION = "h3-dialogue-review-v1"
SKILL_PATH = Path(__file__).resolve().parents[4] / "skills/h3-dialogue-review/SKILL.md"


def public_evidence(value):
    """Polling exposes image hashes, never repeatedly transfers frozen Base64."""
    if isinstance(value, dict):
        return {key: public_evidence(item) for key, item in value.items() if key != "frozen_images"}
    if isinstance(value, list):
        return [public_evidence(item) for item in value]
    return value


def configuration(author):
    from .workshop_h3_skill import writing_author
    chosen = writing_author(author)
    return {"version": VERSION, "system": SKILL_PATH.read_bytes().decode("utf-8"),
            "author": {k: chosen[k] for k in ("profile_id", "base_url", "model", "reasoning_effort", "supports_vision")}}


def parse_response(raw, original):
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("decision") not in {"unchanged", "revised", "needs_user_resolution"}:
        raise ValueError("审校响应缺少有效 decision")
    for key, fields in (("issues", ("location", "type", "certainty", "evidence", "reason", "suggestion")),
                        ("changes", ("location", "reason", "before", "after"))):
        if not isinstance(value.get(key), list) or any(not isinstance(row, dict) or any(not isinstance(row.get(f), str) or not row[f].strip() for f in fields) for row in value[key]):
            raise ValueError("审校响应字段不完整：" + key)
    if any(row["certainty"] not in {"conflict", "risk"} for row in value["issues"]):
        raise ValueError("审校问题必须区分确定冲突与推测风险")
    final = value.get("final_prompt")
    if final is not None and not isinstance(final, str):
        raise ValueError("审校稿必须是文本或 null")
    if value["decision"] == "unchanged" and (final != original or value["changes"]):
        raise ValueError("无需修改结论与原稿不一致")
    if value["decision"] == "revised" and (not final or final == original or not value["issues"] or not value["changes"]):
        raise ValueError("修改结论缺少完整稿或修改证据")
    if value["decision"] == "needs_user_resolution" and not value["issues"]:
        raise ValueError("需用户处理结论缺少具体问题")
    return value


def validate_draft(raw, payload, group):
    plan = payload["base_plan"]
    ordered = [next(b for b in payload["beats"] if b["id"] == bid) for bid in group["beat_ids"]]
    parsed = split_complete_group_draft(raw, ordered, group=group)
    version = payload["authoring"]["contracts"][group["id"]]["version"]
    effective = {**group, "common_prompt": parsed["common_prompt"], "contract_version": version}
    errors = ["违反显式锁定的公共设定：" + line for line in group.get("locked_common_lines", []) if line not in parsed["common_prompt"]]
    if not parsed["common_prompt"].strip():
        errors.append("完整稿缺少公共设定")
    candidates = {}
    for beat, body in zip(ordered, parsed["shots"]):
        errors.extend(contract.prompt_checks(body, beat, effective, h3=True, ordered_beats=ordered, contract_version=version))
        candidates[beat["id"]] = {"h3_prompt": body, "contract_version": version,
            "fingerprint": contract.prompt_fingerprint(beat, group, plan),
            "content_digest": contract.digest([body, parsed["common_prompt"], plan.get("source_fingerprint"), version]),
            "semantic_status": "pending_human", "media_status": "not_reviewed"}
    return candidates, parsed["common_prompt"], list(dict.fromkeys(errors))


def run_review(payload, group, checkpoint):
    config = payload["review_config"]
    snapshot = payload["authoring"]["contracts"][group["id"]]
    entries = [e for e in payload["authoring"]["writing_history"] if e["group_id"] == group["id"] and not e.get("errors")]
    if not entries:
        raise ValueError("缺少通过执行检查的完整原稿")
    original = entries[-1]["raw"]
    images = [s["image_url"] for s in group.get("reference_slots", [])]
    for bid in group["beat_ids"]:
        images.extend(next(b for b in payload["beats"] if b["id"] == bid).get("workshop_writing_refs") or [])
    if sha(snapshot["user"]) != snapshot["user_sha256"] or contract.digest([snapshot["system"], snapshot["user"], images]) != snapshot["input_sha256"]:
        raise ValueError("原稿冻结材料不一致，不能审校")
    original_author = entries[-1].get("author") or {}
    original_identity = {k: v for k, v in original_author.items() if k != "frozen_images"}
    user = json.dumps({"frozen_creation_input": snapshot, "original_prompt": original,
                       "original_author": original_identity, "original_sha256": sha(original)}, ensure_ascii=False)
    key = contract.digest([user, config, images])
    reviews = payload.setdefault("ai_reviews", {})
    previous = reviews.get(group["id"])
    if previous and previous.get("key") == key and previous.get("status") in {"unchanged", "revised", "needs_user_resolution"}:
        return
    if previous:
        payload.setdefault("ai_review_history", []).append(deepcopy(previous))
    entry = {"key": key, "status": "running", "system": config["system"], "user": user,
             "skill_version": config["version"], "skill_sha256": sha(config["system"]),
             "input_sha256": contract.digest([config["system"], user, images]),
             "original_sha256": sha(original), "image_locator_hashes": [sha(url) for url in images],
             "original_image_content_verified": not images or bool(original_author.get("image_content_sha256")),
             "raw": "", "content_call_count": 0, "errors": [], "media_status": "not_reviewed"}
    entry["transport_retry_count"] = 0
    reviews[group["id"]] = entry
    checkpoint("第一稿已保存，正在二次审校 · " + group["id"])
    started = time.monotonic()
    try:
        if len(user) + len(config["system"]) > 180000:
            raise ValueError("审校完整输入超过预算，未静默裁剪")
        entry["content_call_count"] = 1
        frozen_images = original_author.get("frozen_images") or images
        if previous and previous.get("key") == key and previous.get("author", {}).get("frozen_images"):
            frozen_images = previous["author"]["frozen_images"]
        raw, meta = LlmService.author_group(config["system"], user, frozen_images, author=config["author"], max_tokens=24000, temperature=0.2, freeze_images=True)
        entry.update(raw=raw, author=meta)
        result = parse_response(raw, original)
        entry.update(result=result, status=result["decision"], diff="\n".join(unified_diff(original.splitlines(), (result["final_prompt"] or original).splitlines(), fromfile="原稿", tofile="审校稿", lineterm="")))
        if result["final_prompt"] and result["decision"] != "needs_user_resolution":
            candidates, common, errors = validate_draft(result["final_prompt"], payload, group)
            entry.update(candidates=candidates, common_prompt=common, errors=errors, eligible=not errors)
    except Exception as err:
        entry.update(status="failed", errors=[str(err)], eligible=False)
        if getattr(err, "author_meta", None):
            entry["author"] = err.author_meta
    entry["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    checkpoint("二次审校已结束；原稿保留，成片待人工验收")


def selected_payload(payload, ids):
    """Return a transient projection for the existing atomic adoption transaction."""
    projected = deepcopy(payload)
    for group in payload["base_plan"]["groups"]:
        if not set(ids).intersection(group["beat_ids"]):
            continue
        review = payload.get("ai_reviews", {}).get(group["id"], {})
        if review.get("status") not in {"revised", "unchanged"} or not review.get("eligible"):
            raise ValueError("审校稿尚未通过执行检查，不能采用")
        candidates, common, errors = validate_draft(review["result"]["final_prompt"], payload, group)
        if errors or candidates != review["candidates"] or common != review["common_prompt"]:
            raise ValueError("审校稿与冻结证据不一致")
        projected["candidates"].update(candidates)
        projected.setdefault("common_prompt_candidates", {})[group["id"]] = common
    return projected
