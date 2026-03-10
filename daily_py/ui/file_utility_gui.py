#!/usr/bin/env python3
"""DailyPy 文件工具箱 — 通用文件管理 GUI。

集成文件搜索、批量重命名、备份、压缩/解压、查找重复文件等功能。

运行方式::

    python -m daily_py.ui.file_utility_gui
"""

from __future__ import annotations

import datetime
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List

try:
    from daily_py.file_handler import FileHandler
except Exception:
    messagebox.showerror("导入错误", "无法导入 DailyPy 的 FileHandler，请确保以包方式运行。")
    raise


def _fmt_size(size: int) -> str:
    """将字节数格式化为可读字符串。"""
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.2f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _fmt_time(ts: float) -> str:
    """将 epoch 时间戳格式化为 ``YYYY-MM-DD HH:MM:SS``。"""
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class FileUtilityApp:
    """统一文件工具箱 GUI。"""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("DailyPy - 文件工具箱")
        master.geometry("1020x720")
        master.minsize(800, 550)

        self.fh = FileHandler()
        self._log_queue: queue.Queue = queue.Queue()
        self._busy = False

        # ---- 主布局 ----
        top = ttk.Frame(master)
        top.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        self.notebook = ttk.Notebook(top)
        self.notebook.pack(fill="both", expand=True)

        # ---- 各 Tab ----
        self._build_search_tab()
        self._build_rename_tab()
        self._build_backup_tab()
        self._build_compress_tab()
        self._build_duplicates_tab()

        # ---- 底部日志面板 ----
        log_frame = ttk.LabelFrame(master, text="日志")
        log_frame.pack(fill="both", padx=6, pady=6, expand=False)

        self.log_text = tk.Text(
            log_frame, height=10, wrap="word",
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

        # 定时轮询日志队列
        self._poll_log()

    # ------------------------------------------------------------------
    # 共享工具方法
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

    def _browse_file(self, var: tk.StringVar, **kw) -> None:
        f = filedialog.askopenfilename(**kw)
        if f:
            var.set(f)

    def _browse_save(self, var: tk.StringVar, **kw) -> None:
        f = filedialog.asksaveasfilename(**kw)
        if f:
            var.set(f)

    def _run_threaded(self, fn, *args, **kwargs) -> None:
        """在后台线程执行 *fn*，期间禁用主要按钮。"""
        if self._busy:
            self._log("操作进行中，请等待...")
            return
        self._busy = True
        self.status_var.set("执行中...")

        def _wrapper():
            try:
                fn(*args, **kwargs)
            except Exception as exc:
                self._log(f"错误: {exc}")
            finally:
                self.master.after(0, self._on_done)

        threading.Thread(target=_wrapper, daemon=True).start()

    def _on_done(self) -> None:
        self._busy = False
        self.status_var.set("就绪")

    # ------------------------------------------------------------------
    # Tab 0: 文件搜索
    # ------------------------------------------------------------------

    def _build_search_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="文件搜索")

        # 输入区
        r = 0
        ttk.Label(tab, text="目标目录:").grid(row=r, column=0, sticky="w")
        self._s_dir = tk.StringVar()
        ttk.Entry(tab, textvariable=self._s_dir, width=60).grid(row=r, column=1, sticky="ew")
        ttk.Button(tab, text="浏览", command=lambda: self._browse_dir(self._s_dir)).grid(row=r, column=2)

        r += 1
        ttk.Label(tab, text="文件名模式:").grid(row=r, column=0, sticky="w")
        self._s_pattern = tk.StringVar(value="*")
        ttk.Entry(tab, textvariable=self._s_pattern, width=30).grid(row=r, column=1, sticky="w")

        r += 1
        self._s_recursive = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="递归子目录", variable=self._s_recursive).grid(row=r, column=0, sticky="w")
        ttk.Button(tab, text="搜索", command=self._do_search).grid(row=r, column=1, sticky="w")

        # 结果 Treeview
        r += 1
        cols = ("name", "size", "ext", "modified", "path")
        self._s_tree = ttk.Treeview(tab, columns=cols, show="headings", height=14)
        self._s_tree.heading("name", text="文件名")
        self._s_tree.heading("size", text="大小")
        self._s_tree.heading("ext", text="扩展名")
        self._s_tree.heading("modified", text="修改时间")
        self._s_tree.heading("path", text="路径")
        self._s_tree.column("name", width=200)
        self._s_tree.column("size", width=80, anchor="e")
        self._s_tree.column("ext", width=60)
        self._s_tree.column("modified", width=140)
        self._s_tree.column("path", width=400)
        self._s_tree.grid(row=r, column=0, columnspan=3, sticky="nsew")
        sb = ttk.Scrollbar(tab, orient="vertical", command=self._s_tree.yview)
        sb.grid(row=r, column=3, sticky="ns")
        self._s_tree.config(yscrollcommand=sb.set)

        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(r, weight=1)

    def _do_search(self) -> None:
        d = self._s_dir.get().strip()
        if not d:
            messagebox.showerror("输入错误", "请输入目标目录。")
            return
        self._run_threaded(self._search_worker, d)

    def _search_worker(self, directory: str) -> None:
        pattern = self._s_pattern.get().strip() or "*"
        recursive = self._s_recursive.get()
        self._log(f"搜索: {directory}  模式={pattern}  递归={recursive}")
        files = self.fh.search_files(directory, pattern, recursive=recursive)
        self._log(f"找到 {len(files)} 个文件")
        # 在主线程更新 treeview
        self.master.after(0, self._populate_search_tree, files)

    def _populate_search_tree(self, files: List[Path]) -> None:
        self._s_tree.delete(*self._s_tree.get_children())
        for p in files:
            try:
                st = p.stat()
                self._s_tree.insert("", "end", values=(
                    p.name, _fmt_size(st.st_size), p.suffix,
                    _fmt_time(st.st_mtime), str(p),
                ))
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Tab 1: 批量重命名
    # ------------------------------------------------------------------

    def _build_rename_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="批量重命名")

        r = 0
        ttk.Label(tab, text="目标目录:").grid(row=r, column=0, sticky="w")
        self._r_dir = tk.StringVar()
        ttk.Entry(tab, textvariable=self._r_dir, width=60).grid(row=r, column=1, sticky="ew")
        ttk.Button(tab, text="浏览", command=lambda: self._browse_dir(self._r_dir)).grid(row=r, column=2)

        r += 1
        ttk.Label(tab, text="查找模式:").grid(row=r, column=0, sticky="w")
        self._r_pattern = tk.StringVar()
        ttk.Entry(tab, textvariable=self._r_pattern, width=60).grid(row=r, column=1, sticky="ew")

        r += 1
        ttk.Label(tab, text="替换为:").grid(row=r, column=0, sticky="w")
        self._r_replacement = tk.StringVar()
        ttk.Entry(tab, textvariable=self._r_replacement, width=60).grid(row=r, column=1, sticky="ew")

        r += 1
        self._r_regex = tk.BooleanVar(value=False)
        self._r_recursive = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text="使用正则表达式", variable=self._r_regex).grid(row=r, column=0, sticky="w")
        ttk.Checkbutton(tab, text="递归处理子目录", variable=self._r_recursive).grid(row=r, column=1, sticky="w")

        r += 1
        self._r_include_dirs = tk.BooleanVar(value=True)
        self._r_dry_run = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text="同时处理目录名", variable=self._r_include_dirs).grid(row=r, column=0, sticky="w")
        ttk.Checkbutton(tab, text="仅预览（dry-run）", variable=self._r_dry_run).grid(row=r, column=1, sticky="w")

        r += 1
        self._r_case_rename = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="允许大小写重命名（Windows）", variable=self._r_case_rename).grid(
            row=r, column=0, columnspan=2, sticky="w")

        r += 1
        ttk.Button(tab, text="运行/预览", command=self._do_rename).grid(row=r, column=0, columnspan=2, pady=8)

        tab.columnconfigure(1, weight=1)

    def _do_rename(self) -> None:
        d = self._r_dir.get().strip()
        pattern = self._r_pattern.get()
        replacement = self._r_replacement.get()
        if not d:
            messagebox.showerror("输入错误", "请输入目标目录。")
            return
        if not pattern:
            messagebox.showerror("输入错误", "请输入查找模式。")
            return

        self._log("--- 批量重命名 ---")
        self._log(f"目录: {d}")
        self._log(f"模式: {pattern}  替换: {replacement}")
        self._log(f"正则: {self._r_regex.get()}  递归: {self._r_recursive.get()}")
        self._log(f"含目录: {self._r_include_dirs.get()}  dry-run: {self._r_dry_run.get()}  大小写重命名: {self._r_case_rename.get()}")

        self._run_threaded(self._rename_worker, d, pattern, replacement)

    def _rename_worker(self, directory: str, pattern: str, replacement: str) -> None:
        fh = FileHandler(base_path=directory)
        case_rename = self._r_case_rename.get()
        if self._r_recursive.get():
            res = fh.batch_rename_recursive(
                directory, pattern, replacement,
                use_regex=self._r_regex.get(),
                include_dirs=self._r_include_dirs.get(),
                dry_run=self._r_dry_run.get(),
                case_rename=case_rename,
            )
            self._log(f"重命名: {res['count_renamed']}  跳过: {res['count_skipped']}  错误: {res['count_errors']}")
            for item in res["renamed"][:20]:
                self._log(f"  {item['old_path']} -> {item['new_path']}")
            if len(res["renamed"]) > 20:
                self._log(f"  ... 还有 {len(res['renamed']) - 20} 个")
            for item in res["errors"]:
                self._log(f"  错误: {item['error']}")
        else:
            count = fh.batch_rename(directory, pattern, replacement,
                                    use_regex=self._r_regex.get(), case_rename=case_rename)
            self._log(f"重命名文件数: {count}")

    # ------------------------------------------------------------------
    # Tab 2: 备份
    # ------------------------------------------------------------------

    _BACKUP_EXT_PRESETS = ["*", "*.mp3", "*.mp4", "*.png", "*.jpg", "*.json", "*.txt", "*.pdf", "*.doc", "*.xlsx"]

    def _build_backup_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="备份")

        r = 0
        ttk.Label(tab, text="源文件/目录:").grid(row=r, column=0, sticky="w")
        self._b_src = tk.StringVar()
        ttk.Entry(tab, textvariable=self._b_src, width=55).grid(row=r, column=1, sticky="ew")
        btn_frm = ttk.Frame(tab)
        btn_frm.grid(row=r, column=2)
        ttk.Button(btn_frm, text="选择文件", command=lambda: self._browse_file(self._b_src)).pack(side="left", padx=2)
        ttk.Button(btn_frm, text="选择目录", command=lambda: self._browse_dir(self._b_src)).pack(side="left", padx=2)

        r += 1
        ttk.Label(tab, text="备份到:").grid(row=r, column=0, sticky="w")
        self._b_dst = tk.StringVar()
        ttk.Entry(tab, textvariable=self._b_dst, width=55).grid(row=r, column=1, sticky="ew")
        ttk.Button(tab, text="浏览", command=lambda: self._browse_dir(self._b_dst)).grid(row=r, column=2)

        r += 1
        ttk.Label(tab, text="文件匹配:").grid(row=r, column=0, sticky="w")
        self._b_filter = tk.StringVar(value="*")
        filter_frm = ttk.Frame(tab)
        filter_frm.grid(row=r, column=1, sticky="ew")
        ttk.Combobox(filter_frm, textvariable=self._b_filter, values=self._BACKUP_EXT_PRESETS,
                      width=12).pack(side="left")
        ttk.Label(filter_frm, text="  (可手动输入，如 *.mp3 或 *.py)").pack(side="left")

        r += 1
        self._b_keep_name = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="保持原文件名（不加时间戳后缀）", variable=self._b_keep_name).grid(
            row=r, column=0, columnspan=2, sticky="w")

        r += 1
        ttk.Button(tab, text="创建备份", command=self._do_backup).grid(row=r, column=0, columnspan=2, pady=8)

        tab.columnconfigure(1, weight=1)

    def _do_backup(self) -> None:
        src = self._b_src.get().strip()
        if not src:
            messagebox.showerror("输入错误", "请选择源文件或目录。")
            return
        self._run_threaded(self._backup_worker, src)

    def _backup_worker(self, src: str) -> None:
        dst = self._b_dst.get().strip() or None
        keep_name = self._b_keep_name.get()
        pattern = self._b_filter.get().strip() or "*"
        p = Path(src)
        if p.is_file():
            bp = self.fh.backup_file(src, dst, keep_name=keep_name)
            self._log(f"已备份: {src} -> {bp}")
        elif p.is_dir():
            files = self.fh.list_files(src, pattern)
            self._log(f"备份目录: {src}  匹配={pattern}  共 {len(files)} 个文件  保持原名={keep_name}")
            count = 0
            for f in files:
                try:
                    bp = self.fh.backup_file(str(f), dst, keep_name=keep_name)
                    self._log(f"  {f.name} -> {bp}")
                    count += 1
                except Exception as exc:
                    self._log(f"  错误 ({f.name}): {exc}")
            self._log(f"备份完成: 共 {count} 个文件")
        else:
            self._log(f"路径不存在: {src}")

    # ------------------------------------------------------------------
    # Tab 3: 压缩/解压
    # ------------------------------------------------------------------

    def _build_compress_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="压缩/解压")

        # 左：压缩
        left = ttk.LabelFrame(tab, text="压缩", padding=6)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        ttk.Button(left, text="添加文件", command=self._compress_add_files).grid(row=0, column=0, sticky="w")
        ttk.Button(left, text="清空列表", command=self._compress_clear).grid(row=0, column=1, sticky="w", padx=4)

        self._c_listbox = tk.Listbox(left, height=8, width=50)
        self._c_listbox.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=4)
        self._c_files: List[str] = []

        ttk.Label(left, text="输出路径:").grid(row=2, column=0, sticky="w")
        self._c_output = tk.StringVar()
        ttk.Entry(left, textvariable=self._c_output, width=40).grid(row=3, column=0, sticky="ew")
        ttk.Button(left, text="浏览", command=lambda: self._browse_save(
            self._c_output, defaultextension=".zip",
            filetypes=[("ZIP", "*.zip"), ("TAR", "*.tar"), ("所有文件", "*.*")],
        )).grid(row=3, column=1)

        ttk.Label(left, text="格式:").grid(row=4, column=0, sticky="w")
        self._c_fmt = tk.StringVar(value="zip")
        ttk.Combobox(left, textvariable=self._c_fmt, values=["zip", "tar", "gztar"], width=10, state="readonly").grid(row=4, column=1, sticky="w")

        ttk.Button(left, text="压缩", command=self._do_compress).grid(row=5, column=0, columnspan=2, pady=6)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        # 右：解压
        right = ttk.LabelFrame(tab, text="解压", padding=6)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        ttk.Label(right, text="压缩文件:").grid(row=0, column=0, sticky="w")
        self._e_archive = tk.StringVar()
        ttk.Entry(right, textvariable=self._e_archive, width=40).grid(row=1, column=0, sticky="ew")
        ttk.Button(right, text="浏览", command=lambda: self._browse_file(
            self._e_archive, filetypes=[("压缩文件", "*.zip *.tar *.tar.gz *.tgz *.bz2 *.xz"), ("所有文件", "*.*")],
        )).grid(row=1, column=1)

        ttk.Label(right, text="解压到:").grid(row=2, column=0, sticky="w")
        self._e_dest = tk.StringVar()
        ttk.Entry(right, textvariable=self._e_dest, width=40).grid(row=3, column=0, sticky="ew")
        ttk.Button(right, text="浏览", command=lambda: self._browse_dir(self._e_dest)).grid(row=3, column=1)

        ttk.Button(right, text="解压", command=self._do_extract).grid(row=4, column=0, columnspan=2, pady=6)
        right.columnconfigure(0, weight=1)

        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

    def _compress_add_files(self) -> None:
        files = filedialog.askopenfilenames(title="选择要压缩的文件")
        if files:
            for f in files:
                if f not in self._c_files:
                    self._c_files.append(f)
                    self._c_listbox.insert("end", f)

    def _compress_clear(self) -> None:
        self._c_files.clear()
        self._c_listbox.delete(0, "end")

    def _do_compress(self) -> None:
        if not self._c_files:
            messagebox.showerror("输入错误", "请先添加要压缩的文件。")
            return
        output = self._c_output.get().strip()
        if not output:
            messagebox.showerror("输入错误", "请指定输出路径。")
            return
        self._run_threaded(self._compress_worker, list(self._c_files), output)

    def _compress_worker(self, files: List[str], output: str) -> None:
        fmt = self._c_fmt.get()
        self._log(f"压缩 {len(files)} 个文件 -> {output}  (格式: {fmt})")
        self.fh.compress_files(files, output, format=fmt)
        size = Path(output).stat().st_size if Path(output).exists() else 0
        self._log(f"压缩完成: {output}  ({_fmt_size(size)})")

    def _do_extract(self) -> None:
        archive = self._e_archive.get().strip()
        dest = self._e_dest.get().strip()
        if not archive:
            messagebox.showerror("输入错误", "请选择压缩文件。")
            return
        if not dest:
            messagebox.showerror("输入错误", "请选择解压目标目录。")
            return
        self._run_threaded(self._extract_worker, archive, dest)

    def _extract_worker(self, archive: str, dest: str) -> None:
        self._log(f"解压: {archive} -> {dest}")
        self.fh.extract_archive(archive, dest)
        self._log("解压完成")

    # ------------------------------------------------------------------
    # Tab 4: 查找重复文件
    # ------------------------------------------------------------------

    def _build_duplicates_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="查找重复")

        r = 0
        ttk.Label(tab, text="扫描目录:").grid(row=r, column=0, sticky="w")
        self._d_dir = tk.StringVar()
        ttk.Entry(tab, textvariable=self._d_dir, width=60).grid(row=r, column=1, sticky="ew")
        ttk.Button(tab, text="浏览", command=lambda: self._browse_dir(self._d_dir)).grid(row=r, column=2)

        r += 1
        ttk.Button(tab, text="开始扫描", command=self._do_duplicates).grid(row=r, column=0, columnspan=2, pady=6)

        r += 1
        cols = ("group", "name", "size", "path")
        self._d_tree = ttk.Treeview(tab, columns=cols, show="headings", height=14)
        self._d_tree.heading("group", text="分组")
        self._d_tree.heading("name", text="文件名")
        self._d_tree.heading("size", text="大小")
        self._d_tree.heading("path", text="路径")
        self._d_tree.column("group", width=60, anchor="center")
        self._d_tree.column("name", width=200)
        self._d_tree.column("size", width=80, anchor="e")
        self._d_tree.column("path", width=500)
        self._d_tree.grid(row=r, column=0, columnspan=3, sticky="nsew")
        sb = ttk.Scrollbar(tab, orient="vertical", command=self._d_tree.yview)
        sb.grid(row=r, column=3, sticky="ns")
        self._d_tree.config(yscrollcommand=sb.set)

        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(r, weight=1)

    def _do_duplicates(self) -> None:
        d = self._d_dir.get().strip()
        if not d:
            messagebox.showerror("输入错误", "请输入扫描目录。")
            return
        self._run_threaded(self._dup_worker, d)

    def _dup_worker(self, directory: str) -> None:
        self._log(f"扫描重复文件: {directory}")
        dups = self.fh.find_duplicate_files(directory)
        if not dups:
            self._log("未发现重复文件")
            self.master.after(0, self._populate_dup_tree, {})
            return
        total = sum(len(v) - 1 for v in dups.values())
        self._log(f"发现 {len(dups)} 组重复文件，共 {total} 个重复项")
        self.master.after(0, self._populate_dup_tree, dups)

    def _populate_dup_tree(self, dups: dict) -> None:
        self._d_tree.delete(*self._d_tree.get_children())
        for idx, (key, files) in enumerate(dups.items(), 1):
            parts = key.split("_", 1)
            size_str = _fmt_size(int(parts[0])) if parts[0].isdigit() else parts[0]
            for f in files:
                self._d_tree.insert("", "end", values=(
                    f"#{idx}", Path(f).name, size_str, str(f),
                ))


def main():
    root = tk.Tk()
    FileUtilityApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
