from __future__ import annotations

import json
import re
import requests

from server.services.episode_video_service import EpisodeVideoService
from server.services.h3_prompt_builder import H3PromptBuilder
from server.services.project_detail_service import ProjectDetailService


PROJECT_ID = "proj-919ade5e219f46f3"
API_ROOT = "http://127.0.0.1:9010/api/projects"
CHARACTERS = {
    "牛大": ("ast-e14f240da777", "ident-0da777-ancient"),
    "淼淼": ("ast-b882b37c234b", "ident-7c234b-civilian"),
    "安侯嫡子牛铮": ("ast-8f6f6e4c7c9b", "ident-4c7c9b-安侯嫡子牛铮日常造型"),
    "牛铮": ("ast-8f6f6e4c7c9b", "ident-4c7c9b-安侯嫡子牛铮日常造型"),
    "作坊师傅老木": ("ast-4b6198a967a5", "ident-a967a5-作坊师傅老木日常造型"),
    "老木": ("ast-4b6198a967a5", "ident-a967a5-作坊师傅老木日常造型"),
    "奸商钱百万": ("ast-c661e0bf0fce", "ident-bf0fce-奸商钱百万日常造型"),
    "钱百万": ("ast-c661e0bf0fce", "ident-bf0fce-奸商钱百万日常造型"),
    "茶铺娘子阿枝": ("ast-18a7c8ed9b6c", "ident-ed9b6c-茶铺娘子阿枝日常造型"),
    "阿枝": ("ast-18a7c8ed9b6c", "ident-ed9b6c-茶铺娘子阿枝日常造型"),
    "大晟皇帝": ("ast-9d3472c6e014", "ident-c6e014-大晟皇帝日常造型"),
    "皇帝": ("ast-9d3472c6e014", "ident-c6e014-大晟皇帝日常造型"),
}

CANONICAL_NAMES = {
    "ast-e14f240da777": "牛大",
    "ast-b882b37c234b": "淼淼",
    "ast-8f6f6e4c7c9b": "安侯嫡子牛铮",
    "ast-4b6198a967a5": "作坊师傅老木",
    "ast-c661e0bf0fce": "奸商钱百万",
    "ast-18a7c8ed9b6c": "茶铺娘子阿枝",
    "ast-9d3472c6e014": "大晟皇帝",
    "ast-fcd1d48fd303": "好友",
}

DIALOGUE_OVERRIDES = {
    (2, 1): [("好友", "ast-fcd1d48fd303", "下个项目，还是你上！")],
    (2, 3): [("好友", "ast-fcd1d48fd303", "牛大！牛大！撑住！")],
    (3, 4): [("管家", "", "从今日起，安侯府没有你这个人。滚。")],
    (4, 2): [("牛大", "ast-e14f240da777", "贫富差……这盘生意难做。")],
    (4, 3): [("老人", "", "看你像刚被家里撵出来的。")],
    (4, 4): [("商贩", "", "听说宫里账是空的，边关军饷又拖了三月。")],
    (4, 6): [],
    (5, 3): [("小侍女", "", "公主，这些……都压了两个月了。")],
    (5, 6): [],
    (8, 4): [("淼淼", "ast-b882b37c234b", "有风……")],
    (9, 2): [("掌柜", "", "木头也能卖风？滚滚滚，挡客。")],
    (9, 4): [("富商", "", "这一座，我包了。那架子，多少钱？")],
    (9, 5): [
        ("牛大", "ast-e14f240da777", "一台一两。茶楼要，八钱，我再教小二怎么摇得匀。"),
        ("掌柜", "", "十台我全要！"),
    ],
    (10, 2): [
        ("路人甲", "", "那茶楼怎么不热了？"),
        ("路人乙", "", "买了会吹风的木头。"),
    ],
    (10, 3): [("小侍女", "", "布铺要四台，医馆要两台，说病人怕热……")],
}


def dialogue_turns(episode_number: int, beat: dict) -> list[dict]:
    override = DIALOGUE_OVERRIDES.get((episode_number, int(beat.get("sequence") or 0)))
    if override is not None:
        return [{"speaker": speaker, "character_id": character_id, "text": text} for speaker, character_id, text in override]
    dialogue = str(beat.get("dialogue") or "").strip()
    if not dialogue or dialogue in {"无", "无。", "无。风声。"}:
        return []
    matches = re.findall(r"([^：:“”\s]+)[：:]\s*[“\"]([^”\"]+)[”\"]", dialogue)
    turns = []
    for speaker, text in matches:
        character = CHARACTERS.get(speaker)
        canonical_speaker = CANONICAL_NAMES.get(character[0], speaker) if character else speaker
        turns.append({
            "speaker": canonical_speaker,
            "character_id": character[0] if character else "",
            "text": text.strip(),
        })
    if turns:
        extra_quotes = re.findall(r"[“\"]([^”\"]+)[”\"]", dialogue)
        for text in extra_quotes[len(turns):]:
            turns.append({"speaker": "另一名路人", "character_id": "", "text": text.strip()})
        return turns
    quoted = re.findall(r"[“\"]([^”\"]+)[”\"]", dialogue)
    speaker = str(beat.get("speaker") or "").strip()
    if quoted and speaker:
        character = CHARACTERS.get(speaker)
        return [{"speaker": speaker, "character_id": character[0] if character else "", "text": text.strip()} for text in quoted]
    return []


def corrected_beat(episode_number: int, beat: dict) -> dict:
    turns = dialogue_turns(episode_number, beat)
    ids: list[str] = []
    looks: dict[str, str] = {}
    searchable = " ".join([
        " ".join(str(x) for x in beat.get("characters") or []),
        str(beat.get("action") or ""),
        str(beat.get("dialogue") or ""),
    ])
    for name, (character_id, look_id) in CHARACTERS.items():
        if name in searchable and character_id not in ids:
            ids.append(character_id)
            looks[character_id] = look_id

    if episode_number == 2:
        if int(beat.get("sequence") or 0) <= 5 and "ast-e14f240da777" in ids:
            looks["ast-e14f240da777"] = "ident-0da777-modern"
        if int(beat.get("sequence") or 0) in {1, 3}:
            friend_id = "ast-fcd1d48fd303"
            if friend_id not in ids:
                ids.append(friend_id)
            looks[friend_id] = "ident-8fd303"
    if episode_number == 9 and int(beat.get("sequence") or 0) in {2, 4}:
        # These scene-only dialogue Beats have no dedicated shopkeeper/merchant asset.
        # Keep the episode protagonist reference available for continuity while the
        # unreferenced speaker remains an off-camera scene participant.
        ids = ["ast-e14f240da777"]
        looks = {"ast-e14f240da777": "ident-0da777-ancient"}

    # Preserve explicitly selected known characters that are genuinely named in the Beat.
    by_asset_id = {value[0]: value[1] for value in CHARACTERS.values()}
    for character_id in beat.get("character_ids") or []:
        if character_id in by_asset_id and character_id not in ids:
            ids.append(character_id)
            looks[character_id] = by_asset_id[character_id]

    visible_text = str(beat.get("visible_text") or "").strip()
    if not visible_text and not turns:
        action = str(beat.get("action") or "")
        visible = re.findall(r"[“\"]([^”\"]+)[”\"]", action)
        if visible and re.search(r"写|账|牌|字|标|帖|单", action):
            visible_text = "；".join(visible)

    updates = {
        "character_ids": ids,
        "character_look_ids": looks,
        "characters": [CANONICAL_NAMES[character_id] for character_id in ids],
        "dialogue_turns": turns,
        "speaker": turns[0]["speaker"] if turns else str(beat.get("speaker") or ""),
        "visible_text": visible_text,
    }
    if not turns and str(beat.get("dialogue") or "").strip() in {"无", "无。", "无。风声。"}:
        updates["dialogue"] = ""
        updates["speaker"] = ""
    if (episode_number, int(beat.get("sequence") or 0)) == (4, 6):
        updates["dialogue"] = ""
        updates["speaker"] = ""
        updates["visible_text"] = "转让"
    return updates


def make_prompt(shot: dict, speaker_map: dict[str, str]) -> str:
    refs = shot.get("character_references") or []
    definitions = []
    for index, ref in enumerate(refs, start=1):
        definitions.append(
            f"<Subject {index}> is the exact appearance of {ref.get('character_name')}, anchored by <Picture {index}>. "
            f"Preserve this face, age, hairstyle, body proportions, garment layers, fabric colors, footwear, accessories, and period identity exactly: {ref.get('description')}."
        )
    scene_index = len(refs) + 1
    definitions.append(
        f"<Subject {scene_index}> is the exact environment anchored by <Picture {scene_index}>: {shot.get('scene')}. "
        "Preserve its architecture, furniture, practical objects, entrances, surfaces, lighting direction, depth, and spatial layout."
    )
    ref_index = {str(ref.get("character_id") or ""): i for i, ref in enumerate(refs, start=1)}
    speeches = []
    for turn in H3PromptBuilder._dialogue_turns(shot):
        speaker = str(turn.get("speaker") or "").strip()
        text = str(turn.get("text") or "").strip()
        subject_index = ref_index.get(str(turn.get("character_id") or ""))
        subject = f"<Subject {subject_index}> " if subject_index else "An off-camera scene participant "
        speeches.append(
            f"({speaker_map[speaker]}) {subject}{speaker} says <d>[Chinese] {text}</d>. "
            "The lips of the identified visible speaker synchronize only with this exact sentence. All listeners remain silent with naturally closed lips. "
            "The shot begins the line early enough and holds long enough for the complete unhurried speech and a natural pause."
        )
    visible_text = str(shot.get("visible_text") or "").strip()
    visible_instruction = ""
    if visible_text:
        visible_instruction = (
            f'The only required readable on-screen Chinese text is exactly "{visible_text}". '
            "Render it on the specified physical document, sign, label, or display; it is visible text and is never spoken aloud."
        )
    narration = str(shot.get("narration") or "").strip()
    narration_instruction = ""
    if narration:
        narration_instruction = (
            f"In an off-screen voiceover: <d>[Chinese] {narration}</d>. "
            "Every visible character keeps naturally closed lips during the voiceover."
        )
    no_speech = ""
    if not speeches and not narration:
        no_speech = "There is no dialogue or narration in this shot. Every visible character keeps naturally closed lips and performs without suggesting speech."

    characters = ", ".join(shot.get("characters") or []) or "the referenced subject"
    props = ", ".join(str(x) for x in shot.get("props") or []) or "the physically relevant scene objects"
    return "\n".join([
        "subject_definitions:",
        *definitions,
        "summary:",
        f"[reference generation + audio reference] One continuous ten-second cinematic shot in {shot.get('scene')} follows this exact story action: {shot.get('action')}. The visual focus remains on {characters}, with no unrelated event, invented character, or internal cut.",
        "retention_analysis:",
        "fully_preserved. Every supplied picture is authoritative only for its assigned subject. Keep identities separate, retain the selected period costumes, and preserve the referenced environment. Never swap faces, merge people, change age or clothing, duplicate limbs, modernize historical material, or introduce a conflicting location.",
        "detailed_description:",
        f"[Shot 1] Stage one physically continuous ten-second performance inside <Subject {scene_index}>. The exact narrative action is: {shot.get('action')}. The exact camera direction is: {shot.get('camera')}. Translate that direction into one controlled cinematic move with restrained acceleration, coherent screen direction, comfortable headroom, readable eyelines, realistic lens perspective, and no hidden edit. Begin with a brief establishing hold that makes the location and starting body positions immediately legible. Keep {characters} spatially distinct and consistent with their assigned picture references. Use {props} only as specified, with believable scale, weight, grip, contact, inertia, and placement. Do not replace the action with a static portrait or an abstract plot summary.",
        "During the opening phase, establish the relevant hands, faces, props, and environmental relationship before the main movement begins. Natural period-appropriate practical light supplies a stable key direction; soft fill preserves facial detail, motivated edge light separates figures from the background, and all contact shadows and reflections remain coherent. Clothing follows the body with subtle inertia and never changes design. During the middle phase, perform the source action in its written order, showing clear anticipation, contact, weight transfer, consequence, and emotional recognition. Use restrained facial acting through eyes, breathing, jaw, shoulders, and posture. Prevent flicker, facial drift, body warping, prop teleportation, unreadable hand contact, sudden zooms, and unrelated background spectacle.",
        *speeches,
        visible_instruction,
        narration_instruction,
        no_speech,
        "During the closing phase, let the physical action settle instead of adding a new plot beat. Reduce body and camera movement gradually, preserve continuity with the next scene, and hold the final reaction or environmental result for at least one full second so the emotional meaning reads clearly. The complete action, any exact speech, its natural pause, and the final held reaction must all fit comfortably inside ten seconds. Do not invent dialogue, subtitles, narration, extra gestures, additional characters, time jumps, or a second shot.",
        "overall_soundscape:",
        f"Build continuous location-appropriate ambience for {shot.get('scene')}, with synchronized footsteps, fabric movement, breathing, hand contact, prop handling, and surface impacts generated only when visible. Give {props} distinct physically plausible foley. Keep voices clean and correctly assigned, preserve natural room acoustics, and avoid intelligible background dialogue that could be mistaken for a scripted line.",
        "non_diegetic_music:",
        "Use a restrained cinematic score appropriate to the scene's emotional direction: sparse period-sensitive instrumentation, a moderate pulse around 64-78 BPM, minimal melody under dialogue, controlled dynamics, and a soft final cadence. The score must never cover speech or overpower physical sound, and it must not introduce a contradictory comic or heroic mood."
    ]).replace("\n\n", "\n")


def main() -> None:
    episodes = ProjectDetailService.list_episodes(PROJECT_ID)
    assets = ProjectDetailService.list_assets(PROJECT_ID)
    prepared = []
    # Validate every episode against a hypothetical corrected snapshot before writing anything.
    for number in range(2, 11):
        episode = next(item for item in episodes if int(item.get("episode_num") or 0) == number)
        detail = ProjectDetailService.get_episode_detail(PROJECT_ID, episode["id"])
        updates_by_beat = {}
        for beat in detail.get("beats") or []:
            updates = corrected_beat(number, beat)
            beat.update(updates)
            updates_by_beat[beat["id"]] = updates
        shots = EpisodeVideoService._prepare_shots(detail, assets, project_id="")
        for shot in shots:
            shot["duration_seconds"] = 10
            shot["frame_count"] = 243
        speaker_map = H3PromptBuilder._speaker_map(shots)
        prompts = [make_prompt(shot, speaker_map) for shot in shots]
        errors = H3PromptBuilder.validate_prompts(shots, prompts, speaker_map)
        if errors:
            raise RuntimeError(f"Episode {number} prompt validation failed: {errors}")
        prepared.append((number, episode, updates_by_beat, shots, prompts))

    results = []
    for number, episode, updates_by_beat, shots, prompts in prepared:
        for beat_id, updates in updates_by_beat.items():
            ProjectDetailService.update_episode_beat(PROJECT_ID, episode["id"], beat_id, updates)
        payload = {
            "duration_per_beat": 10,
            "frames_per_beat": 243,
            "prompt_source": "codex",
            "prompt_model": "GPT-5 Codex",
            "prompts": [
                {"beat_id": shot["beat_id"], "prompt": prompt}
                for shot, prompt in zip(shots, prompts)
            ],
        }
        response = requests.post(
            f"{API_ROOT}/{PROJECT_ID}/episodes/{episode['id']}/generate-video",
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        receipt = response.json()
        results.append({
            "episode": number,
            "episode_id": episode["id"],
            "title": episode.get("title"),
            "shot_count": len(shots),
            "word_counts": [H3PromptBuilder._english_word_count(prompt) for prompt in prompts],
            **receipt,
        })
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
