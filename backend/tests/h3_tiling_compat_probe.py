"""CPU probe using installed ComfyUI/Director; run with its Python and two paths.

Usage: python h3_tiling_compat_probe.py COMFYUI_ROOT ADAPTER_SOURCE_DIRECTORY
No server, GPU sampling, model loading, or upstream source mutation is performed.
"""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
import torch
import comfy.utils

spec = importlib.util.spec_from_file_location("tiling_probe_author", root / "custom_nodes/ComfyUI_MiniMaxH3_Director/director/spatial_tiled_sampling.py")
tiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tiles)
packed, shapes = comfy.utils.pack_latents([torch.ones(1, 1, 2, 4, 40), torch.ones(1, 1, 2)])
condition = SimpleNamespace(cond=shapes)
base = SimpleNamespace()
cfg = SimpleNamespace(inner_model=base, conds={"positive": [{"model_conds": {"latent_shapes": condition}}]})

class Model:
    inner_model = cfg
    def __init__(self):
        self.widths = []
    def __call__(self, x, sigma, denoise_mask=None, **kwargs):
        self.widths.append(comfy.utils.unpack_latents(x, condition.cond)[0].shape[-1])
        return x

model = Model()
result = tiles._tiled_model_call(model, packed, torch.ones(1), n_tiles=4, overlap_pixels=0)
assert model.widths == [40], model.widths
original = list(model.widths)
model.widths.clear()
base.latent_shapes = shapes
try:
    result = tiles._tiled_model_call(model, packed, torch.ones(1), n_tiles=4, overlap_pixels=0)
finally:
    del base.latent_shapes
assert model.widths == [10, 10, 10, 10], model.widths
assert torch.allclose(result, packed)
assert condition.cond == shapes
print(json.dumps({"original_forward_widths": original, "compatible_forward_widths": model.widths, "output_preserved": True, "condition_restored": True}))

import types
package = types.ModuleType("zly_probe")
package.__path__ = [sys.argv[2]]
sys.modules["zly_probe"] = package
from zly_probe.tiling_compat import bind_refine
from zly_probe.protocol import ConfirmationError

def sample_single_stage():
    from .spatial_tiled_sampling import wrap_sampler_spatial_tiles
    sampler = SimpleNamespace(sampler_function=lambda m, noise, sigmas, **kw: m(noise, sigmas))
    restore = wrap_sampler_spatial_tiles(sampler, n_tiles=4, overlap_pixels=0)
    try:
        return sampler.sampler_function(model, packed, torch.ones(1))
    finally:
        restore()

def refine():
    return sample_single_stage()

model = Model()
evidence = {}
from comfy.ldm.minimax.model import PackedLayout
payload = {"layout": PackedLayout(2, 2, 4, 40, 2), "frame_count": 5}
payload_condition = SimpleNamespace(cond=payload)
cfg.conds["positive"][0]["model_conds"]["minimax_payload"] = payload_condition
original_wrapper = tiles.wrap_sampler_spatial_tiles
bound = bind_refine(refine, sample_single_stage, tiles, evidence)
result = bound()
assert model.widths == [10, 10, 10, 10], model.widths
assert torch.allclose(result, packed)
assert not hasattr(base, "latent_shapes")
assert condition.cond == shapes
assert payload_condition.cond is payload
assert original_wrapper is tiles.wrap_sampler_spatial_tiles
assert evidence == {"tile_model_calls": 4, "tiled_evaluations": 1, "tiled_segments": 1}, evidence
cfg.conds = {}
try:
    bind_refine(refine, sample_single_stage, tiles, {})()
    raise AssertionError("Missing shape must not fall back to full frame")
except ConfirmationError:
    pass
print(json.dumps({"production_private_binding": "passed", "evidence": evidence, "missing_shape_rejected": True}))
