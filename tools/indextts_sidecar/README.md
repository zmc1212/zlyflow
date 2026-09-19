# IndexTTS-2.5 旁路推理服务

工作台 **不** 把 IndexTTS / PyTorch / CUDA 装进 FastAPI 虚拟环境。本目录是独立进程，默认监听 `http://127.0.0.1:7866`。

## 权重位置

不要下载进本仓库。放到工作台**父级**整合包：

```text
<工作台父目录>/整合包及模型/index-tts/checkpoints/config.yaml
```

也可用环境变量 `ZLY_AI_VIDEO_STUDIO_INDEXTTS_ROOT` 指向 `index-tts` 根目录或 `checkpoints` 目录。

无参考音时的 `/v1/audio/speech` 兜底会读取 `index-tts/examples/voice_01.wav`（可选）。配音台真正走 `POST /v1/tts/clone`。

## 启动

1. 按官方 [IndexTTS-2.5](https://github.com/index-tts/index-tts) 用 `uv` 建独立环境（可跳过 DeepSpeed；CUDA 12.8+）。
2. 在该环境执行：`pip install -r tools/indextts_sidecar/requirements.txt`
3. 双击仓库根目录 `启动 IndexTTS 旁路.bat`，或：

```text
set PYTHONPATH=<工作台>/tools
<IndexTTS Python> -m indextts_sidecar.server
```

许可证是 Bilibili Model Use License：工作室自用可商用；月活超 1 亿或年收超 10 亿才需另签。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 进程与权重是否就绪；`loaded` 表示模型是否在显存里 |
| POST | `/free` | 卸载 GPU 上的 IndexTTS |
| POST | `/v1/audio/speech` | OpenAI 兼容 JSON，无参考音时用默认 prompt |
| POST | `/v1/tts/clone` | multipart：`spk_audio` + `text` + `lang` / `emotion` / `emo_vector` / `emo_alpha` / `duration_factor` |

工作台在「管理设置 → TTS」选择「本机 IndexTTS-2.5」后，Base URL 为 `http://127.0.0.1:7866/v1`。H3 出片前会打 `/free`；配音任务领取前会对 ComfyUI `POST /free`。不要和第二套 ComfyUI 抢卡。
