from io import BytesIO

from PIL import Image, ImageOps


MAX_PROFILE_AVATAR_BYTES = 5 * 1024 * 1024
MAX_PROFILE_AVATAR_PIXELS = 20_000_000
PROFILE_AVATAR_SIZE = (256, 256)


def normalize_profile_avatar(content: bytes) -> bytes:
    try:
        with Image.open(BytesIO(content), formats=("JPEG", "PNG", "WEBP")) as source:
            if source.width * source.height > MAX_PROFILE_AVATAR_PIXELS:
                raise ValueError("头像不能超过 2000 万像素")
            oriented = ImageOps.exif_transpose(source)
            avatar = ImageOps.fit(oriented.convert("RGBA"), PROFILE_AVATAR_SIZE, Image.Resampling.LANCZOS)
    except Image.DecompressionBombError as error:
        raise ValueError("头像不能超过 2000 万像素") from error
    except (OSError, SyntaxError) as error:
        raise ValueError("请选择有效的 JPG、PNG 或 WebP 图片") from error

    with BytesIO() as output:
        avatar.save(output, format="WEBP", quality=86)
        return output.getvalue()
