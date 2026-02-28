"""DailyPy 数据库模块。

提供通用 CRUD 基础设施（DBConnection + BaseRepository）以及 MediaVideo 示例实现。

依赖：
    pip install mysql-connector-python
"""

try:
    from .connection import DBConnection
    from .base_repository import BaseRepository
    from .models.media_video import MediaVideo
    from .models.toy_model_video import ToyModelVideo
    from .repositories.media_video_repository import MediaVideoRepository
    from .repositories.toy_model_video_repository import ToyModelVideoRepository
    from .config import create_connection, ENVS

    __all__ = [
        "DBConnection",
        "BaseRepository",
        "MediaVideo",
        "ToyModelVideo",
        "MediaVideoRepository",
        "ToyModelVideoRepository",
        "create_connection",
        "ENVS",
    ]

except ImportError as _e:
    raise ImportError(
        "daily_py.db 依赖 mysql-connector-python，请执行：\n"
        "    pip install mysql-connector-python\n"
        f"原始错误：{_e}"
    ) from _e
