# -*- coding: utf-8 -*-
"""用真实 wan_vace_depth_workflow builder 跑 VACE 复刻烟囱测试。"""
import json
import secrets
import sys
import time
import urllib.request

sys.path.insert(0, r"D:\zlyun\Toonflow\本地视频工作台\backend")

from app.wan_vace_depth_workflow import VACE_OUTPUT_NODE, build_vace_depth_workflow

COMFY = "http://127.0.0.1:8188"

workflow = build_vace_depth_workflow(
    "test_clip.mp4",
    ["first_frame.png"],
    "一只橘色的卡通猫在明亮的房间里跳来跳去，鲜艳可爱的动画风格",
    width=832,
    height=480,
    length=17,
    vace_strength=1.0,
    steps=4,
    seed=secrets.randbits(31),
)


def post(path, payload):
    req = urllib.request.Request(COMFY + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(COMFY + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


result = post("/prompt", {"prompt": workflow, "client_id": "zly_phase0_vace2"})
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
            print("执行错误:", json.dumps(msgs, ensure_ascii=False)[:1600])
        for node_id, out in entry.get("outputs", {}).items():
            print("输出节点", node_id, ":", json.dumps(out, ensure_ascii=False)[:300])
        break
    queue = get("/queue")
    print(f"[{int(time.time()-start)}s] running={len(queue.get('queue_running', []))} pending={len(queue.get('queue_pending', []))}")
