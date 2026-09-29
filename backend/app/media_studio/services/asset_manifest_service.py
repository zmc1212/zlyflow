"""Document-scoped manifest candidates. Only confirmation writes project assets."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import socket
import threading
import time
import uuid

from ..db import query_one, query_all, execute_sql, transaction_cursor, now_str
from .workshop_contract import digest
from .asset_pipeline_prompts import adapter, request, strict_object, VERSION


# Models occasionally echo transport/display fields even when the asset contract
# says not to.  These fields never participate in identity, evidence, or
# persistence; they can be discarded safely while retaining the raw response in
# the job evidence.  Unknown semantic fields remain a hard validation error.
IGNORABLE_ASSET_FIELDS = frozenset({
    "id", "asset_id", "look_id", "description", "visual_description",
    "visual_traits", "appearance", "role", "category", "type", "source",
    "source_quote", "evidence_scope", "notes", "剧情功能", "所属分类",
    "所属角色或场景", "时代/世界观",
})


def owner_alive(owner):
    """A second local app/test process must not recover the active server's work."""
    if not owner:
        return False
    if owner.get("host") != socket.gethostname():
        return True  # Another host owns this task; never reclaim it locally.
    pid = owner.get("pid")
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied is not proof of death.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def source_state(row):
    analysis = json.loads(row.get("analysis_json") or "{}")
    adopted = analysis.get("script_development") or {}
    text = str(adopted.get("script_text") or row.get("raw_text") or "")
    return analysis, {"text": text, "revision": adopted.get("revision", 0),
                      "fingerprint": digest([text, adopted.get("revision", 0)])}


def _find_evidence_scope(part, source, scope, earlier_blocks):
    """Return the source scope containing an exact evidence part."""
    normalized = str(source or "").replace("\r\n", "\n")
    if part in normalized:
        return scope
    for index, block in enumerate(earlier_blocks, 1):
        if part in str(block or "").replace("\r\n", "\n"):
            return index
    return None


def _source_line(block, needle):
    """Return one complete source line containing needle."""
    for line in str(block or "").replace("\r\n", "\n").split("\n"):
        if needle in line and line.strip():
            return line.strip()
    return None


def _repair_evidence_part(part, item, source, scope, earlier_blocks):
    """Canonicalize a model-edited quote to text that actually exists.

    This only accepts a long exact suffix (for example, a speaker prefix was
    omitted) or a source line containing the asset name/alias. Ellipsis and
    free-form paraphrases never pass this repair.
    """
    if "…" in part or "..." in part:
        suffixes = []
    else:
        suffixes = [part.rsplit(mark, 1)[-1].strip() for mark in ("：", ":", "。", "！", "？", "；") if mark in part]
    suffixes = sorted({value for value in suffixes if len(value) >= 8}, key=len, reverse=True)
    for candidate in suffixes:
        found_scope = _find_evidence_scope(candidate, source, scope, earlier_blocks)
        if found_scope is None:
            continue
        block = source if found_scope == scope else earlier_blocks[found_scope - 1]
        return {"scope": found_scope, "quote": _source_line(block, candidate) or candidate}, "suffix"

    names = [item.get("name"), *(item.get("aliases") or [])]
    if not any(isinstance(name, str) and name and name in part for name in names):
        return None, None
    for name in names:
        if not isinstance(name, str) or not name:
            continue
        found_scope = _find_evidence_scope(name, source, scope, earlier_blocks)
        if found_scope is None:
            continue
        block = source if found_scope == scope else earlier_blocks[found_scope - 1]
        line = _source_line(block, name)
        if line:
            return {"scope": found_scope, "quote": line}, "name"
    return None, None


def validate_entries(result, source, scope, earlier_blocks=(), evidence_repairs=None):
    if not isinstance(result.get("entries"), list) or not isinstance(result.get("issues"), list):
        raise ValueError("INVALID_JSON: 资产清单必须包含 entries 和 issues 数组")
    entries = []
    for item in result["entries"]:
        if not isinstance(item, dict) or set(item) - {"kind", "name", "aliases", "identity", "era", "evidence"}:
            raise ValueError("INVALID_JSON: 未知资产字段")
        if item.get("kind") not in {"character", "scene", "prop"} or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("INVALID_ASSET: 资产类型或名称无效")
        if not isinstance(item.get("aliases", []), list) or any(not isinstance(a, str) for a in item.get("aliases", [])):
            raise ValueError("INVALID_ASSET: 别名必须是字符串数组")
        quote = item.get("evidence")
        normalized_source = str(source or "").replace("\r\n", "\n")
        normalized_blocks = [str(block or "").replace("\r\n", "\n") for block in earlier_blocks]
        if isinstance(quote, str):
            quote_text = quote.replace("\r\n", "\n").strip()
            # A model may cite two valid paragraphs separated by an intervening
            # scene action. Treat blank-line-separated parts as independent
            # citations; never accept a rewritten or invented part.
            if quote_text in normalized_source:
                quote_parts = [quote_text]
            else:
                quote_parts = [part.strip() for part in re.split(r"\n\s*\n", quote_text) if part.strip()]
        elif isinstance(quote, list):
            quote_parts = ([part.replace("\r\n", "\n").strip() for part in quote]
                           if quote and all(isinstance(part, str) and part.strip() for part in quote) else [])
        else:
            quote_parts = []
        citations = []
        unresolved = []
        for part in quote_parts:
            evidence_scope = _find_evidence_scope(part, normalized_source, scope, normalized_blocks)
            if evidence_scope is None:
                repaired, repair_kind = _repair_evidence_part(part, item, normalized_source, scope, normalized_blocks)
                if repaired:
                    citations.append(repaired)
                    if evidence_repairs is not None:
                        evidence_repairs.append({"name": item.get("name"), "kind": repair_kind,
                                                 "original": part, "canonical": repaired["quote"]})
                    continue
                unresolved.append(part)
            else:
                citations.append({"scope": evidence_scope, "quote": part})
        if unresolved:
            raise ValueError(f"INVALID_EVIDENCE: 资产 {item.get('name')} 的出处不是输入中的连续原文：{quote}")
        if not citations:
            raise ValueError(f"INVALID_EVIDENCE: 资产 {item.get('name')} 的出处不是输入中的连续原文：{quote}")
        identity = str(item.get("identity") or item["name"]).strip()
        era = str(item.get("era") or "未明确")
        if item["kind"] == "character" and "现代" in era and "古代" in era:
            raise ValueError(f"INVALID_ERA: {item['name']} 将现代与古代写入同一造型，必须分成两个条目，identity 保持相同，分别提供出处")
        # Evidence context distinguishes generic kinship labels from different families.
        stable = digest([item["kind"], item["name"].strip(), identity, str(item.get("era") or "未明确")])[:20]
        entries.append({**item, "name": item["name"].strip(), "identity": identity,
                        "id": "manifest-" + stable, "scope": scope, "evidence": citations})
    return entries


def normalize_model_asset_fields(result):
    """Drop harmless model-only fields before the strict asset validator.

    The strict validator remains the public contract and continues to reject
    arbitrary fields.  This narrow compatibility pass only handles fields that
    cannot affect the saved asset identity or provenance, and reports exactly
    what was dropped so the original response remains auditable.
    """
    if not isinstance(result, dict) or not isinstance(result.get("entries"), list):
        return result, []
    normalized = deepcopy(result)
    warnings = []
    entries = []
    for index, item in enumerate(normalized["entries"], 1):
        if not isinstance(item, dict):
            entries.append(item)
            continue
        extras = set(item) - {"kind", "name", "aliases", "identity", "era", "evidence"}
        removable = extras & IGNORABLE_ASSET_FIELDS
        if removable:
            item = {key: value for key, value in item.items() if key not in removable}
            # The prompt's Chinese asset template calls this display-only
            # field "时代/世界观".  It is safe to use as the contract's era
            # when the model omitted the canonical key entirely.
            if "era" not in item and "时代/世界观" in normalized["entries"][index - 1]:
                item["era"] = normalized["entries"][index - 1]["时代/世界观"]
            warnings.append({"entry": index, "fields": sorted(removable)})
        entries.append(item)
    normalized["entries"] = entries
    return normalized, warnings


class AssetManifestService:
    JOB_TYPE = "asset_manifest"
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="asset-manifest")
    lock = threading.RLock()

    @staticmethod
    def document(project_id, doc_id):
        row = query_one("SELECT * FROM ai_project_documents WHERE id=%s AND project_id=%s", (doc_id, project_id))
        if not row:
            raise ValueError("剧本文档不存在")
        return row

    @classmethod
    def confirmed(cls, project_id, doc_id):
        analysis, source = source_state(cls.document(project_id, doc_id))
        manifest = analysis.get("asset_manifest") or {}
        if manifest.get("status") != "confirmed" or manifest.get("source_fingerprint") != source["fingerprint"]:
            raise ValueError("MANIFEST_REQUIRED: 请先到内容库提取并确认当前剧本的全局资产")
        return manifest

    @classmethod
    def get(cls, project_id, doc_id):
        analysis, source = source_state(cls.document(project_id, doc_id))
        manifest = deepcopy(analysis.get("asset_manifest"))
        if manifest and manifest.get("source_fingerprint") != source["fingerprint"]:
            manifest["status"] = "stale"
        jobs = query_all("SELECT * FROM ai_project_jobs WHERE project_id=%s AND job_type=%s ORDER BY created_at DESC", (project_id, cls.JOB_TYPE))
        matching = [j for j in jobs if json.loads(j["payload_json"]).get("document_id") == doc_id]
        latest = max(matching, key=lambda j: json.loads(j["payload_json"]).get("created_order", 0), default=None)
        job = None
        if latest:
            payload = json.loads(latest["payload_json"])
            job = {"id": latest["id"], "status": latest["status"], "error": latest.get("error_message"),
                   "revision": digest(payload), "data": {k: v for k, v in payload.items() if k not in {"evidence", "source", "settings", "assets_snapshot"}}}
        return {"manifest": manifest, "job": job,
                "history": [{k: v.get(k) for k in ("version", "confirmed_at", "source_revision")} for v in analysis.get("asset_manifest_history") or []],
                "assets": [{**{k: a.get(k) for k in ("id", "name", "kind")},
                            "looks": [{k: look.get(k) for k in ("id", "name")} for look in json.loads(a.get("extra_json") or "{}").get("identities", [])]}
                           for a in query_all("SELECT id,name,kind,extra_json FROM ai_project_assets WHERE project_id=%s", (project_id,))]}

    @classmethod
    def start(cls, project_id, doc_id):
        with cls.lock:
            current = cls.get(project_id, doc_id)
            if current["job"] and current["job"]["status"] in {"queued", "running", "awaiting_review"}:
                return current
            analysis, source = source_state(cls.document(project_id, doc_id))
            if not source["text"].strip():
                raise ValueError("剧本为空")
            project = query_one("SELECT settings_json FROM ai_projects WHERE id=%s", (project_id,)) or {}
            settings = json.loads(project.get("settings_json") or "{}")
            safe = {**settings, **(settings.get("extra") or {})}
            safe = {k: safe[k] for k in ("art_style", "art_style_id", "era", "visual_style", "aspect_ratio", "genre") if k in safe}
            jid = "job-" + uuid.uuid4().hex[:12]
            payload = {"document_id": doc_id, "created_order": time.time_ns(), "source": source, "settings": safe, "evidence": [],
                       "owner": {"host": socket.gethostname(), "pid": os.getpid()},
                       "base_version": (analysis.get("asset_manifest") or {}).get("version"),
                       "previous_entries": (analysis.get("asset_manifest") or {}).get("entries") or [],
                       "assets_snapshot": current["assets"], "message": "等待提取全局资产", "entries": [], "issues": [], "coverage": []}
            if current["job"] and current["job"]["status"] == "failed":
                from ..provider_bridge import llm_row
                old = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s AND project_id=%s", (current["job"]["id"], project_id))
                prior = json.loads(old["payload_json"]) if old else {}
                models = {e.get("model") for e in prior.get("evidence", [])}
                if (prior.get("source") == source and prior.get("settings") == safe
                        and prior.get("base_version") == payload["base_version"]
                        and prior.get("prompt_source") == {k: v for k, v in adapter("assets").items() if k != "system"}
                        and models == {(llm_row() or {}).get("model")} and prior.get("coverage")):
                    for key in ("entries", "issues", "coverage", "evidence"):
                        payload[key] = deepcopy(prior[key])
                    payload["resumed_from_job_id"] = current["job"]["id"]
                    payload["message"] = f"继续提取，已完成 {len(payload['coverage'])} 个区块"
            execute_sql("INSERT INTO ai_project_jobs (id,project_id,job_type,title,status,progress,payload_json,created_at,updated_at) VALUES (%s,%s,%s,%s,'queued',0,%s,%s,%s)",
                        (jid, project_id, cls.JOB_TYPE, "提取全局资产", json.dumps(payload, ensure_ascii=False), now_str(), now_str()))
            cls.executor.submit(cls.run, project_id, jid)
            return cls.get(project_id, doc_id)

    @classmethod
    def run(cls, project_id, jid):
        if not execute_sql("UPDATE ai_project_jobs SET status='running' WHERE id=%s AND project_id=%s AND status='queued'", (jid, project_id)):
            return
        row = query_one("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s", (jid, project_id))
        payload = json.loads(row["payload_json"])
        run_id = uuid.uuid4().hex
        payload["run_id"] = run_id
        previous = row["payload_json"]

        def save(status="running", error=None):
            nonlocal previous
            encoded = json.dumps(payload, ensure_ascii=False)
            if not execute_sql("UPDATE ai_project_jobs SET payload_json=%s,status=%s,error_message=%s,updated_at=%s WHERE id=%s AND project_id=%s AND status='running' AND payload_json=%s",
                               (encoded, status, error, now_str(), jid, project_id, previous)):
                raise ValueError("任务已取消或已被新执行替代")
            previous = encoded

        try:
            save()
            source = payload["source"]["text"]
            # Complete contiguous coverage, including preamble; never truncate long scripts.
            import re
            boundaries = [0, *[m.start() for m in re.finditer(r"(?m)^#{1,3}\s*第[^\n]{1,20}集", source) if m.start() > 0], len(source)]
            blocks = [source[a:b] for a, b in zip(boundaries, boundaries[1:]) if source[a:b].strip()]
            if any(len(block) > 50000 for block in blocks):
                raise ValueError("SOURCE_TOO_LARGE: 单集超过 50000 字，请按集整理；未截断剧本")
            spec = adapter("assets")
            payload["prompt_source"] = {k: v for k, v in spec.items() if k != "system"}
            covered = payload.get("coverage") or []
            if any(c.get("scope") != i or i > len(blocks) or c.get("sha256") != digest(blocks[i-1]) for i, c in enumerate(covered, 1)):
                raise ValueError("RESUME_CONFLICT: 已完成区块与当前剧本不一致，请重新提取")
            merged = {entry["id"]: entry for entry in payload.get("entries", [])}
            for index, block in enumerate(blocks, 1):
                if index <= len(covered):
                    continue
                payload["message"] = f"提取全局资产 {index}/{len(blocks)}"
                system = spec["system"] + '\n返回且只返回 {"entries":[{"kind":"character|scene|prop","name":"规范名","identity":"有证据的身份（称谓须包含家庭归属）","aliases":[],"era":"时代/造型或未明确","evidence":"原文逐字引用"}],"issues":["歧义说明"]}。evidence 可用空行分隔多个独立连续原文片段；每个片段必须逐字来自 source，不得把中间剧情拼进同一片段。不返回数据库 ID。跨分集合并沿用输入已有身份，有歧义时分开并报告。'
                system += '\nidentity 是稳定身份键，不是人物简介：同人必须逐字沿用 known_entries 的 name 和 identity，不因新增外貌、职业、社会关系而改写。era 是单一时代/造型键，沿用已有准确造型；现代与古代必须分成两个条目，不能合写一个 era。不要把剧情分析、没有姓名或外貌细节等正常未知列为歧义；issues 只报告影响身份、造型或资产归属的冲突。'
                user = json.dumps({"settings": payload["settings"], "source": block,
                                   "known_entries": list(merged.values()) or payload.get("previous_entries", [])}, ensure_ascii=False)
                for attempt in range(2):
                    raw = request("assets", system, user, payload["evidence"], save, max_tokens=12000, temperature=0.1)
                    try:
                        parsed = strict_object(raw, {"entries", "issues"})
                        evidence_repairs = []
                        try:
                            entries = validate_entries(parsed, block, index, blocks[:index-1], evidence_repairs)
                        except ValueError as err:
                            # Some OpenAI-compatible endpoints add harmless
                            # display/transport keys to each item.  Preserve
                            # the strict contract for all other fields, but
                            # discard this narrow known set so extraction can
                            # continue without another paid retry.
                            normalized, warnings = normalize_model_asset_fields(parsed)
                            if not warnings:
                                raise
                            evidence_repairs.clear()
                            entries = validate_entries(normalized, block, index, blocks[:index-1], evidence_repairs)
                            parsed = normalized
                            payload["evidence"][-1]["normalization_warnings"] = warnings
                        if evidence_repairs:
                            payload["evidence"][-1]["evidence_repairs"] = evidence_repairs
                        payload["evidence"][-1]["parsed"] = parsed
                        break
                    except ValueError as err:
                        payload["evidence"][-1]["validation_error"] = str(err)
                        if attempt:
                            raise
                        user += "\n上版错误：" + str(err) + "。仅一次修正：evidence 的每个片段必须是 source 中连续逐字原文；需要多处出处时用空行分隔独立片段，不拼接中间剧情，不改标点，不用省略号替代。返回完整 JSON。\n上版：" + raw
                for entry in entries:
                    if entry["id"] in merged:
                        merged[entry["id"]]["evidence"].extend(entry["evidence"])
                        merged[entry["id"]]["aliases"] = list(dict.fromkeys([*merged[entry["id"]].get("aliases", []), *entry.get("aliases", [])]))
                    else:
                        merged[entry["id"]] = entry
                payload["entries"] = list(merged.values())
                payload["issues"].extend(str(i) for i in parsed["issues"])
                payload["coverage"].append({"scope": index, "characters": len(block), "sha256": digest(block)})
                save()
            for entry in payload["entries"]:
                matches = [a for a in payload["assets_snapshot"] if a["kind"] == entry["kind"] and a["name"] == entry["name"]]
                entry["suggested_asset_ids"] = [a["id"] for a in matches]
                entry["difference"] = "复用待确认" if len(matches) == 1 else "重名冲突" if matches else "新增"
            payload["message"] = "候选已生成，请确认身份、造型与原文出处"
            save("awaiting_review")
        except Exception as err:
            try:
                save("failed", str(err))
            except ValueError:
                pass

    @classmethod
    def action(cls, project_id, doc_id, jid, body, user_id):
        with cls.lock, transaction_cursor() as cursor:
            cursor.execute("SELECT * FROM ai_project_documents WHERE id=%s AND project_id=%s FOR UPDATE", (doc_id, project_id))
            doc = cursor.fetchone()
            if not doc:
                raise ValueError("剧本文档不存在")
            cursor.execute("SELECT * FROM ai_project_jobs WHERE id=%s AND project_id=%s FOR UPDATE", (jid, project_id))
            row = cursor.fetchone()
            if not row or row["job_type"] != cls.JOB_TYPE:
                raise ValueError("资产提取任务不存在")
            payload = json.loads(row["payload_json"])
            if payload["document_id"] != doc_id:
                raise ValueError("资产提取任务不属于此文档")
            if body.get("action") == "confirm" and row["status"] == "succeeded":
                return cls.get(project_id, doc_id)
            if body.get("revision") != digest(payload):
                raise ValueError("VERSION_CONFLICT: 候选已变化，请刷新")
            if body.get("action") == "cancel":
                if row["status"] == "succeeded":
                    raise ValueError("已确认清单不能取消")
                cursor.execute("UPDATE ai_project_jobs SET status='cancelled',updated_at=%s WHERE id=%s", (now_str(), jid))
            elif body.get("action") == "restore":
                analysis, source = source_state(doc)
                if body.get("expected_version") != (analysis.get("asset_manifest") or {}).get("version"):
                    raise ValueError("VERSION_CONFLICT: 清单已变化，请刷新")
                snapshot = next((v for v in analysis.get("asset_manifest_history", []) if v["version"] == body.get("version")), None)
                if not snapshot:
                    raise ValueError("清单历史版本不存在")
                restored = deepcopy(snapshot)
                restored.update(version=uuid.uuid4().hex, restored_from=snapshot["version"], confirmed_by=user_id, confirmed_at=now_str())
                if restored["source_fingerprint"] != source["fingerprint"]:
                    restored["status"] = "stale"
                analysis.setdefault("asset_manifest_history", []).append(analysis["asset_manifest"])
                analysis["asset_manifest"] = restored
                cursor.execute("UPDATE ai_project_documents SET analysis_json=%s,updated_at=%s WHERE id=%s AND project_id=%s", (json.dumps(analysis, ensure_ascii=False), now_str(), doc_id, project_id))
            elif body.get("action") == "confirm":
                if row["status"] != "awaiting_review":
                    raise ValueError("当前没有可确认的候选")
                analysis, source = source_state(doc)
                if source["fingerprint"] != payload["source"]["fingerprint"] or (analysis.get("asset_manifest") or {}).get("version") != payload.get("base_version"):
                    raise ValueError("SOURCE_CONFLICT: 剧本或资产清单已变化，请重新提取")
                choices = body.get("choices") or {}
                if set(choices) != {e["id"] for e in payload["entries"]}:
                    raise ValueError("请逐项确认资产复用或新建")
                if payload["issues"] and body.get("issues_confirmed") is not True:
                    raise ValueError("请核对并确认资产歧义")
                cursor.execute("SELECT * FROM ai_project_assets WHERE project_id=%s FOR UPDATE", (project_id,))
                assets = {a["id"]: a for a in cursor.fetchall()}
                entries = deepcopy(payload["entries"])
                for entry in entries:
                    choice = choices[entry["id"]]
                    if not isinstance(choice, dict) or set(choice) - {"asset_id", "look_id"}:
                        raise ValueError("资产映射字段无效")
                    previous_entry = next((e for e in (analysis.get("asset_manifest") or {}).get("entries", []) if e["id"] == entry["id"]), {})
                    aid = choice.get("asset_id")
                    if not aid and previous_entry.get("asset_id") in assets:
                        aid = previous_entry["asset_id"]
                    if aid:
                        if aid not in assets or assets[aid]["kind"] != entry["kind"]:
                            raise ValueError("UNKNOWN_ASSET: 所选资产不存在或类型不符")
                    else:
                        # Repeated identities/eras share the asset explicitly within this transaction.
                        matching = [e for e in entries if e is not entry and e.get("asset_id") and e["kind"] == entry["kind"] and e["identity"] == entry["identity"]]
                        aid = matching[0]["asset_id"] if matching else "ast-" + uuid.uuid4().hex[:12]
                        if aid not in assets:
                            cursor.execute("INSERT INTO ai_project_assets (id,project_id,kind,name,description,extra_json,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                           (aid, project_id, entry["kind"], entry["name"], "未明确的外观请在资产库补充", "{}", now_str(), now_str()))
                            assets[aid] = {"id": aid, "kind": entry["kind"], "extra_json": "{}"}
                    entry["asset_id"] = aid
                    if entry["kind"] == "character":
                        extra = json.loads(assets[aid].get("extra_json") or "{}")
                        looks = extra.setdefault("identities", [])
                        lid = choice.get("look_id") or (previous_entry.get("look_id") if previous_entry.get("asset_id") == aid else None)
                        if lid and not any(l.get("id") == lid for l in looks):
                            raise ValueError("UNKNOWN_LOOK: 所选造型不属于该角色")
                        if not lid:
                            known = next((l for l in looks if l.get("manifest_entry_id") == entry["id"]), None)
                            lid = known["id"] if known else "look-" + uuid.uuid4().hex[:12]
                            if not known:
                                looks.append({"id": lid, "name": entry["name"] + " · " + str(entry.get("era") or "未明确"), "description": str(entry.get("era") or "未明确"), "manifest_entry_id": entry["id"], "image_url": ""})
                                cursor.execute("UPDATE ai_project_assets SET extra_json=%s,updated_at=%s WHERE id=%s AND project_id=%s", (json.dumps(extra, ensure_ascii=False), now_str(), aid, project_id))
                                assets[aid]["extra_json"] = json.dumps(extra, ensure_ascii=False)
                        entry["look_id"] = lid
                previous = analysis.get("asset_manifest")
                if previous:
                    analysis.setdefault("asset_manifest_history", []).append(previous)
                analysis["asset_manifest"] = {"schema_version": 1, "version": uuid.uuid4().hex,
                    "source_fingerprint": source["fingerprint"], "source_revision": source["revision"], "status": "confirmed",
                    "entries": entries, "coverage": payload["coverage"], "job_id": jid, "confirmed_by": user_id, "confirmed_at": now_str()}
                cursor.execute("UPDATE ai_project_documents SET analysis_json=%s,updated_at=%s WHERE id=%s AND project_id=%s", (json.dumps(analysis, ensure_ascii=False), now_str(), doc_id, project_id))
                cursor.execute("UPDATE ai_project_jobs SET status='succeeded',progress=100,updated_at=%s WHERE id=%s", (now_str(), jid))
            else:
                raise ValueError("未知资产清单操作；失败后可重新提取")
        return cls.get(project_id, doc_id)

    @classmethod
    def recover(cls):
        rows = query_all("SELECT id,payload_json FROM ai_project_jobs WHERE job_type=%s AND status IN ('running','queued')", (cls.JOB_TYPE,))
        for row in rows:
            if not owner_alive(json.loads(row["payload_json"]).get("owner")):
                execute_sql("UPDATE ai_project_jobs SET status='failed',error_message=%s WHERE id=%s AND status IN ('running','queued') AND payload_json=%s", ("服务重启，提取证据已保留，请重新提取", row["id"], row["payload_json"]))
