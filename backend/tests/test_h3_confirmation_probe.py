import copy
import unittest
from unittest.mock import Mock

from backend.scripts.inspect_h3_confirmation import (
    CACHE_STATUS, REFINE_JS, inspection_payload, inspect_protocol,
)
from backend.app.minimax_h3_director_refine_workflow import MODE, build_refine_shot
from backend.app.workflow_registry import workflow_for


class ConfirmationProbeTests(unittest.TestCase):
    def session(self, cache):
        session = Mock()
        script = Mock(text=f'api.fetchApi("{CACHE_STATUS}");')
        schema = Mock()
        schema.json.return_value = {"MiniMaxH3DirectorRefine": {"input": {
            "optional": {"confirm_first_pass": ["BOOLEAN", {"default": False}]},
        }}}
        session.get.side_effect = [script, schema]
        response = Mock()
        response.json.return_value = cache
        session.post.return_value = response
        return session

    def test_quality_changes_only_refine_witness(self):
        low, high = inspection_payload(1.0), inspection_payload(2.0)
        self.assertEqual(low["seed"], 0)
        self.assertTrue(low["refine"]["confirm_first_pass"])
        self.assertTrue(low["refine"]["has_sample_model"])
        self.assertTrue(low["refine"]["has_sigmas_tensor"])
        self.assertFalse(low["refine"]["has_upscale_model"])
        low["refine"]["megapixels"] = 2.0
        self.assertEqual(low, high)

    def test_cache_match_cannot_certify_strict_confirmation(self):
        for cache in ({"exists": False, "matches": False},
                      {"exists": True, "matches": True, "can_confirm_refine": True}):
            with self.subTest(cache=cache):
                session = self.session(cache)
                result = inspect_protocol("http://remote.invalid/", session)
                self.assertFalse(result["strict_confirmation_verified"])
                self.assertTrue(result["release_blockers"])
                self.assertEqual(result["synthetic_cache_samples"][0]["response"], cache)
                self.assertEqual(session.post.call_count, 2)
                for call in session.post.call_args_list:
                    self.assertEqual(call.args[0], "http://remote.invalid" + CACHE_STATUS)
                self.assertEqual(session.get.call_args_list[0].args[0], "http://remote.invalid" + REFINE_JS)

    def test_unknown_frontend_fails_without_post(self):
        session = self.session({})
        schema = Mock()
        schema.json.return_value = {"MiniMaxH3DirectorRefine": {"input": {}}}
        session.get.side_effect = [Mock(text="// changed protocol"), schema]
        with self.assertRaises(ValueError):
            inspect_protocol("http://remote.invalid", session)
        session.post.assert_not_called()

    def test_probe_does_not_change_legacy_recipe_or_publish(self):
        before = copy.deepcopy(build_refine_shot("test", ["ref.png"], {}, 0))
        inspection_payload()
        self.assertEqual(build_refine_shot("test", ["ref.png"], {}, 0), before)
        self.assertFalse(before["38"]["inputs"]["confirm_first_pass"])
        self.assertTrue(workflow_for(MODE).hidden_from_catalog)


if __name__ == "__main__":
    unittest.main()
