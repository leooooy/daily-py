"""xfan_video 批量更新 instruct_url 工具。

读取指定目录下的所有 .json 文件，根据文件名（去掉 .json 后缀）在 xfan_video 表中
查找 video_url 包含该文件名的记录。若恰好匹配到 1 条，将 JSON 文件上传至 S3 并
更新该记录的 instruct_url 字段。

Usage::

    python -m daily_py.services.xfan_video.instruct_updater D:/json_files --env prod

示例::

    目录中有: 777_ZippyBloom_3_video_sync_2_1043f6.json
    → 查询 video_url LIKE '%777_ZippyBloom_3_video_sync_2_1043f6%'
    → 匹配 1 条 → 上传 S3 → 更新 instruct_url
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from daily_py.db.config import create_connection
from daily_py.db.repositories.xfan_video_repository import XfanVideoRepository
from daily_py.s3.config import create_uploader


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class UpdateResult:
    """单个 JSON 文件的处理结果。"""

    json_file: str
    keyword: str = ""
    match_count: int = 0
    video_id: int = 0
    s3_url: str = ""
    success: bool = False
    skipped: bool = False
    error: str = ""

    def __str__(self) -> str:
        if self.success:
            return f"[OK]   {self.json_file} → id={self.video_id}  {self.s3_url}"
        if self.skipped:
            return f"[SKIP] {self.json_file}  匹配 {self.match_count} 条（需恰好 1 条）"
        return f"[ERR]  {self.json_file}  {self.error}"


# ---------------------------------------------------------------------------
# 更新器
# ---------------------------------------------------------------------------

class XfanVideoInstructUpdater:
    """批量更新 xfan_video 表的 instruct_url 字段。

    Parameters
    ----------
    env : str
        数据库环境，``"test"`` 或 ``"prod"``。
    s3_prefix : str
        上传到 S3 的路径前缀，默认 ``"xfan/instruct"``。
    """

    def __init__(
        self,
        env: str = "test",
        *,
        s3_prefix: str = "xfan/instruct",
    ) -> None:
        self._env = env
        self._s3_prefix = s3_prefix.strip("/")
        self._log = logging.getLogger(__name__)

    def run(self, json_dir: str) -> List[UpdateResult]:
        """执行完整的批量更新流程。

        Parameters
        ----------
        json_dir : str
            包含 .json 文件的本地目录。
        """
        base = Path(json_dir)
        if not base.is_dir():
            raise NotADirectoryError(f"目录不存在：{json_dir}")

        json_files = sorted(base.rglob("*.json"))
        self._log.info("在 %s 中找到 %d 个 .json 文件", json_dir, len(json_files))

        if not json_files:
            return []

        db = create_connection(self._env)
        repo = XfanVideoRepository(db)
        uploader = create_uploader()

        results: List[UpdateResult] = []
        for i, jf in enumerate(json_files, 1):
            self._log.info("--- [%d/%d] %s ---", i, len(json_files), jf.name)
            r = self._process_one(jf, repo, uploader)
            results.append(r)
            self._log.info(str(r))

        self._print_summary(results)
        return results

    def _process_one(self, json_path: Path, repo, uploader) -> UpdateResult:
        """处理单个 JSON 文件。"""
        result = UpdateResult(json_file=json_path.name)

        try:
            keyword = json_path.stem
            result.keyword = keyword

            matches = repo.find_by_video_url_containing(keyword)
            result.match_count = len(matches)

            if len(matches) != 1:
                result.skipped = True
                if len(matches) == 0:
                    self._log.warning("  未找到匹配记录: %s", keyword)
                else:
                    self._log.warning(
                        "  匹配到 %d 条记录（需恰好 1 条），跳过: %s",
                        len(matches), keyword,
                    )
                return result

            video = matches[0]
            result.video_id = video.id

            s3_key = f"{self._s3_prefix}/{json_path.name}"
            s3_url = uploader.upload_file(str(json_path), s3_key, content_type="application/json")
            result.s3_url = s3_url

            affected = repo.update_fields(video.id, instruct_url=s3_url)
            if affected == 0:
                result.error = f"更新失败，受影响行数为 0 (id={video.id})"
                return result

            result.success = True
            self._log.info("  已更新 id=%d instruct_url=%s", video.id, s3_url)

        except Exception as exc:
            result.error = str(exc)
            self._log.exception("处理 %s 时出错", json_path.name)

        return result

    def _print_summary(self, results: List[UpdateResult]) -> None:
        ok = [r for r in results if r.success]
        skipped = [r for r in results if r.skipped]
        failed = [r for r in results if not r.success and not r.skipped]

        sep = "-" * 72
        self._log.info(sep)
        self._log.info(
            "处理完成  成功 %d / 跳过 %d / 失败 %d / 共 %d",
            len(ok), len(skipped), len(failed), len(results),
        )
        if skipped:
            self._log.info("跳过项（匹配数 ≠ 1）:")
            for r in skipped:
                self._log.info("  %s  匹配 %d 条", r.json_file, r.match_count)
        if failed:
            self._log.warning("失败项:")
            for r in failed:
                self._log.warning("  %s  %s", r.json_file, r.error)
        self._log.info(sep)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  %(levelname)-5s  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main() -> None:
    import argparse

    _setup_logging()

    parser = argparse.ArgumentParser(
        prog="xfan_video_instruct_updater",
        description="批量上传 JSON 到 S3 并更新 xfan_video.instruct_url",
    )
    parser.add_argument("json_dir", help="包含 .json 文件的本地目录")
    parser.add_argument(
        "--env", default="prod", choices=["test", "prod"],
        help="数据库环境（默认 prod）",
    )
    parser.add_argument(
        "--s3-prefix", default="xfan/instruct",
        help="S3 上传路径前缀（默认 xfan/instruct）",
    )

    args = parser.parse_args()

    updater = XfanVideoInstructUpdater(env=args.env, s3_prefix=args.s3_prefix)
    results = updater.run(args.json_dir)

    sys.exit(0 if all(r.success or r.skipped for r in results) else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # ===== 在这里填写参数 =====
        JSON_DIR = r"E:\1、metaXsire内容\1、商业版APP\3、XFans\2. XFans角色视频共振素材\40角色-连接玩具导入账号"
        ENV = "prod"
        S3_PREFIX = "xfan/instruct"
        # ==========================

        _setup_logging()
        u = XfanVideoInstructUpdater(env=ENV, s3_prefix=S3_PREFIX)
        u.run(JSON_DIR)
