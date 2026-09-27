"""Guard the intentional Xiaji retirement; do not import deleted modules."""
import unittest

from backend.app.main import app


class DirectorMigrationRouteTests(unittest.TestCase):
    def test_retired_xiaji_routes_are_not_registered(self):
        routes = [route.path for route in app.routes if hasattr(route, "path")]
        self.assertFalse([path for path in routes if path.startswith("/api/xiaji")])

    def test_current_workshop_routes_remain_registered(self):
        paths = app.openapi()["paths"]
        workshop = "/api/projects/{project_id}/episodes/{episode_id}/workshop"
        self.assertIn("get", paths[workshop])
        self.assertIn("patch", paths[workshop])
        self.assertIn("get", paths["/api/projects/{project_id}/documents"])


if __name__ == "__main__":
    unittest.main()
