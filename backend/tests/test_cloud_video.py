from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image
from cryptography.fernet import Fernet

from backend.app.cloud_video import (
    CloudVideoError,
    CloudVideoUncertainSubmitError,
    build_adapter,
    cloud_video_provider_defaults,
    cloud_video_provider_keys,
    normalize_cloud_task_status,
    with_cloud_video_billing_caution,
)
from backend.app.cloud_video.base import CloudTaskSnapshot
from backend.app.cloud_video.kling import kling_jwt
from backend.app.cloud_video.scnet import ScnetClient
from backend.app.cloud_video_service import CloudVideoService
from backend.app.models import JobStatus
from backend.app.storage import JobStore
from backend.app.workflow_registry import (
    CLOUD_VIDEO_WORKFLOW_IDS,
    apply_billing_option_hints,
    billing_option_hints,
    clamp_cloud_video_options,
    cloud_model_for,
    cloud_provider_for,
    director_workflow_families,
    is_cloud_video_workflow,
    normalize_options,
    workflow_for,
)
from backend.app import worker as worker_module
from backend.app.worker import JobWorker


def _fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


class _FakeResponse:
    def __init__(self, payload: dict | None = None, *, status_code: int = 200, body: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload
        self._body = body

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    @property
    def content(self) -> bytes:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    """按 (method, url 后缀) 返回预设响应的 requests.Session 替身。"""

    def __init__(self, routes: dict[tuple[str, str], object]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        raise AssertionError("use session.get/post")

    def _dispatch(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        for (route_method, suffix), response in self.routes.items():
            if route_method == method and url.endswith(suffix):
                return response
        raise AssertionError(f"no route for {method} {url}")

    def get(self, url: str, **kwargs):
        return self._dispatch("get", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self._dispatch("post", url, **kwargs)


class RegistryCloudVideoTests(unittest.TestCase):
    def test_cloud_workflows_registered(self) -> None:
        self.assertEqual(len(CLOUD_VIDEO_WORKFLOW_IDS), 26)
        for workflow_id in CLOUD_VIDEO_WORKFLOW_IDS:
            definition = workflow_for(workflow_id)
            self.assertEqual(definition.executor, "cloud_video")
            self.assertTrue(definition.cloud_provider)
            self.assertTrue(definition.cloud_model)
            self.assertTrue(is_cloud_video_workflow(workflow_id))
            self.assertFalse(is_cloud_video_workflow("minimax-h3-t2v"))

    def test_i2v_reference_slots(self) -> None:
        kling_i2v = workflow_for("cloud-kling-i2v")
        self.assertEqual(kling_i2v.reference_mode, "keyframes")
        self.assertEqual((kling_i2v.min_references, kling_i2v.max_references), (1, 2))
        hailuo_i2v = workflow_for("cloud-hailuo-i2v")
        self.assertEqual((hailuo_i2v.min_references, hailuo_i2v.max_references), (1, 1))
        scnet_h3_i2v = workflow_for("cloud-scnet-h3-i2v")
        self.assertEqual((scnet_h3_i2v.min_references, scnet_h3_i2v.max_references), (1, 2))
        scnet_seedance_i2v = workflow_for("cloud-scnet-seedance-i2v")
        self.assertEqual((scnet_seedance_i2v.min_references, scnet_seedance_i2v.max_references), (1, 2))

    def test_scnet_workflows_expose_daily_quota_notice(self) -> None:
        scnet_modes = [workflow_id for workflow_id in CLOUD_VIDEO_WORKFLOW_IDS if workflow_id.startswith("cloud-scnet-")]
        self.assertEqual(len(scnet_modes), 5)
        for workflow_id in scnet_modes:
            notice = workflow_for(workflow_id).payload()["billing_notice"]
            self.assertIn("每天含 1 次免费生成额度", notice)
            self.assertIn("超算互联网控制台为准", notice)
        self.assertIsNone(workflow_for("cloud-kling-t2v").payload()["billing_notice"])

    def test_billing_notice_stays_user_facing(self) -> None:
        """计费提示渲染在创作页提交区，面向普通创作者：不得泄露管理端配置入口。"""
        for workflow_id in CLOUD_VIDEO_WORKFLOW_IDS:
            notice = workflow_for(workflow_id).payload()["billing_notice"] or ""
            self.assertNotIn("管理端", notice, workflow_id)
            self.assertNotIn("价格表", notice, workflow_id)
            self.assertNotIn("积分设置", notice, workflow_id)

    def test_normalize_options_and_unknown_rejection(self) -> None:
        normalized = normalize_options(
            "cloud-seedance-t2v",
            {"aspect_ratio": "9:16", "duration": 8, "resolution": "1080p", "model": "doubao-seedance-1-0-lite-t2v-250428"},
        )
        self.assertEqual(normalized["duration"], 8)
        self.assertEqual(normalized["resolution"], "1080p")
        with self.assertRaisesRegex(ValueError, "不支持参数"):
            normalize_options("cloud-kling-t2v", {"speed": "balanced"})

    def test_cloud_model_for_prefers_option(self) -> None:
        self.assertEqual(cloud_model_for("cloud-kling-t2v", {"model": "kling-v2-master"}), "kling-v2-master")
        self.assertEqual(cloud_model_for("cloud-kling-t2v"), "kling-v1-6")
        self.assertIsNone(cloud_model_for("minimax-h3-t2v"))
        self.assertEqual(cloud_provider_for("cloud-hailuo-i2v"), "hailuo")
        self.assertEqual(cloud_provider_for("cloud-scnet-h3-t2v"), "scnet")
        self.assertIsNone(cloud_provider_for("minimax-h3-t2v"))
        self.assertEqual(
            cloud_model_for("cloud-scnet-seedance-t2v", {"model": "Seedance2.5"}), "Seedance2.5",
        )

    def test_clamp_cloud_options_for_director_paths(self) -> None:
        clamped = clamp_cloud_video_options(
            "cloud-kling-t2v",
            {"aspect_ratio": "9:16", "quality": "1.0", "speed": "balanced", "weight_profile": "full", "duration": 8},
        )
        # H3 专属参数被丢弃；时长 8s 落到最近允许档 10s
        self.assertEqual(clamped, {"aspect_ratio": "9:16", "duration": "10"})
        clamped_seedance = clamp_cloud_video_options(
            "cloud-seedance-t2v",
            {"aspect_ratio": "2:3", "quality": "0.6", "speed": "balanced", "weight_profile": "full", "duration": 8},
        )
        self.assertEqual(clamped_seedance["duration"], 8)
        self.assertIn(clamped_seedance["aspect_ratio"], {"3:4", "9:16"})
        clamped_hailuo = clamp_cloud_video_options(
            "cloud-hailuo-t2v", {"aspect_ratio": "16:9", "duration": 8, "quality": "1.0"},
        )
        # 海螺 schema 无 aspect_ratio：被丢弃，时长落到 6s 档
        self.assertEqual(clamped_hailuo, {"duration": "6"})

    def test_director_families_split_by_provider(self) -> None:
        families = {item["id"]: item for item in director_workflow_families()}
        for provider in ("kling", "jimeng", "hailuo"):
            family = families[f"cloud_video:{provider}"]
            self.assertIn("t2v", family["routes"])
            self.assertIn("i2v", family["routes"])
            self.assertTrue(family["label"].startswith("云端 · "))
        # SCNet 一个供应商挂三个模型族：H3/Seedance 各有 T2V+I2V，HappyHorse 只有 T2V
        for family_key in ("scnet-h3", "scnet-seedance"):
            family = families[f"cloud_video:{family_key}"]
            self.assertIn("t2v", family["routes"])
            self.assertIn("i2v", family["routes"])
            self.assertIn("超算互联网", family["label"])
        happyhorse = families["cloud_video:scnet-happyhorse"]
        self.assertIn("t2v", happyhorse["routes"])
        self.assertNotIn("i2v", happyhorse["routes"])
        # GRS MiniMax-H3：T2V / R2V / FL2V 三路由齐备
        grs_family = families["cloud_video:grs-h3"]
        self.assertEqual(
            grs_family["routes"],
            {"t2v": "cloud-grs-h3-t2v", "i2v": "cloud-grs-h3-fl2v", "r2v": "cloud-grs-h3-r2v"},
        )
        # GRS Agnes 2.5：四模式齐备，i2v 定义在后赢得族内图生路由
        agnes_family = families["cloud_video:grs-agnes"]
        self.assertEqual(
            agnes_family["routes"],
            {"t2v": "cloud-grs-agnes-t2v", "i2v": "cloud-grs-agnes-i2v", "r2v": "cloud-grs-agnes-r2v"},
        )
        self.assertIn("Agnes", agnes_family["label"])
        # GRS Wan 3.0：四模式齐备，i2v 同样定义在后
        wan_family = families["cloud_video:grs-wan"]
        self.assertEqual(
            wan_family["routes"],
            {"t2v": "cloud-grs-wan-t2v", "i2v": "cloud-grs-wan-i2v", "r2v": "cloud-grs-wan-r2v"},
        )
        self.assertIn("Wan", wan_family["label"])

    def test_grs_h3_workflows_registered(self) -> None:
        """GRS MiniMax-H3 三模式：槽位、计费提示与分辨率档位标注。"""
        t2v = workflow_for("cloud-grs-h3-t2v")
        self.assertEqual(t2v.cloud_provider, "grs")
        self.assertEqual(t2v.cloud_model, "minimax-h3")
        self.assertEqual(t2v.reference_mode, "none")
        self.assertEqual((t2v.min_references, t2v.max_references), (0, 0))
        r2v = workflow_for("cloud-grs-h3-r2v")
        self.assertEqual(r2v.reference_mode, "collection")
        self.assertEqual((r2v.min_references, r2v.max_references), (1, 9))
        fl2v = workflow_for("cloud-grs-h3-fl2v")
        self.assertEqual(fl2v.reference_mode, "keyframes")
        self.assertEqual((fl2v.min_references, fl2v.max_references), (2, 2))
        for workflow_id in ("cloud-grs-h3-t2v", "cloud-grs-h3-r2v", "cloud-grs-h3-fl2v"):
            payload = workflow_for(workflow_id).payload()
            self.assertIn("GRS 按秒计费", payload["billing_notice"])
            self.assertIn("任务失败自动全额退回积分", payload["billing_notice"])
            properties = workflow_for(workflow_id).option_schema["properties"]
            self.assertEqual(properties["resolution"]["ui_group"], "primary")
            self.assertEqual(properties["aspect_ratio"]["ui_group"], "primary")
            self.assertEqual(properties["prompt_skill"]["ui_group"], "advanced")
            # 单价由 /api/modes 的 billing 动态标注，注册表不再写死金额。
            self.assertNotIn("ui_options", properties["resolution"])
            hints = billing_option_hints(
                workflow_for(workflow_id), {"480p": 5, "768p": 7, "1080p": 15},
            )
            self.assertEqual(hints["resolution"]["768p"], "7 积分/秒")

    def test_grs_agnes_workflows_registered(self) -> None:
        """GRS Agnes Video 2.5 四模式：槽位、参数层级与 4-12 秒约束。"""
        t2v = workflow_for("cloud-grs-agnes-t2v")
        self.assertEqual(t2v.cloud_provider, "grs")
        self.assertEqual(t2v.cloud_model, "agnes-video-2.5")
        self.assertEqual(t2v.cloud_family, "grs-agnes")
        self.assertEqual(t2v.reference_mode, "none")
        i2v = workflow_for("cloud-grs-agnes-i2v")
        self.assertEqual(i2v.reference_mode, "keyframes")
        self.assertEqual((i2v.min_references, i2v.max_references), (1, 1))
        fl2v = workflow_for("cloud-grs-agnes-fl2v")
        self.assertEqual((fl2v.min_references, fl2v.max_references), (2, 2))
        r2v = workflow_for("cloud-grs-agnes-r2v")
        self.assertEqual(r2v.reference_mode, "collection")
        self.assertEqual((r2v.min_references, r2v.max_references), (1, 5))
        for workflow_id in (
            "cloud-grs-agnes-t2v", "cloud-grs-agnes-i2v", "cloud-grs-agnes-fl2v", "cloud-grs-agnes-r2v",
        ):
            payload = workflow_for(workflow_id).payload()
            self.assertIn("GRS 按秒计费", payload["billing_notice"])
            self.assertIn("4-12 秒", payload["billing_notice"])
            properties = workflow_for(workflow_id).option_schema["properties"]
            self.assertEqual(properties["resolution"]["ui_group"], "primary")
            self.assertEqual(properties["aspect_ratio"]["ui_group"], "primary")
            self.assertEqual(properties["duration"]["ui_group"], "primary")
            self.assertEqual(properties["duration"]["minimum"], 4)
            self.assertEqual(properties["duration"]["maximum"], 12)
            self.assertEqual(properties["seed"]["ui_group"], "advanced")
            self.assertNotIn("ui_options", properties["resolution"])
            hints = billing_option_hints(
                workflow_for(workflow_id), {"720p": 10, "1080p": 17, "2k": 23},
            )
            self.assertEqual(hints["resolution"]["2k"], "23 积分/秒")

        normalized = normalize_options(
            "cloud-grs-agnes-t2v", {"aspect_ratio": "9:16", "duration": 12, "resolution": "2k"},
        )
        self.assertEqual(normalized["duration"], 12)
        self.assertEqual(normalized["resolution"], "2k")
        self.assertEqual(normalized["aspect_ratio"], "9:16")
        with self.assertRaises(ValueError):
            normalize_options("cloud-grs-agnes-t2v", {"duration": 10, "resolution": "4k"})

    def test_grs_wan_workflows_registered(self) -> None:
        """GRS Wan 3.0 四模式：槽位、参数层级与 2-30 秒约束。"""
        t2v = workflow_for("cloud-grs-wan-t2v")
        self.assertEqual(t2v.cloud_provider, "grs")
        self.assertEqual(t2v.cloud_model, "wan-3.0")
        self.assertEqual(t2v.cloud_family, "grs-wan")
        self.assertEqual(t2v.reference_mode, "none")
        i2v = workflow_for("cloud-grs-wan-i2v")
        self.assertEqual(i2v.reference_mode, "keyframes")
        self.assertEqual((i2v.min_references, i2v.max_references), (1, 1))
        fl2v = workflow_for("cloud-grs-wan-fl2v")
        self.assertEqual((fl2v.min_references, fl2v.max_references), (2, 2))
        r2v = workflow_for("cloud-grs-wan-r2v")
        self.assertEqual(r2v.reference_mode, "collection")
        self.assertEqual((r2v.min_references, r2v.max_references), (1, 10))
        for workflow_id in (
            "cloud-grs-wan-t2v", "cloud-grs-wan-i2v", "cloud-grs-wan-fl2v", "cloud-grs-wan-r2v",
        ):
            self.assertTrue(is_cloud_video_workflow(workflow_id))
            payload = workflow_for(workflow_id).payload()
            self.assertIn("GRS Wan 3.0 按秒计费", payload["billing_notice"])
            self.assertIn("2-30 秒", payload["billing_notice"])
            properties = workflow_for(workflow_id).option_schema["properties"]
            self.assertEqual(properties["resolution"]["ui_group"], "primary")
            self.assertEqual(properties["aspect_ratio"]["ui_group"], "primary")
            self.assertEqual(properties["duration"]["ui_group"], "primary")
            self.assertEqual(properties["duration"]["minimum"], 2)
            self.assertEqual(properties["duration"]["maximum"], 30)
            self.assertEqual(properties["seed"]["ui_group"], "advanced")
            self.assertNotIn("ui_options", properties["resolution"])
            self.assertNotIn("prompt_skill", properties)
            hints = billing_option_hints(
                workflow_for(workflow_id), {"480p": 14, "720p": 27, "1080p": 54},
            )
            self.assertEqual(hints["resolution"]["480p"], "14 积分/秒")
            self.assertEqual(hints["resolution"]["1080p"], "54 积分/秒")

        normalized = normalize_options(
            "cloud-grs-wan-t2v", {"aspect_ratio": "21:9", "duration": 30, "resolution": "1080p"},
        )
        self.assertEqual(normalized["duration"], 30)
        self.assertEqual(normalized["resolution"], "1080p")
        self.assertEqual(normalized["aspect_ratio"], "21:9")
        with self.assertRaises(ValueError):
            normalize_options("cloud-grs-wan-t2v", {"duration": 31})
        with self.assertRaises(ValueError):
            normalize_options("cloud-grs-wan-t2v", {"duration": 1})
        with self.assertRaises(ValueError):
            normalize_options("cloud-grs-wan-t2v", {"duration": 5, "resolution": "768p"})

    def test_cloud_pricing_providers_include_grs_wan(self) -> None:
        from backend.app.workflow_registry import CLOUD_PRICING_PROVIDERS

        spec = next(item for item in CLOUD_PRICING_PROVIDERS if item["key"] == "grs-wan")
        self.assertEqual(spec["provider_key"], "grs")
        self.assertEqual(spec["family"], "grs-wan")
        self.assertEqual(spec["variant_by"], "resolution")
        self.assertEqual(spec["models"][0]["key"], "wan-3.0")
        self.assertEqual(tuple(spec["models"][0]["resolutions"]), ("480p", "720p", "1080p"))

    def test_billing_option_hints_cover_cloud_variants(self) -> None:
        """选项标注由价格表分档驱动：GRS 按分辨率精确价，MiniMax 按模型/分辨率给区间。"""
        grs_hints = billing_option_hints(
            workflow_for("cloud-grs-h3-t2v"), {"480p": 5, "768p": 7, "1080p": 15},
        )
        self.assertEqual(grs_hints["resolution"]["1080p"], "15 积分/秒")

        minimax_hints = billing_option_hints(
            workflow_for("cloud-minimax-h3-t2v"),
            {
                "MiniMax-H3-Lite:480P": 16,
                "MiniMax-H3-Lite:768P": 26,
                "MiniMax-H3:768P": 50,
                "MiniMax-H3:2K": 80,
            },
        )
        self.assertEqual(minimax_hints["model"]["MiniMax-H3-Lite"], "16-26 积分/秒")
        self.assertEqual(minimax_hints["resolution"]["768P"], "26-50 积分/秒")
        self.assertEqual(minimax_hints["resolution"]["2K"], "80 积分/秒")

        kling_hints = billing_option_hints(workflow_for("cloud-kling-t2v"), {"std": 40, "pro": 80})
        self.assertEqual(kling_hints["kling_mode"]["pro"], "80 积分/秒")

    def test_apply_billing_option_hints_does_not_mutate_registry(self) -> None:
        definition = workflow_for("cloud-grs-h3-t2v")
        payload = definition.payload()
        apply_billing_option_hints(payload, definition, {"480p": 5, "768p": 7, "1080p": 15})
        options_parameter = next(item for item in payload["parameters"] if item["name"] == "options")
        labels = {
            item["value"]: item["label"]
            for item in options_parameter["schema"]["properties"]["resolution"]["ui_options"]
        }
        self.assertEqual(labels["768p"], "768p · 7 积分/秒")
        self.assertNotIn("ui_options", definition.option_schema["properties"]["resolution"])

    def test_grs_h3_normalize_rejects_1080p_over_ten_seconds(self) -> None:
        normalized = normalize_options(
            "cloud-grs-h3-t2v", {"aspect_ratio": "portrait", "duration": 8, "resolution": "768p"},
        )
        self.assertEqual(normalized["duration"], 8)
        self.assertEqual(normalized["resolution"], "768p")
        self.assertFalse(normalized["prompt_skill"])
        with self.assertRaisesRegex(ValueError, "1080p 分辨率最长支持 10 秒"):
            normalize_options("cloud-grs-h3-t2v", {"duration": 12, "resolution": "1080p"})

    def test_minimax_h3_workflows_registered(self) -> None:
        """MiniMax 官方 H3 四模式：槽位、计费提示与参数层级。"""
        t2v = workflow_for("cloud-minimax-h3-t2v")
        self.assertEqual(t2v.cloud_provider, "minimax")
        self.assertEqual(t2v.cloud_model, "MiniMax-H3-Lite")
        self.assertEqual(t2v.cloud_family, "minimax-h3")
        self.assertEqual(t2v.reference_mode, "none")
        self.assertEqual((t2v.min_references, t2v.max_references), (0, 0))
        i2v = workflow_for("cloud-minimax-h3-i2v")
        self.assertEqual(i2v.reference_mode, "keyframes")
        self.assertEqual((i2v.min_references, i2v.max_references), (1, 1))
        fl2v = workflow_for("cloud-minimax-h3-fl2v")
        self.assertEqual((fl2v.min_references, fl2v.max_references), (2, 2))
        r2v = workflow_for("cloud-minimax-h3-r2v")
        self.assertEqual(r2v.reference_mode, "collection")
        self.assertEqual((r2v.min_references, r2v.max_references), (1, 9))
        for workflow_id in (
            "cloud-minimax-h3-t2v", "cloud-minimax-h3-i2v", "cloud-minimax-h3-fl2v", "cloud-minimax-h3-r2v",
        ):
            payload = workflow_for(workflow_id).payload()
            self.assertIn("MiniMax 官方按秒计费", payload["billing_notice"])
            self.assertIn("任务失败自动全额退回积分", payload["billing_notice"])
            properties = workflow_for(workflow_id).option_schema["properties"]
            self.assertEqual(properties["resolution"]["ui_group"], "primary")
            self.assertEqual(properties["duration"]["ui_group"], "primary")
            self.assertEqual(properties["model"]["ui_group"], "advanced")
            self.assertTrue(properties["generate_audio"]["default"])
        # t2v 必须显式画幅；r2v 官方要求显式具体比例（非旗舰档不支持 adaptive）；i2v/fl2v 恒随输入
        self.assertIn("aspect_ratio", workflow_for("cloud-minimax-h3-t2v").option_schema["properties"])
        self.assertIn("aspect_ratio", workflow_for("cloud-minimax-h3-r2v").option_schema["properties"])
        for workflow_id in ("cloud-minimax-h3-i2v", "cloud-minimax-h3-fl2v"):
            self.assertNotIn("aspect_ratio", workflow_for(workflow_id).option_schema["properties"])

    def test_minimax_h3_r2v_defaults_explicit_ratio(self) -> None:
        """r2v 未传画幅时按 schema 默认 16:9 归一，绝不落到官方不支持的 adaptive。"""
        normalized = normalize_options("cloud-minimax-h3-r2v", {"duration": 12, "resolution": "768P"})
        self.assertEqual(normalized["aspect_ratio"], "16:9")
        self.assertEqual(normalized["duration"], 12)

    def test_minimax_h3_normalize_rejects_cross_tier_violations(self) -> None:
        normalized = normalize_options(
            "cloud-minimax-h3-t2v", {"aspect_ratio": "9:16", "duration": 8, "resolution": "480P"},
        )
        self.assertEqual(normalized["duration"], 8)
        self.assertEqual(normalized["resolution"], "480P")
        self.assertEqual(normalized["model"], "MiniMax-H3-Lite")
        self.assertTrue(normalized["generate_audio"])
        with self.assertRaisesRegex(ValueError, "2K 分辨率仅 MiniMax-H3 旗舰档支持"):
            normalize_options("cloud-minimax-h3-t2v", {"duration": 5, "resolution": "2K", "model": "MiniMax-H3-Lite"})
        with self.assertRaisesRegex(ValueError, "480P 分辨率仅 Lite / Highspeed / H3-Max"):
            normalize_options(
                "cloud-minimax-h3-t2v", {"duration": 5, "resolution": "480P", "model": "MiniMax-H3"},
            )
        with self.assertRaisesRegex(ValueError, "H3-Max 档时长起步 5 秒"):
            normalize_options(
                "cloud-minimax-h3-t2v", {"duration": 4, "resolution": "480P", "model": "MiniMax-H3-Max"},
            )

    def test_minimax_h3_clamp_and_director_family(self) -> None:
        clamped = clamp_cloud_video_options(
            "cloud-minimax-h3-t2v",
            {"aspect_ratio": "16:9", "quality": "1.0", "speed": "balanced", "duration": 8, "resolution": "2K"},
        )
        # 导演链路透传 quality 等参数被丢弃；2K + 默认 Lite 回落 768P
        self.assertEqual(clamped["resolution"], "768P")
        self.assertNotIn("quality", clamped)
        clamped_h3_480 = clamp_cloud_video_options(
            "cloud-minimax-h3-t2v",
            {"aspect_ratio": "16:9", "duration": 8, "resolution": "480P", "model": "MiniMax-H3"},
        )
        # H3 旗舰档官方没有 480P 档价，导演链路回落 768P
        self.assertEqual(clamped_h3_480["resolution"], "768P")
        families = {item["id"]: item for item in director_workflow_families()}
        minimax_family = families["cloud_video:minimax-h3"]
        self.assertEqual(minimax_family["label"], "云端 · MiniMax 官方 H3")
        # 族内图生路由取单首帧 i2v（导演链路只有首帧）；fl2v 成对校验仅生成页可选
        self.assertEqual(
            minimax_family["routes"],
            {"t2v": "cloud-minimax-h3-t2v", "i2v": "cloud-minimax-h3-i2v", "r2v": "cloud-minimax-h3-r2v"},
        )


class CloudVideoStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ensure_row_defaults_and_update(self) -> None:
        settings = self.store.get_cloud_video_settings("kling")
        self.assertEqual(settings["provider_key"], "kling")
        self.assertEqual(settings["enabled"], 0)
        self.assertIsNone(settings["base_url"])
        self.store.update_cloud_video_settings(
            "kling", enabled=1, base_url="https://api.example.com", last_test_status="success",
        )
        updated = self.store.get_cloud_video_settings("kling")
        self.assertEqual(updated["enabled"], 1)
        self.assertEqual(updated["base_url"], "https://api.example.com")
        self.assertEqual(updated["last_test_status"], "success")

    def test_unknown_provider_rejected(self) -> None:
        with self.assertRaises(CloudVideoError):
            cloud_video_provider_defaults("nonexistent")
        with self.assertRaises(CloudVideoError):
            self.store.get_cloud_video_settings("nonexistent")

    def test_list_covers_all_providers(self) -> None:
        rows = self.store.list_cloud_video_settings()
        self.assertEqual([row["provider_key"] for row in rows], list(cloud_video_provider_keys()))
        self.assertIn("scnet", [row["provider_key"] for row in rows])


class CloudVideoAdapterTests(unittest.TestCase):
    # ------------------------------------------------------------------
    # 可灵
    # ------------------------------------------------------------------

    def test_kling_jwt_shape(self) -> None:
        token = kling_jwt("ak-test", "sk-test")
        header_b64, payload_b64, _ = token.split(".")
        pad = lambda part: part + "=" * (-len(part) % 4)
        header = json.loads(base64.urlsafe_b64decode(pad(header_b64)))
        payload = json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
        self.assertEqual(header["alg"], "HS256")
        self.assertEqual(payload["iss"], "ak-test")
        self.assertGreater(payload["exp"], payload["nbf"])

    def test_kling_submit_t2v_and_poll(self) -> None:
        session = _FakeSession({
            ("post", "/v1/videos/text2video"): _FakeResponse({"code": 0, "data": {"task_id": "task-1"}}),
            ("get", "/v1/videos/text2video/task-1"): _FakeResponse({
                "code": 0,
                "data": {
                    "task_status": "succeed",
                    "task_result": {"videos": [{"id": "v1", "url": "https://cdn/v.mp4", "duration": 5}]},
                },
            }),
        })
        client = build_adapter("kling", base_url=None, api_key="ak", api_secret="sk", session=session)
        remote_id = client.submit(_submit_request())
        self.assertEqual(remote_id, "t2v:task-1")
        method, url, kwargs = session.calls[0]
        self.assertEqual(url, "https://api.klingai.com/v1/videos/text2video")
        self.assertIn("Authorization", kwargs["headers"])
        self.assertEqual(kwargs["json"]["model_name"], "kling-v1-6")
        self.assertEqual(kwargs["json"]["duration"], "5")
        snapshot = client.poll(remote_id)
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.video_urls, ["https://cdn/v.mp4"])

    def test_kling_submit_i2v_with_tail_frame(self) -> None:
        session = _FakeSession({
            ("post", "/v1/videos/image2video"): _FakeResponse({"code": 0, "data": {"task_id": "task-2"}}),
        })
        client = build_adapter("kling", base_url=None, api_key="ak", api_secret="sk", session=session)
        first = Path(self._tmp_image("first.png", "PNG"))
        tail = Path(self._tmp_image("tail.png", "PNG"))
        remote_id = client.submit(_submit_request(first_frame=first, last_frame=tail))
        self.assertEqual(remote_id, "i2v:task-2")
        body = session.calls[0][2]["json"]
        self.assertIn("image", body)
        self.assertIn("image_tail", body)
        base64.b64decode(body["image"])  # 裸 base64 可解码

    def test_kling_api_error_envelope(self) -> None:
        session = _FakeSession({
            ("post", "/v1/videos/text2video"): _FakeResponse({"code": 1002, "message": "额度不足"}),
        })
        client = build_adapter("kling", base_url=None, api_key="ak", api_secret="sk", session=session)
        with self.assertRaisesRegex(CloudVideoError, "额度不足"):
            client.submit(_submit_request())

    # ------------------------------------------------------------------
    # 方舟 Seedance
    # ------------------------------------------------------------------

    def test_jimeng_submit_and_poll(self) -> None:
        session = _FakeSession({
            ("post", "/api/v3/contents/generations/tasks"): _FakeResponse({"id": "cgt-1", "status": "queued"}),
            ("get", "/api/v3/contents/generations/tasks/cgt-1"): _FakeResponse({
                "id": "cgt-1", "status": "succeeded", "content": {"video_url": "https://cdn/s.mp4"},
            }),
        })
        client = build_adapter("jimeng", base_url=None, api_key="ark-key", session=session)
        remote_id = client.submit(_submit_request(model="doubao-seedance-1-0-pro-250528"))
        self.assertEqual(remote_id, "cgt-1")
        method, url, kwargs = session.calls[0]
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer ark-key")
        content = kwargs["json"]["content"]
        self.assertEqual(kwargs["json"]["model"], "doubao-seedance-1-0-pro-250528")
        self.assertIn("--ratio 16:9", content[0]["text"])
        self.assertIn("--duration 5", content[0]["text"])
        snapshot = client.poll(remote_id)
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.video_urls, ["https://cdn/s.mp4"])

    def test_jimeng_i2v_uses_data_url_role(self) -> None:
        session = _FakeSession({
            ("post", "/api/v3/contents/generations/tasks"): _FakeResponse({"id": "cgt-2"}),
        })
        client = build_adapter("jimeng", base_url=None, api_key="ark", session=session)
        first = Path(self._tmp_image("first.jpg", "JPEG"))
        client.submit(_submit_request(first_frame=first))
        content = session.calls[0][2]["json"]["content"]
        self.assertEqual(content[1]["role"], "first_frame")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_jimeng_test_connection_distinguishes_auth(self) -> None:
        ok_session = _FakeSession({
            ("get", "/tasks/zly-probe-nonexistent-task"): _FakeResponse({}, status_code=404),
        })
        client = build_adapter("jimeng", base_url=None, api_key="ark", session=ok_session)
        self.assertIn("鉴权通过", client.test_connection())
        bad_session = _FakeSession({
            ("get", "/tasks/zly-probe-nonexistent-task"): _FakeResponse({}, status_code=401),
        })
        bad_client = build_adapter("jimeng", base_url=None, api_key="bad", session=bad_session)
        with self.assertRaisesRegex(CloudVideoError, "API Key 无效"):
            bad_client.test_connection()

    # ------------------------------------------------------------------
    # 海螺
    # ------------------------------------------------------------------

    def test_hailuo_submit_and_poll_with_file_retrieve(self) -> None:
        session = _FakeSession({
            ("post", "/v1/video_generation"): _FakeResponse(
                {"task_id": "mx-1", "base_resp": {"status_code": 0, "status_msg": ""}},
            ),
            ("get", "/v1/query/video_generation"): _FakeResponse({
                "task_id": "mx-1", "status": "Success", "file_id": "file-9",
                "base_resp": {"status_code": 0, "status_msg": ""},
            }),
            ("get", "/v1/files/retrieve"): _FakeResponse({
                "file": {"file_id": "file-9", "download_url": "https://cdn/h.mp4"},
                "base_resp": {"status_code": 0, "status_msg": ""},
            }),
        })
        client = build_adapter("hailuo", base_url=None, api_key="mx", session=session)
        remote_id = client.submit(_submit_request(model="I2V-01"))
        self.assertEqual(remote_id, "mx-1")
        first = Path(self._tmp_image("first.jpg", "JPEG"))
        client.submit(_submit_request(model="I2V-01", first_frame=first))
        self.assertIn("first_frame_image", session.calls[1][2]["json"])
        snapshot = client.poll(remote_id)
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.video_urls, ["https://cdn/h.mp4"])

    def test_hailuo_auth_error_maps_to_message(self) -> None:
        session = _FakeSession({
            ("get", "/v1/query/video_generation"): _FakeResponse({
                "base_resp": {"status_code": 1004, "status_msg": "invalid api key"},
            }),
        })
        client = build_adapter("hailuo", base_url=None, api_key="bad", session=session)
        with self.assertRaisesRegex(CloudVideoError, "API Key 无效"):
            client.test_connection()

    # ------------------------------------------------------------------
    # 超算互联网（SCNet）
    # ------------------------------------------------------------------

    def test_scnet_seedance_model_version_option(self) -> None:
        properties = workflow_for("cloud-scnet-seedance-t2v").option_schema["properties"]
        self.assertEqual(properties["model"]["default"], "Seedance2.5")
        self.assertEqual(properties["model"]["enum"], ["Seedance2.5", "Seedance2.0"])
        self.assertEqual(properties["model"]["ui_group"], "advanced")
        i2v_properties = workflow_for("cloud-scnet-seedance-i2v").option_schema["properties"]
        self.assertEqual(i2v_properties["model"]["enum"], ["Seedance2.5", "Seedance2.0"])
        self.assertEqual(normalize_options("cloud-scnet-seedance-t2v", {})["model"], "Seedance2.5")

    def test_scnet_submit_t2v_and_poll(self) -> None:
        session = _FakeSession({
            ("post", "/v1/videos/generations"): _FakeResponse({
                "request_id": "req-1", "output": {"task_id": "sc-1", "task_status": "pending"},
            }),
            ("get", "/v1/tasks/sc-1"): _FakeResponse({
                "request_id": "req-2",
                "output": {
                    "task_id": "sc-1", "task_status": "succeeded",
                    "results": ["https://cdn/sc.mp4"],
                },
            }),
        })
        client = build_adapter("scnet", base_url=None, api_key="sc-key", session=session)
        self.assertIsInstance(client, ScnetClient)
        remote_id = client.submit(_submit_request(
            model="MiniMax-H3",
            options={"aspect_ratio": "16:9", "duration": 5, "resolution": "2K"},
        ))
        self.assertEqual(remote_id, "sc-1")
        method, url, kwargs = session.calls[0]
        self.assertEqual(url, "https://api.scnet.cn/api/llm/v1/videos/generations")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sc-key")
        self.assertEqual(kwargs["headers"]["X-MultiModal-Async"], "true")
        body = kwargs["json"]
        self.assertEqual(body["model"], "MiniMax-H3")
        self.assertEqual(body["input"]["prompt"], "一只猫在雪地里奔跑")
        self.assertEqual(
            body["parameters"],
            {"ratio": "16:9", "duration": 5, "resolution": "2K", "watermark": False},
        )
        snapshot = client.poll(remote_id)
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.video_urls, ["https://cdn/sc.mp4"])

    def test_scnet_i2v_maps_first_and_last_frame(self) -> None:
        session = _FakeSession({
            ("post", "/v1/videos/generations"): _FakeResponse({"output": {"task_id": "sc-2"}}),
        })
        client = build_adapter("scnet", base_url=None, api_key="sc-key", session=session)
        first = Path(self._tmp_image("first.png", "PNG"))
        tail = Path(self._tmp_image("tail.png", "PNG"))
        client.submit(_submit_request(
            model="Seedance2.5", first_frame=first, last_frame=tail, options={"duration": 5},
        ))
        body = session.calls[0][2]["json"]
        self.assertEqual(body["model"], "Seedance2.5")
        media = body["input"]["media"]
        parameters = body["parameters"]
        self.assertEqual([item["type"] for item in media], ["first_frame", "last_frame"])
        self.assertTrue(media[0]["url"].startswith("data:image/"))
        self.assertTrue(media[1]["url"].startswith("data:image/"))
        self.assertNotIn("ratio", parameters)
        self.assertEqual(parameters["output_format"], "mp4")

    def test_scnet_failed_task_surfaces_error_message(self) -> None:
        session = _FakeSession({
            ("get", "/v1/tasks/sc-3"): _FakeResponse({
                "output": {
                    "task_id": "sc-3", "task_status": "failed",
                    "error_code": "InvalidParameter", "error_message": "提示词包含敏感内容",
                },
            }),
        })
        client = build_adapter("scnet", base_url=None, api_key="sc-key", session=session)
        snapshot = client.poll("sc-3")
        self.assertEqual(snapshot.status, "failed")
        self.assertEqual(snapshot.message, "提示词包含敏感内容")

    def test_scnet_test_connection_uses_model_list(self) -> None:
        ok_session = _FakeSession({
            ("get", "/v1/models"): _FakeResponse({
                "object": "list",
                "data": [
                    {"id": "MiniMax-H3"}, {"id": "Seedance2.5"}, {"id": "Seedance2.0"},
                    {"id": "HappyHorse-1.0-T2V"},
                ],
            }),
        })
        client = build_adapter("scnet", base_url=None, api_key="sc-key", session=ok_session)
        self.assertIn("可用视频模型", client.test_connection())
        bad_session = _FakeSession({
            ("get", "/v1/models"): _FakeResponse({}, status_code=401),
        })
        bad_client = build_adapter("scnet", base_url=None, api_key="bad", session=bad_session)
        with self.assertRaisesRegex(CloudVideoError, "API Key 无效"):
            bad_client.test_connection()

    # ------------------------------------------------------------------
    # GRS 视频（MiniMax-H3）
    # ------------------------------------------------------------------

    def test_grs_submit_t2v_and_poll(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse({"id": "grs-1", "status": "running"}),
            ("get", "/v1/api/result"): _FakeResponse({
                "id": "grs-1", "status": "succeeded", "progress": 100,
                "results": [{"url": "https://cdn/grs.mp4"}],
            }),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        remote_id = client.submit(_submit_request(
            model="minimax-h3",
            options={"aspect_ratio": "portrait", "duration": 5, "resolution": "768p", "prompt_skill": True},
        ))
        self.assertEqual(remote_id, "grs-1")
        method, url, kwargs = session.calls[0]
        self.assertEqual(url, "https://grsai.dakka.com.cn/v1/api/generate")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer grs-key")
        body = kwargs["json"]
        self.assertEqual(body["model"], "minimax-h3")
        self.assertEqual(body["prompt"], "一只猫在雪地里奔跑")
        self.assertEqual(body["aspectRatio"], "portrait")
        self.assertEqual(body["resolution"], "768p")
        self.assertEqual(body["duration"], 5)
        self.assertEqual(body["replyType"], "async")
        self.assertTrue(body["promptSkill"])
        self.assertNotIn("images", body)
        snapshot = client.poll(remote_id)
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.video_urls, ["https://cdn/grs.mp4"])
        method, url, kwargs = session.calls[1]
        self.assertEqual(kwargs["params"], {"id": "grs-1"})

    def test_grs_submit_defaults_prompt_skill_off_and_zero_seed_random(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse({"id": "grs-2", "status": "running"}),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        client.submit(_submit_request(
            model="minimax-h3",
            options={"aspect_ratio": "landscape", "duration": "10", "resolution": "1080p", "seed": 0},
        ))
        body = session.calls[0][2]["json"]
        self.assertFalse(body["promptSkill"])
        self.assertNotIn("seed", body)
        self.assertEqual(body["duration"], 10)

    def test_grs_submit_maps_references_to_images(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse({"id": "grs-3", "status": "running"}),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        refs = [
            Path(self._tmp_image("grs-ref-1.png", "PNG")),
            Path(self._tmp_image("grs-ref-2.png", "PNG")),
        ]
        client.submit(_submit_request(
            model="minimax-h3", options={"duration": 5, "resolution": "480p"}, references=refs,
        ))
        body = session.calls[0][2]["json"]
        self.assertEqual(len(body["images"]), 2)
        self.assertTrue(body["images"][0].startswith("data:image/"))

    def test_grs_submit_fl2v_requires_paired_frames(self) -> None:
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=_FakeSession({}))
        first = Path(self._tmp_image("grs-first.png", "PNG"))
        with self.assertRaisesRegex(CloudVideoError, "首尾帧必须成对"):
            client.submit(_submit_request(
                model="minimax-h3", first_frame=first, options={"duration": 5, "resolution": "480p"},
            ))

    def test_grs_submit_rejects_invalid_resolution_duration_and_reference_overflow(self) -> None:
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=_FakeSession({}))
        with self.assertRaisesRegex(CloudVideoError, "分辨率"):
            client.submit(_submit_request(model="minimax-h3", options={"duration": 5, "resolution": "4K"}))
        with self.assertRaisesRegex(CloudVideoError, "1080p 分辨率最长"):
            client.submit(_submit_request(model="minimax-h3", options={"duration": 12, "resolution": "1080p"}))
        refs = [Path(self._tmp_image(f"grs-bulk-{index}.png", "PNG")) for index in range(10)]
        with self.assertRaisesRegex(CloudVideoError, "参考图最多"):
            client.submit(_submit_request(
                model="minimax-h3", options={"duration": 5, "resolution": "480p"}, references=refs,
            ))

    def test_grs_poll_maps_violation_and_running(self) -> None:
        session = _FakeSession({
            ("get", "/v1/api/result"): _FakeResponse({
                "id": "grs-4", "status": "violation", "error": "prompt violation",
            }),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        snapshot = client.poll("grs-4")
        self.assertEqual(snapshot.status, "failed")
        self.assertIn("内容违规", snapshot.message or "")
        running_session = _FakeSession({
            ("get", "/v1/api/result"): _FakeResponse({"id": "grs-5", "status": "running", "progress": 42}),
        })
        running_client = build_adapter("grs", base_url=None, api_key="grs-key", session=running_session)
        snapshot = running_client.poll("grs-5")
        self.assertEqual(snapshot.status, "active")
        self.assertEqual(snapshot.progress, 42)

    def test_grs_submit_rejection_surfaces_error(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse(
                {"status": "failed", "error": "prompt contains banned content"}, status_code=400,
            ),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        with self.assertRaisesRegex(CloudVideoError, "banned content"):
            client.submit(_submit_request(
                model="minimax-h3", options={"duration": 5, "resolution": "480p"},
            ))

    def test_grs_test_connection_and_balance(self) -> None:
        session = _FakeSession({
            ("post", "/client/openapi/getAPIKeyCredits"): _FakeResponse({
                "code": 0, "data": {"credits": 1234.5},
            }),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        self.assertEqual(client.balance(), 1234.5)
        self.assertIn("1234.5", client.test_connection())
        method, url, kwargs = session.calls[0]
        self.assertEqual(kwargs["json"], {"apiKey": "grs-key"})

    def test_grs_agnes_submit_t2v_body(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse({"id": "agnes-1", "status": "running"}),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        remote_id = client.submit(_submit_request(
            model="agnes-video-2.5",
            options={"aspect_ratio": "9:16", "duration": 10, "resolution": "2k", "seed": 7},
        ))
        self.assertEqual(remote_id, "agnes-1")
        body = session.calls[0][2]["json"]
        self.assertEqual(body["model"], "agnes-video-2.5")
        self.assertEqual(body["aspectRatio"], "9:16")
        self.assertEqual(body["resolution"], "2k")
        self.assertEqual(body["duration"], 10)
        self.assertEqual(body["replyType"], "async")
        self.assertEqual(body["seed"], 7)
        # Agnes 不支持 H3 的 promptSkill 参数，不得下发
        self.assertNotIn("promptSkill", body)
        self.assertNotIn("images", body)
        self.assertNotIn("firstFrame", body)

    def test_grs_agnes_first_frame_and_paired_frames(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse({"id": "agnes-2", "status": "running"}),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        first = Path(self._tmp_image("agnes-first.png", "PNG"))
        client.submit(_submit_request(
            model="agnes-video-2.5", first_frame=first,
            options={"aspect_ratio": "9:16", "duration": 5, "resolution": "720p"},
        ))
        body = session.calls[0][2]["json"]
        self.assertTrue(body["firstFrame"].startswith("data:image/"))
        self.assertNotIn("lastFrame", body)

        last = Path(self._tmp_image("agnes-last.png", "PNG"))
        client.submit(_submit_request(
            model="agnes-video-2.5", first_frame=first, last_frame=last,
            options={"aspect_ratio": "9:16", "duration": 5, "resolution": "720p"},
        ))
        body = session.calls[1][2]["json"]
        self.assertTrue(body["firstFrame"].startswith("data:image/"))
        self.assertTrue(body["lastFrame"].startswith("data:image/"))

    def test_grs_agnes_maps_references_to_images(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse({"id": "agnes-3", "status": "running"}),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        refs = [Path(self._tmp_image(f"agnes-ref-{index}.png", "PNG")) for index in range(5)]
        client.submit(_submit_request(
            model="agnes-video-2.5", references=refs,
            options={"aspect_ratio": "16:9", "duration": 5, "resolution": "1080p"},
        ))
        body = session.calls[0][2]["json"]
        self.assertEqual(len(body["images"]), 5)
        self.assertTrue(all(item.startswith("data:image/") for item in body["images"]))

    def test_grs_agnes_validation_rejects_invalid_inputs(self) -> None:
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=_FakeSession({}))
        with self.assertRaisesRegex(CloudVideoError, "时长必须是 4-12 秒"):
            client.submit(_submit_request(
                model="agnes-video-2.5", options={"duration": 3, "resolution": "720p"},
            ))
        with self.assertRaisesRegex(CloudVideoError, "分辨率"):
            client.submit(_submit_request(
                model="agnes-video-2.5", options={"duration": 5, "resolution": "480p"},
            ))
        with self.assertRaisesRegex(CloudVideoError, "画幅"):
            client.submit(_submit_request(
                model="agnes-video-2.5", options={"aspect_ratio": "landscape", "duration": 5, "resolution": "720p"},
            ))
        last = Path(self._tmp_image("agnes-last-only.png", "PNG"))
        with self.assertRaisesRegex(CloudVideoError, "尾帧必须与首帧同时提供"):
            client.submit(_submit_request(
                model="agnes-video-2.5", last_frame=last,
                options={"aspect_ratio": "9:16", "duration": 5, "resolution": "720p"},
            ))
        refs = [Path(self._tmp_image(f"agnes-bulk-{index}.png", "PNG")) for index in range(6)]
        with self.assertRaisesRegex(CloudVideoError, "参考图最多 5 张"):
            client.submit(_submit_request(
                model="agnes-video-2.5", references=refs,
                options={"aspect_ratio": "16:9", "duration": 5, "resolution": "720p"},
            ))

    def test_grs_wan_submit_t2v_body(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse({"id": "wan-1", "status": "running"}),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        remote_id = client.submit(_submit_request(
            model="wan-3.0",
            options={"aspect_ratio": "21:9", "duration": 30, "resolution": "1080p", "seed": 11},
        ))
        self.assertEqual(remote_id, "wan-1")
        body = session.calls[0][2]["json"]
        self.assertEqual(body["model"], "wan-3.0")
        self.assertEqual(body["aspectRatio"], "21:9")
        self.assertEqual(body["resolution"], "1080p")
        self.assertEqual(body["duration"], 30)
        self.assertEqual(body["replyType"], "async")
        self.assertEqual(body["seed"], 11)
        # Wan 不支 H3 的 promptSkill 参数，不得下发
        self.assertNotIn("promptSkill", body)
        self.assertNotIn("images", body)
        self.assertNotIn("firstFrame", body)

    def test_grs_wan_first_and_last_frame_are_independent(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse({"id": "wan-2", "status": "running"}),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        first = Path(self._tmp_image("wan-first.png", "PNG"))
        last = Path(self._tmp_image("wan-last.png", "PNG"))
        options = {"aspect_ratio": "9:16", "duration": 8, "resolution": "720p"}
        client.submit(_submit_request(model="wan-3.0", first_frame=first, options=options))
        body = session.calls[0][2]["json"]
        self.assertTrue(body["firstFrame"].startswith("data:image/"))
        self.assertNotIn("lastFrame", body)

        client.submit(_submit_request(model="wan-3.0", last_frame=last, options=options))
        body = session.calls[1][2]["json"]
        self.assertTrue(body["lastFrame"].startswith("data:image/"))
        self.assertNotIn("firstFrame", body)

        client.submit(_submit_request(
            model="wan-3.0", first_frame=first, last_frame=last, options=options,
        ))
        body = session.calls[2][2]["json"]
        self.assertTrue(body["firstFrame"].startswith("data:image/"))
        self.assertTrue(body["lastFrame"].startswith("data:image/"))

    def test_grs_wan_maps_up_to_ten_references(self) -> None:
        session = _FakeSession({
            ("post", "/v1/api/generate"): _FakeResponse({"id": "wan-3", "status": "running"}),
        })
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=session)
        refs = [Path(self._tmp_image(f"wan-ref-{index}.png", "PNG")) for index in range(10)]
        client.submit(_submit_request(
            model="wan-3.0", references=refs,
            options={"aspect_ratio": "16:9", "duration": 5, "resolution": "480p"},
        ))
        body = session.calls[0][2]["json"]
        self.assertEqual(len(body["images"]), 10)
        self.assertTrue(all(item.startswith("data:image/") for item in body["images"]))

    def test_grs_wan_validation_rejects_invalid_inputs(self) -> None:
        client = build_adapter("grs", base_url=None, api_key="grs-key", session=_FakeSession({}))
        with self.assertRaisesRegex(CloudVideoError, "时长必须是 2-30 秒"):
            client.submit(_submit_request(
                model="wan-3.0", options={"duration": 1, "resolution": "720p"},
            ))
        with self.assertRaisesRegex(CloudVideoError, "时长必须是 2-30 秒"):
            client.submit(_submit_request(
                model="wan-3.0", options={"duration": 31, "resolution": "720p"},
            ))
        with self.assertRaisesRegex(CloudVideoError, "分辨率"):
            client.submit(_submit_request(
                model="wan-3.0", options={"duration": 5, "resolution": "768p"},
            ))
        with self.assertRaisesRegex(CloudVideoError, "画幅"):
            client.submit(_submit_request(
                model="wan-3.0", options={"aspect_ratio": "landscape", "duration": 5, "resolution": "720p"},
            ))
        refs = [Path(self._tmp_image(f"wan-bulk-{index}.png", "PNG")) for index in range(11)]
        with self.assertRaisesRegex(CloudVideoError, "参考图最多 10 张"):
            client.submit(_submit_request(
                model="wan-3.0", references=refs,
                options={"aspect_ratio": "16:9", "duration": 5, "resolution": "720p"},
            ))
        first = Path(self._tmp_image("wan-conflict.png", "PNG"))
        with self.assertRaisesRegex(CloudVideoError, "首尾帧与参考图互斥"):
            client.submit(_submit_request(
                model="wan-3.0", first_frame=first, references=[first],
                options={"aspect_ratio": "16:9", "duration": 5, "resolution": "720p"},
            ))

    # ------------------------------------------------------------------
    # MiniMax 官方平台（H3 v2 API）
    # ------------------------------------------------------------------

    def test_minimax_submit_t2v_and_poll(self) -> None:
        session = _FakeSession({
            ("post", "/v2/video_generation"): _FakeResponse({"task_id": "mx2-1"}),
            ("get", "/v2/query/video_generation/mx2-1"): _FakeResponse({
                "task": {
                    "id": "mx2-1", "model": "MiniMax-H3-Lite", "status": "succeeded",
                    "content": {"url": "https://cdn.hailuoai.com/mx2.mp4"},
                    "resolution": "480P", "duration": 5,
                },
            }),
        })
        client = build_adapter("minimax", base_url=None, api_key="mx-key", session=session)
        remote_id = client.submit(_submit_request(
            model="MiniMax-H3-Lite",
            options={"aspect_ratio": "9:16", "duration": 5, "resolution": "480P", "generate_audio": True},
        ))
        self.assertEqual(remote_id, "mx2-1")
        method, url, kwargs = session.calls[0]
        self.assertEqual(url, "https://api.minimax.cn/v2/video_generation")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer mx-key")
        body = kwargs["json"]
        self.assertEqual(body["model"], "MiniMax-H3-Lite")
        self.assertEqual(body["content"][0], {"type": "text", "text": "一只猫在雪地里奔跑"})
        self.assertEqual(len(body["content"]), 1)  # 文生视频无参考素材
        self.assertEqual(body["resolution"], "480P")
        self.assertEqual(body["duration"], 5)
        self.assertEqual(body["ratio"], "9:16")  # 文生视频必须显式画幅
        self.assertTrue(body["generate_audio"])
        self.assertFalse(body["aigc_watermark"])
        snapshot = client.poll(remote_id)
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.video_urls, ["https://cdn.hailuoai.com/mx2.mp4"])
        self.assertEqual(snapshot.remote_status, "succeeded")

    def test_minimax_submit_i2v_and_fl2v_roles(self) -> None:
        session = _FakeSession({
            ("post", "/v2/video_generation"): _FakeResponse({"task_id": "mx2-2"}),
        })
        client = build_adapter("minimax", base_url=None, api_key="mx-key", session=session)
        first = Path(self._tmp_image("mx-first.png", "PNG"))
        client.submit(_submit_request(
            model="MiniMax-H3-Lite", first_frame=first, options={"duration": 5, "resolution": "768P"},
        ))
        body = session.calls[0][2]["json"]
        self.assertEqual([item["role"] for item in body["content"][1:]], ["first_frame"])
        self.assertTrue(body["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertNotIn("ratio", body)  # 图生视频宽高比恒随输入，不下发
        tail = Path(self._tmp_image("mx-tail.png", "PNG"))
        client.submit(_submit_request(
            model="MiniMax-H3", first_frame=first, last_frame=tail,
            options={"duration": 5, "resolution": "2K"},
        ))
        body = session.calls[1][2]["json"]
        self.assertEqual([item["role"] for item in body["content"][1:]], ["first_frame", "last_frame"])
        self.assertEqual(body["resolution"], "2K")  # H3 旗舰档独享

    def test_minimax_submit_maps_references(self) -> None:
        session = _FakeSession({
            ("post", "/v2/video_generation"): _FakeResponse({"task_id": "mx2-3"}),
        })
        client = build_adapter("minimax", base_url=None, api_key="mx-key", session=session)
        refs = [
            Path(self._tmp_image("mx-ref-1.png", "PNG")),
            Path(self._tmp_image("mx-ref-2.png", "PNG")),
        ]
        client.submit(_submit_request(
            model="MiniMax-H3-Lite",
            options={"duration": 5, "resolution": "480P", "aspect_ratio": "16:9"},
            references=refs,
        ))
        body = session.calls[0][2]["json"]
        self.assertEqual([item["role"] for item in body["content"][1:]], ["reference_image", "reference_image"])
        # 官方参考生必须显式 ratio：Lite/Highspeed/Max 档不接受 adaptive
        self.assertEqual(body["ratio"], "16:9")
        with self.assertRaisesRegex(CloudVideoError, "必须显式指定画幅"):
            client.submit(_submit_request(
                model="MiniMax-H3-Lite", options={"duration": 5, "resolution": "480P"}, references=refs,
            ))

    def test_minimax_submit_rejects_cross_tier_and_overflow(self) -> None:
        client = build_adapter("minimax", base_url=None, api_key="mx-key", session=_FakeSession({}))
        with self.assertRaisesRegex(CloudVideoError, "2K 分辨率仅"):
            client.submit(_submit_request(
                model="MiniMax-H3-Lite", options={"duration": 5, "resolution": "2K"},
            ))
        with self.assertRaisesRegex(CloudVideoError, "480P 仅 MiniMax-H3-Lite"):
            client.submit(_submit_request(
                model="MiniMax-H3", options={"duration": 5, "resolution": "480P"},
            ))
        with self.assertRaisesRegex(CloudVideoError, "时长必须是 5-15"):
            client.submit(_submit_request(
                model="MiniMax-H3-Max", options={"duration": 4, "resolution": "480P"},
            ))
        refs = [Path(self._tmp_image(f"mx-bulk-{index}.png", "PNG")) for index in range(10)]
        with self.assertRaisesRegex(CloudVideoError, "参考图最多"):
            client.submit(_submit_request(
                model="MiniMax-H3-Lite", options={"duration": 5, "resolution": "480P"}, references=refs,
            ))
        tail_only = Path(self._tmp_image("mx-tail-only.png", "PNG"))
        with self.assertRaisesRegex(CloudVideoError, "首尾帧必须成对提供"):
            client.submit(_submit_request(
                model="MiniMax-H3-Lite", last_frame=tail_only, options={"duration": 5, "resolution": "480P"},
            ))

    def test_minimax_poll_failed_cancelled_and_running(self) -> None:
        session = _FakeSession({
            ("get", "/v2/query/video_generation/mx2-4"): _FakeResponse({
                "task": {
                    "id": "mx2-4", "status": "failed",
                    "error": {"code": "1026", "message": "video description contains sensitive content"},
                },
            }),
        })
        client = build_adapter("minimax", base_url=None, api_key="mx-key", session=session)
        snapshot = client.poll("mx2-4")
        self.assertEqual(snapshot.status, "failed")
        self.assertEqual(snapshot.message, "video description contains sensitive content")
        cancelled_session = _FakeSession({
            ("get", "/v2/query/video_generation/mx2-5"): _FakeResponse(
                {"task": {"id": "mx2-5", "status": "cancelled"}},
            ),
        })
        cancelled_client = build_adapter("minimax", base_url=None, api_key="mx-key", session=cancelled_session)
        snapshot = cancelled_client.poll("mx2-5")
        self.assertEqual(snapshot.status, "failed")
        self.assertEqual(snapshot.message, "官方任务失败")
        running_session = _FakeSession({
            ("get", "/v2/query/video_generation/mx2-6"): _FakeResponse(
                {"task": {"id": "mx2-6", "status": "running"}},
            ),
        })
        running_client = build_adapter("minimax", base_url=None, api_key="mx-key", session=running_session)
        snapshot = running_client.poll("mx2-6")
        self.assertEqual(snapshot.status, "active")
        self.assertEqual(snapshot.progress, 12)

    def test_minimax_submit_rejection_surfaces_error(self) -> None:
        session = _FakeSession({
            ("post", "/v2/video_generation"): _FakeResponse(
                {"error": {"type": "invalid_request_error", "message": "prompt contains banned content", "http_code": 400}},
                status_code=400,
            ),
        })
        client = build_adapter("minimax", base_url=None, api_key="mx-key", session=session)
        with self.assertRaisesRegex(CloudVideoError, "banned content"):
            client.submit(_submit_request(
                model="MiniMax-H3-Lite", options={"duration": 5, "resolution": "480P"},
            ))

    def test_minimax_test_connection_distinguishes_auth(self) -> None:
        ok_session = _FakeSession({
            ("get", "/v2/query/video_generation/zly-probe-nonexistent-task"): _FakeResponse(
                {"error": {"type": "not_found", "message": "invalid task_id", "http_code": 404}},
                status_code=404,
            ),
        })
        client = build_adapter("minimax", base_url=None, api_key="mx-key", session=ok_session)
        self.assertIn("鉴权通过", client.test_connection())
        bad_session = _FakeSession({
            ("get", "/v2/query/video_generation/zly-probe-nonexistent-task"): _FakeResponse(
                {"error": {"type": "authentication_error", "message": "invalid api key", "http_code": 401}},
                status_code=401,
            ),
        })
        bad_client = build_adapter("minimax", base_url=None, api_key="bad", session=bad_session)
        with self.assertRaisesRegex(CloudVideoError, "API Key 无效"):
            bad_client.test_connection()

    # ------------------------------------------------------------------
    # 状态归一与扣费警示
    # ------------------------------------------------------------------

    def test_normalize_status(self) -> None:
        self.assertEqual(normalize_cloud_task_status("submitted"), "active")
        self.assertEqual(normalize_cloud_task_status("Processing"), "active")
        self.assertEqual(normalize_cloud_task_status("succeed"), "completed")
        self.assertEqual(normalize_cloud_task_status("Success"), "completed")
        self.assertEqual(normalize_cloud_task_status("failed"), "failed")
        self.assertEqual(normalize_cloud_task_status("cancelled"), "failed")
        self.assertEqual(normalize_cloud_task_status(""), "active")
        self.assertEqual(normalize_cloud_task_status("something-new"), "active")

    def test_billing_caution_not_duplicated(self) -> None:
        once = with_cloud_video_billing_caution("提交超时")
        self.assertIn("为避免重复扣费", once)
        again = with_cloud_video_billing_caution(once)
        self.assertEqual(once, again)

    def test_uncertain_submit_error_is_distinct(self) -> None:
        self.assertTrue(issubclass(CloudVideoUncertainSubmitError, CloudVideoError))

    # ------------------------------------------------------------------

    def _tmp_image(self, name: str, fmt: str) -> str:
        """生成真实图片文件（data_uri 复用 GRS 的 PIL 校验，假字节会被拒绝）。"""
        if not hasattr(self, "_tmp"):
            self._tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / name
        Image.new("RGB", (8, 8), (200, 30, 30)).save(path, format=fmt)
        return str(path)


def _submit_request(
    *, model: str = "kling-v1-6", first_frame: Path | None = None, last_frame: Path | None = None,
    references: list[Path] | None = None, options: dict | None = None,
):
    from backend.app.cloud_video.base import CloudVideoSubmitRequest

    return CloudVideoSubmitRequest(
        model=model, prompt="一只猫在雪地里奔跑", negative_prompt="低画质",
        first_frame=first_frame, last_frame=last_frame, references=references,
        options=options or {"aspect_ratio": "16:9", "duration": "5"},
    )


class CloudVideoServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")
        self.key = _fernet_key()
        CloudVideoService._instance = None

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        CloudVideoService._instance = None

    def test_configure_and_availability(self) -> None:
        service = CloudVideoService.configure(self.store, self.key, None)
        self.assertIs(service, CloudVideoService.instance())
        unavailable, reason = service.availability("kling")
        self.assertFalse(unavailable)
        self.assertIn("尚未在管理设置中启用", reason or "")
        self.store.update_cloud_video_settings("kling", enabled=1)
        no_key, reason2 = service.availability("kling")
        self.assertFalse(no_key)
        self.assertIn("AccessKey", reason2 or "")
        service.update_provider("kling", {"api_key": "ak-1"})
        no_secret, reason3 = service.availability("kling")
        self.assertFalse(no_secret)
        self.assertIn("SecretKey", reason3 or "")

    def test_update_provider_encrypts_keys(self) -> None:
        service = CloudVideoService.configure(self.store, self.key, None)
        config = service.update_provider(
            "kling", {"enabled": True, "api_key": "ak-xyz", "api_secret": "sk-xyz"},
        )
        self.assertTrue(config["enabled"])
        self.assertTrue(config["has_api_key"])
        self.assertNotIn("ak-xyz", json.dumps(config))
        stored = self.store.get_cloud_video_settings("kling")
        self.assertNotIn("ak-xyz", stored.get("api_key_encrypted") or "")

    def test_public_configs_cover_all_providers(self) -> None:
        service = CloudVideoService.configure(self.store, self.key, None)
        configs = service.public_configs()
        self.assertEqual(
            [item["provider_key"] for item in configs], ["kling", "jimeng", "hailuo", "scnet", "grs", "minimax"],
        )
        for item in configs:
            self.assertIn("available", item)
            self.assertIn("unavailable_reason", item)

    def test_test_provider_writes_last_test(self) -> None:
        service = CloudVideoService.configure(self.store, self.key, None)
        with patch.object(service, "client") as client_factory:
            client = MagicMock()
            client.test_connection.return_value = "连接成功，账户余额 12.00"
            client_factory.return_value = client
            result = service.test_provider("kling")
        self.assertEqual(result["available"], False)  # 未启用 → 仍不可用，但测试记录已写
        stored = self.store.get_cloud_video_settings("kling")
        self.assertEqual(stored["last_test_status"], "success")

    def test_test_provider_failure_records(self) -> None:
        service = CloudVideoService.configure(self.store, self.key, None)
        with patch.object(service, "client") as client_factory:
            client = MagicMock()
            client.test_connection.side_effect = CloudVideoError("鉴权失败")
            client_factory.return_value = client
            with self.assertRaises(CloudVideoError):
                service.test_provider("kling")
        stored = self.store.get_cloud_video_settings("kling")
        self.assertEqual(stored["last_test_status"], "failed")
        self.assertIn("鉴权失败", stored["last_test_message"] or "")


class _StubCloudVideoService:
    """execute_cloud_video 的替身：不触网。"""

    def __init__(self, *, fail_submit: bool = False) -> None:
        self.fail_submit = fail_submit

    def availability(self, provider_key: str):
        return True, None

    def submit_generation(self, provider_key: str, **kwargs):
        if self.fail_submit:
            raise CloudVideoUncertainSubmitError(with_cloud_video_billing_caution("提交已发出但等待响应超时"))
        return "remote-123"

    def resume_snapshot(self, provider_key: str, remote_task_id: str) -> CloudTaskSnapshot:
        return CloudTaskSnapshot(
            status="completed", video_urls=["https://cdn/fake.mp4"], remote_status="succeed",
        )

    def download_and_store(self, video_urls, *, prefix: str, filename: str, label: str = "生成视频"):
        self.downloaded_prefix = prefix
        self.downloaded_filename = filename
        return {"kind": "video", "path": f"{prefix}/{filename}", "label": label, "delivery_status": "pending"}


class WorkerCloudVideoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")
        self.worker = JobWorker(self.store, comfy=MagicMock(), grs_provider=None, resource_storage=MagicMock())
        self.worker.resource_storage.persistent_outputs = False

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_job(self, mode: str) -> tuple[str, str]:
        job_id = str(uuid.uuid4())
        self.store.create(job_id, mode, "一只猫在雪地里奔跑", "", None, [], {}, submitted_options={})
        job = self.store.get(job_id)
        item = job["rounds"][-1]["generation_items"][0]
        return job_id, item["id"]

    def _run(self, coroutine) -> None:
        asyncio.run(coroutine)

    def test_execute_cloud_video_happy_path(self) -> None:
        job_id, item_id = self._create_job("cloud-kling-t2v")
        stub = _StubCloudVideoService()
        with patch.object(worker_module, "CloudVideoService") as service_class:
            service_class.instance.return_value = stub
            self._run(self.worker.execute_cloud_video(item_id))
        job = self.store.get(job_id)
        item = job["rounds"][-1]["generation_items"][0]
        self.assertEqual(item["status"], JobStatus.SUCCEEDED.value)
        self.assertEqual(item["remote_task_id"], "remote-123")
        self.assertEqual(item["outputs"][0]["kind"], "video")
        self.assertEqual(stub.downloaded_filename, "kling_remote-123.mp4")

    def test_execute_cloud_video_uncertain_submit_interrupted(self) -> None:
        job_id, item_id = self._create_job("cloud-kling-t2v")
        stub = _StubCloudVideoService(fail_submit=True)
        with patch.object(worker_module, "CloudVideoService") as service_class:
            service_class.instance.return_value = stub
            self._run(self.worker.execute_cloud_video(item_id))
        job = self.store.get(job_id)
        item = job["rounds"][-1]["generation_items"][0]
        self.assertEqual(item["status"], JobStatus.INTERRUPTED.value)
        self.assertIn("为避免重复扣费", item["error"] or "")
        self.assertIsNone(item.get("remote_task_id"))

    def test_execute_cloud_video_service_unavailable(self) -> None:
        job_id, item_id = self._create_job("cloud-hailuo-t2v")
        stub = _StubCloudVideoService()
        stub.availability = lambda provider_key: (False, "「海螺 Hailuo（MiniMax）」尚未在管理设置中启用。")
        with patch.object(worker_module, "CloudVideoService") as service_class:
            service_class.instance.return_value = stub
            self._run(self.worker.execute_cloud_video(item_id))
        job = self.store.get(job_id)
        item = job["rounds"][-1]["generation_items"][0]
        self.assertEqual(item["status"], JobStatus.FAILED.value)
        self.assertIn("尚未在管理设置中启用", item["error"] or "")

    def test_reference_media_keyframes(self) -> None:
        upload_dir = Path(self.temp_dir.name) / "uploads"
        upload_dir.mkdir()
        first = upload_dir / "first.png"
        first.write_bytes(b"\x89PNG")
        definition = workflow_for("cloud-kling-i2v")
        # settings 是冻结 dataclass，直接替换 worker 模块引用（_cloud_video_reference_media 只读 uploads_dir）
        with patch.object(worker_module, "settings", SimpleNamespace(uploads_dir=upload_dir)):
            first_frame, last_frame, references = JobWorker._cloud_video_reference_media(
                definition, {"references": [str(first)]},
            )
        self.assertEqual(first_frame, first.resolve())
        self.assertIsNone(last_frame)
        self.assertEqual(references, [])

    def test_reference_media_collection_passthrough(self) -> None:
        """GRS R2V 等 collection 槽位：参考图整体透传给云端适配器的 references。"""
        upload_dir = Path(self.temp_dir.name) / "uploads"
        upload_dir.mkdir()
        refs = []
        for index in range(3):
            path = upload_dir / f"ref{index}.png"
            path.write_bytes(b"\x89PNG")
            refs.append(path)
        definition = workflow_for("cloud-grs-h3-r2v")
        with patch.object(worker_module, "settings", SimpleNamespace(uploads_dir=upload_dir)):
            first_frame, last_frame, references = JobWorker._cloud_video_reference_media(
                definition, {"references": [str(path) for path in refs]},
            )
        self.assertIsNone(first_frame)
        self.assertIsNone(last_frame)
        self.assertEqual(references, [path.resolve() for path in refs])


class CloudVideoDownloadTests(unittest.TestCase):
    def test_download_rejects_non_video(self) -> None:
        with patch("backend.app.cloud_video_service.requests.get") as get_mock:
            response = MagicMock()
            response.iter_content.return_value = [b"<html>not a video</html>"]
            get_mock.return_value = response
            with self.assertRaisesRegex(CloudVideoError, "不是有效的"):
                CloudVideoService._download_video(["https://cdn/fake.mp4"])

    def test_download_accepts_mp4(self) -> None:
        payload = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64
        with patch("backend.app.cloud_video_service.requests.get") as get_mock:
            response = MagicMock()
            response.iter_content.return_value = [payload]
            get_mock.return_value = response
            content = CloudVideoService._download_video(["https://cdn/fake.mp4"])
        self.assertEqual(content, payload)


if __name__ == "__main__":
    unittest.main()
