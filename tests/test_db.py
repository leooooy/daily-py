"""单元测试 — db 模块（mock DB，不依赖真实数据库连接）。"""

import sys
import types
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# 在真实 mysql.connector 不存在时注入 stub，使 import 不报错
# ---------------------------------------------------------------------------
if "mysql" not in sys.modules:
    mysql_stub = types.ModuleType("mysql")
    connector_stub = types.ModuleType("mysql.connector")
    connector_stub.connect = MagicMock()  # type: ignore[attr-defined]
    mysql_stub.connector = connector_stub  # type: ignore[attr-defined]
    sys.modules["mysql"] = mysql_stub
    sys.modules["mysql.connector"] = connector_stub

from daily_py.db.base_repository import BaseRepository
from daily_py.db.config import ENVS, create_connection
from daily_py.db.connection import DBConnection
from daily_py.db.models.media_video import MediaVideo
from daily_py.db.repositories.media_video_repository import MediaVideoRepository


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_mock_db(*cursors: MagicMock) -> MagicMock:
    """构造一个模拟 DBConnection，依次返回给定的 cursor mock。

    每次调用 db.cursor() 作为上下文管理器时，yield 下一个 cursor。
    """
    it = iter(cursors)

    @contextmanager
    def _fake_cursor():
        yield next(it)

    mock_db = MagicMock(spec=DBConnection)
    mock_db.cursor.side_effect = _fake_cursor
    return mock_db


def _make_cursor(**kwargs: object) -> MagicMock:
    """构造一个带常用属性的 cursor mock。"""
    cur = MagicMock()
    for k, v in kwargs.items():
        setattr(cur, k, v)
    return cur


def _sample_row() -> dict:
    return {
        "id": 1,
        "media_name": "Test Video",
        "media_url": "http://example.com/v.mp4",
        "media_instruct_url": "",
        "media_cover_url": "",
        "media_cover_width": 1920,
        "media_cover_height": 1080,
        "duration": 120,
        "type": 1,
        "service_level_limits": 0,
        "xgame_supported": 0,
        "pinned": 0,
        "show_status": 1,
        "show_order": 1,
        "common": None,
        "deleted_flag": 1,
        "create_time": datetime(2024, 1, 1),
        "update_time": datetime(2024, 1, 2),
        "app_version_type": None,
        "click_count": 0,
    }


# ---------------------------------------------------------------------------
# BaseRepository 测试（使用 MediaVideoRepository 作为具体子类）
# ---------------------------------------------------------------------------

class TestBaseRepository(unittest.TestCase):
    def _repo(self, *cursors: MagicMock) -> MediaVideoRepository:
        return MediaVideoRepository(_make_mock_db(*cursors))

    # ---- find_by_id -------------------------------------------------------

    def test_find_by_id_found(self):
        row = _sample_row()
        cur = _make_cursor()
        cur.fetchone.return_value = row
        result = self._repo(cur).find_by_id(1)

        cur.execute.assert_called_once_with(
            "SELECT * FROM media_video WHERE id = %s", (1,)
        )
        self.assertIsInstance(result, MediaVideo)
        self.assertEqual(result.id, 1)
        self.assertEqual(result.media_name, "Test Video")

    def test_find_by_id_not_found(self):
        cur = _make_cursor()
        cur.fetchone.return_value = None
        result = self._repo(cur).find_by_id(999)
        self.assertIsNone(result)

    # ---- find_all ---------------------------------------------------------

    def test_find_all_no_conditions(self):
        row = _sample_row()
        cur = _make_cursor()
        cur.fetchall.return_value = [row]
        results = self._repo(cur).find_all()

        cur.execute.assert_called_once_with("SELECT * FROM media_video", ())
        self.assertEqual(len(results), 1)

    def test_find_all_with_where_order_limit_offset(self):
        cur = _make_cursor()
        cur.fetchall.return_value = []
        self._repo(cur).find_all(
            where="type = %s",
            params=(2,),
            order_by="show_order ASC",
            limit=10,
            offset=0,
        )
        expected_sql = (
            "SELECT * FROM media_video"
            " WHERE type = %s"
            " ORDER BY show_order ASC"
            " LIMIT 10"
            " OFFSET 0"
        )
        cur.execute.assert_called_once_with(expected_sql, (2,))

    # ---- find_by_fields ---------------------------------------------------

    def test_find_by_fields(self):
        cur = _make_cursor()
        cur.fetchall.return_value = []
        self._repo(cur).find_by_fields(type=1, show_status=1)

        sql_called, params_called = cur.execute.call_args[0]
        self.assertIn("type = %s", sql_called)
        self.assertIn("show_status = %s", sql_called)
        self.assertIn("WHERE", sql_called)
        self.assertEqual(set(params_called), {1})

    # ---- count ------------------------------------------------------------

    def test_count_no_where(self):
        cur = _make_cursor()
        cur.fetchone.return_value = {"cnt": 42}
        result = self._repo(cur).count()

        cur.execute.assert_called_once_with(
            "SELECT COUNT(*) AS cnt FROM media_video", ()
        )
        self.assertEqual(result, 42)

    def test_count_with_where(self):
        cur = _make_cursor()
        cur.fetchone.return_value = {"cnt": 5}
        result = self._repo(cur).count(where="deleted_flag = %s", params=(1,))
        self.assertEqual(result, 5)

    # ---- find_page --------------------------------------------------------

    def test_find_page(self):
        count_cur = _make_cursor()
        count_cur.fetchone.return_value = {"cnt": 3}
        list_cur = _make_cursor()
        row = _sample_row()
        list_cur.fetchall.return_value = [row, row, row]

        items, total = self._repo(count_cur, list_cur).find_page(
            page=1, page_size=10, where="deleted_flag = %s", params=(1,)
        )
        self.assertEqual(total, 3)
        self.assertEqual(len(items), 3)

    def test_find_page_second_page(self):
        count_cur = _make_cursor()
        count_cur.fetchone.return_value = {"cnt": 25}
        list_cur = _make_cursor()
        list_cur.fetchall.return_value = [_sample_row()] * 5

        items, total = self._repo(count_cur, list_cur).find_page(page=3, page_size=5)

        self.assertEqual(total, 25)
        # 验证 OFFSET = (3-1)*5 = 10
        list_sql, list_params = list_cur.execute.call_args[0]
        self.assertIn("OFFSET 10", list_sql)
        self.assertIn("LIMIT 5", list_sql)

    # ---- insert -----------------------------------------------------------

    def test_insert_returns_lastrowid(self):
        cur = _make_cursor()
        cur.lastrowid = 99
        video = MediaVideo(
            media_name="My Video",
            media_url="http://example.com/x.mp4",
            type=1,
            show_status=1,
            show_order=1,
        )
        pk = self._repo(cur).insert(video)

        self.assertEqual(pk, 99)
        sql_called, values_called = cur.execute.call_args[0]
        # 提取括号内的列名列表，验证 id / create_time / update_time 不在其中
        import re as _re
        cols_str = _re.search(r"INSERT INTO \w+ \(([^)]+)\)", sql_called).group(1)
        col_list = [c.strip() for c in cols_str.split(",")]
        self.assertNotIn("id", col_list)
        self.assertNotIn("create_time", col_list)
        self.assertNotIn("update_time", col_list)
        self.assertIn("INSERT INTO media_video", sql_called)
        self.assertIn("media_name", sql_called)
        self.assertIn("My Video", values_called)

    # ---- update -----------------------------------------------------------

    def test_update_returns_rowcount(self):
        cur = _make_cursor()
        cur.rowcount = 1
        video = MediaVideo(id=5, media_name="Updated", type=2)
        result = self._repo(cur).update(video)

        self.assertEqual(result, 1)
        sql_called, values_called = cur.execute.call_args[0]
        self.assertIn("UPDATE media_video SET", sql_called)
        self.assertIn("WHERE id = %s", sql_called)
        # id 应出现在最后一个参数（WHERE 条件）
        self.assertEqual(values_called[-1], 5)
        # auto_fields 不应在 SET 子句
        self.assertNotIn("create_time", sql_called)
        self.assertNotIn("update_time", sql_called)

    # ---- update_fields ----------------------------------------------------

    def test_update_fields(self):
        cur = _make_cursor()
        cur.rowcount = 1
        result = self._repo(cur).update_fields(7, show_status=0, pinned=1)

        self.assertEqual(result, 1)
        sql_called, values_called = cur.execute.call_args[0]
        self.assertIn("UPDATE media_video SET", sql_called)
        self.assertIn("show_status = %s", sql_called)
        self.assertIn("pinned = %s", sql_called)
        self.assertIn("WHERE id = %s", sql_called)
        self.assertEqual(values_called[-1], 7)

    def test_update_fields_empty_kwargs_returns_zero(self):
        cur = _make_cursor()
        result = self._repo(cur).update_fields(1)
        self.assertEqual(result, 0)
        cur.execute.assert_not_called()

    # ---- delete_by_id -----------------------------------------------------

    def test_delete_by_id(self):
        cur = _make_cursor()
        cur.rowcount = 1
        result = self._repo(cur).delete_by_id(3)

        self.assertEqual(result, 1)
        cur.execute.assert_called_once_with(
            "DELETE FROM media_video WHERE id = %s", (3,)
        )


# ---------------------------------------------------------------------------
# MediaVideoRepository 业务方法测试
# ---------------------------------------------------------------------------

class TestMediaVideoRepository(unittest.TestCase):
    def _repo(self, *cursors: MagicMock) -> MediaVideoRepository:
        return MediaVideoRepository(_make_mock_db(*cursors))

    # ---- soft_delete / restore --------------------------------------------

    def test_soft_delete(self):
        cur = _make_cursor()
        cur.rowcount = 1
        result = self._repo(cur).soft_delete(10)

        self.assertEqual(result, 1)
        sql_called, values_called = cur.execute.call_args[0]
        self.assertIn("deleted_flag = %s", sql_called)
        self.assertIn(-1, values_called)
        self.assertEqual(values_called[-1], 10)

    def test_restore(self):
        cur = _make_cursor()
        cur.rowcount = 1
        result = self._repo(cur).restore(10)

        self.assertEqual(result, 1)
        sql_called, values_called = cur.execute.call_args[0]
        self.assertIn("deleted_flag = %s", sql_called)
        self.assertIn(1, values_called)

    # ---- find_visible -----------------------------------------------------

    def test_find_visible(self):
        count_cur = _make_cursor()
        count_cur.fetchone.return_value = {"cnt": 1}
        list_cur = _make_cursor()
        list_cur.fetchall.return_value = [_sample_row()]

        items, total = self._repo(count_cur, list_cur).find_visible(page=1, page_size=10)

        self.assertEqual(total, 1)
        self.assertEqual(len(items), 1)
        # 验证查询条件包含 deleted_flag 和 show_status
        list_sql, list_params = list_cur.execute.call_args[0]
        self.assertIn("deleted_flag", list_sql)
        self.assertIn("show_status", list_sql)
        self.assertIn("show_order", list_sql)

    # ---- find_pinned ------------------------------------------------------

    def test_find_pinned(self):
        cur = _make_cursor()
        row = _sample_row()
        row["pinned"] = 1
        cur.fetchall.return_value = [row]

        results = self._repo(cur).find_pinned()

        self.assertEqual(len(results), 1)
        sql_called, params_called = cur.execute.call_args[0]
        self.assertIn("pinned = %s", sql_called)
        self.assertIn("deleted_flag = %s", sql_called)
        self.assertIn(1, params_called)

    # ---- find_by_type -----------------------------------------------------

    def test_find_by_type(self):
        count_cur = _make_cursor()
        count_cur.fetchone.return_value = {"cnt": 2}
        list_cur = _make_cursor()
        list_cur.fetchall.return_value = [_sample_row(), _sample_row()]

        items, total = self._repo(count_cur, list_cur).find_by_type(
            video_type=3, page=1, page_size=5
        )

        self.assertEqual(total, 2)
        list_sql, list_params = list_cur.execute.call_args[0]
        self.assertIn("type = %s", list_sql)
        self.assertIn("deleted_flag = %s", list_sql)
        self.assertIn(3, list_params)

    # ---- increment_click --------------------------------------------------

    def test_increment_click(self):
        cur = _make_cursor()
        cur.rowcount = 1
        result = self._repo(cur).increment_click(42)

        self.assertEqual(result, 1)
        sql_called, params_called = cur.execute.call_args[0]
        self.assertIn("click_count = click_count + 1", sql_called)
        self.assertEqual(params_called, (42,))


# ---------------------------------------------------------------------------
# MediaVideo 模型测试
# ---------------------------------------------------------------------------

class TestMediaVideoModel(unittest.TestCase):
    def test_from_row_full(self):
        row = _sample_row()
        video = MediaVideo.from_row(row)
        self.assertEqual(video.id, 1)
        self.assertEqual(video.media_name, "Test Video")
        self.assertIsNone(video.common)

    def test_from_row_ignores_unknown_columns(self):
        row = _sample_row()
        row["unknown_col"] = "should_be_ignored"
        video = MediaVideo.from_row(row)  # 不应抛出异常
        self.assertFalse(hasattr(video, "unknown_col"))

    def test_to_dict_round_trip(self):
        video = MediaVideo(id=5, media_name="Round Trip", type=2, click_count=10)
        d = video.to_dict()
        restored = MediaVideo.from_row(d)
        self.assertEqual(restored.id, 5)
        self.assertEqual(restored.media_name, "Round Trip")
        self.assertEqual(restored.click_count, 10)

    def test_default_values(self):
        video = MediaVideo()
        self.assertEqual(video.id, 0)
        self.assertEqual(video.deleted_flag, 1)
        self.assertIsNone(video.create_time)
        self.assertIsNone(video.common)


# ---------------------------------------------------------------------------
# DBConnection — time_zone / ssl_disabled / env_info 测试
# ---------------------------------------------------------------------------

class TestDBConnection(unittest.TestCase):
    def _make_mock_conn(self):
        """返回 (mock_conn, mock_cursor) 供 mysql.connector.connect 使用。"""
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        return mock_conn, mock_cur

    def test_time_zone_set_on_cursor(self):
        mock_conn, mock_cur = self._make_mock_conn()
        import mysql.connector as _mc
        _mc.connect = MagicMock(return_value=mock_conn)

        db = DBConnection(host="127.0.0.1", database="toy", time_zone="Asia/Shanghai")
        with db.cursor() as _:
            pass

        # 第一次 execute 调用必须是 SET time_zone
        first_call = mock_cur.execute.call_args_list[0]
        sql, params = first_call[0]
        self.assertIn("SET time_zone", sql)
        self.assertEqual(params, ("Asia/Shanghai",))

    def test_no_time_zone_skips_set(self):
        mock_conn, mock_cur = self._make_mock_conn()
        import mysql.connector as _mc
        _mc.connect = MagicMock(return_value=mock_conn)

        db = DBConnection(host="127.0.0.1", database="toy")
        with db.cursor() as _:
            pass

        # 没有 SET time_zone 调用
        for c in mock_cur.execute.call_args_list:
            sql = c[0][0] if c[0] else ""
            self.assertNotIn("SET time_zone", sql)

    def test_ssl_disabled_passed_to_connect(self):
        import mysql.connector as _mc
        _mc.connect = MagicMock(return_value=MagicMock())
        _mc.connect.return_value.cursor.return_value = MagicMock()

        DBConnection(host="rds.example.com", ssl_disabled=True, database="toy")
        # ssl_disabled 应被记录在内部 config 中
        db = DBConnection(host="rds.example.com", ssl_disabled=True, database="toy")
        self.assertTrue(db._config["ssl_disabled"])

    def test_env_info_no_ssl(self):
        db = DBConnection(host="rds.example.com", port=3306, database="toy",
                          ssl_disabled=True, time_zone="UTC")
        info = db.env_info
        self.assertIn("rds.example.com", info)
        self.assertIn("no-ssl", info)
        self.assertIn("UTC", info)

    def test_env_info_with_ssl(self):
        db = DBConnection(host="192.168.0.200", port=3306, database="toy",
                          ssl_disabled=False, time_zone="+08:00")
        info = db.env_info
        self.assertNotIn("no-ssl", info)
        self.assertIn("ssl", info)
        self.assertIn("+08:00", info)


# ---------------------------------------------------------------------------
# create_connection / config 测试
# ---------------------------------------------------------------------------

class TestCreateConnection(unittest.TestCase):
    def test_envs_list(self):
        self.assertIn("prod", ENVS)
        self.assertIn("test", ENVS)

    def test_create_test_env_preset_credentials(self):
        """test 环境无显式凭证时，使用预设 root/root。"""
        db = create_connection("test")
        self.assertIsInstance(db, DBConnection)
        self.assertEqual(db._config["host"], "192.168.0.200")
        self.assertFalse(db._config["ssl_disabled"])
        self.assertEqual(db._time_zone, "+08:00")
        self.assertEqual(db._config["user"], "root")
        self.assertEqual(db._config["password"], "root")
        self.assertEqual(db._config["database"], "toy")

    def test_create_test_env_explicit_credentials(self):
        """显式传参时覆盖预设凭证。"""
        db = create_connection("test", user="dev", password="dev123")
        self.assertEqual(db._config["user"], "dev")
        self.assertEqual(db._config["password"], "dev123")

    def test_create_prod_env_preset_credentials(self):
        """prod 环境无显式凭证时，使用预设 metaxsire。"""
        db = create_connection("prod")
        self.assertIsInstance(db, DBConnection)
        self.assertIn("rds.amazonaws.com", db._config["host"])
        self.assertTrue(db._config["ssl_disabled"])
        self.assertEqual(db._time_zone, "UTC")
        self.assertEqual(db._config["user"], "metaxsire")
        self.assertEqual(db._config["database"], "toy")

    def test_create_prod_env_explicit_credentials(self):
        """显式传参时覆盖 prod 预设凭证。"""
        db = create_connection("prod", user="admin", password="s3cr3t")
        self.assertEqual(db._config["user"], "admin")

    def test_unknown_env_raises(self):
        with self.assertRaises(ValueError) as ctx:
            create_connection("staging", user="u", password="p")
        self.assertIn("staging", str(ctx.exception))

    def test_default_env_is_test(self):
        import os
        os.environ.pop("DAILYPY_DB_ENV", None)
        db = create_connection()
        self.assertEqual(db._config["host"], "192.168.0.200")

    def test_env_var_overrides_default(self):
        import os
        os.environ["DAILYPY_DB_ENV"] = "prod"
        try:
            db = create_connection(user="u", password="p")
            self.assertIn("rds.amazonaws.com", db._config["host"])
        finally:
            os.environ.pop("DAILYPY_DB_ENV", None)

    def test_user_from_env_var(self):
        import os
        os.environ["DAILYPY_DB_USER"] = "envuser"
        os.environ["DAILYPY_DB_PASSWORD"] = "envpass"
        try:
            db = create_connection("test")
            self.assertEqual(db._config["user"], "envuser")
            self.assertEqual(db._config["password"], "envpass")
        finally:
            os.environ.pop("DAILYPY_DB_USER", None)
            os.environ.pop("DAILYPY_DB_PASSWORD", None)

    def test_kwargs_override_preset(self):
        db = create_connection("test", user="u", password="p", database="other_db")
        self.assertEqual(db._config["database"], "other_db")

    def test_param_user_beats_env_var(self):
        import os
        os.environ["DAILYPY_DB_USER"] = "envuser"
        try:
            db = create_connection("test", user="explicit_user", password="p")
            self.assertEqual(db._config["user"], "explicit_user")
        finally:
            os.environ.pop("DAILYPY_DB_USER", None)


if __name__ == "__main__":
    unittest.main()
