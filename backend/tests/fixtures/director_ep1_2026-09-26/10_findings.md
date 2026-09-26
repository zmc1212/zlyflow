# P0 取证结论（导演台第 1 集满意版效果恢复）

- 项目：proj-0f9c8015281149f0
- 分集：ep-4d89a8df80a4(穿越危机)，shots_count=27
- 取证导出时间：2026-09-26 20:28:09

## 一、满意视频定位结果

满意稿基线时间：2026-09-24 15:04:21（tmp/director_ep1_shots1-2_prompt.txt）

先按父线索定位问题任务相邻的“2 段视频”任务（满意稿为两镜）：

- 候选 job-9d02637de237｜2026-09-25 13:23:59（距满意稿 22.33 小时）｜生成Director 选中 2 段视频：第 1 集 穿越危机｜https://img.zlyun168.com/zly-ai-video-studio/video/20260925/133831_a1fbb569cb056ce7.mp4
- 该候选仅按“标题为 2 段视频 + 时间最接近满意稿”推断，数据库无显式关联字段，属**高可能但未证实**。

项目内 9 月 20–26 日、completed 且带 result_url 的视频任务全量清单（按时间倒序）：

- job-c8e727e646a3｜2026-09-26 19:33:58｜生成Director 选中 3 段视频：第 1 集 穿越危机｜https://img.zlyun168.com/zly-ai-video-studio/video/20260926/195205_928535ce3114173e.mp4
- job-4477b4053da1｜2026-09-26 18:13:21｜生成Director 选中 2 段视频：第 1 集 穿越危机｜https://img.zlyun168.com/zly-ai-video-studio/video/20260926/184315_1caf839f04705d8e.mp4
- job-3b353200eda8｜2026-09-26 18:12:31｜生成Director 选中 3 段视频：第 1 集 穿越危机｜https://img.zlyun168.com/zly-ai-video-studio/video/20260926/183053_0d67fffebd3450eb.mp4
- job-95aa2a630fbd｜2026-09-26 13:17:49｜生成Director 选中 3 段视频：第 1 集 穿越危机｜https://img.zlyun168.com/zly-ai-video-studio/video/20260926/133618_0a3b9c4238a8087e.mp4
- job-9d02637de237｜2026-09-25 13:23:59｜生成Director 选中 2 段视频：第 1 集 穿越危机｜https://img.zlyun168.com/zly-ai-video-studio/video/20260925/133831_a1fbb569cb056ce7.mp4
- job-72cc047a71be｜2026-09-22 02:31:25｜生成整集视频：第 1 集 硕士穿越，醒来成了穷小子｜https://img.zlyun168.com/zly-ai-video-studio/video/20260922/032752_921ebae730229b66.mp4
- job-bc29708d2d4f｜2026-09-21 20:49:41｜生成Beat 2视频：第 1 集 硕士穿越，醒来成了穷小子｜https://img.zlyun168.com/zly-ai-video-studio/video/20260921/205744_db29769631fe016f.mp4
- job-6174f1915aa1｜2026-09-21 13:25:42｜生成Beat 1视频：第 1 集 硕士穿越，醒来成了穷小子｜https://img.zlyun168.com/zly-ai-video-studio/video/20260921/161434_78d2289c3e866e3b.mp4
- job-062c53d4bd8a｜2026-09-21 10:32:15｜生成选中 2 镜（Beat 1、2）视频：第 1 集 硕士穿越，醒来成了穷小子｜https://img.zlyun168.com/zly-ai-video-studio/video/20260921/110416_f440b2f7e24cb9c5.mp4
- job-a1c8e8ed6deb｜2026-09-21 00:32:39｜生成选中 2 镜（Beat 1、2）视频：第 1 集 硕士穿越，醒来成了穷小子｜https://img.zlyun168.com/zly-ai-video-studio/video/20260921/010320_7d26face9358a9a2.mp4
- job-ffd87eb217b8｜2026-09-20 21:19:13｜生成选中 2 镜（Beat 1、2）视频：第 1 集 硕士穿越，醒来成了穷小子｜https://img.zlyun168.com/zly-ai-video-studio/video/20260920/215240_c4c4b4ffcd1c6515.mp4
- job-d3d9a45da206｜2026-09-20 17:39:10｜生成Beat 1视频：第 1 集 硕士穿越，醒来成了穷小子｜https://img.zlyun168.com/zly-ai-video-studio/video/20260920/180542_c43c16e345bcecea.mp4

## 二、问题稿 vs 满意稿 逐镜 diff 摘要

payload_json 大小：214378 字节；其中 shots[] 共 3 镜，最终提示词取自 h3_prompt/prompt 字段（prompt_source=prompt_master_director, prompt_profile=director_segments）。

- global_prompt：满意稿主体定义段 350 字 vs payload global_prompt 302 字，归一化相似度 0.313。
- 结构标记：满意稿含 ['【主体】', '【动作】', '【镜头】', '【音效】', '【约束】']；payload 含 ['【主体】', '【动作】', '【镜头】', '【音效】', '【约束】']。

满意稿共解析出 2 镜；问题 payload 共 3 镜。

### Shot 1｜0–8秒｜中景·伏案研读

- 最终字段：h3_prompt（h3_prompt_source=workshop_v7, beat_id=beat-c99c747a1e46）
- 时长：满意稿 0.0–8.0秒 vs payload 0.0–8.0秒（一致）
- 景别：满意稿 中景 vs payload 中景（一致）
- 台词：一致｜满意稿 ['[中文] ‘青山遮不住，毕竟东流去’……这诗风，不像宋人笔法。']｜payload ['[中文] ‘青山遮不住，毕竟东流去’……这诗风，不像宋人笔法。']
- 段落细化标记：满意稿 ['【主体】', '【动作】', '【镜头】', '【音效】', '【约束】'] vs payload ['【主体】', '【动作】', '【镜头】', '【音效】', '【约束】']
- 文本：不一致（归一化相似度 0.343；满意稿 521 字 vs payload 643 字）

### Shot 2｜8–16秒｜近景·提笔记录

- 最终字段：h3_prompt（h3_prompt_source=workshop_v7, beat_id=beat-5949bf77b487）
- 时长：满意稿 8.0–16.0秒 vs payload 8.0–16.0秒（一致）
- 景别：满意稿 近景 vs payload None（不一致）
- 台词：一致｜满意稿 ['[中文] 再查查出处，应该还有线索。']｜payload ['[中文] 再查查出处，应该还有线索。']
- 段落细化标记：满意稿 ['【主体】', '【动作】', '【镜头】', '【音效】', '【约束】'] vs payload ['【主体】', '【动作】', '【镜头】', '【音效】', '【约束】']
- 文本：不一致（归一化相似度 0.357；满意稿 533 字 vs payload 676 字）

### payload 多出的镜头

- 第 3 镜：16.0–24.0秒，景别 全景，508 字，beat_id=beat-cba65156421e，台词 []。满意稿中无此镜。


## 三、问题任务基本信息

- id：job-3b353200eda8
- job_type：video_generation
- title：生成Director 选中 3 段视频：第 1 集 穿越危机
- status：completed（progress=100）
- created_at：2026-09-26 18:12:31
- completed_at：2026-09-26 18:30:57
- result_url：https://img.zlyun168.com/zly-ai-video-studio/video/20260926/183053_0d67fffebd3450eb.mp4
- error_message：None

## 四、当前 Provider 配置

- ComfyUI base_url：http://192.168.10.54:8188
- LLM model：deepseek-v4.1-flash
- VLM model：glm-4v-flash
- vlm.use_llm_credentials：1

## 五、备注

- 满意版候选视频在线校验（只读 HEAD 请求，不下载）：job-9d02637de237（2 段视频，9/25）HTTP 200，1,984,224 字节；job-4477b4053da1（2 段视频，9/26 18:13）HTTP 200，1,356,706 字节；问题任务 job-3b353200eda8 HTTP 200，1,524,909 字节。三条链接均仍可访问。
- 满意版尚存的原始提示词证据只有 tmp/director_ep1_shots1-2_prompt.txt；该文件的提示词如何写入任务 payload 的过程未在库中留痕，建议恢复开发时以本满意稿为回归基线。
- 无异常。本目录所有文件均由 export_p0_fixtures.py 只读导出。
