from __future__ import annotations

import gc
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any, Protocol

from . import paths, protocol

logger = logging.getLogger("indextts_sidecar")


class InferenceEngine(Protocol):
    def infer(self, **kwargs: Any) -> Path: ...
    def free(self) -> None: ...
    def loaded(self) -> bool: ...


class IndexTTSEngine:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else paths.default_index_tts_root()
        self._tts: Any = None
        self._lock = threading.Lock()

    def loaded(self) -> bool:
        return self._tts is not None

    def _load(self) -> Any:
        if self._tts is not None:
            return self._tts
        with self._lock:
            if self._tts is not None:
                return self._tts
            if not paths.checkpoints_ready(self.root):
                raise RuntimeError(
                    f"未找到 IndexTTS-2.5 权重：{paths.checkpoints_dir(self.root)}。"
                    "请把官方 checkpoints 放到工作台父级「整合包及模型/index-tts/checkpoints」，"
                    "或设置 ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT。"
                )
            try:
                from indextts.infer_v2_5 import IndexTTS2
            except ImportError as exc:
                raise RuntimeError(
                    "当前 Python 环境没有 IndexTTS-2.5。请用官方 uv/venv 启动旁路服务，"
                    "不要把模型装进工作台 FastAPI 虚拟环境。"
                ) from exc
            cfg = str(paths.config_path(self.root))
            model_dir = str(paths.checkpoints_dir(self.root))
            logger.info("Loading IndexTTS-2.5 from %s", model_dir)
            self._tts = IndexTTS2(cfg_path=cfg, model_dir=model_dir, use_bf16=True)
            return self._tts

    def infer(
        self,
        *,
        spk_audio_prompt: str,
        text: str,
        lang: str = "ZH",
        output_path: str | None = None,
        emo_vector: list[float] | None = None,
        emo_alpha: float = 0.8,
        duration_factor: float = 1.0,
        emo_audio_prompt: str | None = None,
        emo_text: str | None = None,
    ) -> Path:
        tts = self._load()
        dest = Path(output_path) if output_path else Path(tempfile.mkstemp(suffix=".wav")[1])
        kwargs: dict[str, Any] = {
            "spk_audio_prompt": spk_audio_prompt,
            "text": text,
            "lang": lang,
            "output_path": str(dest),
            "emo_alpha": protocol.clamp_emo_alpha(emo_alpha),
            "duration_factor": protocol.clamp_duration_factor(duration_factor),
            "use_random": False,
            "verbose": False,
        }
        if emo_vector:
            kwargs["emo_vector"] = emo_vector
        if emo_audio_prompt:
            kwargs["emo_audio_prompt"] = emo_audio_prompt
        if emo_text:
            kwargs["emo_text"] = emo_text
            kwargs["use_emo_text"] = True
        tts.infer(**kwargs)
        if not dest.is_file() or dest.stat().st_size < 64:
            raise RuntimeError("IndexTTS 没有写出有效音频")
        return dest

    def free(self) -> None:
        with self._lock:
            self._tts = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            logger.debug("CUDA cache unload skipped", exc_info=True)
