#!/usr/bin/env python3
"""DailyPy 媒体工具 — 查看媒体详细信息、截取视频帧。

支持本地文件和 URL（ffprobe/ffmpeg 直接读取 URL，无需下载）。

运行方式::

    python -m daily_py.ui.media_tool_gui
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse

_IMAGE_HANDLER_OK = True
try:
    from daily_py.image_handler import ImageHandler
except Exception:
    _IMAGE_HANDLER_OK = False


def _is_url(s: str) -> bool:
    """判断字符串是否为 HTTP/HTTPS URL。"""
    try:
        r = urlparse(s)
        return r.scheme in ("http", "https")
    except Exception:
        return False


def _fmt_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.2f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _fmt_bitrate(bps: int) -> str:
    if bps <= 0:
        return ""
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1_000:.0f} Kbps"
    return f"{bps} bps"


_VIDEO_FILETYPES = [
    ("视频文件", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.m4v *.ts *.mpg *.mpeg *.3gp"),
    ("所有文件", "*.*"),
]
_MEDIA_FILETYPES = [
    ("媒体文件", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.m4v *.jpg *.jpeg *.png *.gif *.bmp *.tiff *.webp"),
    ("视频", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.m4v *.ts"),
    ("图片", "*.jpg *.jpeg *.png *.gif *.bmp *.tiff *.webp"),
    ("所有文件", "*.*"),
]


class MediaToolApp:
    """独立媒体工具 GUI。"""

    # 属性名中英映射
    _LABELS = {
        "file_name": "文件名",
        "file_size": "文件大小",
        "absolute_path": "绝对路径",
        "type": "类型",
        "format": "容器格式",
        "duration_sec": "时长（秒）",
        "bit_rate": "总码率",
        "video_codec": "视频编码",
        "video_profile": "编码 Profile",
        "width": "宽度",
        "height": "高度",
        "video_bit_rate": "视频码率",
        "frame_rate": "帧率",
        "pix_fmt": "像素格式",
        "audio_codec": "音频编码",
        "audio_sample_rate": "音频采样率",
        "audio_channels": "音频声道",
        "audio_bit_rate": "音频码率",
        "image_format": "图片格式",
        "image_mode": "色彩模式",
        "source_url": "源 URL",
    }

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("DailyPy - 媒体工具")
        master.geometry("900x650")
        master.minsize(700, 500)

        self._log_queue: queue.Queue = queue.Queue()
        self._busy = False
        self._ih: ImageHandler | None = None

        if _IMAGE_HANDLER_OK:
            try:
                self._ih = ImageHandler()
            except Exception as e:
                self._ih = None
                messagebox.showwarning("初始化警告", f"ImageHandler 初始化失败: {e}\n部分功能不可用。")

        # 主布局
        top = ttk.Frame(master)
        top.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        self.notebook = ttk.Notebook(top)
        self.notebook.pack(fill="both", expand=True)

        self._build_info_tab()
        self._build_extract_tab()

        # 底部日志
        log_frame = ttk.LabelFrame(master, text="日志")
        log_frame.pack(fill="both", padx=6, pady=6, expand=False)

        self.log_text = tk.Text(
            log_frame, height=8, wrap="word",
            bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9),
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        sb.pack(fill="y", side="right")
        self.log_text.config(yscrollcommand=sb.set)

        btn_frame = ttk.Frame(master)
        btn_frame.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log).pack(side="right")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(btn_frame, textvariable=self.status_var).pack(side="left")

        self._poll_log()

    # ------------------------------------------------------------------
    # 共享工具
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

    def _browse_file(self, var: tk.StringVar, **kw) -> None:
        f = filedialog.askopenfilename(**kw)
        if f:
            var.set(f)

    def _browse_save(self, var: tk.StringVar, **kw) -> None:
        f = filedialog.asksaveasfilename(**kw)
        if f:
            var.set(f)

    def _run_threaded(self, fn, *args) -> None:
        if self._busy:
            self._log("操作进行中，请等待...")
            return
        self._busy = True
        self.status_var.set("执行中...")

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

    # ------------------------------------------------------------------
    # Tab 0: 媒体信息
    # ------------------------------------------------------------------

    def _build_info_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="媒体信息")

        r = 0
        ttk.Label(tab, text="文件路径 / URL:").grid(row=r, column=0, sticky="w")
        self._i_path = tk.StringVar()
        ttk.Entry(tab, textvariable=self._i_path, width=60).grid(row=r, column=1, sticky="ew")
        ttk.Button(tab, text="浏览", command=lambda: self._browse_file(
            self._i_path, filetypes=_MEDIA_FILETYPES,
        )).grid(row=r, column=2)

        r += 1
        ttk.Button(tab, text="获取信息", command=self._do_info).grid(row=r, column=0, columnspan=2, pady=6, sticky="w")

        r += 1
        cols = ("property", "value")
        self._i_tree = ttk.Treeview(tab, columns=cols, show="headings", height=16)
        self._i_tree.heading("property", text="属性")
        self._i_tree.heading("value", text="值")
        self._i_tree.column("property", width=160)
        self._i_tree.column("value", width=600)
        self._i_tree.grid(row=r, column=0, columnspan=3, sticky="nsew")
        sb = ttk.Scrollbar(tab, orient="vertical", command=self._i_tree.yview)
        sb.grid(row=r, column=3, sticky="ns")
        self._i_tree.config(yscrollcommand=sb.set)

        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(r, weight=1)

    def _do_info(self) -> None:
        path = self._i_path.get().strip()
        if not path:
            messagebox.showerror("输入错误", "请输入文件路径或 URL。")
            return
        if not self._ih:
            messagebox.showerror("错误", "ImageHandler 不可用，无法获取媒体信息。")
            return
        self._run_threaded(self._info_worker, path)

    def _info_worker(self, path: str) -> None:
        self._log(f"获取媒体信息: {path}")
        info = self._ih.get_media_info(path)
        self._log(f"类型: {info.get('type', 'unknown')}")
        self.master.after(0, self._populate_info_tree, info)

    def _populate_info_tree(self, info: dict) -> None:
        self._i_tree.delete(*self._i_tree.get_children())

        for key, value in info.items():
            if key == "exif":
                # EXIF 展开为子项
                self._i_tree.insert("", "end", values=("--- EXIF ---", ""))
                for ek, ev in value.items():
                    self._i_tree.insert("", "end", values=(f"  {ek}", str(ev)))
                continue

            label = self._LABELS.get(key, key)
            # 格式化特殊值
            if key == "file_size":
                display = _fmt_size(value)
            elif key in ("bit_rate", "video_bit_rate", "audio_bit_rate"):
                display = _fmt_bitrate(value)
            elif key == "duration_sec" and value:
                mins, secs = divmod(float(value), 60)
                display = f"{value:.3f} s ({int(mins)}:{secs:05.2f})"
            elif key == "type":
                display = {"video": "视频", "image": "图片"}.get(value, value)
            elif key in ("width", "height"):
                display = f"{value} px"
            else:
                display = str(value)

            self._i_tree.insert("", "end", values=(label, display))

    # ------------------------------------------------------------------
    # Tab 1: 视频截图
    # ------------------------------------------------------------------

    def _build_extract_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="视频截图")

        r = 0
        ttk.Label(tab, text="视频文件 / URL:").grid(row=r, column=0, sticky="w")
        self._e_video = tk.StringVar()
        ttk.Entry(tab, textvariable=self._e_video, width=60).grid(row=r, column=1, sticky="ew")
        ttk.Button(tab, text="浏览", command=lambda: self._browse_file(
            self._e_video, filetypes=_VIDEO_FILETYPES,
        )).grid(row=r, column=2)

        r += 1
        ttk.Label(tab, text="截取时间（秒）:").grid(row=r, column=0, sticky="w")
        self._e_time = tk.StringVar(value="1.0")
        ttk.Entry(tab, textvariable=self._e_time, width=15).grid(row=r, column=1, sticky="w")

        r += 1
        ttk.Label(tab, text="输出路径:").grid(row=r, column=0, sticky="w")
        self._e_output = tk.StringVar()
        ttk.Entry(tab, textvariable=self._e_output, width=60).grid(row=r, column=1, sticky="ew")
        ttk.Button(tab, text="浏览", command=lambda: self._browse_save(
            self._e_output, defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("所有文件", "*.*")],
        )).grid(row=r, column=2)

        r += 1
        ttk.Label(tab, text="(留空则自动生成: 视频同目录下 frame_时间.png)").grid(
            row=r, column=1, sticky="w")

        r += 1
        ttk.Button(tab, text="截取", command=self._do_extract).grid(row=r, column=0, columnspan=2, pady=8, sticky="w")

        tab.columnconfigure(1, weight=1)

    def _do_extract(self) -> None:
        video = self._e_video.get().strip()
        if not video:
            messagebox.showerror("输入错误", "请输入视频文件路径或 URL。")
            return
        if not self._ih:
            messagebox.showerror("错误", "ImageHandler 不可用，无法截取帧。")
            return
        try:
            time_sec = float(self._e_time.get().strip())
        except ValueError:
            messagebox.showerror("输入错误", "截取时间必须是数字（秒）。")
            return

        output = self._e_output.get().strip()
        if not output:
            if _is_url(video):
                output = str(Path.cwd() / f"frame_{time_sec:.1f}s.png")
            else:
                vp = Path(video)
                output = str(vp.parent / f"frame_{time_sec:.1f}s.png")
            self._e_output.set(output)

        self._run_threaded(self._extract_worker, video, time_sec, output)

    def _extract_worker(self, video: str, time_sec: float, output: str) -> None:
        self._log(f"截取视频帧: {video} @ {time_sec}s -> {output}")
        result = self._ih.extract_frame(video, time_sec, output)
        size = result.stat().st_size if result.exists() else 0
        self._log(f"截取完成: {result} ({_fmt_size(size)})")


def main():
    root = tk.Tk()
    MediaToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
