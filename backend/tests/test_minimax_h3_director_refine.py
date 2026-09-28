import copy
import json
import unittest
from unittest.mock import Mock

from backend.app.minimax_h3_director_refine_workflow import (
    MODE, baseline, build_refine_shot, build_refine_workflow, validate_refine_dependencies,
)
from backend.app.workflow_registry import normalize_options, workflow_for
from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
from backend.app.media_studio.services.director_reliable import shot_route


class DirectorRefineTests(unittest.TestCase):
    def test_recipe_preserves_author_parameters(self):
        graph = build_refine_shot('test', ['ref.png'], normalize_options(MODE, {}), 666)
        original = baseline()
        self.assertEqual(graph['6']['inputs']['bit_depth'], 8)
        self.assertEqual(graph['19']['inputs']['bit_depth'], 8)
        mutable = {'12', '38', '7', '20'}
        for node in original.keys() - mutable:
            self.assertEqual(graph[node], original[node], node)
        for key, value in original['12']['inputs'].items():
            if key not in {'global_prompt', 'timeline_data', 'total_frames'}:
                self.assertEqual(graph['12']['inputs'][key], value, key)
        for key, value in original['38']['inputs'].items():
            self.assertEqual(graph['38']['inputs'][key], value, key)

    def test_disabled_preserves_first_pass(self):
        on = build_refine_shot('test', ['ref.png'], {}, 12)
        off = build_refine_shot('test', ['ref.png'], {'refine_enabled': False}, 12)
        expected = copy.deepcopy(on['12'])
        expected['inputs'].pop('refine')
        self.assertEqual(off['12'], expected)
        self.assertNotIn('38', off)
        self.assertNotIn('20', off)
        self.assertEqual(on['16'], off['16'])

    def test_validation_and_routing(self):
        with self.assertRaises(ValueError):
            build_refine_shot('test', [], {}, 12)
        with self.assertRaises(ValueError):
            normalize_options(MODE, {'refine_quality': '4.0'})
        with self.assertRaises(ValueError):
            normalize_options(MODE, {'speed': 'balanced'})
        self.assertEqual(shot_route(MODE.value, 1, 5)[0], MODE.value)
        self.assertIsNone(shot_route(MODE.value, 0, 5)[0])
        graph = ComfyVideoClient.build_shot_workflow(MODE.value, 'test', ['ref.png'], 'test', options={})
        self.assertEqual(graph['7']['inputs']['filename_prefix'], 'test-refined')
        with self.assertRaisesRegex(ValueError, '依赖缺失'):
            validate_refine_dependencies(graph, {})

    def test_schema(self):
        props = workflow_for(MODE).option_schema['properties']
        self.assertTrue(all(p['ui_group'] in {'primary', 'advanced', 'internal'} for p in props.values()))
        self.assertEqual(props['refine_quality']['ui_visible_when'], {'refine_enabled': True})
        self.assertNotIn('upscale_after', props)

    def test_timeline_route_and_seed_zero(self):
        timeline = {'totalFrames': 248, 'global': {'refs': []}, 'segments': [
            {'id': str(i), 'refs': [{'imageFile': 'ref.png'}], 'frameCount': 124,
             'continuityFromPrev': bool(i), 'prompt': 'test'} for i in range(2)]}
        graph = ComfyVideoClient.build_workflow(timeline, 'r2v', 'test',
            workflow_id=MODE.value, options={'seed': 0, 'refine_quality': '1.0'})
        self.assertEqual(graph['12']['inputs']['seed'], 0)
        self.assertEqual(graph['38']['inputs']['megapixels'], 1.0)
        submitted = json.loads(graph['12']['inputs']['timeline_data'])
        self.assertTrue(submitted['segments'][1]['continuityFromPrev'])
        self.assertEqual(submitted['output']['continuityOverlapFrames'], 22)
        self.assertNotIn('output', timeline)
        shot = ComfyVideoClient.build_shot_workflow(MODE.value, 'test', ['ref.png'], 'test', options={'seed': 0})
        self.assertEqual(shot['12']['inputs']['seed'], 0)

    def test_history_selects_final_by_node_not_order(self):
        graph = build_refine_shot('test', ['ref.png'], {}, 12)
        client = ComfyVideoClient('http://example.invalid')
        history = {'status': {'completed': True, 'status_str': 'success'}, 'outputs': {
            '20': {'images': [{'filename': 'first.mp4'}]},
            '7': {'images': [{'filename': 'final.mp4'}]},
        }}
        response = Mock()
        response.json.return_value = {'test': history}
        client.session = Mock()
        client.session.get.return_value = response
        _, output = client.wait_for_result('test', workflow=graph, poll_seconds=0)
        self.assertEqual(output['filename'], 'final.mp4')
        del history['outputs']['7']
        with self.assertRaisesRegex(RuntimeError, 'SaveVideo'):
            client.wait_for_result('test', workflow=graph, poll_seconds=0)


if __name__ == '__main__':
    unittest.main()
