"""Novel 数据模型。"""

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class Novel:
    """对应数据库 novel 表的数据模型。

    deleted_flag 约定：1 = 正常，-1 = 已删除。
    """

    id: int = 0
    author: str = ""
    introduction: str = ""
    title: str = ""
    cover: str = ""
    cover_height: int = 0
    cover_width: int = 0
    content: Optional[str] = None
    audio_url: str = ""
    service_level_limits: int = 0
    click_count: int = 0
    deleted_flag: int = 1
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Novel":
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in row.items() if k in known}
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)
