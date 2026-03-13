"""业务仓库包。"""

from .media_resource_repository import MediaResourceRepository
from .media_video_repository import MediaVideoRepository
from .novel_repository import NovelRepository
from .recommond_repository import RecommondRepository
from .toy_model_video_repository import ToyModelVideoRepository
from .xfan_video_repository import XfanVideoRepository

__all__ = [
    "MediaResourceRepository",
    "MediaVideoRepository",
    "NovelRepository",
    "RecommondRepository",
    "ToyModelVideoRepository",
    "XfanVideoRepository",
]
