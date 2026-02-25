"""
媒体视频上传 GUI — 右键 Run 直接启动。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daily_py.ui.media_upload_gui import main

if __name__ == "__main__":
    main()
