"""ToyModelVideo 数据模型。"""

import dataclasses
import json
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ToyModelVideo:
    """对应数据库 toy_model_video 表的数据模型。

    toy_model: 玩具蓝牙型号（字符串主键）。
    video_ids: 关联视频 ID，JSON 数组字符串存储，例如 ``"[26,27,28]"``。
    """

    toy_model: str = ""
    video_ids: str = ""

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "ToyModelVideo":
        """从数据库查询结果行（dict）构造实例，未知列自动忽略。"""
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in row.items() if k in known})

    def to_dict(self) -> Dict[str, Any]:
        """转为字典。"""
        return dataclasses.asdict(self)

    def get_video_id_list(self) -> List[int]:
        """将 video_ids JSON 数组字符串解析为整数列表。"""
        if not self.video_ids.strip():
            return []
        return [int(x) for x in json.loads(self.video_ids)]

    @classmethod
    def from_video_id_list(cls, toy_model: str, ids: List[int]) -> "ToyModelVideo":
        """从视频 ID 整数列表构造实例，序列化为 JSON 数组字符串。"""
        return cls(toy_model=toy_model, video_ids=json.dumps(ids, separators=(",", ":")))
