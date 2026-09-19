# 内置短剧配音声线来源

工作台需要「一句参考音」才能让 IndexTTS 克隆角色。市面短剧音色大多来自剪映、魔音工坊、配音秀、MiniMax 等商业库，**不能下载进本仓库**。

本目录只收录 [IndexTTS 官方示例](https://huggingface.co/spaces/IndexTeam/IndexTTS-2-Demo/tree/main/examples)（`voice_01.wav` … `voice_12.wav`，无 `voice_10`），许可证为 [bilibili Model Use License Agreement](https://github.com/index-tts/index-tts/blob/main/LICENSE)。中文短剧角色名是产品侧听感归档，不是官方角色名。

缺失的 wav 会在首次试听时从 HuggingFace Space 再拉一次，保存到 `prompts/`。不要把模型权重放进本目录。
