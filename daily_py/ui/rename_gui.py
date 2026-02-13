#!/usr/bin/env python3
"""GUI for batch renaming in DailyPy FileHandler.

A tiny Tkinter app that lets you pick a directory, specify
the rename pattern, and run a batch rename recursively.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

try:
    # Import via package path for reliability when running as module
    from daily_py.file_handler import FileHandler
except Exception:
    messagebox.showerror("导入错误", "无法导入 DailyPy 的 FileHandler，请确保以包方式运行。")
    raise


class RenameApp:
    def __init__(self, master: tk.Tk | tk.Toplevel):
        self.master = master
        master.title("DailyPy - 批量重命名")

        frm = ttk.Frame(master, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        # Directory
        ttk.Label(frm, text="目标目录:").grid(row=0, column=0, sticky="w")
        self.dir_var = tk.StringVar()
        self.dir_entry = ttk.Entry(frm, textvariable=self.dir_var, width=60)
        self.dir_entry.grid(row=0, column=1, sticky="ew")

        # Pattern
        ttk.Label(frm, text="文本模式 (Format): ").grid(row=1, column=0, sticky="w")
        self.pattern_var = tk.StringVar(value="old")
        self.pattern_entry = ttk.Entry(frm, textvariable=self.pattern_var, width=60)
        self.pattern_entry.grid(row=1, column=1, sticky="ew")

        # Replacement
        ttk.Label(frm, text="替换为: ").grid(row=2, column=0, sticky="w")
        self.replacement_var = tk.StringVar(value="new")
        self.replacement_entry = ttk.Entry(frm, textvariable=self.replacement_var, width=60)
        self.replacement_entry.grid(row=2, column=1, sticky="ew")

        # Options
        self.regex_var = tk.BooleanVar(value=False)
        self.recursive_var = tk.BooleanVar(value=True)
        self.include_dirs_var = tk.BooleanVar(value=True)
        self.dry_run_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(frm, text="使用正则表达式", variable=self.regex_var).grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(frm, text="递归处理子目录", variable=self.recursive_var).grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(frm, text="同时处理目录名", variable=self.include_dirs_var).grid(row=4, column=0, sticky="w")
        ttk.Checkbutton(frm, text="仅预览（dry-run）", variable=self.dry_run_var).grid(row=4, column=1, sticky="w")

        # Run button
        self.run_btn = ttk.Button(frm, text="运行/预览", command=self.run_rename)
        self.run_btn.grid(row=5, column=0, columnspan=2, pady=8)

        # Output area
        self.output = tk.Text(frm, height=12, width=80, wrap="word")
        self.output.grid(row=6, column=0, columnspan=2, pady=8, sticky="nsew")
        frm.rowconfigure(6, weight=1)
        frm.columnconfigure(1, weight=1)

    def log(self, text: str):
        self.output.insert(tk.END, text + "\n")
        self.output.see(tk.END)

    def run_rename(self) -> None:
        dir_path = self.dir_var.get().strip()
        pattern = self.pattern_var.get()
        replacement = self.replacement_var.get()
        use_regex = self.regex_var.get()
        include_dirs = self.include_dirs_var.get()
        dry_run = self.dry_run_var.get()

        if not dir_path:
            messagebox.showerror("输入错误", "请提供目标目录路径。")
            return

        self.log("# 运行参数 #")
        self.log(f"目录: {dir_path}")
        self.log(f"模式: {pattern}")
        self.log(f"替换: {replacement}")
        self.log(f"使用正则: {use_regex}")
        self.log(f"递归: {bool(self.recursive_var.get())}")
        self.log(f"包含目录: {include_dirs}")
        self.log(f"dry_run: {dry_run}")
        self.log("------------------------------")

        fh = FileHandler(base_path=dir_path)
        try:
            if self.recursive_var.get():
                res = fh.batch_rename_recursive(
                    dir_path,
                    pattern,
                    replacement,
                    use_regex=use_regex,
                    include_dirs=include_dirs,
                    dry_run=dry_run,
                )
                self.log(f"重命名结果: {res}")
            else:
                count = fh.batch_rename(dir_path, pattern, replacement, use_regex=use_regex)
                self.log(f"重命名计数: {count}")
        except Exception as e:
            self.log(f"错误: {e}")


def main():
    root = tk.Tk()
    app = RenameApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
