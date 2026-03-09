"""xfan_video Background 文件检查工具。

递归遍历指定目录下所有文件名包含 "Background"（不区分大小写）的文件夹，
扫描其中的 .mp4 文件，查询 xfan_video 表中 video_url 是否包含该文件名，
并统计结果。

Usage::

    python -m daily_py.services.xfan_video.background_checker D:/videos --env prod
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from daily_py.db.config import create_connection
from daily_py.db.repositories.xfan_video_repository import XfanVideoRepository


@dataclass
class CheckItem:
    """单个 mp4 文件的检查结果。"""
    mp4_file: str
    folder: str
    keyword: str = ""
    match_count: int = 0
    video_ids: List[int] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.match_count > 0


class XfanVideoBackgroundChecker:
    """扫描 Background 文件夹中的 mp4，检查是否存在于 xfan_video 表。"""

    def __init__(self, env: str = "prod") -> None:
        self._env = env
        self._log = logging.getLogger(__name__)

    def run(self, root_dir: str) -> List[CheckItem]:
        root = Path(root_dir)
        if not root.is_dir():
            raise NotADirectoryError(f"目录不存在：{root_dir}")

        # 1) 找到所有名称包含 background 的文件夹
        bg_dirs = [
            d for d in root.rglob("*")
            if d.is_dir() and "background" in d.name.lower()
        ]
        self._log.info("在 %s 中找到 %d 个 Background 文件夹", root_dir, len(bg_dirs))
        for d in bg_dirs:
            self._log.info("  %s", d)

        if not bg_dirs:
            return []

        # 2) 收集所有 mp4 文件
        mp4_files: List[tuple[Path, Path]] = []  # (mp4_path, parent_bg_dir)
        for d in bg_dirs:
            for mp4 in sorted(d.glob("*.mp4")):
                mp4_files.append((mp4, d))
        self._log.info("共找到 %d 个 mp4 文件", len(mp4_files))

        if not mp4_files:
            return []

        # 3) 逐个查询数据库
        db = create_connection(self._env)
        repo = XfanVideoRepository(db)

        results: List[CheckItem] = []
        for i, (mp4, bg_dir) in enumerate(mp4_files, 1):
            keyword = mp4.stem  # 去掉 .mp4 后缀
            item = CheckItem(
                mp4_file=mp4.name,
                folder=str(bg_dir.relative_to(root)),
                keyword=keyword,
            )

            matches = repo.find_by_video_url_containing(keyword)
            item.match_count = len(matches)
            item.video_ids = [v.id for v in matches]

            tag = "EXISTS" if item.found else "MISS"
            self._log.info(
                "[%d/%d] [%s] %s  (匹配 %d 条%s)",
                i, len(mp4_files), tag, mp4.name, len(matches),
                f"  ids={item.video_ids}" if matches else "",
            )
            results.append(item)

        self._print_summary(results)
        return results

    def _print_summary(self, results: List[CheckItem]) -> None:
        found = [r for r in results if r.found]
        missed = [r for r in results if not r.found]

        sep = "=" * 72
        self._log.info(sep)
        self._log.info(
            "统计  共 %d 个 mp4 | 已存在 %d | 未找到 %d",
            len(results), len(found), len(missed),
        )
        self._log.info(sep)

        if missed:
            self._log.info("未找到的文件:")
            for r in missed:
                self._log.info("  [%s] %s", r.folder, r.mp4_file)

        if found:
            self._log.info("已存在的文件:")
            for r in found:
                self._log.info(
                    "  [%s] %s  → %d 条  ids=%s",
                    r.folder, r.mp4_file, r.match_count, r.video_ids,
                )
        self._log.info(sep)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main() -> None:
    import argparse

    _setup_logging()

    parser = argparse.ArgumentParser(
        prog="xfan_video_background_checker",
        description="扫描 Background 文件夹中的 mp4，检查是否存在于 xfan_video 表",
    )
    parser.add_argument("root_dir", help="要扫描的根目录")
    parser.add_argument(
        "--env", default="prod", choices=["test", "prod"],
        help="数据库环境（默认 prod）",
    )
    args = parser.parse_args()

    checker = XfanVideoBackgroundChecker(env=args.env)
    checker.run(args.root_dir)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # ===== 在这里填写参数 =====
        ROOT_DIR = r"E:\1、metaXsire内容\1、商业版APP\3、XFans\2. XFans角色视频共振素材\40角色-连接玩具导入账号"
        ENV = "prod"
        # ==========================

        _setup_logging()
        XfanVideoBackgroundChecker(env=ENV).run(ROOT_DIR)
