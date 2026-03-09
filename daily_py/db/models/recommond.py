"""Recommond 数据模型。"""

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class Recommond:
    """对应数据库 recommond_table 表的数据模型。

    deleted_flag 约定：1 = 正常，-1 = 已删除。
    """

    id: int = 0
    name: Optional[str] = None
    tag: Optional[str] = None
    introduce: Optional[str] = None
    poster: Optional[str] = None
    author: Optional[str] = None
    instruct_path: Optional[str] = None
    status: int = 0
    file_path: Optional[str] = None
    vr_video_url: Optional[str] = None
    type: Optional[str] = None
    duration: Optional[int] = None
    image_height: Optional[int] = None
    image_width: Optional[int] = None
    service_level_limits: Optional[int] = None
    deleted_flag: Optional[int] = 1
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    likes_count: int = 0
    collection_count: int = 0
    fake_collection_count: Optional[int] = None
    is_old_version: int = 0
    novel_text_url: Optional[str] = None
    show_order: int = 890
    first_frame_url: Optional[str] = None
    gender: Optional[int] = None
    selected_level: int = 0
    xgame_supported: Optional[int] = 0
    vr_mode: int = 0

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Recommond":
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in row.items() if k in known}
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)
