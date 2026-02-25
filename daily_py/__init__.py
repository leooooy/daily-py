"""DailyPy - 日常Python工具库

提供简单、通用的日常工具集合。当前仅包含 FileHandler 文件处理器。
"""

__version__ = "0.1.0"
__author__ = "DailyPy Team"
__description__ = "日常Python工具集"

try:
    from .file_handler import FileHandler  # type: ignore
    __all__ = ["FileHandler"]
except Exception:
    # 在打包或导入阶段可能尚未生成文件时不阻塞导入
    __all__ = ["ImageHandler"] if 'ImageHandler' in globals() else []

# 兼容地导出 ImageHandler（若 image_handler 模块存在）
try:
    from .image_handler import ImageHandler  # type: ignore
    __all__.append("ImageHandler")
except Exception:
    pass

# 导出 db 模块公共类（依赖 mysql-connector-python，缺失时跳过）
try:
    from .db import DBConnection, BaseRepository, MediaVideo, MediaVideoRepository, create_connection, ENVS  # type: ignore
    __all__ += ["DBConnection", "BaseRepository", "MediaVideo", "MediaVideoRepository", "create_connection", "ENVS"]
except Exception:
    pass

try:
    from .s3 import S3Uploader, create_uploader  # type: ignore
    __all__ += ["S3Uploader", "create_uploader"]
except Exception:
    pass

try:
    from .media_video_uploader import MediaVideoUploader, UploadResult  # type: ignore
    __all__ += ["MediaVideoUploader", "UploadResult"]
except Exception:
    pass
