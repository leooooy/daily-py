"""novel 批量更新 alignment_url 工具。

遍历目录中的 .json 文件，文件名格式为 ``{id}_{title}.json``
（如 ``14_Neon_Sorcery.json``），下划线前的数字即为 novel 表的 id。
将 JSON 上传至 S3 的 ``media_resource/novel`` 目录后，
更新对应记录的 alignment_url 字段。

Usage::

    python -m daily_py.services.novel.alignment_url_batch_update D:/align_json --env prod
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from daily_py.db.config import create_connection
from daily_py.db.repositories.novel_repository import NovelRepository
from daily_py.s3.config import create_uploader


@dataclass
class UpdateResult:
    """单个 JSON 文件的处理结果。"""

    json_file: str
    novel_id: int = 0
    s3_url: str = ""
    success: bool = False
    skipped: bool = False
    error: str = ""

    def __str__(self) -> str:
        if self.success:
            return f"[OK]   {self.json_file} → id={self.novel_id}  {self.s3_url}"
        if self.skipped:
            return f"[SKIP] {self.json_file}  {self.error}"
        return f"[ERR]  {self.json_file}  {self.error}"


def _parse_id(filename: str) -> Optional[int]:
    """从文件名提取 id，格式: {id}_{...}.json"""
    m = re.match(r"^(\d+)_", filename)
    return int(m.group(1)) if m else None


class NovelAlignmentUpdater:
    """批量上传 align.json 并更新 novel.alignment_url。

    Parameters
    ----------
    env : str
        数据库环境，``"test"`` 或 ``"prod"``。
    s3_prefix : str
        S3 上传路径前缀，默认 ``"media_resource/novel"``。
    """

    def __init__(
        self,
        env: str = "prod",
        *,
        s3_prefix: str = "media_resource/novel",
    ) -> None:
        self._env = env
        self._s3_prefix = s3_prefix.strip("/")
        self._log = logging.getLogger(__name__)

    def run(self, json_dir: str) -> List[UpdateResult]:
        base = Path(json_dir)
        if not base.is_dir():
            raise NotADirectoryError(f"目录不存在：{json_dir}")

        json_files = sorted(base.glob("*.json"))
        self._log.info("在 %s 中找到 %d 个 .json 文件", json_dir, len(json_files))

        if not json_files:
            return []

        db = create_connection(self._env)
        repo = NovelRepository(db)
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
        result = UpdateResult(json_file=json_path.name)

        try:
            novel_id = _parse_id(json_path.name)
            if novel_id is None:
                result.skipped = True
                result.error = "文件名无法解析 id（需 {id}_{...}.json 格式）"
                return result
            result.novel_id = novel_id

            novel = repo.find_by_id(novel_id)
            if novel is None:
                result.skipped = True
                result.error = f"id={novel_id} 在 novel 表中不存在"
                return result

            s3_key = f"{self._s3_prefix}/{json_path.name}"
            s3_url = uploader.upload_file(str(json_path), s3_key, content_type="application/json")
            result.s3_url = s3_url

            affected = repo.update_fields(novel_id, alignment_url=s3_url)
            if affected == 0:
                result.error = f"更新失败，受影响行数为 0 (id={novel_id})"
                return result

            result.success = True
            self._log.info("  已更新 id=%d alignment_url=%s", novel_id, s3_url)

        except Exception as exc:
            result.error = str(exc)
            self._log.exception("处理 %s 时出错", json_path.name)

        return result

    def _print_summary(self, results: List[UpdateResult]) -> None:
        ok = [r for r in results if r.success]
        skipped = [r for r in results if r.skipped]
        failed = [r for r in results if not r.success and not r.skipped]

        sep = "=" * 72
        self._log.info(sep)
        self._log.info(
            "处理完成  成功 %d / 跳过 %d / 失败 %d / 共 %d",
            len(ok), len(skipped), len(failed), len(results),
        )
        if skipped:
            self._log.info("跳过项:")
            for r in skipped:
                self._log.info("  %s  %s", r.json_file, r.error)
        if failed:
            self._log.warning("失败项:")
            for r in failed:
                self._log.warning("  %s  %s", r.json_file, r.error)
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
        prog="novel_alignment_updater",
        description="批量上传 align.json 到 S3 并更新 novel.alignment_url",
    )
    parser.add_argument("json_dir", help="包含 .json 文件的本地目录")
    parser.add_argument(
        "--env", default="prod", choices=["test", "prod"],
        help="数据库环境（默认 prod）",
    )
    parser.add_argument(
        "--s3-prefix", default="media_resource/novel",
        help="S3 上传路径前缀（默认 media_resource/novel）",
    )
    args = parser.parse_args()

    updater = NovelAlignmentUpdater(env=args.env, s3_prefix=args.s3_prefix)
    results = updater.run(args.json_dir)
    sys.exit(0 if all(r.success or r.skipped for r in results) else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # ===== 在这里填写参数 =====
        JSON_DIR = r"D:\ftp\260318\novel_json"
        ENV = "prod"
        S3_PREFIX = "media_resource/novel"
        # ==========================

        _setup_logging()
        NovelAlignmentUpdater(env=ENV, s3_prefix=S3_PREFIX).run(JSON_DIR)
