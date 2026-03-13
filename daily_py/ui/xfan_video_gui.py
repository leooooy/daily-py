#!/usr/bin/env python3
"""XFans 视频管理 GUI — 数据列表、批量上传、instruct_url 批量更新。

运行方式::

    python -m daily_py.ui.xfan_video_gui
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 日志队列（把 logging / print 输出转入队列，供主线程渲染）
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue) -> None:
        super().__init__()
        self._q = q

    def emit(self, record: logging.LogRecord) -> None:
        self._q.put(("log", record.levelno, self.format(record)))


class _StdoutToQueue:
    def __init__(self, q: queue.Queue) -> None:
        self._q = q

    def write(self, msg: str) -> None:
        if msg.strip():
            self._q.put(("print", 0, msg.rstrip()))

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 表格列定义
# ---------------------------------------------------------------------------

_COLS = [
    ("id",                   "ID",          55,  "center"),
    ("character_id",         "角色ID",      60,  "center"),
    ("title",                "标题",        160, "w"),
    ("background",           "背景",        50,  "center"),
    ("deleted_flag",         "删除标志",    70,  "center"),
    ("service_level_limits", "等级限制",    70,  "center"),
    ("duration",             "时长(s)",     60,  "center"),
    ("click_count",          "点击数",      60,  "center"),
    ("cover_width",          "封面宽",      55,  "center"),
    ("cover_height",         "封面高",      55,  "center"),
    ("video_url",            "视频URL",     220, "w"),
    ("instruct_url",         "指令URL",     220, "w"),
    ("cover_url",            "封面URL",     220, "w"),
    ("create_time",          "创建时间",    145, "center"),
]
_COL_IDS     = [c[0] for c in _COLS]
_COL_HEADERS = [c[1] for c in _COLS]
_COL_WIDTHS  = [c[2] for c in _COLS]
_COL_ANCHORS = [c[3] for c in _COLS]


def _fmt(val) -> str:
    if val is None:
        return ""
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class XfanVideoApp:
    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("DailyPy - XFans 视频管理")
        master.minsize(1000, 680)
        master.geometry("1140x750")
        master.resizable(True, True)

        self._log_queue: queue.Queue = queue.Queue()
        self._task_queue: queue.Queue = queue.Queue()
        self._running = False

        # 数据列表状态
        self._repo = None
        self._db = None
        self._page = 1
        self._page_size = 50
        self._total = 0
        self._sort_col: Optional[str] = None
        self._sort_asc = True

        self._build_ui()
        self._poll_log()
        self._poll_task()

    # ==================================================================
    # UI 构建
    # ==================================================================

    def _build_ui(self) -> None:
        root = self.master
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        main = ttk.Frame(root, padding=8)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)
        main.rowconfigure(1, weight=0)

        # ── Notebook ──
        self.notebook = ttk.Notebook(main)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self._build_tab_list()
        self._build_tab_upload()
        self._build_tab_instruct()
        self._build_log_area(main)

    # ------------------------------------------------------------------
    # Tab 1: 数据列表
    # ------------------------------------------------------------------

    def _build_tab_list(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="数据列表")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        # ── 连接面板 ──
        conn_lf = ttk.LabelFrame(tab, text="数据库连接", padding=(8, 4))
        conn_lf.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(conn_lf, text="环境:").grid(row=0, column=0, padx=(0, 4))
        self.list_env_var = tk.StringVar(value="test")
        ttk.Combobox(
            conn_lf, textvariable=self.list_env_var,
            values=["test", "prod"], state="readonly", width=6,
        ).grid(row=0, column=1, padx=(0, 18))

        self.conn_btn = ttk.Button(conn_lf, text="连接", width=8, command=self._connect)
        self.conn_btn.grid(row=0, column=2, padx=(0, 6))

        self.disconn_btn = ttk.Button(
            conn_lf, text="断开", width=8, command=self._disconnect, state="disabled",
        )
        self.disconn_btn.grid(row=0, column=3)

        # ── 筛选面板 ──
        filter_lf = ttk.LabelFrame(tab, text="筛选条件", padding=(8, 4))
        filter_lf.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(filter_lf, text="删除状态:").grid(row=0, column=0, padx=(0, 4))
        self.del_flag_var = tk.StringVar(value="全部")
        ttk.Combobox(
            filter_lf, textvariable=self.del_flag_var,
            values=["全部", "正常 (1)", "已删除 (-1)"],
            state="readonly", width=11,
        ).grid(row=0, column=1, padx=(0, 14))

        ttk.Label(filter_lf, text="Background:").grid(row=0, column=2, padx=(0, 4))
        self.bg_filter_var = tk.StringVar(value="全部")
        ttk.Combobox(
            filter_lf, textvariable=self.bg_filter_var,
            values=["全部", "0: 普通", "1: 背景"],
            state="readonly", width=10,
        ).grid(row=0, column=3, padx=(0, 14))

        ttk.Label(filter_lf, text="关键词:").grid(row=0, column=4, padx=(0, 4))
        self.keyword_var = tk.StringVar()
        kw_entry = ttk.Entry(filter_lf, textvariable=self.keyword_var, width=22)
        kw_entry.grid(row=0, column=5, padx=(0, 14))
        kw_entry.bind("<Return>", lambda _e: self._search())

        ttk.Label(filter_lf, text="每页:").grid(row=0, column=6, padx=(0, 4))
        self.page_size_var = tk.StringVar(value="50")
        ttk.Combobox(
            filter_lf, textvariable=self.page_size_var,
            values=["20", "50", "100", "200"], state="readonly", width=5,
        ).grid(row=0, column=7, padx=(0, 14))

        self.search_btn = ttk.Button(
            filter_lf, text="查询", width=8, command=self._search, state="disabled",
        )
        self.search_btn.grid(row=0, column=8)

        # ── Treeview ──
        tree_frame = ttk.Frame(tab)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            tree_frame, columns=_COL_IDS, show="headings", selectmode="extended",
        )
        for cid, header, width, anchor in zip(_COL_IDS, _COL_HEADERS, _COL_WIDTHS, _COL_ANCHORS):
            self.tree.heading(cid, text=header, command=lambda c=cid: self._sort_by(c))
            self.tree.column(cid, width=width, minwidth=36, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("deleted", foreground="#999999")
        self.tree.tag_configure("normal",  foreground="#000000")

        # 右键菜单
        self._ctx_menu = tk.Menu(self.master, tearoff=0)
        self._ctx_menu.add_command(label="复制单元格", command=self._copy_cell)
        self._ctx_menu.add_command(label="复制整行",   command=self._copy_row)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="复制所选行", command=self._copy_selected_rows)
        self.tree.bind("<Button-3>",  self._on_right_click)
        self.tree.bind("<Control-c>", lambda *_: self._copy_selected_rows())

        # ── 操作按钮 + 分页 ──
        action_frame = ttk.Frame(tab)
        action_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        action_frame.columnconfigure(3, weight=1)

        self.soft_del_btn = ttk.Button(
            action_frame, text="软删除", width=9, command=self._soft_delete, state="disabled",
        )
        self.soft_del_btn.grid(row=0, column=0, padx=(0, 6))

        self.restore_btn = ttk.Button(
            action_frame, text="恢复", width=9, command=self._restore, state="disabled",
        )
        self.restore_btn.grid(row=0, column=1, padx=(0, 6))

        self.hard_del_btn = ttk.Button(
            action_frame, text="物理删除", width=10, command=self._hard_delete, state="disabled",
        )
        self.hard_del_btn.grid(row=0, column=2, padx=(0, 0))

        # 分页
        page_nav = ttk.Frame(action_frame)
        page_nav.grid(row=0, column=4)

        self.first_btn = ttk.Button(page_nav, text="<<", width=3, command=self._go_first, state="disabled")
        self.first_btn.pack(side="left", padx=2)
        self.prev_btn = ttk.Button(page_nav, text="<", width=3, command=self._go_prev, state="disabled")
        self.prev_btn.pack(side="left", padx=2)
        self.page_label = ttk.Label(page_nav, text="第 - / - 页", width=12, anchor="center")
        self.page_label.pack(side="left", padx=6)
        self.next_btn = ttk.Button(page_nav, text=">", width=3, command=self._go_next, state="disabled")
        self.next_btn.pack(side="left", padx=2)
        self.last_btn = ttk.Button(page_nav, text=">>", width=3, command=self._go_last, state="disabled")
        self.last_btn.pack(side="left", padx=2)
        self.total_label = ttk.Label(page_nav, text="共 0 条", width=10)
        self.total_label.pack(side="left", padx=(10, 0))

        # ── 状态栏 ──
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(
            tab, textvariable=self.status_var, relief="sunken", anchor="w", padding=(4, 2),
        ).grid(row=4, column=0, sticky="ew", pady=(4, 0))

    # ------------------------------------------------------------------
    # Tab 2: 视频+封面批量上传
    # ------------------------------------------------------------------

    def _build_tab_upload(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="视频+封面上传")
        tab.columnconfigure(1, weight=1)

        row = 0

        # 上传目录
        ttk.Label(tab, text="上传目录:").grid(row=row, column=0, sticky="w", pady=3)
        folder_frame = ttk.Frame(tab)
        folder_frame.grid(row=row, column=1, sticky="ew", pady=3)
        folder_frame.columnconfigure(0, weight=1)
        self.upload_folder_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self.upload_folder_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(folder_frame, text="浏览", command=self._browse_upload_folder, width=6).grid(
            row=0, column=1, padx=(4, 0),
        )
        row += 1

        # 环境
        ttk.Label(tab, text="环境:").grid(row=row, column=0, sticky="w", pady=3)
        self.upload_env_var = tk.StringVar(value="test")
        ttk.Combobox(
            tab, textvariable=self.upload_env_var,
            values=["test", "prod"], state="readonly", width=10,
        ).grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # 试运行
        self.upload_dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="试运行 (Dry-run)", variable=self.upload_dry_run_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=3,
        )
        row += 1

        ttk.Separator(tab, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6,
        )
        row += 1

        # S3 前缀
        for label, attr, default in [
            ("视频前缀:",  "upload_video_prefix_var",    "xfan"),
            ("封面前缀:",  "upload_cover_prefix_var",    "xfan/cover"),
            ("指令前缀:",  "upload_instruct_prefix_var", "xfan/instruct"),
        ]:
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            ttk.Entry(tab, textvariable=var).grid(row=row, column=1, sticky="ew", pady=2)
            row += 1

        # 封面截取时间
        ttk.Label(tab, text="封面截取时间(秒):").grid(row=row, column=0, sticky="w", pady=2)
        self.upload_cover_time_var = tk.StringVar(value="1.0")
        ttk.Entry(tab, textvariable=self.upload_cover_time_var, width=10).grid(
            row=row, column=1, sticky="w", pady=2,
        )
        row += 1

        # 说明
        note = ttk.Label(
            tab, foreground="#666666",
            text=(
                "说明：子文件夹命名格式 {character_id}_{name}（如 1004_Cum_Zoya）。\n"
                "同名 .mp4/.jpg/.json 组成一条记录；已有同名 .jpg 时不会重新截帧。\n"
                "文件夹名含 \"background\" 时 background=1，否则 =0。"
            ),
        )
        note.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 2))
        row += 1

        ttk.Separator(tab, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6,
        )
        row += 1

        # 按钮
        self.upload_btn = ttk.Button(tab, text="开始上传", command=self._start_upload, width=14)
        self.upload_btn.grid(row=row, column=0, columnspan=2, pady=4)

    # ------------------------------------------------------------------
    # Tab 3: instruct_url 批量更新
    # ------------------------------------------------------------------

    def _build_tab_instruct(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="instruct_url 更新")
        tab.columnconfigure(1, weight=1)

        row = 0

        # JSON 目录
        ttk.Label(tab, text="JSON 目录:").grid(row=row, column=0, sticky="w", pady=3)
        folder_frame = ttk.Frame(tab)
        folder_frame.grid(row=row, column=1, sticky="ew", pady=3)
        folder_frame.columnconfigure(0, weight=1)
        self.instruct_folder_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self.instruct_folder_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(folder_frame, text="浏览", command=self._browse_instruct_folder, width=6).grid(
            row=0, column=1, padx=(4, 0),
        )
        row += 1

        # 环境
        ttk.Label(tab, text="环境:").grid(row=row, column=0, sticky="w", pady=3)
        self.instruct_env_var = tk.StringVar(value="test")
        ttk.Combobox(
            tab, textvariable=self.instruct_env_var,
            values=["test", "prod"], state="readonly", width=10,
        ).grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # S3 前缀
        ttk.Label(tab, text="S3 前缀:").grid(row=row, column=0, sticky="w", pady=3)
        self.instruct_s3_prefix_var = tk.StringVar(value="xfan/instruct")
        ttk.Entry(tab, textvariable=self.instruct_s3_prefix_var).grid(
            row=row, column=1, sticky="ew", pady=3,
        )
        row += 1

        ttk.Separator(tab, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6,
        )
        row += 1

        # 按钮
        self.instruct_btn = ttk.Button(tab, text="开始更新", command=self._start_instruct, width=14)
        self.instruct_btn.grid(row=row, column=0, columnspan=2, pady=4)

    # ------------------------------------------------------------------
    # 共享日志区
    # ------------------------------------------------------------------

    def _build_log_area(self, parent: ttk.Frame) -> None:
        log_frame = ttk.LabelFrame(parent, text="运行日志", padding=(6, 4))
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        parent.rowconfigure(1, weight=1)

        # 清空按钮
        btn_frame = ttk.Frame(log_frame)
        btn_frame.grid(row=0, column=0, sticky="e", pady=(0, 2))
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log, width=10).pack(side="right")

        self.log_text = tk.Text(
            log_frame, height=10, wrap="word", state="disabled",
            bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9),
            selectbackground="#264f78",
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")

        sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)

        self.log_text.tag_configure("error",   foreground="#f44747")
        self.log_text.tag_configure("warning", foreground="#dcdcaa")
        self.log_text.tag_configure("print",   foreground="#9cdcfe")

        # 进度条
        self.progress = ttk.Progressbar(log_frame, mode="indeterminate")
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    # ==================================================================
    # Tab 1 — 数据列表事件
    # ==================================================================

    def _connect(self) -> None:
        env = self.list_env_var.get()
        self.conn_btn.configure(state="disabled")
        self.status_var.set("连接中…")
        threading.Thread(target=self._do_connect, args=(env,), daemon=True).start()

    def _do_connect(self, env: str) -> None:
        try:
            from daily_py.db import XfanVideoRepository, create_connection
            db = create_connection(env=env)
            repo = XfanVideoRepository(db)
            repo.count()
            self._task_queue.put(("connect_ok", db, repo))
        except BaseException as exc:
            logging.getLogger(__name__).exception("数据库连接失败")
            self._task_queue.put(("connect_err", str(exc)))

    def _disconnect(self) -> None:
        self._repo = None
        self._db = None
        self._set_connected(False)
        self._clear_tree()
        self._page = 1
        self._total = 0
        self._update_pagination()
        self.status_var.set("已断开")

    def _search(self) -> None:
        if not self._repo:
            return
        self._page = 1
        self._run_query()

    def _run_query(self) -> None:
        if not self._repo:
            return
        try:
            self._page_size = int(self.page_size_var.get())
        except ValueError:
            self._page_size = 50

        del_flag_str = self.del_flag_var.get()
        deleted_flag: Optional[int] = None
        if del_flag_str == "正常 (1)":
            deleted_flag = 1
        elif del_flag_str == "已删除 (-1)":
            deleted_flag = -1

        bg_str = self.bg_filter_var.get()
        background: Optional[int] = None
        if bg_str != "全部":
            background = int(bg_str.split(":")[0])

        keyword = self.keyword_var.get().strip()

        self.search_btn.configure(state="disabled")
        self.status_var.set("查询中…")
        threading.Thread(
            target=self._do_query,
            args=(self._page, self._page_size, deleted_flag, background, keyword),
            daemon=True,
        ).start()

    def _do_query(
        self, page: int, page_size: int,
        deleted_flag: Optional[int], background: Optional[int], keyword: str,
    ) -> None:
        try:
            items, total = self._repo.find_all_admin(
                page=page, page_size=page_size,
                deleted_flag=deleted_flag, background=background, keyword=keyword,
            )
            self._task_queue.put(("query_ok", items, total))
        except BaseException as exc:
            logging.getLogger(__name__).exception("查询失败")
            self._task_queue.put(("query_err", str(exc)))

    # ── 操作 ──

    def _get_selected_ids(self) -> List[int]:
        ids = []
        for iid in self.tree.selection():
            values = self.tree.item(iid, "values")
            ids.append(int(values[0]))
        return ids

    def _soft_delete(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            messagebox.showinfo("提示", "请先选择要操作的行。")
            return
        if not messagebox.askyesno("确认软删除", f"将选中的 {len(ids)} 条记录标记为已删除？"):
            return
        self._run_action("soft_delete", ids)

    def _restore(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            messagebox.showinfo("提示", "请先选择要操作的行。")
            return
        if not messagebox.askyesno("确认恢复", f"将选中的 {len(ids)} 条记录恢复？"):
            return
        self._run_action("restore", ids)

    def _hard_delete(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            messagebox.showinfo("提示", "请先选择要操作的行。")
            return
        if not messagebox.askyesno("确认物理删除", f"此操作不可恢复！\n确认彻底删除选中的 {len(ids)} 条记录？"):
            return
        self._run_action("hard_delete", ids)

    def _run_action(self, action: str, ids: List[int]) -> None:
        self._set_action_btns(False)
        label = {"soft_delete": "软删除", "restore": "恢复", "hard_delete": "物理删除"}.get(action, action)
        self.status_var.set(f"执行{label}中…")
        threading.Thread(target=self._do_action, args=(action, ids), daemon=True).start()

    def _do_action(self, action: str, ids: List[int]) -> None:
        try:
            affected = 0
            for vid in ids:
                if action == "soft_delete":
                    affected += self._repo.soft_delete(vid)
                elif action == "restore":
                    affected += self._repo.restore(vid)
                elif action == "hard_delete":
                    affected += self._repo.delete_by_id(vid)
            self._task_queue.put(("action_ok", action, affected))
        except BaseException as exc:
            logging.getLogger(__name__).exception("操作 %s 失败", action)
            self._task_queue.put(("action_err", str(exc)))

    # ── 分页 ──

    def _total_pages(self) -> int:
        return max(1, (self._total + self._page_size - 1) // self._page_size)

    def _go_first(self) -> None:
        self._page = 1; self._run_query()

    def _go_prev(self) -> None:
        if self._page > 1:
            self._page -= 1; self._run_query()

    def _go_next(self) -> None:
        if self._page < self._total_pages():
            self._page += 1; self._run_query()

    def _go_last(self) -> None:
        self._page = self._total_pages(); self._run_query()

    # ── 排序 ──

    def _sort_by(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True

        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        try:
            items.sort(key=lambda x: float(x[0]) if x[0] else 0, reverse=not self._sort_asc)
        except ValueError:
            items.sort(key=lambda x: x[0], reverse=not self._sort_asc)
        for idx, (_, k) in enumerate(items):
            self.tree.move(k, "", idx)

        arrow = " ▲" if self._sort_asc else " ▼"
        for cid, header in zip(_COL_IDS, _COL_HEADERS):
            self.tree.heading(cid, text=(header + arrow) if cid == col else header)

    # ── 右键复制 ──

    def _on_right_click(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        if row_id not in self.tree.selection():
            self.tree.selection_set(row_id)
        self._rclick_row = row_id
        try:
            self._rclick_col = int(self.tree.identify_column(event.x).lstrip("#")) - 1
        except ValueError:
            self._rclick_col = 0
        self._ctx_menu.tk_popup(event.x_root, event.y_root)

    def _copy_cell(self) -> None:
        row_id = getattr(self, "_rclick_row", None)
        col = getattr(self, "_rclick_col", 0)
        if not row_id:
            return
        values = self.tree.item(row_id, "values")
        self._to_clipboard(str(values[col]) if col < len(values) else "")

    def _copy_row(self) -> None:
        row_id = getattr(self, "_rclick_row", None)
        if not row_id:
            return
        values = self.tree.item(row_id, "values")
        self._to_clipboard("\t".join(str(v) for v in values))

    def _copy_selected_rows(self) -> None:
        lines = []
        for iid in self.tree.selection():
            values = self.tree.item(iid, "values")
            lines.append("\t".join(str(v) for v in values))
        if lines:
            self._to_clipboard("\n".join(lines))

    def _to_clipboard(self, text: str) -> None:
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
        self.status_var.set(f"已复制: {text[:60]}")

    # ── Treeview 更新 ──

    def _populate_tree(self, items) -> None:
        self._clear_tree()
        for item in items:
            d = item.to_dict()
            values = tuple(_fmt(d.get(c)) for c in _COL_IDS)
            tag = "deleted" if d.get("deleted_flag") == -1 else "normal"
            self.tree.insert("", "end", values=values, tags=(tag,))

    def _clear_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())

    def _update_pagination(self) -> None:
        total_pages = self._total_pages()
        self.page_label.configure(text=f"第 {self._page} / {total_pages} 页")
        self.total_label.configure(text=f"共 {self._total} 条")
        has_prev = self._page > 1
        has_next = self._page < total_pages
        self.first_btn.configure(state="normal" if has_prev else "disabled")
        self.prev_btn.configure(state="normal" if has_prev else "disabled")
        self.next_btn.configure(state="normal" if has_next else "disabled")
        self.last_btn.configure(state="normal" if has_next else "disabled")

    def _set_connected(self, connected: bool) -> None:
        self.conn_btn.configure(state="disabled" if connected else "normal")
        self.disconn_btn.configure(state="normal" if connected else "disabled")
        self.search_btn.configure(state="normal" if connected else "disabled")
        self._set_action_btns(connected)

    def _set_action_btns(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self.soft_del_btn, self.restore_btn, self.hard_del_btn):
            btn.configure(state=state)

    # ==================================================================
    # Tab 2 — 视频+封面批量上传
    # ==================================================================

    def _browse_upload_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择上传目录")
        if folder:
            self.upload_folder_var.set(folder)

    def _start_upload(self) -> None:
        if self._running:
            return
        folder = self.upload_folder_var.get().strip()
        if not folder:
            messagebox.showerror("参数错误", "请选择上传目录。")
            return
        try:
            cover_time = float(self.upload_cover_time_var.get())
        except ValueError:
            messagebox.showerror("参数错误", "封面截取时间格式有误。")
            return

        params = dict(
            root_dir=folder,
            env=self.upload_env_var.get(),
            dry_run=self.upload_dry_run_var.get(),
            video_prefix=self.upload_video_prefix_var.get().strip(),
            cover_prefix=self.upload_cover_prefix_var.get().strip(),
            instruct_prefix=self.upload_instruct_prefix_var.get().strip(),
            cover_time_sec=cover_time,
        )

        self._running = True
        self.upload_btn.configure(state="disabled", text="上传中…")
        self.progress.start(12)
        threading.Thread(target=self._run_upload, kwargs=params, daemon=True).start()

    def _run_upload(
        self, root_dir: str, env: str, dry_run: bool,
        video_prefix: str, cover_prefix: str, instruct_prefix: str,
        cover_time_sec: float,
    ) -> None:
        handler = self._attach_log_handler()
        old_stdout = sys.stdout
        sys.stdout = _StdoutToQueue(self._log_queue)  # type: ignore[assignment]

        try:
            from daily_py.services.xfan_video.video_cover_batch_upload import XfanVideoUploader

            uploader = XfanVideoUploader(
                env=env,
                video_prefix=video_prefix,
                cover_prefix=cover_prefix,
                instruct_prefix=instruct_prefix,
                cover_time_sec=cover_time_sec,
            )
            uploader.run(root_dir, dry_run=dry_run)
        except Exception as exc:
            self._log_queue.put(("log", logging.ERROR, f"[ERROR] {exc}"))
        finally:
            sys.stdout = old_stdout
            self._detach_log_handler(handler)
            self.master.after(0, self._upload_done)

    def _upload_done(self) -> None:
        self._running = False
        self.progress.stop()
        self.upload_btn.configure(state="normal", text="开始上传")

    # ==================================================================
    # Tab 3 — instruct_url 批量更新
    # ==================================================================

    def _browse_instruct_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择 JSON 目录")
        if folder:
            self.instruct_folder_var.set(folder)

    def _start_instruct(self) -> None:
        if self._running:
            return
        folder = self.instruct_folder_var.get().strip()
        if not folder:
            messagebox.showerror("参数错误", "请选择 JSON 目录。")
            return

        params = dict(
            json_dir=folder,
            env=self.instruct_env_var.get(),
            s3_prefix=self.instruct_s3_prefix_var.get().strip(),
        )

        self._running = True
        self.instruct_btn.configure(state="disabled", text="更新中…")
        self.progress.start(12)
        threading.Thread(target=self._run_instruct, kwargs=params, daemon=True).start()

    def _run_instruct(self, json_dir: str, env: str, s3_prefix: str) -> None:
        handler = self._attach_log_handler()
        old_stdout = sys.stdout
        sys.stdout = _StdoutToQueue(self._log_queue)  # type: ignore[assignment]

        try:
            from daily_py.services.xfan_video.instruct_url_batch_update import XfanVideoInstructUpdater

            updater = XfanVideoInstructUpdater(env=env, s3_prefix=s3_prefix)
            updater.run(json_dir)
        except Exception as exc:
            self._log_queue.put(("log", logging.ERROR, f"[ERROR] {exc}"))
        finally:
            sys.stdout = old_stdout
            self._detach_log_handler(handler)
            self.master.after(0, self._instruct_done)

    def _instruct_done(self) -> None:
        self._running = False
        self.progress.stop()
        self.instruct_btn.configure(state="normal", text="开始更新")

    # ==================================================================
    # 日志辅助
    # ==================================================================

    def _attach_log_handler(self) -> _QueueHandler:
        handler = _QueueHandler(self._log_queue)
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S"),
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)
        return handler

    def _detach_log_handler(self, handler: _QueueHandler) -> None:
        logging.getLogger().removeHandler(handler)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    # ==================================================================
    # 主线程轮询
    # ==================================================================

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

    def _poll_task(self) -> None:
        try:
            while True:
                msg = self._task_queue.get_nowait()
                try:
                    self._handle_task_msg(msg)
                except Exception:
                    logging.getLogger(__name__).exception("处理队列消息出错: %s", msg[0] if msg else "?")
                    self.status_var.set("内部错误")
        except queue.Empty:
            pass
        self.master.after(100, self._poll_task)

    def _handle_task_msg(self, msg: tuple) -> None:
        kind = msg[0]

        if kind == "connect_ok":
            _, db, repo = msg
            self._db = db
            self._repo = repo
            self._set_connected(True)
            self.status_var.set(f"已连接: {self.list_env_var.get()}")
            self._run_query()

        elif kind == "connect_err":
            self.conn_btn.configure(state="normal")
            self.status_var.set("连接失败")
            messagebox.showerror("连接失败", msg[1])

        elif kind == "query_ok":
            _, items, total = msg
            self._total = total
            self._populate_tree(items)
            self._update_pagination()
            self.search_btn.configure(state="normal")
            self.status_var.set(f"查询完成  当前页 {len(items)} 条 / 共 {total} 条")

        elif kind == "query_err":
            self.search_btn.configure(state="normal")
            self.status_var.set("查询失败")
            messagebox.showerror("查询失败", msg[1])

        elif kind == "action_ok":
            _, action, affected = msg
            label = {"soft_delete": "软删除", "restore": "恢复", "hard_delete": "物理删除"}.get(action, action)
            self.status_var.set(f"{label} 完成，受影响 {affected} 行")
            self._set_action_btns(True)
            self._run_query()

        elif kind == "action_err":
            self._set_action_btns(True)
            self.status_var.set("操作失败")
            messagebox.showerror("操作失败", msg[1])


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "xfan_video_gui.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    _setup_logging()
    root = tk.Tk()
    XfanVideoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
