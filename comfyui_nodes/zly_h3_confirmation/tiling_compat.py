"""Private compatibility bindings for the author's legacy spatial tiler."""
import builtins
import importlib
import logging
from types import SimpleNamespace

from .protocol import ConfirmationError, clone_function


def compatible_refine(refine, evidence):
    sample = refine.__globals__["sample_single_stage"]
    tiles = importlib.import_module(sample.__globals__["__package__"] + ".spatial_tiled_sampling")
    return bind_refine(refine, sample, tiles, evidence)


def bind_refine(refine, sample, tiles, evidence):
    """No sys.modules replacement, upstream source write, or global monkey patch."""
    evidence.update(tile_model_calls=0, tiled_evaluations=0, tiled_segments=0)
    failures = []

    class Proxy(tiles._TiledModelProxy):
        def __call__(self, x, sigma, denoise_mask=None, model_options=None, seed=None, **kwargs):
            inner = object.__getattribute__(self, "_inner")
            cfg = inner.inner_model
            base = cfg.inner_model
            missing = object()
            original = getattr(base, "latent_shapes", missing)
            shapes = original if original is not missing else None
            if not shapes:
                candidates = [getattr(c.get("latent_shapes"), "cond", None)
                              for c in tiles._iter_payloads(cfg)]
                candidates = [c for c in candidates if c]
                if not candidates or any(c != candidates[0] for c in candidates[1:]):
                    failures.append("TILING_SHAPES_UNAVAILABLE")
                    raise ConfirmationError(failures[-1])
                shapes = candidates[0]

            def invoke(model_k, tile, step, mask, call_kw):
                # The author silently falls back on layout errors. Fail closed here.
                if base.latent_shapes == shapes:
                    failures.append("TILING_FULL_FRAME_FALLBACK_REJECTED")
                    raise ConfirmationError(failures[-1])
                evidence["tile_model_calls"] += 1
                return tiles._invoke_model(model_k, tile, step, mask, call_kw)

            call = clone_function(tiles._tiled_model_call, _invoke_model=invoke)
            base.latent_shapes = shapes
            try:
                result = call(inner, x, sigma, denoise_mask=denoise_mask,
                              model_options=model_options, seed=seed,
                              n_tiles=object.__getattribute__(self, "_n_tiles"),
                              overlap_pixels=object.__getattribute__(self, "_overlap_pixels"), **kwargs)
                evidence["tiled_evaluations"] += 1
                return result
            except Exception as exc:
                failures.append(str(exc))
                raise
            finally:
                if original is missing:
                    delattr(base, "latent_shapes")
                else:
                    base.latent_shapes = original

    wrap = clone_function(tiles.wrap_sampler_spatial_tiles, _TiledModelProxy=Proxy)
    original_import = builtins.__import__

    def private_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "spatial_tiled_sampling" and level == 1 and "wrap_sampler_spatial_tiles" in fromlist:
            return SimpleNamespace(wrap_sampler_spatial_tiles=wrap)
        return original_import(name, globals, locals, fromlist, level)

    private_sample = clone_function(sample, __builtins__={**vars(builtins), "__import__": private_import})
    private_refine = clone_function(refine, sample_single_stage=private_sample)

    def execute(*args, **kwargs):
        before = evidence["tile_model_calls"]
        result = private_refine(*args, **kwargs)
        if failures or evidence["tile_model_calls"] == before:
            raise ConfirmationError("SPATIAL_TILING_NOT_VERIFIED: " + "; ".join(failures))
        evidence["tiled_segments"] += 1
        logging.getLogger(__name__).info("ZLY H3 verified spatial tiling: %s", evidence)
        return result

    return execute
