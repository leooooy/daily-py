"""DailyPy S3 模块 — 文件上传工具。

依赖：
    pip install boto3
"""

try:
    from .uploader import S3Uploader
    from .config import create_uploader

    __all__ = ["S3Uploader", "create_uploader"]

except ImportError as _e:
    raise ImportError(
        "daily_py.s3 依赖 boto3，请执行：\n"
        "    pip install boto3\n"
        f"原始错误：{_e}"
    ) from _e
