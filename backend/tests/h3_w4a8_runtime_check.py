"""Opt-in CUDA/runtime check on the existing ComfyUI host; never saves model weights."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy-root", required=True)
    parser.add_argument("--runtime-overlay")
    parser.add_argument("--loader")
    parser.add_argument("--model")
    parser.add_argument("--legacy-model")
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]
    os.chdir(args.comfy_root)
    sys.path.insert(0, args.comfy_root)
    if args.runtime_overlay:
        sys.path.insert(0, args.runtime_overlay)
    import torch
    import comfy_kitchen
    from comfy_kitchen.tensor import AsymW4A8Int8Layout, QuantizedTensor
    from comfy_kitchen.tensor.w4a8_int8 import w4a8_int8_linear

    torch.manual_seed(42)
    weight = torch.randn(256, 512, device="cuda", dtype=torch.bfloat16)
    x = torch.randn(64, 512, device="cuda", dtype=torch.bfloat16)
    qdata, params = AsymW4A8Int8Layout.quantize(weight)
    started = time.time()
    output = w4a8_int8_linear(
        x, qdata, params.scale, params.s_channel, codebook=params.codebook,
        correction=params.correction, group_size=params.group_size,
        convrot_groupsize=params.convrot_groupsize, out_dtype=torch.bfloat16,
    )
    torch.cuda.synchronize()
    reference = torch.nn.functional.linear(x, AsymW4A8Int8Layout.dequantize(qdata, params))
    rel_error = (output.float() - reference.float()).norm() / reference.float().norm()
    assert tuple(output.shape) == (64, 256) and bool(torch.isfinite(output).all())
    assert float(rel_error) < 0.05, f"Unexpected W4A8 relative error: {rel_error}"
    print(json.dumps({"torch": torch.__version__, "kitchen_path": comfy_kitchen.__file__,
                      "gpu": torch.cuda.get_device_name(0), "cuda_smoke_seconds": time.time() - started,
                      "relative_error": float(rel_error)}, ensure_ascii=False), flush=True)
    # The installed ComfyUI must still import its original quantized operators.
    import comfy.ops
    import comfy.quant_ops
    print("original_comfy_ops_import=ok", flush=True)
    if args.legacy_model:
        import comfy.sd
        legacy = comfy.sd.load_diffusion_model(args.legacy_model)
        layers = [layer for layer in legacy.model.modules()
                  if getattr(layer, "weight", None) is not None
                  and layer.weight.ndim == 2 and hasattr(layer, "in_features")]
        if not layers:
            raise RuntimeError("No linear layers found in the legacy checkpoint")
        layers.sort(key=lambda layer: bool(getattr(layer, "quant_format", None)), reverse=True)
        layer = layers[0].to(device="cuda")
        legacy_x = torch.randn(8, layer.in_features, device="cuda", dtype=torch.bfloat16)
        with torch.inference_mode():
            legacy_y = layer(legacy_x)
        torch.cuda.synchronize()
        assert bool(torch.isfinite(legacy_y).all())
        print(json.dumps({"legacy_model": Path(args.legacy_model).name,
                          "legacy_quant_format": getattr(layer, "quant_format", None),
                          "legacy_linear_class": type(layer).__qualname__,
                          "legacy_layer_output_shape": list(legacy_y.shape)}), flush=True)
        del layers, layer, legacy, legacy_x, legacy_y
    if args.model:
        if not args.loader:
            raise ValueError("--loader required with --model")
        spec = importlib.util.spec_from_file_location("zly_w4a8_check_loader", args.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        started = time.time()
        model = module.load_w4a8_model(args.model)
        weights = [layer.weight for layer in model.model.modules()
                   if getattr(layer, "quant_format", None) == "asym_w4a8_int8"]
        if not weights:
            raise RuntimeError("No W4A8 layers were actually loaded")
        # Use a real checkpoint layer, rather than proving only random-tensor execution.
        w = weights[0].to(device="cuda")
        real_input = torch.randn(8, w.shape[1], device="cuda", dtype=torch.bfloat16)
        with torch.inference_mode():
            out = torch.nn.functional.linear(real_input, w)
        torch.cuda.synchronize()
        assert bool(torch.isfinite(out).all())
        print(json.dumps({"model": Path(args.model).name, "loaded_w4a8_layers": len(weights),
                          "load_and_layer_seconds": time.time() - started,
                          "real_layer_output_shape": list(out.shape)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
