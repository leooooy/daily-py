#!/usr/bin/env python3
"""DailyPy LLM 对话工具 GUI — 支持 Grok (xAI) 和 OpenAI.

运行方式::

    python -m daily_py.ui.llm_chat_gui
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Optional

from daily_py.services.llm_chat import (
    PROVIDERS,
    ChatSession,
    Message,
    chat_stream,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_WINDOW_TITLE = "DailyPy - LLM 对话工具"
_WINDOW_SIZE = "900x700"
_MIN_SIZE = (700, 500)


class LLMChatApp:
    """LLM 对话 GUI."""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title(_WINDOW_TITLE)
        master.geometry(_WINDOW_SIZE)
        master.minsize(*_MIN_SIZE)

        self._chunk_queue: queue.Queue = queue.Queue()
        self._busy = False
        self._image_path: Optional[str] = None
        self._session = ChatSession()

        main = ttk.Frame(master, padding=8)
        main.pack(fill="both", expand=True)

        self._build_toolbar(main)
        self._build_chat_area(main)
        self._build_input_area(main)
        self._build_status(master)

        self._poll_chunks()
        self._on_provider_change()

    # ------------------------------------------------------------------
    # 工具栏
    # ------------------------------------------------------------------

    def _build_toolbar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 4))

        # Provider 选择
        ttk.Label(bar, text="Provider:").pack(side="left")
        self._v_provider = tk.StringVar(value="grok")
        provider_cb = ttk.Combobox(
            bar, textvariable=self._v_provider, state="readonly",
            values=list(PROVIDERS.keys()), width=8,
        )
        provider_cb.pack(side="left", padx=(4, 12))
        provider_cb.bind("<<ComboboxSelected>>", lambda _: self._on_provider_change())

        # 模型选择
        ttk.Label(bar, text="Model:").pack(side="left")
        self._v_model = tk.StringVar()
        self._model_cb = ttk.Combobox(
            bar, textvariable=self._v_model, state="readonly", width=22,
        )
        self._model_cb.pack(side="left", padx=(4, 12))

        # API Key
        ttk.Label(bar, text="API Key:").pack(side="left")
        self._v_key = tk.StringVar()
        ttk.Entry(bar, textvariable=self._v_key, show="*", width=30).pack(
            side="left", padx=(4, 12),
        )

        # 清空对话
        ttk.Button(bar, text="清空对话", command=self._clear_chat).pack(side="right")

    # ------------------------------------------------------------------
    # 聊天记录区
    # ------------------------------------------------------------------

    def _build_chat_area(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=(0, 4))

        self.chat_text = tk.Text(
            frame, wrap="word", state="disabled",
            font=("Microsoft YaHei UI", 10),
            bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="#d4d4d4",
            selectbackground="#264f78",
            padx=8, pady=8,
        )
        sb = ttk.Scrollbar(frame, command=self.chat_text.yview)
        self.chat_text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.chat_text.pack(side="left", fill="both", expand=True)

        # 消息样式 tags
        self.chat_text.tag_config(
            "user_name", foreground="#569cd6", font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.chat_text.tag_config(
            "assistant_name", foreground="#4ec9b0", font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.chat_text.tag_config("user_msg", foreground="#ce9178")
        self.chat_text.tag_config("assistant_msg", foreground="#d4d4d4")
        self.chat_text.tag_config("image_tag", foreground="#808080")

    # ------------------------------------------------------------------
    # 输入区
    # ------------------------------------------------------------------

    def _build_input_area(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill="x")

        # 图片附件按钮 + 预览标签
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=(0, 2))

        self._img_btn = ttk.Button(
            btn_frame, text="📎 附加图片", command=self._pick_image,
        )
        self._img_btn.pack(side="left")

        self._img_label = ttk.Label(btn_frame, text="", foreground="gray")
        self._img_label.pack(side="left", padx=(8, 0))

        self._img_clear_btn = ttk.Button(
            btn_frame, text="✕", width=2, command=self._clear_image,
        )

        # 输入框 + 发送按钮
        input_frame = ttk.Frame(frame)
        input_frame.pack(fill="x")

        self.input_text = tk.Text(
            input_frame, height=3, wrap="word",
            font=("Microsoft YaHei UI", 10),
            bg="#252526", fg="#d4d4d4",
            insertbackground="#d4d4d4",
            padx=6, pady=4,
        )
        self.input_text.pack(side="left", fill="x", expand=True)
        self.input_text.bind("<Control-Return>", lambda _: self._send())

        send_btn = ttk.Button(input_frame, text="发送\n(Ctrl+Enter)", command=self._send)
        send_btn.pack(side="right", padx=(4, 0), fill="y")

    # ------------------------------------------------------------------
    # 状态栏
    # ------------------------------------------------------------------

    def _build_status(self, parent: tk.Tk) -> None:
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(parent, textvariable=self.status_var, relief="sunken", anchor="w").pack(
            fill="x", side="bottom",
        )

    # ------------------------------------------------------------------
    # Provider / 模型切换
    # ------------------------------------------------------------------

    def _on_provider_change(self) -> None:
        provider = self._v_provider.get()
        cfg = PROVIDERS[provider]
        models = cfg["models"]
        self._model_cb.config(values=models)
        self._v_model.set(models[0])
        self._v_key.set("")
        # 图片按钮仅 grok 可用
        if provider == "grok":
            self._img_btn.config(state="normal")
        else:
            self._img_btn.config(state="disabled")
            self._clear_image()

    # ------------------------------------------------------------------
    # 图片选择
    # ------------------------------------------------------------------

    def _pick_image(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp *.webp")],
        )
        if path:
            self._image_path = path
            name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            self._img_label.config(text=f"📷 {name}")
            self._img_clear_btn.pack(side="left", padx=(4, 0))

    def _clear_image(self) -> None:
        self._image_path = None
        self._img_label.config(text="")
        self._img_clear_btn.pack_forget()

    # ------------------------------------------------------------------
    # 发送消息
    # ------------------------------------------------------------------

    def _send(self) -> None:
        if self._busy:
            return
        text = self.input_text.get("1.0", "end").strip()
        if not text:
            return

        # 准备 session
        self._session.provider = self._v_provider.get()
        self._session.model = self._v_model.get()
        self._session.api_key = self._v_key.get().strip()

        # 附带图片时自动切换到 vision 模型
        if self._image_path and self._session.provider == "grok":
            vision_models = PROVIDERS["grok"].get("vision_models", [])
            if self._session.model not in vision_models and vision_models:
                self._session.model = vision_models[0]
                self._v_model.set(vision_models[0])

        # 添加用户消息
        msg = Message(role="user", content=text, image_path=self._image_path)
        self._session.messages.append(msg)

        # 显示用户消息
        self._append_chat("user_name", "You")
        if self._image_path:
            name = self._image_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            self._append_chat("image_tag", f"  [图片: {name}]")
        self._append_chat("user_msg", text + "\n")

        # 清空输入
        self.input_text.delete("1.0", "end")
        img_path = self._image_path
        self._clear_image()

        # 显示助手标记
        self._append_chat("assistant_name", f"{self._session.model}")

        # 启动线程调用 API
        self._busy = True
        self.status_var.set("生成中...")

        def _worker() -> None:
            try:
                reply = chat_stream(
                    self._session,
                    on_chunk=lambda chunk: self._chunk_queue.put(chunk),
                )
                # 保存助手消息到会话
                self._session.messages.append(
                    Message(role="assistant", content=reply)
                )
                self._chunk_queue.put(("\n", True))  # 结束标记
            except Exception as exc:
                err_msg = str(exc)
                self._chunk_queue.put(None)  # 错误标记
                self.master.after(0, lambda m=err_msg: self._on_error(m))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_error(self, msg: str) -> None:
        self._append_chat("user_msg", f"\n[错误] {msg}\n")
        # 移除最后一条用户消息（发送失败）
        if self._session.messages and self._session.messages[-1].role == "user":
            self._session.messages.pop()
        self._busy = False
        self.status_var.set("就绪")

    # ------------------------------------------------------------------
    # 流式输出轮询
    # ------------------------------------------------------------------

    def _poll_chunks(self) -> None:
        while True:
            try:
                item = self._chunk_queue.get_nowait()
            except queue.Empty:
                break

            if item is None:
                # 错误已在 _on_error 处理
                continue
            if isinstance(item, tuple):
                # 结束标记
                self._append_chat("assistant_msg", "\n")
                self._busy = False
                self.status_var.set("就绪")
                continue

            # 正常文本 chunk
            self.chat_text.config(state="normal")
            self.chat_text.insert("end", item, "assistant_msg")
            self.chat_text.see("end")
            self.chat_text.config(state="disabled")

        self.master.after(50, self._poll_chunks)

    # ------------------------------------------------------------------
    # 聊天区工具方法
    # ------------------------------------------------------------------

    def _append_chat(self, tag: str, text: str) -> None:
        self.chat_text.config(state="normal")
        self.chat_text.insert("end", text + "\n", tag)
        self.chat_text.see("end")
        self.chat_text.config(state="disabled")

    def _clear_chat(self) -> None:
        if self._busy:
            return
        self._session.clear()
        self.chat_text.config(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.config(state="disabled")
        self.status_var.set("对话已清空")


# ------------------------------------------------------------------
# 入口
# ------------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    LLMChatApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
