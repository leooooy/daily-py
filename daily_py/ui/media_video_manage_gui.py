#!/usr/bin/env python3
"""媒体视频管理 GUI — 查询列表、软删除、恢复、物理删除。

运行方式::

    python -m daily_py.ui.media_video_manage_gui
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk

# 确保无论从哪里启动，项目根目录都在 sys.path 上
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from tkinter import messagebox, ttk
from typing import List, Optional

from daily_py.db import MediaVideoRepository, create_connection

# ---------------------------------------------------------------------------
# 表格列定义
# ---------------------------------------------------------------------------

_COLS = [
    ("id",                   "ID",         55,  "center"),
    ("media_name",           "名称",       210,  "w"),
    ("type",                 "类型",        80,  "center"),
    ("show_status",          "显示",        50,  "center"),
    ("deleted_flag",         "删除标志",    70,  "center"),
    ("pinned",               "置顶",        50,  "center"),
    ("show_order",           "排序",        50,  "center"),
    ("duration",             "时长(s)",     60,  "center"),
    ("click_count",          "点击数",      60,  "center"),
    ("service_level_limits", "等级限制",    70,  "center"),
    ("common",               "common",      60,  "center"),
    ("media_cover_width",    "封面宽",      60,  "center"),
    ("media_cover_height",   "封面高",      60,  "center"),
    ("media_url",            "视频URL",    220,  "w"),
    ("media_instruct_url",   "指令URL",    220,  "w"),
    ("media_cover_url",      "封面URL",    220,  "w"),
    ("create_time",          "创建时间",   145,  "center"),
]
_COL_IDS     = [c[0] for c in _COLS]
_COL_HEADERS = [c[1] for c in _COLS]
_COL_WIDTHS  = [c[2] for c in _COLS]
_COL_ANCHORS = [c[3] for c in _COLS]

_TYPE_LABELS = {0: "普通视频", 1: "VR视频"}


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class MediaVideoManageApp:
    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("DailyPy - 媒体视频管理")
        master.minsize(960, 620)
        master.geometry("1100x700")
        master.resizable(True, True)

        self._repo = None          # MediaVideoRepository，连接后赋值
        self._db = None            # DBConnection
        self._task_queue: queue.Queue = queue.Queue()
        self._page = 1
        self._page_size = 50
        self._total = 0
        self._sort_col: Optional[str] = None
        self._sort_asc = True

        self._build_ui()
        self._poll_queue()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = self.master
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        main = ttk.Frame(root, padding=8)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)   # Treeview 行自动伸展

        # ── 连接面板 ──────────────────────────────────────────────────
        conn_lf = ttk.LabelFrame(main, text="数据库连接", padding=(8, 4))
        conn_lf.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(conn_lf, text="环境:").grid(row=0, column=0, padx=(0, 4))
        self.env_var = tk.StringVar(value="test")
        ttk.Combobox(
            conn_lf, textvariable=self.env_var,
            values=["test", "prod"], state="readonly", width=6,
        ).grid(row=0, column=1, padx=(0, 18))

        self.conn_btn = ttk.Button(
            conn_lf, text="连接", width=8, command=self._connect)
        self.conn_btn.grid(row=0, column=2, padx=(0, 6))

        self.disconn_btn = ttk.Button(
            conn_lf, text="断开", width=8,
            command=self._disconnect, state="disabled")
        self.disconn_btn.grid(row=0, column=3)

        # ── 筛选面板 ──────────────────────────────────────────────────
        filter_lf = ttk.LabelFrame(main, text="筛选条件", padding=(8, 4))
        filter_lf.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(filter_lf, text="删除状态:").grid(row=0, column=0, padx=(0, 4))
        self.del_flag_var = tk.StringVar(value="全部")
        ttk.Combobox(
            filter_lf, textvariable=self.del_flag_var,
            values=["全部", "正常 (1)", "已删除 (-1)"],
            state="readonly", width=11,
        ).grid(row=0, column=1, padx=(0, 14))

        ttk.Label(filter_lf, text="类型:").grid(row=0, column=2, padx=(0, 4))
        self.type_var = tk.StringVar(value="全部")
        ttk.Combobox(
            filter_lf, textvariable=self.type_var,
            values=["全部", "0: 普通视频", "1: VR视频"],
            state="readonly", width=11,
        ).grid(row=0, column=3, padx=(0, 14))

        ttk.Label(filter_lf, text="名称关键词:").grid(row=0, column=4, padx=(0, 4))
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
            filter_lf, text="查询", width=8,
            command=self._search, state="disabled")
        self.search_btn.grid(row=0, column=8)

        # ── Treeview ──────────────────────────────────────────────────
        tree_frame = ttk.Frame(main)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            tree_frame, columns=_COL_IDS,
            show="headings", selectmode="extended",
        )
        for cid, header, width, anchor in zip(
            _COL_IDS, _COL_HEADERS, _COL_WIDTHS, _COL_ANCHORS
        ):
            self.tree.heading(
                cid, text=header,
                command=lambda c=cid: self._sort_by(c),
            )
            self.tree.column(cid, width=width, minwidth=36, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # 行颜色：已删除行显示为灰色
        self.tree.tag_configure("deleted", foreground="#999999")
        self.tree.tag_configure("normal",  foreground="#000000")

        # 右键菜单 + Ctrl+C 复制
        self._ctx_menu = tk.Menu(self.master, tearoff=0)
        self._ctx_menu.add_command(label="复制单元格", command=self._copy_cell)
        self._ctx_menu.add_command(label="复制整行",   command=self._copy_row)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="复制所选行", command=self._copy_selected_rows)
        self.tree.bind("<Button-3>",  self._on_right_click)
        self.tree.bind("<Control-c>", lambda *_: self._copy_selected_rows())

        # ── 操作按钮 + 分页 ───────────────────────────────────────────
        action_frame = ttk.Frame(main)
        action_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        action_frame.columnconfigure(4, weight=1)   # 弹性间隔

        ttk.Button(
            action_frame, text="打开上传", width=10,
            command=self._open_upload,
        ).grid(row=0, column=0, padx=(0, 14))

        self.soft_del_btn = ttk.Button(
            action_frame, text="软删除", width=9,
            command=self._soft_delete, state="disabled")
        self.soft_del_btn.grid(row=0, column=1, padx=(0, 6))

        self.restore_btn = ttk.Button(
            action_frame, text="恢复", width=9,
            command=self._restore, state="disabled")
        self.restore_btn.grid(row=0, column=2, padx=(0, 6))

        self.hard_del_btn = ttk.Button(
            action_frame, text="物理删除", width=10,
            command=self._hard_delete, state="disabled")
        self.hard_del_btn.grid(row=0, column=3, padx=(0, 0))

        # 分页控件（右侧）
        page_nav = ttk.Frame(action_frame)
        page_nav.grid(row=0, column=5)

        self.first_btn = ttk.Button(
            page_nav, text="<<", width=3,
            command=self._go_first, state="disabled")
        self.first_btn.pack(side="left", padx=2)

        self.prev_btn = ttk.Button(
            page_nav, text="<", width=3,
            command=self._go_prev, state="disabled")
        self.prev_btn.pack(side="left", padx=2)

        self.page_label = ttk.Label(page_nav, text="第 - / - 页", width=12, anchor="center")
        self.page_label.pack(side="left", padx=6)

        self.next_btn = ttk.Button(
            page_nav, text=">", width=3,
            command=self._go_next, state="disabled")
        self.next_btn.pack(side="left", padx=2)

        self.last_btn = ttk.Button(
            page_nav, text=">>", width=3,
            command=self._go_last, state="disabled")
        self.last_btn.pack(side="left", padx=2)

        self.total_label = ttk.Label(page_nav, text="共 0 条", width=10)
        self.total_label.pack(side="left", padx=(10, 0))

        # ── 状态栏 ────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(
            main, textvariable=self.status_var,
            relief="sunken", anchor="w", padding=(4, 2),
        ).grid(row=4, column=0, sticky="ew", pady=(4, 0))

    # ------------------------------------------------------------------
    # 连接 / 断开
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        env = self.env_var.get()
        self.conn_btn.configure(state="disabled")
        self.status_var.set("连接中…")
        threading.Thread(
            target=self._do_connect, args=(env,), daemon=True
        ).start()

    def _do_connect(self, env: str) -> None:
        try:
            db   = create_connection(env=env)
            repo = MediaVideoRepository(db)
            repo.count()   # 测试连通性
            self._task_queue.put(("connect_ok", db, repo))
        except Exception as exc:
            self._task_queue.put(("connect_err", str(exc)))

    def _open_upload(self) -> None:
        from daily_py.ui.media_upload_gui import MediaUploadApp
        win = tk.Toplevel(self.master)
        MediaUploadApp(win, initial_env=self.env_var.get())

    # ------------------------------------------------------------------
    # 右键复制
    # ------------------------------------------------------------------

    def _on_right_click(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)   # "#1", "#2", ...
        if not row_id:
            return
        # 让点击行变为选中（不清除多选）
        if row_id not in self.tree.selection():
            self.tree.selection_set(row_id)
        # 记录右键目标，供菜单命令使用
        self._rclick_row = row_id
        try:
            self._rclick_col = int(col_id.lstrip("#")) - 1   # 0-based
        except ValueError:
            self._rclick_col = 0
        self._ctx_menu.tk_popup(event.x_root, event.y_root)

    def _copy_cell(self) -> None:
        row_id = getattr(self, "_rclick_row", None)
        col    = getattr(self, "_rclick_col", 0)
        if not row_id:
            return
        values = self.tree.item(row_id, "values")
        text = str(values[col]) if col < len(values) else ""
        self._to_clipboard(text)

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
        self.status_var.set(f"已复制: {text}")

    def _disconnect(self) -> None:
        self._repo = None
        self._db   = None
        self._set_connected(False)
        self._clear_tree()
        self._page = 1
        self._total = 0
        self._update_pagination()
        self.status_var.set("已断开")

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

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

        type_sel = self.type_var.get()
        video_type: Optional[int] = None
        if type_sel != "全部":
            video_type = int(type_sel.split(":")[0])

        keyword = self.keyword_var.get().strip()

        self.search_btn.configure(state="disabled")
        self.status_var.set("查询中…")
        threading.Thread(
            target=self._do_query,
            args=(self._page, self._page_size, deleted_flag, video_type, keyword),
            daemon=True,
        ).start()

    def _do_query(
        self,
        page: int,
        page_size: int,
        deleted_flag: Optional[int],
        video_type: Optional[int],
        keyword: str,
    ) -> None:
        try:
            items, total = self._repo.find_all_admin(
                page=page,
                page_size=page_size,
                deleted_flag=deleted_flag,
                video_type=video_type,
                name_keyword=keyword,
            )
            self._task_queue.put(("query_ok", items, total))
        except Exception as exc:
            self._task_queue.put(("query_err", str(exc)))

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------

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
        if not messagebox.askyesno(
            "确认软删除",
            f"将选中的 {len(ids)} 条记录标记为已删除（deleted_flag → -1）？",
        ):
            return
        self._run_action("soft_delete", ids)

    def _restore(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            messagebox.showinfo("提示", "请先选择要操作的行。")
            return
        if not messagebox.askyesno(
            "确认恢复",
            f"将选中的 {len(ids)} 条记录恢复（deleted_flag → 1）？",
        ):
            return
        self._run_action("restore", ids)

    def _hard_delete(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            messagebox.showinfo("提示", "请先选择要操作的行。")
            return
        if not messagebox.askyesno(
            "⚠ 确认物理删除",
            f"此操作不可恢复！\n确认彻底删除选中的 {len(ids)} 条记录？",
        ):
            return
        self._run_action("hard_delete", ids)

    def _run_action(self, action: str, ids: List[int]) -> None:
        self._set_action_btns(False)
        label = {"soft_delete": "软删除", "restore": "恢复",
                 "hard_delete": "物理删除"}.get(action, action)
        self.status_var.set(f"执行{label}中…")
        threading.Thread(
            target=self._do_action, args=(action, ids), daemon=True
        ).start()

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
        except Exception as exc:
            self._task_queue.put(("action_err", str(exc)))

    # ------------------------------------------------------------------
    # 分页导航
    # ------------------------------------------------------------------

    def _total_pages(self) -> int:
        return max(1, (self._total + self._page_size - 1) // self._page_size)

    def _go_first(self) -> None:
        self._page = 1
        self._run_query()

    def _go_prev(self) -> None:
        if self._page > 1:
            self._page -= 1
            self._run_query()

    def _go_next(self) -> None:
        if self._page < self._total_pages():
            self._page += 1
            self._run_query()

    def _go_last(self) -> None:
        self._page = self._total_pages()
        self._run_query()

    # ------------------------------------------------------------------
    # 列头点击排序（对当前页数据本地排序）
    # ------------------------------------------------------------------

    def _sort_by(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True

        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        try:
            items.sort(key=lambda x: float(x[0]) if x[0] else 0,
                       reverse=not self._sort_asc)
        except ValueError:
            items.sort(key=lambda x: x[0], reverse=not self._sort_asc)
        for idx, (_, k) in enumerate(items):
            self.tree.move(k, "", idx)

        arrow = " ▲" if self._sort_asc else " ▼"
        for cid, header in zip(_COL_IDS, _COL_HEADERS):
            self.tree.heading(cid, text=(header + arrow) if cid == col else header)

    # ------------------------------------------------------------------
    # Treeview 刷新
    # ------------------------------------------------------------------

    def _populate_tree(self, items) -> None:
        self._clear_tree()
        for item in items:
            d = item.to_dict()
            values = tuple(
                _TYPE_LABELS.get(d[c], _fmt(d.get(c))) if c == "type" else _fmt(d.get(c))
                for c in _COL_IDS
            )
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

    # ------------------------------------------------------------------
    # 连接态按钮管理
    # ------------------------------------------------------------------

    def _set_connected(self, connected: bool) -> None:
        self.conn_btn.configure(state="disabled" if connected else "normal")
        self.disconn_btn.configure(state="normal" if connected else "disabled")
        self.search_btn.configure(state="normal" if connected else "disabled")
        self._set_action_btns(connected)

    def _set_action_btns(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self.soft_del_btn, self.restore_btn, self.hard_del_btn):
            btn.configure(state=state)

    # ------------------------------------------------------------------
    # 主线程轮询任务队列
    # ------------------------------------------------------------------

    def _poll_queue(self) -> None:
        try:
            while True:
                self._handle_msg(self._task_queue.get_nowait())
        except queue.Empty:
            pass
        self.master.after(100, self._poll_queue)

    def _handle_msg(self, msg: tuple) -> None:
        kind = msg[0]

        if kind == "connect_ok":
            _, db, repo = msg
            self._db   = db
            self._repo = repo
            self._set_connected(True)
            env_info = getattr(db, "env_info", "已连接")
            self.status_var.set(f"已连接: {env_info}")
            self._run_query()   # 连接后自动加载第一页

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
            self.status_var.set(
                f"查询完成  当前页 {len(items)} 条 / 共 {total} 条"
            )

        elif kind == "query_err":
            self.search_btn.configure(state="normal")
            self.status_var.set("查询失败")
            messagebox.showerror("查询失败", msg[1])

        elif kind == "action_ok":
            _, action, affected = msg
            label = {"soft_delete": "软删除", "restore": "恢复",
                     "hard_delete": "物理删除"}.get(action, action)
            self.status_var.set(f"{label} 完成，受影响 {affected} 行")
            self._set_action_btns(True)
            self._run_query()   # 操作后刷新列表

        elif kind == "action_err":
            self._set_action_btns(True)
            self.status_var.set("操作失败")
            messagebox.showerror("操作失败", msg[1])


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _fmt(val) -> str:
    if val is None:
        return ""
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    MediaVideoManageApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
