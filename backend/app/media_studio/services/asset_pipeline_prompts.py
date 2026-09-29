"""Versioned, bounded excerpts of the two user-supplied documents.

Original files are never edited. Excerpts are method references, not instructions
to rewrite the adopted story or manufacture appearances absent from the source.
"""
from pathlib import Path
import hashlib
import json
import time

VERSION = "asset-shot-v1"
ROOT = Path(__file__).resolve().parents[4]
SOURCES = {
    "assets": ("skills/AI短片全流程/【资产库】全资产大师V3.0_场景+角色+道具_万能版.txt",
               [("全剧扫描", 39, 48), ("时代与身份", 204, 216), ("道具剧情功能", 361, 365)]),
    "shots": ("skills/AI短片全流程/分镜解析公开版.md",
              [("视听签名", 147, 173), ("单元戏剧功能", 819, 840),
               ("景别、机位、运镜与转场", 1013, 1116), ("角色定义与声音角色", 380, 415)]),
}
RULES = """规则优先级：已确认剧情、逐字对白和项目设置 > 工作流能力与 JSON 合同 > 本阶段适配 > 参考方法。
不重排、增删或改写故事。不发明人物、道具、外观；未知为未明确。示例不是用户剧本。
不强制真人写实或场景氛围人物。不机械套用镜数、反应镜、ASL、营销标签配额。
本阶段不生成资产生图卡、H3 正文、预算或 VFX 公司推荐。引用必须附原文证据。
具名角色独立记录，同人跨时代用不同造型；别名合并需证据，家庭不同的“母亲”不能自动合并。
所有待确认语义冲突必须报告 issues，不可把猜测当事实。"""

ASSET_SCOPE_RULES = """资产采用精简制作清单，不是原文物件清单。
人物的普通衣服、裤裙、鞋、佩饰归入人物造型描述，不单列 prop；普通家具、杂物和背景陈设归入场景描述。
只有承担独立剧情功能（关键交接、身份线索、触发事件）或原文明确要求辨认其独特外观的物件，才单列关键道具。
仅被拿着、穿着、碰触、发声或在动作中出现，不足以证明需要独立资产。普通穿戴即使被看见也保留在动作和造型文字中。
服饰若确为独立线索或关键交接物可例外单列，但必须有原文证据；不按品类黑名单删掉剧情物件。
已有清单或资产库只用于有证据的身份复用，不要求沿用其中所有旧物件。未知剧情作用不补造，默认不单列。
同一人的年龄或服装变化用造型表达，不因此新增另一个角色身份；不同人仍需证据区分。
资产存在不等于视频必须输入其图片。视频默认优先人物造型，关键道具仅在需要锁定外观时由用户选择参考图；工作流上限不是凑图目标。"""


def adapter(stage):
    path, sections = SOURCES[stage]
    content = (ROOT / path).read_bytes()
    lines = content.decode("utf-8-sig").splitlines()
    excerpt = "\n\n".join(f"【{name}】\n" + "\n".join(lines[start-1:end]) for name, start, end in sections)
    return {"version": VERSION, "path": path, "sha256": hashlib.sha256(content).hexdigest(),
            "sections": [{"name": n, "start": s, "end": e} for n, s, e in sections],
            "system": RULES + "\n以下为选用方法，任何示例与格式以本次合同覆盖：\n" + excerpt
            + ("\n本次资产范围（覆盖参考方法中的全物件扫描）：\n" + ASSET_SCOPE_RULES if stage == "assets" else "")}


def request(stage, system, user, evidence, checkpoint=lambda: None, **kwargs):
    """Persist the exact request before network I/O, including failed attempts."""
    from .llm_service import LlmService
    from ..provider_bridge import llm_row
    from ...llm_request_policy import chat_policy, chat_parameters
    provider = llm_row() or {}
    policy = chat_policy(str(provider.get("model") or ""), str(provider.get("base_url") or ""))
    requested = dict(kwargs)
    # Mandatory reasoning can consume legacy stage budgets before complete JSON.
    # A single explicit ceiling; never disable mandatory thinking or retry unboundedly.
    if policy.thinking_required:
        kwargs["max_tokens"] = max(int(kwargs.get("max_tokens", 12000)), 32768)
    effective = chat_parameters(policy, temperature=kwargs.get("temperature", 0.4),
                                max_tokens=kwargs.get("max_tokens", 6000),
                                reasoning_effort=provider.get("reasoning_effort") if provider.get("reasoning_effort") != "auto" else None)
    record = {"stage": stage, "system": system, "user": user,
              "model": provider.get("model"), "reasoning_effort": provider.get("reasoning_effort"),
              "parameters": kwargs, "requested_parameters": requested, "effective_parameters": effective, "parameter_policy": policy.name,
              "status": "running"}
    evidence.append(record)
    checkpoint()
    start = time.monotonic()
    try:
        raw = LlmService.chat_text(system, user, meta_out=record.setdefault("response_metadata", {}), **kwargs)
        record.update(raw=raw, status="returned")
        return raw
    except Exception as err:
        # Do not store HTTP errors containing headers/credentials.
        record.update(status="failed", error_type=type(err).__name__)
        raise
    finally:
        record["elapsed_ms"] = round((time.monotonic() - start) * 1000)
        checkpoint()


def strict_object(raw, keys):
    from .llm_service import LlmService
    result = LlmService._parse_json_object(raw)
    if not isinstance(result, dict) or set(result) != set(keys):
        raise ValueError("INVALID_JSON: 返回字段不符合阶段合同")
    return result
