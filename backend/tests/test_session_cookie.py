from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import Response

from backend.app import main as main_module


class SessionCookieTests(unittest.TestCase):
    """跨站内嵌会话 Cookie 的 SameSite 行为。"""

    def session_cookie(self, **overrides) -> str:
        settings = replace(main_module.settings, **overrides)
        with patch.object(main_module, "settings", settings):
            response = Response()
            main_module.set_session_cookie(response, "token-123")
        return response.headers["set-cookie"].lower()

    def test_default_remains_lax(self):
        header = self.session_cookie()
        self.assertIn("samesite=lax", header)
        self.assertIn("httponly", header)
        self.assertNotIn("samesite=none", header)

    def test_cross_site_cookies_use_none_with_secure(self):
        header = self.session_cookie(cross_site_cookies=True, secure_cookies=True)
        self.assertIn("samesite=none", header)
        self.assertIn("; secure", header)

    def test_cross_site_without_secure_falls_back_to_lax(self):
        # 浏览器拒绝没有 Secure 的 SameSite=None，宁可保持 lax 也不要静默失效。
        header = self.session_cookie(cross_site_cookies=True, secure_cookies=False)
        self.assertIn("samesite=lax", header)
        self.assertNotIn("samesite=none", header)


if __name__ == "__main__":
    unittest.main()