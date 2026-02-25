"""MediaVideo 数据模型。"""

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class MediaVideo:
    """对应数据库 media_video 表的数据模型。

    deleted_flag 约定：1 = 正常，-1 = 已删除。
    """

    id: int = 0
    media_name: str = ""
    media_url: str = ""
    media_instruct_url: str = ""
    media_cover_url: str = ""
    media_cover_width: int = 0
    media_cover_height: int = 0
    duration: int = 0
    type: int = 0
    service_level_limits: int = 0
    xgame_supported: int = 0
    pinned: int = 0
    show_status: int = 0
    show_order: int = 0
    common: Optional[int] = None
    deleted_flag: int = 1
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    app_version_type: Optional[int] = None
    click_count: int = 0

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "MediaVideo":
        """从数据库查询结果行（dict）构造 MediaVideo 实例。

        未知列会被忽略，缺失列使用默认值。
        """
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in row.items() if k in known}
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（字段顺序与声明顺序一致）。"""
        return dataclasses.asdict(self)
