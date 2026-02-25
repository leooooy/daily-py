#!/usr/bin/env python3
"""媒体视频上传 GUI — 可视化批量上传工具。

运行方式::

    python -m daily_py.ui.media_upload_gui
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional


# ---------------------------------------------------------------------------
# 把 logging / print 输出转入队列，供主线程渲染到文本框
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue) -> None:
        super().__init__()
        self._q = q

    def emit(self, record: logging.LogRecord) -> None:
        self._q.put(("log", record.levelno, self.format(record)))


class _StdoutToQueue:
    """把 sys.stdout.write() 的内容推入日志队列。"""

    def __init__(self, q: queue.Queue) -> None:
        self._q = q

    def write(self, msg: str) -> None:
        if msg.strip():
            self._q.put(("print", 0, msg.rstrip()))

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class MediaUploadApp:
    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("DailyPy - 媒体视频上传")
        master.resizable(True, True)

        self._log_queue: queue.Queue = queue.Queue()
        self._running = False
        self._build_ui()
        self._poll_log()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.master, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")
        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        row = 0

        # ---- 上传目录 ----
        ttk.Label(frm, text="上传目录:").grid(row=row, column=0, sticky="w", pady=3)
        folder_frame = ttk.Frame(frm)
        folder_frame.grid(row=row, column=1, sticky="ew", pady=3)
        folder_frame.columnconfigure(0, weight=1)
        self.folder_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self.folder_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(folder_frame, text="浏览", command=self._browse_folder, width=6).grid(
            row=0, column=1, padx=(4, 0)
        )
        row += 1

        # ---- 环境 ----
        ttk.Label(frm, text="环境:").grid(row=row, column=0, sticky="w", pady=3)
        self.env_var = tk.StringVar(value="test")
        ttk.Combobox(
            frm, textvariable=self.env_var, values=["test", "prod"],
            state="readonly", width=10,
        ).grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # ---- 复选项 ----
        opts = ttk.Frame(frm)
        opts.grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
        self.recursive_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="递归子目录", variable=self.recursive_var).pack(side="left", padx=(0, 20))
        ttk.Checkbutton(opts, text="试运行 (Dry-run)", variable=self.dry_run_var).pack(side="left")
        row += 1

        ttk.Separator(frm, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6
        )
        row += 1

        # ---- S3 前缀 ----
        for label, attr, default in [
            ("视频前缀:",  "video_prefix_var",  "media_video"),
            ("JSON 前缀:", "json_prefix_var",   "media_instruct"),
            ("封面前缀:",  "cover_prefix_var",  "media_cover"),
        ]:
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            ttk.Entry(frm, textvariable=var).grid(row=row, column=1, sticky="ew", pady=2)
            row += 1

        # ---- 封面截取时间 ----
        ttk.Label(frm, text="封面截取时间 (秒):").grid(row=row, column=0, sticky="w", pady=2)
        self.cover_time_var = tk.StringVar(value="1.0")
        ttk.Entry(frm, textvariable=self.cover_time_var, width=10).grid(
            row=row, column=1, sticky="w", pady=2
        )
        row += 1

        # ---- DB 字段 ----
        ttk.Label(frm, text="type:").grid(row=row, column=0, sticky="w", pady=2)
        self.type_var = tk.StringVar(value="0")
        ttk.Entry(frm, textvariable=self.type_var, width=10).grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        ttk.Label(frm, text="service_level_limits:").grid(row=row, column=0, sticky="w", pady=2)
        self.sll_var = tk.StringVar(value="0")
        ttk.Entry(frm, textvariable=self.sll_var, width=10).grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        ttk.Label(frm, text="common (空 = NULL):").grid(row=row, column=0, sticky="w", pady=2)
        self.common_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.common_var, width=10).grid(row=row, column=1, sticky="w", pady=2)
        row += 1

        # ---- 按钮 ----
        ttk.Separator(frm, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6
        )
        row += 1

        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=4)
        self.run_btn = ttk.Button(
            btn_frame, text="开始上传", command=self._start_upload, width=14
        )
        self.run_btn.pack(side="left", padx=6)
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log, width=10).pack(
            side="left", padx=6
        )
        row += 1

        # ---- 日志区 ----
        ttk.Label(frm, text="运行日志:").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(8, 2)
        )
        row += 1

        self.log_text = tk.Text(
            frm, height=18, width=88, wrap="word", state="disabled",
            bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9),
            selectbackground="#264f78",
        )
        self.log_text.grid(row=row, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(row, weight=1)

        sb = ttk.Scrollbar(frm, orient="vertical", command=self.log_text.yview)
        sb.grid(row=row, column=2, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)

        # 颜色标签
        self.log_text.tag_configure("error",   foreground="#f44747")
        self.log_text.tag_configure("warning", foreground="#dcdcaa")
        self.log_text.tag_configure("print",   foreground="#9cdcfe")
        row += 1

        # ---- 进度条 ----
        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择上传目录")
        if folder:
            self.folder_var.set(folder)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _start_upload(self) -> None:
        if self._running:
            return

        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showerror("参数错误", "请选择上传目录。")
            return

        try:
            cover_time    = float(self.cover_time_var.get())
            default_type  = int(self.type_var.get())
            sll           = int(self.sll_var.get())
            common_str    = self.common_var.get().strip()
            common: Optional[int] = int(common_str) if common_str else None
        except ValueError as exc:
            messagebox.showerror("参数错误", f"数值参数格式有误: {exc}")
            return

        params = dict(
            folder=folder,
            env=self.env_var.get(),
            recursive=self.recursive_var.get(),
            dry_run=self.dry_run_var.get(),
            video_prefix=self.video_prefix_var.get().strip(),
            json_prefix=self.json_prefix_var.get().strip(),
            cover_prefix=self.cover_prefix_var.get().strip(),
            cover_time_sec=cover_time,
            default_type=default_type,
            default_service_level_limits=sll,
            default_common=common,
        )

        self._running = True
        self.run_btn.configure(state="disabled", text="上传中…")
        self.progress.start(12)
        threading.Thread(target=self._run_pipeline, kwargs=params, daemon=True).start()

    # ------------------------------------------------------------------
    # 后台线程：执行上传
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        folder: str,
        env: str,
        recursive: bool,
        dry_run: bool,
        video_prefix: str,
        json_prefix: str,
        cover_prefix: str,
        cover_time_sec: float,
        default_type: int,
        default_service_level_limits: int,
        default_common: Optional[int],
    ) -> None:
        # 把 logging 输出导入队列
        handler = _QueueHandler(self._log_queue)
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S")
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        old_level = root_logger.level
        root_logger.setLevel(logging.INFO)

        # 把 print() 输出也导入队列
        old_stdout = sys.stdout
        sys.stdout = _StdoutToQueue(self._log_queue)  # type: ignore[assignment]

        try:
            from daily_py.media_video_pipeline import MediaVideoPipeline

            pipeline = MediaVideoPipeline(
                env=env,
                video_prefix=video_prefix,
                json_prefix=json_prefix,
                cover_prefix=cover_prefix,
                cover_time_sec=cover_time_sec,
                default_type=default_type,
                default_service_level_limits=default_service_level_limits,
                default_common=default_common,
            )
            pipeline.run(folder, recursive=recursive, dry_run=dry_run)

        except Exception as exc:
            self._log_queue.put(("log", logging.ERROR, f"[ERROR] {exc}"))

        finally:
            sys.stdout = old_stdout
            root_logger.removeHandler(handler)
            root_logger.setLevel(old_level)
            self.master.after(0, self._upload_done)

    def _upload_done(self) -> None:
        self._running = False
        self.progress.stop()
        self.run_btn.configure(state="normal", text="开始上传")

    # ------------------------------------------------------------------
    # 主线程轮询队列，刷新日志文本框
    # ------------------------------------------------------------------

    def _poll_log(self) -> None:
        try:
            while True:
                kind, level, msg = self._log_queue.get_nowait()
                self.log_text.configure(state="normal")
                if kind == "log" and level >= logging.ERROR:
                    self.log_text.insert(tk.END, msg + "\n", "error")
                elif kind == "log" and level >= logging.WARNING:
                    self.log_text.insert(tk.END, msg + "\n", "warning")
                elif kind == "print":
                    self.log_text.insert(tk.END, msg + "\n", "print")
                else:
                    self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.master.after(100, self._poll_log)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    MediaUploadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
