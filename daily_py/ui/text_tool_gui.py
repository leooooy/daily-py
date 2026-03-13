#!/usr/bin/env python3
"""GUI 文字处理工具 — 文字比对、数字范围展开等。

运行方式::

    python -m daily_py.ui.text_tool_gui
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _split_items(text: str) -> set[str]:
    """Split text by spaces, newlines, and commas; discard empty strings."""
    parts = re.split(r"[,\s]+", text.strip())
    return {p for p in parts if p}


def _expand_ranges(text: str) -> str:
    """将数字范围表达式展开为逗号分隔的数字。

    支持格式：
    - 单个数字: 3
    - 范围: 1-5 → 1,2,3,4,5
    - 混合: 1-3,7,10-12 → 1,2,3,7,10,11,12
    - 分隔符: 逗号、空格、换行均可
    """
    tokens = re.split(r"[,\s]+", text.strip())
    result: list[int] = []
    for token in tokens:
        if not token:
            continue
        m = re.match(r"^(-?\d+)\s*[-~]\s*(-?\d+)$", token)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            step = 1 if start <= end else -1
            result.extend(range(start, end + step, step))
        elif re.match(r"^-?\d+$", token):
            result.append(int(token))
        else:
            raise ValueError(f"无法解析: {token!r}")
    return ",".join(str(n) for n in result)


# ---------------------------------------------------------------------------
# Tab 1: 文字比对
# ---------------------------------------------------------------------------

class _DiffTab:
    def __init__(self, parent: ttk.Frame, status_var: tk.StringVar) -> None:
        self._status = status_var

        # ── 输入区 ──
        input_frame = ttk.Frame(parent, padding=10)
        input_frame.pack(fill="x")

        left = ttk.LabelFrame(input_frame, text="输入框 A", padding=6)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.text_a = tk.Text(left, height=10, width=40, wrap="word")
        self.text_a.pack(fill="both", expand=True)

        right = ttk.LabelFrame(input_frame, text="输入框 B", padding=6)
        right.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.text_b = tk.Text(right, height=10, width=40, wrap="word")
        self.text_b.pack(fill="both", expand=True)

        # ── 按钮 ──
        btn_frame = ttk.Frame(parent, padding=6)
        btn_frame.pack()
        ttk.Button(btn_frame, text="比对", command=self._compare).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="清空", command=self._clear).pack(side="left", padx=4)

        # ── 结果区 ──
        result_frame = ttk.Frame(parent, padding=10)
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

    def _compare(self) -> None:
        set_a = _split_items(self.text_a.get("1.0", "end"))
        set_b = _split_items(self.text_b.get("1.0", "end"))

        common = sorted(set_a & set_b)
        only_a = sorted(set_a - set_b)
        only_b = sorted(set_b - set_a)

        for txt, items in zip(self.result_texts, [common, only_a, only_b]):
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.insert("1.0", "\n".join(items))
            txt.config(state="disabled")

        self._status.set(
            f"A: {len(set_a)} 项 | B: {len(set_b)} 项 | "
            f"共有: {len(common)} | 仅A: {len(only_a)} | 仅B: {len(only_b)}"
        )

    def _clear(self) -> None:
        self.text_a.delete("1.0", "end")
        self.text_b.delete("1.0", "end")
        for txt in self.result_texts:
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.config(state="disabled")
        self._status.set("已清空")


# ---------------------------------------------------------------------------
# Tab 2: 数字范围展开
# ---------------------------------------------------------------------------

class _RangeExpandTab:
    def __init__(self, parent: ttk.Frame, status_var: tk.StringVar) -> None:
        self._status = status_var

        # ── 输入区 ──
        input_lf = ttk.LabelFrame(parent, text="输入（支持 1-5, 8, 10-12 等格式）", padding=8)
        input_lf.pack(fill="x", padx=10, pady=(10, 5))

        self.input_text = tk.Text(input_lf, height=4, wrap="word")
        self.input_text.pack(fill="x")

        # ── 按钮 ──
        btn_frame = ttk.Frame(parent, padding=6)
        btn_frame.pack()
        ttk.Button(btn_frame, text="展开", command=self._expand).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="复制结果", command=self._copy).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="清空", command=self._clear).pack(side="left", padx=4)

        # ── 结果区 ──
        result_lf = ttk.LabelFrame(parent, text="结果（逗号分隔）", padding=8)
        result_lf.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.result_text = tk.Text(result_lf, height=6, wrap="word", state="disabled")
        self.result_text.pack(fill="both", expand=True)

    def _expand(self) -> None:
        raw = self.input_text.get("1.0", "end").strip()
        if not raw:
            self._status.set("请输入数字范围")
            return
        try:
            expanded = _expand_ranges(raw)
        except ValueError as exc:
            self._status.set(f"错误: {exc}")
            return

        count = expanded.count(",") + 1 if expanded else 0
        self.result_text.config(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", expanded)
        self.result_text.config(state="disabled")
        self._status.set(f"展开完成，共 {count} 个数字")

    def _copy(self) -> None:
        content = self.result_text.get("1.0", "end").strip()
        if not content:
            self._status.set("结果为空，无法复制")
            return
        self.result_text.master.clipboard_clear()
        self.result_text.master.clipboard_append(content)
        self._status.set("已复制到剪贴板")

    def _clear(self) -> None:
        self.input_text.delete("1.0", "end")
        self.result_text.config(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.config(state="disabled")
        self._status.set("已清空")


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class TextToolApp:
    def __init__(self, master: tk.Tk | tk.Toplevel) -> None:
        self.master = master
        master.title("DailyPy - 文字处理工具")
        master.geometry("900x650")

        # 状态栏（底部，先创建供 Tab 使用）
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(master, textvariable=self.status_var, relief="sunken",
                  padding=4).pack(fill="x", side="bottom")

        # Notebook
        notebook = ttk.Notebook(master)
        notebook.pack(fill="both", expand=True)

        diff_tab = ttk.Frame(notebook)
        notebook.add(diff_tab, text="文字比对")
        _DiffTab(diff_tab, self.status_var)

        range_tab = ttk.Frame(notebook)
        notebook.add(range_tab, text="数字范围展开")
        _RangeExpandTab(range_tab, self.status_var)



def main() -> None:
    root = tk.Tk()
    TextToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
