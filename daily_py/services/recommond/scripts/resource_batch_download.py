"""recommond_table 资源批量下载工具。

查询所有 novel_text_url 不为空的记录，下载每条记录的 4 个 URL 字段到本地：
- novel_text_url
- poster
- instruct_path
- file_path

Usage::

    python -m daily_py.services.recommond.scripts.resource_batch_download D:/recommond_output --env prod
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import requests

from daily_py.db.config import create_connection
from daily_py.db.models.recommond import Recommond
from daily_py.db.repositories.recommond_repository import RecommondRepository


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

# 需要下载的 URL 字段
_URL_FIELDS = ("novel_text_url", "poster", "instruct_path", "file_path")


@dataclass
class DownloadItem:
    """单个 URL 的下载结果。"""
    field_name: str
    url: str
    local_path: str = ""
    success: bool = False
    skipped: bool = False
    error: str = ""
    size_bytes: int = 0


@dataclass
class RecordResult:
    """单条 recommond 记录的下载结果。"""
    record_id: int
    name: str = ""
    items: List[DownloadItem] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for i in self.items if i.success)

    @property
    def skip_count(self) -> int:
        return sum(1 for i in self.items if i.skipped)

    @property
    def fail_count(self) -> int:
        return sum(1 for i in self.items if not i.success and not i.skipped)

    def __str__(self) -> str:
        return (
            f"id={self.record_id}  {self.name}  "
            f"成功 {self.ok_count} / 跳过 {self.skip_count} / 失败 {self.fail_count}"
        )


def _filename_from_url(url: str) -> str:
    """从 URL 中提取文件名。"""
    parsed = urlparse(url)
    return Path(parsed.path).name or "unknown"


def _sanitize_dirname(name: str) -> str:
    """清理目录名中的非法字符。"""
    return re.sub(r'[<>:"/\\|?*]', "_", name or "unknown").strip()


def _download_file(
    url: str,
    dest: Path,
    timeout: int = 60,
    chunk_size: int = 8192,
    logger: Optional[logging.Logger] = None,
) -> int:
    """流式下载文件到 dest，返回文件字节数。"""
    log = logger or logging.getLogger(__name__)
    resp = requests.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()

    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    total = 0
    try:
        with open(tmp_dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                f.write(chunk)
                total += len(chunk)
        tmp_dest.rename(dest)
    except BaseException:
        if tmp_dest.exists():
            tmp_dest.unlink()
        raise

    return total


# ---------------------------------------------------------------------------
# 下载器
# ---------------------------------------------------------------------------

class RecommondDownloader:
    """批量下载 recommond_table 中 novel_text_url 不为空的记录的资源文件。

    Parameters
    ----------
    env : str
        数据库环境。
    timeout : int
        单个文件 HTTP 请求超时（秒）。
    chunk_size : int
        流式下载每次读取的字节数。
    """

    def __init__(
        self,
        env: str = "prod",
        *,
        timeout: int = 60,
        chunk_size: int = 8192,
    ) -> None:
        self._env = env
        self._timeout = timeout
        self._chunk_size = chunk_size
        self._log = logging.getLogger(__name__)

    def run(self, output_dir: str) -> List[RecordResult]:
        """执行完整下载流程。"""
        base = Path(output_dir)
        base.mkdir(parents=True, exist_ok=True)

        db = create_connection(self._env)
        repo = RecommondRepository(db)
        records = repo.find_with_novel_text_url()
        self._log.info("查询到 %d 条 novel_text_url 不为空的记录", len(records))

        if not records:
            return []

        results: List[RecordResult] = []
        for i, rec in enumerate(records, 1):
            self._log.info(
                "===== [%d/%d] id=%d  %s =====",
                i, len(records), rec.id, rec.name or "",
            )
            r = self._download_record(rec, base)
            results.append(r)
            self._log.info("  %s", r)

        self._print_summary(results)
        return results

    def _download_record(self, rec: Recommond, base: Path) -> RecordResult:
        """下载单条记录的所有资源文件。"""
        dir_name = _sanitize_dirname(f"{rec.id}_{rec.name}")
        record_dir = base / dir_name
        record_dir.mkdir(parents=True, exist_ok=True)

        result = RecordResult(record_id=rec.id, name=rec.name or "")

        for field_name in _URL_FIELDS:
            url = getattr(rec, field_name, None)

            if not url or not url.strip():
                continue

            url = url.strip()
            item = DownloadItem(field_name=field_name, url=url)

            try:
                filename = _filename_from_url(url)
                # 用字段名前缀避免同名冲突
                dest = record_dir / f"{field_name}__{filename}"
                item.local_path = str(dest)

                # 已存在则跳过
                if dest.exists() and dest.stat().st_size > 0:
                    item.success = True
                    item.skipped = True
                    item.size_bytes = dest.stat().st_size
                    self._log.info("    [SKIP] %s → %s", field_name, dest.name)
                    result.items.append(item)
                    continue

                # 清理临时文件
                tmp = dest.with_suffix(dest.suffix + ".tmp")
                if tmp.exists():
                    tmp.unlink()

                size = _download_file(
                    url, dest,
                    timeout=self._timeout,
                    chunk_size=self._chunk_size,
                    logger=self._log,
                )
                item.success = True
                item.size_bytes = size
                mb = size / (1024 * 1024)
                self._log.info("    [OK]   %s → %s  (%.2f MB)", field_name, dest.name, mb)

            except Exception as exc:
                item.error = str(exc)
                self._log.warning("    [ERR]  %s → %s", field_name, exc)

            result.items.append(item)

        # 所有 URL 都下载失败时删除空目录
        if result.items and result.ok_count == 0:
            import shutil
            shutil.rmtree(record_dir, ignore_errors=True)
            self._log.warning("  所有文件下载失败，已删除目录: %s", record_dir)

        return result

    def _print_summary(self, results: List[RecordResult]) -> None:
        total_items = sum(len(r.items) for r in results)
        total_ok = sum(r.ok_count for r in results)
        total_skip = sum(r.skip_count for r in results)
        total_fail = sum(r.fail_count for r in results)
        total_bytes = sum(
            it.size_bytes for r in results for it in r.items if it.success and not it.skipped
        )

        sep = "=" * 72
        self._log.info(sep)
        self._log.info(
            "下载完成  记录 %d 条 | 文件 %d 个  成功 %d / 跳过 %d / 失败 %d  (%.1f MB)",
            len(results), total_items, total_ok, total_skip, total_fail,
            total_bytes / (1024 * 1024),
        )
        failed_items = [
            (r, it) for r in results for it in r.items
            if not it.success and not it.skipped
        ]
        if failed_items:
            self._log.warning("失败项:")
            for r, it in failed_items:
                self._log.warning("  id=%d  %s  %s", r.record_id, it.field_name, it.error)
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
        prog="recommond_downloader",
        description="批量下载 recommond_table 中 novel_text_url 不为空的记录的资源文件",
    )
    parser.add_argument("output_dir", help="本地下载目标目录")
    parser.add_argument(
        "--env", default="prod", choices=["test", "prod"],
        help="数据库环境（默认 prod）",
    )
    parser.add_argument(
        "--timeout", type=int, default=60,
        help="HTTP 请求超时秒数（默认 60）",
    )
    args = parser.parse_args()

    downloader = RecommondDownloader(env=args.env, timeout=args.timeout)
    results = downloader.run(args.output_dir)
    sys.exit(0 if all(r.fail_count == 0 for r in results) else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # ===== 在这里填写参数 =====
        OUTPUT_DIR = r"D:/recommond_output"
        ENV = "prod"
        # ==========================

        _setup_logging()
        RecommondDownloader(env=ENV).run(OUTPUT_DIR)
