"""MediaResource 数据模型。"""

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class MediaResource:
    """对应数据库 media_resource 表的数据模型。

    注意：id 为 varchar（非自增），common 为 bit(1)，
    时间字段为 created_time / updated_time。
    deleted_flag 约定：1 = 正常，-1 = 已删除。
    """

    id: str = ""
    media_name: Optional[str] = None
    introduce: Optional[str] = None
    media_url: Optional[str] = None
    author: Optional[str] = None
    media_cover_url: Optional[str] = None
    media_cover_height: Optional[int] = None
    media_cover_width: Optional[int] = None
    media_size: int = 0
    service_level_limits: Optional[int] = None
    media_category: Optional[str] = None
    visibility: Optional[str] = None
    user_id: Optional[str] = None
    media_state: Optional[int] = None
    reward_token: int = 0
    likes_count: int = 0
    collection_count: int = 0
    provider_module: Optional[str] = None
    deleted_flag: Optional[int] = 1
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    show_order: Optional[int] = None
    xgame_support: int = 0
    vr_mode: int = 0
    common: Optional[int] = 1

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "MediaResource":
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in row.items() if k in known}
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)
