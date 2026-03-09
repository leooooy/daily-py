"""Novel 仓库。"""

from typing import List

from daily_py.db.base_repository import BaseRepository
from daily_py.db.models.novel import Novel


class NovelRepository(BaseRepository[Novel]):
    table_name = "novel"
    primary_key = "id"
    model_class = Novel
    auto_fields = ("create_time", "update_time")
