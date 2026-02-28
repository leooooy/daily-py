"""ToyModelVideo 业务仓库。"""

import json
from typing import List

from ..base_repository import BaseRepository
from ..models.toy_model_video import ToyModelVideo


class ToyModelVideoRepository(BaseRepository[ToyModelVideo]):
    """针对 toy_model_video 表的业务仓库。

    toy_model 为字符串主键（非自增），insert / upsert 均包含该字段。
    """

    table_name = "toy_model_video"
    primary_key = "toy_model"
    model_class = ToyModelVideo
    auto_fields = ()

    # ------------------------------------------------------------------
    # 写入 —— 覆盖 BaseRepository.insert（主键非自增，不可跳过）
    # ------------------------------------------------------------------

    def insert(self, entity: ToyModelVideo) -> int:
        """插入一条记录（toy_model 作为字符串主键，不跳过主键列）。

        Returns:
            受影响行数。
        """
        data = entity.to_dict()
        fields = [k for k in data if k not in self.auto_fields]
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})"
        with self._db.cursor() as cur:
            cur.execute(sql, tuple(data[f] for f in fields))
            return cur.rowcount  # type: ignore[return-value]

    def upsert(self, entity: ToyModelVideo) -> int:
        """插入或更新（ON DUPLICATE KEY UPDATE video_ids）。

        若 toy_model 已存在则更新 video_ids，否则插入新行。

        Returns:
            受影响行数（插入=1，更新=2，无变化=0）。
        """
        sql = (
            f"INSERT INTO {self.table_name} (toy_model, video_ids)"
            f" VALUES (%s, %s)"
            f" ON DUPLICATE KEY UPDATE video_ids = VALUES(video_ids)"
        )
        with self._db.cursor() as cur:
            cur.execute(sql, (entity.toy_model, entity.video_ids))
            return cur.rowcount  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 业务查询
    # ------------------------------------------------------------------

    def find_all_ordered(self) -> List[ToyModelVideo]:
        """查询全部记录，按 toy_model 字母序升序。"""
        return self.find_all(order_by="toy_model ASC")

    # ------------------------------------------------------------------
    # 便捷写入
    # ------------------------------------------------------------------

    def set_video_ids(self, toy_model: str, video_ids: str) -> int:
        """更新指定玩具型号的 video_ids 字符串，返回受影响行数。"""
        return self.update_fields(toy_model, video_ids=video_ids)

    def set_video_id_list(self, toy_model: str, ids: List[int]) -> int:
        """将整数 ID 列表序列化为 JSON 数组字符串后更新，返回受影响行数。"""
        return self.set_video_ids(toy_model, json.dumps(ids, separators=(",", ":")))
