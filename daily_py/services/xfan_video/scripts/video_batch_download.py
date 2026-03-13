"""xfan_video 批量下载工具。

从 xfan_video 表读取 video_url，解析文件名中前两段下划线分隔的段作为子目录名，
下载到本地指定目录。

Usage::

    python -m daily_py.services.xfan_video.scripts.video_batch_download D:/downloads/xfan --env prod

URL 示例::

    https://cdn.metaxsire.com/xfan/777_ZippyBloom_3_video_sync_2_1043f6.mp4
    → 子目录: 777_ZippyBloom
    → 文件名: 777_ZippyBloom_3_video_sync_2_1043f6.mp4
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import requests

from daily_py.db.config import create_connection
from daily_py.db.models.xfan_video import XfanVideo
from daily_py.db.repositories.xfan_video_repository import XfanVideoRepository


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    """单个视频文件的下载结果。"""

    video_id: int
    video_url: str
    local_path: str = ""
    success: bool = False
    skipped: bool = False
    error: str = ""
    size_bytes: int = 0
    elapsed_sec: float = 0.0

    def __str__(self) -> str:
        if self.skipped:
            return f"[SKIP] id={self.video_id}  {self.local_path}"
        if self.success:
            mb = self.size_bytes / (1024 * 1024)
            return (
                f"[OK]   id={self.video_id}  {mb:.1f}MB"
                f"  {self.elapsed_sec:.1f}s  {self.local_path}"
            )
        return f"[ERR]  id={self.video_id}  {self.error}"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _extract_subfolder(url: str) -> str:
    """从 URL 的文件名中提取前两段下划线分隔的段作为子目录名。

    Example::

        '777_ZippyBloom_3_video_sync_2_1043f6.mp4' -> '777_ZippyBloom'

    不足两段时使用整个 stem。
    """
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    stem = Path(filename).stem
    parts = stem.split("_")
    if len(parts) >= 2:
        return f"{parts[0]}_{parts[1]}"
    return stem


def download_file(
    url: str,
    dest: Path,
    timeout: int = 60,
    chunk_size: int = 8192,
    logger: Optional[logging.Logger] = None,
) -> int:
    """流式下载文件到 dest，返回文件字节数。

    先写入 .tmp 临时文件，完成后 rename，防止中断产生不完整文件。
    """
    log = logger or logging.getLogger(__name__)
    resp = requests.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()

    content_length = resp.headers.get("Content-Length")
    if content_length:
        log.info("  Content-Length: %s bytes", content_length)

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

class XfanVideoDownloader:
    """从 xfan_video 表批量下载视频到本地目录。

    Parameters
    ----------
    env : str
        数据库环境，``"test"`` 或 ``"prod"``。
    timeout : int
        单个文件 HTTP 请求超时（秒）。
    chunk_size : int
        流式下载每次读取的字节数。
    """

    def __init__(
        self,
        env: str = "test",
        *,
        timeout: int = 60,
        chunk_size: int = 8192,
    ) -> None:
        self._env = env
        self._timeout = timeout
        self._chunk_size = chunk_size
        self._log = logging.getLogger(__name__)

    def run(self, output_dir: str) -> List[DownloadResult]:
        """执行完整下载流程。

        Parameters
        ----------
        output_dir : str
            本地目标根目录。视频将按子目录分类存放。
        """
        base = Path(output_dir)
        base.mkdir(parents=True, exist_ok=True)

        db = create_connection(self._env)
        repo = XfanVideoRepository(db)
        videos = repo.find_all_active()
        self._log.info("共查询到 %d 条未删除视频记录", len(videos))

        if not videos:
            return []

        results: List[DownloadResult] = []
        for i, video in enumerate(videos, 1):
            self._log.info(
                "--- [%d/%d] id=%d  %s ---",
                i, len(videos), video.id, video.title,
            )
            r = self._download_one(video, base)
            results.append(r)
            self._log.info(str(r))

        self._print_summary(results)
        return results

    def _download_one(self, video: XfanVideo, base: Path) -> DownloadResult:
        """下载单个视频文件。"""
        result = DownloadResult(video_id=video.id, video_url=video.video_url)

        if not video.video_url:
            result.error = "video_url 为空"
            return result

        try:
            subfolder = _extract_subfolder(video.video_url)
            filename = Path(urlparse(video.video_url).path).name

            dest_dir = base / subfolder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / filename
            result.local_path = str(dest)

            # 已存在则跳过
            if dest.exists() and dest.stat().st_size > 0:
                result.success = True
                result.skipped = True
                result.size_bytes = dest.stat().st_size
                return result

            # 清理可能残留的临时文件
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            if tmp.exists():
                tmp.unlink()

            t0 = time.perf_counter()
            size = download_file(
                video.video_url,
                dest,
                timeout=self._timeout,
                chunk_size=self._chunk_size,
                logger=self._log,
            )
            elapsed = time.perf_counter() - t0

            result.success = True
            result.size_bytes = size
            result.elapsed_sec = elapsed

        except Exception as exc:
            result.error = str(exc)
            self._log.exception("下载 id=%d 时出错", video.id)

        return result

    def _print_summary(self, results: List[DownloadResult]) -> None:
        ok = [r for r in results if r.success and not r.skipped]
        skipped = [r for r in results if r.skipped]
        failed = [r for r in results if not r.success]

        total_bytes = sum(r.size_bytes for r in ok)
        total_mb = total_bytes / (1024 * 1024)

        sep = "-" * 72
        self._log.info(sep)
        self._log.info(
            "下载完成  成功 %d / 跳过 %d / 失败 %d / 共 %d  (%.1f MB)",
            len(ok), len(skipped), len(failed), len(results), total_mb,
        )
        if failed:
            self._log.warning("失败项:")
            for r in failed:
                self._log.warning("  id=%d  %s", r.video_id, r.error)
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
        prog="xfan_video_downloader",
        description="从 xfan_video 表批量下载视频到本地目录",
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
    parser.add_argument(
        "--chunk-size", type=int, default=8192,
        help="流式下载块大小（字节，默认 8192）",
    )

    args = parser.parse_args()

    downloader = XfanVideoDownloader(
        env=args.env,
        timeout=args.timeout,
        chunk_size=args.chunk_size,
    )
    results = downloader.run(args.output_dir)

    sys.exit(0 if all(r.success or r.skipped for r in results) else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # ===== 在这里填写参数 =====
        OUTPUT_DIR = r"E:\metaXsire\1、商业版APP\3、XFans\其他人物"
        ENV = "prod"
        TIMEOUT = 60
        CHUNK_SIZE = 8192
        # ==========================

        _setup_logging()
        dl = XfanVideoDownloader(env=ENV, timeout=TIMEOUT, chunk_size=CHUNK_SIZE)
        dl.run(OUTPUT_DIR)
