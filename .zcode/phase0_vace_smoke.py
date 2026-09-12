# -*- coding: utf-8 -*-
"""VACE 深度复刻图烟囱测试：提交并轮询到完成。"""
import json
import random
import time
import urllib.request

COMFY = "http://127.0.0.1:8188"

NEGATIVE = "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"

workflow = {
    "1": {"inputs": {"unet_name": "wan2.1_vace_1.3B.safetensors", "weight_dtype": "default"}, "class_type": "UNETLoader", "_meta": {"title": "加载 Wan VACE 模型"}},
    "2": {"inputs": {"model": ["1", 0], "shift": 16.0}, "class_type": "ModelSamplingSD3", "_meta": {"title": "Wan 采样配置"}},
    "3": {"inputs": {"clip_name": "umt5_xxl_enc_bf16.pth", "type": "wan", "device": "cpu"}, "class_type": "CLIPLoader", "_meta": {"title": "加载 UMT5 文本编码器"}},
    "4": {"inputs": {"text": "一只橘色的卡通猫在明亮的房间里跳来跳去，风格鲜艳可爱", "clip": ["3", 0]}, "class_type": "CLIPTextEncode", "_meta": {"title": "正向提示词"}},
    "5": {"inputs": {"text": NEGATIVE, "clip": ["3", 0]}, "class_type": "CLIPTextEncode", "_meta": {"title": "负向提示词"}},
    "6": {"inputs": {"vae_name": "wan_2.1_vae.pth"}, "class_type": "VAELoader", "_meta": {"title": "加载 Wan VAE"}},
    "7": {"inputs": {"image": "first_frame.png"}, "class_type": "LoadImage", "_meta": {"title": "原片首帧参考"}},
    "8": {"inputs": {"video": "test_clip.mp4", "force_rate": 16, "custom_width": 0, "custom_height": 0, "frame_load_cap": 17, "skip_first_frames": 0, "select_every_nth": 1}, "class_type": "VHS_LoadVideo", "_meta": {"title": "读取控制视频"}},
    "9": {"inputs": {"positive": ["4", 0], "negative": ["5", 0], "vae": ["6", 0], "width": 832, "height": 480, "length": 17, "batch_size": 1, "strength": 1.0, "reference_images": ["7", 0], "control_video": ["8", 0]}, "class_type": "WanVaceMultiReference", "_meta": {"title": "VACE 控制编码"}},
    "10": {"inputs": {"model": ["2", 0], "seed": random.randint(0, 2**31), "steps": 4, "cfg": 5.0, "sampler_name": "uni_pc", "scheduler": "simple", "positive": ["9", 0], "negative": ["9", 1], "latent_image": ["9", 2], "denoise": 1.0}, "class_type": "KSampler", "_meta": {"title": "采样"}},
    "11": {"inputs": {"samples": ["10", 0], "trim_amount": ["9", 3]}, "class_type": "TrimVideoLatent", "_meta": {"title": "移除参考帧"}},
    "12": {"inputs": {"samples": ["11", 0], "vae": ["6", 0]}, "class_type": "VAEDecode", "_meta": {"title": "解码"}},
    "13": {"inputs": {"images": ["12", 0], "fps": 16}, "class_type": "CreateVideo", "_meta": {"title": "创建视频"}},
    "14": {"inputs": {"video": ["13", 0], "filename_prefix": "video/zly_replication_smoke", "format": "mp4", "codec": "h264"}, "class_type": "SaveVideo", "_meta": {"title": "保存视频"}},
}


def post(path, payload):
    req = urllib.request.Request(
        COMFY + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(COMFY + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


result = post("/prompt", {"prompt": workflow, "client_id": "zly_phase0_smoke"})
prompt_id = result["prompt_id"]
print("已提交 prompt_id:", prompt_id)

start = time.time()
while True:
    time.sleep(5)
    history = get(f"/history/{prompt_id}")
    if prompt_id in history:
        entry = history[prompt_id]
        status = entry.get("status", {})
        print(f"[{int(time.time()-start)}s] status={status.get('status_str')} completed={status.get('completed')}")
        if status.get("completed") or status.get("status_str") in ("error", "failed"):
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                print("执行错误:", json.dumps(msgs, ensure_ascii=False)[:2000])
            outputs = entry.get("outputs", {})
            for node_id, out in outputs.items():
                print("输出节点", node_id, ":", json.dumps(out, ensure_ascii=False)[:400])
            break
    else:
        queue = get("/queue")
        running = len(queue.get("queue_running", []))
        pending = len(queue.get("queue_pending", []))
        print(f"[{int(time.time()-start)}s] 运行中 running={running} pending={pending}")
