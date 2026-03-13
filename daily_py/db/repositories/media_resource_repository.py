"""MediaResource 业务仓库。"""

from ..base_repository import BaseRepository
from ..models.media_resource import MediaResource


class MediaResourceRepository(BaseRepository[MediaResource]):
    """针对 media_resource 表的业务仓库。

    注意：media_resource 的主键 id 是 varchar（非自增），
    insert 时需要包含主键字段。
    """

    table_name = "media_resource"
    primary_key = "id"
    model_class = MediaResource
    auto_fields = ("created_time", "updated_time")

    def insert(self, entity: MediaResource) -> int:  # type: ignore[override]
        """插入一条记录（包含主键 id）。

        与 BaseRepository.insert 不同，这里不跳过主键列，
        因为 media_resource.id 是 varchar，需要手动指定。
        返回 0（无自增主键）。
        """
        data = entity.to_dict()
        skip = set(self.auto_fields)
        fields = [k for k in data if k not in skip]
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})"
        values = tuple(data[f] for f in fields)
        with self._db.cursor() as cur:
            cur.execute(sql, values)
            return 0
