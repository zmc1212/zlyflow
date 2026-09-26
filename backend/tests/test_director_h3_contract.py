import unittest

from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder
from backend.app.media_studio.services.prompt_expansion_service import PromptExpansionService


class DirectorH3ContractTests(unittest.TestCase):
    def test_compiler_keeps_shared_prompt_out_of_segment_body(self):
        result = H3PromptBuilder.compile_director_segment_prompt(
            "subject_definitions: 主体与场景锁定",
            "[Shot 1｜0–8秒]\n[主体] 主角抬头。",
        )
        self.assertEqual(result["global_prompt"], "subject_definitions: 主体与场景锁定")
        self.assertEqual(result["segment_prompt"], "[Shot 1｜0–8秒]\n[主体] 主角抬头。")

    def test_v6_group_contract_projects_to_legacy_parts(self):
        plan = {
            "schema_version": 6,
            "kind": "director_segments",
            "planning_strategy": "atomic_units",
            "workflow_id": "minimax-h3-director-accel-r2v",
            "language": "zh-CN",
            "common_prompt": "主体定义：主角与车站",
            "reference_slots": [],
            "source_facts": {"beat-1": {"events": [], "dialogues": []}},
            "groups": [{
                "id": "group-1",
                "shots": [{"id": "shot-1", "beat_id": "beat-1", "h3_prompt": "[Shot 1｜0–8秒] 车站。", "duration_seconds": 8}],
            }],
        }
        # The projection itself is part of validation; the resulting error, if
        # any, must be a factual contract issue rather than an unsupported v6
        # schema error.
        with self.assertRaises(ValueError) as ctx:
            PromptExpansionService.validate_director_plan(plan)
        self.assertNotIn("结构已升级", str(ctx.exception))
        self.assertTrue(str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
