#!/usr/bin/env python3
"""DailyPy 模型下载工具 GUI — 从 HuggingFace Hub 下载模型到本地。

运行方式::

    python -m daily_py.ui.model_download_gui
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

_DOWNLOADER_OK = True
try:
    from daily_py.services.model_downloader import ModelDownloader
except Exception:
    _DOWNLOADER_OK = False

_DEFAULT_BASE_DIR = r"D:\my_models"

# 常用模型预设
_PRESETS = [
    ("Qwen3-ForcedAligner-0.6B (强制对齐)", "Qwen/Qwen3-ForcedAligner-0.6B"),
]


class ModelDownloadApp:
    """模型下载 GUI。"""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("DailyPy - 模型下载工具")
        master.geometry("750x550")
        master.minsize(600, 450)

        self._log_queue: queue.Queue = queue.Queue()
        self._busy = False

        main = ttk.Frame(master, padding=8)
        main.pack(fill="both", expand=True)

        self._build_form(main)
        self._build_model_list(main)
        self._build_log(master)
        self._build_status(master)

        self._poll_log()
        self._refresh_model_list()

    # ------------------------------------------------------------------
    # 表单区
    # ------------------------------------------------------------------

    def _build_form(self, parent: ttk.Frame) -> None:
        form = ttk.LabelFrame(parent, text="下载设置", padding=8)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        r = 0
        # 模型 ID
        ttk.Label(form, text="模型 ID:").grid(row=r, column=0, sticky="w")
        self._v_repo = tk.StringVar(value="Qwen/Qwen3-ForcedAligner-0.6B")
        ttk.Entry(form, textvariable=self._v_repo, width=50).grid(row=r, column=1, sticky="ew")

        # 预设下拉
        preset_f = ttk.Frame(form)
        preset_f.grid(row=r, column=2, padx=(4, 0))
        self._v_preset = tk.StringVar(value="")
        preset_cb = ttk.Combobox(
            preset_f, textvariable=self._v_preset, state="readonly", width=30,
            values=[name for name, _ in _PRESETS],
        )
        preset_cb.pack(side="left")
        preset_cb.bind("<<ComboboxSelected>>", self._on_preset_select)

        # 下载目录
        r += 1
        ttk.Label(form, text="下载目录:").grid(row=r, column=0, sticky="w")
        self._v_base_dir = tk.StringVar(value=_DEFAULT_BASE_DIR)
        ttk.Entry(form, textvariable=self._v_base_dir, width=50).grid(row=r, column=1, sticky="ew")
        ttk.Button(form, text="浏览",
                   command=lambda: self._browse_dir(self._v_base_dir)).grid(row=r, column=2)

        # Token（可选）
        r += 1
        ttk.Label(form, text="HF Token (可选):").grid(row=r, column=0, sticky="w")
        self._v_token = tk.StringVar()
        ttk.Entry(form, textvariable=self._v_token, width=50, show="*").grid(row=r, column=1, sticky="ew")

        # 按钮行
        r += 1
        btn_f = ttk.Frame(form)
        btn_f.grid(row=r, column=0, columnspan=3, pady=(10, 0), sticky="w")
        self._btn_download = ttk.Button(btn_f, text="开始下载", command=self._do_download)
        self._btn_download.pack(side="left")
        ttk.Button(btn_f, text="刷新列表", command=self._refresh_model_list).pack(side="left", padx=(12, 0))

    # ------------------------------------------------------------------
    # 已下载模型列表
    # ------------------------------------------------------------------

    def _build_model_list(self, parent: ttk.Frame) -> None:
        list_frame = ttk.LabelFrame(parent, text="已下载模型", padding=4)
        list_frame.pack(fill="both", expand=True, pady=(6, 0))

        cols = ("name", "size", "path")
        self._tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=5)
        self._tree.heading("name", text="模型名")
        self._tree.heading("size", text="大小 (MB)")
        self._tree.heading("path", text="路径")
        self._tree.column("name", width=250)
        self._tree.column("size", width=80, anchor="e")
        self._tree.column("path", width=350)
        self._tree.pack(fill="both", expand=True, side="left")

        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        sb.pack(fill="y", side="right")
        self._tree.config(yscrollcommand=sb.set)

    def _refresh_model_list(self) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)
        if not _DOWNLOADER_OK:
            return
        dl = ModelDownloader(base_dir=self._v_base_dir.get().strip() or _DEFAULT_BASE_DIR)
        for m in dl.list_models():
            self._tree.insert("", "end", values=(m["name"], m["size_mb"], m["path"]))

    # ------------------------------------------------------------------
    # 日志区
    # ------------------------------------------------------------------

    def _build_log(self, parent) -> None:
        log_frame = ttk.LabelFrame(parent, text="日志")
        log_frame.pack(fill="both", padx=6, pady=6, expand=True)

        self.log_text = tk.Text(
            log_frame, height=6, wrap="word",
            bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9),
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        sb.pack(fill="y", side="right")
        self.log_text.config(yscrollcommand=sb.set)

    def _build_status(self, parent) -> None:
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log).pack(side="right")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(btn_frame, textvariable=self.status_var).pack(side="left")

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        self._log_queue.put(msg)

    def _poll_log(self) -> None:
        while True:
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.master.after(100, self._poll_log)

    def _clear_log(self) -> None:
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _browse_dir(self, var: tk.StringVar) -> None:
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def _on_preset_select(self, _event=None) -> None:
        name = self._v_preset.get()
        for label, repo_id in _PRESETS:
            if label == name:
                self._v_repo.set(repo_id)
                break

    def _run_threaded(self, fn, *args) -> None:
        if self._busy:
            self._log("操作进行中，请等待...")
            return
        self._busy = True
        self.status_var.set("下载中...")
        self._btn_download.config(state="disabled")

        def _wrapper():
            try:
                fn(*args)
            except Exception as exc:
                self._log(f"错误: {exc}")
            finally:
                self.master.after(0, self._on_done)

        threading.Thread(target=_wrapper, daemon=True).start()

    def _on_done(self) -> None:
        self._busy = False
        self.status_var.set("就绪")
        self._btn_download.config(state="normal")
        self._refresh_model_list()

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------

    def _do_download(self) -> None:
        if not _DOWNLOADER_OK:
            messagebox.showerror("错误", "ModelDownloader 模块不可用，请检查依赖。")
            return

        repo_id = self._v_repo.get().strip()
        if not repo_id:
            messagebox.showerror("输入错误", "请输入模型 ID。")
            return

        base_dir = self._v_base_dir.get().strip() or _DEFAULT_BASE_DIR
        token = self._v_token.get().strip() or None

        self._run_threaded(self._download_worker, repo_id, base_dir, token)

    def _download_worker(self, repo_id: str, base_dir: str, token: str | None) -> None:
        dl = ModelDownloader(
            base_dir=base_dir, token=token, progress_callback=self._log,
        )
        path = dl.download(repo_id)
        self._log(f"模型路径: {path}")


def main() -> None:
    root = tk.Tk()
    ModelDownloadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
