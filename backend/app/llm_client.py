from __future__ import annotations

import re
from typing import Any
import requests


class LlmError(RuntimeError):
    pass


class LlmTemporaryError(LlmError):
    pass


SYSTEM_PROMPT_OPTIMIZE_VIDEO = """你是一位顶级的 AI 视频生成提示词专家（精通 MiniMax、Runway、Sora、LTX-Video 等模型）。
你的任务是将用户输入的简短粗糙的视频想法，扩写并优化为高质量、高表现力、电影级质感的提示词。

优化原则：
1. 画面主体与动作：清晰描述主体外观特征、具体动作变化及动态过程。
2. 镜头与运镜：明确景别（特写/中景/全景）与镜头运动方式（缓慢推近、平移跟随、低角度仰拍、航拍俯瞰等）。
3. 光影与色彩：描述光线来源与质感（如晨光侧逆光、丁达尔光效、冷暖对比色调、电影级调色）。
4. 氛围与细节：补充环境动态细节（如微风拂动、粒子漂浮、雨滴水花等）。
5. 结构保留：若原提示词中包含 `<Picture 1>`、`<Picture 2>` 等参考图标记，必须在对应主体位置原样保留这些标记，不得删除或更改序号。
6. 输出格式：直接输出优化后的提示词文本，严禁包含任何前言、解释、分析或 markdown 格式块。输出纯文本。

重要：你不需要也不允许输出任何思考过程、分析过程、推理过程或内心独白。直接输出最终结果即可。"""

SYSTEM_PROMPT_OPTIMIZE_IMAGE = """你是一位顶级的 AI 绘画与图像生成提示词专家（精通 Midjourney、Stable Diffusion、FLUX、GPT-Image 等模型）。
你的任务是将用户输入的简短粗糙的图像创意，优化为具有丰富细节、高审美构图与强烈艺术氛围的高质量提示词。

优化原则：
1. 画面主体：精准刻画主体的形态、材质、服饰、姿态与神情。
2. 构图与视角：明确构图法则（黄金分割、对称构图、主观视角等）与空间景深。
3. 光影与色彩：细化光源方向、光质（柔光、强光、戏剧性高光）与色彩搭配方案。
4. 细节与质感：增强材质纹理细节与环境真实感/艺术质感。
5. 输出格式：直接输出优化后的提示词文本，严禁包含任何前言、解释、分析或 markdown 格式块。输出纯文本。

重要：你不需要也不允许输出任何思考过程、分析过程、推理过程或内心独白。直接输出最终结果即可。"""


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _json(self, response: requests.Response, action: str) -> dict[str, Any]:
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise LlmTemporaryError(f"大模型服务 {action} 暂时不可用（HTTP {response.status_code}）：{response.text[:200]}")
        if response.status_code >= 400:
            try:
                err_payload = response.json()
                msg = err_payload.get("error", {}).get("message") or err_payload.get("message") or response.text[:200]
            except Exception:
                msg = response.text[:200]
            raise LlmError(f"大模型服务 {action} 失败（HTTP {response.status_code}）：{msg}")
        try:
            payload = response.json()
        except ValueError as error:
            raise LlmError(f"大模型服务 {action} 返回了无效 JSON 响应") from error
        if not isinstance(payload, dict):
            raise LlmError(f"大模型服务 {action} 返回格式异常")
        return payload

    def list_models(self, timeout: float = 10.0) -> list[str]:
        url = f"{self.base_url}/models"
        try:
            response = self.session.get(url, headers=self.headers, timeout=timeout)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                    return [str(item["id"]) for item in data["data"] if isinstance(item, dict) and "id" in item]
        except Exception:
            pass
        return []

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 关闭 Qwen3 / Qwen2.5 思考模式（enable_thinking=False），
            # 不支持此参数的模型会忽略该字段，不影响兼容性
            "enable_thinking": False,
        }
        try:
            response = self.session.post(url, headers=self.headers, json=payload, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            raise LlmTemporaryError(f"请求大模型服务异常：{exc}") from exc

        try:
            data = self._json(response, "对话推理")
        except LlmError as error:
            err_text = str(error)
            if "has no provider supported" in err_text or "not found" in err_text.lower():
                available_models = self.list_models()
                if available_models:
                    top_models = ", ".join(available_models[:6])
                    raise LlmError(
                        f"模型 '{model}' 当前平台未开放或不支持直接推理。平台当前开放可用模型推荐：{top_models}"
                    ) from error
            raise

        raw = self._extract_response_content(data)
        content = self._strip_thinking(raw)
        if not content:
            raise LlmError("大模型返回的内容为空")
        return content

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """清洗推理模型在 content 中混入的思考过程。

        处理以下已知格式：
        1. <think>…</think> 标签块（Qwen3 / DeepSeek 等）
        2. /think 截断标记（部分平台将 </think> 替换为 /think）
        3. 思考块结束后的空白
        """
        if not text:
            return text

        # 1. 去掉 <think>…</think> 完整块（可能多个，允许跨行）
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)

        # 2. 去掉 /think 截断标记及其之前的所有内容（部分平台格式）
        if "/think" in cleaned.lower():
            parts = re.split(r"/think", cleaned, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                cleaned = parts[1]

        # 3. 去掉未被标签包裹但以「用户提供的是」「我需要」「让我」等中文推理前缀开头的段落
        #    策略：若整体内容以 <think> 开头但没有闭合标签，取最后一个空行之后的部分
        if cleaned.strip().startswith("<think"):
            # 未闭合的思考块，取最后连续非空段落
            paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
            if paragraphs:
                cleaned = paragraphs[-1]

        return cleaned.strip()

    def _extract_response_content(self, data: dict[str, Any]) -> str:
        # 1. 标准 OpenAI 格式: data["choices"][0]["message"]["content"]
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                msg = first_choice.get("message")
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if content and str(content).strip():
                        return str(content).strip()
                    # 兼容深度思考/推理模型 (如 DeepSeek R1)
                    reasoning = msg.get("reasoning_content")
                    if reasoning and str(reasoning).strip():
                        return str(reasoning).strip()
                # 兼容 completions 格式: choices[0]["text"]
                if "text" in first_choice and first_choice["text"]:
                    return str(first_choice["text"]).strip()

        # 2. 阿里云 DashScope / ModelScope 任务格式: data["output"]["text"] 或 data["output"]["choices"]
        output = data.get("output")
        if isinstance(output, dict):
            if "text" in output and output["text"]:
                return str(output["text"]).strip()
            nested_choices = output.get("choices")
            if isinstance(nested_choices, list) and nested_choices:
                first_nc = nested_choices[0]
                if isinstance(first_nc, dict):
                    msg = first_nc.get("message")
                    if isinstance(msg, dict) and msg.get("content"):
                        return str(msg["content"]).strip()
                    if "text" in first_nc and first_nc["text"]:
                        return str(first_nc["text"]).strip()

        # 3. 常见直接返回字段: response, result, content, text, generated_text
        for key in ("response", "result", "content", "text", "generated_text"):
            val = data.get(key)
            if val and isinstance(val, str) and val.strip():
                return val.strip()

        # 4. 如果上游在 HTTP 200 中返回了错误对象
        for err_key in ("error", "error_message", "message", "Message", "err_msg", "msg"):
            err_val = data.get(err_key)
            if isinstance(err_val, dict) and "message" in err_val:
                raise LlmError(f"大模型返回错误：{err_val['message']}")
            if isinstance(err_val, str) and err_val.strip() and err_val.lower() not in {"success", "ok"}:
                raise LlmError(f"大模型返回提示：{err_val.strip()}")

        # 5. 若无法解析，输出清晰响应摘要以便排查
        data_preview = str(data)[:300]
        raise LlmError(f"大模型响应格式不匹配（未找到 choices 或 output 内容）。返回数据：{data_preview}")

    def test_connection(self, model: str) -> str:
        messages = [
            {"role": "user", "content": "你好，请仅回复两个字：收到。"}
        ]
        return self.chat_completion(messages, model=model, temperature=0.1, max_tokens=32, timeout=15.0)



    def optimize_prompt(
        self,
        prompt: str,
        *,
        media_type: str = "video",
        workflow_name: str | None = None,
        skill_id: str | None = None,
        reference_count: int = 0,
        workflow_id: str | None = None,
        model: str,
    ) -> str:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise LlmError("提示词内容不能为空")

        from .llm_minimax_skills import build_h3_system_prompt

        system_instruction = build_h3_system_prompt(
            skill_id=skill_id,
            reference_count=reference_count,
            media_type=media_type,
            workflow_name=workflow_name,
        )
        user_content = f"原始创意需求：{clean_prompt}"
        if workflow_name:
            user_content += f"\n当前工作流名称：{workflow_name}"
        if workflow_id:
            user_content += f"\n当前工作流 ID：{workflow_id}"
        if reference_count > 0:
            user_content += f"\n已上传参考图数量：{reference_count} 张"

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ]
        optimized = self.chat_completion(messages, model=model, temperature=0.7, max_tokens=1536, timeout=60.0)
        # 移除模型可能包裹的 markdown 代码块标签（如 ``` 或 ```markdown ）
        if optimized.startswith("```") and optimized.endswith("```"):
            lines = optimized.splitlines()
            if len(lines) >= 3:
                optimized = "\n".join(lines[1:-1]).strip()
        return optimized

