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
        # --- 输入模式 ---
        ttk.Label(tab, text="输入模式:").grid(row=r, column=0, sticky="w")
        self._e_mode = tk.StringVar(value="file")
        mode_frame = ttk.Frame(tab)
        mode_frame.grid(row=r, column=1, sticky="w")
        ttk.Radiobutton(mode_frame, text="单个文件 / URL", variable=self._e_mode,
                        value="file", command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(mode_frame, text="文件夹批量", variable=self._e_mode,
                        value="folder", command=self._on_mode_change).pack(side="left", padx=(12, 0))

        r += 1
        # --- 文件/文件夹路径 ---
        self._e_path_label = ttk.Label(tab, text="视频文件 / URL:")
        self._e_path_label.grid(row=r, column=0, sticky="w")
        self._e_video = tk.StringVar()
        ttk.Entry(tab, textvariable=self._e_video, width=60).grid(row=r, column=1, sticky="ew")
        btn_frame_path = ttk.Frame(tab)
        btn_frame_path.grid(row=r, column=2)
        self._e_browse_file_btn = ttk.Button(btn_frame_path, text="浏览文件",
                                              command=lambda: self._browse_file(
                                                  self._e_video, filetypes=_VIDEO_FILETYPES))
        self._e_browse_file_btn.pack(side="left")
        self._e_browse_folder_btn = ttk.Button(btn_frame_path, text="浏览文件夹",
                                                command=self._browse_folder_for_extract)
        self._e_browse_folder_btn.pack(side="left", padx=(2, 0))

        r += 1
        # --- 递归选项（仅文件夹模式） ---
        self._e_recursive = tk.BooleanVar(value=False)
        self._e_recursive_chk = ttk.Checkbutton(tab, text="递归子文件夹",
                                                  variable=self._e_recursive)
        self._e_recursive_chk.grid(row=r, column=1, sticky="w")

        r += 1
        # --- 截取方式 ---
        ttk.Label(tab, text="截取方式:").grid(row=r, column=0, sticky="w")
        self._e_capture_mode = tk.StringVar(value="time")
        cap_frame = ttk.Frame(tab)
        cap_frame.grid(row=r, column=1, sticky="w")
        ttk.Radiobutton(cap_frame, text="按时间（秒）", variable=self._e_capture_mode,
                        value="time", command=self._on_capture_mode_change).pack(side="left")
        ttk.Radiobutton(cap_frame, text="按帧号", variable=self._e_capture_mode,
                        value="frame", command=self._on_capture_mode_change).pack(side="left", padx=(12, 0))

        r += 1
        self._e_value_label = ttk.Label(tab, text="截取时间（秒）:")
        self._e_value_label.grid(row=r, column=0, sticky="w")
        self._e_value = tk.StringVar(value="0.5")
        ttk.Entry(tab, textvariable=self._e_value, width=15).grid(row=r, column=1, sticky="w")

        r += 1
        # --- 输出格式 ---
        ttk.Label(tab, text="输出格式:").grid(row=r, column=0, sticky="w")
        fmt_frame = ttk.Frame(tab)
        fmt_frame.grid(row=r, column=1, sticky="w")
        self._e_fmt = tk.StringVar(value="jpg")
        ttk.Radiobutton(fmt_frame, text="JPG", variable=self._e_fmt, value="jpg").pack(side="left")
        ttk.Radiobutton(fmt_frame, text="PNG", variable=self._e_fmt, value="png").pack(side="left", padx=(12, 0))

        r += 1
        # --- 图片质量 ---
        quality_frame = ttk.Frame(tab)
        quality_frame.grid(row=r, column=1, sticky="w")
        ttk.Label(quality_frame, text="JPG 质量 (-q:v):").pack(side="left")
        self._e_quality = tk.StringVar(value="5")
        ttk.Entry(quality_frame, textvariable=self._e_quality, width=5).pack(side="left", padx=(4, 0))
        ttk.Label(quality_frame, text="  PNG 压缩 (-compression_level):").pack(side="left", padx=(12, 0))
        self._e_compress = tk.StringVar(value="9")
        ttk.Entry(quality_frame, textvariable=self._e_compress, width=5).pack(side="left", padx=(4, 0))

        r += 1
        # --- 输出路径（仅单文件模式） ---
        self._e_output_label = ttk.Label(tab, text="输出路径:")
        self._e_output_label.grid(row=r, column=0, sticky="w")
        self._e_output = tk.StringVar()
        self._e_output_entry = ttk.Entry(tab, textvariable=self._e_output, width=60)
        self._e_output_entry.grid(row=r, column=1, sticky="ew")
        self._e_output_browse_btn = ttk.Button(tab, text="浏览", command=lambda: self._browse_save(
            self._e_output, defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("所有文件", "*.*")],
        ))
        self._e_output_browse_btn.grid(row=r, column=2)

        r += 1
        self._e_output_hint = ttk.Label(tab, text="(留空则自动生成: 视频同名.jpg)")
        self._e_output_hint.grid(row=r, column=1, sticky="w")

        r += 1
        ttk.Button(tab, text="截取", command=self._do_extract).grid(
            row=r, column=0, columnspan=2, pady=8, sticky="w")

        tab.columnconfigure(1, weight=1)

        # 初始化 UI 状态
        self._on_mode_change()

    def _on_mode_change(self) -> None:
        """切换单文件/文件夹模式时更新 UI。"""
        is_folder = self._e_mode.get() == "folder"
        if is_folder:
            self._e_path_label.config(text="视频文件夹:")
            self._e_browse_file_btn.pack_forget()
            self._e_browse_folder_btn.pack(side="left")
            self._e_recursive_chk.grid()
            # 文件夹模式下隐藏单文件输出路径
            self._e_output_label.grid_remove()
            self._e_output_entry.grid_remove()
            self._e_output_browse_btn.grid_remove()
            self._e_output_hint.config(text="(输出到各视频同目录，与视频同名)")
            self._e_output_hint.grid()
        else:
            self._e_path_label.config(text="视频文件 / URL:")
            self._e_browse_folder_btn.pack_forget()
            self._e_browse_file_btn.pack(side="left")
            self._e_recursive_chk.grid_remove()
            self._e_output_label.grid()
            self._e_output_entry.grid()
            self._e_output_browse_btn.grid()
            self._e_output_hint.config(text="(留空则自动生成: 视频同名.jpg)")
            self._e_output_hint.grid()

    def _on_capture_mode_change(self) -> None:
        """切换按时间/按帧号时更新标签。"""
        if self._e_capture_mode.get() == "time":
            self._e_value_label.config(text="截取时间（秒）:")
            self._e_value.set("0.5")
        else:
            self._e_value_label.config(text="截取帧号:")
            self._e_value.set("5")

    def _browse_folder_for_extract(self) -> None:
        d = filedialog.askdirectory()
        if d:
            self._e_video.set(d)

    def _get_extract_params(self):
        """解析并返回截图参数字典，出错返回 None。"""
        fmt = self._e_fmt.get()
        try:
            quality = int(self._e_quality.get().strip())
        except ValueError:
            messagebox.showerror("输入错误", "JPG 质量必须是整数。")
            return None
        try:
            compression = int(self._e_compress.get().strip())
        except ValueError:
            messagebox.showerror("输入错误", "PNG 压缩等级必须是整数。")
            return None

        capture_mode = self._e_capture_mode.get()
        val_str = self._e_value.get().strip()
        if capture_mode == "time":
            try:
                value = float(val_str)
            except ValueError:
                messagebox.showerror("输入错误", "截取时间必须是数字（秒）。")
                return None
        else:
            try:
                value = int(val_str)
            except ValueError:
                messagebox.showerror("输入错误", "帧号必须是整数。")
                return None

        return {
            "capture_mode": capture_mode,
            "value": value,
            "fmt": fmt,
            "quality": quality,
            "compression_level": compression,
        }

    def _do_extract(self) -> None:
        path = self._e_video.get().strip()
        if not path:
            messagebox.showerror("输入错误", "请输入视频文件路径、URL 或文件夹。")
            return
        if not self._ih:
            messagebox.showerror("错误", "ImageHandler 不可用，无法截取帧。")
            return

        params = self._get_extract_params()
        if params is None:
            return

        mode = self._e_mode.get()
        if mode == "folder":
            recursive = self._e_recursive.get()
            self._run_threaded(self._extract_folder_worker, path, recursive, params)
        else:
            output = self._e_output.get().strip()
            self._run_threaded(self._extract_single_worker, path, output, params)

    def _auto_output_path(self, video_src: str, params: dict) -> str:
        """根据视频路径自动生成输出路径：视频同名 + 指定后缀。"""
        fmt = params["fmt"]
        if _is_url(video_src):
            from urllib.parse import urlparse
            url_path = urlparse(video_src).path
            stem = Path(url_path).stem or "frame"
            return str(Path.cwd() / f"{stem}.{fmt}")
        else:
            return str(Path(video_src).with_suffix(f".{fmt}"))

    def _do_extract_one(self, video_src: str, output: str, params: dict) -> None:
        """执行单个视频的截图（在工作线程中调用）。"""
        cap_mode = params["capture_mode"]
        fmt = params["fmt"]
        quality = params["quality"]
        compression = params["compression_level"]

        if cap_mode == "time":
            time_sec = params["value"]
            self._log(f"截取: {video_src} @ {time_sec}s -> {output}")
            result = self._ih.extract_frame(
                video_src, time_sec, output,
                fmt=fmt, quality=quality, compression_level=compression,
            )
        else:
            frame_num = params["value"]
            self._log(f"截取: {video_src} 第{frame_num}帧 -> {output}")
            result = self._ih.extract_frame_by_number(
                video_src, frame_num, output,
                fmt=fmt, quality=quality, compression_level=compression,
            )
        size = result.stat().st_size if result.exists() else 0
        self._log(f"  完成: {result} ({_fmt_size(size)})")

    def _extract_single_worker(self, video: str, output: str, params: dict) -> None:
        if not output:
            output = self._auto_output_path(video, params)
            self.master.after(0, lambda: self._e_output.set(output))
        self._do_extract_one(video, output, params)

    def _extract_folder_worker(self, folder: str, recursive: bool, params: dict) -> None:
        folder_path = Path(folder)
        if not folder_path.is_dir():
            self._log(f"错误: {folder} 不是有效的文件夹路径")
            return

        video_exts = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
                      ".m4v", ".ts", ".mpg", ".mpeg", ".3gp"}
        if recursive:
            files = [f for f in folder_path.rglob("*") if f.suffix.lower() in video_exts]
        else:
            files = [f for f in folder_path.iterdir() if f.is_file() and f.suffix.lower() in video_exts]

        files.sort()
        if not files:
            self._log(f"文件夹中未找到视频文件: {folder}")
            return

        self._log(f"找到 {len(files)} 个视频文件，开始批量截图...")
        success, fail = 0, 0
        for f in files:
            output = self._auto_output_path(str(f), params)
            try:
                self._do_extract_one(str(f), output, params)
                success += 1
            except Exception as exc:
                self._log(f"  失败: {f.name} - {exc}")
                fail += 1
        self._log(f"批量截图完成: 成功 {success}，失败 {fail}")


def main():
    root = tk.Tk()
    MediaToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
