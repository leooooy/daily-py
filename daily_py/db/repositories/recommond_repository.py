"""Recommond 仓库。"""

from typing import List

from daily_py.db.base_repository import BaseRepository
from daily_py.db.models.recommond import Recommond


class RecommondRepository(BaseRepository[Recommond]):
    table_name = "recommond_table"
    primary_key = "id"
    model_class = Recommond
    auto_fields = ("create_time", "update_time")

    def find_with_novel_text_url(self) -> List[Recommond]:
        """查询所有 novel_text_url 不为空的记录。"""
        return self.find_all(
            where="novel_text_url IS NOT NULL AND novel_text_url != ''",
            params=(),
            order_by="id ASC",
        )
