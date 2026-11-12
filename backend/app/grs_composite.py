"""图片服务复合管线：局部重绘 / 消除笔 / 扩图的纯函数处理逻辑。

这三个工作流由「图片服务指令生成 + 本地 PIL 合成」组成：
- 局部重绘 / 消除笔：原图 + 白色遮罩图交给图片服务指令改图，返回结果按遮罩
  与原图合成，遮罩外像素与原图完全一致（羽化过渡）。
- 扩图：原图按目标画幅等比垫入扩展画布（拉伸模糊底），图片服务补全扩展区，
  回来后把原图按位置贴回，原区域像素完全一致。

合成逻辑全部是纯 PIL 函数，便于单元测试；执行器接线在 worker.py。
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFilter

from .models import JobMode

COMPOSITE_IMAGE_MODES = {
    JobMode.IMAGE_INPAINT.value,
    JobMode.IMAGE_ERASER.value,
    JobMode.IMAGE_OUTPAINT.value,
}

# 注册表 internal 默认：走图片服务指令改图能力最好的模型。
DEFAULT_COMPOSITE_PROVIDER_MODEL = "nano-banana-2"

# 遮罩合成默认羽化半径（按原图短边自适应夹取）。
DEFAULT_FEATHER_PX = 12

OUTPAINT_TARGET_ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4")
ASPECT_RATIO_VALUES = {
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "1:1": 1.0,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
}

# 扩图目标画布单边上限（工具页画布交互提交的 target_width/height）；
# 原图本身超过该值时放宽到原图边长，保证 1x 也始终合法。
OUTPAINT_MAX_SIDE = 4096


class CompositeImageError(ValueError):
    """复合图片管线的输入错误（422 语义）。"""


# ---------------------------------------------------------------------------
# 输入校验与加载
# ---------------------------------------------------------------------------

def load_rgb(path: str | Path, label: str) -> Image.Image:
    try:
        image = Image.open(path)
        image.load()
    except Exception as error:  # noqa: BLE001 - 统一转为业务错误
        raise CompositeImageError(f"{label}无法读取：{error}") from error
    return image.convert("RGB")


def load_mask(path: str | Path, size: tuple[int, int]) -> Image.Image:
    """遮罩图：白色=编辑区。任意尺寸都会缩放到原图尺寸，返回 L 模式。"""
    try:
        image = Image.open(path)
        image.load()
    except Exception as error:  # noqa: BLE001
        raise CompositeImageError(f"遮罩图无法读取：{error}") from error
    mask = image.convert("L").resize(size, Image.LANCZOS)
    histogram = mask.histogram()
    white = sum(histogram[200:])
    if white == 0:
        raise CompositeImageError("遮罩图中没有白色区域，请先标记要编辑的部分")
    return mask


def feather_alpha_for(image: Image.Image, feather_px: int) -> int:
    """羽化半径按短边夹取，避免小图被羽化吞掉。"""
    shortest = min(image.size)
    return max(0, min(int(feather_px), max(0, shortest // 8)))


# ---------------------------------------------------------------------------
# 遮罩合成（局部重绘 / 消除笔）
# ---------------------------------------------------------------------------

def composite_masked(
    original: Image.Image, generated: Image.Image, mask: Image.Image, feather_px: int = DEFAULT_FEATHER_PX,
) -> Image.Image:
    """按遮罩把图片服务结果贴回原图：遮罩外与原图逐像素一致，遮罩内羽化过渡。"""
    if original.size != generated.size:
        generated = generated.resize(original.size, Image.LANCZOS)
    if original.size != mask.size:
        mask = mask.resize(original.size, Image.LANCZOS)
    radius = feather_alpha_for(original, feather_px)
    alpha = mask.filter(ImageFilter.GaussianBlur(radius)) if radius > 0 else mask
    return Image.composite(generated.convert("RGB"), original.convert("RGB"), alpha)


# ---------------------------------------------------------------------------
# 扩图
# ---------------------------------------------------------------------------

def outpaint_canvas(
    original: Image.Image, target_aspect: str,
    target_size: tuple[int, int] | None = None, offset: tuple[int, int] | None = None,
) -> tuple[Image.Image, tuple[int, int]]:
    """把原图等比垫入目标画布：返回画布（拉伸模糊底）与原图左上角位置。

    两种目标画布指定方式：显式 target_size（工具页画布交互，任意尺寸），
    或 target_aspect 预设画幅（原图更"竖"时向左右扩展，更"横"时向上下扩展）。
    offset 指定原图左上角位置（拖拽可能非对称扩展），缺省居中。
    """
    if target_size is not None:
        canvas_w, canvas_h = target_size
        if canvas_w < original.width or canvas_h < original.height:
            raise CompositeImageError("目标画布不能小于原图，扩图只会向外扩展")
    else:
        ratio = ASPECT_RATIO_VALUES.get(target_aspect)
        if ratio is None:
            raise CompositeImageError(f"不支持的目标画幅: {target_aspect}")
        width, height = original.size
        source_ratio = width / height
        if source_ratio <= ratio:
            # 原图更竖（或同比例）：高度不变，向左右扩展到目标比例。
            canvas_h = height
            canvas_w = max(width, round(height * ratio))
        else:
            # 原图更横：宽度不变，向上下扩展到目标比例。
            canvas_w = width
            canvas_h = max(height, round(width / ratio))
    canvas_w += canvas_w % 2
    canvas_h += canvas_h % 2
    left = (canvas_w - original.width) // 2
    top = (canvas_h - original.height) // 2
    if offset is not None:
        left = max(0, min(int(offset[0]), canvas_w - original.width))
        top = max(0, min(int(offset[1]), canvas_h - original.height))
    # 拉伸模糊底作为颜色上下文，模型在它之上补全扩展区。
    backdrop = original.resize((canvas_w, canvas_h), Image.LANCZOS).filter(
        ImageFilter.GaussianBlur(max(12, min(canvas_w, canvas_h) // 16)),
    )
    backdrop.paste(original, (left, top))
    return backdrop, (left, top)


def outpaint_target_size(options: dict, original_size: tuple[int, int]) -> tuple[int, int] | None:
    """读取工具页画布交互提交的显式目标画布；两项都缺省（0）时返回 None 走预设画幅。"""
    width = int(options.get("target_width") or 0)
    height = int(options.get("target_height") or 0)
    if width <= 0 and height <= 0:
        return None
    if width <= 0 or height <= 0:
        raise CompositeImageError("目标画布宽高必须同时提供")
    original_w, original_h = original_size
    if width < original_w or height < original_h:
        raise CompositeImageError("目标画布不能小于原图，扩图只会向外扩展")
    if width > max(OUTPAINT_MAX_SIDE, original_w) or height > max(OUTPAINT_MAX_SIDE, original_h):
        raise CompositeImageError(f"目标画布单边不能超过 {OUTPAINT_MAX_SIDE} 像素")
    return (width + width % 2, height + height % 2)


def outpaint_offset(
    options: dict, original_size: tuple[int, int], target_size: tuple[int, int],
) -> tuple[int, int]:
    """读取原图在目标画布内的左上角位置，夹取到合法范围（缺省 0 时由居中兜底）。"""
    offset_x = int(options.get("target_offset_x") or 0)
    offset_y = int(options.get("target_offset_y") or 0)
    return (
        max(0, min(offset_x, target_size[0] - original_size[0])),
        max(0, min(offset_y, target_size[1] - original_size[1])),
    )


# ---------------------------------------------------------------------------
# 图片服务指令模板
# ---------------------------------------------------------------------------

def composite_prompt(mode: JobMode | str, user_prompt: str, target_aspect: str | None = None) -> str:
    key = mode.value if isinstance(mode, JobMode) else str(mode)
    prompt = (user_prompt or "").strip()
    if key == JobMode.IMAGE_INPAINT.value:
        if not prompt:
            raise CompositeImageError("请填写要把选区替换成什么内容")
        return (
            f"第一张是原图，第二张是标记图：白色区域是要重绘的位置。"
            f"只修改原图中白色标记的区域，把它变成：{prompt}。"
            f"白色区域之外的画面内容必须保持完全不变。"
        )
    if key == JobMode.IMAGE_ERASER.value:
        hint = f"要移除的对象是：{prompt}。" if prompt else ""
        return (
            "第一张是原图，第二张是标记图：白色区域是要移除内容的位置。"
            f"{hint}把原图中白色标记区域的内容移除，并用周围的背景自然填补，"
            "衔接处不留明显痕迹。白色区域之外的画面内容必须保持完全不变。"
        )
    if key == JobMode.IMAGE_OUTPAINT.value:
        aspect_note = f"目标画幅为 {target_aspect}。" if target_aspect else ""
        user_note = f"扩展区域按用户的描述生成：{prompt}。" if prompt else ""
        return (
            f"把这张图片的边缘部分向外自然延伸，补全成更完整的画面。{aspect_note}"
            f"{user_note}"
            "延伸区域要与原画面在内容、风格、光影和透视上保持连贯；"
            "图片中央的原始内容保持不变。"
        )
    raise CompositeImageError(f"不支持的图片复合工作流: {mode}")


def composite_images(
    mode: JobMode | str, original: Image.Image, generated: Image.Image,
    mask: Image.Image | None, position: tuple[int, int] | None, feather_px: int,
    outpaint_target_size: tuple[int, int] | None = None,
) -> Image.Image:
    """按模式把图片服务结果合成为最终交付图。"""
    key = mode.value if isinstance(mode, JobMode) else str(mode)
    if key in {JobMode.IMAGE_INPAINT.value, JobMode.IMAGE_ERASER.value}:
        if mask is None:
            raise CompositeImageError("缺少遮罩图，无法合成结果")
        return composite_masked(original, generated, mask, feather_px)
    if key == JobMode.IMAGE_OUTPAINT.value:
        if position is None:
            raise CompositeImageError("缺少原图位置，无法合成结果")
        return composite_outpaint_canvas(
            generated, original, position, feather_px, target_size=outpaint_target_size,
        )
    raise CompositeImageError(f"不支持的图片复合工作流: {mode}")


def composite_outpaint_canvas(
    generated: Image.Image, original: Image.Image, position: tuple[int, int], feather_px: int,
    target_size: tuple[int, int] | None = None,
) -> Image.Image:
    """扩图合成：生成结果先对齐垫图画布尺寸，再把原图带羽化贴回原位。

    图片服务会按自己的分辨率返回同比例结果（如 1376x768），必须先缩放回
    垫图画布尺寸，position 才与原图对齐。
    """
    output = generated.convert("RGB")
    if target_size is not None and output.size != tuple(target_size):
        output = output.resize(tuple(target_size), Image.LANCZOS)
    if output.size == original.size:
        # 模型没有扩展画布（如原比例已匹配目标），直接返回生成图。
        return output
    radius = feather_alpha_for(original, feather_px)
    inner = Image.new("L", original.size, 255)
    if radius > 0:
        inner = inner.filter(ImageFilter.GaussianBlur(radius))
        # 高斯羽化会让边缘半透明、中心略低于 255，重新拉回纯白中心。
        inner = inner.point(lambda v: 255 if v >= 250 else v)
    output.paste(original.convert("RGB"), position, inner)
    return output


# ---------------------------------------------------------------------------
# 执行器入口（供 worker 调用的纯函数；uploads_root 便于测试注入）
# ---------------------------------------------------------------------------

def _resolve_reference_paths(uploads_root: Path, context: dict) -> list[Path]:
    paths: list[Path] = []
    for name in context.get("references") or []:
        path = Path(name).resolve()
        if uploads_root.resolve() not in path.parents or not path.is_file():
            raise CompositeImageError(f"参考图片不存在或超出上传目录: {path.name}")
        paths.append(path)
    return paths


def build_composite_inputs(uploads_root: Path, mode: JobMode | str, context: dict) -> tuple[
    Image.Image, dict, str, list[str],
]:
    """加载并预处理复合工作流素材：返回 (原图, options, 图片服务指令, 输入 data URI 列表)。"""
    key = mode.value if isinstance(mode, JobMode) else str(mode)
    options = context.get("options") or {}
    paths = _resolve_reference_paths(uploads_root, context)
    user_prompt = str(context.get("prompt") or "")
    if key in {JobMode.IMAGE_INPAINT.value, JobMode.IMAGE_ERASER.value}:
        if len(paths) != 2:
            raise CompositeImageError("需要上传原图和遮罩图（白色=编辑区）两张素材")
        original = load_rgb(paths[0], "原图")
        mask = load_mask(paths[1], original.size)
        mask_view = Image.merge("RGB", (mask, mask, mask))
        images = [
            data_uri_bytes("original.png", encode_png(original)),
            data_uri_bytes("mask.png", encode_png(mask_view)),
        ]
        prompt = composite_prompt(key, user_prompt)
    elif key == JobMode.IMAGE_OUTPAINT.value:
        if not paths:
            raise CompositeImageError("需要上传原图")
        original = load_rgb(paths[0], "原图")
        target_size = outpaint_target_size(options, original.size)
        if target_size is not None:
            canvas, _position = outpaint_canvas(
                original, "", target_size=target_size,
                offset=outpaint_offset(options, original.size, target_size),
            )
            prompt = composite_prompt(key, user_prompt)
        else:
            target_aspect = str(options.get("target_aspect") or "16:9")
            canvas, _position = outpaint_canvas(original, target_aspect)
            prompt = composite_prompt(key, user_prompt, target_aspect)
        images = [data_uri_bytes("canvas.png", encode_png(canvas))]
    else:
        raise CompositeImageError(f"不支持的图片复合工作流: {key}")
    return original, options, prompt, images


def compose_final(
    uploads_root: Path, mode: JobMode | str, context: dict, generated_bytes: bytes,
) -> bytes:
    """把图片服务返回图与原素材合成最终交付图，返回 PNG 字节。"""
    key = mode.value if isinstance(mode, JobMode) else str(mode)
    options = context.get("options") or {}
    raw_feather = options.get("feather")
    # feather=0 是合法值（关闭羽化），只有缺省才回落默认。
    feather = DEFAULT_FEATHER_PX if raw_feather is None else int(raw_feather)
    original, _options, _prompt, _images = build_composite_inputs(uploads_root, key, context)
    try:
        generated = Image.open(BytesIO(generated_bytes))
        generated.load()
    except Exception as error:  # noqa: BLE001
        raise CompositeImageError(f"图片服务返回结果无法解析：{error}") from error
    mask = None
    position = None
    if key in {JobMode.IMAGE_INPAINT.value, JobMode.IMAGE_ERASER.value}:
        paths = _resolve_reference_paths(uploads_root, context)
        if len(paths) != 2:
            raise CompositeImageError("需要上传原图和遮罩图（白色=编辑区）两张素材")
        mask = load_mask(paths[1], original.size)
    elif key == JobMode.IMAGE_OUTPAINT.value:
        target_size = outpaint_target_size(options, original.size)
        if target_size is not None:
            canvas, position = outpaint_canvas(
                original, "", target_size=target_size,
                offset=outpaint_offset(options, original.size, target_size),
            )
        else:
            target_aspect = str(options.get("target_aspect") or "16:9")
            canvas, position = outpaint_canvas(original, target_aspect)
    final = composite_images(key, original, generated, mask, position, feather, canvas.size if key == JobMode.IMAGE_OUTPAINT.value else None)
    return encode_png(final)


def encode_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def data_uri_bytes(filename: str, content: bytes) -> str:
    """把图片字节编码为 data URI（与 GrsClient.data_uri 同格式）。"""
    suffix = Path(filename).suffix.lower().lstrip(".") or "png"
    mime = "image/jpeg" if suffix in {"jpg", "jpeg"} else "image/png"
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"
