"""XfanVideo 数据模型。"""

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class XfanVideo:
    """对应数据库 xfan_video 表的数据模型。

    deleted_flag 约定：1 = 正常，-1 = 已删除。
    """

    id: int = 0
    user_id: str = ""
    character_id: int = 0
    service_level_limits: int = 0
    price: int = 0
    title: str = ""
    video_url: str = ""
    instruct_url: str = ""
    cover_url: Optional[str] = None
    cover_height: int = 0
    cover_width: int = 0
    duration: int = 0
    show_order: int = 0
    deleted_flag: int = 1
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    click_count: int = 0
    background: int = 0

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "XfanVideo":
        """从数据库查询结果行（dict）构造 XfanVideo 实例。

        未知列会被忽略，缺失列使用默认值。
        """
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in row.items() if k in known}
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（字段顺序与声明顺序一致）。"""
        return dataclasses.asdict(self)
