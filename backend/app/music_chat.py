"""「音乐对话创作」服务：多轮对话持续迭代歌曲参数，提案确认后入队 YuE2 生成。

流程：POST /api/music/chats（可锚定已有歌曲）→ 每轮 POST messages：
先落库用户消息 → 组「系统提示词 + 基准快照 + 最近历史 + 本轮输入」→ LLM 输出 JSON 提案 →
落库助手消息（proposal_json）→ 用户点生成 → generate_from_proposal 复用 MusicJobService.enqueue
入队并回填 message.job_id / chat.anchor_job_id，任务带 chat_id 形成版本链。
快照永远以 anchor 任务行（title/style/lyrics/duration）为唯一事实，历史只提供意图连续性。
"""
from __future__ import annotations

import json
import queue
import re
import threading
import uuid
from typing import Any

from .director_stream import _decode_partial_string
from .llm_client import LlmError
from .music_job_service import MusicJobService
from .storage import JobStore, now

MAX_CHAT_INPUT_LENGTH = 2000
MAX_CHAT_HISTORY_MESSAGES = 16
CHAT_TITLE_DEFAULT = "新对话"
ALLOWED_OUTPUT_FORMATS = ("flac", "mp3", "wav")

MUSIC_CHAT_SYSTEM_PROMPT = """你是「ZLY AI 视频工作台」的音乐创作助手，在对话中帮用户持续迭代一首歌：从一句话灵感从零创作，或基于已生成的歌曲修改标题、风格与歌词。你的输出会交给 YuE2 作曲引擎生成音频。

每轮输入的第一条消息是「当前基准歌曲参数快照」（可能标注为空，表示从零创作），随后是历史修改对话和用户最新这句话。

只输出一个 JSON 对象，不要任何解释或 Markdown 代码块：
{
  "reply": "给用户看的简短回复：说明你理解了什么、动了哪些地方；纯提问或闲聊时正常回答，1-3 句",
  "changed": true 或 false,
  "title": "歌曲标题，中文，不超过 20 字",
  "style": "一句英文标签串，逗号分隔，12-50 词，固定顺序：演唱语言 → 曲风/子曲风 → 主唱（性别/音色/唱法，纯音乐写 instrumental）→ 关键乐器与质感 → 情绪与旋律特征 → 结尾 N BPM。禁止指令句，禁止中文。",
  "lyrics": "完整歌词。分节标签 [Intro]、[Verse 1]、[Verse 2]、[Pre-Chorus]、[Chorus]、[Bridge]、[Outro] 各占一行，节与节之间空一行，每行一句歌词。纯音乐时输出空字符串。",
  "duration_seconds": 210
}

修改规则（最重要）：
- 用户只是在提问、求解释或闲聊时：changed=false，title/style/lyrics/duration_seconds 原样回传快照里的值，禁止趁机改词改曲风。
- 局部修改：style 只增删用户涉及的标签，其余逐字保留；lyrics 只改用户指名的段落或行，其余行逐字保留；分节标签结构保持。
- 从零创作或整体重写：按快照为空的 vibe 规范扩写；用户没提演唱语言时默认写中文歌词；歌词要与用户描述的故事或情绪强相关，副歌要有记忆点。
- 歌词量与时长匹配：约 60 秒写 1-2 节主歌加 1 段副歌；约 210 秒写完整 主歌-预副歌-副歌-桥段-尾奏 结构。
- duration_seconds 只在用户明确提出时长时更改，10-600 之间的整数；其余情况回传快照值。
- changed=true 时所有字段都必须是修改后的完整最终值（整份歌词全文，不是增量描述或差异说明）。"""


class MusicChatError(ValueError):
    """对话业务规则错误（内容不合法、无可生成提案等）；路由映射为 422。"""


class MusicChatNotFoundError(MusicChatError):
    """对话/消息/锚点不存在；路由映射为 404。"""


def create_chat(store: JobStore, owner_user_id: str, *, anchor_job_id: str | None = None) -> dict[str, Any]:
    if anchor_job_id:
        anchor = store.get_music_job(anchor_job_id, owner_user_id=owner_user_id)
        if not anchor:
            raise MusicChatNotFoundError("锚定的歌曲不存在")
    chat_id = f"mchat-{uuid.uuid4().hex[:12]}"
    timestamp = now()
    title = CHAT_TITLE_DEFAULT
    if anchor_job_id:
        anchor = store.get_music_job(anchor_job_id, owner_user_id=owner_user_id)
        title = f"改《{(anchor or {}).get('title') or '未命名歌曲'}》"
    return store.create_music_chat({
        "id": chat_id,
        "owner_user_id": owner_user_id,
        "title": title,
        "anchor_job_id": anchor_job_id,
        "created_at": timestamp,
        "updated_at": timestamp,
    })


def _anchor_snapshot(store: JobStore, chat: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """返回 (快照, 刷新后的 chat)。锚点任务被删时清空 anchor 视为从零创作。"""
    anchor_job_id = str(chat.get("anchor_job_id") or "")
    if not anchor_job_id:
        return None, chat
    job = store.get_music_job(anchor_job_id)
    if not job:
        chat = store.update_music_chat(str(chat["id"]), anchor_job_id=None) or chat
        return None, chat
    params = job.get("params") or {}
    return {
        "title": str(job.get("title") or ""),
        "style": str(job.get("style") or ""),
        "lyrics": str(job.get("lyrics") or ""),
        "duration_seconds": job.get("duration_seconds") or params.get("duration_seconds"),
        "status": str(job.get("status") or ""),
    }, chat


def _snapshot_message(snapshot: dict[str, Any] | None) -> dict[str, str]:
    if snapshot:
        body = (
            "当前基准歌曲参数快照：\n"
            + json.dumps(snapshot, ensure_ascii=False, indent=2)
            + "\n\n以下是修改对话历史；最后一条是用户最新这句话。"
        )
    else:
        body = "当前基准歌曲参数快照：空（从零创作）。\n\n以下是修改对话历史；最后一条是用户最新这句话。"
    return {"role": "user", "content": body}


def _history_messages(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """历史消息：用户带原文，助手只带 reply 文本；参数状态由快照承载，避免重复增长。"""
    messages: list[dict[str, str]] = []
    for row in rows:
        role = str(row.get("role") or "")
        content = str(row.get("content") or "")
        if not content:
            continue
        if role not in ("user", "assistant"):
            continue
        messages.append({"role": role, "content": content})
    return messages[-MAX_CHAT_HISTORY_MESSAGES:]


def _clamp_proposal(parsed: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    changed = bool(parsed.get("changed"))
    reply = str(parsed.get("reply") or "").strip() or "收到，我们继续。"
    fallback_title = str((snapshot or {}).get("title") or "")
    fallback_style = str((snapshot or {}).get("style") or "")
    fallback_lyrics = str((snapshot or {}).get("lyrics") or "")
    fallback_duration = (snapshot or {}).get("duration_seconds")
    title = str(parsed.get("title") or fallback_title).strip()[:120]
    style = str(parsed.get("style") or fallback_style).strip()[:2000]
    lyrics = str(parsed.get("lyrics") or fallback_lyrics).strip()[:8000]
    try:
        duration = int(parsed.get("duration_seconds") or fallback_duration or 210)
    except (TypeError, ValueError):
        duration = 210
    duration = max(10, min(600, duration))
    if changed and not style:
        raise LlmError("音乐助手没有返回有效的风格参数，请重试")
    return {
        "changed": changed,
        "reply": reply[:500],
        "title": title,
        "style": style,
        "lyrics": lyrics,
        "duration_seconds": duration,
    }


def _prepare_round(
    store: JobStore,
    chat_id: str,
    owner_user_id: str,
    content: str,
    *,
    duration_seconds: int | None = None,
    instrumental: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]], dict[str, Any] | None]:
    """对话轮次公共准备：校验输入、落库用户消息、组装 LLM 上下文。"""
    text = str(content or "").strip()
    if not text:
        raise MusicChatError("消息内容不能为空")
    if len(text) > MAX_CHAT_INPUT_LENGTH:
        raise MusicChatError(f"单条消息不能超过 {MAX_CHAT_INPUT_LENGTH} 字")
    chat = store.get_music_chat(chat_id, owner_user_id=owner_user_id)
    if not chat:
        raise MusicChatNotFoundError("对话不存在")

    snapshot, chat = _anchor_snapshot(store, chat)
    user_message = store.append_music_chat_message({
        "id": f"mmsg-{uuid.uuid4().hex[:12]}",
        "chat_id": chat_id,
        "role": "user",
        "content": text,
        "created_at": now(),
    })
    rows = store.list_music_chat_messages(chat_id)
    # 刚落库的用户消息就是最后一条；之前的作为历史上下文
    history = _history_messages(rows[:-1])
    snapshot_message = _snapshot_message(snapshot)
    if duration_seconds is not None or instrumental is not None:
        voice = "纯音乐" if instrumental else "人声歌曲"
        snapshot_message = {
            "role": "user",
            "content": snapshot_message["content"] + f"\n\n用户本轮在界面上指定：{voice}、目标时长约 {int(duration_seconds or 210)} 秒。修改提案应遵循这两个期望（纯音乐时歌词为空）。",
        }
    messages = [
        {"role": "system", "content": MUSIC_CHAT_SYSTEM_PROMPT},
        snapshot_message,
        *history,
        {"role": "user", "content": text},
    ]
    return chat, user_message, messages, snapshot


def send_music_chat_message(
    store: JobStore,
    chat_id: str,
    owner_user_id: str,
    content: str,
    llm_provider: Any,
    *,
    duration_seconds: int | None = None,
    instrumental: bool | None = None,
) -> dict[str, Any]:
    """一轮对话（同步）：用户消息先落库（LLM 失败不丢），再取提案落库为助手消息。"""
    if llm_provider is None:
        raise LlmError("大模型服务尚未初始化")
    chat, user_message, messages, snapshot = _prepare_round(
        store, chat_id, owner_user_id, content,
        duration_seconds=duration_seconds, instrumental=instrumental,
    )
    parsed = llm_provider.chat_json_messages(messages)
    if not isinstance(parsed, dict):
        raise LlmError("音乐助手未返回有效的提案，请重试")
    proposal = _clamp_proposal(parsed, snapshot)
    assistant_message = store.append_music_chat_message({
        "id": f"mmsg-{uuid.uuid4().hex[:12]}",
        "chat_id": chat_id,
        "role": "assistant",
        "content": proposal["reply"],
        "proposal": {key: proposal[key] for key in ("changed", "title", "style", "lyrics", "duration_seconds")},
        "created_at": now(),
    })
    chat = store.update_music_chat(chat_id) or chat
    return {"chat": chat, "user_message": user_message, "assistant_message": assistant_message}


_REPLY_FIELD = re.compile(r'"reply"\s*:\s*"')


def _extract_partial_reply(text: str) -> str:
    """从累积的部分 JSON 文本里实时解出 reply 字段内容（未闭合也算）。"""
    match = _REPLY_FIELD.search(text)
    if not match:
        return ""
    value, _ = _decode_partial_string(text, match.end())
    return value


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_music_chat_message(
    store: JobStore,
    chat_id: str,
    owner_user_id: str,
    content: str,
    llm_provider: Any,
    *,
    duration_seconds: int | None = None,
    instrumental: bool | None = None,
):
    """一轮对话（SSE 流式）：user_message → delta*（reply 逐字）→ done/error。

    LLM 调用跑在守护线程里，on_chunk 的部分 JSON 预览经队列转发为 delta 事件；
    解析成功后落库助手消息并发 done。用户消息在流开始前已落库，失败不丢。"""
    if llm_provider is None:
        raise LlmError("大模型服务尚未初始化")
    chat, user_message, messages, snapshot = _prepare_round(
        store, chat_id, owner_user_id, content,
        duration_seconds=duration_seconds, instrumental=instrumental,
    )

    def generate():
        yield _sse_event("user_message", {"message": user_message})
        result_queue: queue.Queue = queue.Queue()
        emitted = 0

        def on_chunk(text: str) -> None:
            nonlocal emitted
            reply = _extract_partial_reply(text)
            if len(reply) > emitted:
                result_queue.put(("delta", reply[emitted:]))
                emitted = len(reply)

        def run_llm() -> None:
            try:
                parsed = llm_provider.chat_json_messages_stream(messages, on_chunk)
                result_queue.put(("parsed", parsed))
            except BaseException as error:  # LlmError/解析失败/未知异常都走 error 事件
                result_queue.put(("error", error))

        threading.Thread(target=run_llm, daemon=True).start()
        while True:
            kind, payload = result_queue.get()
            if kind == "delta":
                yield _sse_event("delta", {"text": payload})
                continue
            break

        if kind == "error":
            message = str(payload) if isinstance(payload, (LlmError, MusicChatError, ValueError)) else "音乐助手暂时没有接上，请重试"
            yield _sse_event("error", {"message": message[:300]})
            return
        try:
            proposal = _clamp_proposal(payload, snapshot)
        except (LlmError, ValueError) as error:
            yield _sse_event("error", {"message": str(error)[:300]})
            return
        assistant_message = store.append_music_chat_message({
            "id": f"mmsg-{uuid.uuid4().hex[:12]}",
            "chat_id": chat_id,
            "role": "assistant",
            "content": proposal["reply"],
            "proposal": {key: proposal[key] for key in ("changed", "title", "style", "lyrics", "duration_seconds")},
            "created_at": now(),
        })
        chat = store.update_music_chat(chat_id) or chat
        yield _sse_event("done", {
            "user_message": user_message,
            "assistant_message": assistant_message,
            "chat": chat,
        })

    return generate()


def generate_from_proposal(
    store: JobStore, chat_id: str, owner_user_id: str, message_id: str
) -> dict[str, Any]:
    """把提案卡入队为音乐任务；同一消息幂等，不重复占用远端 GPU。"""
    chat = store.get_music_chat(chat_id, owner_user_id=owner_user_id)
    if not chat:
        raise MusicChatNotFoundError("对话不存在")
    message = store.get_music_chat_message(message_id)
    if not message or str(message.get("chat_id")) != chat_id:
        raise MusicChatNotFoundError("提案消息不存在")
    proposal = message.get("proposal") or {}
    if str(message.get("role")) != "assistant" or not proposal.get("changed"):
        raise MusicChatError("该消息没有可生成的修改提案")

    existing_job_id = str(message.get("job_id") or "")
    if existing_job_id:
        job = store.get_music_job(existing_job_id)
        if job:
            return job

    # 生成参数沿用锚点任务的 cot/adapters，保持 LoRA 与 CoT 选择跨版本稳定
    anchor_job = store.get_music_job(str(chat.get("anchor_job_id") or "")) if chat.get("anchor_job_id") else None
    anchor_params = (anchor_job or {}).get("params") or {}
    job = MusicJobService.enqueue(
        owner_user_id,
        title=str(proposal.get("title") or "").strip(),
        style=str(proposal.get("style") or "").strip(),
        lyrics=str(proposal.get("lyrics") or "").strip(),
        duration_seconds=int(proposal.get("duration_seconds") or 210),
        output_format=str(anchor_params.get("output_format") or "flac"),
        steps=anchor_params.get("steps"),
        seed=anchor_params.get("seed"),
        lm_seed=anchor_params.get("lm_seed"),
        cot=str(anchor_params.get("cot") or "full"),
        adapters=anchor_params.get("adapters") or None,
        chat_id=chat_id,
    )
    store.update_music_chat_message(message_id, job_id=str(job["id"]))
    updates: dict[str, Any] = {"anchor_job_id": str(job["id"])}
    if str(chat.get("title") or CHAT_TITLE_DEFAULT) == CHAT_TITLE_DEFAULT:
        title = str(job.get("title") or "").strip()
        if title:
            updates["title"] = f"改《{title[:60]}》"
    store.update_music_chat(chat_id, **updates)
    return job
