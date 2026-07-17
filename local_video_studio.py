import copy
import json
import mimetypes
import os
import secrets
import threading
import time
from pathlib import Path

import gradio as gr
import requests
from starlette.responses import FileResponse as StarletteFileResponse


APP_DIR = Path(__file__).resolve().parent
RESULT_DIR = APP_DIR / "results"
RESULT_DIR.mkdir(exist_ok=True)

COMFY_URL = "http://127.0.0.1:8189"
WORKFLOW_DIR = Path(r"D:\zlyun\Toonflow\配置文件+工作流")
FLUX_WORKFLOW_PATH = WORKFLOW_DIR / "Flux2-Klein-三图参考.json"
LTX_WORKFLOW_PATH = WORKFLOW_DIR / "video_ltx2_3_i2v(new).json"
TEXT_TO_IMAGE_WORKFLOW_PATH = WORKFLOW_DIR / "Flux2-Klein-文生图.json"

FLUX_IMAGE_NODES = ("76", "164", "179")
FLUX_PROMPT_NODE = "108"
FLUX_SEED_NODE = "146"
FLUX_OUTPUT_NODE = "195"

LTX_IMAGE_NODE = "98"
LTX_PROMPT_NODE = "167:164"
LTX_SEED_NODES = ("167:135", "167:165")
LTX_OUTPUT_NODE = "75"

VACE_OUTPUT_NODE = "17"
VACE_WIDTH = 832
VACE_HEIGHT = 480
VACE_FRAMES = 81
VACE_FPS = 16

T2I_PROMPT_NODE = "2"
T2I_NEGATIVE_PROMPT_NODE = "3"


class HeadCompatibleFileResponse(StarletteFileResponse):
    """Avoid a Gradio/uvicorn HEAD response mismatch on local Windows builds.

    Gradio registers HEAD on its temporary upload-file endpoint.  With the
    bundled uvicorn+h11 versions, FileResponse advertises the GET body's
    Content-Length while correctly returning no body for HEAD; h11 then rejects
    that response.  Browsers use HEAD when validating image previews, so remove
    the body-length header only for HEAD requests.
    """

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "HEAD":
            # FileResponse normally creates these headers lazily in __call__.
            # Set the stat data first so it cannot add Content-Length again
            # after this compatibility adjustment.
            if self.stat_result is None:
                self.stat_result = os.stat(self.path)
                self.set_stat_headers(self.stat_result)
            if "content-length" in self.headers:
                del self.headers["content-length"]
        await super().__call__(scope, receive, send)


def install_gradio_upload_preview_fix() -> None:
    """Install the file-response compatibility shim before Blocks is created."""
    import gradio.routes

    gradio.routes.FileResponse = HeadCompatibleFileResponse
T2I_LATENT_NODE = "5"
T2I_SEED_NODE = "6"
T2I_OUTPUT_NODE = "8"
T2I_VAE_NODE = "4"
T2I_REFERENCE_IMAGE_NODE = "10"
T2I_REFERENCE_SCALE_NODE = "11"
T2I_REFERENCE_LATENT_NODE = "12"
T2I_REFERENCE_POSITIVE_NODE = "13"
T2I_REFERENCE_NEGATIVE_NODE = "14"

IMAGE_SIZES = {
    "横版 1280 x 720": (1280, 720),
    "方图 1024 x 1024": (1024, 1024),
    "竖版 720 x 1280": (720, 1280),
}

REQUEST_TIMEOUT_SECONDS = 1_800
GENERATION_LOCK = threading.Lock()


class ComfyError(RuntimeError):
    pass


def workflow_from(path: Path) -> dict:
    if not path.is_file():
        raise ComfyError(f"找不到工作流文件: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def random_seed() -> int:
    return secrets.randbelow(2**63 - 1)


def require_images(*images: str) -> None:
    if not all(images):
        raise ComfyError("请上传三张参考图后再生成。")


def upload_image(local_path: str, tag: str) -> str:
    source = Path(local_path)
    if not source.is_file():
        raise ComfyError(f"上传图像不存在: {source}")

    filename = f"{tag}_{int(time.time() * 1000)}_{secrets.token_hex(4)}{source.suffix.lower() or '.png'}"
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with source.open("rb") as file:
        response = requests.post(
            f"{COMFY_URL}/upload/image",
            data={"overwrite": "true"},
            files={"image": (filename, file, mime_type)},
            timeout=60,
        )
    if not response.ok:
        raise ComfyError(f"上传图像到 ComfyUI 失败: {response.text}")

    payload = response.json()
    returned_name = payload.get("name")
    if not returned_name:
        raise ComfyError(f"ComfyUI 上传接口未返回文件名: {payload}")
    subfolder = payload.get("subfolder", "")
    return f"{subfolder}/{returned_name}" if subfolder else returned_name


def submit(workflow: dict) -> str:
    client_id = f"local-video-studio-{secrets.token_hex(8)}"
    response = requests.post(
        f"{COMFY_URL}/prompt",
        json={"prompt": workflow, "client_id": client_id},
        timeout=60,
    )
    if not response.ok:
        raise ComfyError(f"ComfyUI 拒绝工作流: {response.text}")
    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        raise ComfyError("ComfyUI 未返回任务 ID。")
    return prompt_id


def get_error_message(record: dict) -> str:
    status = record.get("status", {})
    messages = status.get("messages", [])
    for message in messages:
        if isinstance(message, list) and message and message[0] == "execution_error":
            return str(message)
    return str(status) if status else "未知推理错误"


def wait_for_history(prompt_id: str) -> dict:
    started = time.monotonic()
    while time.monotonic() - started < REQUEST_TIMEOUT_SECONDS:
        response = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=30)
        if response.ok:
            record = response.json().get(prompt_id)
            if record:
                status = record.get("status", {}).get("status_str")
                if status == "error":
                    raise ComfyError(f"ComfyUI 推理失败: {get_error_message(record)}")
                if status == "success" or record.get("outputs"):
                    return record
        time.sleep(2)
    raise ComfyError(f"等待 ComfyUI 超时（{REQUEST_TIMEOUT_SECONDS // 60} 分钟）。")


def output_file(record: dict, node_id: str, keys: tuple[str, ...]) -> dict:
    node_output = record.get("outputs", {}).get(node_id, {})
    for key in keys:
        files = node_output.get(key, [])
        if files:
            return files[-1]
    raise ComfyError(f"任务完成但未找到节点 {node_id} 的输出文件。")


def download_file(file_info: dict, prefix: str) -> str:
    filename = file_info.get("filename")
    if not filename:
        raise ComfyError(f"ComfyUI 输出缺少 filename: {file_info}")

    response = requests.get(
        f"{COMFY_URL}/view",
        params={
            "filename": filename,
            "subfolder": file_info.get("subfolder", ""),
            "type": file_info.get("type", "output"),
        },
        timeout=120,
    )
    if not response.ok:
        raise ComfyError(f"下载 ComfyUI 输出失败: {response.text}")

    suffix = Path(filename).suffix or ".bin"
    destination = RESULT_DIR / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}{suffix}"
    destination.write_bytes(response.content)
    return str(destination)


def build_flux_workflow(reference_images: tuple[str, str, str], prompt: str) -> dict:
    workflow = copy.deepcopy(workflow_from(FLUX_WORKFLOW_PATH))
    for node_id, image in zip(FLUX_IMAGE_NODES, reference_images):
        workflow[node_id]["inputs"]["image"] = image
    workflow[FLUX_PROMPT_NODE]["inputs"]["text"] = prompt.strip()
    workflow[FLUX_SEED_NODE]["inputs"]["seed"] = random_seed()
    return workflow


def build_ltx_workflow(first_frame: str, prompt: str) -> dict:
    workflow = copy.deepcopy(workflow_from(LTX_WORKFLOW_PATH))
    workflow[LTX_IMAGE_NODE]["inputs"]["image"] = first_frame
    workflow[LTX_PROMPT_NODE]["inputs"]["prompt"] = prompt.strip()
    for node_id in LTX_SEED_NODES:
        workflow[node_id]["inputs"]["noise_seed"] = random_seed()
    return workflow


def build_vace_multi_reference_workflow(reference_images: tuple[str, str, str], prompt: str) -> dict:
    """Build a Wan2.1-VACE 1.3B reference-to-video workflow for three images."""
    return {
        "1": {
            "inputs": {"unet_name": "wan2.1_vace_1.3B.safetensors", "weight_dtype": "default"},
            "class_type": "UNETLoader",
            "_meta": {"title": "加载 Wan VACE 模型"},
        },
        "2": {
            "inputs": {"model": ["1", 0], "shift": 16.0},
            "class_type": "ModelSamplingSD3",
            "_meta": {"title": "Wan 采样配置"},
        },
        "3": {
            "inputs": {"clip_name": "umt5_xxl_enc_bf16.pth", "type": "wan", "device": "cpu"},
            "class_type": "CLIPLoader",
            "_meta": {"title": "加载 UMT5 文本编码器"},
        },
        "4": {
            "inputs": {"text": prompt.strip(), "clip": ["3", 0]},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "正向提示词"},
        },
        "5": {
            "inputs": {"text": "低清晰度，画面变形，主体不一致，文字水印", "clip": ["3", 0]},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "负向提示词"},
        },
        "6": {
            "inputs": {"vae_name": "wan2.1_vae.pth"},
            "class_type": "VAELoader",
            "_meta": {"title": "加载 Wan VAE"},
        },
        "7": {
            "inputs": {"image": reference_images[0]},
            "class_type": "LoadImage",
            "_meta": {"title": "场景参考"},
        },
        "8": {
            "inputs": {"image": reference_images[1]},
            "class_type": "LoadImage",
            "_meta": {"title": "主体参考"},
        },
        "9": {
            "inputs": {"image": reference_images[2]},
            "class_type": "LoadImage",
            "_meta": {"title": "风格参考"},
        },
        "10": {
            "inputs": {"image1": ["7", 0], "image2": ["8", 0]},
            "class_type": "ImageBatch",
            "_meta": {"title": "合并前两张参考图"},
        },
        "11": {
            "inputs": {"image1": ["10", 0], "image2": ["9", 0]},
            "class_type": "ImageBatch",
            "_meta": {"title": "合并三张参考图"},
        },
        "12": {
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "vae": ["6", 0],
                "width": VACE_WIDTH,
                "height": VACE_HEIGHT,
                "length": VACE_FRAMES,
                "batch_size": 1,
                "strength": 1.0,
                "reference_images": ["11", 0],
            },
            "class_type": "WanVaceMultiReference",
            "_meta": {"title": "Wan VACE 多图参考"},
        },
        "13": {
            "inputs": {
                "model": ["2", 0],
                "seed": random_seed(),
                "steps": 30,
                "cfg": 5.0,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "positive": ["12", 0],
                "negative": ["12", 1],
                "latent_image": ["12", 2],
                "denoise": 1.0,
            },
            "class_type": "KSampler",
            "_meta": {"title": "Wan VACE 采样"},
        },
        "14": {
            "inputs": {"samples": ["13", 0], "trim_amount": ["12", 3]},
            "class_type": "TrimVideoLatent",
            "_meta": {"title": "移除参考帧"},
        },
        "15": {
            "inputs": {"samples": ["14", 0], "vae": ["6", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "解码视频帧"},
        },
        "16": {
            "inputs": {"images": ["15", 0], "fps": VACE_FPS},
            "class_type": "CreateVideo",
            "_meta": {"title": "创建视频"},
        },
        VACE_OUTPUT_NODE: {
            "inputs": {
                "video": ["16", 0],
                "filename_prefix": "video/wan_vace_multi_reference",
                "format": "mp4",
                "codec": "h264",
            },
            "class_type": "SaveVideo",
            "_meta": {"title": "保存多图参考视频"},
        },
    }


def build_text_to_image_workflow(
    prompt: str,
    negative_prompt: str,
    image_size: str,
    reference_image: str | None = None,
) -> dict:
    if image_size not in IMAGE_SIZES:
        raise ComfyError(f"不支持的图片尺寸: {image_size}")

    width, height = IMAGE_SIZES[image_size]
    workflow = copy.deepcopy(workflow_from(TEXT_TO_IMAGE_WORKFLOW_PATH))
    workflow[T2I_PROMPT_NODE]["inputs"]["text"] = prompt.strip()
    workflow[T2I_NEGATIVE_PROMPT_NODE]["inputs"]["text"] = negative_prompt.strip()
    workflow[T2I_LATENT_NODE]["inputs"]["width"] = width
    workflow[T2I_LATENT_NODE]["inputs"]["height"] = height
    workflow[T2I_SEED_NODE]["inputs"]["seed"] = random_seed()

    if reference_image:
        workflow.update(
            {
                T2I_REFERENCE_IMAGE_NODE: {
                    "inputs": {"image": reference_image},
                    "class_type": "LoadImage",
                    "_meta": {"title": "加载参考图"},
                },
                T2I_REFERENCE_SCALE_NODE: {
                    "inputs": {
                        "upscale_method": "lanczos",
                        "megapixels": 1,
                        "resolution_steps": 64,
                        "image": [T2I_REFERENCE_IMAGE_NODE, 0],
                    },
                    "class_type": "ImageScaleToTotalPixels",
                    "_meta": {"title": "缩放参考图"},
                },
                T2I_REFERENCE_LATENT_NODE: {
                    "inputs": {
                        "pixels": [T2I_REFERENCE_SCALE_NODE, 0],
                        "vae": [T2I_VAE_NODE, 0],
                    },
                    "class_type": "VAEEncode",
                    "_meta": {"title": "编码参考图"},
                },
                T2I_REFERENCE_POSITIVE_NODE: {
                    "inputs": {
                        "conditioning": [T2I_PROMPT_NODE, 0],
                        "latent": [T2I_REFERENCE_LATENT_NODE, 0],
                    },
                    "class_type": "ReferenceLatent",
                    "_meta": {"title": "正向参考图"},
                },
                T2I_REFERENCE_NEGATIVE_NODE: {
                    "inputs": {
                        "conditioning": [T2I_NEGATIVE_PROMPT_NODE, 0],
                        "latent": [T2I_REFERENCE_LATENT_NODE, 0],
                    },
                    "class_type": "ReferenceLatent",
                    "_meta": {"title": "负向参考图"},
                },
            }
        )
        workflow[T2I_SEED_NODE]["inputs"]["positive"] = [T2I_REFERENCE_POSITIVE_NODE, 0]
        workflow[T2I_SEED_NODE]["inputs"]["negative"] = [T2I_REFERENCE_NEGATIVE_NODE, 0]

    return workflow


def generate_first_frame(image_a: str, image_b: str, image_c: str, frame_prompt: str):
    try:
        require_images(image_a, image_b, image_c)
        if not frame_prompt or not frame_prompt.strip():
            raise ComfyError("请填写首帧提示词。")
        with GENERATION_LOCK:
            references = tuple(
                upload_image(image, f"reference_{index}")
                for index, image in enumerate((image_a, image_b, image_c), start=1)
            )
            prompt_id = submit(build_flux_workflow(references, frame_prompt))
            record = wait_for_history(prompt_id)
            image_info = output_file(record, FLUX_OUTPUT_NODE, ("images",))
            first_frame = download_file(image_info, "first_frame")
        return first_frame, "首帧生成完成。"
    except Exception as error:
        return None, f"生成失败: {error}"


def generate_text_to_image(
    reference_image: str | None,
    prompt: str,
    negative_prompt: str,
    image_size: str,
):
    try:
        if not prompt or not prompt.strip():
            raise ComfyError("请填写图片提示词。")

        reference_message = "正在上传参考图并提交文生图任务..." if reference_image else "正在提交文生图任务..."
        yield None, reference_message
        with GENERATION_LOCK:
            uploaded_reference = upload_image(reference_image, "text_to_image_reference") if reference_image else None
            prompt_id = submit(
                build_text_to_image_workflow(
                    prompt,
                    negative_prompt or "",
                    image_size,
                    uploaded_reference,
                )
            )
            record = wait_for_history(prompt_id)
            image_info = output_file(record, T2I_OUTPUT_NODE, ("images",))
            image = download_file(image_info, "text_to_image")
        yield image, "文生图生成完成。"
    except Exception as error:
        yield None, f"生成失败: {error}"


def generate_video(image_a: str, image_b: str, image_c: str, frame_prompt: str, video_prompt: str):
    try:
        require_images(image_a, image_b, image_c)
        if not frame_prompt or not frame_prompt.strip():
            raise ComfyError("请填写首帧提示词。")
        if not video_prompt or not video_prompt.strip():
            raise ComfyError("请填写视频运动提示词。")

        yield None, None, "正在上传三张参考图并排队生成首帧..."
        with GENERATION_LOCK:
            references = tuple(
                upload_image(image, f"reference_{index}")
                for index, image in enumerate((image_a, image_b, image_c), start=1)
            )
            flux_id = submit(build_flux_workflow(references, frame_prompt))
            flux_record = wait_for_history(flux_id)
            image_info = output_file(flux_record, FLUX_OUTPUT_NODE, ("images",))
            first_frame = download_file(image_info, "first_frame")

            yield first_frame, None, "首帧已完成，正在提交 LTX 2.3 图生视频任务..."
            first_frame_input = upload_image(first_frame, "generated_first_frame")
            ltx_id = submit(build_ltx_workflow(first_frame_input, video_prompt))
            ltx_record = wait_for_history(ltx_id)
            video_info = output_file(ltx_record, LTX_OUTPUT_NODE, ("videos", "gifs", "images"))
            video = download_file(video_info, "video")
        yield first_frame, video, "视频生成完成。"
    except Exception as error:
        yield None, None, f"生成失败: {error}"


def generate_vace_multi_reference_video(image_a: str, image_b: str, image_c: str, prompt: str):
    try:
        require_images(image_a, image_b, image_c)
        if not prompt or not prompt.strip():
            raise ComfyError("请填写多图参考视频提示词。")

        yield None, "正在上传三张 VACE 参考图并提交视频任务..."
        with GENERATION_LOCK:
            references = tuple(
                upload_image(image, f"vace_reference_{index}")
                for index, image in enumerate((image_a, image_b, image_c), start=1)
            )
            prompt_id = submit(build_vace_multi_reference_workflow(references, prompt))
            record = wait_for_history(prompt_id)
            video_info = output_file(record, VACE_OUTPUT_NODE, ("videos", "gifs", "images"))
            video = download_file(video_info, "wan_vace_multi_reference")
        yield video, "Wan VACE 多图参考视频生成完成。"
    except Exception as error:
        yield None, f"生成失败: {error}"


REFERENCE_TOKENS = {
    "@场景": "场景参考图",
    "@主体": "主体参考图",
    "@风格": "风格参考图",
    "@图1": "场景参考图",
    "@图2": "主体参考图",
    "@图3": "风格参考图",
}


def replace_reference_tokens(prompt: str) -> tuple[str, bool]:
    """Translate UI reference tokens into instructions understood by local models."""
    text = (prompt or "").strip()
    used_reference = False
    for token, label in REFERENCE_TOKENS.items():
        if token in text:
            text = text.replace(token, label)
            used_reference = True
    return text, used_reference


def reference_aware_prompt(prompt: str, creation_type: str) -> str:
    text, used_reference = replace_reference_tokens(prompt)
    if not used_reference:
        return text

    if creation_type == "图片生成":
        return (
            f"{text}\n"
            "参考图约束：以已上传的参考图为视觉依据，保持提示词指定的主体、服装、风格或场景特征。"
        )
    return (
        f"{text}\n"
        "参考图约束：场景参考图用于环境与构图，主体参考图用于人物或物体，"
        "风格参考图用于画面质感与色彩；请按提示词中提到的参考图执行。"
    )


def append_reference_token(prompt: str, token: str) -> str:
    current = prompt or ""
    if token in current:
        return current
    separator = "" if not current or current.endswith((" ", "\n")) else " "
    return f"{current}{separator}{token} "


def generate_from_studio(
    creation_type: str,
    reference_1: str | None,
    reference_2: str | None,
    reference_3: str | None,
    prompt: str,
    negative_prompt: str,
    image_size: str,
):
    """Adapt the focused composer to the existing image and video workflows."""
    frame_prompt = reference_aware_prompt(prompt, creation_type)
    if creation_type == "图片生成":
        for image, message in generate_text_to_image(
            reference_1,
            frame_prompt,
            negative_prompt,
            image_size,
        ):
            yield image, None, message
        return

    if creation_type == "VACE 多图视频":
        for video, message in generate_vace_multi_reference_video(
            reference_1,
            reference_2,
            reference_3,
            frame_prompt,
        ):
            yield None, video, message
        return

    for first_frame, video, message in generate_video(
        reference_1,
        reference_2,
        reference_3,
        frame_prompt,
        replace_reference_tokens(prompt)[0],
    ):
        yield first_frame, video, message


def studio_mode_changed(creation_type: str):
    if creation_type == "图片生成":
        return (
            gr.Textbox(
                placeholder="描述你想生成的画面、主体、风格和光线...",
            ),
            gr.Markdown("上传一张参考图可帮助保持主体、服装或风格。"),
            gr.Dropdown(value="Flux2-Klein"),
        )
    if creation_type == "VACE 多图视频":
        return (
            gr.Textbox(
                placeholder="描述三张参考图在同一镜头中的主体、动作、关系与氛围...",
            ),
            gr.Markdown("VACE 将场景、主体、风格三张图作为独立参考条件，输出 832 x 480、约 5 秒视频。"),
            gr.Dropdown(value="Wan2.1 VACE 1.3B"),
        )
    return (
        gr.Textbox(
            placeholder="描述镜头中的主体、动作、运镜和氛围...",
        ),
        gr.Markdown("视频模式需要三张参考素材：场景、主体与风格。"),
        gr.Dropdown(value="Flux2 + LTX 2.3"),
    )


STUDIO_CSS = """
:root {
    --page: #f7f8fa;
    --surface: #ffffff;
    --line: #e9edf2;
    --line-strong: #dfe5eb;
    --ink: #151a22;
    --muted: #77808d;
    --cyan: #00a6c8;
    --cyan-soft: #e9f9fc;
}

body, .gradio-container {
    background: var(--page) !important;
    color: var(--ink) !important;
    font-family: "Microsoft YaHei UI", "PingFang SC", sans-serif !important;
}

.gradio-container {
    max-width: none !important;
    min-height: 100vh;
    padding: 0 !important;
}

#studio-shell {
    width: min(1080px, calc(100% - 40px));
    margin: 0 auto;
    padding: 110px 0 64px;
}

#studio-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 86px;
    color: #323b48;
    font-size: 15px;
    font-weight: 700;
}

#studio-brand .brand-mark {
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    border-radius: 7px;
    color: white;
    background: #111820;
    font-size: 14px;
}

#composer-title {
    margin: 0 0 38px !important;
    text-align: center;
}

#composer-title h1 {
    margin: 0 !important;
    color: #111820;
    font-size: 28px !important;
    font-weight: 700 !important;
    letter-spacing: 0 !important;
}

#composer {
    overflow: hidden;
    border: 1px solid var(--line-strong);
    border-radius: 18px;
    background: var(--surface);
    box-shadow: 0 12px 36px rgba(18, 30, 45, 0.05);
}

#composer .form, #composer .wrap {
    gap: 0 !important;
}

#reference-row {
    padding: 20px 20px 0;
    gap: 10px !important;
}

#reference-row .image-container {
    min-height: 104px !important;
    border: 1px dashed #cfd9e2 !important;
    border-radius: 10px !important;
    background: #fbfcfd !important;
}

#reference-row .image-container:hover {
    border-color: var(--cyan) !important;
    background: #f4fcfe !important;
}

#reference-row .image-container .upload-button {
    color: #586574 !important;
    font-size: 12px !important;
}

#reference-row label {
    color: #6a7581 !important;
    font-size: 12px !important;
}

#prompt-box {
    padding: 12px 20px 0;
}

#prompt-box textarea {
    min-height: 114px !important;
    padding: 12px 2px !important;
    border: 0 !important;
    box-shadow: none !important;
    background: transparent !important;
    color: var(--ink) !important;
    font-size: 15px !important;
    line-height: 1.7 !important;
    resize: vertical !important;
}

#prompt-box textarea:focus {
    box-shadow: none !important;
}

#mode-hint {
    min-height: 22px;
    margin: -2px 20px 10px;
    color: var(--muted);
    font-size: 12px;
}

#reference-token-row {
    gap: 6px !important;
    margin: 0 20px 12px;
}

#reference-token-row button {
    width: auto !important;
    min-height: 27px !important;
    padding: 0 9px !important;
    border: 1px solid #dbe9ed !important;
    border-radius: 7px !important;
    box-shadow: none !important;
    background: #f5fcfd !important;
    color: #397180 !important;
    font-size: 12px !important;
}

#reference-token-row button:hover {
    border-color: #9fd4e0 !important;
    background: #e9f9fc !important;
}

#composer-tools {
    align-items: center !important;
    gap: 8px !important;
    padding: 14px 18px 18px;
    border-top: 1px solid #f0f2f5;
}

#composer-tools .block {
    min-width: 0;
}

#composer-tools .wrap {
    gap: 7px !important;
}

#composer-tools label {
    display: none !important;
}

#composer-tools .single-select, #composer-tools input, #composer-tools button.secondary {
    min-height: 36px !important;
    border: 1px solid var(--line) !important;
    border-radius: 8px !important;
    box-shadow: none !important;
    background: #fff !important;
    color: #374151 !important;
    font-size: 13px !important;
}

#composer-tools button.secondary:hover {
    border-color: #b9cbd3 !important;
    background: #f8fbfc !important;
}

#mode-select {
    min-width: 110px;
}

#size-select {
    min-width: 142px;
}

#advanced-panel {
    margin: 0 20px 18px;
    border: 1px solid var(--line) !important;
    border-radius: 9px !important;
    background: #fbfcfd !important;
}

#advanced-panel > button {
    color: #617080 !important;
    font-size: 13px !important;
}

#advanced-panel textarea {
    border-radius: 7px !important;
    border-color: var(--line) !important;
    box-shadow: none !important;
    font-size: 13px !important;
}

#generate-button {
    width: 42px;
    min-width: 42px !important;
    height: 42px;
    min-height: 42px !important;
    border: 0 !important;
    border-radius: 50% !important;
    box-shadow: none !important;
    background: #151b23 !important;
    color: #fff !important;
    font-size: 20px !important;
    line-height: 1 !important;
}

#generate-button:hover {
    background: #27313c !important;
}

#preset-row {
    justify-content: center !important;
    gap: 8px !important;
    margin-top: 18px;
}

#preset-row button {
    width: auto !important;
    min-height: 32px !important;
    padding: 0 12px !important;
    border: 1px solid var(--line) !important;
    border-radius: 16px !important;
    box-shadow: none !important;
    background: #fff !important;
    color: #637080 !important;
    font-size: 12px !important;
}

#results-area {
    margin-top: 44px;
    padding-top: 26px;
    border-top: 1px solid #e7ebef;
}

#results-area h2 {
    margin: 0 0 16px !important;
    color: #29313a;
    font-size: 16px !important;
    font-weight: 650 !important;
}

#results-area .image-container, #results-area .video-container {
    border-radius: 8px !important;
    border-color: var(--line) !important;
    background: #fff !important;
}

#status-box textarea {
    min-height: 36px !important;
    border: 0 !important;
    box-shadow: none !important;
    background: transparent !important;
    color: #77808d !important;
    font-size: 13px !important;
}

@media (max-width: 700px) {
    #studio-shell { width: min(100% - 24px, 1080px); padding-top: 30px; }
    #studio-brand { margin-bottom: 54px; }
    #composer-title { margin-bottom: 26px !important; }
    #composer-title h1 { font-size: 24px !important; }
    #reference-row { padding: 14px 14px 0; }
    #reference-row .image-container { min-height: 80px !important; }
    #prompt-box { padding: 8px 14px 0; }
    #mode-hint { margin-left: 14px; margin-right: 14px; }
    #reference-token-row { margin-left: 14px; margin-right: 14px; }
    #composer-tools { align-items: stretch !important; padding: 12px 14px 14px; }
    #generate-button { align-self: flex-end; }
    #advanced-panel { margin-left: 14px; margin-right: 14px; }
    #results-area { margin-top: 32px; }
}
"""


def create_app() -> gr.Blocks:
    install_gradio_upload_preview_fix()
    with gr.Blocks(title="Toonflow 本地视频工作台") as app:
        with gr.Column(elem_id="studio-shell"):
            gr.HTML(
                '<div id="studio-brand"><span class="brand-mark">T</span><span>Toonflow</span></div>'
            )
            gr.Markdown("# 你好，想创作什么？", elem_id="composer-title")

            with gr.Column(elem_id="composer"):
                with gr.Row(elem_id="reference-row", equal_height=True):
                    reference_1 = gr.Image(
                        type="filepath",
                        label="场景参考",
                        sources=["upload"],
                        height=104,
                    )
                    reference_2 = gr.Image(
                        type="filepath",
                        label="主体参考",
                        sources=["upload"],
                        height=104,
                    )
                    reference_3 = gr.Image(
                        type="filepath",
                        label="风格参考",
                        sources=["upload"],
                        height=104,
                    )

                prompt = gr.Textbox(
                    label="创作提示词",
                    placeholder="描述镜头中的主体、动作、运镜和氛围...",
                    lines=4,
                    max_lines=8,
                    show_label=False,
                    elem_id="prompt-box",
                )
                mode_hint = gr.Markdown(
                    "视频模式需要三张参考素材：场景、主体与风格。",
                    elem_id="mode-hint",
                )
                with gr.Row(elem_id="reference-token-row"):
                    scene_token = gr.Button("@场景", variant="secondary")
                    subject_token = gr.Button("@主体", variant="secondary")
                    style_token = gr.Button("@风格", variant="secondary")

                with gr.Accordion("更多设置", open=False, elem_id="advanced-panel"):
                    negative_prompt = gr.Textbox(
                        label="负面提示词",
                        placeholder="可选，例如：低清晰度、变形、文字水印",
                        lines=2,
                    )

                with gr.Row(elem_id="composer-tools"):
                    creation_type = gr.Dropdown(
                        choices=["视频生成", "VACE 多图视频", "图片生成"],
                        value="视频生成",
                        show_label=False,
                        elem_id="mode-select",
                    )
                    model_name = gr.Dropdown(
                        choices=["Flux2 + LTX 2.3", "Wan2.1 VACE 1.3B", "Flux2-Klein"],
                        value="Flux2 + LTX 2.3",
                        interactive=False,
                        show_label=False,
                        min_width=160,
                    )
                    image_size = gr.Dropdown(
                        choices=list(IMAGE_SIZES),
                        value="横版 1280 x 720",
                        show_label=False,
                        elem_id="size-select",
                    )
                    gr.HTML('<span style="flex:1"></span>')
                    generate_button = gr.Button(
                        "&#8593;",
                        elem_id="generate-button",
                        elem_classes=["generate-button"],
                    )

            with gr.Row(elem_id="preset-row"):
                cinematic_preset = gr.Button("电影感运镜", variant="secondary")
                portrait_preset = gr.Button("人物特写", variant="secondary")
                travel_preset = gr.Button("旅行航拍", variant="secondary")

            with gr.Column(elem_id="results-area"):
                gr.Markdown("## 创作结果")
                with gr.Row():
                    image_output = gr.Image(
                        label="图片 / 首帧",
                        type="filepath",
                        height=380,
                    )
                    video_output = gr.Video(label="视频", height=380)
                status = gr.Textbox(
                    label="任务状态",
                    placeholder="等待开始创作",
                    interactive=False,
                    show_label=False,
                    elem_id="status-box",
                )

        creation_type.change(
            studio_mode_changed,
            inputs=creation_type,
            outputs=[prompt, mode_hint, model_name],
        )
        scene_token.click(
            lambda text: append_reference_token(text, "@场景"),
            inputs=prompt,
            outputs=prompt,
        )
        subject_token.click(
            lambda text: append_reference_token(text, "@主体"),
            inputs=prompt,
            outputs=prompt,
        )
        style_token.click(
            lambda text: append_reference_token(text, "@风格"),
            inputs=prompt,
            outputs=prompt,
        )
        cinematic_preset.click(
            lambda: "电影级中景，人物缓步前行，镜头平稳向前推进，清晨侧逆光，细腻的空间层次。",
            outputs=prompt,
        )
        portrait_preset.click(
            lambda: "人物半身特写，自然微笑和轻微转头，浅景深，柔和窗边光，镜头缓慢推近。",
            outputs=prompt,
        )
        travel_preset.click(
            lambda: "广阔山谷与蜿蜒道路，无人机由高处缓慢下降并向前飞行，金色日落，真实航拍质感。",
            outputs=prompt,
        )
        generate_button.click(
            generate_from_studio,
            inputs=[
                creation_type,
                reference_1,
                reference_2,
                reference_3,
                prompt,
                negative_prompt,
                image_size,
            ],
            outputs=[image_output, video_output, status],
        )
    return app


if __name__ == "__main__":
    app = create_app()
    app.queue(default_concurrency_limit=1)
    app.launch(
        server_name="0.0.0.0",
        server_port=7865,
        show_error=True,
        css=STUDIO_CSS,
    )
