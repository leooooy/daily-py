"""数据库连接管理器 — 每次操作创建新连接，支持自动 commit/rollback/close。"""

from contextlib import contextmanager
from typing import Any, Dict, Generator

try:
    import mysql.connector
except ImportError as _e:
    raise ImportError(
        "mysql-connector-python 未安装，请执行：pip install mysql-connector-python"
    ) from _e


class DBConnection:
    """轻量级 MySQL 连接管理器。

    每次调用 cursor() 都会新建一条连接；执行完毕后自动 commit；
    发生异常时自动 rollback；最终关闭连接。

    Example::

        db = DBConnection(host="127.0.0.1", user="root", password="secret", database="mydb")
        with db.cursor() as cur:
            cur.execute("SELECT 1")
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "",
        charset: str = "utf8mb4",
        ssl_disabled: bool = False,
        time_zone: str = "",
        **kwargs: Any,
    ) -> None:
        # time_zone 通过 SET 语句设置（兼容所有 mysql-connector 版本）
        self._time_zone: str = time_zone
        self._config: Dict[str, Any] = dict(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset=charset,
            ssl_disabled=ssl_disabled,
            **kwargs,
        )

    @property
    def env_info(self) -> str:
        """返回可读的连接标识（不含密码）。"""
        c = self._config
        ssl_tag = "no-ssl" if c.get("ssl_disabled") else "ssl"
        tz = f"/{self._time_zone}" if self._time_zone else ""
        return f"{c['host']}:{c['port']}/{c['database']}[{ssl_tag}{tz}]"

    @contextmanager
    def cursor(self) -> Generator:
        """上下文管理器：yield 一个 dict-cursor，自动管理事务和连接生命周期。"""
        conn = mysql.connector.connect(**self._config)
        cur = None
        try:
            cur = conn.cursor(dictionary=True)
            if self._time_zone:
                cur.execute("SET time_zone = %s", (self._time_zone,))
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if cur is not None:
                cur.close()
            conn.close()
