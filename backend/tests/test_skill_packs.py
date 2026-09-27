from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.director_agents import _system
from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder, _THICKNESS_PAD
from backend.app.media_studio.services.llm_service import DualShotAuthorError, DualShotAuthorResult, LlmService
from backend.app.skill_packs import (
    HALF_NARRATED_PACK_ID,
    UnknownSkillPackError,
    UnknownSkillStepError,
    craft_overlay_for_stage,
    get_pack,
    list_pack_catalog,
    packing_overrides_of,
    packing_system_prompt_for,
    persist_project_settings,
    recipe_from_mapping,
    registered_step_ids,
    resolve_skill_pack_id,
    run_workshop_prompt,
    skill_pack_id_of,
    skill_pack_scope,
    validate_skill_pack_id,
)
from backend.app.skill_packs.handlers import (
    EN_BLOCK_MARK,
    StepContext,
    ZH_BLOCK_MARK,
    bind_r2v_slot_images,
    build_dual_author_system,
    build_timestamped_zh_author_system,
    build_timestamped_zh_author_user,
    collect_zh_author_image_urls,
    expand_r2v_slot_plan,
    extract_ref2va_prompt,
    extract_triptych_panels,
    fill_timestamped_zh_prompt,
    generate_shot_triptych,
    h3_authoring_context_images,
    inject_craft_text,
    parse_dual_author_output,
    polish_ref2va,
    slot_contains_full_triptych,
    validate_timestamped_zh_prompt,
    write_timestamped_zh_prompt,
)
from backend.app.skill_packs.recipe import PACKS_ROOT, default_recipe, load_recipe_file, reset_pack_cache
from backend.app.skill_packs.triptych import split_triptych_image
from backend.app.skill_packs.yaml_util import parse_yaml
from backend.app.media_studio.services.storyboard_image_service import StoryboardImageService
from backend.app.vision_runtime import VisionCallMeta


def _scene_asset(scene_id: str = "s1", name: str = "场景", url: str = "https://x/scene.png") -> dict:
    return {"id": scene_id, "kind": "scene", "name": name, "extra": {"master_url": url}}


class SkillPackRegistryTests(unittest.TestCase):
    def test_meta_yaml_loads_and_declares_registered_steps(self):
        recipe = load_recipe_file(PACKS_ROOT / HALF_NARRATED_PACK_ID / "meta.yaml")
        self.assertEqual(HALF_NARRATED_PACK_ID, recipe.id)
        registered = registered_step_ids()
        unknown = [step for step in recipe.declared_step_ids() if step not in registered]
        self.assertEqual([], unknown)
        self.assertEqual(
            (
                "generate_shot_triptych",
                "extract_triptych_panels",
                "write_timestamped_zh_prompt",
                "polish_ref2va",
                "bind_r2v_slots",
            ),
            recipe.workshop_shot,
        )
        self.assertTrue(recipe.packing_overrides.allow_timeranges)
        self.assertTrue(recipe.packing_overrides.allow_multi_camera_path)
        self.assertTrue(recipe.packing_overrides.faithful_zh_pack)
        self.assertTrue(recipe.packing_overrides.skip_program_pack)
        self.assertEqual(5, recipe.confirm_format.get("duration_min"))
        self.assertEqual(15, recipe.confirm_format.get("duration_max"))
        self.assertEqual("user-confirmed", recipe.confirm_format.get("resolution"))
        self.assertEqual(
            ("characters", "props"),
            tuple(item.source for item in recipe.r2v_slots),
        )
        self.assertIn("真人短剧", recipe.summary)
        self.assertEqual("MiniMax Design", recipe.author)
        self.assertTrue(recipe.cover.startswith("https://cdn.hailuoai.com/"))
        self.assertTrue(recipe.cover.endswith(".mp4"))

    def test_unknown_step_rejected_at_recipe_load(self):
        with self.assertRaises(UnknownSkillStepError):
            recipe_from_mapping({"id": "demo-pack", "workshop_shot": ["not_a_registered_step"]})

    def test_catalog_starts_with_default_and_includes_half_narrated(self):
        reset_pack_cache()
        catalog = list_pack_catalog()
        self.assertEqual("", catalog[0]["id"])
        self.assertEqual(["render_ref2va_default"], catalog[0]["workshop_shot"])
        self.assertEqual("不注入 Plaza 制作配方，工坊用程序装箱六段。", catalog[0]["summary"])
        ids = [item["id"] for item in catalog]
        self.assertIn(HALF_NARRATED_PACK_ID, ids)
        half = next(item for item in catalog if item["id"] == HALF_NARRATED_PACK_ID)
        self.assertIn("真人短剧", half["summary"])
        self.assertEqual("MiniMax Design", half["author"])
        self.assertTrue(half["cover"].startswith("https://cdn.hailuoai.com/"))
        self.assertEqual("", catalog[0]["cover"])
        self.assertEqual("", catalog[0]["author"])

    def test_recipe_cover_only_keeps_http_urls(self):
        recipe = recipe_from_mapping({"id": "demo-pack", "cover": "javascript:alert(1)", "author": "内部"})
        self.assertEqual("", recipe.cover)
        self.assertEqual("内部", recipe.author)

    def test_yaml_parser_reads_pack_meta(self):
        text = (PACKS_ROOT / HALF_NARRATED_PACK_ID / "meta.yaml").read_text(encoding="utf-8")
        data = parse_yaml(text)
        self.assertEqual(HALF_NARRATED_PACK_ID, data["id"])
        self.assertEqual("characters", data["r2v_slots"][0]["source"])
        self.assertTrue(data["packing_overrides"]["allow_timeranges"])


class SkillPackBindingTests(unittest.TestCase):
    def test_extra_skill_pack_id_canonicalizes_camel_case(self):
        merged = persist_project_settings({}, {"skillPackId": HALF_NARRATED_PACK_ID})
        self.assertEqual(HALF_NARRATED_PACK_ID, merged["extra"]["skill_pack_id"])
        self.assertNotIn("skillPackId", merged["extra"])
        self.assertEqual(HALF_NARRATED_PACK_ID, skill_pack_id_of(merged))

    def test_updating_settings_keeps_existing_extra(self):
        merged = persist_project_settings(
            {"visual_style": "modern"},
            None,
            current_settings={"visual_style": "old"},
            current_extra={"skill_pack_id": HALF_NARRATED_PACK_ID},
        )
        self.assertEqual("modern", merged["visual_style"])
        self.assertEqual(HALF_NARRATED_PACK_ID, merged["extra"]["skill_pack_id"])

    def test_unknown_pack_id_rejected(self):
        with self.assertRaises(UnknownSkillPackError):
            validate_skill_pack_id("not-a-real-pack")
        with self.assertRaises(UnknownSkillPackError):
            persist_project_settings({}, {"skill_pack_id": "not-a-real-pack"})

    def test_empty_skill_pack_id_clears_binding(self):
        merged = persist_project_settings(
            None,
            {"skill_pack_id": ""},
            current_settings={"extra": {"skill_pack_id": HALF_NARRATED_PACK_ID, "keep": 1}},
        )
        self.assertNotIn("skill_pack_id", merged.get("extra") or {})
        self.assertEqual(1, merged["extra"]["keep"])

    def test_resolve_prefers_payload_then_project(self):
        pack_id = resolve_skill_pack_id(
            payload={"skill_pack_id": HALF_NARRATED_PACK_ID},
            project={"extra": {"skill_pack_id": "ignored"}},
        )
        self.assertEqual(HALF_NARRATED_PACK_ID, pack_id)


class SkillPackPackingPromptTests(unittest.TestCase):
    def test_default_packing_system_prompt_forbids_timeranges(self):
        system = LlmService._h3_system_prompt("Ref2VA", "8")
        self.assertIn("Do NOT emit At HH:MM.SSS", system)
        self.assertIn("at most one camera move", system)
        self.assertIn("no timecodes", system)

    def test_pack_overrides_relax_timeranges_and_camera(self):
        reset_pack_cache()
        overrides = packing_overrides_of(HALF_NARRATED_PACK_ID)
        system = packing_system_prompt_for("Ref2VA", "8", HALF_NARRATED_PACK_ID)
        self.assertTrue(overrides["allow_timeranges"])
        self.assertTrue(overrides["faithful_zh_pack"])
        self.assertTrue(overrides["skip_program_pack"])
        self.assertIn("00:00–00:05", system)
        self.assertIn("more than one move", system)
        self.assertIn("only schedule", system)
        self.assertNotIn("Do NOT emit At HH:MM.SSS", system)

    def test_workshop_default_prompt_does_not_call_llm(self):
        with patch.object(LlmService, "_request_h3_prompt") as request:
            prompt = run_workshop_prompt({
                "dialogue": "你好。",
                "ref_images": [{"index": 1}, {"index": 2}],
            })
        request.assert_not_called()
        self.assertIn("[Shot 1]", prompt)
        self.assertIn("你好。", prompt)
        self.assertIn(_THICKNESS_PAD, prompt)

    def test_workshop_half_narrated_raises_when_author_fails(self):
        beat_info = {
            "skill_pack_id": HALF_NARRATED_PACK_ID,
            "dialogue": "你好。",
            "action": "她转身关上门。",
            "heading": "出租屋",
            "duration_seconds": 8,
            "ref_images": [{"index": 1, "category": "character"}, {"index": 2, "category": "scene"}],
            "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
            "scene": "出租屋",
            "scene_id": "s1",
        }
        with patch.object(LlmService, "author_timestamped_zh_prompt", side_effect=RuntimeError("llm off")):
            with self.assertRaises(RuntimeError):
                run_workshop_prompt(beat_info)
        self.assertFalse(str(beat_info.get("h3_prompt") or "").strip())
        self.assertNotIn(_THICKNESS_PAD, str(beat_info.get("h3_prompt") or ""))
        self.assertNotEqual("skeleton", beat_info.get("timestamped_zh_fallback"))
        self.assertFalse(str(beat_info.get("timestamped_zh_prompt") or "").strip())

    def test_bind_r2v_slots_skips_full_triptych(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = {
            "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
            "scene": "出租屋",
            "scene_id": "s1",
            "triptych_url": "https://x/triptych.png",
            "triptych_panels": {"start": "https://x/start.png", "mid": "https://x/mid.png", "end": "https://x/end.png"},
        }
        slots = bind_r2v_slot_images(recipe, beat, [_scene_asset(name="出租屋")])
        sources = [item["source"] for item in slots]
        self.assertEqual(["characters"], sources)
        char_slot = next(item for item in slots if item["source"] == "characters")
        self.assertIn("设定板分格", char_slot["label"])
        self.assertIn("发型", char_slot["label"])
        self.assertFalse(slot_contains_full_triptych(slots, "https://x/triptych.png"))
        self.assertTrue(all(item.get("url") != "https://x/triptych.png" for item in slots))

    def test_bind_r2v_skips_empty_or_master_panel_urls(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        slots = bind_r2v_slot_images(
            recipe,
            {
                "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
                "scene": "出租屋",
                "triptych_url": "https://x/triptych.png",
                "triptych_panels": {
                    "start": "https://x/start.png",
                    "mid": "https://x/triptych.png",
                    "end": "",
                },
            },
            [],
        )
        sources = [item["source"] for item in slots]
        self.assertEqual(["characters"], sources)
        self.assertNotIn("triptych.mid", sources)
        self.assertNotIn("triptych.end", sources)

    def test_r2v_drops_mid_before_end_when_slots_exceed_nine(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        six = [{"id": f"c{i}", "name": f"角色{i}", "url": f"https://x/c{i}.png"} for i in range(6)]
        seven = six + [{"id": "c6", "name": "角色6", "url": "https://x/c6.png"}]
        panels = {
            "start": "https://x/start.png",
            "mid": "https://x/mid.png",
            "end": "https://x/end.png",
        }
        six_slots = bind_r2v_slot_images(
            recipe,
            {
                "characters": six,
                "scene": "走廊",
                "scene_id": "s-hall",
                "triptych_url": "https://x/triptych.png",
                "triptych_panels": panels,
            },
            [_scene_asset("s-hall", "走廊")],
        )
        six_sources = [item["source"] for item in six_slots]
        self.assertEqual(6, len(six_slots))
        self.assertEqual(["characters"] * 6, six_sources)
        seven_slots = bind_r2v_slot_images(
            recipe,
            {
                "characters": seven,
                "scene": "走廊",
                "scene_id": "s-hall",
                "triptych_url": "https://x/triptych.png",
                "triptych_panels": panels,
            },
            [_scene_asset("s-hall", "走廊")],
        )
        seven_sources = [item["source"] for item in seven_slots]
        self.assertEqual(7, len(seven_slots))
        self.assertEqual(["characters"] * 7, seven_sources)

    def test_r2v_inserts_prop_sheets_and_skips_empty_urls(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        assets = [
            {"id": "p1", "kind": "prop", "name": "旧木书箱", "extra": {"reference_url": "https://x/box.png"}},
            {"id": "p2", "kind": "prop", "name": "无图信", "extra": {}},
            {"id": "p3", "kind": "prop", "name": "铜锁", "image_url": "https://x/lock.png"},
        ]
        planned = expand_r2v_slot_plan(
            recipe,
            {
                "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
                "scene": "书房",
                "prop_ids": ["p1", "p2", "p3"],
                "triptych_url": "https://x/triptych.png",
                "triptych_panels": {
                    "start": "https://x/start.png",
                    "mid": "https://x/mid.png",
                    "end": "https://x/end.png",
                },
            },
            assets,
        )
        sources = [item["source"] for item in planned]
        self.assertIn("props", sources)
        prop_slots = [item for item in planned if item["source"] == "props"]
        self.assertEqual(["https://x/box.png", "https://x/lock.png"], [item["url"] for item in prop_slots])
        self.assertTrue(all("分格" in item["label"] for item in prop_slots))
        self.assertTrue(all("小物件" in item["label"] for item in prop_slots))
        self.assertEqual(2, len(prop_slots))
        names = [item["name"] for item in planned]
        self.assertIn("旧木书箱", names)
        self.assertIn("铜锁", names)
        self.assertNotIn("无图信", names)

    def test_r2v_keeps_four_prop_sheets_but_excludes_writing_only_images(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        assets = [
            {"id": "p1", "kind": "prop", "name": "古籍", "extra": {"reference_url": "https://x/book.png"}},
            {"id": "p2", "kind": "prop", "name": "电脑", "extra": {"reference_url": "https://x/pc.png"}},
            {"id": "p3", "kind": "prop", "name": "台灯", "extra": {"reference_url": "https://x/lamp.png"}},
            {"id": "p4", "kind": "prop", "name": "笔记本", "extra": {"reference_url": "https://x/nb.png"}},
        ]
        planned = expand_r2v_slot_plan(
            recipe,
            {
                "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
                "scene": "现代大学图书馆",
                "scene_id": "s1",
                "prop_ids": ["p1", "p2", "p3", "p4"],
                "triptych_url": "https://x/triptych.png",
                "triptych_panels": {
                    "start": "https://x/start.png",
                    "mid": "https://x/mid.png",
                    "end": "https://x/end.png",
                },
            },
            assets + [{"id": "s1", "kind": "scene", "name": "现代大学图书馆", "extra": {"master_url": "https://x/scene.png"}}],
        )
        prop_urls = [item["url"] for item in planned if item["source"] == "props"]
        self.assertEqual(
            ["https://x/book.png", "https://x/pc.png", "https://x/lamp.png", "https://x/nb.png"],
            prop_urls,
        )
        self.assertEqual(5, len(planned))
        self.assertEqual(["characters", "props", "props", "props", "props"], [item["source"] for item in planned])
        self.assertEqual([1, 2, 3, 4, 5], [item["index"] for item in planned])
        self.assertIn("只锁外形与材质", planned[1]["label"])
        self.assertIn("覆盖场景卡里同名陈设", planned[1]["label"])

    def test_r2v_skips_empty_character_url_so_indices_do_not_shift(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        planned = expand_r2v_slot_plan(
            recipe,
            {
                "character_ids": ["c1"],
                "scene": "现代大学图书馆",
                "scene_id": "s1",
            },
            [
                {
                    "id": "c1",
                    "kind": "character",
                    "name": "沈砚",
                    "extra": {
                        "identities": [{
                            "id": "old",
                            "description": "17岁古代少年，粗布长衫",
                            "image_url": "https://x/old.png",
                        }],
                    },
                },
                {"id": "s1", "kind": "scene", "name": "现代大学图书馆", "extra": {"master_url": "https://x/scene.png"}},
            ],
        )
        self.assertEqual([], planned)  # Scene cards are writing context, not R2V slots.

    def test_r2v_with_two_props_drops_mid_before_end(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        chars = [{"id": f"c{i}", "name": f"角色{i}", "url": f"https://x/c{i}.png"} for i in range(4)]
        assets = [
            {"id": "p1", "kind": "prop", "name": "剑", "extra": {"reference_url": "https://x/sword.png"}},
            {"id": "p2", "kind": "prop", "name": "信", "extra": {"reference_url": "https://x/letter.png"}},
            _scene_asset("s-hall", "走廊"),
        ]
        slots = bind_r2v_slot_images(
            recipe,
            {
                "characters": chars,
                "scene": "走廊",
                "scene_id": "s-hall",
                "prop_ids": ["p1", "p2"],
                "triptych_url": "https://x/triptych.png",
                "triptych_panels": {
                    "start": "https://x/start.png",
                    "mid": "https://x/mid.png",
                    "end": "https://x/end.png",
                },
            },
            assets,
        )
        sources = [item["source"] for item in slots]
        self.assertEqual(6, len(slots))
        self.assertEqual(2, sources.count("props"))
        self.assertNotIn("triptych.start", sources)
        self.assertNotIn("triptych.mid", sources)
        self.assertNotIn("triptych.end", sources)

    def test_zh_author_images_include_prop_sheets(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        urls = collect_zh_author_image_urls(
            recipe,
            {
                "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
                "scene": "书房",
                "scene_id": "s1",
                "prop_ids": ["p1"],
                "triptych_url": "https://x/triptych.png",
            },
            [
                {"id": "c1", "name": "沈砚", "extra": {"avatar_url": "https://x/char.png"}},
                {"id": "s1", "name": "书房", "extra": {"master_url": "https://x/scene.png"}},
                {"id": "p1", "kind": "prop", "name": "旧木书箱", "extra": {"reference_url": "https://x/box.png"}},
            ],
        )
        self.assertIn("https://x/char.png", urls)
        self.assertIn("https://x/scene.png", urls)
        self.assertIn("https://x/box.png", urls)
        self.assertIn("https://x/triptych.png", urls)

    def test_zh_author_images_keep_full_triptych(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        urls = collect_zh_author_image_urls(
            recipe,
            {
                "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
                "scene": "出租屋",
                "scene_id": "s1",
                "triptych_url": "https://x/triptych.png",
                "triptych_panels": {
                    "start": "https://x/start.png",
                    "mid": "https://x/mid.png",
                    "end": "https://x/end.png",
                },
            },
            [
                {"id": "c1", "name": "沈砚", "extra": {"avatar_url": "https://x/char.png"}},
                {"id": "s1", "name": "出租屋", "extra": {"master_url": "https://x/scene.png"}},
            ],
        )
        self.assertIn("https://x/char.png", urls)
        self.assertIn("https://x/scene.png", urls)
        self.assertIn("https://x/triptych.png", urls)
        self.assertIn("https://x/start.png", urls)

    def test_official_h3_template_fill_starts_at_zero_and_uses_pictures(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        text = fill_timestamped_zh_prompt(
            recipe,
            {
                "sequence": 3,
                "heading": "出租屋对峙",
                "action": "她转身关上门。",
                "camera": "固定机位",
                "dialogue": "你好。",
                "duration_seconds": 8,
                "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
                "scene": "出租屋",
                "scene_id": "s1",
                "triptych_panels": {"start": "https://x/start.png"},
            },
            [_scene_asset("s1", "出租屋")],
            recipe.reference_text("h3-video-prompt-template.md"),
        )
        self.assertIn("内部时间从00:00开始", text)
        self.assertIn("<Picture", text)
        self.assertNotIn("@Image", text)
        self.assertNotIn("【编号】", text)
        self.assertIn("沈砚角色卡", text)
        self.assertIn("设定板分格", text)
        self.assertIn("出租屋", text)
        self.assertNotIn("<Picture 2>", text)
        self.assertIn("起幅", text)
        self.assertIn("镜头目的", text)
        self.assertIn("参考素材", text)
        self.assertIn("必须出现的视觉内容", text)
        self.assertIn("按旁白和画面内容切镜", text)
        self.assertIn("对白", text)
        self.assertIn("旁白", text)
        self.assertIn("画面要求", text)
        self.assertIn("负向约束", text)
        self.assertRegex(text, r"00:00\s*[–\-]\s*00:")
        self.assertIn("场景卡、三联母图和三张裁切格都不上传本地 H3", text)
        self.assertIn("不得声明为 Picture", text)
        self.assertIn("本镜无第三人称旁白", text)
        self.assertIn("（开口）：你好。", text)
        self.assertIn("不要用内心或开口句充数", recipe.reference_text("h3-video-prompt-template.md"))

    def test_workshop_half_narrated_raises_when_start_frame_author_fails(self):
        with patch.object(LlmService, "author_timestamped_zh_prompt", side_effect=RuntimeError("llm off")):
            with self.assertRaises(RuntimeError):
                run_workshop_prompt({
                    "skill_pack_id": HALF_NARRATED_PACK_ID,
                    "dialogue": "你好。",
                    "action": "她转身关上门。",
                    "heading": "出租屋",
                    "duration_seconds": 8,
                    "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
                    "scene": "出租屋",
                    "scene_id": "s1",
                    "triptych_panels": {"start": "https://x/start.png"},
                    "assets": [
                        {"id": "c1", "name": "沈砚", "extra": {"avatar_url": "https://x/char.png"}},
                        {"id": "s1", "name": "出租屋", "extra": {"master_url": "https://x/scene.png"}},
                    ],
                })

    def test_extract_triptych_panels_from_bytes_without_upload(self):
        import io

        from PIL import Image

        image = Image.new("RGB", (30, 10), (0, 0, 0))
        for x in range(10):
            image.putpixel((x, 0), (255, 0, 0))
            image.putpixel((x + 10, 0), (0, 255, 0))
            image.putpixel((x + 20, 0), (0, 0, 255))
        panels = split_triptych_image(image)
        self.assertEqual((10, 10), panels["start"].size)
        self.assertEqual((10, 10), panels["mid"].size)
        self.assertEqual((10, 10), panels["end"].size)
        self.assertEqual((255, 0, 0), panels["start"].getpixel((0, 0)))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=95)
        ctx = StepContext(recipe=get_pack(HALF_NARRATED_PACK_ID), beat={"id": "b1"})
        ctx.data["triptych_bytes"] = buffer.getvalue()
        ctx.options["store_panels"] = False
        extract_triptych_panels(ctx)
        stored = ctx.beat_updates["triptych_panels"]
        self.assertTrue(stored["start"].startswith("memory:start:"))
        self.assertTrue(stored["mid"].startswith("memory:mid:"))
        self.assertTrue(stored["end"].startswith("memory:end:"))

    def test_extract_triptych_panels_recrops_when_mid_or_end_missing(self):
        ctx = StepContext(
            recipe=get_pack(HALF_NARRATED_PACK_ID),
            beat={
                "id": "b1",
                "triptych_url": "https://x/triptych.png",
                "triptych_panels": {"start": "https://x/start.png"},
            },
        )
        ctx.options["store_panels"] = False
        with patch(
            "backend.app.skill_packs.handlers.split_triptych_url",
            return_value={"start": b"aaa", "mid": b"bbbb", "end": b"ccccc"},
        ) as split:
            extract_triptych_panels(ctx)
        split.assert_called_once_with("https://x/triptych.png")
        stored = ctx.beat_updates["triptych_panels"]
        self.assertTrue(stored["mid"].startswith("memory:mid:"))
        self.assertTrue(stored["end"].startswith("memory:end:"))

    @patch("backend.app.media_studio.services.storyboard_image_service.StoryboardImageService.enqueue")
    def test_generate_shot_triptych_enqueues_16x9_stage(self, enqueue):
        enqueue.return_value = {"job_id": "job-triptych", "beat_id": "b1", "status": "queued"}
        ctx = StepContext(
            recipe=get_pack(HALF_NARRATED_PACK_ID),
            project_id="p1",
            episode_id="e1",
            beat_id="b1",
            beat={"id": "b1", "character_ids": ["c1"], "scene": "出租屋", "scene_id": "s1"},
        )
        ctx.options["enqueue_images"] = True
        generate_shot_triptych(ctx)
        enqueue.assert_called_once()
        self.assertEqual("triptych", enqueue.call_args.args[4])
        self.assertEqual("job-triptych", ctx.beat_updates["triptych_job_id"])

    def test_storyboard_canvas_and_stage_guard(self):
        self.assertEqual(("16:9", "2K", 2048, 1152), StoryboardImageService._stage_canvas("triptych"))
        self.assertEqual(("2:3", "1K", 768, 1152), StoryboardImageService._stage_canvas("sketch"))
        with self.assertRaisesRegex(ValueError, "sketch、render 或 triptych"):
            StoryboardImageService.enqueue("p", "e", "b", {}, "nope")


def _shot2_author_zh() -> str:
    return """镜头2，总时长12秒，内部时间从00:00开始。
镜头目的：吴耐免租，沙丽丽听完再问，再双手护胸。

参考素材：
- <Picture 1> 吴耐角色卡，提供身份与外形连续性（只锁脸、发型和服装，不锁姿势；禁止把设定板分格、白底或重复小人带进镜头）
- <Picture 2> 沙丽丽角色卡，提供身份与外形连续性（只锁脸、发型和服装，不锁姿势；禁止把设定板分格、白底或重复小人带进镜头）

必须出现的视觉内容：
- 轿厢内已站定，不要开门
- 吴耐挥手免租
- 沙丽丽听完再问并护胸

按旁白和画面内容切镜：
- 00:00–00:04：吴耐挥手免租，说「算了，房租免了。」
- 00:04–00:08：沙丽丽听完再问，「啊？大爷你不要房租？」
- 00:08–00:12：双手护胸，「该不会想让我那啥吧？」

对白：
- 吴耐在 00:00–00:04 说：“算了，房租免了。”
- 沙丽丽在 00:04–00:08 说：“啊？大爷你不要房租？”
- 沙丽丽在 00:08–00:12 说：“该不会想让我那啥吧？”

旁白：
- 本镜可无旁白；旁白/内心时段人物嘴唇闭合

画面要求：
- 已在电梯轿厢内站定
- 真人实拍短剧摄影
- 场景与三联只转写成环境、起幅、主动作和落幅文字

负向约束：
- 不要插画、CG、文字、水印、美颜滤镜、人物消失、瞬移、反射重影
- 场景卡和三联不上传本地 H3；成片必须是单一 9:16，不许分栏、不许把三格同时摆进画面
"""


def _shot2_author_en() -> str:
    return """subject_definitions:
<Subject 1> is locked by <Picture 1>. <Subject 2> is locked by <Picture 2>. The lift, opening, action, and closing composition are described only in text.
summary:
[Shot 1] Wu Nai waves off the rent while Sha Lili listens, then asks, then covers her chest.
retention_analysis:
fully_preserved.
detailed_description:
[Shot 1] The camera holds. <d>[Chinese] 算了，房租免了。</d> Then Sha Lili asks <d>[Chinese] 啊？大爷你不要房租？</d> Then she covers her chest <d>[Chinese] 该不会想让我那啥吧？</d>
overall_soundscape:
Quiet lift.
non_diegetic_music:
None.
"""


def _shot2_author_raw() -> str:
    return f"{ZH_BLOCK_MARK}\n{_shot2_author_zh()}\n{EN_BLOCK_MARK}\n{_shot2_author_en()}"


def _shot2_author_beat() -> dict:
    return {
        "id": "b2",
        "sequence": 2,
        "story_shot": 2,
        "heading": "电梯免租",
        "action": "吴耐挥手免租。沙丽丽听完再问，双手护胸。",
        "camera": "固定机位，必要时小幅度慢速运镜。",
        "duration_seconds": 12,
        "dialogue": "吴耐：“算了，房租免了。” 沙丽丽：“啊？大爷你不要房租？” 沙丽丽：“该不会想让我那啥吧？”",
        "dialogue_turns": [
            {"speaker": "吴耐", "text": "算了，房租免了。"},
            {"speaker": "沙丽丽", "text": "啊？大爷你不要房租？"},
            {"speaker": "沙丽丽", "text": "该不会想让我那啥吧？"},
        ],
        "characters": [
            {"id": "c-wu", "name": "吴耐", "url": "https://x/wu.png"},
            {"id": "c-sha", "name": "沙丽丽", "url": "https://x/sha.png"},
        ],
        "scene": "电梯",
        "scene_id": "s-el",
        "triptych_url": "https://x/triptych.png",
        "triptych_panels": {"start": "https://x/start.png", "mid": "https://x/mid.png", "end": "https://x/end.png"},
    }


def _shot2_author_assets() -> list[dict]:
    return [
        {"id": "c-wu", "name": "吴耐", "extra": {"avatar_url": "https://x/wu.png", "description": "老年男人"}},
        {"id": "c-sha", "name": "沙丽丽", "extra": {"avatar_url": "https://x/sha.png", "description": "年轻女人"}},
        {"id": "s-el", "name": "电梯", "extra": {"master_url": "https://x/scene.png"}},
    ]


def _shot1_author_beat() -> dict:
    return {
        "id": "b1",
        "sequence": 1,
        "story_shot": 1,
        "heading": "电梯厅讨好",
        "action": "先上摇沙丽丽求情，再下摇看衣服内心，最后推近吴耐开口。",
        "camera": "上摇、下摇、短推",
        "duration_seconds": 15,
        "dialogue": (
            "沙丽丽：“大爷，我什么都可以做。那个，那个房租下个月一定给你。” "
            "吴耐（内心）：“浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。” "
            "吴耐：“不用想也知道，做的是什么。”"
        ),
        "characters": [
            {"id": "c-wu", "name": "吴耐", "url": "https://x/wu.png"},
            {"id": "c-sha", "name": "沙丽丽", "url": "https://x/sha.png"},
        ],
        "scene": "走廊",
        "scene_id": "s-el",
        "triptych_url": "https://x/triptych.png",
        "triptych_panels": {"start": "https://x/start.png", "mid": "https://x/mid.png", "end": "https://x/end.png"},
    }


def _shot1_wrong_zh() -> str:
    inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
    spoken_a = "大爷，我什么都可以做。"
    spoken_b = "那个，那个房租下个月一定给你。"
    spoken_c = "不用想也知道，做的是什么。"
    return f"""镜头1，总时长15秒，内部时间从00:00开始。
镜头目的：沙丽丽讨好求情，吴耐内心判断后冷脸回应。

参考素材：
- <Picture 1> 吴耐角色卡
- <Picture 2> 沙丽丽角色卡

必须出现的视觉内容：
- 9楼电梯厅
- 沙丽丽红吊带与黑裙
- 吴耐冷脸

按旁白和画面内容切镜：
- 00:00–00:02：腰部起幅，第三人称旁白响起。
- 00:02–00:05：上摇到脸，沙丽丽开口。
- 00:05–00:07：她说完第二句。
- 00:07–00:10：下摇到衣服，内心画外音。
- 00:10–00:14：短推吴耐开口。
- 00:14–00:15：定格。

对白：
- 沙丽丽在00:02–00:05说：“{spoken_a}”
- 沙丽丽在00:05–00:07说：“{spoken_b}”
- 吴耐在00:10–00:14说：“{spoken_c}”

旁白：
- 00:00–00:02第三人称旁白：“{inner}”
- 00:07–00:10吴耐内心画外音：“{spoken_c}”

画面要求：
- 竖屏9:16单镜到底

负向约束：
- 不要插画、字幕、水印
"""


def _shot1_fixed_zh() -> str:
    inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
    spoken_a = "大爷，我什么都可以做。"
    spoken_b = "那个，那个房租下个月一定给你。"
    spoken_c = "不用想也知道，做的是什么。"
    return f"""镜头1，总时长15秒，内部时间从00:00开始。
镜头目的：沙丽丽讨好求情，吴耐内心判断后冷脸回应。

参考素材：
- <Picture 1> 吴耐角色卡
- <Picture 2> 沙丽丽角色卡

必须出现的视觉内容：
- 9楼电梯厅
- 沙丽丽红吊带与黑裙
- 吴耐冷脸

按旁白和画面内容切镜：
- 00:00–00:02：腰部起幅上摇，画内闭嘴。
- 00:02–00:05：上摇到脸，沙丽丽开口。
- 00:05–00:07：她说完第二句。
- 00:07–00:10：下摇到衣服，吴耐内心。
- 00:10–00:14：短推吴耐开口。
- 00:14–00:15：定格。

对白：
- 沙丽丽在 00:02–00:05 说：“{spoken_a}”
- 沙丽丽在 00:05–00:07 说：“{spoken_b}”
- 吴耐在 00:07–00:10（内心）：“{inner}”
- 吴耐在 00:10–00:14 说：“{spoken_c}”

旁白：
- 本镜无第三人称旁白。角色内心写在对白里，标（内心）。

画面要求：
- 竖屏9:16单镜到底

负向约束：
- 不要插画、字幕、水印
"""


def _shot1_wrong_en() -> str:
    inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
    spoken_a = "大爷，我什么都可以做。"
    spoken_b = "那个，那个房租下个月一定给你。"
    spoken_c = "不用想也知道，做的是什么。"
    return f"""subject_definitions:
<Picture 1> Wu Nai. <Picture 2> Sha Lili. The corridor and composition are text-only.
summary:
A 15-second corridor beat.
retention_analysis:
fully_preserved.
detailed_description:
[Shot 1] 00:00-00:02 A third-person voiceover says in an off-screen voiceover: <d>[Chinese] {inner}</d> while all visible characters' lips remain completely closed.
00:02-00:05 Sha Lili (S2) says: <d>[Chinese] {spoken_a}</d>
00:05-00:07 Sha Lili (S2) says: <d>[Chinese] {spoken_b}</d>
00:07-00:10 An off-screen inner voice says in an off-screen voiceover: <d>[Chinese] {spoken_c}</d> while all visible characters' lips remain completely closed.
00:10-00:14 Wu Nai (S1) says: <d>[Chinese] {spoken_c}</d>
overall_soundscape:
Quiet corridor.
non_diegetic_music:
None.
"""


def _shot1_tilt_down_inner_zh() -> str:
    inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
    spoken_a = "大爷，我什么都可以做。"
    spoken_b = "那个，那个房租下个月一定给你。"
    spoken_c = "不用想也知道，做的是什么。"
    return f"""镜头1，总时长15秒，内部时间从00:00开始。
镜头目的：沙丽丽讨好求情，吴耐下摇看衣服时内心判断，再冷脸开口。

参考素材：
- <Picture 1> 吴耐角色卡
- <Picture 2> 沙丽丽角色卡

必须出现的视觉内容：
- 9楼电梯厅
- 沙丽丽红吊带与黑裙
- 吴耐冷脸

按旁白和画面内容切镜：
- 00:00–00:02.50：腰部起幅上摇，沙丽丽开口说“{spoken_a}”。
- 00:02.50–00:05.50：上摇到脸，沙丽丽说“{spoken_b}”。
- 00:05.50–00:09.50：下摇看衣服，吴耐内心“{inner}”，画内闭嘴。
- 00:09.50–00:11.50：停在胸腰，两人闭嘴。
- 00:11.50–00:14.00：短推吴耐开口“{spoken_c}”。
- 00:14.00–00:00:15.00：定格。

对白：
- 沙丽丽在 00:00–00:02.50（开口）：“{spoken_a}”
- 沙丽丽在 00:02.50–00:05.50（开口）：“{spoken_b}”
- 吴耐在 00:05.50–00:09.50（内心）：“{inner}”
- 吴耐在 00:11.50–00:14.00（开口）：“{spoken_c}”

旁白：
- 本镜无第三人称旁白。角色内心写在对白里，标（内心）。

画面要求：
- 竖屏9:16单镜到底

负向约束：
- 不要插画、字幕、水印
"""


def _shot1_tilt_down_inner_en() -> str:
    inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
    spoken_a = "大爷，我什么都可以做。"
    spoken_b = "那个，那个房租下个月一定给你。"
    spoken_c = "不用想也知道，做的是什么。"
    return f"""subject_definitions:
<Picture 1> Wu Nai. <Picture 2> Sha Lili. The corridor and composition are text-only.
summary:
A 15-second corridor beat.
retention_analysis:
fully_preserved.
detailed_description:
[Shot 1] 00:00-00:02.50 Sha Lili (S2) says: <d>{spoken_a}</d>
00:02.50-00:05.50 Sha Lili (S2) says: <d>{spoken_b}</d>
00:05.50-00:09.50 An off-screen inner voice (not produced by the on-screen mouth) says in an off-screen voiceover: <d>{inner}</d> while all visible characters' lips remain completely closed.
00:11.50-00:14.00 Wu Nai (S1) says: <d>{spoken_c}</d>
overall_soundscape:
Quiet corridor.
non_diegetic_music:
None.
"""


def _shot1_fixed_en() -> str:
    inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
    spoken_a = "大爷，我什么都可以做。"
    spoken_b = "那个，那个房租下个月一定给你。"
    spoken_c = "不用想也知道，做的是什么。"
    return f"""subject_definitions:
<Picture 1> Wu Nai. <Picture 2> Sha Lili. The corridor and composition are text-only.
summary:
A 15-second corridor beat.
retention_analysis:
fully_preserved.
detailed_description:
[Shot 1] Sha Lili (S2) says: <d>[Chinese] {spoken_a}</d> Sha Lili (S2) says: <d>[Chinese] {spoken_b}</d>
An off-screen inner voice (not produced by the on-screen mouth) says in an off-screen voiceover: <d>[Chinese] {inner}</d> while all visible characters' lips remain completely closed.
Wu Nai (S1) says: <d>[Chinese] {spoken_c}</d>
overall_soundscape:
Quiet corridor.
non_diegetic_music:
None.
"""


class SkillPackZhAuthorTests(unittest.TestCase):
    def test_llm_author_splits_multi_turn_dialogue_across_ranges(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = _shot2_author_beat()
        ctx = StepContext(recipe=recipe, beat=beat, assets=_shot2_author_assets())
        with patch.object(
            LlmService,
            "_complete_zh_author",
            return_value=(_shot2_author_raw(), VisionCallMeta(status="unavailable")),
        ) as chat:
            write_timestamped_zh_prompt(ctx)
        chat.assert_called()
        text = ctx.beat_updates["timestamped_zh_prompt"]
        self.assertNotEqual("skeleton", ctx.data.get("timestamped_zh_fallback"))
        rent = [line for line in text.splitlines() if "00:" in line and "房租免了" in line]
        ask = [line for line in text.splitlines() if "00:" in line and "不要房租" in line]
        chest = [line for line in text.splitlines() if "00:" in line and "护胸" in line]
        self.assertTrue(rent)
        self.assertTrue(ask)
        self.assertTrue(chest)
        self.assertNotEqual(rent[0], ask[0])
        self.assertNotEqual(ask[0], chest[0])
        self.assertGreaterEqual(len({line.strip() for line in rent + ask + chest}), 3)

    def test_vlm_disabled_still_uses_text_llm(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = _shot2_author_beat()
        with patch.object(
            LlmService,
            "_complete_zh_author",
            return_value=(_shot2_author_raw(), VisionCallMeta(status="unavailable", model="7b", image_count=4)),
        ) as chat:
            result = LlmService.author_timestamped_zh_prompt(
                recipe,
                beat,
                _shot2_author_assets(),
                recipe.reference_text("h3-video-prompt-template.md"),
            )
        chat.assert_called()
        self.assertIn("算了，房租免了。", result.zh_prompt)
        self.assertNotIn("<Picture 3>", result.zh_prompt)

    def test_write_timestamped_stores_dual_en_and_vision(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = _shot2_author_beat()
        packed = (
            "subject_definitions:\n<Subject 1> is locked by <Picture 1>.\n"
            "summary:\n[Shot 1] A short beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n[Shot 1] 算了，房租免了。\n"
            "overall_soundscape:\nQuiet lift.\n"
            "non_diegetic_music:\nNone."
        )
        result = DualShotAuthorResult(
            zh_prompt=_shot2_author_zh(),
            en_prompt=packed,
            en_valid=True,
            vision=VisionCallMeta(status="used", model="gpt-5.6-sol", image_count=5, source="llm"),
        )
        ctx = StepContext(recipe=recipe, beat=beat, assets=_shot2_author_assets(), beat_info={})
        with patch.object(LlmService, "author_timestamped_zh_prompt", return_value=result):
            write_timestamped_zh_prompt(ctx)
        self.assertEqual(packed, ctx.data.get("authored_en_prompt"))
        self.assertTrue(ctx.data.get("authored_en_valid"))
        self.assertEqual("used", ctx.data.get("vision_status"))
        self.assertEqual("gpt-5.6-sol", ctx.data.get("vision_model"))
        self.assertEqual(5, ctx.data.get("vision_image_count"))
        self.assertEqual(packed, ctx.data.get("h3_prompt"))

    def test_polish_ref2va_keeps_authored_en_when_skip_program_pack(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        authored = (
            "subject_definitions:\n<picture 1> lead. <picture 2> corridor. <picture 3> start.\n"
            "summary:\n[reference generation] A beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n[Shot 1] The camera tracks down the corridor. <d>[Chinese] 你好。</d>\n"
            "overall_soundscape:\nCorridor hum.\n"
            "non_diegetic_music:\nNone."
        )
        ctx = StepContext(
            recipe=recipe,
            beat={"dialogue": "你好。", "authored_en_prompt": authored},
            data={
                "authored_en_prompt": authored,
                "timestamped_zh_prompt": "镜头目的：走廊\n00:00–00:08 开口",
            },
            beat_info={
                "dialogue": "你好。",
                "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            },
        )
        polish_ref2va(ctx)
        prompt = ctx.data["h3_prompt"]
        self.assertIn("The camera tracks down the corridor", prompt)
        self.assertIn("<Picture 1>", prompt)
        self.assertNotIn("The camera holds a stable medium composition", prompt)
        self.assertNotIn("Already inside the closed cabin", prompt)
        self.assertNotRegex(prompt, r"00:00\s*[–\-]\s*00:")
        self.assertNotIn(_THICKNESS_PAD, prompt)

    def test_polish_ref2va_raises_when_skip_program_pack_without_authored_en(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        ctx = StepContext(
            recipe=recipe,
            beat={"dialogue": "你好。"},
            data={"timestamped_zh_prompt": "镜头目的：走廊\n00:00–00:08 开口"},
            beat_info={
                "dialogue": "你好。",
                "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            },
        )
        with self.assertRaises(DualShotAuthorError) as raised:
            polish_ref2va(ctx)
        self.assertIn("英文六段", str(raised.exception))
        self.assertNotIn("h3_prompt", ctx.beat_updates)
        self.assertNotIn(_THICKNESS_PAD, str(ctx.data.get("h3_prompt") or ""))

    def test_dual_author_skips_prepare_when_skip_program_pack(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = {
            "dialogue": "你好。",
            "duration_seconds": 8,
            "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
            "scene": "走廊",
            "scene_id": "s1",
            "triptych_panels": {"start": "https://x/start.png"},
        }
        assets = [
            {"id": "c1", "name": "沈砚", "extra": {"avatar_url": "https://x/char.png"}},
            {"id": "s1", "name": "走廊", "extra": {"master_url": "https://x/scene.png"}},
        ]
        zh = (
            "镜头目的：走走廊\n参考素材：<Picture 1>\n"
            "必须出现的视觉内容：走廊\n"
            "按旁白和画面内容切镜：00:00–00:08 开口\n对白：你好。\n旁白：无\n"
            "画面要求：9:16\n负向约束：无分栏"
        )
        en = (
            "subject_definitions:\n<picture 1> lead. The corridor and composition are text-only.\n"
            "summary:\n[reference generation] A beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n[Shot 1] The camera tracks down the corridor. <d>[Chinese] 你好。</d>\n"
            "overall_soundscape:\nCorridor hum.\n"
            "non_diegetic_music:\nNone."
        )
        raw = f"{ZH_BLOCK_MARK}\n{zh}\n{EN_BLOCK_MARK}\n{en}"
        with patch.object(
            LlmService,
            "_complete_zh_author",
            return_value=(raw, VisionCallMeta(status="unavailable")),
        ):
            result = LlmService.author_timestamped_zh_prompt(
                recipe,
                beat,
                assets,
                recipe.reference_text("h3-video-prompt-template.md"),
            )
        self.assertTrue(result.en_valid)
        self.assertIn("The camera tracks down the corridor", result.en_prompt)
        self.assertIn("<Picture 1>", result.en_prompt)
        self.assertNotIn("The camera holds a stable medium composition", result.en_prompt)
        self.assertNotIn("Already inside the closed cabin", result.en_prompt)
        self.assertNotRegex(result.en_prompt, r"00:00\s*[–\-]\s*00:")
        self.assertNotIn(_THICKNESS_PAD, result.en_prompt)

    def test_dual_author_accepts_colonless_en_headings_when_skip_program_pack(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = {
            "dialogue": "你好。",
            "duration_seconds": 8,
            "characters": [{"id": "c1", "name": "沈砚", "url": "https://x/char.png"}],
            "scene": "走廊",
            "scene_id": "s1",
            "triptych_panels": {"start": "https://x/start.png"},
        }
        assets = [
            {"id": "c1", "name": "沈砚", "extra": {"avatar_url": "https://x/char.png"}},
            {"id": "s1", "name": "走廊", "extra": {"master_url": "https://x/scene.png"}},
        ]
        zh = (
            "镜头目的：走走廊\n参考素材：<Picture 1>\n"
            "必须出现的视觉内容：走廊\n"
            "按旁白和画面内容切镜：00:00–00:08 开口\n对白：你好。\n旁白：无\n"
            "画面要求：9:16\n负向约束：无分栏"
        )
        en = (
            "subject_definitions\n<picture 1> lead. The corridor and composition are text-only.\n"
            "summary\n[reference generation] A beat.\n"
            "retention_analysis\nfully_preserved.\n"
            "detailed_description\n[Shot 1] The camera tracks down the corridor. <d>[Chinese] 你好。</d>\n"
            "overall_soundscape\nCorridor hum.\n"
            "non_diegetic_music\nNone."
        )
        raw = f"{ZH_BLOCK_MARK}\n{zh}\n{EN_BLOCK_MARK}\n{en}"
        with patch.object(
            LlmService,
            "_complete_zh_author",
            return_value=(raw, VisionCallMeta(status="unavailable")),
        ):
            result = LlmService.author_timestamped_zh_prompt(
                recipe,
                beat,
                assets,
                recipe.reference_text("h3-video-prompt-template.md"),
            )
        self.assertTrue(result.en_valid)
        self.assertRegex(result.en_prompt, r"(?m)^subject_definitions:")
        self.assertRegex(result.en_prompt, r"(?m)^non_diegetic_music:")
        self.assertIn("<Picture 1>", result.en_prompt)
        self.assertEqual(
            [],
            LlmService._validate_h3_prompt(
                result.en_prompt,
                "Ref2VA",
                {"dialogue": "你好。", "ref_images": [{"index": 1}], "skill_pack_id": HALF_NARRATED_PACK_ID},
            ),
        )

    def test_polish_ref2va_canonicalizes_colonless_headings_when_skip_program_pack(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        authored = (
            "subject_definitions\n<picture 1> lead. <picture 2> corridor. <picture 3> start.\n"
            "summary\n[reference generation] A beat.\n"
            "retention_analysis\nfully_preserved.\n"
            "detailed_description\n[Shot 1] The camera tracks down the corridor. <d>[Chinese] 你好。</d>\n"
            "overall_soundscape\nCorridor hum.\n"
            "non_diegetic_music\nNone."
        )
        ctx = StepContext(
            recipe=recipe,
            beat={"dialogue": "你好。", "authored_en_prompt": authored},
            data={
                "authored_en_prompt": authored,
                "timestamped_zh_prompt": "镜头目的：走廊\n00:00–00:08 开口",
            },
            beat_info={
                "dialogue": "你好。",
                "ref_images": [{"index": 1}, {"index": 2}, {"index": 3}],
            },
        )
        polish_ref2va(ctx)
        prompt = ctx.data["h3_prompt"]
        self.assertRegex(prompt, r"(?m)^subject_definitions:")
        self.assertRegex(prompt, r"(?m)^non_diegetic_music:")
        self.assertIn("<Picture 1>", prompt)
        self.assertNotIn(_THICKNESS_PAD, prompt)

    def test_llm_author_failure_does_not_fill_skeleton(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = _shot2_author_beat()
        ctx = StepContext(recipe=recipe, beat=beat, assets=_shot2_author_assets())
        with patch.object(LlmService, "author_timestamped_zh_prompt", side_effect=RuntimeError("llm down")):
            with self.assertRaises(RuntimeError):
                write_timestamped_zh_prompt(ctx)
        self.assertNotIn("timestamped_zh_prompt", ctx.beat_updates)
        self.assertNotEqual("skeleton", ctx.data.get("timestamped_zh_fallback"))
        self.assertFalse(str(ctx.data.get("h3_prompt") or "").strip())
        self.assertNotIn(_THICKNESS_PAD, str(ctx.data.get("h3_prompt") or ""))

    def test_dual_author_system_omits_packer_and_requires_dual_blocks(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        system = build_dual_author_system(recipe, "镜头目的：\n")
        zh_system = build_timestamped_zh_author_system(recipe, "镜头目的：\n")
        self.assertNotIn("Do not emit <d>", system)
        self.assertNotIn("Return only the finished prompt", system)
        self.assertNotIn("Write all six sections in English", system)
        self.assertNotIn("{{Dn}}", system)
        self.assertIn(ZH_BLOCK_MARK, system)
        self.assertIn(EN_BLOCK_MARK, system)
        self.assertIn("<d>", system)
        self.assertIn("subject_definitions:", system)
        self.assertIn("non_diegetic_music:", system)
        self.assertIn("英文冒号", system)
        self.assertIn("detailed_description", system)
        self.assertIn("设定板分格", system)
        self.assertIn("重复小物件", system)
        self.assertIn("重复小物件", zh_system)
        self.assertIn("成片必须是单一 9:16", system)
        self.assertIn("三张 9:16 裁切格", system)
        self.assertIn("分秒构图文字", system)
        self.assertIn("整张 16:9 三联", system)
        self.assertIn("只锁脸、发型和服装", zh_system)
        self.assertIn(ZH_BLOCK_MARK, zh_system)
        self.assertIn(EN_BLOCK_MARK, zh_system)
        self.assertNotIn("Do not emit <d>", zh_system)
        self.assertNotIn("Return only the finished prompt", zh_system)
        self.assertNotIn("Seed Audio", system)
        self.assertNotIn("Design Image 2", system)
        self.assertNotIn("Final narration generation", system)
        self.assertNotIn("请先输出 <<<ZH>>> 官方八块中文分秒稿", system)
        self.assertIn("says in an off-screen voiceover", system)
        self.assertIn("lips remain completely closed", system)
        self.assertIn("禁止：Name says:", system)
        self.assertIn("三通道", system)
        self.assertIn("表演顺序", system)
        self.assertIn("本镜无第三人称旁白", system)
        self.assertIn("Three speech channels", system)
        self.assertIn("exactly one <d>", system)
        user = build_timestamped_zh_author_user(recipe, _shot2_author_beat(), _shot2_author_assets())
        self.assertIn("直接输出完整 <<<ZH>>>", user)
        self.assertIn("构图、调度和动作节奏", user)
        self.assertIn("写稿附图", user)
        self.assertIn("https://x/triptych.png", user)
        self.assertNotIn("<Picture 3>", user)
        self.assertIn("表演顺序", user)
        self.assertIn("1. 吴耐（开口）：算了，房租免了。", user)
        self.assertIn("本镜无第三人称旁白", user)
        self.assertNotIn("请先输出 <<<ZH>>> 官方八块中文分秒稿", user)
        inner_beat = {
            **_shot2_author_beat(),
            "dialogue": "吴耐（内心）：“浓妆艳抹。” 吴耐：“不用想也知道。”",
            "dialogue_turns": [
                {"speaker": "吴耐（内心）", "text": "浓妆艳抹。"},
                {"speaker": "吴耐", "text": "不用想也知道。"},
            ],
        }
        user_inner = build_timestamped_zh_author_user(recipe, inner_beat, _shot2_author_assets())
        self.assertIn("says in an off-screen voiceover", user_inner)
        self.assertIn("1. 吴耐（内心）：浓妆艳抹。", user_inner)
        self.assertIn("2. 吴耐（开口）：不用想也知道。", user_inner)

    def test_zh_author_user_includes_previous_shot_handoff(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = {
            **_shot2_author_beat(),
            "opening_state": "仍坐在书桌前",
            "closing_state": "伸手接书",
            "transition_note": "动作匹配切",
            "previous_shot": "落幅姿势：仍坐在书桌前，古籍滑向桌沿；切型：动作匹配切",
        }
        user = build_timestamped_zh_author_user(recipe, beat, _shot2_author_assets())
        self.assertIn("上一镜承接：落幅姿势：仍坐在书桌前，古籍滑向桌沿；切型：动作匹配切", user)
        self.assertIn("开场姿势（00:00 必须与此一致", user)
        self.assertIn("仍坐在书桌前", user)
        self.assertIn("切型：动作匹配切", user)

    def test_shot1_channel_contract_rejects_wrong_draft_and_accepts_fix(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = _shot1_author_beat()
        assets = _shot2_author_assets()
        system = build_dual_author_system(recipe, recipe.reference_text("h3-video-prompt-template.md"))
        user = build_timestamped_zh_author_user(recipe, beat, assets)
        self.assertIn("三通道", system)
        self.assertIn("表演顺序", user)
        self.assertIn("1. 沙丽丽（开口）：大爷，我什么都可以做。", user)
        self.assertIn("2. 沙丽丽（开口）：那个，那个房租下个月一定给你。", user)
        self.assertIn("3. 吴耐（内心）：浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。", user)
        self.assertIn("4. 吴耐（开口）：不用想也知道，做的是什么。", user)
        self.assertIn("本镜无第三人称旁白", user)
        self.assertIn("一个字都不要改", user)
        self.assertIn("<d>[Chinese]", user)
        self.assertIn("00:00 起幅只写画面或开口", user)
        inner = "浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。"
        poisoned = {
            **beat,
            "dialogue_turns": [
                {"speaker": "沙丽丽", "text": "大爷，我什么都可以做。"},
                {"speaker": "沙丽丽", "text": "那个，那个房租下个月一定给你。"},
                {"speaker": "吴耐", "text": "不用想也知道，做的是什么。"},
            ],
            "narration": inner,
        }
        poisoned_user = build_timestamped_zh_author_user(recipe, poisoned, assets)
        self.assertIn("本镜无第三人称旁白", poisoned_user)
        self.assertIn("一个字都不要改", poisoned_user)
        self.assertNotIn("旁白原文（只进「旁白」块", poisoned_user)
        self.assertIn("3. 吴耐（内心）：浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。", poisoned_user)
        self.assertEqual("", H3PromptBuilder.third_person_narration(poisoned))
        self.assertEqual("夜色笼罩走廊。", H3PromptBuilder.third_person_narration({
            **beat,
            "narration": "夜色笼罩走廊。",
        }))
        poisoned_wrong = validate_timestamped_zh_prompt(_shot1_wrong_zh(), recipe, poisoned, assets)
        self.assertTrue(any("旁白块不得写入开口或内心" in item for item in poisoned_wrong))
        skeleton = fill_timestamped_zh_prompt(
            recipe,
            beat,
            assets,
            recipe.reference_text("h3-video-prompt-template.md"),
        )
        dialogue_block, _, after_dialogue = skeleton.partition("旁白：")
        self.assertIn("吴耐（内心）：浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。", dialogue_block)
        self.assertIn("本镜无第三人称旁白", after_dialogue.split("画面要求：")[0])
        self.assertNotIn("浓妆艳抹", after_dialogue.split("画面要求：")[0])
        wrong = validate_timestamped_zh_prompt(_shot1_wrong_zh(), recipe, beat, assets)
        self.assertTrue(any("第三人称/第一人称旁白" in item for item in wrong))
        self.assertTrue(any("开口原文被标成内心" in item for item in wrong))
        self.assertTrue(any("旁白块不得写入开口或内心" in item for item in wrong))
        self.assertTrue(any("内心不要写在 00:00 起幅" in item for item in wrong))
        self.assertEqual([], validate_timestamped_zh_prompt(_shot1_fixed_zh(), recipe, beat, assets))
        decimal = _shot1_tilt_down_inner_zh()
        self.assertEqual([], validate_timestamped_zh_prompt(decimal, recipe, beat, assets))
        garbled = decimal.replace("参考素材：", "\ufffd\ufffd\ufffd考素材：", 1)
        self.assertEqual([], validate_timestamped_zh_prompt(garbled, recipe, beat, assets))
        stuffed = decimal.replace(
            "本镜无第三人称旁白。角色内心写在对白里，标（内心）。",
            "旁白原文：“浓妆艳抹，昼伏夜出，红色吊带，黑色小短裙。”",
        )
        stuffed_errors = validate_timestamped_zh_prompt(stuffed, recipe, beat, assets)
        self.assertTrue(any("旁白块不得写入开口或内心" in item for item in stuffed_errors))
        self.assertFalse(any("分秒未覆盖" in item for item in stuffed_errors))
        self.assertFalse(any("不同时间段" in item for item in stuffed_errors))
        beat_info = {
            "dialogue": beat["dialogue"],
            "skill_pack_id": HALF_NARRATED_PACK_ID,
            "ref_images": [{"index": i} for i in range(1, 3)],
        }
        wrong_en = LlmService._validate_h3_prompt(_shot1_wrong_en(), "Ref2VA", beat_info)
        self.assertTrue(any("duplicated" in item for item in wrong_en))
        self.assertTrue(any("performance order" in item for item in wrong_en))
        self.assertEqual([], LlmService._validate_h3_prompt(_shot1_fixed_en(), "Ref2VA", beat_info))
        self.assertEqual([], LlmService._validate_h3_prompt(_shot1_tilt_down_inner_en(), "Ref2VA", beat_info))

    def test_concatenated_same_speaker_lines_validate_per_sentence(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = {
            **_shot2_author_beat(),
            "duration_seconds": 13,
            "dialogue": (
                "吴耐：“算了，房租免了。” "
                "沙丽丽：“啊？大爷你不要房租？该不会想让我那啥吧？我是正经人，卖艺不卖身的。”"
            ),
        }
        beat.pop("dialogue_turns", None)
        atoms = H3PromptBuilder.split_speech_atoms(
            "啊？大爷你不要房租？该不会想让我那啥吧？我是正经人，卖艺不卖身的。"
        )
        self.assertEqual(
            [
                "啊？大爷你不要房租？",
                "该不会想让我那啥吧？",
                "我是正经人，卖艺不卖身的。",
            ],
            atoms,
        )
        user = build_timestamped_zh_author_user(recipe, beat, _shot2_author_assets())
        self.assertIn("啊？大爷你不要房租？", user)
        self.assertIn("该不会想让我那啥吧？", user)
        self.assertIn("我是正经人，卖艺不卖身的。", user)
        self.assertIn("2. 沙丽丽（开口）：啊？大爷你不要房租？", user)
        self.assertNotIn(
            "沙丽丽（开口）：啊？大爷你不要房租？该不会想让我那啥吧？我是正经人，卖艺不卖身的。",
            user,
        )
        zh = """镜头2，总时长13秒，内部时间从00:00开始。
镜头目的：吴耐免租，沙丽丽惊疑护胸。

参考素材：
- <Picture 1> 吴耐
- <Picture 2> 沙丽丽

必须出现的视觉内容：
- 电梯门前
- 吴耐挥手
- 沙丽丽护胸

按旁白和画面内容切镜：
- 00:00–00:03：双人中景站定。
- 00:03–00:05：吴耐挥手免租。
- 00:05–00:07：沙丽丽惊讶反问。
- 00:07–00:10：她猜疑并声明正经。
- 00:10–00:13：护胸定格。

对白：
- 吴耐在 00:03–00:05 说：“算了，房租免了。”
- 沙丽丽在 00:05–00:07 说：“啊？大爷你不要房租？”
- 沙丽丽在 00:07–00:10 说：“该不会想让我那啥吧？我是正经人，卖艺不卖身的。”

旁白：
- 本镜可无旁白

画面要求：
- 真人实拍
- 单一 9:16

负向约束：
- 不要插画、字幕、水印
"""
        self.assertEqual([], validate_timestamped_zh_prompt(zh, recipe, beat, _shot2_author_assets()))
        dumped = zh.replace("该不会想让我那啥吧？我是正经人，卖艺不卖身的。", "该不会想让我那啥吧？")
        missing = validate_timestamped_zh_prompt(dumped, recipe, beat, _shot2_author_assets())
        self.assertTrue(any("卖艺不卖身" in item for item in missing))
        same_range = """镜头2，总时长13秒，内部时间从00:00开始。
镜头目的：吴耐免租，沙丽丽惊疑护胸。

参考素材：
- <Picture 1> 吴耐
- <Picture 2> 沙丽丽

必须出现的视觉内容：
- 电梯门前

按旁白和画面内容切镜：
- 00:00–00:13：两人站在电梯门前把全部台词一次说完。

对白：
- 两人在 00:00–00:13 说：“算了，房租免了。啊？大爷你不要房租？该不会想让我那啥吧？我是正经人，卖艺不卖身的。”

旁白：
- 本镜可无旁白

画面要求：
- 真人实拍

负向约束：
- 不要插画
"""
        split_errors = validate_timestamped_zh_prompt(same_range, recipe, beat, _shot2_author_assets())
        self.assertTrue(any("不同时间段" in item for item in split_errors))

    def test_normalize_injects_missing_shot_1(self):
        en = """subject_definitions:
<Picture 1> locks Wu Nai. <Picture 2> locks Sha Lili. The corridor and composition are text-only.
summary:
Wu Nai waives rent.
retention_analysis:
fully_preserved.
detailed_description:
00:03-00:05 Wu Nai speaks <d>[Chinese] 算了，房租免了。</d> 00:05-00:07 <d>[Chinese] 啊？大爷你不要房租？</d> 00:07-00:10 <d>[Chinese] 该不会想让我那啥吧？我是正经人，卖艺不卖身的。</d>
overall_soundscape:
Quiet corridor.
non_diegetic_music:
None.
"""
        self.assertNotIn("[Shot 1]", en)
        normalized = H3PromptBuilder.normalize_authored_ref2va(en)
        self.assertIn("[Shot 1]", normalized)
        beat_info = {
            "dialogue": (
                "吴耐：“算了，房租免了。” "
                "沙丽丽：“啊？大爷你不要房租？该不会想让我那啥吧？我是正经人，卖艺不卖身的。”"
            ),
            "ref_images": [{"index": i} for i in range(1, 3)],
            "skill_pack_id": HALF_NARRATED_PACK_ID,
        }
        self.assertEqual([], LlmService._validate_h3_prompt(normalized, "Ref2VA", beat_info))

    def test_stub_zh_prompt_asks_for_rewrite_not_laundry_list(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        errors = validate_timestamped_zh_prompt(
            "官方八块中文分秒稿与",
            recipe,
            _shot2_author_beat(),
            _shot2_author_assets(),
        )
        self.assertEqual(1, len(errors))
        self.assertIn("说明句", errors[0])
        self.assertNotIn("缺少八块标题：镜头目的", errors[0])

    def test_stub_dual_author_retries_then_succeeds(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        stub = f"{ZH_BLOCK_MARK}\n官方八块中文分秒稿与\n{EN_BLOCK_MARK}\n英文六段稿。"
        meta = VisionCallMeta(status="unavailable")
        with patch.object(
            LlmService,
            "_complete_zh_author",
            side_effect=[(stub, meta), (_shot2_author_raw(), meta)],
        ) as chat:
            result = LlmService.author_timestamped_zh_prompt(
                recipe,
                _shot2_author_beat(),
                _shot2_author_assets(),
                recipe.reference_text("h3-video-prompt-template.md"),
            )
        self.assertEqual(2, chat.call_count)
        self.assertEqual(16000, chat.call_args_list[0].kwargs["max_tokens"])
        retry_prompt = chat.call_args_list[1].args[1]
        self.assertIn("说明句", retry_prompt)
        self.assertNotIn("缺少八块标题：镜头目的", retry_prompt)
        self.assertIn("算了，房租免了。", result.zh_prompt)

    def test_parse_unmarked_zh_en_split_and_english_only_missing_zh(self):
        zh, en = parse_dual_author_output(
            "镜头目的：对峙\n参考素材：<Picture 1>\nsubject_definitions:\n<Picture 1> lead.\n"
        )
        self.assertIn("镜头目的", zh)
        self.assertTrue(en.lower().startswith("subject_definitions:"))
        zh_only, en_only = parse_dual_author_output(
            "subject_definitions:\n<Picture 1> lead.\nsummary:\n[Shot 1] A beat.\n"
        )
        self.assertEqual("", zh_only)
        self.assertTrue(en_only.lower().startswith("subject_definitions:"))
        zh_colonless, en_colonless = parse_dual_author_output(
            "镜头目的：对峙\n参考素材：<Picture 1>\nsubject_definitions\n<Picture 1> lead.\n"
        )
        self.assertIn("镜头目的", zh_colonless)
        self.assertTrue(en_colonless.lower().startswith("subject_definitions"))
        extracted = extract_ref2va_prompt(en_colonless)
        normalized = H3PromptBuilder.normalize_authored_ref2va(extracted)
        self.assertRegex(normalized, r"(?m)^subject_definitions:")

    def test_english_only_author_raises_without_skeleton(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        beat = _shot2_author_beat()
        ctx = StepContext(recipe=recipe, beat=beat, assets=_shot2_author_assets(), beat_info={})
        english_only = (
            "subject_definitions:\n<Picture 1> lead.\n"
            "summary:\n[Shot 1] A beat.\n"
            "retention_analysis:\nfully_preserved.\n"
            "detailed_description:\n[Shot 1] The camera holds.\n"
            "overall_soundscape:\nQuiet.\n"
            "non_diegetic_music:\nNone."
        )
        with patch.object(
            LlmService,
            "_complete_zh_author",
            return_value=(english_only, VisionCallMeta(status="unavailable")),
        ):
            with self.assertRaises(DualShotAuthorError) as raised:
                write_timestamped_zh_prompt(ctx)
        self.assertIn("<<<ZH>>>", str(raised.exception))
        self.assertNotIn("timestamped_zh_prompt", ctx.beat_updates)
        self.assertNotEqual("skeleton", ctx.data.get("timestamped_zh_fallback"))
        self.assertNotIn(_THICKNESS_PAD, str(ctx.data.get("h3_prompt") or ""))


class SkillPackCraftOverlayTests(unittest.TestCase):
    def test_inject_craft_uses_confirm_format_range(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        text = inject_craft_text(recipe, "script")
        self.assertIn(recipe.name, text)
        self.assertIn("5–15 秒", text)
        self.assertIn("2K 或 768P", text)
        self.assertIn("Story and script", text)
        self.assertIn("spoken copy separate from visual direction", text)
        self.assertNotIn("重建版", text)
        self.assertNotIn("Final narration generation", text)
        self.assertNotIn("Seed Audio", text)

    def test_author_and_craft_follow_resolved_aspect(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        system = build_dual_author_system(recipe, "镜头目的：\n", aspect_ratio="16:9")
        original = {
            **_shot2_author_beat(),
            "heading": "竖屏 9:16 单镜到底",
            "camera": "竖屏中近景",
            "action": "衣服铺满竖屏",
        }
        user = build_timestamped_zh_author_user(
            recipe,
            original,
            _shot2_author_assets(),
            aspect_ratio="16:9",
        )
        overlay = inject_craft_text(recipe, "script", aspect_ratio="16:9")
        workshop = inject_craft_text(recipe, "workshop", aspect_ratio="16:9")
        extra_overlay = inject_craft_text(
            recipe,
            "script",
            extra={"workshop_aspect_ratio": "1:1"},
        )
        context = h3_authoring_context_images(recipe, _shot2_author_beat(), [], aspect_ratio="16:9")
        start_label = next((item["label"] for item in context if item.get("source") == "triptych.start"), "")
        self.assertIn("成片 16:9", system)
        self.assertIn("成片必须是单一 16:9", system)
        self.assertIn("三张 16:9 裁切格", system)
        self.assertNotIn("成片始终单一 9:16", system)
        self.assertNotIn("9:16 裁切", system)
        self.assertNotIn("成片始终单一 9:16", user)
        self.assertIn("成片始终单一 16:9", user)
        self.assertIn("镜头目的：横屏 16:9 单镜到底", user)
        self.assertIn("横屏中近景", user)
        self.assertIn("衣服铺满横屏", user)
        self.assertNotIn("竖屏", user.split("写稿附图")[0])
        self.assertEqual("竖屏 9:16 单镜到底", original["heading"])
        self.assertIn("确认画幅 16:9", overlay)
        self.assertIn("确认画幅 1:1", extra_overlay)
        self.assertIn("场景卡、三联母图与起幅/中格/结果裁切格仅供写稿", workshop)
        self.assertIn("确认画幅 16:9", workshop)
        self.assertIn("仅供写稿理解构图与动作节奏", start_label)
        self.assertIn("不上传视频模型", start_label)
        self.assertNotIn("9:16 裁切", start_label)

    def test_inject_craft_maps_official_chapters_without_rewriting_stages(self):
        recipe = get_pack(HALF_NARRATED_PACK_ID)
        self.assertEqual(
            {"script", "assets", "episodes", "storyboard"},
            set(recipe.director2_overlay),
        )
        script = inject_craft_text(recipe, "script")
        assets = inject_craft_text(recipe, "assets")
        episodes = inject_craft_text(recipe, "episodes")
        storyboard = inject_craft_text(recipe, "storyboard")
        self.assertIn("双通道", script)
        self.assertIn("Inspiration and concept", script)
        self.assertIn("Story and script", script)
        self.assertNotIn("Character and scene cards", script)
        self.assertIn("pure white background", assets)
        self.assertIn("Character and scene cards", assets)
        self.assertNotIn("Story and script", assets)
        self.assertNotIn("Seed Audio", assets)
        self.assertIn("分集结构", episodes)
        self.assertIn("Story and script", episodes)
        self.assertIn("镜头合同", storyboard)
        self.assertIn("Storyboard and shot contract", storyboard)
        self.assertIn("Keyframe generation", storyboard)
        self.assertIn("5–15", storyboard)
        self.assertNotIn("Final narration generation", storyboard)

    def test_official_pack_files_replace_reconstruction(self):
        root = PACKS_ROOT / HALF_NARRATED_PACK_ID
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        source = (root / "SOURCE.md").read_text(encoding="utf-8")
        template = (root / "references" / "h3-video-prompt-template.md").read_text(encoding="utf-8")
        triptych = (root / "references" / "triptych-prompt.md").read_text(encoding="utf-8")
        self.assertIn("half-narrated-live-action-short-drama", source)
        self.assertIn("1.0.1", source)
        self.assertIn("Design Image 2", skill)
        self.assertIn("禁止把分格", skill)
        self.assertIn("Keyframe generation", skill)
        self.assertNotIn("官方原文缺失", skill)
        self.assertIn("<Picture", template)
        self.assertNotIn("@Image", template)
        self.assertIn("禁止把分格", template)
        self.assertIn("设定板", template)
        self.assertIn("分格", template)
        self.assertIn("设定板", skill)
        self.assertIn("禁止抄分格", source)
        self.assertIn("16:9", triptych)
        self.assertIn("{aspect}", triptych)
        self.assertIn("{panel_geometry}", triptych)
        self.assertNotIn("9:16 裁切", triptych)
        self.assertFalse((root / "references" / "shot-prompt-template.md").is_file())

    def test_director_system_appends_overlay_in_pack_scope(self):
        with skill_pack_scope(HALF_NARRATED_PACK_ID):
            body = _system("script", "只输出 JSON。")
        self.assertIn("AGENT_ID: script", body)
        self.assertIn("技能包", body)
        self.assertIn("只输出 JSON。", body)
        plain = _system("script", "只输出 JSON。")
        self.assertNotIn("技能包", plain)

    def test_optimize_overlay_mentions_timeranges(self):
        overlay = craft_overlay_for_stage("optimize", HALF_NARRATED_PACK_ID)
        self.assertTrue(overlay)
        self.assertIn("道具设定板", overlay)
        self.assertIn("禁止抄分格", overlay)
        workshop = inject_craft_text(get_pack(HALF_NARRATED_PACK_ID), "workshop")
        self.assertIn("道具设定板", workshop)
        self.assertIn("禁止抄分格", workshop)


class SkillPackDefaultRecipeTests(unittest.TestCase):
    def test_empty_pack_id_is_default_render(self):
        recipe = default_recipe()
        self.assertTrue(recipe.is_default)
        self.assertEqual(("render_ref2va_default",), recipe.workshop_shot)
        self.assertFalse(recipe.packing_overrides.allow_timeranges)
        self.assertEqual("", validate_skill_pack_id(""))


if __name__ == "__main__":
    unittest.main()
