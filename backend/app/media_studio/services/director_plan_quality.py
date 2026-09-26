"""Bounded, evidence-driven Director revisions; no video submission here."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Callable

from ...dialogue_timing import estimate_dialogue_duration_sec, resolve_shot_duration_sec
from .prompt_templates import PromptTemplateError, parse_director_creative_output
from .director_review_policy import REVIEW_POLICY, REVIEW_POLICY_VERSION

QUALITY_VERSION = 1
CREATIVE_FIELDS = ("shot_size", "camera", "movement", "performance", "dialogue_timing", "purpose")
CRITERIA = {"fidelity", "causality", "continuity", "timing", "camera", "performance", "references", "user_feedback"}


def beat_duration(beat: dict) -> float:
    value = beat.get("video_duration")
    return float(value) if value not in (None, "") else float(resolve_shot_duration_sec(beat))


def content_digest(plan: dict | None) -> str:
    """Exclude delivery metadata so rendering cannot invalidate an editing base."""
    if not plan:
        return ""
    body = {key: plan.get(key) for key in ("id", "revision", "source_fingerprint", "common_setting", "reference_slots")}
    body["segments"] = [{k: s.get(k) for k in ("id", "source_units", "sections", "prompt_text")}
                        for p in plan.get("parts", []) for s in p.get("segments", [])]
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def preflight(beats: list[dict], facts: dict, definition) -> list[dict]:
    """Only reject provable conflicts; unknown scene boundaries are not guessed."""
    issues = []
    max_seconds = int(definition.max_total_frames) / 24
    runs: list[list[dict]] = []
    for beat in beats:
        bid = str(beat["id"])
        rows = facts[bid]
        try:
            seconds = beat_duration(beat)
        except (ValueError, TypeError, OverflowError):
            seconds = float("nan")
        speech = sum(estimate_dialogue_duration_sec(x["text"]) for x in rows["dialogues"])
        count = len(rows["events"]) + len(rows["dialogues"])
        def add(code, evidence, suggestion):
            issues.append({"code": code, "beat_id": bid, "evidence": evidence, "suggestion": suggestion})
        if not math.isfinite(seconds) or seconds <= 0:
            add("INVALID_DURATION", "分镜时长无效。", "请填写有效的正数时长。")
        elif speech > seconds + 1 / 24:
            add("DIALOGUE_TIME", f"对白预计至少 {speech:.1f} 秒，分镜仅 {seconds:g} 秒。", "请增加分镜时长或修改对白后重新生成。")
        if not count:
            add("NO_ACTION", "分镜仅有持续状态，没有可分配的动作或对白。", "请补充真实动作，或将状态并入相邻分镜。")
        if count and math.isfinite(seconds) and seconds >= count * max_seconds:
            add("UNIT_CAPACITY", "现有事实数量无法在单元容量内覆盖分镜时长。", "请明确动作边界、调整时长或改用逐镜生成。")
        scene = str(beat.get("scene_id") or beat.get("scene") or "").strip()
        if not runs or scene != runs[-1][0]["scene"]:
            runs.append([])
        runs[-1].append({"scene": scene, "beat_id": bid, "count": count})
    for run in runs:
        # A fully specified scene, or the entire episode, has no possible
        # second unit when it contains just one immutable fact.
        if sum(x["count"] for x in run) == 1 and (run[0]["scene"] and all(x["scene"] for group in runs for x in group) or len(runs) == 1):
            issues.append({"code": "SINGLE_UNIT_SCENE", "beat_id": run[0]["beat_id"],
                           "evidence": f"场景「{run[0]['scene'] or '本集'}」只有一个可分配事实，不能组成至少两段的 Director Part。",
                           "suggestion": "请明确真实动作边界后调整分镜，或选择逐镜生成；不会添加空镜凑数。"})
    return issues


def blocking_issues(plan: dict) -> list[dict]:
    return [i for i in (plan.get("creative_review") or {}).get("issues", []) if i.get("severity") != "advisory"]


def assert_ready_for_video(plan: dict, group_id: str | None = None) -> None:
    if not plan.get("quality_version"):
        return  # Historical plans keep their existing behavior.
    if not isinstance(plan.get("creative_review"), dict) or plan.get("quality_status") == "not_reviewed" or plan.get("reviewed_content_digest") != content_digest(plan):
        raise ValueError("Director 当前正文尚未复验，请先按意见返修或重新审稿")
    blockers = blocking_issues(plan)
    if group_id and int(plan.get("schema_version") or 0) >= 5:
        segment_ids = {s["id"] for part in plan.get("parts") or []
                       if (part.get("source_group_id") or part.get("id")) == group_id
                       for s in part.get("segments") or []}
        blockers = [issue for issue in blockers if issue.get("segment_id") in segment_ids
                    or (not issue.get("segment_id") and str(issue.get("id") or "").startswith(group_id + ":"))]
    if blockers:
        raise ValueError("Director 方案仍有阻断问题，请在方案中返修或调整分镜后再出片")


def review_plan(plan: dict, source: dict, requirements: list[dict], previous: list[dict], *,
                group_cache: dict | None = None, save_group: Callable[[dict], None] | None = None) -> dict:
    from .script_development import call_json
    parts = plan["parts"]
    if int(plan.get("schema_version") or 0) >= 5:
        grouped: dict[str, list[dict]] = {}
        for part in parts:
            grouped.setdefault(part.get("source_group_id") or part["id"], []).append(part)
        scopes = list(grouped.items())
    else:
        scopes = [("episode", parts)]
    normalized = {}
    for group_id, scoped_parts in scopes:
        ids = {s["id"] for p in scoped_parts for s in p["segments"]}
        beat_ids = {bid for p in scoped_parts for s in p["segments"] for bid in s.get("source_beat_ids") or []}
        scoped_asset_ids = {x for b in source.get("beats") or [] if str(b.get("id")) in beat_ids
                            for x in [b.get("scene_id"), *(b.get("character_ids") or []), *(b.get("prop_ids") or [])]}
        scoped_asset_ids.update(slot.get("asset_id") for part in scoped_parts
                                for slot in part.get("reference_slots") or [] if slot.get("asset_id"))
        scoped_source = source if group_id == "episode" else {
            "episode": {"id": (source.get("episode") or {}).get("id"),
                        "title": (source.get("episode") or {}).get("title")},
            "beats": [b for b in source.get("beats") or [] if str(b.get("id")) in beat_ids],
            "assets": [a for a in source.get("assets") or [] if a.get("id") in scoped_asset_ids],
        }
        scoped_plan = plan if group_id == "episode" else {**plan, "parts": scoped_parts,
            "reference_slots": scoped_parts[0].get("reference_slots", plan.get("reference_slots") or []),
            "director_design": {"groups": [g for g in (plan.get("director_design") or {}).get("groups") or []
                                           if g.get("group_id") == group_id]}}
        scoped_requirements = [r for r in requirements if not r.get("segment_ids") or ids.intersection(r["segment_ids"])]
        scoped_previous = [i for i in previous if i.get("segment_id") in ids or
                           (not i.get("segment_id") and (group_id == "episode" or str(i.get("id") or "").startswith(group_id + ":")))]
        digest = hashlib.sha256(json.dumps({"review_policy_version": REVIEW_POLICY_VERSION, "source": scoped_source, "plan": review_context(scoped_plan),
            "requirements": scoped_requirements, "previous": scoped_previous}, ensure_ascii=False,
            sort_keys=True, default=str).encode()).hexdigest()
        cached = (group_cache or {}).get(group_id) or {}
        if cached.get("digest") == digest:
            result = {"issues": cached["issues"]}
        else:
            result = call_json(
        "你是独立分镜审片编辑。对照原剧本、实际提交正文和全部用户修改要求审稿。"
        "核查事实/对白忠实、因果、动作密度、正常语速、持物站位连续性、摄影表演冲突、参考图。"
        "对 previous_issues 逐项复核，包括以前已解决的问题，禁止只检查最近改动。"
        "返回 {issues:[{segment_id,criterion,severity,repair_scope,evidence,suggestion}]}。"
        "segment_id 必须来自本方案；全局问题使用空字符串。criterion 只能为 "
        "fidelity,causality,continuity,timing,camera,performance,references,user_feedback。"
        "severity 为 blocking（违背明确要求或不可拍）或 advisory（可取舍的审美建议）。"
        "repair_scope 为 creative 或 planning；改剧情/对白、总时长、动作归属、公共设定或起止状态才能解决的必须是 planning。"
        "evidence 引用实际冲突，suggestion 写可验证的修改目标。不得将主观偏好当作硬错误。"
        "只有全部核查满足时 issues=[]；不能声称已生成视频验证。" + REVIEW_POLICY,
            {"source": scoped_source, "plan": review_context(scoped_plan), "requirements": scoped_requirements,
             "previous_issues": scoped_previous})
        rows = result.get("issues")
        if not isinstance(rows, list):
            raise PromptTemplateError(f"生成组 {group_id} 创作审稿必须返回 issues 数组")
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("evidence") or "").strip() or not str(row.get("suggestion") or "").strip():
                raise PromptTemplateError(f"生成组 {group_id} 创作审稿缺少问题证据与修复目标")
            sid = row.get("segment_id", "")
            criterion = row.get("criterion", "fidelity")
            severity = row.get("severity", "blocking")
            scope = row.get("repair_scope", "planning")
            if any(not isinstance(x, str) for x in (sid, criterion, severity, scope)) or sid not in ids | {""} or criterion not in CRITERIA or severity not in {"blocking", "advisory"} or scope not in {"creative", "planning"}:
                raise PromptTemplateError(f"生成组 {group_id} 创作审稿的问题位置或分类无效")
            key = f"{sid or group_id}:{criterion}"
            issue = {"id": key, "segment_id": sid, "criterion": criterion, "severity": severity,
                     "repair_scope": scope, "evidence": str(row["evidence"]), "suggestion": str(row["suggestion"])}
            if key in normalized:
                old = normalized[key]
                issue["evidence"] = old["evidence"] + "\n" + issue["evidence"]
                issue["suggestion"] = old["suggestion"] + "\n" + issue["suggestion"]
                if old["severity"] == "blocking": issue["severity"] = "blocking"
                if old["repair_scope"] == "planning": issue["repair_scope"] = "planning"
            normalized[key] = issue
        if group_cache is not None and cached.get("digest") != digest:
            group_cache[group_id] = {"digest": digest, "issues": rows}
            if save_group:
                save_group(group_cache)
    return {"issues": list(normalized.values())}


def review_context(plan: dict) -> dict:
    return {key: plan.get(key) for key in ("director_design", "common_setting", "reference_slots", "parts", "language")}


def repair_segments(plan: dict, source: dict, issues: list[dict], requirements: list[dict], targets: list[str]) -> dict:
    """Model writes a scoped patch; program owns all immutable fields."""
    from .llm_service import LlmService
    from .prompt_expansion_service import PromptExpansionService as Service
    candidate = deepcopy(plan)
    segments = [s for p in candidate["parts"] for s in p["segments"] if s["id"] in targets]
    if not segments:
        raise PromptTemplateError("返修未指定有效段落")
    scoped_parts = [p for p in candidate["parts"] if any(s["id"] in targets for s in p["segments"])]
    scoped_beats = {bid for p in scoped_parts for s in p["segments"] for bid in s.get("source_beat_ids") or []}
    scoped_source = {"episode": {"id": (source.get("episode") or {}).get("id")},
                     "beats": [b for b in source.get("beats") or [] if str(b.get("id")) in scoped_beats]}
    scoped_group_ids = {p.get("source_group_id") for p in scoped_parts}
    scoped_plan = {**plan, "parts": scoped_parts,
                   "reference_slots": scoped_parts[0].get("reference_slots", plan.get("reference_slots") or [])}
    if int(plan.get("schema_version") or 0) >= 5:
        design = plan.get("director_design") or {}
        scoped_plan["director_design"] = {"groups": [g for g in design.get("groups") or []
                                                      if g.get("group_id") in scoped_group_ids]}
    raw = LlmService.chat_text(
        "你是分镜返修编辑，只修指定段落，返回 JSON {segments:[{segment_id,unit_ids,unit_designs:"
        "[{unit_id,shot_size,camera,movement,performance,dialogue_timing,purpose}],summary,retention_analysis,"
        "detailed_description,overall_soundscape,non_diegetic_music}]}。"
        "unit_designs 可省略；提供时只允许列出的摄影表演字段。其他字段每段必须填写。"
        "剧情、对白原文、时长、单元归属、起止状态、公共设定和未指定段落已锁定，不得改变。"
        "正文只补充未在 unit_designs 表达的必要声画细节，禁止重复摄影表演、动作原文和台词；"
        "不要写 Shot 编号或固定连续性前缀，程序会编译。只使用已存在参考图。"
        "用户反馈不能凌驾于锁定事实；不可满足的问题留给审稿，不编造剧情解决。",
        json.dumps({"source": scoped_source, "plan": review_context(scoped_plan),
                    "target_segment_ids": targets, "issues": [i for i in issues if i.get("segment_id") in targets],
                    "requirements": [r for r in requirements if not r.get("segment_ids") or set(r["segment_ids"]) & set(targets)]}, ensure_ascii=False),
        max_tokens=16000, temperature=0.2, timeout=300)
    try:
        data = LlmService._parse_json_object(raw)
    except ValueError as err:
        raise PromptTemplateError(f"返修 JSON 无法解析：{err}") from err
    rows = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(rows, list) or any(not isinstance(x, dict) or not isinstance(x.get("segment_id"), str) for x in rows):
        raise PromptTemplateError("返修缺少段落")
    by_id = {x.get("segment_id"): x for x in rows}
    if len(by_id) != len(rows) or set(by_id) != set(targets):
        raise PromptTemplateError("返修范围与所选段落不一致")
    for seg in segments:
        units = {u["id"]: u for u in seg["source_units"]}
        edits = by_id[seg["id"]].get("unit_designs", [])
        if not isinstance(edits, list):
            raise PromptTemplateError("返修摄影表演字段格式无效")
        seen = set()
        for edit in edits:
            if not isinstance(edit, dict) or not isinstance(edit.get("unit_id"), str) or edit["unit_id"] not in units or edit["unit_id"] in seen or set(edit) - {"unit_id", *CREATIVE_FIELDS}:
                raise PromptTemplateError("返修试图改变锁定字段或未知单元")
            seen.add(edit["unit_id"])
            for k, v in edit.items():
                if k == "unit_id": continue
                if not isinstance(v, str) or not v.strip():
                    raise PromptTemplateError("摄影表演字段不能为空")
                units[edit["unit_id"]][k] = v.strip()
    scoped_slots = scoped_parts[0].get("reference_slots", candidate.get("reference_slots", []))
    parsed = parse_director_creative_output(json.dumps(data, ensure_ascii=False), candidate["language"],
        scoped_slots, segments, candidate["common_setting"])
    groups = Service._compile_director_groups(segments, parsed["groups"], candidate["language"])
    for seg, group in zip(segments, groups):
        seg.update(sections=group["sections"], prompt_text=group["prompt_text"])
    # Keep the design used by the reviewer consistent with the compiled plan.
    designed = (candidate.get("director_design") or {}).get("units", [])
    for seg in segments:
        for unit in seg["source_units"]:
            for original in designed:
                if original.get("source_beat_id") == unit.get("source_beat_id") and original.get("event_ids") == unit.get("event_ids") and original.get("dialogue_ids") == unit.get("dialogue_ids"):
                    original.update({k: unit[k] for k in CREATIVE_FIELDS if k in unit})
    all_segments = [s for p in candidate["parts"] for s in p["segments"]]
    Service._validate_director_groups(all_segments, [{"sections": s["sections"], "prompt_text": s["prompt_text"],
        "shot_numbers": [x["shot_number"] for x in s["shots"]]} for s in all_segments], candidate["language"])
    Service.validate_director_plan(candidate)
    return candidate


def improve_plan(plan: dict, source: dict, *, feedback: str = "", targets: list[str] | None = None,
                 save: Callable[[dict], None] = lambda _: None, state: dict | None = None) -> dict:
    """At most two patches. Preserve best known draft on regression or no progress."""
    from ...llm_client import emit_llm_stream_status
    if (state or {}).get("done"):
        return deepcopy(state["plan"])
    current = deepcopy((state or {}).get("plan") or plan)
    history = deepcopy((state or {}).get("history") or [])
    group_cache = deepcopy((state or {}).get("group_reviews") or {})
    pending_snapshot = deepcopy((state or {}).get("pending_review"))
    def save_reviews(cache: dict) -> None:
        save({"plan": current, "history": history, "done": False, "group_reviews": cache,
              **({"pending_review": pending_snapshot} if pending_snapshot else {})})
    requirements = deepcopy(current.get("revision_requirements") or [])
    if feedback and not state:
        requirements.append({"feedback": feedback, "segment_ids": targets or []})
    current["revision_requirements"] = requirements
    current["quality_version"] = QUALITY_VERSION
    ledger = {i["id"]: i for h in [*(plan.get("revision_history") or []), *history] for i in h.get("issues", []) if i.get("id")}
    if not state:
        emit_llm_stream_status("director_creative_review", "正在逐项审稿并检查修改要求", reset=True)
        current["creative_review"] = deepcopy(review_plan(current, source, requirements, list(ledger.values()),
            group_cache=group_cache, save_group=save_reviews))
        if feedback:
            for sid in targets or []:
                if not any(i["segment_id"] == sid and i["criterion"] == "user_feedback" for i in current["creative_review"]["issues"]):
                    current["creative_review"]["issues"].append({"id": f"{sid}:user_feedback", "segment_id": sid,
                        "criterion": "user_feedback", "severity": "blocking", "repair_scope": "creative",
                        "evidence": "本次修改意见尚未落实到新版本。", "suggestion": feedback})
        history.append({"round": 0, "status": "reviewed", "issues": current["creative_review"]["issues"]})
    def checkpoint(reason=""):
        current["quality_status"] = "review_required" if current["creative_review"]["issues"] else "reviewed"
        current["revision_history"] = history
        current["revision_stop_reason"] = reason
        current["reviewed_content_digest"] = content_digest(current)
        save({"plan": current, "history": history, "done": bool(reason), "group_reviews": group_cache})
    checkpoint()
    attempted = sum(1 for h in history if h["round"] > 0)
    pending = pending_snapshot
    for attempt in range(attempted + 1, 3):
        issues = current["creative_review"]["issues"]
        ledger.update({i["id"]: i for i in issues})
        blockers = [i for i in issues if i["severity"] == "blocking"]
        explicit = bool(feedback and attempt == 1)
        if not blockers and not explicit:
            checkpoint("completed")
            return current
        eligible = [i for i in blockers if i["repair_scope"] == "creative" and i["segment_id"]]
        selected = list(targets or []) if explicit else sorted({i["segment_id"] for i in eligible if targets is None or i["segment_id"] in targets})
        if not selected or any(i["repair_scope"] == "planning" and (not explicit or i["segment_id"] in selected) for i in blockers):
            checkpoint("planning_required")
            return current
        emit_llm_stream_status("director_revision", f"正在返修并复验第 {attempt} 轮", reset=True, attempt=attempt, segment_ids=selected)
        try:
            if pending and pending.get("round") == attempt:
                candidate = deepcopy(pending["candidate"])
                repaired_groups = set(pending.get("repaired_group_ids") or [])
            else:
                candidate = deepcopy(current)
                repaired_groups = set()
            group_targets: dict[str, list[str]] = {}
            for part in current["parts"]:
                group_id = (part.get("source_group_id") or part["id"]) if int(current.get("schema_version") or 0) >= 5 else "episode"
                for segment in part["segments"]:
                    if segment["id"] in selected:
                        group_targets.setdefault(group_id, []).append(segment["id"])
            for group_id, ids in group_targets.items():
                if group_id in repaired_groups:
                    continue
                candidate = repair_segments(candidate, source, issues, requirements, ids)
                repaired_groups.add(group_id)
                pending_snapshot = {"round": attempt, "candidate": candidate,
                                    "repaired_group_ids": sorted(repaired_groups)}
                save({"plan": current, "history": history, "done": False, "group_reviews": group_cache,
                      "pending_review": pending_snapshot})
            candidate["creative_review"] = review_plan(candidate, source, requirements, list(ledger.values()),
                group_cache=group_cache, save_group=save_reviews)
        except PromptTemplateError as err:
            history.append({"round": attempt, "status": "invalid_patch", "detail": str(err), "segment_ids": selected})
            checkpoint("invalid_patch")
            return current
        before = {i["id"] for i in blockers}
        after = {i["id"] for i in blocking_issues(candidate)}
        accepted = after < before or (explicit and not after and content_digest(candidate) != content_digest(current))
        old_segments = {s["id"]: s for p in current["parts"] for s in p["segments"]}
        changes = [{"segment_id": s["id"], "before": old_segments[s["id"]]["prompt_text"], "after": s["prompt_text"]}
                   for p in candidate["parts"] for s in p["segments"] if s["prompt_text"] != old_segments[s["id"]]["prompt_text"]]
        history.append({"round": attempt, "status": "accepted" if accepted else "rejected", "segment_ids": selected,
                        "resolved": sorted(before - after), "remaining": sorted(after & before), "new": sorted(after - before),
                        "issues": candidate["creative_review"]["issues"], "changes": changes})
        if not accepted:
            checkpoint("no_progress")
            return current
        current = candidate
        checkpoint()
    checkpoint("completed" if not blocking_issues(current) else "round_limit")
    return current
