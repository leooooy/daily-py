"""
媒体视频上传脚本 — 右键 Run 直接执行。

使用步骤：
  1. 修改下面 ===== 配置区 ===== 里的参数
  2. 先把 DRY_RUN 设为 True 试跑，确认文件列表无误
  3. 确认后把 DRY_RUN 改为 False 正式上传
"""

import sys
from pathlib import Path

# 把项目根目录加入 sys.path，使脚本在任意位置都能 import daily_py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daily_py.media_video_pipeline import MediaVideoPipeline

# ===================================================================
# ★ 配置区 — 按需修改
# ===================================================================

# 要上传的本地视频目录（支持 Windows 反斜杠或 / 都可以）
FOLDER = r"D:\ftp\260126\2"

# 数据库环境："test"（内网 192.168.0.200）或 "prod"（AWS RDS）
ENV = "test"

# 是否递归扫描子目录
RECURSIVE = False

# 试运行模式：True = 只打印计划，不实际上传/写库；False = 正式执行
DRY_RUN = False

# S3 前缀（一般不需要改）
VIDEO_PREFIX  = "media_video"
JSON_PREFIX   = "media_instruct"
COVER_PREFIX  = "media_cover"

# 封面截取时间点（秒）
COVER_TIME_SEC = 1.0

# 写入 DB 时的默认字段值
DEFAULT_TYPE                  = 0
DEFAULT_SERVICE_LEVEL_LIMITS  = 0   # 服务等级限制，0 = 不限制
DEFAULT_COMMON                = None  # common 字段，None = NULL

# ===================================================================

if __name__ == "__main__":
    pipeline = MediaVideoPipeline(
        env=ENV,
        video_prefix=VIDEO_PREFIX,
        json_prefix=JSON_PREFIX,
        cover_prefix=COVER_PREFIX,
        cover_time_sec=COVER_TIME_SEC,
        default_type=DEFAULT_TYPE,
        default_service_level_limits=DEFAULT_SERVICE_LEVEL_LIMITS,
        default_common=DEFAULT_COMMON,
    )
    pipeline.run(FOLDER, recursive=RECURSIVE, dry_run=DRY_RUN)
