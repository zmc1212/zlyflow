from __future__ import annotations

import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from backend.app.auth import AuthStore, csrf_token
from backend.app.credit_service import CreditService
from backend.app.enterprise_service import (
    EnterpriseModelForbiddenError,
    ensure_call_allowed,
    ensure_mode_allowed,
    filter_workflow_definitions,
    mode_allowed,
)
from backend.app.main import SESSION_COOKIE, app
from backend.app.models import JobStatus, UserRole
from backend.app.storage import CreditInsufficientError, JobStore
from backend.app.workflow_registry import WORKFLOWS, set_catalog_lookup
from backend.tests.app_state_guard import restore_app_state, snapshot_app_state


def _unique_id() -> str:
    return uuid.uuid4().hex[:12]


class EnterpriseBase(unittest.TestCase):
    """共用环境：单库 SQLite（JobStore + AuthStore 同库，贴近生产 MySQL 单库）。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "shared.db"
        self.store = JobStore(db_path)
        self.auth_store = AuthStore(db_path)
        self.credits = CreditService(self.store)
        self._app_state = snapshot_app_state(app)
        app.state.store = self.store
        app.state.credits = self.credits
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
        self.admin_token, _ = self.auth_store.create_session(self.admin["id"])
        self.employee_token, _ = self.auth_store.create_session(self.employee["id"])
        self.client = TestClient(app)

    def tearDown(self) -> None:
        restore_app_state(app, self._app_state)
        set_catalog_lookup(None)
        self.temp_dir.cleanup()

    def login_as(self, token: str) -> None:
        self.client.cookies.set(SESSION_COOKIE, token)

    def admin_headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": csrf_token(self.admin_token)}

    def create_enterprise(self, *, name: str = "星河传媒", code: str | None = None) -> dict:
        self.login_as(self.admin_token)
        res = self.client.post(
            "/api/admin/enterprises",
            json={"name": name, "code": code or f"ent-{_unique_id()}"},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 201, res.text)
        return res.json()


class EnterpriseCrudTests(EnterpriseBase):
    """企业主档 CRUD 与编码唯一性。"""

    def test_create_list_update_detail(self) -> None:
        enterprise = self.create_enterprise(name="测试企业A")
        self.assertEqual(enterprise["name"], "测试企业A")
        self.assertEqual(enterprise["status"], "active")
        self.assertEqual(enterprise["balance"], 0)

        self.login_as(self.admin_token)
        res = self.client.get("/api/admin/enterprises", headers=self.admin_headers())
        self.assertEqual(res.status_code, 200)
        ids = [item["id"] for item in res.json()]
        self.assertIn(enterprise["id"], ids)

        res = self.client.get(f"/api/admin/enterprises/{enterprise['id']}", headers=self.admin_headers())
        self.assertEqual(res.status_code, 200)
        detail = res.json()
        self.assertEqual(detail["enterprise"]["id"], enterprise["id"])
        # 未配置策略时归一化为四类全部开放（默认不限制），catalog 含模型清单
        self.assertEqual(len(detail["policies"]), 4)
        self.assertTrue(all(item["mode"] == "all" for item in detail["policies"]))
        self.assertTrue(detail["catalog"]["video"])
        self.assertTrue(detail["catalog"]["image"])
        self.assertTrue(detail["catalog"]["llm"])

        res = self.client.patch(
            f"/api/admin/enterprises/{enterprise['id']}",
            json={"name": "测试企业A改", "contact_name": "李四", "status": "disabled"},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "测试企业A改")
        self.assertEqual(res.json()["contact_name"], "李四")
        self.assertEqual(res.json()["status"], "disabled")

    def test_duplicate_code_rejected(self) -> None:
        first = self.create_enterprise(code="CODE-001")
        self.login_as(self.admin_token)
        res = self.client.post(
            "/api/admin/enterprises", json={"name": "另一家", "code": "CODE-001"},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("编码已被使用", res.json()["detail"])
        self.assertTrue(first["code"])

    def test_employee_forbidden(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.get("/api/admin/enterprises", headers={"X-CSRF-Token": csrf_token(self.employee_token)})
        self.assertEqual(res.status_code, 403)

    def test_delete_empty_enterprise_and_guards(self) -> None:
        enterprise = self.create_enterprise(name="待删除企业")
        self.login_as(self.admin_token)
        # 有成员时禁止删除
        self.client.post(
            f"/api/admin/enterprises/{enterprise['id']}/members",
            json={"user_id": self.employee["id"]},
            headers=self.admin_headers(),
        )
        res = self.client.delete(f"/api/admin/enterprises/{enterprise['id']}", headers=self.admin_headers())
        self.assertEqual(res.status_code, 409)
        self.assertIn("仍有成员", res.json()["detail"])

        # 移出成员但有钱包流水时禁止删除
        self.client.delete(
            f"/api/admin/enterprises/{enterprise['id']}/members/{self.employee['id']}",
            headers=self.admin_headers(),
        )
        self.client.post(
            f"/api/admin/enterprises/{enterprise['id']}/credits",
            json={"delta": 100, "reason": "充值"},
            headers=self.admin_headers(),
        )
        res = self.client.delete(f"/api/admin/enterprises/{enterprise['id']}", headers=self.admin_headers())
        self.assertEqual(res.status_code, 409)

        # 空白企业可以删除
        fresh = self.create_enterprise(name="空白企业")
        res = self.client.delete(f"/api/admin/enterprises/{fresh['id']}", headers=self.admin_headers())
        self.assertEqual(res.status_code, 204)
        res = self.client.get(f"/api/admin/enterprises/{fresh['id']}", headers=self.admin_headers())
        self.assertEqual(res.status_code, 404)


class EnterpriseHierarchyTests(EnterpriseBase):
    """企业层级：集团-子公司树形归属、循环校验与删除保护。"""

    def test_create_child_and_list_parent(self) -> None:
        parent = self.create_enterprise(name="星河集团")
        self.login_as(self.admin_token)
        res = self.client.post(
            "/api/admin/enterprises",
            json={"name": "星河影业", "parent_id": parent["id"]},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 201, res.text)
        child = res.json()
        self.assertEqual(child["parent_id"], parent["id"])

        listed = self.client.get("/api/admin/enterprises", headers=self.admin_headers()).json()
        by_id = {item["id"]: item for item in listed}
        self.assertEqual(by_id[child["id"]]["parent_id"], parent["id"])
        self.assertIsNone(by_id[parent["id"]]["parent_id"])

    def test_unknown_parent_and_cycle_rejected(self) -> None:
        parent = self.create_enterprise(name="集团")
        self.login_as(self.admin_token)
        res = self.client.post(
            "/api/admin/enterprises",
            json={"name": "子公司", "parent_id": "ent-missing"},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("上级企业不存在", res.json()["detail"])

        child = self.client.post(
            "/api/admin/enterprises",
            json={"name": "子公司", "parent_id": parent["id"]},
            headers=self.admin_headers(),
        ).json()
        # 自己不能作为自己的上级
        res = self.client.patch(
            f"/api/admin/enterprises/{child['id']}",
            json={"parent_id": child["id"]},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 422)
        # 祖先不能挂到后代下面
        res = self.client.patch(
            f"/api/admin/enterprises/{parent['id']}",
            json={"parent_id": child["id"]},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("循环", res.json()["detail"])

    def test_reparent_and_clear_parent(self) -> None:
        group = self.create_enterprise(name="集团")
        self.login_as(self.admin_token)
        child = self.client.post(
            "/api/admin/enterprises",
            json={"name": "子公司", "parent_id": group["id"]},
            headers=self.admin_headers(),
        ).json()
        res = self.client.patch(
            f"/api/admin/enterprises/{child['id']}",
            json={"parent_id": None},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(res.json()["parent_id"])

    def test_delete_parent_with_children_rejected(self) -> None:
        parent = self.create_enterprise(name="待删集团")
        self.login_as(self.admin_token)
        self.client.post(
            "/api/admin/enterprises",
            json={"name": "下属公司", "parent_id": parent["id"]},
            headers=self.admin_headers(),
        )
        res = self.client.delete(f"/api/admin/enterprises/{parent['id']}", headers=self.admin_headers())
        self.assertEqual(res.status_code, 409)
        self.assertIn("下级企业", res.json()["detail"])


class EnterpriseMemberTests(EnterpriseBase):
    """成员归属：分配/移出账号与校验。"""

    def test_bind_and_unbind_member(self) -> None:
        enterprise = self.create_enterprise()
        self.login_as(self.admin_token)
        res = self.client.post(
            f"/api/admin/enterprises/{enterprise['id']}/members",
            json={"user_id": self.employee["id"]},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["enterprise_id"], enterprise["id"])
        self.assertEqual(res.json()["enterprise_name"], enterprise["name"])

        members = self.client.get(
            f"/api/admin/enterprises/{enterprise['id']}/members", headers=self.admin_headers(),
        ).json()
        self.assertEqual([item["id"] for item in members], [self.employee["id"]])
        self.assertEqual(members[0]["net_consumed"], 0)

        res = self.client.delete(
            f"/api/admin/enterprises/{enterprise['id']}/members/{self.employee['id']}",
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json()["enterprise_id"])

    def test_bind_rejects_disabled_enterprise_and_unknown_user(self) -> None:
        enterprise = self.create_enterprise()
        self.login_as(self.admin_token)
        res = self.client.post(
            f"/api/admin/enterprises/{enterprise['id']}/members",
            json={"user_id": "missing-user"},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 404)

        self.client.patch(
            f"/api/admin/enterprises/{enterprise['id']}", json={"status": "disabled"},
            headers=self.admin_headers(),
        )
        res = self.client.post(
            f"/api/admin/enterprises/{enterprise['id']}/members",
            json={"user_id": self.employee["id"]},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 409)


class EnterpriseWalletTests(EnterpriseBase):
    """企业钱包：充值、成员消费落企业钱包、退款回冲与成员用量统计。"""

    def setUp(self) -> None:
        super().setUp()
        self.enterprise = self.create_enterprise()
        self.login_as(self.admin_token)
        res = self.client.post(
            f"/api/admin/enterprises/{self.enterprise['id']}/members",
            json={"user_id": self.employee["id"]},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 201)

    def test_recharge_and_member_consumption_route_to_enterprise_wallet(self) -> None:
        # 企业充值 1000
        self.login_as(self.admin_token)
        res = self.client.post(
            f"/api/admin/enterprises/{self.enterprise['id']}/credits",
            json={"delta": 1000, "reason": "开户充值"},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["balance"], 1000)
        self.assertEqual(res.json()["total_recharged"], 1000)

        # 成员消费 200 → 落企业钱包，个人钱包保持为空且不建账
        self.store.deduct_credits(
            self.employee["id"], 200, price_key="cloud:cloud-kling-t2v",
            ref_type="job", ref_id="job-1", reason="云端视频 5 秒",
        )
        wallet = self.store.get_or_create_enterprise_credit_account(self.enterprise["id"])
        self.assertEqual(wallet["balance"], 800)
        self.assertEqual(wallet["total_consumed"], 200)
        personal = self.store.get_or_create_credit_account(self.employee["id"])
        self.assertEqual(personal["balance"], 0)
        self.assertEqual(personal["total_consumed"], 0)

        # 余额不足：企业钱包余额不足时预扣失败且不变更数据
        with self.assertRaises(CreditInsufficientError):
            self.store.deduct_credits(self.employee["id"], 5000)

        # 失败退款 → 回企业钱包
        self.store.refund_credits(
            self.employee["id"], 200, reason="任务失败退回", ref_type="job", ref_id="job-1",
        )
        wallet = self.store.get_or_create_enterprise_credit_account(self.enterprise["id"])
        self.assertEqual(wallet["balance"], 1000)
        self.assertEqual(wallet["total_consumed"], 0)

        # 成员用量统计：净消耗 0（消耗与退款相抵）
        usage = self.store.enterprise_member_usage(self.enterprise["id"])
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["user_id"], self.employee["id"])
        self.assertEqual(usage[0]["gross_consumed"], 200)
        self.assertEqual(usage[0]["refunded"], 200)
        self.assertEqual(usage[0]["net_consumed"], 0)

    def test_member_usage_stats_and_price_key_breakdown(self) -> None:
        self.store.adjust_enterprise_credit(self.enterprise["id"], 500, type="admin_recharge", reason="充值")
        self.store.deduct_credits(self.employee["id"], 100, price_key="llm:assistant_chat")
        self.store.deduct_credits(self.employee["id"], 150, price_key="cloud:cloud-grs-h3-t2v")
        usage = self.store.enterprise_member_usage(self.enterprise["id"])
        self.assertEqual(usage[0]["net_consumed"], 250)
        breakdown = {item["price_key"]: item["net_consumed"] for item in self.store.enterprise_usage_by_price_key(self.enterprise["id"])}
        self.assertEqual(breakdown.get("llm:assistant_chat"), 100)
        self.assertEqual(breakdown.get("cloud:cloud-grs-h3-t2v"), 150)

    def test_unbind_restores_personal_wallet_billing(self) -> None:
        self.store.adjust_enterprise_credit(self.enterprise["id"], 300, type="admin_recharge", reason="充值")
        # 绑定期间个人充值也落企业钱包（结算主体是企业）
        self.store.adjust_credit(self.employee["id"], 50, type="admin_recharge", reason="个人赠送")
        wallet = self.store.get_or_create_enterprise_credit_account(self.enterprise["id"])
        self.assertEqual(wallet["balance"], 350)
        # 解绑后消费回落个人钱包
        self.auth_store.update_user(self.employee["id"], enterprise_id=None, update_enterprise=True)
        self.store.adjust_credit(self.employee["id"], 50, type="admin_recharge", reason="解绑后赠送")
        self.store.deduct_credits(self.employee["id"], 30, price_key="llm:assistant_chat")
        personal = self.store.get_or_create_credit_account(self.employee["id"])
        self.assertEqual(personal["balance"], 20)
        wallet = self.store.get_or_create_enterprise_credit_account(self.enterprise["id"])
        self.assertEqual(wallet["balance"], 350)

    def test_my_account_shows_enterprise_scope(self) -> None:
        self.store.adjust_enterprise_credit(self.enterprise["id"], 777, type="admin_recharge", reason="充值")
        self.login_as(self.employee_token)
        res = self.client.get("/api/credits/me")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["scope"], "enterprise")
        self.assertEqual(body["balance"], 777)
        self.assertEqual(body["enterprise"]["id"], self.enterprise["id"])

        # estimate 接口展示企业余额
        res = self.client.post("/api/credits/estimate", json={"mode": "cloud-kling-t2v", "options": {"duration": 5, "kling_mode": "std"}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["balance"], 777)
        self.assertTrue(res.json()["sufficient"])

    def test_admin_adjustment_targets_enterprise_explicitly_and_lists_both_ledgers(self) -> None:
        self.login_as(self.admin_token)
        headers = self.admin_headers()
        employee_id = self.employee["id"]
        enterprise_id = self.enterprise["id"]
        body = {"delta": 150, "reason": "企业额度", "request_id": "top-up"}
        result = self.client.post("/api/admin/credits/adjust", json={**body, "user_id": employee_id}, headers=headers)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.store.get_or_create_enterprise_credit_account(enterprise_id)["balance"], 0)
        endpoint = f"/api/admin/enterprises/{enterprise_id}/credits"
        self.assertEqual(self.client.post(endpoint, json=body, headers=headers).status_code, 200)
        self.assertEqual(self.client.post(endpoint, json=body, headers=headers).json()["balance"], 150)
        excessive = {"delta": -151, "reason": "超额扣减"}
        self.assertEqual(self.client.post(endpoint, json=excessive, headers=headers).status_code, 422)

        response = self.client.get("/api/admin/credits/accounts", params={"query": self.enterprise["name"]}).json()
        self.assertEqual([(row["scope"], row["balance"]) for row in response], [("enterprise", 150)])
        self.store.deduct_credits(employee_id, 30, ref_type="job", ref_id="lookup-job")
        self.store.adjust_credit(self.admin["id"], 10, type="admin_recharge", reason="个人额度")
        path = "/api/admin/credits/transactions"
        self.assertEqual(len(self.client.get(path).json()), 1)
        page_one = self.client.get(path, params={"scope": "all", "limit": 2}).json()
        page_two = self.client.get(path, params={"scope": "all", "limit": 2, "offset": 2}).json()
        self.assertEqual([row["scope"] for row in page_one + page_two], ["user", "enterprise", "enterprise"])
        self.assertEqual(page_two[0]["user_id"], None)
        self.assertEqual(page_two[0]["actor_username"], self.admin["username"])
        hit = self.client.get(path, params={"scope": "enterprise", "query": "lookup-job"}).json()
        self.assertEqual([(row["user_id"], row["delta"]) for row in hit], [(employee_id, -30)])

        self.login_as(self.employee_token)
        mine = self.client.get("/api/credits/transactions").json()
        self.assertEqual([(row["scope"], row["delta"]) for row in mine], [("enterprise", -30)])

    def test_generation_refund_uses_original_wallet_after_transfer_and_runs_once(self) -> None:
        enterprise_id = self.enterprise["id"]
        employee_id = self.employee["id"]
        self.store.adjust_enterprise_credit(enterprise_id, 600, reason="充值")
        mode, options = "cloud-kling-t2v", {"duration": 5, "kling_mode": "std"}
        quote = self.credits.quote_job(employee_id, mode, options)
        job = self.store.create("wallet-test", mode, "测试", "", None, [], options, owner_user_id=employee_id, credit_quote=quote)
        item_id = job["rounds"][0]["generation_items"][0]["id"]
        self.assertEqual(self.store.get_or_create_enterprise_credit_account(enterprise_id)["balance"], 600 - quote.total)
        self.auth_store.update_user(employee_id, enterprise_id=None, update_enterprise=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            failures = [pool.submit(self.store.update_generation, item_id, status=JobStatus.FAILED) for _ in range(2)]
            for failure in failures:
                self.assertTrue(failure.result()["credits_settled"])
        self.assertEqual(self.store.get_or_create_enterprise_credit_account(enterprise_id)["balance"], 600)
        self.assertEqual(self.store.get_or_create_credit_account(employee_id)["balance"], 0)
        self.assertEqual(len(self.store.list_enterprise_credit_transactions(enterprise_id, type="refund")), 1)

    def test_external_job_refund_is_idempotent_after_company_transfer(self) -> None:
        enterprise_id = self.enterprise["id"]
        employee_id = self.employee["id"]
        self.store.adjust_enterprise_credit(enterprise_id, 600, reason="充值")
        bill = self.credits.bill_job(employee_id, "cloud-kling-t2v", {"duration": 5, "kling_mode": "std"}, job_id="external")
        self.auth_store.update_user(employee_id, enterprise_id=None, update_enterprise=True)
        for _ in range(2):
            self.credits.refund_deduction(employee_id, bill["total"], job_id="external", wallet_enterprise_id=bill["wallet_enterprise_id"])
        self.assertEqual(self.store.get_or_create_enterprise_credit_account(enterprise_id)["balance"], 600)
        self.assertEqual(self.store.get_or_create_credit_account(employee_id)["balance"], 0)
        self.assertEqual(len(self.store.list_enterprise_credit_transactions(enterprise_id, type="refund")), 1)


class EnterprisePolicyTests(EnterpriseBase):
    """企业模型访问策略：白名单 / 全关 / LLM·VLM 能力与 /api/modes 过滤。"""

    def setUp(self) -> None:
        super().setUp()
        self.enterprise = self.create_enterprise()
        self.login_as(self.admin_token)
        self.client.post(
            f"/api/admin/enterprises/{self.enterprise['id']}/members",
            json={"user_id": self.employee["id"]},
            headers=self.admin_headers(),
        )

    def set_policies(self, policies: list[dict]) -> None:
        res = self.client.put(
            f"/api/admin/enterprises/{self.enterprise['id']}/policies",
            json={"policies": policies},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_default_allows_everything(self) -> None:
        self.assertTrue(mode_allowed(self.store, self.employee["id"], "cloud-kling-t2v"))
        self.assertTrue(mode_allowed(self.store, self.employee["id"], "grs-gpt-image-2"))
        self.assertTrue(ensure_call_allowed_or_ok(self.store, self.employee["id"], "llm", "assistant_chat"))

    def test_video_whitelist_blocks_other_video_models(self) -> None:
        self.set_policies([
            {"model_kind": "video", "mode": "whitelist", "models": ["cloud-grs-h3-t2v"]},
        ])
        self.assertTrue(mode_allowed(self.store, self.employee["id"], "cloud-grs-h3-t2v"))
        self.assertFalse(mode_allowed(self.store, self.employee["id"], "cloud-kling-t2v"))
        with self.assertRaises(EnterpriseModelForbiddenError):
            ensure_mode_allowed(self.store, self.employee["id"], "cloud-kling-t2v")

    def test_image_none_blocks_all_image_models(self) -> None:
        self.set_policies([
            {"model_kind": "image", "mode": "none", "models": []},
        ])
        self.assertFalse(mode_allowed(self.store, self.employee["id"], "grs-gpt-image-2"))
        # 视频不受影响
        self.assertTrue(mode_allowed(self.store, self.employee["id"], "cloud-kling-t2v"))

    def test_llm_policy_gates_call_balance_and_consume(self) -> None:
        self.set_policies([
            {"model_kind": "llm", "mode": "whitelist", "models": ["assistant_chat"]},
        ])
        self.store.adjust_enterprise_credit(self.enterprise["id"], 100, type="admin_recharge", reason="充值")
        self.credits.require_call_balance(self.employee["id"], "llm", "assistant_chat")
        cost = self.credits.consume_call(self.employee["id"], "llm", "assistant_chat")
        self.assertEqual(cost, 1)
        wallet = self.store.get_or_create_enterprise_credit_account(self.enterprise["id"])
        self.assertEqual(wallet["balance"], 99)

        with self.assertRaises(EnterpriseModelForbiddenError):
            self.credits.require_call_balance(self.employee["id"], "llm", "split_script")
        with self.assertRaises(EnterpriseModelForbiddenError):
            self.credits.consume_call(self.employee["id"], "llm", "split_script")

    def test_vlm_none_blocks_vision_calls(self) -> None:
        self.set_policies([
            {"model_kind": "vlm", "mode": "none", "models": []},
        ])
        with self.assertRaises(EnterpriseModelForbiddenError):
            ensure_call_allowed(self.store, self.employee["id"], "vlm", "analyze_subject")

    def test_invalid_policy_payload_rejected(self) -> None:
        res = self.client.put(
            f"/api/admin/enterprises/{self.enterprise['id']}/policies",
            json={"policies": [{"model_kind": "bogus", "mode": "all", "models": []}]},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 422)
        res = self.client.put(
            f"/api/admin/enterprises/{self.enterprise['id']}/policies",
            json={"policies": [{"model_kind": "video", "mode": "sometimes", "models": []}]},
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 422)

    def test_modes_endpoint_filtered_for_enterprise_member(self) -> None:
        self.set_policies([
            {"model_kind": "video", "mode": "whitelist", "models": ["cloud-grs-h3-t2v"]},
            {"model_kind": "image", "mode": "none", "models": []},
        ])
        self.login_as(self.employee_token)
        res = self.client.get("/api/modes")
        self.assertEqual(res.status_code, 200)
        modes = {item["id"] for item in res.json()["modes"]}
        self.assertIn("cloud-grs-h3-t2v", modes)
        self.assertNotIn("cloud-kling-t2v", modes)
        self.assertNotIn("grs-gpt-image-2", modes)

        # 管理员（未绑定企业）不受影响
        self.login_as(self.admin_token)
        modes = {item["id"] for item in self.client.get("/api/modes").json()["modes"]}
        self.assertIn("cloud-kling-t2v", modes)

    def test_modes_filter_matches_registry_definitions(self) -> None:
        self.set_policies([
            {"model_kind": "video", "mode": "whitelist", "models": ["minimax-h3-t2v"]},
        ])
        visible = filter_workflow_definitions(self.store, self.employee["id"], list(WORKFLOWS))
        video_visible = [item.id for item in visible if item.media_type != "image"]
        self.assertEqual(video_visible, ["minimax-h3-t2v"])


class EnterpriseJobSubmissionTests(EnterpriseBase):
    """提交链路策略拦截：POST /api/jobs 403（浏览器/MCP/导演台共用提交入口）。"""

    def setUp(self) -> None:
        super().setUp()
        self.enterprise = self.create_enterprise()
        self.login_as(self.admin_token)
        self.client.post(
            f"/api/admin/enterprises/{self.enterprise['id']}/members",
            json={"user_id": self.employee["id"]},
            headers=self.admin_headers(),
        )
        self.client.put(
            f"/api/admin/enterprises/{self.enterprise['id']}/policies",
            json={"policies": [{"model_kind": "video", "mode": "whitelist", "models": ["cloud-grs-h3-t2v"]}]},
            headers=self.admin_headers(),
        )

    def test_submit_blocked_for_non_whitelisted_mode(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.post(
            "/api/jobs",
            data={"mode": "cloud-kling-t2v", "prompt": "一只猫", "options": '{"duration": 5, "kling_mode": "std"}'},
            files=[],
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("未开放", res.json()["detail"])

    def test_director_create_queued_job_blocked(self) -> None:
        from backend.app.director_jobs import create_queued_job

        with self.assertRaises(EnterpriseModelForbiddenError):
            create_queued_job(
                self.store,
                owner_user_id=self.employee["id"],
                mode="cloud-kling-t2v",
                prompt="一只猫在奔跑",
                options={"duration": 5, "kling_mode": "std"},
            )
        # 白名单内的工作流可以创建
        job = create_queued_job(
            self.store,
            owner_user_id=self.employee["id"],
            mode="cloud-grs-h3-t2v",
            prompt="一只猫在奔跑",
            options={"duration": 5, "resolution": "480p"},
        )
        self.assertEqual(job["mode"], "cloud-grs-h3-t2v")


class EnterpriseBatchAccountTests(EnterpriseBase):
    """企业批量开号：前缀 + 序号、统一初始密码、冲突整批失败。"""

    def setUp(self) -> None:
        super().setUp()
        self.enterprise = self.create_enterprise()
        self.login_as(self.admin_token)

    def batch_payload(self, **overrides) -> dict:
        payload = {
            "enterprise_id": self.enterprise["id"],
            "username_prefix": "xh",
            "start_index": 1,
            "count": 5,
            "display_name_prefix": "员工",
            "password": "password123456",
        }
        payload.update(overrides)
        return payload

    def test_batch_create_accounts_with_prefix_and_uniform_password(self) -> None:
        res = self.client.post(
            "/api/admin/users/batch", json=self.batch_payload(count=100), headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 201, res.text)
        body = res.json()
        self.assertEqual(body["count"], 100)
        self.assertEqual(body["first_username"], "xh001")
        self.assertEqual(body["last_username"], "xh100")
        self.assertEqual(len(body["users"]), 100)
        self.assertEqual(body["users"][0]["username"], "xh001")
        self.assertEqual(body["users"][0]["display_name"], "员工001")

        created = self.auth_store.get_user(body["users"][0]["id"])
        self.assertEqual(created["enterprise_id"], self.enterprise["id"])
        self.assertEqual(created["role"], UserRole.EMPLOYEE.value)
        self.assertTrue(created["must_change_password"])
        self.assertIsNotNone(self.auth_store.verify_credentials("xh001", "password123456"))

    def test_batch_conflict_is_all_or_nothing(self) -> None:
        first = self.client.post(
            "/api/admin/users/batch", json=self.batch_payload(count=3), headers=self.admin_headers(),
        )
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post(
            "/api/admin/users/batch", json=self.batch_payload(count=5), headers=self.admin_headers(),
        )
        self.assertEqual(second.status_code, 409)
        self.assertIn("xh001", second.json()["detail"])
        usernames = [user["username"] for user in self.auth_store.list_users() if user["username"].startswith("xh")]
        self.assertEqual(usernames, ["xh001", "xh002", "xh003"])

    def test_batch_rejects_disabled_enterprise(self) -> None:
        self.client.patch(
            f"/api/admin/enterprises/{self.enterprise['id']}",
            json={"status": "disabled"}, headers=self.admin_headers(),
        )
        res = self.client.post(
            "/api/admin/users/batch", json=self.batch_payload(), headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 409)

    def test_batch_requires_admin(self) -> None:
        self.login_as(self.employee_token)
        res = self.client.post(
            "/api/admin/users/batch", json=self.batch_payload(),
            headers={"X-CSRF-Token": csrf_token(self.employee_token)},
        )
        self.assertEqual(res.status_code, 403)

    def test_batch_count_limits(self) -> None:
        for count in (0, 201):
            res = self.client.post(
                "/api/admin/users/batch", json=self.batch_payload(count=count), headers=self.admin_headers(),
            )
            self.assertEqual(res.status_code, 422)

    def test_batch_custom_start_and_prefix_case(self) -> None:
        res = self.client.post(
            "/api/admin/users/batch",
            json=self.batch_payload(username_prefix="ManJu", start_index=98, count=5),
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 201, res.text)
        body = res.json()
        self.assertEqual(body["first_username"], "manju098")
        self.assertEqual(body["last_username"], "manju102")
        self.assertEqual(
            [user["username"] for user in body["users"]],
            ["manju098", "manju099", "manju100", "manju101", "manju102"],
        )
        self.assertEqual(
            [user["display_name"] for user in body["users"]],
            ["员工098", "员工099", "员工100", "员工101", "员工102"],
        )

    def test_batch_created_account_state_and_shared_password_hash(self) -> None:
        res = self.client.post(
            "/api/admin/users/batch", json=self.batch_payload(count=2), headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 201, res.text)
        with self.auth_store.connection() as connection:
            rows = connection.execute(
                """SELECT username, is_active, must_change_password, email, password_hash
                FROM users WHERE username IN (?, ?) ORDER BY username""",
                ("xh001", "xh002"),
            ).fetchall()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(int(row["is_active"]), 1)
            self.assertEqual(int(row["must_change_password"]), 1)
            self.assertIsNone(row["email"])
        # 统一密码只哈希一次，两个账号复用同一哈希且都能通过密码校验。
        self.assertEqual(rows[0]["password_hash"], rows[1]["password_hash"])
        self.assertIsNotNone(self.auth_store.verify_credentials("xh002", "password123456"))

    def test_batch_rejects_unknown_enterprise(self) -> None:
        res = self.client.post(
            "/api/admin/users/batch",
            json=self.batch_payload(enterprise_id="ent-missing"),
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 404)

    def test_batch_conflicts_with_existing_single_account(self) -> None:
        created = self.client.post(
            "/api/admin/users",
            json={
                "username": "xh003", "display_name": "已存在", "password": "password123456",
                "role": "employee", "enterprise_id": self.enterprise["id"],
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        before = {user["username"] for user in self.auth_store.list_users()}
        res = self.client.post(
            "/api/admin/users/batch", json=self.batch_payload(count=5), headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 409)
        self.assertIn("xh003", res.json()["detail"])
        self.assertEqual({user["username"] for user in self.auth_store.list_users()}, before)

    def test_batch_invalid_payloads(self) -> None:
        cases = [
            ("blank prefix", {"username_prefix": " "}),
            ("invalid prefix char", {"username_prefix": "xh/"}),
            ("zero start", {"start_index": 0}),
            ("blank name prefix", {"display_name_prefix": " "}),
            ("short password", {"password": "123"}),
        ]
        before = len(self.auth_store.list_users())
        for label, override in cases:
            with self.subTest(label=label):
                res = self.client.post(
                    "/api/admin/users/batch", json=self.batch_payload(**override), headers=self.admin_headers(),
                )
                self.assertEqual(res.status_code, 422, f"{label}: {res.text}")
        self.assertEqual(len(self.auth_store.list_users()), before)

    def test_batch_requires_csrf(self) -> None:
        before = len(self.auth_store.list_users())
        res = self.client.post("/api/admin/users/batch", json=self.batch_payload(), headers={})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(len(self.auth_store.list_users()), before)

    def test_batch_writes_audit_log(self) -> None:
        res = self.client.post(
            "/api/admin/users/batch", json=self.batch_payload(count=3), headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 201, res.text)
        with self.auth_store.connection() as connection:
            row = connection.execute(
                """SELECT action, target_type, target_id, detail FROM audit_logs
                WHERE action = ? ORDER BY id DESC LIMIT 1""",
                ("batch_create_users",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["target_type"], "enterprise")
        self.assertEqual(row["target_id"], self.enterprise["id"])
        self.assertIn("count=3", row["detail"])
        self.assertIn("xh001-xh003", row["detail"])


class EnterpriseBatchStoreValidationTests(EnterpriseBase):
    """AuthStore.create_users_bulk 的边界校验（不经 HTTP）。"""

    def setUp(self) -> None:
        super().setUp()
        self.enterprise = self.create_enterprise()

    def bulk_kwargs(self, **overrides) -> dict:
        payload = {
            "enterprise_id": self.enterprise["id"],
            "username_prefix": "xh",
            "start_index": 1,
            "count": 2,
            "display_name_prefix": "员工",
            "password": "password123456",
        }
        payload.update(overrides)
        return payload

    def test_rejects_invalid_inputs_without_creating_accounts(self) -> None:
        cases = [
            ("empty enterprise", {"enterprise_id": " "}),
            ("empty prefix", {"username_prefix": ""}),
            ("invalid prefix", {"username_prefix": "中文"}),
            ("zero start", {"start_index": 0}),
            ("zero count", {"count": 0}),
            ("too many", {"count": 201}),
            ("empty name prefix", {"display_name_prefix": " "}),
            ("short password", {"password": "123"}),
            ("username too long", {"username_prefix": "a" * 60, "start_index": 999999, "count": 1}),
            ("display name too long", {"display_name_prefix": "员" * 78, "start_index": 999999, "count": 1}),
        ]
        before = len(self.auth_store.list_users())
        for label, override in cases:
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    self.auth_store.create_users_bulk(**self.bulk_kwargs(**override))
                self.assertEqual(len(self.auth_store.list_users()), before)

    def test_padding_width_expands_for_large_index(self) -> None:
        users = self.auth_store.create_users_bulk(**self.bulk_kwargs(start_index=998, count=5))
        self.assertEqual(
            [user["username"] for user in users],
            ["xh0998", "xh0999", "xh1000", "xh1001", "xh1002"],
        )
        self.assertEqual(
            [user["display_name"] for user in users],
            ["员工0998", "员工0999", "员工1000", "员工1001", "员工1002"],
        )

    def test_start_index_boundary_single_account(self) -> None:
        users = self.auth_store.create_users_bulk(**self.bulk_kwargs(start_index=999999, count=1))
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["username"], "xh999999")
        self.assertEqual(users[0]["display_name"], "员工999999")

    def test_uniform_password_is_hashed_once(self) -> None:
        self.auth_store.create_users_bulk(**self.bulk_kwargs(count=3))
        with self.auth_store.connection() as connection:
            rows = connection.execute(
                "SELECT password_hash FROM users WHERE username IN (?, ?, ?)",
                ("xh001", "xh002", "xh003"),
            ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row["password_hash"] for row in rows}), 1)


class EnterpriseMemberQuotaTests(EnterpriseBase):
    """企业成员额度：月度/累计上限、退款回冲、成员隔离与生命周期清理。"""

    def setUp(self) -> None:
        super().setUp()
        self.enterprise = self.create_enterprise()
        self.login_as(self.admin_token)
        self.client.post(
            f"/api/admin/enterprises/{self.enterprise['id']}/members",
            json={"user_id": self.employee["id"]},
            headers=self.admin_headers(),
        )
        self.client.post(
            f"/api/admin/enterprises/{self.enterprise['id']}/credits",
            json={"delta": 5000, "reason": "开户充值"},
            headers=self.admin_headers(),
        )

    def set_quota(self, period: str, credit_limit: int, user_id: str | None = None):
        return self.client.put(
            f"/api/admin/enterprises/{self.enterprise['id']}/members/{user_id or self.employee['id']}/quota",
            json={"period": period, "credit_limit": credit_limit},
            headers=self.admin_headers(),
        )

    def wallet(self) -> dict:
        return self.store.get_or_create_enterprise_credit_account(self.enterprise["id"])

    def test_monthly_quota_blocks_and_refund_restores(self) -> None:
        res = self.set_quota("monthly", 1000)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["quota_period"], "monthly")
        self.assertEqual(res.json()["quota_limit"], 1000)

        self.store.deduct_credits(
            self.employee["id"], 800, price_key="test", ref_type="job", ref_id="job-quota-a",
        )
        balance_before = self.wallet()["balance"]
        with self.assertRaises(CreditInsufficientError) as raised:
            self.store.deduct_credits(
                self.employee["id"], 300, price_key="test", ref_type="job", ref_id="job-quota-b",
            )
        self.assertIn("企业分配额度不足", str(raised.exception))
        self.assertEqual(self.wallet()["balance"], balance_before)

        self.store.refund_credits(
            self.employee["id"], 800, reason="任务失败退回", ref_type="job", ref_id="job-quota-a",
        )
        self.store.deduct_credits(
            self.employee["id"], 900, price_key="test", ref_type="job", ref_id="job-quota-c",
        )
        self.assertEqual(self.wallet()["balance"], 4100)

    def test_total_quota_and_member_isolation(self) -> None:
        second = self.auth_store.create_user(
            "worker2", "员工二", "password123456", UserRole.EMPLOYEE,
            enterprise_id=self.enterprise["id"],
        )
        self.assertEqual(self.set_quota("total", 500).status_code, 200)

        self.store.deduct_credits(
            self.employee["id"], 400, price_key="test", ref_type="job", ref_id="job-total-a",
        )
        with self.assertRaises(CreditInsufficientError):
            self.store.deduct_credits(
                self.employee["id"], 200, price_key="test", ref_type="job", ref_id="job-total-b",
            )
        # 其他成员未配置额度，不受影响
        self.store.deduct_credits(
            second["id"], 200, price_key="test", ref_type="job", ref_id="job-total-c",
        )

        self.store.refund_credits(
            self.employee["id"], 200, reason="退款", ref_type="job", ref_id="job-total-a",
        )
        self.store.deduct_credits(
            self.employee["id"], 300, price_key="test", ref_type="job", ref_id="job-total-d",
        )
        with self.assertRaises(CreditInsufficientError):
            self.store.deduct_credits(
                self.employee["id"], 1, price_key="test", ref_type="job", ref_id="job-total-e",
            )

    def test_member_list_returns_quota_and_can_clear(self) -> None:
        self.assertEqual(self.set_quota("monthly", 5000).status_code, 200)
        members = self.client.get(
            f"/api/admin/enterprises/{self.enterprise['id']}/members", headers=self.admin_headers(),
        ).json()
        member = next(item for item in members if item["id"] == self.employee["id"])
        self.assertEqual(member["quota_period"], "monthly")
        self.assertEqual(member["quota_limit"], 5000)
        self.assertEqual(member["quota_used"], 0)

        self.assertEqual(self.set_quota("none", 0).status_code, 200)
        members = self.client.get(
            f"/api/admin/enterprises/{self.enterprise['id']}/members", headers=self.admin_headers(),
        ).json()
        member = next(item for item in members if item["id"] == self.employee["id"])
        self.assertEqual(member["quota_period"], "none")
        self.assertEqual(member["quota_limit"], 0)

        self.assertEqual(self.set_quota("monthly", 0).status_code, 422)
        other = self.auth_store.create_user(
            "unbound", "未绑定", "password123456", UserRole.EMPLOYEE,
        )
        self.assertEqual(self.set_quota("monthly", 100, user_id=other["id"]).status_code, 409)

    def test_unbind_clears_member_quota(self) -> None:
        self.assertEqual(self.set_quota("monthly", 500).status_code, 200)
        res = self.client.delete(
            f"/api/admin/enterprises/{self.enterprise['id']}/members/{self.employee['id']}",
            headers=self.admin_headers(),
        )
        self.assertEqual(res.status_code, 200, res.text)
        quota = self.store.get_enterprise_member_quota(self.enterprise["id"], self.employee["id"])
        self.assertEqual(quota["period"], "none")

    def test_quota_precheck_blocks_before_call(self) -> None:
        self.assertEqual(self.set_quota("monthly", 100).status_code, 200)
        self.store.deduct_credits(
            self.employee["id"], 100, price_key="test", ref_type="job", ref_id="job-precheck",
        )
        with self.assertRaises(CreditInsufficientError):
            self.credits.require_call_balance(self.employee, "llm", "optimize_prompt")
        # 额度足够时预检通过
        self.assertEqual(self.set_quota("monthly", 100000).status_code, 200)
        self.credits.require_call_balance(self.employee, "llm", "optimize_prompt")


def ensure_call_allowed_or_ok(store, user_id: str, scope: str, kind: str) -> bool:
    """测试辅助：ensure_call_allowed 不抛错即视为允许。"""
    ensure_call_allowed(store, user_id, scope, kind)
    return True


if __name__ == "__main__":
    unittest.main()
