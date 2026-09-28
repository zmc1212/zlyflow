"""Opt-in real A/B acceptance runner; never alters project prompts or adopted media.

python -m backend.tests.acceptance_ai_review --writing-job ID --video-job ID --output test-results/review-ab
An existing checkpoint resumes downloads/polling, never resubmits an acknowledged prompt.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from backend.app.media_studio.db import query_one
from backend.app.media_studio.provider_bridge import comfy_row
from backend.app.media_studio.services.workshop_ai_review import configuration, run_review
from backend.app.media_studio.services.workshop_direct_input import sha
from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient


def load_job(jid):
    row = query_one("SELECT payload_json FROM ai_project_jobs WHERE id=%s", (jid,))
    if not row:
        raise ValueError("任务不存在：" + jid)
    return json.loads(row["payload_json"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writing-job", required=True)
    parser.add_argument("--video-job", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--retry-review", action="store_true", help="显式重试失败审校，不重写原稿")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    folder = Path(args.output).resolve()
    if not folder.is_relative_to(root / "test-results"):
        raise ValueError("验收输出必须位于 test-results")
    folder.mkdir(parents=True, exist_ok=True)
    record = folder / "evidence.json"
    if record.exists():
        state = json.loads(record.read_text(encoding="utf-8"))
        if state["writing_job"] != args.writing_job or state["video_job"] != args.video_job:
            raise ValueError("输出目录属于其他对照")
    else:
        state = {"writing_job": args.writing_job, "video_job": args.video_job,
                 "writing": load_job(args.writing_job), "video": load_job(args.video_job),
                 "renders": {}, "media_verdict": "pending_human"}
    def save(message=""):
        record.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if message:
            print(message, flush=True)
    url = comfy_row()["base_url"].rstrip("/")
    video = state["video"]
    if url != video["comfy_base_url"].rstrip("/"):
        raise ValueError("实际 ComfyUI 与原始任务不同，禁止切换实例完成对照")
    state["actual_comfy_url"] = url
    comfy = ComfyVideoClient(url)
    comfy.ping()
    payload = state["writing"]
    gids = {s["director_part_id"] for s in video["shots"]}
    if len(gids) != 1:
        raise ValueError("本验收器每次只接受一个完整组")
    group = next(g for g in payload["base_plan"]["groups"] if g["id"] in gids)
    if [s["beat_id"] for s in video["shots"]] != group["beat_ids"]:
        raise ValueError("视频与第一稿镜头顺序不一致")
    if any(payload["candidates"][s["beat_id"]]["h3_prompt"] != s["h3_prompt"] for s in video["shots"]):
        raise ValueError("视频并非此冻结原稿的执行版本")
    if "review_config" not in payload:
        payload["review_config"] = configuration(payload["writing_author"])
    previous = payload.get("ai_reviews", {}).get(group["id"])
    if previous and previous.get("status") in {"failed", "cancelled", "running"} and not args.retry_review:
        raise ValueError("上次审校未成功；核实后使用 --retry-review 显式重试")
    run_review(payload, group, save)
    review = payload["ai_reviews"][group["id"]]
    save("审校状态：" + review["status"])
    if review["status"] != "revised" or not review.get("eligible"):
        print("没有可用且不同的审校稿，不提交无效 A/B。", flush=True)
        return
    original = deepcopy(video["workflow_request"])
    revised = deepcopy(original)
    nodes = [(key, node) for key, node in revised.items() if node["class_type"] == "MiniMaxH3Director"]
    if len(nodes) != 1:
        raise ValueError("无法唯一定位已保存的 H3 导演节点")
    node_id, node = nodes[0]
    inputs = node["inputs"]
    timeline = json.loads(inputs["timeline_data"])
    if len(timeline["segments"]) != len(group["beat_ids"]):
        raise ValueError("已保存执行 graph 与整组镜头数不一致")
    print('时间轴公共字段：' + ','.join(timeline['global']), flush=True)
    inputs["global_prompt"] = review["common_prompt"]
    # This node stores its shared prompt in both the widget and serialized timeline.
    if timeline["global"]["prompt"] != original[node_id]["inputs"]["global_prompt"]:
        raise ValueError("原始 graph 公共设定副本不一致")
    timeline["global"]["prompt"] = review["common_prompt"]
    for segment, bid in zip(timeline["segments"], group["beat_ids"]):
        segment["prompt"] = review["candidates"][bid]["h3_prompt"]
    workspace = timeline["batchWorkspaces"]["r2v"]
    workspace["globalCommon"]["prompt"] = review["common_prompt"]
    for segment, bid in zip(workspace["segments"], group["beat_ids"]):
        segment["prompt"] = review["candidates"][bid]["h3_prompt"]
    inputs["timeline_data"] = json.dumps(timeline, ensure_ascii=False)
    state["graphs"] = {"A": original, "B": revised}
    state["graph_sha256"] = {k: sha(json.dumps(v, sort_keys=True, ensure_ascii=False)) for k, v in state["graphs"].items()}
    state["changed_node"] = node_id
    save()
    for variant, graph in state["graphs"].items():
        result = state["renders"].setdefault(variant, {})
        if result.get("output"):
            target = folder / (variant + ".mp4")
            if not target.exists():
                target.write_bytes(comfy.download_output(result["output"]))
            continue
        if result.get("submitting") and not result.get("prompt_id"):
            raise ValueError("上次提交结果不确定，请核实远端队列，不能盲目重发")
        if not result.get("prompt_id"):
            result["submitting"] = True
            save("提交探索性对照 " + variant)
            submitted = comfy.submit(graph)
            result.update(submitted)
            save("已提交 " + variant + " " + result["prompt_id"])
        history, output = comfy.wait_for_result(result["prompt_id"])
        result["output"] = output
        save("远端完成 " + variant)
        (folder / (variant + ".mp4")).write_bytes(comfy.download_output(output))
    print("A/B 已完成，需人工盲评；结果未采纳到工程。", flush=True)


if __name__ == "__main__":
    main()
