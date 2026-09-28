from __future__ import annotations

from copy import deepcopy
import json

from ..db import transaction_cursor, now_str
from . import production_state as model


class ProductionConflict(RuntimeError):
    pass


class ProductionService:
    @staticmethod
    def detail(project_id: str, episode_id: str) -> dict:
        from .project_detail_service import ProjectDetailService
        return ProjectDetailService.get_episode_detail(project_id, episode_id)

    @classmethod
    def get(cls, project_id: str, episode_id: str, mode: str | None = None) -> dict:
        detail = cls.detail(project_id, episode_id)
        return model.summary(detail, mode=mode)

    @classmethod
    def _mutate(cls, project_id, episode_id, operation, expected_revision=None):
        # Populate legacy beats before entering the lock, then re-read current state under lock.
        prior_detail = cls.detail(project_id, episode_id)
        from .project_detail_service import ProjectDetailService
        from .prompt_expansion_service import PromptExpansionService
        with transaction_cursor() as cursor:
            cursor.execute("SELECT * FROM ai_project_episodes WHERE id=%s AND project_id=%s FOR UPDATE", (episode_id, project_id))
            row = cursor.fetchone()
            if not row:
                raise ValueError("分集不存在")
            data = json.loads(row.get("data_json") or "{}")
            cursor.execute("SELECT * FROM ai_project_assets WHERE project_id=%s ORDER BY updated_at DESC", (project_id,))
            assets = [ProjectDetailService._hydrate_asset(dict(a)) for a in cursor.fetchall()]
            authoring = PromptExpansionService.hydrated_authoring_state(project_id, row, data, data.get("beats") or [], assets)
            detail = {"id": episode_id, "project_id": project_id, "script_text": row.get("script_text"),
                      "data": data, "beats": data.get("beats") or [], "prompt_authoring": authoring,
                      "production_asset_fingerprint": model.asset_fingerprint(assets, data.get("beats") or []),
                      "legacy_director_output": prior_detail.get("legacy_director_output"),
                      "legacy_director_jobs": prior_detail.get("legacy_director_jobs")}
            state = model.hydrate(detail)
            if expected_revision is not None and (type(expected_revision) is not int or state["revision"] != expected_revision):
                raise ProductionConflict("制作版本已变化，请刷新后重试")
            operation(state, detail)
            state["revision"] += 1
            data["production"] = state
            cursor.execute("UPDATE ai_project_episodes SET data_json=%s,updated_at=%s WHERE id=%s AND project_id=%s",
                           (json.dumps(data, ensure_ascii=False), now_str(), episode_id, project_id))
            return model.summary(detail, state)

    @staticmethod
    def _expected(payload):
        if type(payload.get("expected_revision")) is not int:
            raise ValueError("必须提供 expected_revision")
        return payload["expected_revision"]

    @classmethod
    def update(cls, project_id: str, episode_id: str, payload: dict, action: str) -> dict:
        expected = cls._expected(payload)
        mode = payload.get("mode")
        if mode not in model.MODES:
            raise ValueError("未知制作方式")
        def apply(state, detail):
            nonlocal mode
            if state.get("schema_version") == 2:
                mode = "director"
            if action == "adopt":
                model.adopt(state, detail, mode, str(payload.get("material_id") or ""))
            elif action == "audio":
                if not isinstance(payload.get("audio"), list):
                    raise ValueError("必须提供声音编排列表")
                c = model.plan_context(detail, mode)
                model.version(state, mode, c["key"])["audio"] = model.validate_audio(state, detail, mode, payload["audio"])
            elif action != "mode":
                raise ValueError("未知制作操作")
            state["active_mode"] = mode
        return cls._mutate(project_id, episode_id, apply, expected)

    @staticmethod
    def generation_context(detail: dict, mode: str) -> dict:
        from .workshop_contract import unified
        if unified(detail):
            mode = "director"
        context = model.plan_context(detail, mode)
        return {"mode": mode, "plan_key": context["key"], "plan_snapshot": context["snapshot"],
                "unit_ids": [u["id"] for u in context["units"]]}

    @classmethod
    def record_output(cls, payload: dict, job_id: str, units: list[dict], url: str, measured: dict) -> str:
        context = payload["production_context"]
        mode = context["mode"]
        ids = [str(s["beat_id"]) for s in units]
        material_id = "material-" + model.digest([job_id, ids, measured.get("variant"), measured.get("content_sha256")])
        material = {"id": material_id, "job_id": job_id, "plan_key": context["plan_key"],
                    "unit_ids": ids, "url": url, "title": "连续选区" if len(ids) > 1 else "画面版本",
                    "workflow_id": units[0].get("group_workflow_id") or payload.get("workflow_id"),
                    "render_mode": units[0].get("group_render_mode"), "created_at": now_str(), **measured}
        def add(state, detail):
            current = model.plan_context(detail, mode)
            same_input = current["snapshot"].get("revision") == context["plan_snapshot"].get("revision") if isinstance(current["snapshot"], dict) and current["snapshot"].get("schema_version") == 7 else True
            model.register_material(state, mode, material, auto_adopt=payload.get("auto_adopt", True) and same_input and current["key"] == context["plan_key"] and not current["stale"])
        cls._mutate(payload["project_id"], payload["episode_id"], add)
        payload.setdefault("production_material_ids", [])
        if material_id not in payload["production_material_ids"]:
            payload["production_material_ids"].append(material_id)
        return material_id

    @classmethod
    def export_snapshot(cls, project_id: str, episode_id: str, options: dict) -> dict:
        expected = cls._expected(options)
        snapshot = {}
        def freeze(state, detail):
            mode = options.get("production_mode") or state["active_mode"]
            s = model.summary(detail, state, mode)
            if not s["ready"]:
                raise ValueError("；".join(s["block_reasons"]))
            snapshot.update({k: deepcopy(s[k]) for k in ("revision", "plan_key", "fingerprint", "timeline", "audio")})
            snapshot["mode"] = mode
        cls._mutate(project_id, episode_id, freeze, expected)
        return snapshot

    @classmethod
    def record_export(cls, payload: dict, job_id: str, url: str, *, direct: bool = False) -> None:
        context = payload["production_context"] if direct else payload["production_snapshot"]
        def add(state, detail):
            v = model.version(state, context["mode"], context["plan_key"])
            if any(e.get("job_id") == job_id for e in v["exports"]):
                return
            fp = context.get("fingerprint")
            if direct:
                adopted = set(v["adopted"].values())
                ids = set(context["unit_ids"])
                matches = ids == set(v["adopted"]) and adopted == set(payload.get("production_material_ids") or [])
                fp = model.fingerprint(v) if matches and not any(a.get("enabled", True) for a in v["audio"]) else None
            v["exports"].append({"job_id": job_id, "url": url, "fingerprint": fp, "created_at": now_str(),
                                 "source": "generated" if direct else "composed", "plan_key": context["plan_key"]})
        cls._mutate(payload["project_id"], payload["episode_id"], add)
