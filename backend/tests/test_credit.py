from __future__ import annotations

import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.credit_service import CreditService, compute_cost_preview
from backend.app.grs_provider import GrsProviderService
from backend.app.main import SESSION_COOKIE, app
from backend.app.models import CreditPriceRuleUpdateItem, JobStatus, UserRole
from backend.app.storage import CreditInsufficientError, JobStore
from backend.app.workflow_registry import set_catalog_lookup
from backend.tests.app_state_guard import restore_app_state, snapshot_app_state


def _unique_id() -> str:
    return uuid.uuid4().hex[:12]


class CreditPricingTests(unittest.TestCase):
    """计价数学：云端视频按秒分档、GRS 换算系数与按模型覆盖、本地免费。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")
        self.credits = CreditService(self.store)

    def tearDown(self) -> None:
        set_catalog_lookup(None)
        self.temp_dir.cleanup()

    def test_price_rule_seeds_exist(self) -> None:
        rules = {rule["rule_key"]: rule for rule in self.store.list_credit_price_rules()}
        self.assertIn("cloud:cloud-kling-t2v", rules)
        self.assertEqual(rules["cloud:cloud-kling-t2v"]["unit_by_variant"], {"std": 40, "pro": 80})
        self.assertIn("cloud:cloud-scnet-h3-t2v", rules)
        for mode_id in ("cloud-grs-h3-t2v", "cloud-grs-h3-r2v", "cloud-grs-h3-fl2v"):
            rule = rules[f"cloud:{mode_id}"]
            self.assertEqual(rule["unit_by_variant"], {"480p": 5, "768p": 7, "1080p": 15})
            self.assertIn("成本直换", rule["note"])
        minimax_variants = {
            "MiniMax-H3-Lite:480P": 16,
            "MiniMax-H3-Lite:768P": 26,
            "MiniMax-H3-Highspeed:480P": 26,
            "MiniMax-H3-Highspeed:768P": 40,
            "MiniMax-H3:768P": 50,
            "MiniMax-H3:2K": 80,
            "MiniMax-H3-Max:480P": 33,
            "MiniMax-H3-Max:768P": 50,
        }
        for mode_id in ("cloud-minimax-h3-t2v", "cloud-minimax-h3-i2v", "cloud-minimax-h3-fl2v", "cloud-minimax-h3-r2v"):
            rule = rules[f"cloud:{mode_id}"]
            self.assertEqual(rule["unit_by_variant"], minimax_variants)
            self.assertIn("MiniMax 官方成本直换", rule["note"])
        self.assertIn("grs_image:global", rules)
        self.assertEqual(rules["grs_image:global"]["extra_config"]["grs_credits_to_platform"], 2.0)
        for kind in ("optimize_prompt", "split_script", "director_plan", "assistant_chat", "director_clarify"):
            self.assertIn(f"llm:{kind}", rules)
        self.assertIn("vlm:analyze_subject", rules)

    def test_estimate_cloud_video_per_second_by_variant(self) -> None:
        estimate = self.credits.estimate_job("cloud-kling-t2v", {"duration": 5, "kling_mode": "std"})
        self.assertEqual(estimate["credits"], 200)
        self.assertEqual(estimate["unit_credits"], 40)
        pro = self.credits.estimate_job("cloud-kling-t2v", {"duration": 10, "kling_mode": "pro"})
        self.assertEqual(pro["credits"], 800)
        h3_768 = self.credits.estimate_job("cloud-scnet-h3-t2v", {"duration": 8, "resolution": "768P"})
        self.assertEqual(h3_768["credits"], 400)
        h3_2k = self.credits.estimate_job("cloud-scnet-h3-t2v", {"duration": 8, "resolution": "2K"})
        self.assertEqual(h3_2k["credits"], 800)

    def test_estimate_grs_h3_by_resolution(self) -> None:
        """GRS H3 成本直换：480p 5 / 768p 7 / 1080p 15 积分每秒，三种任务形态同价。"""
        tiers = self.credits.estimate_job("cloud-grs-h3-t2v", {"duration": 10, "resolution": "768p"})
        self.assertEqual(tiers["credits"], 70)
        self.assertEqual(tiers["unit_credits"], 7)
        self.assertEqual(self.credits.estimate_job("cloud-grs-h3-t2v", {"duration": 10, "resolution": "480p"})["credits"], 50)
        self.assertEqual(self.credits.estimate_job("cloud-grs-h3-t2v", {"duration": 10, "resolution": "1080p"})["credits"], 150)
        self.assertEqual(
            self.credits.estimate_job("cloud-grs-h3-r2v", {"duration": 5, "resolution": "768p"})["credits"], 35,
        )
        self.assertEqual(
            self.credits.estimate_job("cloud-grs-h3-fl2v", {"duration": 8, "resolution": "1080p"})["credits"], 120,
        )

    def test_estimate_grs_agnes_by_resolution(self) -> None:
        """GRS Agnes 2.5 成本直换：720p 10 / 1080p 17 / 2k 23 积分每秒，四种任务形态同价。"""
        tiers = self.credits.estimate_job("cloud-grs-agnes-t2v", {"duration": 10, "resolution": "1080p"})
        self.assertEqual(tiers["credits"], 170)
        self.assertEqual(tiers["unit_credits"], 17)
        self.assertEqual(
            self.credits.estimate_job("cloud-grs-agnes-t2v", {"duration": 4, "resolution": "720p"})["credits"], 40,
        )
        self.assertEqual(
            self.credits.estimate_job("cloud-grs-agnes-t2v", {"duration": 12, "resolution": "2k"})["credits"], 276,
        )
        self.assertEqual(
            self.credits.estimate_job("cloud-grs-agnes-r2v", {"duration": 5, "resolution": "720p"})["credits"], 50,
        )
        rule = self.store.get_credit_price_rule("cloud:cloud-grs-agnes-i2v")
        self.assertEqual(
            rule["extra_config"]["native_variant_prices"], {"720p": 0.10, "1080p": 0.17, "2k": 0.23},
        )
        self.assertEqual(rule["extra_config"]["price_source"], "native")

    def test_native_price_mapping_and_provider_coefficient(self) -> None:
        """归一化层：原生价 × 每元积分 × 供应商系数 = 平台单价，估算与展示同口径。"""
        rule = self.store.get_credit_price_rule("cloud:cloud-grs-h3-t2v")
        self.assertEqual(
            rule["extra_config"]["native_variant_prices"],
            {"480p": 0.05, "768p": 0.07, "1080p": 0.15},
        )
        self.assertEqual(rule["extra_config"]["price_source"], "native")
        billing = self.credits.billing_info("cloud-grs-h3-t2v")
        self.assertEqual(billing["resolved_unit_by_variant"], {"480p": 5, "768p": 7, "1080p": 15})
        self.assertEqual(billing["summary"], "5-15 积分/秒")
        self.assertEqual(billing["price_source"], "native")

        extra = dict(rule["extra_config"])
        extra["provider_coefficient"] = 2.0
        self.store.update_credit_price_rules([{"rule_key": "cloud:cloud-grs-h3-t2v", "extra_config": extra}])
        doubled = self.credits.estimate_job("cloud-grs-h3-t2v", {"duration": 10, "resolution": "768p"})
        self.assertEqual(doubled["credits"], 140)
        self.assertEqual(doubled["unit_credits"], 14)
        self.assertEqual(
            self.credits.billing_info("cloud-grs-h3-t2v")["summary"], "10-30 积分/秒",
        )

    def test_manual_price_source_keeps_admin_units(self) -> None:
        """运营切换为手动单价后，原生价只做展示，不再覆盖 unit_by_variant。"""
        rule = self.store.get_credit_price_rule("cloud:cloud-grs-h3-t2v")
        extra = dict(rule["extra_config"])
        extra.update({"price_source": "manual", "provider_coefficient": 2.0})
        self.store.update_credit_price_rules([{"rule_key": "cloud:cloud-grs-h3-t2v", "extra_config": extra}])
        estimate = self.credits.estimate_job("cloud-grs-h3-t2v", {"duration": 10, "resolution": "768p"})
        self.assertEqual(estimate["credits"], 70)
        billing = self.credits.billing_info("cloud-grs-h3-t2v")
        self.assertEqual(billing["price_source"], "manual")
        self.assertEqual(billing["resolved_unit_by_variant"], {"480p": 5, "768p": 7, "1080p": 15})

    def test_minimax_unpriced_combination_falls_back_to_model_price(self) -> None:
        """H3 旗舰档 480P 暂无独立档价时，按同模型已有最低价兜底，避免漏价变免费。"""
        estimate = self.credits.estimate_job(
            "cloud-minimax-h3-t2v", {"duration": 5, "model": "MiniMax-H3", "resolution": "480P"},
        )
        self.assertEqual(estimate["unit_credits"], 50)
        self.assertEqual(estimate["credits"], 250)

    def test_input_image_fee_beyond_free_quota(self) -> None:
        """输入图片费：每任务前 5 张免费，超出部分按模型档位图片单价加收。"""
        estimate = self.credits.estimate_job(
            "cloud-minimax-h3-r2v",
            {"duration": 5, "model": "MiniMax-H3-Lite", "resolution": "768P"},
            reference_counts=[7],
        )
        # 5 秒 × 26 + 2 张 × 13 = 130 + 26
        self.assertEqual(estimate["credits"], 156)
        self.assertEqual(estimate["input_image_credits"], 26)
        self.assertEqual(estimate["input_image_count"], 2)
        self.assertEqual(estimate["input_image_unit_credits"], 13)
        self.assertIn("参考图超出免费额度 2 张 × 13 积分", estimate["breakdown"])

        free = self.credits.estimate_job(
            "cloud-minimax-h3-r2v",
            {"duration": 5, "model": "MiniMax-H3-Lite", "resolution": "768P"},
            reference_counts=[5],
        )
        self.assertEqual(free["credits"], 130)
        self.assertEqual(free["input_image_credits"], 0)

        h3 = self.credits.estimate_job(
            "cloud-minimax-h3-t2v",
            {"duration": 5, "model": "MiniMax-H3", "resolution": "768P"},
            reference_counts=[7],
        )
        self.assertEqual(h3["credits"], 290)  # 5 × 50 + 2 × 20
        self.assertEqual(h3["input_image_unit_credits"], 20)

        # 多镜批量按镜头分别享受免费额度：3 张 × 3 镜都在免费额度内。
        multi = self.credits.estimate_job(
            "cloud-minimax-h3-r2v",
            {"duration": 5, "model": "MiniMax-H3-Lite", "resolution": "768P"},
            reference_counts=[3, 3, 3],
        )
        self.assertEqual(multi["input_image_credits"], 0)
        multi_paid = self.credits.estimate_job(
            "cloud-minimax-h3-r2v",
            {"duration": 5, "model": "MiniMax-H3-Lite", "resolution": "768P"},
            reference_counts=[7, 7],
        )
        self.assertEqual(multi_paid["input_image_credits"], 52)  # 2 + 2 张 × 13

        grs = self.credits.estimate_job(
            "cloud-grs-h3-r2v", {"duration": 5, "resolution": "768p"}, reference_counts=[9],
        )
        self.assertEqual(grs["credits"], 35)  # GRS 未配置输入图片价，不加收
        self.assertEqual(grs["input_image_credits"], 0)

    def test_estimate_minimax_h3_by_model_tier_and_resolution(self) -> None:
        """MiniMax 官方 H3：变体键为「模型档位:分辨率」，选项缺省回落 schema 默认档。"""
        default = self.credits.estimate_job("cloud-minimax-h3-t2v", {"duration": 5})
        self.assertEqual(default["unit_credits"], 26)  # 默认 Lite + 默认 768P
        self.assertEqual(default["credits"], 130)
        lite_480 = self.credits.estimate_job(
            "cloud-minimax-h3-t2v", {"duration": 5, "model": "MiniMax-H3-Lite", "resolution": "480P"},
        )
        self.assertEqual(lite_480["credits"], 80)
        h3_2k = self.credits.estimate_job(
            "cloud-minimax-h3-r2v", {"duration": 8, "model": "MiniMax-H3", "resolution": "2K"},
        )
        self.assertEqual(h3_2k["credits"], 640)
        max_768 = self.credits.estimate_job(
            "cloud-minimax-h3-fl2v", {"duration": 6, "model": "MiniMax-H3-Max", "resolution": "768P"},
        )
        self.assertEqual(max_768["credits"], 300)
        self.assertIn("MiniMax-H3:2K", h3_2k["breakdown"])

    def test_estimate_grs_image_with_ratio_and_override(self) -> None:
        # 目录条目由 catalog lookup 提供（生产环境为 store.get_grs_image_model）。
        set_catalog_lookup(lambda key: {
            "workflow_id": key,
            "provider_model": "nano-banana-pro",
            "display_name": "Nano Banana Pro",
            "description": "",
            "profile": "gpt_image_2",
            "credit_cost": 10,
        } if key == "grs-nano-test" else None)
        estimate = self.credits.estimate_job("grs-nano-test", {"count": 2, "provider_model": "nano-banana-pro"})
        self.assertEqual(estimate["credits"], 40)  # ceil(10 × 2.0) = 20/张 × 2 张
        self.assertEqual(estimate["items"], 2)
        self.assertEqual(estimate["unit_credits"], 20)

        self.store.update_credit_price_rules([{
            "rule_key": "grs_image:global",
            "extra_config": {"grs_credits_to_platform": 2.0, "model_overrides": {"nano-banana-pro": 50}},
        }])
        overridden = self.credits.estimate_job("grs-nano-test", {"count": 2, "provider_model": "nano-banana-pro"})
        self.assertEqual(overridden["credits"], 100)  # 覆盖价 50/张 × 2

    def test_estimate_local_comfy_workflow_is_free(self) -> None:
        estimate = self.credits.estimate_job("minimax-h3-t2v", {"duration": 10})
        self.assertEqual(estimate["credits"], 0)
        unknown = self.credits.estimate_job("not-a-workflow", {})
        self.assertEqual(unknown["credits"], 0)

    def test_estimate_call_and_billing_info(self) -> None:
        self.assertEqual(self.credits.estimate_call("llm", "split_script"), 3)
        self.assertEqual(self.credits.estimate_call("llm", "missing_kind"), 0)
        billing = self.credits.billing_info("cloud-kling-t2v")
        self.assertEqual(billing["scope"], "cloud_video")
        self.assertEqual(billing["pricing_kind"], "per_second")
        self.assertIsNone(self.credits.billing_info("minimax-h3-t2v"))

    def test_disabled_rule_makes_job_free(self) -> None:
        self.store.update_credit_price_rules([{"rule_key": "cloud:cloud-kling-t2v", "enabled": False}])
        estimate = self.credits.estimate_job("cloud-kling-t2v", {"duration": 5, "kling_mode": "std"})
        self.assertEqual(estimate["credits"], 0)


class CreditBillingTests(unittest.TestCase):
    """预扣/退款/重试：余额原子性、终态退款与 settled 防重复。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")
        self.credits = CreditService(self.store)
        self.user_id = f"user-{_unique_id()}"
        self.store.adjust_credit(self.user_id, 1000, type="admin_recharge", reason="测试充值")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_billable_job(self, *, mode: str = "cloud-kling-t2v", options: dict | None = None, per_item: int = 200) -> tuple[str, str]:
        job_id = f"job-{_unique_id()}"
        self.store.create(
            job_id, mode, "一只猫在雪地里奔跑", "", None, [],
            options or {"duration": 5, "kling_mode": "std"},
            owner_user_id=self.user_id, credits_per_item=per_item,
        )
        item_id = self.store.get(job_id)["rounds"][-1]["generation_items"][0]["id"]
        return job_id, item_id

    def test_deduct_updates_balance_and_totals(self) -> None:
        result = self.store.deduct_credits(self.user_id, 200, price_key="cloud:cloud-kling-t2v", ref_type="job", ref_id="job-1")
        self.assertEqual(result["balance"], 800)
        account = self.store.get_or_create_credit_account(self.user_id)
        self.assertEqual(account["total_consumed"], 200)
        transactions = self.store.list_credit_transactions(user_id=self.user_id)
        self.assertEqual(transactions[0]["type"], "consume")
        self.assertEqual(transactions[0]["balance_after"], 800)

    def test_deduct_insufficient_is_atomic(self) -> None:
        with self.assertRaises(CreditInsufficientError) as ctx:
            self.store.deduct_credits(self.user_id, 2000)
        self.assertEqual(ctx.exception.balance, 1000)
        self.assertEqual(ctx.exception.required, 2000)
        account = self.store.get_or_create_credit_account(self.user_id)
        self.assertEqual(account["balance"], 1000)
        # 没有扣费流水写入
        types = [item["type"] for item in self.store.list_credit_transactions(user_id=self.user_id)]
        self.assertEqual(types, ["admin_recharge"])

    def test_failed_generation_item_refunds_once(self) -> None:
        job_id, item_id = self._create_billable_job()
        self.store.deduct_credits(self.user_id, 200, ref_type="job", ref_id=job_id)
        self.store.update_generation(item_id, status=JobStatus.FAILED, error="上游失败")
        account = self.store.get_or_create_credit_account(self.user_id)
        self.assertEqual(account["balance"], 1000)
        self.assertEqual(account["total_consumed"], 0)
        item = self.store.get(job_id)["rounds"][-1]["generation_items"][0]
        self.assertTrue(item["credits_settled"])
        # 再次置 FAILED 不得重复退款
        self.store.update_generation(item_id, status=JobStatus.FAILED, error="重复终态")
        account = self.store.get_or_create_credit_account(self.user_id)
        self.assertEqual(account["balance"], 1000)
        refunds = [item for item in self.store.list_credit_transactions(user_id=self.user_id) if item["type"] == "refund"]
        self.assertEqual(len(refunds), 1)

    def test_cancelled_generation_item_refunds(self) -> None:
        job_id, item_id = self._create_billable_job()
        self.store.deduct_credits(self.user_id, 200, ref_type="job", ref_id=job_id)
        self.store.update_generation(item_id, status=JobStatus.CANCELLED)
        account = self.store.get_or_create_credit_account(self.user_id)
        self.assertEqual(account["balance"], 1000)

    def test_succeeded_generation_item_keeps_deduction(self) -> None:
        job_id, item_id = self._create_billable_job()
        self.store.deduct_credits(self.user_id, 200, ref_type="job", ref_id=job_id)
        self.store.update_generation(item_id, status=JobStatus.SUCCEEDED, outputs=[{"kind": "video", "path": "a.mp4"}])
        account = self.store.get_or_create_credit_account(self.user_id)
        self.assertEqual(account["balance"], 800)
        self.assertEqual(account["total_consumed"], 200)

    def test_unbilled_local_job_never_refunds(self) -> None:
        job_id = f"job-{_unique_id()}"
        self.store.create(job_id, "minimax-h3-t2v", "本地任务", "", None, [], {"duration": 5}, owner_user_id=self.user_id)
        item_id = self.store.get(job_id)["rounds"][-1]["generation_items"][0]["id"]
        self.store.update_generation(item_id, status=JobStatus.FAILED, error="本地失败")
        account = self.store.get_or_create_credit_account(self.user_id)
        self.assertEqual(account["balance"], 1000)

    def test_retry_rebills_at_current_price(self) -> None:
        job_id, item_id = self._create_billable_job()
        self.store.deduct_credits(self.user_id, 200, ref_type="job", ref_id=job_id)
        self.store.update_generation(item_id, status=JobStatus.FAILED, error="失败")
        # 管理端调价后重试
        self.store.update_credit_price_rules([{"rule_key": "cloud:cloud-kling-t2v", "unit_by_variant": {"std": 60, "pro": 120}}])
        options = {"duration": 5, "kling_mode": "std"}
        quote = self.credits.quote_job({"id": self.user_id}, "cloud-kling-t2v", options)
        with ThreadPoolExecutor(max_workers=2) as pool:
            retries = [pool.submit(self.store.retry_failed_items, job_id, credit_quote=quote) for _ in range(2)]
            self.assertEqual(sorted(len(retry.result()) for retry in retries), [0, 1])
        account = self.store.get_or_create_credit_account(self.user_id)
        self.assertEqual(account["balance"], 700)
        item = self.store.get(job_id)["rounds"][-1]["generation_items"][0]
        self.assertEqual(item["credits_billed"], 300)
        self.assertFalse(item["credits_settled"])
        # 重试再次失败：按新价格退款
        self.store.update_generation(item_id, status=JobStatus.FAILED, error="再次失败")
        account = self.store.get_or_create_credit_account(self.user_id)
        self.assertEqual(account["balance"], 1000)

    def test_task_creation_and_precharge_roll_back_together(self) -> None:
        options = {"duration": 5, "kling_mode": "std"}
        quote = self.credits.quote_job(self.user_id, "cloud-kling-t2v", options)
        job_id = _unique_id()
        with self.store.connection() as connection:
            connection.execute("""CREATE TRIGGER fail_generation_item BEFORE INSERT ON generation_items
                BEGIN SELECT RAISE(ABORT, 'test insert failure'); END""")
        with self.assertRaisesRegex(Exception, "test insert failure"):
            self.store.create(job_id, "cloud-kling-t2v", "测试", "", None, [], options,
                              owner_user_id=self.user_id, credit_quote=quote)
        with self.assertRaises(KeyError):
            self.store.get(job_id)
        self.assertEqual(self.credits.account(self.user_id)["balance"], 1000)
        self.assertEqual(self.store.list_credit_transactions(ref_id=job_id), [])

    def test_bill_job_returns_per_item_for_multi_image(self) -> None:
        set_catalog_lookup(lambda key: {
            "workflow_id": key, "provider_model": "m", "display_name": "M", "description": "",
            "profile": "gpt_image_2", "credit_cost": 10,
        } if key == "grs-multi-test" else None)
        try:
            job_id = f"job-{_unique_id()}"
            billed = self.credits.bill_job(
                {"id": self.user_id}, "grs-multi-test",
                {"count": 3, "provider_model": "m"}, job_id=job_id,
            )
            self.assertEqual(billed["total"], 60)  # ceil(10×2.0)=20 × 3 张
            self.assertEqual(billed["per_item"], 20)
            account = self.store.get_or_create_credit_account(self.user_id)
            self.assertEqual(account["balance"], 940)
        finally:
            set_catalog_lookup(None)

    def test_consume_call_is_tolerant_for_all_roles(self) -> None:
        cost = self.credits.consume_call({"id": self.user_id}, "llm", "split_script")
        self.assertEqual(cost, 3)
        self.assertEqual(self.store.get_or_create_credit_account(self.user_id)["balance"], 997)
        # 无用户记录的历史 owner id 也正常按次扣费（不再按角色豁免）。
        cost = self.credits.consume_call("unknown-owner", "llm", "split_script")
        self.assertEqual(cost, 3)

    def test_super_admin_is_billed_like_regular_user(self) -> None:
        admin = {"id": "root-bill", "role": UserRole.SUPER_ADMIN.value}
        self.store.adjust_credit(admin["id"], 300, type="admin_recharge", reason="测试充值")
        options = {"duration": 5, "kling_mode": "std"}

        quote = self.credits.quote_job(admin, "cloud-kling-t2v", options)
        self.assertIsNotNone(quote)
        self.assertEqual(quote.total, 200)

        self.assertEqual(self.credits.consume_call(admin, "llm", "split_script"), 3)
        billed = self.credits.bill_job(admin, "cloud-kling-t2v", options, job_id=f"job-{_unique_id()}")
        self.assertEqual(billed["total"], 200)
        self.assertEqual(self.store.get_or_create_credit_account(admin["id"])["balance"], 97)

    def test_adjust_recharge_and_negative(self) -> None:
        account = self.credits.adjust(self.user_id, 500, reason="活动赠送", actor_user_id="admin-1")
        self.assertEqual(account["balance"], 1500)
        self.assertEqual(account["total_recharged"], 1500)
        account = self.credits.adjust(self.user_id, -200, reason="纠错扣回", actor_user_id="admin-1")
        self.assertEqual(account["balance"], 1300)
        self.assertEqual(account["total_recharged"], 1500)  # 负调整不动累计充值
        with self.assertRaises(ValueError):
            self.credits.adjust(self.user_id, 0, reason="无意义")


class CreditEndpointTests(unittest.TestCase):
    """端点：用户余额/流水/预估 + 管理端充值与价格表。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")
        self.auth_store = AuthStore(Path(self.temp_dir.name) / "test.db")
        self._app_state = snapshot_app_state(app)
        app.state.store = self.store
        app.state.credits = CreditService(self.store)
        app.state.auth_store = self.auth_store
        self.super_admin = self.auth_store.create_user(
            "root", "超管", "password123456", UserRole.SUPER_ADMIN, must_change_password=False,
        )
        self.admin = self.auth_store.create_user(
            "manager", "管理员", "password123456", UserRole.ADMIN, must_change_password=False,
        )
        self.employee = self.auth_store.create_user(
            "worker", "员工", "password123456", UserRole.EMPLOYEE, must_change_password=False,
        )
        self.employee_token, _ = self.auth_store.create_session(self.employee["id"])
        self.admin_token, _ = self.auth_store.create_session(self.admin["id"])
        self.super_admin_token, _ = self.auth_store.create_session(self.super_admin["id"])
        self.credits = CreditService(self.store)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        restore_app_state(app, self._app_state)
        set_catalog_lookup(None)
        self.temp_dir.cleanup()

    def login_as(self, token: str) -> None:
        self.client.cookies.set(SESSION_COOKIE, token)

    def test_my_account_and_transactions(self) -> None:
        self.login_as(self.admin_token)
        res = self.client.post(
            "/api/admin/credits/adjust", json={"user_id": self.employee["id"], "delta": 100, "reason": "开通赠送"},
            headers={"X-CSRF-Token": csrf_token(self.admin_token)},
        )
        self.assertEqual(res.status_code, 200)
        self.login_as(self.employee_token)
        res = self.client.get("/api/credits/me")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["balance"], 100)
        res = self.client.get("/api/credits/transactions")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()[0]["type"], "admin_recharge")

    def test_estimate_endpoint(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.post("/api/credits/estimate", json={"mode": "cloud-kling-t2v", "options": {"duration": 5, "kling_mode": "std"}})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["credits"], 200)
        self.assertFalse(body["sufficient"])
        self.assertIn("云端视频 5 秒", body["breakdown"])

    def test_modes_exposes_resolved_cloud_billing_and_option_labels(self) -> None:
        """/api/modes：云端视频返回实际扣费分档与摘要，分辨率选项带动态积分标注。"""
        self.login_as(self.employee_token)
        res = self.client.get("/api/modes")
        self.assertEqual(res.status_code, 200)
        modes = {item["id"]: item for item in res.json()["modes"]}
        grs = modes["cloud-grs-h3-t2v"]
        self.assertEqual(grs["billing"]["summary"], "5-15 积分/秒")
        self.assertEqual(grs["billing"]["native_variant_prices"]["768p"], 0.07)
        self.assertEqual(grs["billing"]["resolved_unit_by_variant"]["768p"], 7)
        options = next(item for item in grs["parameters"] if item["name"] == "options")
        labels = {
            item["value"]: item["label"]
            for item in options["schema"]["properties"]["resolution"]["ui_options"]
        }
        self.assertEqual(labels["768p"], "768p · 7 积分/秒")

        minimax = modes["cloud-minimax-h3-t2v"]
        self.assertEqual(minimax["billing"]["summary"], "16-80 积分/秒")
        minimax_options = next(item for item in minimax["parameters"] if item["name"] == "options")
        minimax_model_labels = {
            item["value"]: item["label"]
            for item in minimax_options["schema"]["properties"]["model"]["ui_options"]
        }
        self.assertIn("16-26 积分/秒", minimax_model_labels["MiniMax-H3-Lite"])

    def test_estimate_endpoint_includes_input_image_fee(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.post("/api/credits/estimate", json={
            "mode": "cloud-minimax-h3-r2v",
            "options": {"duration": 5, "model": "MiniMax-H3-Lite", "resolution": "768P"},
            "reference_count": 7,
        })
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["credits"], 156)
        self.assertEqual(body["input_image_credits"], 26)
        self.assertEqual(body["input_image_count"], 2)
        self.assertEqual(body["input_image_unit_credits"], 13)
        self.assertIn("参考图超出免费额度", body["breakdown"])

    def test_estimate_endpoint_within_free_image_quota(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.post("/api/credits/estimate", json={
            "mode": "cloud-minimax-h3-r2v",
            "options": {"duration": 5, "model": "MiniMax-H3-Lite", "resolution": "768P"},
            "reference_count": 5,
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["credits"], 130)
        self.assertEqual(res.json()["input_image_credits"], 0)

    def test_pricing_catalog_endpoint(self) -> None:
        """价格页数据：档位结构来自注册表，单价来自价格表，只暴露 GRS（H3 / Agnes / Wan）与 MiniMax 官方。"""
        res = self.client.get("/api/pricing")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["credits_per_yuan"], 100)
        providers = {item["key"]: item for item in body["providers"]}
        self.assertEqual(set(providers), {"grs", "grs-agnes", "grs-wan", "minimax"})

        grs = providers["grs"]
        self.assertEqual(len(grs["models"]), 1)
        grs_model = grs["models"][0]
        self.assertEqual(grs_model["label"], "MiniMax-H3")
        self.assertEqual(
            [item["credits_per_second"] for item in grs_model["resolutions"]], [5, 7, 15],
        )
        self.assertEqual(grs_model["resolutions"][1]["credits_5s"], 35)
        self.assertEqual(grs_model["input_image_credits"], 0)
        self.assertEqual(grs["input_image_free_quota"], 5)
        self.assertEqual(len(grs["workflow_ids"]), 3)

        agnes = providers["grs-agnes"]
        self.assertEqual(len(agnes["models"]), 1)
        agnes_model = agnes["models"][0]
        self.assertEqual(agnes_model["key"], "agnes-video-2.5")
        self.assertEqual([item["value"] for item in agnes_model["resolutions"]], ["720p", "1080p", "2k"])
        self.assertEqual([item["credits_per_second"] for item in agnes_model["resolutions"]], [10, 17, 23])
        self.assertEqual(agnes_model["resolutions"][2]["native_price_per_second"], 0.23)
        self.assertEqual(len(agnes["workflow_ids"]), 4)
        self.assertEqual(len(agnes["modes"]), 4)

        wan = providers["grs-wan"]
        self.assertEqual(len(wan["models"]), 1)
        wan_model = wan["models"][0]
        self.assertEqual(wan_model["key"], "wan-3.0")
        self.assertEqual([item["value"] for item in wan_model["resolutions"]], ["480p", "720p", "1080p"])
        # 2700/5400/10800 上游积分每秒（¥0.135/0.27/0.54）×100 后向上取整
        self.assertEqual([item["credits_per_second"] for item in wan_model["resolutions"]], [14, 27, 54])
        self.assertEqual(wan_model["resolutions"][0]["native_price_per_second"], 0.135)
        self.assertEqual(wan_model["input_image_credits"], 0)
        self.assertEqual(len(wan["workflow_ids"]), 4)
        self.assertEqual(len(wan["modes"]), 4)

        minimax = providers["minimax"]
        self.assertEqual([model["key"] for model in minimax["models"]], [
            "MiniMax-H3-Lite", "MiniMax-H3-Highspeed", "MiniMax-H3", "MiniMax-H3-Max",
        ])
        lite = minimax["models"][0]
        self.assertEqual([item["value"] for item in lite["resolutions"]], ["480P", "768P"])
        self.assertEqual(lite["input_image_credits"], 13)
        h3 = next(model for model in minimax["models"] if model["key"] == "MiniMax-H3")
        self.assertEqual([item["value"] for item in h3["resolutions"]], ["768P", "2K"])
        self.assertEqual(h3["input_image_credits"], 20)
        self.assertEqual(h3["resolutions"][1]["credits_per_second"], 80)
        self.assertEqual(len(minimax["workflow_ids"]), 4)

    def test_pricing_catalog_includes_image_and_ai_call_prices(self) -> None:
        """价格页新增生图与 AI 大模型价格：条目来自目录/价格表，单价与实际扣费口径一致。"""
        # 端点读取 app.state.grs_provider；测试类替换了 store，必须同步换成临时库的实例。
        app.state.grs_provider = GrsProviderService(self.store, Fernet.generate_key().decode())
        res = self.client.get("/api/pricing")
        self.assertEqual(res.status_code, 200)
        body = res.json()

        image = body["image_generation"]
        self.assertEqual(image["pricing_kind"], "per_item")
        self.assertTrue(image["models"], "生图目录应有种子模型")
        for item in image["models"]:
            self.assertTrue(item["key"])
            self.assertTrue(item["label"])
            self.assertIsInstance(item["credits_per_image"], int)
            record = self.store.get_grs_image_model(item["key"])
            self.assertIsNotNone(record)
            self.assertEqual(
                item["credits_per_image"],
                self.credits.grs_image_unit_price(item["key"], record.get("provider_model")),
            )
        self.assertTrue(any(item["is_default"] for item in image["models"]))
        # 只下发生效模型（停用模型不得出现在价格页）。
        disabled = {
            row["workflow_id"] for row in self.store.list_grs_image_models() if not row["enabled"]
        }
        self.assertFalse(disabled & {item["key"] for item in image["models"]})

        ai = body["ai_calls"]["items"]
        self.assertTrue(ai)
        first = ai[0]
        self.assertEqual(first["key"], "llm:optimize_prompt")
        self.assertEqual(first["label"], "提示词优化")
        self.assertEqual(first["billing_mode"], "per_call")
        self.assertEqual(first["unit_credits"], 1)
        for item in ai:
            self.assertIn(item["scope"], {"llm", "vlm"})
            self.assertIn(item["billing_mode"], {"per_call", "per_token"})
            self.assertEqual(item["unit_credits"], self.credits.estimate_call(item["scope"], item["kind"]))
        self.assertEqual({item["scope"] for item in ai}, {"llm", "vlm"})

    def test_admin_price_table_exposes_resolved_units(self) -> None:
        self.login_as(self.admin_token)
        res = self.client.get("/api/admin/credits/prices")
        self.assertEqual(res.status_code, 200)
        rules = {item["rule_key"]: item for item in res.json()}
        self.assertEqual(rules["cloud:cloud-grs-h3-t2v"]["resolved_unit_by_variant"]["768p"], 7)
        self.assertEqual(rules["cloud:cloud-minimax-h3-t2v"]["resolved_unit_by_variant"]["MiniMax-H3:2K"], 80)

    def test_admin_adjust_requires_admin_role(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.post(
            "/api/admin/credits/adjust", json={"user_id": self.employee["id"], "delta": 100, "reason": "自助充值"},
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 403)

    def test_admin_adjust_updates_balance_and_audits(self) -> None:
        self.login_as(self.admin_token)
        res = self.client.post(
            "/api/admin/credits/adjust", json={"user_id": self.employee["id"], "delta": 500, "reason": "内部测试充值"},
            headers={"X-CSRF-Token": csrf_token(self.admin_token)},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["balance"], 500)
        res = self.client.post(
            "/api/admin/credits/adjust", json={"user_id": self.employee["id"], "delta": 0, "reason": "非法"},
            headers={"X-CSRF-Token": csrf_token(self.admin_token)},
        )
        self.assertEqual(res.status_code, 422)
        with self.auth_store.connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM audit_logs WHERE action = 'adjust_credit'",
            ).fetchone()
        self.assertGreaterEqual(int(row["total"]), 1)

    def test_admin_account_search_includes_users_without_a_wallet(self) -> None:
        self.login_as(self.admin_token)
        result = self.client.get("/api/admin/credits/accounts", params={"query": "worker"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual([(row["user_id"], row["balance"]) for row in result.json()], [(self.employee["id"], 0)])
        first = self.client.get("/api/admin/credits/accounts", params={"limit": 1}).json()
        second = self.client.get("/api/admin/credits/accounts", params={"limit": 1, "offset": 1}).json()
        self.assertNotEqual(first[0]["user_id"], second[0]["user_id"])
        with self.store.connection() as connection:
            self.assertIsNone(connection.execute("SELECT user_id FROM credit_accounts WHERE user_id = ?", (self.employee["id"],)).fetchone())

    def test_admin_adjust_replay_and_invalid_adjustments(self) -> None:
        self.login_as(self.admin_token)
        headers = {"X-CSRF-Token": csrf_token(self.admin_token)}
        path = "/api/admin/credits/adjust"
        body = {"user_id": self.employee["id"], "delta": 25, "reason": "手动充值", "request_id": "adjust-once"}
        self.assertEqual(self.client.post(path, json=body, headers=headers).status_code, 200)
        self.assertEqual(self.client.post(path, json=body, headers=headers).json()["balance"], 25)
        self.assertEqual(self.client.post(path, json={**body, "delta": 30}, headers=headers).status_code, 409)
        for changes, status in (({"delta": -26}, 422), ({"delta": 1.5}, 422), ({"reason": "  "}, 422), ({"user_id": "missing"}, 404)):
            result = self.client.post(path, json={**body, "request_id": "another", **changes}, headers=headers)
            self.assertEqual(result.status_code, status)
        rows = self.client.get("/api/admin/credits/transactions", params={"query": "worker", "scope": "all"}).json()
        self.assertEqual([(row["delta"], row["actor_username"]) for row in rows], [(25, "manager")])

    def test_admin_prices_roundtrip(self) -> None:
        self.login_as(self.admin_token)
        res = self.client.get("/api/admin/credits/prices")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(any(rule["rule_key"] == "cloud:cloud-kling-t2v" for rule in res.json()))
        # LLM 条目返回成本预览：单次成本、覆盖率与建议积分随价格表下发给管理端。
        assistant = next(rule for rule in res.json() if rule["rule_key"] == "llm:assistant_chat")
        self.assertIsNotNone(assistant.get("cost_preview"))
        self.assertAlmostEqual(assistant["cost_preview"]["cost_cny"], 0.0092, places=6)
        res = self.client.put(
            "/api/admin/credits/prices",
            json={"rules": [{"rule_key": "cloud:cloud-kling-t2v", "unit_by_variant": {"std": 50, "pro": 90}}]},
            headers={"X-CSRF-Token": csrf_token(self.admin_token)},
        )
        self.assertEqual(res.status_code, 200)
        estimate = self.credits.estimate_job("cloud-kling-t2v", {"duration": 5, "kling_mode": "std"})
        self.assertEqual(estimate["credits"], 250)
        unknown = self.client.put(
            "/api/admin/credits/prices",
            json={"rules": [{"rule_key": "cloud:not-exists", "unit_credits": 1}]},
            headers={"X-CSRF-Token": csrf_token(self.admin_token)},
        )
        self.assertEqual(unknown.status_code, 422)

    def test_admin_price_validation_and_optimistic_update(self) -> None:
        self.login_as(self.admin_token)
        headers = {"X-CSRF-Token": csrf_token(self.admin_token)}
        path = "/api/admin/credits/prices"
        initial = {row["rule_key"]: row for row in self.client.get(path).json()}
        values = {"rule_key": "grs_image:global", "expected_updated_at": initial["grs_image:global"]["updated_at"]}
        for invalid in ({"grs_credits_to_platform": -1}, {"model_overrides": {"model": 2.5}}, {"input_image_price": 2}):
            self.assertEqual(self.client.put(path, json={"rules": [{**values, "extra_config": invalid}]}, headers=headers).status_code, 422)
        config = {**initial["grs_image:global"]["extra_config"], "grs_credits_to_platform": 3.5}
        result = self.client.put(path, json={"rules": [{**values, "extra_config": config}]}, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        key = "llm:assistant_chat"
        another = {"rule_key": key, "unit_credits": initial[key]["unit_credits"] + 4}
        result = self.client.put(path, json={"rules": [another, {**values, "enabled": False}]}, headers=headers)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.store.get_credit_price_rule(key)["unit_credits"], initial[key]["unit_credits"])
        self.assertEqual(self.store.get_credit_price_rule("grs_image:global")["extra_config"], config)

    def test_super_admin_billed_like_regular_user(self) -> None:
        self.login_as(self.super_admin_token)
        res = self.client.post("/api/credits/estimate", json={"mode": "cloud-kling-t2v", "options": {"duration": 5, "kling_mode": "std"}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["credits"], 200)
        self.store.adjust_credit(self.super_admin["id"], 500, type="admin_recharge", reason="测试充值")
        billed = self.credits.bill_job(
            {"id": self.super_admin["id"], "role": self.super_admin["role"]},
            "cloud-kling-t2v", {"duration": 5, "kling_mode": "std"}, job_id="job-x",
        )
        self.assertEqual(billed["total"], 200)
        self.assertEqual(billed["per_item"], 200)
        self.assertEqual(self.store.get_or_create_credit_account(self.super_admin["id"])["balance"], 300)


    def test_admin_usage_profit_report_groups_and_totals(self) -> None:
        user_id = self.employee["id"]
        self.store.adjust_credit(user_id, 1000, type="admin_recharge", reason="报表测试")
        self.store.adjust_credit(
            user_id, -300, type="consume", price_key="llm:assistant_chat", reason="助手",
            meta={
                "cost_cny": 1.5, "cost_basis": "actual", "billing_basis": "actual_tokens",
                "model": "deepseek-v4-flash", "prompt_tokens": 800, "completion_tokens": 200,
                "total_tokens": 1000,
            },
        )
        self.store.adjust_credit(
            user_id, -200, type="consume", price_key="cloud:cloud-kling-t2v", reason="视频", meta={},
        )
        self.store.adjust_credit(
            user_id, 50, type="refund", price_key="llm:assistant_chat", reason="失败退款",
        )
        self.login_as(self.admin_token)
        result = self.client.get(
            "/api/admin/credits/usage-report", params={"group_by": "price_key", "scope": "all"},
        )
        self.assertEqual(result.status_code, 200)
        body = result.json()
        totals = body["totals"]
        self.assertEqual(totals["calls"], 2)
        self.assertEqual(totals["credits"], 500)
        self.assertEqual(totals["refunds"], 1)
        self.assertEqual(totals["refunded_credits"], 50)
        self.assertEqual(totals["net_credits"], 450)
        self.assertAlmostEqual(totals["cost_cny"], 1.5, places=6)
        self.assertEqual(totals["costed_calls"], 1)
        self.assertEqual(totals["uncosted_calls"], 1)
        self.assertEqual(totals["token_calls"], 1)
        self.assertEqual(totals["tokens"], 1000)
        self.assertAlmostEqual(totals["margin_cny"], 3.0, places=6)
        self.assertAlmostEqual(totals["margin_rate"], 2 / 3, places=5)
        self.assertTrue(body["refunds_grouped"])
        rows = {row["key"]: row for row in body["rows"]}
        self.assertEqual(rows["llm:assistant_chat"]["refunded_credits"], 50)
        self.assertEqual(rows["llm:assistant_chat"]["net_credits"], 250)
        self.assertEqual(rows["cloud:cloud-kling-t2v"]["uncosted_calls"], 1)
        model_report = self.client.get(
            "/api/admin/credits/usage-report", params={"group_by": "model", "scope": "all"},
        ).json()
        self.assertFalse(model_report["refunds_grouped"])
        self.assertIn("deepseek-v4-flash", {row["key"] for row in model_report["rows"]})
        invalid = self.client.get(
            "/api/admin/credits/usage-report", params={"start": "2026-11-20", "end": "2026-11-01"},
        )
        self.assertEqual(invalid.status_code, 422)

    def test_provider_price_sync_writes_llm_rules(self) -> None:
        """拉取失败时回退内置官方价，按 1.5 系数换算并切 per_token。"""
        class _StubLlm:
            def public_config(self) -> dict:
                return {
                    "enabled": True,
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model": "deepseek-v4.1-flash-1017",
                }

            def api_key(self) -> str:
                return "test-key"

        app.state.llm_provider = _StubLlm()
        self.login_as(self.admin_token)
        with patch(
            "backend.app.main.fetch_upstream_prices",
            return_value=([], "供应商模型目录未返回 token 单价"),
        ):
            res = self.client.post(
                "/api/admin/credits/provider-prices/apply",
                json={"scope": "llm", "margin": 1.5, "min_credits": 1, "billing_mode": "per_token"},
                headers={"X-CSRF-Token": csrf_token(self.admin_token)},
            )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        applied = {item["rule_key"]: item for item in body["applied"]}
        self.assertEqual(applied["llm:assistant_chat"]["status"], "applied")
        self.assertEqual(applied["llm:assistant_chat"]["source"], "builtin")
        rule = self.store.get_credit_price_rule("llm:assistant_chat")
        self.assertEqual(rule["extra_config"]["billing_mode"], "per_token")
        self.assertEqual(rule["extra_config"]["billing_margin"], 1.5)
        self.assertEqual(
            rule["extra_config"]["cost_reference"]["model_prices"]["deepseek-v4.1-flash-1017"]["output_per_mtok"],
            8.0,
        )
        self.assertIn(rule["unit_credits"], (2, 3))
        # 价格页数据随新规则变化：llm:assistant_chat 按典型 tokens 显示为 2-3 积分。
        pricing = self.client.get("/api/pricing").json()
        assistant = next(item for item in pricing["ai_calls"]["items"] if item["key"] == "llm:assistant_chat")
        self.assertEqual(assistant["billing_mode"], "per_token")
        self.assertIn(assistant["unit_credits"], (2, 3))
        self.assertEqual(assistant["input_per_mtok"], 2.0)
        self.assertEqual(assistant["billing_margin"], 1.5)
        self.assertEqual(assistant["price_source"], "provider_catalog")

    def test_provider_price_sync_skips_free_vlm_model(self) -> None:
        """官方免费视觉模型不能被改成按 token 最低积分扣费。"""
        class _StubVlm:
            def public_config(self) -> dict:
                return {
                    "enabled": True,
                    "base_url": "https://api.qnaigc.com/v1",
                    "model": "qiniu/conatus-free",
                }

            def api_key(self) -> str:
                return "test-key"

        app.state.vlm_provider = _StubVlm()
        before = self.store.get_credit_price_rule("vlm:analyze_subject")
        self.login_as(self.admin_token)
        with patch(
            "backend.app.main.fetch_upstream_prices",
            return_value=([], "供应商模型目录未返回 token 单价"),
        ):
            res = self.client.post(
                "/api/admin/credits/provider-prices/apply",
                json={"scope": "vlm", "margin": 1.5, "min_credits": 1, "billing_mode": "per_token"},
                headers={"X-CSRF-Token": csrf_token(self.admin_token)},
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(all(item["status"] == "skipped" for item in res.json()["applied"]))
        after = self.store.get_credit_price_rule("vlm:analyze_subject")
        self.assertEqual(after["unit_credits"], before["unit_credits"])
        self.assertNotEqual(after["extra_config"]["billing_mode"], "per_token")


class CallCostReferenceTests(unittest.TestCase):
    """LLM/VLM 成本参考：种子口径、覆盖率、流水用量与校验。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")
        self.credits = CreditService(self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_seed_reference_and_preview(self) -> None:
        rules = {rule["rule_key"]: rule for rule in self.store.list_credit_price_rules()}
        assistant = rules["llm:assistant_chat"]
        preview = compute_cost_preview(assistant)
        self.assertIsNotNone(preview)
        # 6,000 输入 @¥1/M + 800 输出 @¥4/M = ¥0.0092；1 积分 = ¥0.01。
        self.assertAlmostEqual(preview["cost_cny"], 0.0092, places=6)
        self.assertAlmostEqual(preview["coverage"], 1.087, places=3)
        self.assertEqual(preview["status"], "thin")
        plan = compute_cost_preview(rules["llm:director_plan"])
        self.assertAlmostEqual(plan["cost_cny"], 0.24, places=6)
        self.assertAlmostEqual(plan["coverage"], 1.25, places=3)
        self.assertEqual(plan["status"], "healthy")
        self.assertEqual(plan["suggested_unit_credits"], 24)

    def test_consume_call_records_actual_usage_meta(self) -> None:
        user_id = "credit-user"
        self.store.adjust_credit(user_id, 100, type="admin_adjust", reason="测试充值")
        spent = self.credits.consume_call(
            user_id, "llm", "assistant_chat",
            usage={"prompt_tokens": 6000, "completion_tokens": 800, "total_tokens": 6800, "cached_tokens": 0},
            model="deepseek-v4-flash",
        )
        self.assertEqual(spent, 1)
        row = self.store.list_credit_transactions(user_id=user_id, type="consume")[0]
        meta = row["meta"]
        self.assertEqual(meta["prompt_tokens"], 6000)
        self.assertEqual(meta["completion_tokens"], 800)
        self.assertEqual(meta["model"], "deepseek-v4-flash")
        self.assertEqual(meta["cost_basis"], "actual")
        self.assertAlmostEqual(meta["cost_cny"], 0.0092, places=6)

    def test_consume_call_marks_estimated_without_usage(self) -> None:
        user_id = "credit-user-2"
        self.store.adjust_credit(user_id, 100, type="admin_adjust", reason="测试充值")
        self.credits.consume_call(user_id, "llm", "director_plan")
        row = self.store.list_credit_transactions(user_id=user_id, type="consume")[0]
        self.assertEqual(row["meta"]["cost_basis"], "estimated")
        self.assertEqual(row["meta"]["prompt_tokens"], 120000)
        self.assertAlmostEqual(row["meta"]["cost_cny"], 0.24, places=6)

    def test_legacy_rows_backfilled_once(self) -> None:
        with self.store.connection() as connection:
            connection.execute(
                "UPDATE credit_price_rules SET extra_config = NULL WHERE rule_key = 'llm:assistant_chat'",
            )
        self.store.initialize()
        rule = self.store.get_credit_price_rule("llm:assistant_chat")
        self.assertIn("cost_reference", rule["extra_config"])
        # 管理端清空后不再覆盖：保存空对象即视为已配置。
        self.store.update_credit_price_rules([{"rule_key": "llm:assistant_chat", "extra_config": {}}])
        self.store.initialize()
        self.assertEqual(self.store.get_credit_price_rule("llm:assistant_chat")["extra_config"], {})

    def test_cost_reference_validation(self) -> None:
        base = {
            "input_per_mtok": 1, "cached_input_per_mtok": 0.02, "output_per_mtok": 4,
            "assumed_input_tokens": 6000, "assumed_cached_tokens": 0, "assumed_output_tokens": 800,
            "provider_coefficient": 1,
        }
        CreditPriceRuleUpdateItem(
            rule_key="llm:assistant_chat", extra_config={"cost_reference": base},
        ).validate_pricing_config()
        CreditPriceRuleUpdateItem(
            rule_key="llm:assistant_chat",
            extra_config={
                "billing_mode": "per_token", "billing_margin": 1.2, "min_credits": 2,
                "cost_reference": {
                    **base,
                    "model_prices": {"deepseek-v4-flash": {"input_per_mtok": 0.5, "output_per_mtok": 2}},
                    "off_peak": {
                        "enabled": True, "discount": 0.5, "timezone": "Asia/Shanghai",
                        "windows": [{"start": "00:30", "end": "08:30"}],
                    },
                },
            },
        ).validate_pricing_config()
        invalid = [
            {**base, "input_per_mtok": -1},
            {**base, "assumed_input_tokens": 1.5},
            {**base, "assumed_cached_tokens": 7000},
            {**base, "input_per_mtok": 0, "output_per_mtok": 0},
            {**base, "estimated": "yes"},
            {**base, "model_prices": {"m": {"input_per_mtok": -1}}},
            {**base, "off_peak": {"enabled": "yes"}},
            {**base, "off_peak": {"enabled": True, "discount": 1.5}},
            {**base, "off_peak": {"enabled": True, "windows": [{"start": ""}]}},
        ]
        for config in invalid:
            with self.assertRaises(ValueError):
                CreditPriceRuleUpdateItem(
                    rule_key="llm:assistant_chat", extra_config={"cost_reference": config},
                ).validate_pricing_config()
        for config in ({"billing_mode": "per_hour"}, {"billing_margin": 0}, {"min_credits": 1.5}):
            with self.assertRaises(ValueError):
                CreditPriceRuleUpdateItem(
                    rule_key="llm:assistant_chat", extra_config={"cost_reference": base, **config},
                ).validate_pricing_config()

    def _set_assistant_pricing(self, *, reference_overrides: dict | None = None, **extra: object) -> None:
        self.store.update_credit_price_rules([{
            "rule_key": "llm:assistant_chat",
            "unit_credits": 7,
            "enabled": True,
            "extra_config": {
                "billing_mode": "per_token",
                "billing_margin": 1,
                "min_credits": 1,
                "cost_reference": {
                    "input_per_mtok": 1, "cached_input_per_mtok": 0.02, "output_per_mtok": 4,
                    "assumed_input_tokens": 6000, "assumed_cached_tokens": 0,
                    "assumed_output_tokens": 800, "provider_coefficient": 1,
                    "model_prices": {},
                    "off_peak": {"enabled": False, "discount": 0.5, "timezone": "Asia/Shanghai", "windows": []},
                    **(reference_overrides or {}),
                },
                **extra,
            },
        }])

    def test_per_token_settles_actual_usage(self) -> None:
        self.store.adjust_credit("token-user", 5000, type="admin_adjust", reason="测试充值")
        self._set_assistant_pricing(billing_margin=2, min_credits=10)
        usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "cached_tokens": 0}
        self.assertEqual(self.credits.estimate_call("llm", "assistant_chat"), 10)
        self.assertEqual(self.credits.consume_call("token-user", "llm", "assistant_chat", usage=usage), 1000)
        row = self.store.list_credit_transactions(user_id="token-user", type="consume")[0]
        self.assertEqual(row["balance_after"], 4000)
        self.assertEqual(row["meta"]["billing_basis"], "actual_tokens")
        self.assertEqual(row["meta"]["unit_credits"], 1000)
        self.assertAlmostEqual(row["meta"]["cost_cny"], 5.0, places=6)
        self.assertIn("按 token", row["reason"])

    def test_per_token_falls_back_to_unit_without_usage(self) -> None:
        self.store.adjust_credit("token-user-2", 100, type="admin_adjust", reason="测试充值")
        self._set_assistant_pricing()
        self.assertEqual(self.credits.consume_call("token-user-2", "llm", "assistant_chat"), 7)
        row = self.store.list_credit_transactions(user_id="token-user-2", type="consume")[0]
        self.assertEqual(row["meta"]["billing_basis"], "per_call")
        self.assertEqual(row["meta"]["cost_basis"], "estimated")

    def test_per_call_mode_is_unchanged_with_usage(self) -> None:
        self.store.adjust_credit("call-user", 100, type="admin_adjust", reason="测试充值")
        self._set_assistant_pricing(billing_mode="per_call")
        usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
        self.assertEqual(self.credits.consume_call("call-user", "llm", "assistant_chat", usage=usage), 7)

    def test_per_token_uses_model_tier_and_off_peak(self) -> None:
        from datetime import datetime, timezone
        from backend.app.credit_service import off_peak_multiplier, token_charge

        self._set_assistant_pricing(
            reference_overrides={
                "model_prices": {"deepseek-v4-flash": {"input_per_mtok": 10, "output_per_mtok": 40}},
                "off_peak": {
                    "enabled": True, "discount": 0.5, "timezone": "Asia/Shanghai",
                    "windows": [{"start": "00:30", "end": "08:30"}],
                },
            },
        )
        rule = self.store.get_credit_price_rule("llm:assistant_chat")
        usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
        # 北京 04:00（UTC 20:00）命中错峰 5 折：10+40=50 元 -> 25 元 -> 2500 积分。
        night = datetime(2024, 1, 1, 20, 0, tzinfo=timezone.utc)
        self.assertEqual(off_peak_multiplier(rule["extra_config"]["cost_reference"], night), 0.5)
        charged = token_charge(rule, usage, model="deepseek-v4-flash", at=night)
        self.assertEqual(charged["credits"], 2500)
        self.assertTrue(charged["model_tier"])
        self.assertTrue(charged["off_peak_applied"])
        # 未命中时段与未命中模型档位回到基础价。
        day = datetime(2024, 1, 1, 4, 0, tzinfo=timezone.utc)
        self.assertEqual(off_peak_multiplier(rule["extra_config"]["cost_reference"], day), 1.0)
        self.assertFalse(token_charge(rule, usage, model="other-model", at=day)["model_tier"])

    def test_per_token_minimum_credits(self) -> None:
        self._set_assistant_pricing(min_credits=300)
        rule = self.store.get_credit_price_rule("llm:assistant_chat")
        from backend.app.credit_service import token_charge

        self.assertEqual(token_charge(rule, {"prompt_tokens": 1, "completion_tokens": 1})["credits"], 300)


class ProviderPriceCatalogTests(unittest.TestCase):
    """供应商价目：内置官方价匹配、上游 USD 折算、同步写入模型档位。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "test.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_builtin_matches_dated_model_and_converts(self) -> None:
        from backend.app.llm_price_catalog import price_to_credits, resolve_price

        price = resolve_price("dashscope", "deepseek-v4.1-flash-1017")
        self.assertIsNotNone(price)
        self.assertEqual(price["source"], "builtin")
        self.assertEqual((price["input_per_mtok"], price["cached_input_per_mtok"], price["output_per_mtok"]),
                         (2.0, 0.04, 8.0))
        # 100 积分 = 1 元：¥2/M × 100 × 1.5 = 300 积分/M。
        self.assertEqual(price_to_credits(price, 1.5), {
            "input_credits_per_mtok": 300,
            "cached_input_credits_per_mtok": 6,
            "output_credits_per_mtok": 1200,
        })
        self.assertIsNone(resolve_price("dashscope", "unknown-model"))
        self.assertEqual(resolve_price("zhipu", "glm-5.3")["output_per_mtok"], 28.0)
        self.assertTrue(resolve_price("qiniu", "qiniu/conatus-free")["free"])

    def test_upstream_usd_pricing_is_converted_to_cny_per_mtok(self) -> None:
        from backend.app.llm_price_catalog import parse_upstream_prices

        payload = {"data": [{
            "id": "openai/gpt-x",
            "pricing": {"prompt": "0.000001", "completion": "0.000002", "input_cache_read": "0.0000005"},
        }]}
        entries = parse_upstream_prices(payload, base_url="https://openrouter.ai/api/v1", usd_cny=7.0)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "upstream")
        self.assertEqual(entries[0]["input_per_mtok"], 7.0)
        self.assertEqual(entries[0]["output_per_mtok"], 14.0)
        self.assertEqual(entries[0]["cached_input_per_mtok"], 3.5)

    def test_plan_rule_sync_writes_tier_margin_and_off_peak(self) -> None:
        from backend.app.llm_price_catalog import plan_rule_sync, resolve_price

        price = resolve_price("dashscope", "deepseek-v4.1-flash-1017")
        rule = self.store.get_credit_price_rule("llm:assistant_chat")
        plan = plan_rule_sync(
            rule, price, model="deepseek-v4.1-flash-1017", margin=1.5,
            min_credits=1, billing_mode="per_token",
        )
        self.assertEqual(plan["extra_config"]["billing_mode"], "per_token")
        self.assertEqual(plan["extra_config"]["billing_margin"], 1.5)
        reference = plan["extra_config"]["cost_reference"]
        self.assertEqual(reference["model_prices"]["deepseek-v4.1-flash-1017"]["input_per_mtok"], 2.0)
        self.assertEqual(reference["reference_source"], "provider_catalog")
        self.assertTrue(reference["off_peak"]["enabled"])
        # 6,000 输入 + 800 输出：峰值 ¥0.0184，×100×1.5 ≈ 2.76 → 3 积分；
        # 若当前正好落在错峰窗，半价后为 2 积分。
        self.assertIn(plan["unit_credits"], (2, 3))

    def test_unknown_provider_model_never_invents_price(self) -> None:
        from backend.app.llm_price_catalog import resolve_price

        self.assertIsNone(resolve_price("custom", "totally-unknown-model"))


if __name__ == "__main__":
    unittest.main()
