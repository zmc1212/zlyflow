"""云端视频逐镜任务（剧集工坊）单元测试。

覆盖：云端只允许逐镜/选中镜头、时长取整与夹取、参考图上限、计费快照、执行编排与失败退款。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.media_studio.services import episode_video_service as module
from backend.app.media_studio.services.episode_video_service import EpisodeVideoService


def _shot(sequence: int, duration: float, refs: int = 3) -> dict:
    return {
        "beat_id": f"beat-{sequence}",
        "sequence": sequence,
        "duration_sec": duration,
        "reference_urls": [f"https://cdn.example.com/{sequence}-{index}.png" for index in range(refs)],
        "prompt_cache_base": {},
    }


class CloudShotCreateTests(unittest.TestCase):
    def test_episode_scope_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "仅支持"):
            EpisodeVideoService._create_cloud_shot_job(
                "proj-1", "ep-1",
                workflow_id="cloud-minimax-h3-r2v",
                settings={"model": "MiniMax-H3-Lite", "resolution": "768P", "aspect_ratio": "16:9"},
                options={}, selected_ids=[], render_scope="episode",
                prompt_mode="h3", model_name="MiniMax 官方 H3",
            )

    def test_duration_is_rounded_and_clamped_and_billed(self) -> None:
        captured: dict = {}

        def fake_execute(sql: str, params: tuple | None = None) -> int:
            if "INSERT INTO ai_project_jobs" in sql:
                captured["params"] = params
            return 1

        def fake_bill(user, mode, options, *, job_id, reference_counts=None):
            captured["bill"] = {
                "user": user, "mode": mode, "options": dict(options), "job_id": job_id,
                "reference_counts": list(reference_counts or []),
            }
            return {"total": 312, "per_item": 312, "wallet_enterprise_id": "enterprise-1", "price_key": "cloud:cloud-minimax-h3-r2v"}

        with patch.object(module, "execute_sql", fake_execute), \
             patch.object(module, "query_one", lambda *a, **k: {"owner_user_id": "user-1"}), \
             patch.object(EpisodeVideoService, "_assert_can_enqueue", lambda *a, **k: None), \
             patch.object(module.ProjectDetailService, "get_episode_detail", lambda *a, **k: {"number": 1, "title": "第一集"}), \
             patch.object(module.ProjectDetailService, "list_assets", lambda *a, **k: []), \
             patch.object(EpisodeVideoService, "_prepare_shots", lambda *a, **k: [
                 _shot(1, 12.4, refs=2), _shot(2, 2.0, refs=12),
             ]), \
             patch.object(module, "CreditService", return_value=SimpleNamespace(bill_job=fake_bill)), \
             patch.object(module, "JobStore", return_value=object()), \
             patch.object(EpisodeVideoService, "_submit_job", lambda job_id: None):
            result = EpisodeVideoService._create_cloud_shot_job(
                "proj-1", "ep-1",
                workflow_id="cloud-minimax-h3-r2v",
                settings={"model": "MiniMax-H3-Lite", "resolution": "768P", "aspect_ratio": "16:9"},
                options={}, selected_ids=["beat-1", "beat-2"], render_scope="selection",
                prompt_mode="h3", model_name="MiniMax 官方 H3",
            )

        self.assertEqual(result["shot_count"], 2)
        self.assertEqual(captured["bill"]["user"], "user-1")
        self.assertEqual(captured["bill"]["mode"], "cloud-minimax-h3-r2v")
        # 12.4 → 12；2.0 → 夹到下限 4；合计 16 秒参与计价
        self.assertEqual(captured["bill"]["options"]["duration"], 16)
        # 输入图片费按镜头分别计数：镜 1 两张、镜 2 截断到官方上限 9 张
        self.assertEqual(captured["bill"]["reference_counts"], [2, 9])
        payload = json.loads(captured["params"][3])
        durations = [shot["cloud_duration"] for shot in payload["source_shots"]]
        self.assertEqual(durations, [12, 4])
        self.assertEqual(len(payload["source_shots"][1]["reference_urls"]), 9)  # 参考图截断到官方上限
        self.assertEqual(payload["billing"]["credits"], 312)
        self.assertEqual(payload["billing"]["wallet_enterprise_id"], "enterprise-1")
        self.assertEqual(payload["billing"]["price_key"], "cloud:cloud-minimax-h3-r2v")
        self.assertEqual(payload["cloud_total_seconds"], 16)
        self.assertEqual(payload["render_mode"], "shot")


class CloudShotRunTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "workflow_id": "cloud-minimax-h3-r2v",
            "project_id": "proj-1",
            "episode_id": "ep-1",
            "render_scope": "shot",
            "prompt_mode": "h3",
            "cloud_base_options": {"model": "MiniMax-H3-Lite", "resolution": "768P", "aspect_ratio": "16:9"},
            "billing": {"user_id": "user-1", "credits": 312},
            "source_shots": [_shot(1, 12.0)],
            "shots": [],
            "render_plan": {"status": "queued"},
        }

    def _fake_service(self, root: Path) -> SimpleNamespace:
        calls: dict = {"submit": [], "stored": 0}

        def submit(provider, **kwargs):
            calls["submit"].append({"provider": provider, **{k: v for k, v in kwargs.items() if k != "references"}})
            calls["submit"][-1]["reference_count"] = len(kwargs.get("references") or [])
            return "remote-1"

        def wait(provider, remote_task_id, *, on_progress=None):
            return SimpleNamespace(
                status="completed", video_urls=["https://cdn.example.com/out.mp4"],
                message="", remote_status="succeeded",
            )

        def store(urls, *, prefix, filename, label="生成视频"):
            calls["stored"] += 1
            return {"kind": "video", "path": f"{prefix}/{filename}", "cloud_url": "https://cdn.qiniu.example.com/out.mp4"}

        service = SimpleNamespace(
            availability=lambda provider: (True, None),
            resource_storage=object(),
            submit_generation=submit,
            wait_for_task=wait,
            download_and_store=store,
        )
        service.calls = calls
        return service

    def test_happy_path_writes_shot_video_and_completes(self) -> None:
        payload = self._payload()
        executed: list[str] = []
        written: dict = {}

        def fake_write(_payload, shots, result_url, job_id=""):
            written["shots"] = shots
            written["result_url"] = result_url

        with patch.object(module.CloudVideoService, "instance", return_value=self._fake_service(Path("."))), \
             patch.object(EpisodeVideoService, "_prepare_job_prompts", lambda job_id, p: ["prompt-1"]), \
             patch.object(EpisodeVideoService, "_download_cloud_references", lambda shot, root, index: [Path("ref.png")]), \
             patch.object(EpisodeVideoService, "_write_selected_beat_videos", fake_write), \
             patch.object(module, "execute_sql", lambda sql, params=None: executed.append(sql) or 1):
            EpisodeVideoService._run_cloud_job("job-1", payload)

        self.assertEqual(written["result_url"], "https://cdn.qiniu.example.com/out.mp4")
        self.assertEqual(written["shots"][0]["video_url"], "https://cdn.qiniu.example.com/out.mp4")
        self.assertTrue(any("status = 'completed'" in sql for sql in executed))

    def test_failure_refunds_and_marks_failed(self) -> None:
        payload = self._payload()
        payload["billing"].update(wallet_enterprise_id="enterprise-1", price_key="cloud:cloud-minimax-h3-r2v")
        executed: list[str] = []
        refunds: list[dict] = []

        class FakeCredit:
            def refund_deduction(self, user_id, amount, *, job_id, reason, wallet_enterprise_id, price_key):
                refunds.append({
                    "user_id": user_id, "amount": amount, "job_id": job_id,
                    "wallet_enterprise_id": wallet_enterprise_id, "price_key": price_key,
                })
                return {"ok": True}

        service = self._fake_service(Path("."))
        service.submit_generation = lambda provider, **kwargs: (_ for _ in ()).throw(RuntimeError("云端提交失败"))

        with patch.object(module.CloudVideoService, "instance", return_value=service), \
             patch.object(EpisodeVideoService, "_prepare_job_prompts", lambda job_id, p: ["prompt-1"]), \
             patch.object(EpisodeVideoService, "_download_cloud_references", lambda shot, root, index: [Path("ref.png")]), \
             patch.object(module, "CreditService", return_value=FakeCredit()), \
             patch.object(module, "JobStore", return_value=object()), \
             patch.object(module, "execute_sql", lambda sql, params=None: executed.append(sql) or 1):
            with self.assertRaises(RuntimeError):
                EpisodeVideoService._run_cloud_job("job-2", payload)

        self.assertEqual(refunds, [{
            "user_id": "user-1", "amount": 312, "job_id": "job-2",
            "wallet_enterprise_id": "enterprise-1", "price_key": "cloud:cloud-minimax-h3-r2v",
        }])
        self.assertTrue(any("status = 'failed'" in sql for sql in executed))


if __name__ == "__main__":
    unittest.main()
