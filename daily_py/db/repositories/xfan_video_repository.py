"""XfanVideo 业务仓库。"""

from typing import List, Optional, Tuple

from ..base_repository import BaseRepository
from ..models.xfan_video import XfanVideo


class XfanVideoRepository(BaseRepository[XfanVideo]):
    """针对 xfan_video 表的业务仓库。"""

    table_name = "xfan_video"
    primary_key = "id"
    model_class = XfanVideo
    auto_fields = ("create_time", "update_time")

    # 需要排除的 character_id 列表（主线角色）
    EXCLUDED_CHARACTER_IDS = (
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
        11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        21, 22, 23, 24,
        1000, 1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008,
        1009, 1010, 1011, 1012, 1013, 1014, 1015, 1016, 1017,
    )

    # ------------------------------------------------------------------
    # 业务查询
    # ------------------------------------------------------------------

    def find_all_active(self) -> List[XfanVideo]:
        """查询所有未删除（deleted_flag=1）且排除主线角色的视频，按 id 升序。"""
        placeholders = ",".join(["%s"] * len(self.EXCLUDED_CHARACTER_IDS))
        return self.find_all(
            where=f"deleted_flag = %s AND character_id NOT IN ({placeholders})",
            params=(1, *self.EXCLUDED_CHARACTER_IDS),
            order_by="id ASC",
        )

    def find_by_video_url_containing(self, keyword: str) -> List[XfanVideo]:
        """查询 video_url 包含指定关键字的未删除记录。"""
        return self.find_all(
            where="deleted_flag = %s AND video_url LIKE %s",
            params=(1, f"%{keyword}%"),
        )

    def find_active(
        self,
        page: int = 1,
        page_size: int = 100,
    ) -> Tuple[List[XfanVideo], int]:
        """分页查询未删除（deleted_flag=1）的视频，按 id 升序。"""
        return self.find_page(
            page=page,
            page_size=page_size,
            where="deleted_flag = %s",
            params=(1,),
            order_by="id ASC",
        )

    # ------------------------------------------------------------------
    # 管理查询
    # ------------------------------------------------------------------

    def find_all_admin(
        self,
        page: int = 1,
        page_size: int = 50,
        deleted_flag: Optional[int] = None,
        background: Optional[int] = None,
        keyword: str = "",
    ) -> Tuple[List[XfanVideo], int]:
        """管理员分页查询，支持按删除状态、background、关键词过滤，按 id 降序。"""
        conditions: list = []
        params: list = []
        if deleted_flag is not None:
            conditions.append("deleted_flag = %s")
            params.append(deleted_flag)
        if background is not None:
            conditions.append("background = %s")
            params.append(background)
        if keyword:
            conditions.append("(title LIKE %s OR video_url LIKE %s)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        where = " AND ".join(conditions) if conditions else None
        return self.find_page(
            page=page,
            page_size=page_size,
            where=where,
            params=tuple(params) if params else None,
            order_by="id DESC",
        )

    # ------------------------------------------------------------------
    # 软删除 / 恢复
    # ------------------------------------------------------------------

    def soft_delete(self, video_id: int) -> int:
        """软删除：将 deleted_flag 置为 -1，返回受影响行数。"""
        return self.update_fields(video_id, deleted_flag=-1)

    def restore(self, video_id: int) -> int:
        """恢复：将 deleted_flag 置为 1，返回受影响行数。"""
        return self.update_fields(video_id, deleted_flag=1)
