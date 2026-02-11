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
    __all__ = []
