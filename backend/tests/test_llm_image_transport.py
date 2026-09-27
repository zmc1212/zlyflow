"""Aliyun image transport must not depend on the upstream downloading our CDN."""
import base64
import io
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from PIL import Image
import requests

from backend.app.llm_client import LlmError, OpenAICompatibleClient
from backend.app import llm_image_transport as transport


ALIYUN_URL = "https://ws-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


def png_bytes(color="red", size=(32, 32)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def messages(urls):
    return [
        {"role": "system", "content": "Write using every reference in order."},
        {"role": "user", "content": [
            {"type": "text", "text": "Picture 1, Picture 2"},
            *[{"type": "image_url", "image_url": {"url": url, "detail": "high"}} for url in urls],
        ]},
    ]


class AliyunImageIntegrationTests(unittest.TestCase):
    @patch("backend.app.llm_image_transport.download_image")
    @patch("requests.Session.post")
    def test_real_image_urls_are_inlined_without_mutating_or_reordering(self, post, download):
        red, blue = png_bytes(), png_bytes("blue")
        download.side_effect = [red, blue]
        response = MagicMock(status_code=200)
        response.json.return_value = {"id": "req-inline", "model": "deepseek-v4.1-flash",
                                      "choices": [{"message": {"content": "draft"}}]}
        post.return_value = response
        original = messages(["https://cdn.example/one.png", "https://cdn.example/two.png",
                             "https://cdn.example/one.png"])
        before = deepcopy(original)
        meta = {}
        result = OpenAICompatibleClient(ALIYUN_URL, "secret-test").chat_completion(
            original, "deepseek-v4.1-flash", meta_out=meta, max_tokens=123)
        payload = post.call_args.kwargs["json"]
        parts = payload["messages"][1]["content"][1:]
        self.assertEqual(result, "draft")
        self.assertEqual(original, before)
        self.assertEqual(payload["model"], "deepseek-v4.1-flash")
        self.assertEqual(payload["max_tokens"], 123)
        self.assertEqual(download.call_count, 2)
        self.assertEqual(parts[0], parts[2])
        self.assertNotEqual(parts[0], parts[1])
        for part, expected in zip(parts, (red, blue, red)):
            self.assertEqual(part["image_url"]["detail"], "high")
            url = part["image_url"]["url"]
            self.assertTrue(url.startswith("data:image/png;base64,"))
            self.assertEqual(base64.b64decode(url.split(",", 1)[1]), expected)
        self.assertEqual(meta["image_transport"], "inline_base64")
        self.assertEqual(meta["image_count"], 3)
        self.assertEqual(meta["inlined_image_count"], 3)
        self.assertNotIn("cdn.example", str(meta))

    @patch("requests.Session.post")
    def test_other_providers_and_text_only_requests_keep_their_payload(self, post):
        response = MagicMock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        post.return_value = response
        original = messages(["https://cdn.example/one.png"])
        OpenAICompatibleClient("https://other.example/v1", "secret").chat_completion(original, "model")
        self.assertEqual(post.call_args.kwargs["json"]["messages"], original)
        plain = [{"role": "user", "content": "text only"}]
        OpenAICompatibleClient(ALIYUN_URL, "secret").chat_completion(plain, "model")
        self.assertEqual(post.call_args.kwargs["json"]["messages"], plain)

    @patch("backend.app.llm_image_transport.download_image")
    @patch("requests.Session.post")
    def test_failed_download_never_submits_text_only_or_switches_model(self, post, download):
        from backend.app.llm_image_transport import ImageTransportError
        download.side_effect = ImageTransportError("图片下载超时")
        meta = {}
        with self.assertRaisesRegex(LlmError, "第 1 张参考图.*图片下载超时"):
            OpenAICompatibleClient(ALIYUN_URL, "secret").chat_completion(
                messages(["https://cdn.example/image.png?token=private"]), "model", meta_out=meta)
        post.assert_not_called()
        self.assertFalse(meta["ok"])
        self.assertEqual(meta["failure_stage"], "image_preparation")
        self.assertNotIn("private", str(meta))


class ImagePreparationTests(unittest.TestCase):
    def test_provider_detection_is_by_exact_host_not_model_name(self):
        for url in (ALIYUN_URL, "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                    "https://dashscope-us.aliyuncs.com/compatible-mode/v1"):
            self.assertTrue(transport.uses_inline_images(url))
        for url in ("https://evilmaas.aliyuncs.com/v1", "https://dashscope.aliyuncs.com.evil.test/v1",
                    "https://evil.test/dashscope.aliyuncs.com", "http://localhost:1234/v1"):
            self.assertFalse(transport.uses_inline_images(url))

    @patch.object(transport, "download_image")
    def test_valid_inline_probe_is_not_downloaded_or_double_encoded(self, download):
        from backend.app.vision_capability import RED_PROBE_DATA_URL
        original = messages([RED_PROBE_DATA_URL])
        self.assertEqual(transport.prepare_chat_images(original, ALIYUN_URL, meta_out={}), original)
        download.assert_not_called()

    def test_invalid_inline_data_and_corrupt_images_fail_with_picture_number(self):
        for url in ("data:image/png;base64,not-valid!", "data:image/png,raw",
                    "data:image/png;base64," + base64.b64encode(b"not a picture").decode(), ""):
            with self.subTest(url=url), self.assertRaisesRegex(transport.ImageTransportError, "第 1 张参考图"):
                transport.prepare_chat_images(messages([url]), ALIYUN_URL, meta_out={})

    @patch.object(transport, "MAX_IMAGE_PIXELS", 10)
    def test_pixel_limit_is_checked_before_decoding(self):
        with self.assertRaisesRegex(transport.ImageTransportError, "像素过大"):
            transport._encode_image(png_bytes(), 1024)

    @patch.object(transport, "MAX_IMAGE_EDGE", 32)
    def test_only_wire_copy_is_resized_and_transparency_is_preserved(self):
        out = io.BytesIO()
        Image.new("RGBA", (128, 64), (255, 0, 0, 0)).save(out, format="PNG")
        source = out.getvalue()
        result = transport._encode_image(source, 1024)
        with Image.open(io.BytesIO(base64.b64decode(result.split(",", 1)[1]))) as im:
            self.assertEqual(im.size, (32, 16))
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.getpixel((0, 0))[3], 0)
        with Image.open(io.BytesIO(source)) as original:
            self.assertEqual(original.size, (128, 64))

    def test_aggregate_budget_counts_repeated_slots_and_preserves_non_image_parts(self):
        url = "data:image/png;base64," + base64.b64encode(png_bytes()).decode()
        original = messages([url] * 9)
        original[1]["content"].insert(1, {"type": "custom", "value": "leave intact"})
        meta = {}
        result = transport.prepare_chat_images(original, ALIYUN_URL, meta_out=meta)
        self.assertEqual(result, original)
        self.assertEqual(meta["image_count"], 9)
        self.assertEqual(meta["inlined_image_count"], 9)
        self.assertEqual(meta["image_payload_bytes"], len(url) * 9)
        self.assertLessEqual(meta["image_payload_bytes"], transport.MAX_ENCODED_BYTES)

    def test_large_noise_image_fits_per_image_budget_after_compression(self):
        out = io.BytesIO()
        Image.effect_noise((512, 256), 64).convert("RGB").save(out, format="PNG")
        result = transport._encode_image(out.getvalue(), 48 * 1024)
        raw = base64.b64decode(result.split(",", 1)[1])
        self.assertLessEqual(len(raw), 48 * 1024)
        with Image.open(io.BytesIO(raw)) as im:
            self.assertGreater(im.width, im.height)


class ImageDownloadTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch.object(transport.socket, "getaddrinfo",
                                return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]).start()
        self.session_cls = patch.object(transport.requests, "Session").start()
        self.addCleanup(patch.stopall)
        self.session = self.session_cls.return_value.__enter__.return_value
        self.body = png_bytes()

    def response(self, status=200, headers=None, chunks=None):
        response = MagicMock(status_code=status)
        response.headers = headers if headers is not None else {"Content-Type": "image/png"}
        response.iter_content.return_value = chunks if chunks is not None else [self.body]
        response.__enter__.return_value = response
        return response

    def test_download_uses_separate_session_without_credentials_and_closes_response(self):
        response = self.response()
        self.session.get.return_value = response
        result = transport.download_image("https://cdn.example/img.png?token=private")
        self.assertEqual(result, self.body)
        self.assertFalse(self.session.trust_env)
        self.assertFalse(self.session.get.call_args.kwargs["allow_redirects"])
        self.assertNotIn("headers", self.session.get.call_args.kwargs)
        self.assertNotIn("auth", self.session.get.call_args.kwargs)
        response.__exit__.assert_called_once()
        self.session_cls.return_value.__exit__.assert_called_once()

    def test_private_loopback_and_link_local_dns_are_rejected(self):
        for ip in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fd00::1"):
            self.dns.return_value = [(2, 1, 6, "", (ip, 443))]
            with self.subTest(ip=ip), self.assertRaisesRegex(transport.ImageTransportError, "非公网"):
                transport.download_image("https://cdn.example/image.png")
        self.session.get.assert_not_called()

    def test_non_http_schemes_and_embedded_credentials_are_rejected(self):
        for url in ("file:///etc/passwd", "ftp://cdn.example/image", "https://user:password@cdn.example/image"):
            with self.subTest(url=url), self.assertRaises(transport.ImageTransportError):
                transport.download_image(url)
        self.session.get.assert_not_called()

    @patch.object(transport, "_configured_media_hostname", return_value="cdn.example")
    def test_proxy_fake_ips_are_only_allowed_for_configured_https_cdn(self, configured):
        self.dns.return_value = [(2, 1, 6, "", ("198.18.1.132", 443)),
                                (10, 1, 6, "", ("fdfe:dcba:9876::187", 443, 0, 0))]
        self.session.get.return_value = self.response()
        self.assertEqual(transport.download_image("https://cdn.example/image"), self.body)
        for url in ("http://cdn.example/image", "https://cdn.example:8443/image",
                    "https://untrusted.example/image", "https://cdn.example.evil.test/image"):
            with self.subTest(url=url), self.assertRaisesRegex(transport.ImageTransportError, "非公网"):
                transport.download_image(url)
        self.assertEqual(self.session.get.call_count, 1)

    @patch.object(transport, "_configured_media_hostname", return_value="cdn.example")
    def test_configured_cdn_still_cannot_resolve_to_actual_private_network(self, configured):
        self.dns.return_value = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with self.assertRaisesRegex(transport.ImageTransportError, "非公网"):
            transport.download_image("https://cdn.example/image")
        self.session.get.assert_not_called()
        configured.assert_not_called()

    @patch.object(transport, "_configured_media_hostname", side_effect=RuntimeError("offline"))
    def test_proxy_domain_lookup_failure_is_closed(self, configured):
        self.dns.return_value = [(2, 1, 6, "", ("198.18.1.132", 443))]
        with self.assertRaisesRegex(transport.ImageTransportError, "非公网"):
            transport.download_image("https://cdn.example/image")
        self.session.get.assert_not_called()

    def test_redirect_target_is_revalidated_before_get(self):
        self.dns.side_effect = [[(2, 1, 6, "", ("8.8.8.8", 443))],
                                [(2, 1, 6, "", ("127.0.0.1", 443))]]
        first = self.response(302, {"Location": "https://localhost/private"})
        self.session.get.return_value = first
        with self.assertRaisesRegex(transport.ImageTransportError, "非公网"):
            transport.download_image("https://cdn.example/image")
        self.assertEqual(self.session.get.call_count, 1)
        first.__exit__.assert_called_once()

    def test_relative_public_redirect_is_followed(self):
        self.session.get.side_effect = [self.response(302, {"Location": "/actual.png"}), self.response()]
        self.assertEqual(transport.download_image("https://cdn.example/image"), self.body)
        self.assertEqual(self.session.get.call_args.args[0], "https://cdn.example/actual.png")

    def test_http_failure_and_timeout_never_leak_signed_url(self):
        self.session.get.return_value = self.response(403)
        with self.assertRaisesRegex(transport.ImageTransportError, "HTTP 403") as caught:
            transport.download_image("https://cdn.example/image?token=private")
        self.assertNotIn("private", str(caught.exception))
        self.session.get.side_effect = requests.Timeout("https://cdn.example/image?token=private")
        with self.assertRaisesRegex(transport.ImageTransportError, "图片下载超时") as caught:
            transport.download_image("https://cdn.example/image?token=private")
        self.assertNotIn("private", str(caught.exception))

    def test_html_is_not_forwarded_as_an_image(self):
        self.session.get.return_value = self.response(headers={"Content-Type": "text/html"})
        with self.assertRaisesRegex(transport.ImageTransportError, "未返回"):
            transport.download_image("https://cdn.example/image")

    @patch.object(transport, "MAX_SOURCE_BYTES", 10)
    def test_download_enforces_declared_and_actual_byte_limits(self):
        self.session.get.return_value = self.response(headers={"Content-Type": "image/png", "Content-Length": "11"})
        with self.assertRaisesRegex(transport.ImageTransportError, "超过"):
            transport.download_image("https://cdn.example/image")
        self.session.get.return_value = self.response(chunks=[b"123456", b"123456"])
        with self.assertRaisesRegex(transport.ImageTransportError, "超过"):
            transport.download_image("https://cdn.example/image")


if __name__ == "__main__":
    unittest.main()
