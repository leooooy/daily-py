"""MediaVideo 业务仓库。"""

from typing import List, Tuple

from ..base_repository import BaseRepository
from ..models.media_video import MediaVideo


class MediaVideoRepository(BaseRepository[MediaVideo]):
    """针对 media_video 表的业务仓库，在通用 CRUD 基础上新增业务查询。"""

    table_name = "media_video"
    primary_key = "id"
    model_class = MediaVideo
    auto_fields = ("create_time", "update_time")

    # ------------------------------------------------------------------
    # 软删除 / 恢复
    # ------------------------------------------------------------------

    def soft_delete(self, video_id: int) -> int:
        """软删除：将 deleted_flag 置为 -1，返回受影响行数。"""
        return self.update_fields(video_id, deleted_flag=-1)

    def restore(self, video_id: int) -> int:
        """恢复：将 deleted_flag 置为 1，返回受影响行数。"""
        return self.update_fields(video_id, deleted_flag=1)

    # ------------------------------------------------------------------
    # 业务查询
    # ------------------------------------------------------------------

    def find_visible(
        self, page: int = 1, page_size: int = 20
    ) -> Tuple[List[MediaVideo], int]:
        """查询未删除且处于显示状态的视频，按 show_order 升序分页。"""
        return self.find_page(
            page=page,
            page_size=page_size,
            where="deleted_flag = %s AND show_status = %s",
            params=(1, 1),
            order_by="show_order ASC",
        )

    def find_pinned(self) -> List[MediaVideo]:
        """查询所有置顶（pinned=1）且未删除的视频，按 show_order 升序。"""
        return self.find_all(
            where="pinned = %s AND deleted_flag = %s",
            params=(1, 1),
            order_by="show_order ASC",
        )

    def find_by_type(
        self, video_type: int, page: int = 1, page_size: int = 20
    ) -> Tuple[List[MediaVideo], int]:
        """按视频类型分页查询（仅未删除记录），按 show_order 升序。"""
        return self.find_page(
            page=page,
            page_size=page_size,
            where="type = %s AND deleted_flag = %s",
            params=(video_type, 1),
            order_by="show_order ASC",
        )

    def increment_click(self, video_id: int) -> int:
        """原子递增点击计数，返回受影响行数。"""
        sql = (
            f"UPDATE {self.table_name} SET click_count = click_count + 1"
            f" WHERE {self.primary_key} = %s"
        )
        with self._db.cursor() as cur:
            cur.execute(sql, (video_id,))
            return cur.rowcount  # type: ignore[return-value]
