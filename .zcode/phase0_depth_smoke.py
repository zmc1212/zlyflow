# -*- coding: utf-8 -*-
"""DA3 视频深度提取烟囱测试。"""
import json
import time
import urllib.request

COMFY = "http://127.0.0.1:8188"

workflow = {
    "1": {"inputs": {"video": "test_clip.mp4", "force_rate": 16, "custom_width": 0, "custom_height": 0,
                     "frame_load_cap": 33, "skip_first_frames": 0, "select_every_nth": 1},
          "class_type": "VHS_LoadVideo", "_meta": {"title": "读取参考视频"}},
    "2": {"inputs": {"model_name": "depth_anything_3_mono_large.safetensors", "weight_dtype": "default"},
          "class_type": "LoadDA3Model", "_meta": {"title": "加载 DA3"}},
    "3": {"inputs": {"da3_model": ["2", 0], "image": ["1", 0], "resolution": 504,
                     "resize_method": "lower_bound_resize", "mode": "mono"},
          "class_type": "DA3Inference", "_meta": {"title": "深度推理"}},
    "4": {"inputs": {"da3_geometry": ["3", 0],
                     "output": "depth", "output.normalization": "v2_style", "output.apply_sky_clip": False},
          "class_type": "DA3Render", "_meta": {"title": "渲染深度图"}},
    "5": {"inputs": {"images": ["4", 0], "frame_rate": 16, "loop_count": 0,
                     "filename_prefix": "video/zly_depth_smoke", "format": "video/h264-mp4",
                     "pix_fmt": "yuv420p", "crf": 20, "save_metadata": True, "save_output": True,
                     "pingpong": False},
          "class_type": "VHS_VideoCombine", "_meta": {"title": "保存深度视频"}},
}


def post(path, payload):
    req = urllib.request.Request(COMFY + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(COMFY + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


result = post("/prompt", {"prompt": workflow, "client_id": "zly_phase0_depth"})
prompt_id = result["prompt_id"]
print("已提交 prompt_id:", prompt_id)

start = time.time()
while True:
    time.sleep(5)
    history = get(f"/history/{prompt_id}")
    if prompt_id in history:
        entry = history[prompt_id]
        status = entry.get("status", {})
        print(f"[{int(time.time()-start)}s] status={status.get('status_str')}")
        if status.get("status_str") == "error":
            msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
            print("执行错误:", json.dumps(msgs, ensure_ascii=False)[:1500])
        for node_id, out in entry.get("outputs", {}).items():
            print("输出节点", node_id, ":", json.dumps(out, ensure_ascii=False)[:400])
        break
    queue = get("/queue")
    print(f"[{int(time.time()-start)}s] running={len(queue.get('queue_running', []))} pending={len(queue.get('queue_pending', []))}")
