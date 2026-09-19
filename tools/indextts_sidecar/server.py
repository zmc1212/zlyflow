from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import paths, protocol
from .engine import IndexTTSEngine, InferenceEngine

logger = logging.getLogger("indextts_sidecar")


class SpeechRequest(BaseModel):
    model: str = "indextts-2.5"
    input: str = Field(default="", min_length=0)
    voice: str = "clone"
    response_format: str = "wav"
    lang: str | None = None
    emo_vector: list[float] | None = None
    emotion: str | None = None
    emo_alpha: float | None = None
    duration_factor: float | None = None


def create_app(engine: InferenceEngine | None = None) -> FastAPI:
    tts = engine or IndexTTSEngine()
    app = FastAPI(title="IndexTTS-2.5 sidecar", version="1.0.0")
    app.state.engine = tts

    @app.get("/health")
    def health() -> dict[str, Any]:
        root = getattr(tts, "root", paths.default_index_tts_root())
        ready = paths.checkpoints_ready(root)
        return {
            "status": "ok" if ready else "missing_checkpoints",
            "engine": "indextts-2.5",
            "loaded": bool(tts.loaded()),
            "ready": ready,
            "checkpoints": str(paths.checkpoints_dir(root)),
            "origin": paths.DEFAULT_ORIGIN,
        }

    @app.post("/free")
    def free() -> dict[str, Any]:
        tts.free()
        return {"status": "ok", "loaded": False}

    def _synthesize(
        *,
        text: str,
        spk_path: str,
        lang: str | None,
        emotion: str | None,
        emo_vector: Any,
        emo_alpha: Any,
        duration_factor: Any,
        emo_audio_path: str | None = None,
        emo_text: str | None = None,
    ) -> bytes:
        line = str(text or "").strip()
        if not line:
            raise HTTPException(status_code=400, detail="text 不能为空")
        try:
            dest = tts.infer(
                spk_audio_prompt=spk_path,
                text=line,
                lang=protocol.detect_lang(line, lang),
                emo_vector=protocol.emotion_vector(emotion, emo_vector),
                emo_alpha=protocol.clamp_emo_alpha(emo_alpha),
                duration_factor=protocol.clamp_duration_factor(duration_factor),
                emo_audio_prompt=emo_audio_path,
                emo_text=emo_text,
            )
            return dest.read_bytes()
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("IndexTTS infer failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/v1/audio/speech")
    def speech(payload: SpeechRequest) -> Response:
        prompt = paths.default_speaker_prompt(getattr(tts, "root", None))
        if prompt is None:
            raise HTTPException(
                status_code=400,
                detail="无参考音时需要 examples/voice_01.wav，或改用 POST /v1/tts/clone 上传角色参考音。",
            )
        audio = _synthesize(
            text=payload.input,
            spk_path=str(prompt),
            lang=payload.lang,
            emotion=payload.emotion,
            emo_vector=payload.emo_vector,
            emo_alpha=payload.emo_alpha,
            duration_factor=payload.duration_factor,
        )
        return Response(content=audio, media_type="audio/wav")

    @app.post("/v1/tts/clone")
    async def clone(
        text: str = Form(...),
        lang: str | None = Form(default=None),
        emotion: str | None = Form(default=None),
        emo_vector: str | None = Form(default=None),
        emo_alpha: float | None = Form(default=None),
        duration_factor: float | None = Form(default=None),
        emo_text: str | None = Form(default=None),
        spk_audio: UploadFile | None = File(default=None),
        emo_audio: UploadFile | None = File(default=None),
    ) -> Response:
        if spk_audio is None:
            raise HTTPException(status_code=400, detail="请上传 spk_audio 参考音")
        spk_bytes = await spk_audio.read()
        if not spk_bytes:
            raise HTTPException(status_code=400, detail="参考音为空")
        suffix = Path(spk_audio.filename or "prompt.wav").suffix or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(spk_bytes)
            spk_path = handle.name
        emo_path = None
        try:
            if emo_audio is not None:
                emo_bytes = await emo_audio.read()
                if emo_bytes:
                    emo_suffix = Path(emo_audio.filename or "emo.wav").suffix or ".wav"
                    with tempfile.NamedTemporaryFile(suffix=emo_suffix, delete=False) as handle:
                        handle.write(emo_bytes)
                        emo_path = handle.name
            vector: Any = emo_vector
            if isinstance(emo_vector, str) and emo_vector.strip():
                try:
                    vector = json.loads(emo_vector)
                except json.JSONDecodeError:
                    vector = None
            audio = _synthesize(
                text=text,
                spk_path=spk_path,
                lang=lang,
                emotion=emotion,
                emo_vector=vector,
                emo_alpha=emo_alpha,
                duration_factor=duration_factor,
                emo_audio_path=emo_path,
                emo_text=emo_text,
            )
            return Response(content=audio, media_type="audio/wav")
        finally:
            for path in (spk_path, emo_path):
                if not path:
                    continue
                try:
                    os.unlink(path)
                except OSError:
                    pass

    @app.exception_handler(HTTPException)
    async def http_error(_request: Any, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app


app = create_app()


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "indextts_sidecar.server:app",
        host=paths.SIDECAR_HOST,
        port=paths.SIDECAR_PORT,
        factory=False,
    )


if __name__ == "__main__":
    main()
