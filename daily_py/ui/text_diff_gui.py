#!/usr/bin/env python3
"""GUI for text comparison in DailyPy.

Two input boxes, split by spaces/newlines/commas, then show:
- Common items (both A and B)
- Only in A
- Only in B
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk


def _split_items(text: str) -> set[str]:
    """Split text by spaces, newlines, and commas; discard empty strings."""
    parts = re.split(r"[,\s]+", text.strip())
    return {p for p in parts if p}


class TextDiffApp:
    def __init__(self, master: tk.Tk | tk.Toplevel):
        self.master = master
        master.title("DailyPy - 文字比对工具")
        master.geometry("900x620")

        # ── Input area ──
        input_frame = ttk.Frame(master, padding=10)
        input_frame.pack(fill="x")

        # Input A
        left = ttk.LabelFrame(input_frame, text="输入框 A", padding=6)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.text_a = tk.Text(left, height=10, width=40, wrap="word")
        self.text_a.pack(fill="both", expand=True)

        # Input B
        right = ttk.LabelFrame(input_frame, text="输入框 B", padding=6)
        right.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.text_b = tk.Text(right, height=10, width=40, wrap="word")
        self.text_b.pack(fill="both", expand=True)

        # ── Buttons ──
        btn_frame = ttk.Frame(master, padding=6)
        btn_frame.pack()
        ttk.Button(btn_frame, text="比对", command=self._compare).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="清空", command=self._clear).pack(side="left", padx=4)

        # ── Result area ──
        result_frame = ttk.Frame(master, padding=10)
        result_frame.pack(fill="both", expand=True)
        result_frame.columnconfigure((0, 1, 2), weight=1)
        result_frame.rowconfigure(1, weight=1)

        headers = ["共有项", "仅 A 中有", "仅 B 中有"]
        colors = ["#2e7d32", "#1565c0", "#c62828"]
        self.result_texts: list[tk.Text] = []

        for col, (header, color) in enumerate(zip(headers, colors)):
            lbl = ttk.Label(result_frame, text=header, font=("", 10, "bold"))
            lbl.grid(row=0, column=col, sticky="w", padx=6)
            txt = tk.Text(result_frame, height=12, width=28, wrap="word",
                          fg=color, state="disabled")
            txt.grid(row=1, column=col, sticky="nsew", padx=4, pady=4)
            self.result_texts.append(txt)

        # ── Status bar ──
        self.status_var = tk.StringVar(value="请在上方输入文字后点击「比对」")
        ttk.Label(master, textvariable=self.status_var, relief="sunken",
                  padding=4).pack(fill="x", side="bottom")

    def _compare(self):
        set_a = _split_items(self.text_a.get("1.0", "end"))
        set_b = _split_items(self.text_b.get("1.0", "end"))

        common = sorted(set_a & set_b)
        only_a = sorted(set_a - set_b)
        only_b = sorted(set_b - set_a)

        results = [common, only_a, only_b]
        for txt, items in zip(self.result_texts, results):
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", "\n".join(items))
            txt.config(state="disabled")

        self.status_var.set(
            f"A: {len(set_a)} 项 | B: {len(set_b)} 项 | "
            f"共有: {len(common)} | 仅A: {len(only_a)} | 仅B: {len(only_b)}"
        )

    def _clear(self):
        self.text_a.delete("1.0", "end")
        self.text_b.delete("1.0", "end")
        for txt in self.result_texts:
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.config(state="disabled")
        self.status_var.set("已清空")


def main():
    root = tk.Tk()
    TextDiffApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
