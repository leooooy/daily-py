#!/usr/bin/env python3
"""DailyPy 强制对齐工具 GUI — 音频 + 文本 → 词级时间戳。

运行方式::

    python -m daily_py.ui.forced_align_gui
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Sequence

_ALIGNER_OK = True
try:
    from daily_py.services.novel.forced_aligner import ForcedAligner
except Exception:
    _ALIGNER_OK = False

_AUDIO_FILETYPES = [
    ("音频文件", "*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma *.opus"),
    ("所有文件", "*.*"),
]


class ForcedAlignApp:
    """强制对齐 GUI。"""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("DailyPy - 强制对齐工具")
        master.geometry("800x600")
        master.minsize(650, 500)

        self._log_queue: queue.Queue = queue.Queue()
        self._busy = False

        # --- 主布局 ---
        main = ttk.Frame(master, padding=8)
        main.pack(fill="both", expand=True)

        self._build_form(main)
        self._build_log(master)
        self._build_status(master)

        self._poll_log()

    # ------------------------------------------------------------------
    # 表单区
    # ------------------------------------------------------------------

    def _build_form(self, parent: ttk.Frame) -> None:
        form = ttk.LabelFrame(parent, text="对齐设置", padding=8)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        r = 0
        # 输入模式
        ttk.Label(form, text="输入模式:").grid(row=r, column=0, sticky="w")
        self._mode = tk.StringVar(value="single")
        mode_f = ttk.Frame(form)
        mode_f.grid(row=r, column=1, sticky="w")
        ttk.Radiobutton(mode_f, text="单文件", variable=self._mode,
                        value="single", command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(mode_f, text="批量文件夹", variable=self._mode,
                        value="batch", command=self._on_mode_change).pack(side="left", padx=(12, 0))
        ttk.Radiobutton(mode_f, text="预切割合并", variable=self._mode,
                        value="presplit", command=self._on_mode_change).pack(side="left", padx=(12, 0))

        # --- 单文件输入 ---
        r += 1
        self._lbl_audio = ttk.Label(form, text="音频文件:")
        self._lbl_audio.grid(row=r, column=0, sticky="w")
        self._v_audio = tk.StringVar()
        self._ent_audio = ttk.Entry(form, textvariable=self._v_audio, width=60)
        self._ent_audio.grid(row=r, column=1, sticky="ew")
        self._btn_audio = ttk.Button(form, text="浏览", command=self._browse_audio)
        self._btn_audio.grid(row=r, column=2)

        r += 1
        self._lbl_text = ttk.Label(form, text="文本文件:")
        self._lbl_text.grid(row=r, column=0, sticky="w")
        self._v_text = tk.StringVar()
        self._ent_text = ttk.Entry(form, textvariable=self._v_text, width=60)
        self._ent_text.grid(row=r, column=1, sticky="ew")
        self._btn_text = ttk.Button(form, text="浏览", command=self._browse_text)
        self._btn_text.grid(row=r, column=2)

        # --- 批量输入 ---
        r += 1
        self._lbl_audio_dir = ttk.Label(form, text="音频文件夹:")
        self._lbl_audio_dir.grid(row=r, column=0, sticky="w")
        self._v_audio_dir = tk.StringVar()
        self._ent_audio_dir = ttk.Entry(form, textvariable=self._v_audio_dir, width=60)
        self._ent_audio_dir.grid(row=r, column=1, sticky="ew")
        self._btn_audio_dir = ttk.Button(form, text="浏览",
                                          command=lambda: self._browse_dir(self._v_audio_dir))
        self._btn_audio_dir.grid(row=r, column=2)

        r += 1
        self._lbl_text_dir = ttk.Label(form, text="文本文件夹:")
        self._lbl_text_dir.grid(row=r, column=0, sticky="w")
        self._v_text_dir = tk.StringVar()
        self._ent_text_dir = ttk.Entry(form, textvariable=self._v_text_dir, width=60)
        self._ent_text_dir.grid(row=r, column=1, sticky="ew")
        self._btn_text_dir = ttk.Button(form, text="浏览",
                                         command=lambda: self._browse_dir(self._v_text_dir))
        self._btn_text_dir.grid(row=r, column=2)

        # --- 预切割合并输入 ---
        r += 1
        self._lbl_presplit = ttk.Label(form, text="预切割文件夹:")
        self._lbl_presplit.grid(row=r, column=0, sticky="w")
        self._v_presplit = tk.StringVar()
        self._ent_presplit = ttk.Entry(form, textvariable=self._v_presplit, width=60)
        self._ent_presplit.grid(row=r, column=1, sticky="ew")
        self._btn_presplit = ttk.Button(form, text="浏览",
                                         command=lambda: self._browse_dir(self._v_presplit))
        self._btn_presplit.grid(row=r, column=2)

        # --- 输出目录 ---
        r += 1
        ttk.Label(form, text="输出目录:").grid(row=r, column=0, sticky="w")
        self._v_output = tk.StringVar()
        ttk.Entry(form, textvariable=self._v_output, width=60).grid(row=r, column=1, sticky="ew")
        ttk.Button(form, text="浏览",
                   command=lambda: self._browse_dir(self._v_output)).grid(row=r, column=2)

        # --- 输出格式 ---
        r += 1
        ttk.Label(form, text="输出格式:").grid(row=r, column=0, sticky="w")
        fmt_f = ttk.Frame(form)
        fmt_f.grid(row=r, column=1, sticky="w")
        self._fmt_asr = tk.BooleanVar(value=True)
        self._fmt_json = tk.BooleanVar(value=False)
        self._fmt_srt = tk.BooleanVar(value=False)
        self._fmt_vtt = tk.BooleanVar(value=False)
        ttk.Checkbutton(fmt_f, text="JSON(读取音频)", variable=self._fmt_asr,
                         command=self._on_fmt_change).pack(side="left")
        ttk.Checkbutton(fmt_f, text="JSON", variable=self._fmt_json).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(fmt_f, text="SRT", variable=self._fmt_srt).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(fmt_f, text="VTT", variable=self._fmt_vtt).pack(side="left", padx=(12, 0))

        # --- ASR 引导对齐 ---
        r += 1
        self._asr_guided = tk.BooleanVar(value=False)
        self._chk_asr_guided = ttk.Checkbutton(
            form, text="ASR 引导对齐（长音频推荐：ASR识别→强制对齐→映射回原文）",
            variable=self._asr_guided, command=self._on_fmt_change,
        )
        self._chk_asr_guided.grid(row=r, column=0, columnspan=3, sticky="w")

        # --- SRT 每行字数 ---
        r += 1
        ttk.Label(form, text="SRT/VTT 每行最大字数:").grid(row=r, column=0, sticky="w")
        self._v_max_chars = tk.StringVar(value="40")
        ttk.Entry(form, textvariable=self._v_max_chars, width=8).grid(row=r, column=1, sticky="w")

        # --- 语言 ---
        r += 1
        ttk.Label(form, text="语言:").grid(row=r, column=0, sticky="w")
        self._v_lang = tk.StringVar(value="English")
        lang_f = ttk.Frame(form)
        lang_f.grid(row=r, column=1, sticky="w")
        for lang in ("Chinese", "English", "Japanese", "Korean"):
            ttk.Radiobutton(lang_f, text=lang, variable=self._v_lang,
                            value=lang).pack(side="left", padx=(0, 8))

        # --- 对齐模型路径 ---
        r += 1
        self._lbl_model = ttk.Label(form, text="对齐模型路径:")
        self._lbl_model.grid(row=r, column=0, sticky="w")
        self._v_model = tk.StringVar(value="D:\\my_models\\Qwen3-ForcedAligner-0.6B")
        self._ent_model = ttk.Entry(form, textvariable=self._v_model, width=60)
        self._ent_model.grid(row=r, column=1, sticky="ew")

        # --- ASR 模型路径 ---
        r += 1
        self._lbl_asr_model = ttk.Label(form, text="ASR 模型路径:")
        self._lbl_asr_model.grid(row=r, column=0, sticky="w")
        self._v_asr_model = tk.StringVar(value="D:\\my_models\\Qwen3-ASR-0.6B")
        self._ent_asr_model = ttk.Entry(form, textvariable=self._v_asr_model, width=60)
        self._ent_asr_model.grid(row=r, column=1, sticky="ew")

        # --- 开始按钮 ---
        r += 1
        self._btn_start = ttk.Button(form, text="开始对齐", command=self._do_align)
        self._btn_start.grid(row=r, column=0, columnspan=2, pady=(10, 0), sticky="w")

        # 初始化 UI 状态
        self._on_mode_change()
        self._on_fmt_change()

    # ------------------------------------------------------------------
    # 日志区
    # ------------------------------------------------------------------

    def _build_log(self, parent) -> None:
        log_frame = ttk.LabelFrame(parent, text="日志")
        log_frame.pack(fill="both", padx=6, pady=6, expand=True)

        self.log_text = tk.Text(
            log_frame, height=10, wrap="word",
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

    def _run_threaded(self, fn, *args) -> None:
        if self._busy:
            self._log("操作进行中，请等待...")
            return
        self._busy = True
        self.status_var.set("执行中...")
        self._btn_start.config(state="disabled")

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
        self._btn_start.config(state="normal")

    # ------------------------------------------------------------------
    # 浏览
    # ------------------------------------------------------------------

    def _browse_audio(self) -> None:
        f = filedialog.askopenfilename(filetypes=_AUDIO_FILETYPES)
        if f:
            self._v_audio.set(f)

    def _browse_text(self) -> None:
        f = filedialog.askopenfilename(filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if f:
            self._v_text.set(f)

    def _browse_dir(self, var: tk.StringVar) -> None:
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    # ------------------------------------------------------------------
    # 模式切换
    # ------------------------------------------------------------------

    def _is_asr_only(self) -> bool:
        """仅选中 JSON(读取音频) 时为 ASR 模式，不需要文本输入。"""
        return (self._fmt_asr.get()
                and not self._fmt_json.get()
                and not self._fmt_srt.get()
                and not self._fmt_vtt.get())

    def _on_fmt_change(self) -> None:
        self._on_mode_change()
        # ASR 模型路径：ASR-only 或 ASR 引导模式都需要
        need_asr = self._fmt_asr.get() or self._asr_guided.get()
        if need_asr:
            self._lbl_asr_model.grid()
            self._ent_asr_model.grid()
        else:
            self._lbl_asr_model.grid_remove()
            self._ent_asr_model.grid_remove()

    def _on_mode_change(self) -> None:
        mode = self._mode.get()
        asr_only = self._is_asr_only()

        # 隐藏所有输入控件，再按模式显示
        for w in (self._lbl_audio, self._ent_audio, self._btn_audio,
                  self._lbl_text, self._ent_text, self._btn_text,
                  self._lbl_audio_dir, self._ent_audio_dir, self._btn_audio_dir,
                  self._lbl_text_dir, self._ent_text_dir, self._btn_text_dir,
                  self._lbl_presplit, self._ent_presplit, self._btn_presplit):
            w.grid_remove()

        if mode == "single":
            for w in (self._lbl_audio, self._ent_audio, self._btn_audio):
                w.grid()
            if not asr_only:
                for w in (self._lbl_text, self._ent_text, self._btn_text):
                    w.grid()
        elif mode == "batch":
            for w in (self._lbl_audio_dir, self._ent_audio_dir, self._btn_audio_dir):
                w.grid()
            if not asr_only:
                for w in (self._lbl_text_dir, self._ent_text_dir, self._btn_text_dir):
                    w.grid()
        elif mode == "presplit":
            for w in (self._lbl_presplit, self._ent_presplit, self._btn_presplit):
                w.grid()

    # ------------------------------------------------------------------
    # 执行对齐
    # ------------------------------------------------------------------

    def _get_formats(self) -> tuple:
        fmts = []
        if self._fmt_json.get():
            fmts.append("json")
        if self._fmt_srt.get():
            fmts.append("srt")
        if self._fmt_vtt.get():
            fmts.append("vtt")
        return tuple(fmts) or ("json",)

    def _do_align(self) -> None:
        if not _ALIGNER_OK:
            messagebox.showerror("错误", "ForcedAligner 模块不可用，请检查依赖。")
            return

        output_dir = self._v_output.get().strip()
        if not output_dir:
            messagebox.showerror("输入错误", "请指定输出目录。")
            return

        language = self._v_lang.get().strip()
        model = self._v_model.get().strip()
        asr_model = self._v_asr_model.get().strip()
        use_asr = self._fmt_asr.get()

        # ASR 模式：仅需音频
        if self._is_asr_only():
            if self._mode.get() == "batch":
                audio_dir = self._v_audio_dir.get().strip()
                if not audio_dir:
                    messagebox.showerror("输入错误", "请指定音频文件夹。")
                    return
                self._run_threaded(
                    self._batch_asr_worker, audio_dir, output_dir,
                    model, asr_model, language,
                )
            else:
                audio = self._v_audio.get().strip()
                if not audio:
                    messagebox.showerror("输入错误", "请指定音频文件。")
                    return
                self._run_threaded(
                    self._single_asr_worker, audio, output_dir,
                    model, asr_model, language,
                )
            return

        # 预切割合并模式
        if self._mode.get() == "presplit":
            presplit_dir = self._v_presplit.get().strip()
            if not presplit_dir:
                messagebox.showerror("输入错误", "请指定预切割文件夹。")
                return
            self._run_threaded(
                self._presplit_worker, presplit_dir, output_dir, model, language,
            )
            return

        try:
            max_chars = int(self._v_max_chars.get().strip())
        except ValueError:
            messagebox.showerror("输入错误", "每行最大字数必须是整数。")
            return

        formats = self._get_formats()
        asr_guided = self._asr_guided.get()

        if self._mode.get() == "batch":
            audio_dir = self._v_audio_dir.get().strip()
            text_dir = self._v_text_dir.get().strip()
            if not audio_dir or not text_dir:
                messagebox.showerror("输入错误", "请指定音频文件夹和文本文件夹。")
                return
            if asr_guided:
                self._run_threaded(
                    self._batch_asr_guided_worker, audio_dir, text_dir, output_dir,
                    formats, max_chars, model, asr_model, language,
                )
            else:
                self._run_threaded(
                    self._batch_worker, audio_dir, text_dir, output_dir,
                    formats, max_chars, model, language,
                )
        else:
            audio = self._v_audio.get().strip()
            text = self._v_text.get().strip()
            if not audio or not text:
                messagebox.showerror("输入错误", "请指定音频文件和文本文件。")
                return
            if asr_guided:
                self._run_threaded(
                    self._single_asr_guided_worker, audio, text, output_dir,
                    formats, max_chars, model, asr_model, language,
                )
            else:
                self._run_threaded(
                    self._single_worker, audio, text, output_dir,
                    formats, max_chars, model, language,
                )

    def _single_worker(
        self, audio: str, text: str, output_dir: str,
        formats: tuple, max_chars: int, model: str, language: str,
    ) -> None:
        aligner = ForcedAligner(
            model_path=model, language=language, progress_callback=self._log,
        )
        r = aligner.align(audio, text, output_dir, formats=formats, srt_max_chars=max_chars)
        if r.success:
            self._log(f"对齐完成! 输出 {len(r.words)} 个词级时间戳")
            if r.output_json:
                self._log(f"  JSON: {r.output_json}")
            if r.output_srt:
                self._log(f"  SRT:  {r.output_srt}")
            if r.output_vtt:
                self._log(f"  VTT:  {r.output_vtt}")
        else:
            self._log(f"对齐失败: {r.error}")

    def _batch_worker(
        self, audio_dir: str, text_dir: str, output_dir: str,
        formats: tuple, max_chars: int, model: str, language: str,
    ) -> None:
        aligner = ForcedAligner(
            model_path=model, language=language, progress_callback=self._log,
        )
        aligner.batch_align(
            audio_dir, text_dir, output_dir,
            formats=formats, srt_max_chars=max_chars,
        )

    # ------------------------------------------------------------------
    # ASR 引导对齐 workers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 预切割合并 worker
    # ------------------------------------------------------------------

    def _presplit_worker(
        self, folder: str, output_dir: str, model: str, language: str,
    ) -> None:
        aligner = ForcedAligner(
            model_path=model, language=language, progress_callback=self._log,
        )
        r = aligner.align_presplit(folder, output_dir)
        if r.success:
            self._log(f"预切割合并完成! {len(r.words)} 个词")
            if r.output_json:
                self._log(f"  JSON: {r.output_json}")
        else:
            self._log(f"预切割合并失败: {r.error}")

    # ------------------------------------------------------------------
    # ASR 引导对齐 workers
    # ------------------------------------------------------------------

    def _single_asr_guided_worker(
        self, audio: str, text: str, output_dir: str,
        formats: tuple, max_chars: int, model: str, asr_model: str, language: str,
    ) -> None:
        aligner = ForcedAligner(
            model_path=model, language=language, progress_callback=self._log,
        )
        r = aligner.align_with_asr(
            audio, text, output_dir,
            asr_model_path=asr_model, formats=formats, srt_max_chars=max_chars,
        )
        if r.success:
            self._log(f"ASR 引导对齐完成! 输出 {len(r.words)} 个词级时间戳")
            if r.output_json:
                self._log(f"  JSON: {r.output_json}")
            if r.output_srt:
                self._log(f"  SRT:  {r.output_srt}")
            if r.output_vtt:
                self._log(f"  VTT:  {r.output_vtt}")
        else:
            self._log(f"ASR 引导对齐失败: {r.error}")

    def _batch_asr_guided_worker(
        self, audio_dir: str, text_dir: str, output_dir: str,
        formats: tuple, max_chars: int, model: str, asr_model: str, language: str,
    ) -> None:
        aligner = ForcedAligner(
            model_path=model, language=language, progress_callback=self._log,
        )
        aligner.batch_align_with_asr(
            audio_dir, text_dir, output_dir,
            asr_model_path=asr_model, formats=formats, srt_max_chars=max_chars,
        )

    # ------------------------------------------------------------------
    # ASR 语音识别 workers (仅音频，无文本)
    # ------------------------------------------------------------------

    def _single_asr_worker(
        self, audio: str, output_dir: str,
        model: str, asr_model: str, language: str,
    ) -> None:
        aligner = ForcedAligner(
            model_path=model, language=language, progress_callback=self._log,
        )
        r = aligner.transcribe_audio(audio, output_dir, asr_model_path=asr_model)
        if r.success:
            self._log(f"ASR 完成! 输出 {len(r.words)} 个词级时间戳")
            if r.output_json:
                self._log(f"  JSON: {r.output_json}")
        else:
            self._log(f"ASR 失败: {r.error}")

    def _batch_asr_worker(
        self, audio_dir: str, output_dir: str,
        model: str, asr_model: str, language: str,
    ) -> None:
        aligner = ForcedAligner(
            model_path=model, language=language, progress_callback=self._log,
        )
        results = aligner.batch_transcribe(audio_dir, output_dir, asr_model_path=asr_model)
        ok = sum(1 for r in results if r.success)
        self._log(f"批量 ASR 完成: {ok}/{len(results)} 成功")


def main() -> None:
    root = tk.Tk()
    ForcedAlignApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
