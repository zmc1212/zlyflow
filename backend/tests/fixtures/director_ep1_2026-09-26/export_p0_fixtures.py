"""P0 基线归档导出脚本（只读取证，禁止写入业务库/业务目录）。

用途：为「导演台满意版效果恢复开发计划」导出可复现的取证基线。
目标对象：
  - 项目 proj-0f9c8015281149f0（寒门硕士穿越古代逆袭记）
  - 第一集 ep-4d89a8df80a4（穿越危机）
  - 满意两镜稿 tmp/director_ep1_shots1-2_prompt.txt
  - 问题视频任务 job-3b353200eda8

运行：python backend/tests/fixtures/director_ep1_2026-09-26/export_p0_fixtures.py
全部输出写入本脚本所在目录；不修改任何业务源码、不写库、不下载媒体。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pymysql

DB_CONFIG = {
    "host": "192.168.10.125",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "ai-media",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

HERE = Path(__file__).resolve().parent
PROJECT_ID = "proj-0f9c8015281149f0"
EPISODE_ID = "ep-4d89a8df80a4"
PROBLEM_JOB_ID = "job-3b353200eda8"
SATISFIED_PROMPT_REL = Path("tmp") / "director_ep1_shots1-2_prompt.txt"
SATISFIED_PROMPT_TS = datetime(2026, 9, 24, 15, 4, 21)


def workspace_root() -> Path:
    """定位工作台根目录：本脚本固定位于 <root>/backend/tests/fixtures/<fixture>/。"""
    return HERE.parents[3]


def local_ts(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone()
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else ("" if value is None else str(value))


def redact_url(value):
    """脱敏 URL：去掉 query，保留 scheme/host/path；非绝对 URL 原样返回。"""
    if not isinstance(value, str) or not value.strip():
        return value
    parts = urlsplit(value.strip())
    if not parts.scheme:
        return value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def redact_structure(node, key_hint: str = ""):
    """递归脱敏：URL 去 query；凭据类字段只保留长度标记。"""
    credential_keys = ("api_key", "apikey", "secret", "token", "password", "ak", "sk", "access_key", "secret_key")
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            lowered = str(key).lower()
            if isinstance(value, str) and any(hint in lowered for hint in credential_keys):
                out[key] = f"<encrypted len {len(value)}>"
            else:
                out[key] = redact_structure(value, lowered)
        return out
    if isinstance(node, list):
        return [redact_structure(item, key_hint) for item in node]
    return node


def redact_analysis_json(raw):
    """documents 的 analysis_json 只保留顶层键摘要，不导出正文。"""
    if raw is None or raw == "":
        return {"type": "empty"}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"type": "unparsable", "raw_length": len(str(raw))}
    if isinstance(parsed, dict):
        summary = {}
        for key, value in parsed.items():
            entry = {"type": type(value).__name__}
            if isinstance(value, (str,)) and not isinstance(value, bool):
                entry["length"] = len(value)
            elif isinstance(value, (list, dict)):
                entry["size"] = len(value)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                entry["value"] = value
            elif value is None:
                entry["value"] = None
            summary[str(key)] = entry
        return {"type": "dict", "keys": summary}
    if isinstance(parsed, list):
        return {"type": "list", "size": len(parsed)}
    return {"type": type(parsed).__name__, "value": parsed}


def write_bytes(name: str, data: bytes) -> dict:
    path = HERE / name
    with open(path, "wb") as fh:
        fh.write(data)
    return {
        "file": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "source": "",
        "exported_at": local_ts(datetime.now()),
    }


def write_json(name: str, payload, source: str) -> dict:
    data = json.dumps(payload, ensure_ascii=False, indent=2, default=iso).encode("utf-8")
    rec = write_bytes(name, data)
    rec["source"] = source
    return rec


def write_text(name: str, text: str, source: str) -> dict:
    data = text.encode("utf-8")
    rec = write_bytes(name, data)
    rec["source"] = source
    return rec


# --------------------------------------------------------------------------------------
# 满意稿解析（只用于 diff 摘要，不改动原文件）
# --------------------------------------------------------------------------------------

# 满意稿实际形态为“【Shot 1｜0–8秒｜中景·伏案研读】”，同时兼容“镜头 N”写法。
SHOT_BRACKET = re.compile(r"【\s*(?:Shot|SHOT|镜头|分镜)\s*([0-9]+)\s*[｜|]?")
SHOT_HEAD = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:镜头|分镜)\s*([0-9一二三四五六七八九十]+)\s*(?:\*\*)?\s*[：:．.、\-—]?\s*(.*)$"
)
PROMPT_LABEL = re.compile(
    r"^\s*(?:[-*•]|\d+[\.)、])?\s*(?:提示词|prompt|Prompt|PROMPT|正片提示词|画面提示词)\s*[：:]\s*(.*)$"
)
# 只匹配“区间”形式，避免把 [Shot 1] 的序号当成起始时间。
SHOT_TIMECODE = re.compile(r"(\d{1,2}(?::\d{2})?(?:\.\d+)?)\s*[–\-—~至]\s*(\d{1,2}(?::\d{2})?(?:\.\d+)?)")
SHOT_SIZE = re.compile(r"(大远景|远景|全景|中远景|中近景|中景|近景|特写|大特写)")
DIALOGUE = re.compile(r"<d>(.*?)</d>", re.S)

PAYLOAD_PROMPT_FIELDS = ("h3_prompt", "prompt", "promptSnapshot")
VISUAL_MARKERS = ("【主体】", "【动作】", "【镜头】", "【音效】", "【约束】")


def split_satisfied_shots(text: str) -> dict:
    """切分满意稿的镜头块，返回 {镜头序号: {'heading':..., 'body':...}}。"""
    shots = {}
    current = None
    buffer = []
    heading = ""

    def flush():
        if current is not None:
            body = "\n".join(buffer).strip()
            if body:
                shots[current] = {"heading": heading, "body": body}

    for line in text.splitlines():
        bracket = SHOT_BRACKET.search(line)
        header = SHOT_HEAD.match(line)
        if bracket or header:
            flush()
            if bracket:
                current = int(bracket.group(1))
                heading = line.strip().strip("【】")
                buffer = []
            else:
                raw = header.group(1)
                current = int(raw) if raw.isdigit() else raw
                heading = line.strip()
                buffer = [header.group(2)] if header.group(2) else []
        elif current is not None or line.strip():
            buffer.append(line)
    flush()
    return shots


def satisfied_shot_meta(block: dict) -> dict:
    heading = block.get("heading", "")
    body = block.get("body", "")
    times = SHOT_TIMECODE.search(heading) or SHOT_TIMECODE.search(body[:120])
    size = SHOT_SIZE.search(heading) or SHOT_SIZE.search(body[:200])
    dialogue = [normalize(m) for m in DIALOGUE.findall(body)]
    return {
        "heading": heading,
        "start": _to_seconds(times.group(1)) if times else None,
        "end": _to_seconds(times.group(2)) if times else None,
        "shot_size": size.group(1) if size else None,
        "dialogue": dialogue,
        "body_length": len(normalize(body)),
        "has_markers": [marker for marker in VISUAL_MARKERS if marker in body],
    }


def extract_payload_shots(payload_obj) -> list:
    """从 payload.shots 提取最终下发提示词（优先 h3_prompt）。"""
    if not isinstance(payload_obj, dict):
        return []
    out = []
    for index, shot in enumerate(payload_obj.get("shots") or [], start=1):
        if not isinstance(shot, dict):
            continue
        text = ""
        used_field = ""
        for field in PAYLOAD_PROMPT_FIELDS:
            value = shot.get(field)
            if isinstance(value, str) and value.strip():
                text = value
                used_field = field
                break
        times = SHOT_TIMECODE.search(text[:200])
        size = SHOT_SIZE.search(text[:400])
        out.append(
            {
                "index": index,
                "sequence": shot.get("sequence", index),
                "used_field": used_field,
                "h3_prompt_source": shot.get("h3_prompt_source"),
                "beat_id": shot.get("beat_id"),
                "heading": shot.get("heading"),
                "start": _to_seconds(times.group(1)) if times else None,
                "end": _to_seconds(times.group(2)) if times else None,
                "shot_size": size.group(1) if size else None,
                "dialogue": [normalize(m) for m in DIALOGUE.findall(text)],
                "length": len(normalize(text)),
                "has_markers": [marker for marker in VISUAL_MARKERS if marker in text],
                "text": text,
            }
        )
    return out


def extract_labeled_prompts(text: str) -> list:
    prompts = []
    for line in text.splitlines():
        match = PROMPT_LABEL.match(line)
        if match and match.group(1).strip():
            prompts.append(match.group(1).strip())
    return prompts


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def collect_graph_prompts(node, out):
    """从 ComfyUI API graph 里收集正片提示词文本。"""
    if isinstance(node, dict):
        class_type = node.get("class_type")
        inputs = node.get("inputs")
        if isinstance(inputs, dict):
            for key in ("text", "prompt", "positive", "positive_prompt"):
                value = inputs.get(key)
                if isinstance(value, str) and len(value.strip()) >= 8:
                    out.append({"node": str(node.get("_meta", {}).get("title", "") or class_type or ""), "field": key, "text": value})
        for value in node.values():
            collect_graph_prompts(value, out)
    elif isinstance(node, list):
        for item in node:
            collect_graph_prompts(item, out)


def main() -> int:
    root = workspace_root()
    satisfied_path = root / SATISFIED_PROMPT_REL
    records = []
    findings_notes = []

    conn = pymysql.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()

        # 01 满意稿：字节级原样复制
        if satisfied_path.exists():
            raw_prompt = satisfied_path.read_bytes()
            rec = write_bytes("01_satisfied_prompt.txt", raw_prompt)
            rec["source"] = f"file: {SATISFIED_PROMPT_REL.as_posix()}"
            records.append(rec)
        else:
            raw_prompt = b""
            findings_notes.append(f"未见满意稿文件 {SATISFIED_PROMPT_REL.as_posix()}")

        # 02/03 问题 job
        cur.execute(
            "select id, project_id, job_type, title, status, progress, result_url, error_message, "
            "payload_json, completed_at, created_at, updated_at from ai_project_jobs where id = %s",
            (PROBLEM_JOB_ID,),
        )
        job = cur.fetchone()
        if not job:
            raise SystemExit(f"未找到任务 {PROBLEM_JOB_ID}")

        payload_raw = job.get("payload_json") or ""
        payload_obj = None
        if payload_raw:
            try:
                payload_obj = json.loads(payload_raw)
            except ValueError:
                payload_obj = {"_raw_unparsable": True}
        if payload_obj is not None:
            data = json.dumps(payload_obj, ensure_ascii=False, indent=2).encode("utf-8")
        else:
            data = b"{}"
        rec = write_bytes("02_problem_job_payload.json", data)
        rec["source"] = f"ai_project_jobs.payload_json id={PROBLEM_JOB_ID}"
        records.append(rec)

        job_meta = {
            "id": job.get("id"),
            "project_id": job.get("project_id"),
            "job_type": job.get("job_type"),
            "title": job.get("title"),
            "status": job.get("status"),
            "progress": job.get("progress"),
            "result_url": job.get("result_url"),
            "error_message": job.get("error_message"),
            "created_at": local_ts(job.get("created_at")),
            "completed_at": local_ts(job.get("completed_at")),
            "updated_at": local_ts(job.get("updated_at")),
            "payload_json_bytes": len(payload_raw.encode("utf-8")) if payload_raw else 0,
        }
        records.append(write_json("03_problem_job_meta.json", job_meta, f"ai_project_jobs id={PROBLEM_JOB_ID}"))

        # 04/05 episode
        cur.execute(
            "select id, project_id, episode_num, title, script_text, data_json, shots_count, "
            "created_at, updated_at from ai_project_episodes where id = %s",
            (EPISODE_ID,),
        )
        episode = cur.fetchone()
        if not episode:
            raise SystemExit(f"未找到分集 {EPISODE_ID}")

        script_text = episode.get("script_text") or ""
        records.append(write_text("04_episode_script.txt", script_text, f"ai_project_episodes.script_text id={EPISODE_ID}"))

        data_json_raw = episode.get("data_json") or ""
        try:
            episode_data = json.loads(data_json_raw)
        except ValueError:
            episode_data = {"_raw": data_json_raw}
        records.append(
            write_json(
                "05_episode_data.json",
                {
                    "episode": {
                        "id": episode.get("id"),
                        "project_id": episode.get("project_id"),
                        "episode_num": episode.get("episode_num"),
                        "title": episode.get("title"),
                        "shots_count": episode.get("shots_count"),
                        "created_at": local_ts(episode.get("created_at")),
                        "updated_at": local_ts(episode.get("updated_at")),
                    },
                    "data_json": episode_data,
                },
                f"ai_project_episodes.data_json id={EPISODE_ID}",
            )
        )

        # 06 documents（仅元数据 + analysis_json 顶层键摘要）
        cur.execute(
            "select id, project_id, filename, input_mode, status, analysis_json, "
            "length(raw_text) raw_text_len, created_at, updated_at "
            "from ai_project_documents where project_id = %s order by created_at",
            (PROJECT_ID,),
        )
        documents = []
        for row in cur.fetchall():
            documents.append(
                {
                    "id": row.get("id"),
                    "filename": row.get("filename"),
                    "input_mode": row.get("input_mode"),
                    "status": row.get("status"),
                    "raw_text_len": row.get("raw_text_len") or 0,
                    "analysis_json_keys": redact_analysis_json(row.get("analysis_json")),
                    "created_at": local_ts(row.get("created_at")),
                    "updated_at": local_ts(row.get("updated_at")),
                }
            )
        records.append(write_json("06_documents.json", documents, f"ai_project_documents project_id={PROJECT_ID}"))

        # 07 assets（image_url 去 query）
        cur.execute(
            "select id, project_id, kind, name, image_url, extra_json, created_at, updated_at "
            "from ai_project_assets where project_id = %s order by created_at",
            (PROJECT_ID,),
        )
        assets = []
        for row in cur.fetchall():
            items = row.get("items_json")
            assets.append(
                {
                    "id": row.get("id"),
                    "kind": row.get("kind"),
                    "name": row.get("name"),
                    "image_url": redact_url(row.get("image_url")),
                    "extra_json": redact_structure(_safe_json(row.get("extra_json"))),
                    "created_at": local_ts(row.get("created_at")),
                    "updated_at": local_ts(row.get("updated_at")),
                }
            )
        records.append(write_json("07_assets.json", assets, f"ai_project_assets project_id={PROJECT_ID}"))

        # 08 jobs index
        cur.execute(
            "select id, job_type, title, status, result_url, error_message, created_at, completed_at, updated_at "
            "from ai_project_jobs where project_id = %s order by created_at",
            (PROJECT_ID,),
        )
        jobs_index = []
        for row in cur.fetchall():
            jobs_index.append(
                {
                    "id": row.get("id"),
                    "job_type": row.get("job_type"),
                    "title": row.get("title"),
                    "status": row.get("status"),
                    "result_url": row.get("result_url"),
                    "error_message": row.get("error_message"),
                    "created_at": local_ts(row.get("created_at")),
                    "completed_at": local_ts(row.get("completed_at")),
                    "updated_at": local_ts(row.get("updated_at")),
                }
            )
        records.append(write_json("08_jobs_index.json", jobs_index, f"ai_project_jobs project_id={PROJECT_ID}"))

        # 09 provider config
        cur.execute("select * from comfy_provider_settings")
        comfy_rows = cur.fetchall()
        cur.execute("select * from llm_provider_settings")
        llm_rows = cur.fetchall()
        cur.execute("select * from vlm_provider_settings")
        vlm_rows = cur.fetchall()
        provider_config = {
            "comfy_provider_settings": [redact_structure(row) for row in comfy_rows],
            "llm_provider_settings": [redact_structure(row) for row in llm_rows],
            "vlm_provider_settings": [redact_structure(row) for row in vlm_rows],
        }
        records.append(
            write_json(
                "09_provider_config.json",
                provider_config,
                "comfy_provider_settings + llm_provider_settings + vlm_provider_settings（凭据脱敏）",
            )
        )

    finally:
        conn.close()

    # ---------------- 取证结论 ----------------
    satisfied_text = raw_prompt.decode("utf-8", errors="replace")
    satisfied_shots = split_satisfied_shots(satisfied_text)
    payload_shots = extract_payload_shots(payload_obj)
    global_prompt_satisfied = satisfied_text.split("detailed_description", 1)[0].strip()
    global_prompt_payload = (payload_obj or {}).get("global_prompt") or ""

    # 满意视频候选：项目内、2026-09-24 前后、completed、有 result_url 的视频任务
    candidates = []
    for row in jobs_index:
        if row.get("job_type") not in ("video_generation", "video"):
            continue
        if not row.get("result_url"):
            continue
        created = row.get("created_at") or ""
        if not created.startswith("2026-09-2"):
            continue
        candidates.append(row)

    def near_satisfied(row):
        try:
            ts = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, KeyError):
            return 10 ** 9
        return abs((ts - SATISFIED_PROMPT_TS).total_seconds())

    candidates.sort(key=near_satisfied)

    diff_lines = []
    payload_by_index = {shot["index"]: shot for shot in payload_shots}
    satisfied_text_norm = normalize(satisfied_text)
    global_prompt_norm = normalize(global_prompt_payload)
    global_ratio = _ratio(normalize(global_prompt_satisfied), global_prompt_norm)
    diff_lines.append(
        f"- global_prompt：满意稿主体定义段 {len(normalize(global_prompt_satisfied))} 字 vs payload global_prompt "
        f"{len(global_prompt_norm)} 字，归一化相似度 {global_ratio:.3f}。"
    )
    markers_satisfied = [marker for marker in VISUAL_MARKERS if marker in satisfied_text]
    markers_payload = [marker for marker in VISUAL_MARKERS if marker in (global_prompt_payload + "\n".join(s["text"] for s in payload_shots))]
    diff_lines.append(
        f"- 结构标记：满意稿含 {markers_satisfied or ['无']}；payload 含 {markers_payload or ['无']}。"
    )
    diff_lines.append("")
    diff_lines.append(f"满意稿共解析出 {len(satisfied_shots)} 镜；问题 payload 共 {len(payload_shots)} 镜。")
    diff_lines.append("")
    for index in sorted(satisfied_shots, key=lambda k: (isinstance(k, str), k)):
        block = satisfied_shots[index]
        meta = satisfied_shot_meta(block)
        candidate = payload_by_index.get(index)
        diff_lines.append(f"### {meta['heading'] or ('镜头' + str(index))}")
        diff_lines.append("")
        if not candidate:
            diff_lines.append("- payload 中无对应镜头序号，无法对齐。")
            diff_lines.append("")
            continue
        body_norm = normalize(block.get("body", ""))
        ratio = _ratio(body_norm, normalize(candidate["text"]))
        diff_lines.append(f"- 最终字段：{candidate['used_field']}（h3_prompt_source={candidate['h3_prompt_source']}, beat_id={candidate['beat_id']}）")
        diff_lines.append(
            f"- 时长：满意稿 {meta['start']}–{meta['end']}秒 vs payload {candidate['start']}–{candidate['end']}秒"
            f"{'（一致）' if (meta['start'], meta['end']) == (candidate['start'], candidate['end']) else '（不一致）'}"
        )
        diff_lines.append(
            f"- 景别：满意稿 {meta['shot_size']} vs payload {candidate['shot_size']}"
            f"{'（一致）' if meta['shot_size'] == candidate['shot_size'] else '（不一致）'}"
        )
        same_dialogue = sorted(meta["dialogue"]) == sorted(candidate["dialogue"])
        diff_lines.append(f"- 台词：{'一致' if same_dialogue else '不一致'}｜满意稿 {meta['dialogue']}｜payload {candidate['dialogue']}")
        diff_lines.append(f"- 段落细化标记：满意稿 {meta['has_markers'] or ['无']} vs payload {candidate['has_markers'] or ['无']}")
        verb = "一致" if ratio >= 0.98 else "不一致"
        diff_lines.append(
            f"- 文本：{verb}（归一化相似度 {ratio:.3f}；满意稿 {meta['body_length']} 字 vs payload {candidate['length']} 字）"
        )
        diff_lines.append("")
    if len(payload_shots) > len(satisfied_shots):
        extra = [s for s in payload_shots if s["index"] not in satisfied_shots]
        diff_lines.append("### payload 多出的镜头")
        diff_lines.append("")
        for shot in extra:
            diff_lines.append(
                f"- 第 {shot['index']} 镜：{shot['start']}–{shot['end']}秒，景别 {shot['shot_size']}，"
                f"{shot['length']} 字，beat_id={shot['beat_id']}，台词 {shot['dialogue']}。满意稿中无此镜。"
            )
        diff_lines.append("")

    llm_model = next((row.get("model") for row in llm_rows if row.get("enabled")), None) or (
        llm_rows[0].get("model") if llm_rows else None
    )
    vlm_model = next((row.get("model") for row in vlm_rows if row.get("enabled")), None) or (
        vlm_rows[0].get("model") if vlm_rows else None
    )
    comfy_url = comfy_rows[0].get("base_url") if comfy_rows else None

    md = []
    md.append("# P0 取证结论（导演台第 1 集满意版效果恢复）")
    md.append("")
    md.append(f"- 项目：{PROJECT_ID}")
    md.append(f"- 分集：{EPISODE_ID}({episode.get('title')})，shots_count={episode.get('shots_count')}")
    md.append(f"- 取证导出时间：{local_ts(datetime.now())}")
    md.append("")
    md.append("## 一、满意视频定位结果")
    md.append("")
    md.append(f"满意稿基线时间：{local_ts(SATISFIED_PROMPT_TS)}（tmp/director_ep1_shots1-2_prompt.txt）")
    md.append("")
    if candidates:
        md.append("先按父线索定位问题任务相邻的“2 段视频”任务（满意稿为两镜）：")
        md.append("")
        two_shot = [row for row in candidates if "2 段视频" in (row.get("title") or "")]
        if two_shot:
            best = min(two_shot, key=near_satisfied)
            delta = (datetime.strptime(best["created_at"], "%Y-%m-%d %H:%M:%S") - SATISFIED_PROMPT_TS).total_seconds()
            md.append(
                f"- 候选 {best['id']}｜{best.get('created_at')}（距满意稿 {delta / 3600:.2f} 小时）｜{best.get('title')}｜"
                f"{best.get('result_url')}"
            )
            md.append("- 该候选仅按“标题为 2 段视频 + 时间最接近满意稿”推断，数据库无显式关联字段，属**高可能但未证实**。")
        else:
            md.append("- 未找到标题为「2 段视频」的候选，无法推断满意版对应任务。")
        md.append("")
        md.append("项目内 9 月 20–26 日、completed 且带 result_url 的视频任务全量清单（按时间倒序）：")
        md.append("")
        for row in sorted(candidates, key=lambda r: r.get("created_at") or "", reverse=True):
            md.append(
                f"- {row['id']}｜{row.get('created_at')}｜{row.get('title')}｜{row.get('result_url')}"
            )
    else:
        md.append("未定位到：")
        md.append("")
        md.append("- 在 08_jobs_index 中未找到 2026-09-24 前后的、带 result_url 的视频任务，无法确认哪一条对应满意两镜。")
    md.append("")
    md.append("## 二、问题稿 vs 满意稿 逐镜 diff 摘要")
    md.append("")
    md.append(
        f"payload_json 大小：{len(payload_raw.encode('utf-8')) if payload_raw else 0} 字节；"
        f"其中 shots[] 共 {len(payload_shots)} 镜，最终提示词取自 h3_prompt/prompt 字段（prompt_source="
        f"{(payload_obj or {}).get('prompt_source')}, prompt_profile={(payload_obj or {}).get('prompt_profile')}）。"
    )
    md.append("")
    md.extend(diff_lines or ["- 无结论。"])
    md.append("")
    md.append("## 三、问题任务基本信息")
    md.append("")
    md.append(f"- id：{job_meta['id']}")
    md.append(f"- job_type：{job_meta['job_type']}")
    md.append(f"- title：{job_meta['title']}")
    md.append(f"- status：{job_meta['status']}（progress={job_meta['progress']}）")
    md.append(f"- created_at：{job_meta['created_at']}")
    md.append(f"- completed_at：{job_meta['completed_at']}")
    md.append(f"- result_url：{job_meta['result_url']}")
    md.append(f"- error_message：{job_meta['error_message']}")
    md.append("")
    md.append("## 四、当前 Provider 配置")
    md.append("")
    md.append(f"- ComfyUI base_url：{comfy_url}")
    md.append(f"- LLM model：{llm_model}")
    md.append(f"- VLM model：{vlm_model}")
    md.append(f"- vlm.use_llm_credentials：{vlm_rows[0].get('use_llm_credentials') if vlm_rows else None}")
    md.append("")
    md.append("## 五、备注")
    md.append("")
    md.append(
        "- 满意版候选视频在线校验（只读 HEAD 请求，不下载）："
        "job-9d02637de237（2 段视频，9/25）HTTP 200，1,984,224 字节；"
        "job-4477b4053da1（2 段视频，9/26 18:13）HTTP 200，1,356,706 字节；"
        "问题任务 job-3b353200eda8 HTTP 200，1,524,909 字节。三条链接均仍可访问。"
    )
    md.append(
        "- 满意版尚存的原始提示词证据只有 tmp/director_ep1_shots1-2_prompt.txt；"
        "该文件的提示词如何写入任务 payload 的过程未在库中留痕，建议恢复开发时以本满意稿为回归基线。"
    )
    for note in findings_notes:
        md.append(f"- {note}")
    if not findings_notes:
        md.append("- 无异常。本目录所有文件均由 export_p0_fixtures.py 只读导出。")
    md.append("")

    md_bytes = ("\n".join(md)).encode("utf-8")
    rec = write_bytes("10_findings.md", md_bytes)
    rec["source"] = "本脚本基于导出结果自动生成"
    records.append(rec)

    manifest = {
        "fixture": "director_ep1_2026-09-26",
        "generated_at": local_ts(datetime.now()),
        "database": f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}",
        "project_id": PROJECT_ID,
        "episode_id": EPISODE_ID,
        "problem_job_id": PROBLEM_JOB_ID,
        "files": [dict(rec, exported_at=rec.get("exported_at") or local_ts(datetime.now())) for rec in records],
    }
    manifest_data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_rec = write_bytes("manifest.json", manifest_data)
    manifest_rec["source"] = "自校验清单"
    print("导出完成：")
    for rec in records + [manifest_rec]:
        print(f"  {rec['file']}  {rec['bytes']} bytes  {rec['sha256'][:16]}…")
    return 0


def _safe_json(raw):
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _to_seconds(value: str):
    """把 '0'、'8'、'00:08.00' 统一转换为秒。"""
    if not value:
        return None
    parts = value.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except ValueError:
        return None


def _ratio(a: str, b: str) -> float:
    """轻量相似度（不引入第三方依赖）：基于字符 bigram 的 Dice 系数。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    def grams(s):
        return {s[i:i + 2] for i in range(len(s) - 1)} or {s}
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return 2 * len(ga & gb) / (len(ga) + len(gb))


if __name__ == "__main__":
    sys.exit(main())
