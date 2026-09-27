"""Immutable, minimal H3 author input. No creative defaults or model calls."""
from copy import deepcopy
import hashlib
import json
import re

from . import workshop_contract as contract
from .workshop_h3_skill import DIRECT_SKILL_PATH, DIRECT_VERSION, source_dialogues, voice_map, _RANGE, _seconds

VERSION = DIRECT_VERSION
# Authored shot material only; never include cached prompts or runtime state.
CREATIVE_FIELDS = ("heading", "scene", "scene_time", "characters", "speaker", "dialogue",
                   "action", "camera", "audio", "dramatic_intent", "performance", "visual_strategy",
                   "opening_state", "closing_state", "transition_note", "props")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_input(plan, group, beats, source, *, revision_beat_id=None, revision_note=""):
    text = str(source.get("text") or "")
    if not text.strip():
        raise ValueError("创作来源缺失：请先确认本集剧本")
    by_id = {b["id"]: b for b in beats}
    ordered = [by_id[bid] for bid in group["beat_ids"]]
    if source.get("conflict"):
        raise ValueError("创作来源冲突：" + str(source["conflict"]))
    skill_bytes = DIRECT_SKILL_PATH.read_bytes()
    skill = skill_bytes.decode("utf-8")
    lines = ["根据以下材料，按 Skill 原生结构生成本组完整 H3 提示词（公共设定及全部镜头）。",
             f"画幅：{plan['aspect_ratio']}。镜头按下列顺序编号 1..{len(ordered)}。",
             "执行时间基准：" + ("组内累计秒。" if contract.group_timecode_mode(group) == "cumulative" else "每镜独立，从 0 秒开始。"),
             "完整分集剧本：\n" + text, "已确认的镜头创作材料："]
    materials = []
    for i, beat in enumerate(ordered, 1):
        material = {k: deepcopy(beat[k]) for k in CREATIVE_FIELDS if beat.get(k) not in (None, "", [])}
        if not material:
            raise ValueError(f"镜头 {i} 创作材料缺失，请确认镜头正文")
        materials.append(material)
        lines.append(f"镜头 {i}，{contract.duration(beat):g} 秒：")
        seen = set()
        for key, value in material.items():
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            # The same sentence in the full script does not preserve its shot
            # assignment. Keep confirmed fields even when source text contains them.
            if rendered in seen:
                continue
            seen.add(rendered)
            lines.append(f"{key}：{rendered}")
    slots = group.get("reference_slots") or []
    images = []
    references = []
    lines.append("实际视频参考图（按上传顺序）：")
    for i, slot in enumerate(slots, 1):
        if slot.get("token") != f"<Picture {i}>" or not slot.get("image_url"):
            raise ValueError("参考图片编号或地址不完整")
        identity = slot.get("name") or slot.get("label") or slot.get("asset_name")
        if not identity:
            raise ValueError(f"Picture {i} 缺少人物／道具身份，请确认素材")
        purpose = slot.get("kind") or slot.get("role") or slot.get("asset_type") or "身份与外观参考"
        lines.append(f"<Picture {i}>：{identity}；用途：{purpose}")
        images.append(slot["image_url"])
        references.append({"token": f"<Picture {i}>", "identity": identity, "purpose": purpose,
                           "image_locator_sha256": sha(str(slot["image_url"]))})
    if not slots:
        lines.append("未提供视频参考图片。")
    if not any(s.get("kind") == "scene" for s in slots):
        lines.append("未提供最终视频场景参考图，场景以文字材料为依据。")
    lines.append("未提供参考音频；场景与物件仅以剧本及上述实际素材为依据。")
    for i, beat in enumerate(ordered, 1):
        refs = beat.get("workshop_writing_refs") or []
        if refs:
            lines.append(f"随后 {len(refs)} 张图片仅供镜头 {i} 写稿参考，不分配 Picture 编号，不作为视频参考。")
            images.extend(refs)
    locks = group.get("locked_common_lines") or []
    if locks:
        lines.append("用户明确锁定项：\n" + "\n".join(locks))
    if revision_beat_id:
        if revision_beat_id not in group["beat_ids"] or not revision_note.strip():
            raise ValueError("单镜返修需指定本组镜头及明确意见")
        lines.append(f"本次人工返修镜头 {group['beat_ids'].index(revision_beat_id) + 1}：{revision_note}")
        lines.append("返回完整组稿；公共设定与非目标镜头正文逐字保持。当前完整稿：")
        lines.append(group.get("common_prompt") or "")
        for beat in ordered:
            body = (plan.get("shot_prompts", {}).get(beat["id"]) or {}).get("h3_prompt")
            if not body:
                raise ValueError("单镜返修缺少已采纳的整组正文")
            lines.append(body)
    user = "\n\n".join(lines)
    if len(skill) + len(user) > 180000:
        raise ValueError("完整上下文超过 180000 字符预算，未静默裁剪")
    return {"version": VERSION, "skill_path": "skills/MINIMAXH3格式动作语气台词细化SKILL/SKILL.md",
            "skill_revision": "original", "validation_policy": "execution_only_v3",
            "skill_text": skill, "skill_sha256": hashlib.sha256(skill_bytes).hexdigest(),
            "system": skill, "user": user, "system_sha256": sha(skill), "user_sha256": sha(user),
            "input_sha256": contract.digest([skill, user, images]),
            "source_sha256": sha(text), "source": {k: deepcopy(source.get(k)) for k in
                ("document_id", "revision", "fingerprint", "source_type", "text")},
            "materials": materials, "material_source": {"type": "confirmed_workshop_shots",
                "planning_revision": plan.get("planning_revision"), "source_revision": plan.get("source_revision")},
            "beat_ids": list(group["beat_ids"]), "references": references,
            "image_hashes": [sha(str(url)) for url in images],
            "image_hash_policy": "ordered_locator_sha256; not downloaded image content",
            "revision_beat_id": revision_beat_id, "revision_note": revision_note,
            "context_policy": "full_source_no_truncation", "text_normalization": "UTF-8 decoded; no stripping or newline conversion",
            "projection_policy": "container_and_shot_header_only"}


def dialogue_key(text):
    """Ignore paired quotation typography only; never rewrite stored speech."""
    text = str(text).strip()
    for opening, closing in (("‘", "’"), ("“", "”"), ("「", "」"), ("『", "』")):
        text = re.sub(re.escape(opening) + r"([^" + re.escape(opening + closing) + r"\n]+)" + re.escape(closing), r"\1", text)
    text = re.sub(r'"([^"\n]+)"', r"\1", text)
    # Apostrophes within words (don't, John's) are spoken text, not quotation.
    return re.sub(r"(?<![\w])'([^'\n]+)'(?![\w])", r"\1", text)


def dialogues_match(expected, actual, version):
    normalize = dialogue_key if version == "h3-skill-direct-v2" else lambda text: str(text).strip()
    return [normalize(t) for t in expected] == [normalize(t) for t in actual]


def unavailable_audio_references(text):
    """Current Director compiler has no audio inputs. Inspect instructions, not dialogue."""
    text = re.sub(r"<d>.*?</d>", "", text, flags=re.S)
    pattern = r"<Audio\s*\d+>|(?:参考音频|音频参考)\s*[#＃]?\s*[0-9一二三四五六七八九十]+|第\s*[0-9一二三四五六七八九十]+\s*(?:段|条|个)参考音频"
    findings = []
    for clause in re.split(r"[，。；;\n]", text):
        for match in re.finditer(pattern, clause, re.I):
            prefix = clause[:match.start()]
            if re.search(r"(?:未提供|没有(?:提供)?|未上传|未使用|不使用|不引用|无)\s*$", prefix):
                continue
            findings.append(match[0])
    return list(dict.fromkeys(findings))


def integrity_checks(body, beat, group, *, offset_sec=0.0, version="h3-skill-direct-v1"):
    """Data integrity, not a writing-style gate. Accept native Subject aliases."""
    errors = []
    common = str(group.get("common_prompt") or "")
    if version == "h3-skill-direct-v3":
        if not common.strip() or not re.search(r"detailed_description\s*[:：]", body):
            errors.append("公共设定或镜头正文容器缺失")
        if re.search(r"<Audio\s*\d+>", common + body, re.I):
            errors.append("引用了未提供的参考音频")
        if any(int(n) < 1 or int(n) > len(group.get("reference_slots") or [])
               for n in re.findall(r"<Picture\s+(\d+)>", common, re.I)):
            errors.append("公共设定引用了不存在的参考图")
        return errors
    expected = source_dialogues(beat)
    tags = list(re.finditer(r"<d>\s*\[中文\]\s*(.*?)</d>", body, re.S))
    if not dialogues_match([text for _, text in expected], [m[1] for m in tags], version):
        errors.append("对白必须按原顺序逐句逐字保留，不得遗漏、重复或新增")
    if body.count("<d>") != len(tags) or body.count("</d>") != len(tags):
        errors.append("对白标签不完整")
    action = re.search(r"【动作】(.*?)(?=【|$)", body, re.S)
    if tags and (not action or any(not action.start(1) <= tag.start() < action.end(1) for tag in tags)):
        errors.append("对白必须位于动作正文中")
    end_sec = offset_sec + contract.duration(beat)
    for timing in _RANGE.finditer(body):
        start, end = _seconds(timing[1]), _seconds(timing[2])
        if not offset_sec <= start < end <= end_sec:
            errors.append("已标注的动作或对白时间超出本镜确认范围")
    if not common.strip() or not re.search(r"detailed_description\s*[:：]", body):
        errors.append("公共设定或镜头正文容器缺失")
    for field in ("主体", "动作", "镜头", "音效", "约束"):
        if len(re.findall(f"【{field}】", body)) != 1 or not re.search(f"【{field}】\\s*[^【\\s]", body):
            errors.append(f"镜头正文缺少完整的【{field}】")
    if (unavailable_audio_references(common + "\n" + body) if version == "h3-skill-direct-v2" else re.search(r"<Audio\s+\d+>", common + body)):
        errors.append("引用了未提供的参考音频")
    if any(int(n) < 1 or int(n) > len(group.get("reference_slots") or []) for n in re.findall(r"<Picture\s+(\d+)>", common)):
        errors.append("公共设定引用了不存在的参考图")
    definitions = re.split(r"声音设定\s*[:：]", common, maxsplit=1)[0]
    subjects = re.findall(r"^\s*<Subject\s+(\d+)>", definitions, re.M)
    if len(subjects) != len(set(subjects)):
        errors.append("主体编号重复定义")
    mapping = dict(voice_map(common, [name for name, _ in expected if name]))
    cursor = 0
    for (owner, _), tag in zip(expected, tags):
        prefix = body[cursor:tag.start()]
        cursor = tag.end()
        labels = [owner] if owner else []
        for line in common.splitlines():
            if owner and owner in line:
                labels.extend(re.findall(r"<(?:Subject|Picture)\s+\d+>", line))
        number = mapping.get(owner)
        explicit = any(re.search(rf"{re.escape(label)}\s*\(S{number}\)", prefix) for label in labels)
        # A named solo speaker already has an unambiguous shared voice. Missing
        # repeated typography is not an identity mismatch; conflicting IDs are.
        action_prefix = prefix.split("【动作】")[-1]
        named_solo = (version == "h3-skill-direct-v2" and len(mapping) == 1 and owner in mapping
                      and bool(owner) and owner in action_prefix
                      and not re.search(r"\(S\d+\)", action_prefix))
        if not number or not (explicit or named_solo):
            errors.append("对白说话人与共享声音定义不一致：" + (owner or "未知"))
    return errors
