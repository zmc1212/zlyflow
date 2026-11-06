"""Queued KEEP face repair for the ZLY workbench (ComfyUI V3)."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile

import folder_paths
from comfy import model_management
from comfy.utils import ProgressBar
from comfy_api.latest import ComfyExtension, io
from .worker import run

for category, relative in [("keep", "keep_models/KEEP"), ("keep_face_models", "facedetection")]:
    folder_paths.add_model_folder_path(category, os.path.join(folder_paths.models_dir, relative))


def input_video(name: str) -> Path:
    path = Path(folder_paths.get_annotated_filepath(name)).resolve()
    root = Path(folder_paths.get_input_directory()).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("找不到上传的视频，请重新上传后重试。")
    return path


def model_file(category: str, name: str) -> str:
    if name not in folder_paths.get_filename_list(category):
        raise ValueError(f"缺少人脸修复模型：{name}")
    return folder_paths.get_full_path_or_raise(category, name)


class KeepFaceRestore(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="ZLYKeepFaceRestore", display_name="人脸高清修复 · KEEP", category="ZLY/video",
            is_output_node=True,
            inputs=[
                io.String.Input("video"), io.String.Input("face_source_video"),
                io.Float.Input("point_x", default=.5, min=0, max=1),
                io.Float.Input("point_y", default=.5, min=0, max=1),
                io.Combo.Input("duration", options=["full", "5s"], default="full"),
                io.Boolean.Input("preserve_audio", default=True),
                io.Combo.Input("model_name", options=folder_paths.get_filename_list("keep")),
                io.Combo.Input("detector_model", options=folder_paths.get_filename_list("keep_face_models")),
                io.Combo.Input("parser_model", options=folder_paths.get_filename_list("keep_face_models")),
                io.Int.Input("chunk_length", default=12, min=2, max=32),
                io.Int.Input("overlap", default=4, min=0, max=16),
                io.Float.Input("landmark_sigma", default=2, min=0, max=4),
                io.String.Input("filename_prefix", default="ZLY_KEEP_FACE_RESTORE"),
            ], outputs=[],
        )

    @classmethod
    def execute(cls, video, face_source_video, point_x, point_y, duration, preserve_audio,
                model_name, detector_model, parser_model, chunk_length, overlap, landmark_sigma,
                filename_prefix) -> io.NodeOutput:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", filename_prefix):
            raise ValueError("视频输出名称无效。")
        if overlap >= chunk_length:
            raise ValueError("时序重叠必须小于处理窗口。")
        runtime = Path(folder_paths.base_path) / "extra_tools/KEEP_ComfyCompat"
        if not (runtime / "modules/deps/wm_basicsr/archs/keep_arch.py").is_file():
            raise ValueError("KEEP 执行依赖尚未安装，请按工作台架构文档完成部署。")
        base = input_video(video)
        source = input_video(face_source_video)
        output_root = Path(folder_paths.get_output_directory()).resolve()
        folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(filename_prefix, str(output_root))
        name = f"{filename}_{counter:05}_.mp4"
        output = (Path(folder) / name).resolve()
        if not output.is_relative_to(output_root):
            raise ValueError("视频输出目录无效。")
        config = {
            "base_video": str(base), "source_video": str(source), "output": str(output),
            "point": [float(point_x), float(point_y)], "duration": duration,
            "preserve_audio": bool(preserve_audio), "chunk_length": int(chunk_length),
            "overlap": int(overlap), "landmark_sigma": float(landmark_sigma),
            "model": model_file("keep", model_name),
            "detector": model_file("keep_face_models", detector_model),
            "parser": model_file("keep_face_models", parser_model),
            "runtime": str(runtime), "comfy_root": str(Path(folder_paths.base_path)),
        }
        model_management.unload_all_models()
        model_management.soft_empty_cache()
        bar = ProgressBar(100)
        def emit(value, **data):
            model_management.throw_exception_if_processing_interrupted()
            bar.update_absolute(int(value), 100)
        try:
            with tempfile.TemporaryDirectory(prefix="zly-keep-", dir=folder_paths.get_temp_directory()) as directory:
                config["temp_dir"] = directory
                report = run(config, emit)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        bar.update_absolute(100, 100)
        return io.NodeOutput(ui={"videos": [{"filename": name, "subfolder": subfolder, "type": "output"}],
                                 "face_restore_report": [report]})


class KeepExtension(ComfyExtension):
    async def get_node_list(self):
        return [KeepFaceRestore]


async def comfy_entrypoint():
    return KeepExtension()
