"""LLM Chat Service — 支持 Grok (xAI) 和 OpenAI 的对话接口."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

import requests

# ---------------------------------------------------------------------------
# Provider 配置
# ---------------------------------------------------------------------------

PROVIDERS: Dict[str, Dict[str, object]] = {
    "grok": {
        "endpoint": "https://api.x.ai/v1/chat/completions",
        "default_key": os.getenv("XAI_API_KEY", ""),
        "models": [
            "grok-3", "grok-3-mini",
            "grok-4-fast-non-reasoning", "grok-4-fast-reasoning",
            "grok-4-0709",
            "grok-4-1-fast-non-reasoning", "grok-4-1-fast-reasoning",
            "grok-4.20-beta-0309-non-reasoning", "grok-4.20-beta-0309-reasoning",
        ],
        "vision_models": [
            "grok-4-fast-non-reasoning", "grok-4-fast-reasoning",
            "grok-4-0709",
            "grok-4-1-fast-non-reasoning", "grok-4-1-fast-reasoning",
            "grok-4.20-beta-0309-non-reasoning", "grok-4.20-beta-0309-reasoning",
        ],
    },
    "openai": {
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "default_key": os.getenv("OPENAI_API_KEY", ""),
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    },
}


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str
    image_path: Optional[str] = None  # 仅 user 消息可附带图片


@dataclass
class ChatSession:
    """维护一次多轮对话的上下文."""

    provider: str = "grok"
    model: str = "grok-3"
    api_key: str = ""
    messages: List[Message] = field(default_factory=list)

    def clear(self) -> None:
        self.messages.clear()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _encode_image(image_path: str) -> str:
    """将图片文件编码为 base64 data URI."""
    mime, _ = mimetypes.guess_type(image_path)
    if not mime:
        mime = "image/png"
    data = Path(image_path).read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _build_messages(messages: List[Message]) -> List[dict]:
    """将 Message 列表转换为 OpenAI 兼容的消息格式."""
    result = []
    for msg in messages:
        if msg.image_path:
            content = [
                {"type": "text", "text": msg.content},
                {
                    "type": "image_url",
                    "image_url": {"url": _encode_image(msg.image_path)},
                },
            ]
            result.append({"role": msg.role, "content": content})
        else:
            result.append({"role": msg.role, "content": msg.content})
    return result


# ---------------------------------------------------------------------------
# 核心 API 调用
# ---------------------------------------------------------------------------

def chat_stream(
    session: ChatSession,
    on_chunk: Optional[Callable[[str], None]] = None,
) -> str:
    """发送对话请求并以流式方式返回回复.

    Args:
        session: 包含 provider/model/api_key/messages 的会话对象.
        on_chunk: 每收到一段文本时的回调（用于 GUI 实时显示）.

    Returns:
        完整的助手回复文本.

    Raises:
        RuntimeError: API 调用失败时.
    """
    provider_cfg = PROVIDERS[session.provider]
    endpoint = str(provider_cfg["endpoint"])
    api_key = session.api_key or str(provider_cfg["default_key"])

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": session.model,
        "messages": _build_messages(session.messages),
        "stream": True,
    }

    resp = requests.post(
        endpoint, headers=headers, json=payload, stream=True, timeout=120
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API 错误 ({resp.status_code}): {resp.text[:500]}")

    resp.encoding = "utf-8"
    full_text = ""
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        data_str = line[len("data: "):]
        if data_str.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
            delta = chunk["choices"][0].get("delta", {})
            text = delta.get("content", "")
            if text:
                full_text += text
                if on_chunk:
                    on_chunk(text)
        except (json.JSONDecodeError, KeyError, IndexError):
            continue

    return full_text
