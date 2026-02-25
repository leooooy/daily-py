"""通用泛型 CRUD 基类。

子类只需声明四个类变量即可获得完整的增删改查能力：

    class UserRepository(BaseRepository["User"]):
        table_name = "user"
        primary_key = "id"
        model_class = User
        auto_fields = ("create_time", "update_time")
"""

from typing import Any, Generic, List, Optional, Tuple, Type, TypeVar

from .connection import DBConnection

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """通用 CRUD 基类。

    子类需声明以下类变量：

    Attributes:
        table_name: 数据库表名。
        primary_key: 主键列名，默认 ``"id"``。
        model_class: 模型类，需实现 ``from_row(row)`` 和 ``to_dict()``。
        auto_fields: 由数据库自动管理的字段名元组，INSERT / UPDATE 时跳过。
    """

    table_name: str = ""
    primary_key: str = "id"
    model_class: Type[T] = None  # type: ignore[assignment]
    auto_fields: Tuple[str, ...] = ()

    def __init__(self, db: DBConnection) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def find_by_id(self, pk: Any) -> Optional[T]:
        """按主键查询单条记录，不存在时返回 ``None``。"""
        sql = f"SELECT * FROM {self.table_name} WHERE {self.primary_key} = %s"
        with self._db.cursor() as cur:
            cur.execute(sql, (pk,))
            row = cur.fetchone()
        return self.model_class.from_row(row) if row else None

    def find_all(
        self,
        where: Optional[str] = None,
        params: Optional[tuple] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[T]:
        """条件查询，所有参数均可选。

        Args:
            where: WHERE 子句（不含 ``WHERE`` 关键字），例如 ``"status = %s"``。
            params: 与 ``where`` 对应的参数元组。
            order_by: ORDER BY 子句（不含关键字），例如 ``"id DESC"``。
            limit: 最多返回条数。
            offset: 跳过条数。
        """
        sql = f"SELECT * FROM {self.table_name}"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset is not None:
            sql += f" OFFSET {int(offset)}"
        with self._db.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
        return [self.model_class.from_row(r) for r in rows]

    def find_by_fields(self, **kwargs: Any) -> List[T]:
        """等值多字段查询，字段间使用 AND 连接。

        Example::

            repo.find_by_fields(status=1, type=2)
        """
        if not kwargs:
            return self.find_all()
        conditions = " AND ".join(f"{k} = %s" for k in kwargs)
        params = tuple(kwargs.values())
        return self.find_all(where=conditions, params=params)

    def find_page(
        self,
        page: int,
        page_size: int,
        where: Optional[str] = None,
        params: Optional[tuple] = None,
        order_by: Optional[str] = None,
    ) -> Tuple[List[T], int]:
        """分页查询。

        Returns:
            ``(items, total)`` — 当页数据列表与满足条件的总记录数。
        """
        total = self.count(where=where, params=params)
        offset = (page - 1) * page_size
        items = self.find_all(
            where=where,
            params=params,
            order_by=order_by,
            limit=page_size,
            offset=offset,
        )
        return items, total

    def count(
        self,
        where: Optional[str] = None,
        params: Optional[tuple] = None,
    ) -> int:
        """统计满足条件的记录数。"""
        sql = f"SELECT COUNT(*) AS cnt FROM {self.table_name}"
        if where:
            sql += f" WHERE {where}"
        with self._db.cursor() as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
        return int(row["cnt"]) if row else 0

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def insert(self, entity: T) -> int:
        """插入一条记录，返回自增主键值。

        主键列和 ``auto_fields`` 中的字段会被跳过。
        """
        data = entity.to_dict()  # type: ignore[attr-defined]
        skip = set(self.auto_fields) | {self.primary_key}
        fields = [k for k in data if k not in skip]
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})"
        values = tuple(data[f] for f in fields)
        with self._db.cursor() as cur:
            cur.execute(sql, values)
            return cur.lastrowid  # type: ignore[return-value]

    def update(self, entity: T) -> int:
        """按主键全量更新（``auto_fields`` 中的字段跳过），返回受影响行数。"""
        data = entity.to_dict()  # type: ignore[attr-defined]
        skip = set(self.auto_fields)
        fields = [k for k in data if k not in skip and k != self.primary_key]
        set_clause = ", ".join(f"{f} = %s" for f in fields)
        sql = f"UPDATE {self.table_name} SET {set_clause} WHERE {self.primary_key} = %s"
        values = tuple(data[f] for f in fields) + (data[self.primary_key],)
        with self._db.cursor() as cur:
            cur.execute(sql, values)
            return cur.rowcount  # type: ignore[return-value]

    def update_fields(self, pk: Any, **kwargs: Any) -> int:
        """按主键局部更新指定字段，返回受影响行数。

        Example::

            repo.update_fields(pk=5, status=0, remark="done")
        """
        if not kwargs:
            return 0
        set_clause = ", ".join(f"{k} = %s" for k in kwargs)
        sql = f"UPDATE {self.table_name} SET {set_clause} WHERE {self.primary_key} = %s"
        values = tuple(kwargs.values()) + (pk,)
        with self._db.cursor() as cur:
            cur.execute(sql, values)
            return cur.rowcount  # type: ignore[return-value]

    def delete_by_id(self, pk: Any) -> int:
        """物理删除指定主键的记录，返回受影响行数。"""
        sql = f"DELETE FROM {self.table_name} WHERE {self.primary_key} = %s"
        with self._db.cursor() as cur:
            cur.execute(sql, (pk,))
            return cur.rowcount  # type: ignore[return-value]
