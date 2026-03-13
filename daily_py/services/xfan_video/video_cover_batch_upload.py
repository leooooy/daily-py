"""xfan_video 批量上传工具。

遍历指定目录下的所有子文件夹，子文件夹命名格式为 ``{character_id}_{name}``
（如 ``1004_Cum_Zoya``，其中 character_id = 1004）。

每个子文件夹中，同名的 .mp4 / .jpg / .json 组成一条记录：
- .mp4 → video_url（奇数分辨率自动修复）
- .jpg → cover_url + cover_width / cover_height
- .json → instruct_url
- 所在文件夹名包含 "background"（不区分大小写）→ background = 1，否则 = 0

Usage::

    python -m daily_py.services.xfan_video.video_cover_batch_upload D:/xfan_files --env prod
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from daily_py.db.config import create_connection
from daily_py.db.models.xfan_video import XfanVideo
from daily_py.db.repositories.xfan_video_repository import XfanVideoRepository
from daily_py.image_handler import ImageHandler
from daily_py.s3.config import create_uploader
from daily_py.s3.uploader import S3Uploader


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class UploadResult:
    """单个视频文件的处理结果。"""

    stem: str
    character_id: int = 0
    background: int = 0
    success: bool = False
    video_id: int = 0
    video_url: str = ""
    cover_url: str = ""
    instruct_url: str = ""
    duration: int = 0
    error: str = ""

    def __str__(self) -> str:
        if self.success:
            bg_tag = " [BG]" if self.background else ""
            return (
                f"[OK]  {self.stem}{bg_tag}  id={self.video_id}"
                f"  char={self.character_id}  dur={self.duration}s"
            )
        return f"[ERR] {self.stem}  {self.error}"


def _parse_character_id(folder_name: str) -> Optional[int]:
    """从文件夹名提取 character_id，格式: {id}_{...}"""
    m = re.match(r"^(\d+)_", folder_name)
    return int(m.group(1)) if m else None


def _is_background_dir(dirname: str) -> bool:
    """判断文件夹名是否包含 background（不区分大小写）。"""
    return "background" in dirname.lower()


# ---------------------------------------------------------------------------
# 上传器
# ---------------------------------------------------------------------------

class XfanVideoUploader:
    """批量上传 xfan_video 记录。

    Parameters
    ----------
    env : str
        数据库环境。
    video_prefix : str
        视频文件的 S3 路径前缀。
    cover_prefix : str
        封面图片的 S3 路径前缀。
    instruct_prefix : str
        指令 JSON 的 S3 路径前缀。
    cover_time_sec : float or None
        封面截取时间点（秒）。None 表示不自动截帧，仅使用已有 .jpg。
    """

    def __init__(
        self,
        env: str = "prod",
        *,
        video_prefix: str = "xfan",
        cover_prefix: str = "xfan/cover",
        instruct_prefix: str = "xfan/instruct",
        cover_time_sec: Optional[float] = 1.0,
    ) -> None:
        self._env = env
        self._video_prefix = video_prefix.strip("/")
        self._cover_prefix = cover_prefix.strip("/")
        self._instruct_prefix = instruct_prefix.strip("/")
        self._cover_time = cover_time_sec
        self._log = logging.getLogger(__name__)

    def run(self, root_dir: str, dry_run: bool = False) -> List[UploadResult]:
        """执行完整的批量上传流程。"""
        root = Path(root_dir)
        if not root.is_dir():
            raise NotADirectoryError(f"目录不存在：{root_dir}")

        # 收集子文件夹
        subdirs = sorted(
            [d for d in root.iterdir() if d.is_dir()],
            key=lambda d: d.name,
        )
        self._log.info("在 %s 下找到 %d 个子文件夹", root_dir, len(subdirs))

        if not subdirs:
            return []

        db = create_connection(self._env)
        repo = XfanVideoRepository(db)
        s3 = create_uploader()
        ih = ImageHandler()

        all_results: List[UploadResult] = []

        for di, sub in enumerate(subdirs, 1):
            character_id = _parse_character_id(sub.name)
            if character_id is None:
                self._log.warning(
                    "[%d/%d] 跳过 %s — 无法解析 character_id",
                    di, len(subdirs), sub.name,
                )
                continue

            self._log.info(
                "===== [%d/%d] %s  character_id=%d =====",
                di, len(subdirs), sub.name, character_id,
            )

            results = self._process_folder(sub, character_id, repo, s3, ih, dry_run)
            all_results.extend(results)

        self._print_summary(all_results)
        return all_results

    def _process_folder(
        self,
        folder: Path,
        character_id: int,
        repo: XfanVideoRepository,
        s3: S3Uploader,
        ih: ImageHandler,
        dry_run: bool,
    ) -> List[UploadResult]:
        """处理单个子文件夹下的所有 mp4 文件。

        - 子文件夹根目录下的 mp4 → background=0
        - 名称包含 "background" 的子子文件夹下的 mp4 → background=1
        """
        results: List[UploadResult] = []

        # 根目录下的 mp4 → background=0
        mp4_files = sorted(folder.glob("*.mp4"))
        if mp4_files:
            self._log.info("  找到 %d 个普通 mp4 文件", len(mp4_files))
            for mp4 in mp4_files:
                r = self._process_one(mp4, character_id, 0, repo, s3, ih, dry_run)
                results.append(r)
                self._log.info("  %s", r)

        # 名称包含 background 的子文件夹 → background=1
        for sub in sorted(folder.iterdir()):
            if sub.is_dir() and _is_background_dir(sub.name):
                bg_mp4s = sorted(sub.glob("*.mp4"))
                if bg_mp4s:
                    self._log.info("  [BG] %s 下找到 %d 个 mp4 文件", sub.name, len(bg_mp4s))
                    for mp4 in bg_mp4s:
                        r = self._process_one(mp4, character_id, 1, repo, s3, ih, dry_run)
                        results.append(r)
                        self._log.info("  %s", r)

        if not results:
            self._log.info("  无 mp4 文件，跳过")

        return results

    def _process_one(
        self,
        mp4_path: Path,
        character_id: int,
        background: int,
        repo: XfanVideoRepository,
        s3: S3Uploader,
        ih: ImageHandler,
        dry_run: bool,
    ) -> UploadResult:
        stem = mp4_path.stem
        result = UploadResult(
            stem=stem,
            character_id=character_id,
            background=background,
        )

        jpg_path = mp4_path.with_suffix(".jpg")
        json_path = mp4_path.with_suffix(".json")
        timings: Dict[str, float] = {}

        def _t(label: str, fn, *args, **kwargs):
            t0 = time.perf_counter()
            ret = fn(*args, **kwargs)
            timings[label] = time.perf_counter() - t0
            return ret

        try:
            # ⓪ 修复奇数分辨率
            if dry_run:
                vw, vh = _t("⓪检查尺寸", ih.get_video_size, mp4_path)
                if vw % 2 != 0 or vh % 2 != 0:
                    self._log.warning(
                        "  ⓪ %s 尺寸含奇数（%dx%d），实际上传时将自动修复",
                        stem, vw, vh,
                    )
            else:
                _t("⓪修复尺寸", ih.ensure_even_dimensions, mp4_path)

            # ① 获取视频时长
            duration_f = _t("①时长", ih.get_video_duration, mp4_path)
            duration = max(0, int(duration_f))
            result.duration = duration

            # ② 封面处理
            cover_w = cover_h = 0
            cover_tmp: Optional[Path] = None

            if jpg_path.exists():
                cover_tmp = jpg_path
                cover_w, cover_h = _t("②封面尺寸", ih.get_image_size, cover_tmp)
            elif self._cover_time is not None:
                cover_tmp = mp4_path.parent / f"{stem}.jpg"
                cover_at = (
                    min(self._cover_time, max(0.0, duration_f * 0.1))
                    if duration_f > 0 else 0.0
                )
                _t("②截帧", ih.extract_frame, mp4_path, cover_at, output_path=cover_tmp)
                cover_w, cover_h = _t("②封面尺寸", ih.get_image_size, cover_tmp)

            # ---- dry-run 模式 ----
            if dry_run:
                bg_tag = " [BG]" if background else ""
                result.video_url = f"[dry-run] {self._video_prefix}/{mp4_path.name}"
                result.success = True
                self._log.info(
                    "  [DRY] %s%s  char=%d  dur=%ds  cover=%s  json=%s",
                    stem, bg_tag, character_id, duration,
                    "YES" if cover_tmp else "NO",
                    "YES" if json_path.exists() else "NO",
                )
                return result

            # ③ 上传 .mp4
            video_key = f"{self._video_prefix}/{mp4_path.name}"
            result.video_url = _t(
                "③上传mp4",
                s3.upload_file, str(mp4_path), video_key, content_type="video/mp4",
            )

            # ④ 上传 .jpg 封面（可选）
            if cover_tmp is not None and cover_tmp.exists():
                cover_key = f"{self._cover_prefix}/{stem}.jpg"
                result.cover_url = _t(
                    "④上传封面",
                    s3.upload_file, str(cover_tmp), cover_key, content_type="image/jpeg",
                )

            # ⑤ 上传 .json 指令（可选）
            if json_path.exists():
                json_key = f"{self._instruct_prefix}/{json_path.name}"
                result.instruct_url = _t(
                    "⑤上传json",
                    s3.upload_file, str(json_path), json_key, content_type="application/json",
                )

            # ⑥ 写入数据库
            video = XfanVideo(
                user_id="public",
                character_id=character_id,
                service_level_limits=3,
                price=0,
                title="",
                video_url=result.video_url,
                instruct_url=result.instruct_url,
                cover_url=result.cover_url or None,
                cover_width=cover_w,
                cover_height=cover_h,
                duration=duration,
                background=background,
                deleted_flag=1,
            )
            result.video_id = _t("⑥写DB", repo.insert, video)
            result.success = True

        except Exception as exc:
            result.error = str(exc)
            self._log.exception("  处理 %s 时出错", mp4_path.name)

        self._log_timings(stem, timings)
        return result

    def _log_timings(self, stem: str, timings: Dict[str, float]) -> None:
        if not timings:
            return
        total = sum(timings.values())
        if total == 0:
            return
        bottleneck = max(timings, key=timings.__getitem__)
        parts = "  ".join(f"{k} {v:.1f}s ({v / total * 100:.0f}%)" for k, v in timings.items())
        self._log.info("  ⏱ %s | 总计 %.1fs | 瓶颈: %s  ||  %s", stem, total, bottleneck, parts)

    def _print_summary(self, results: List[UploadResult]) -> None:
        ok = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        bg_count = sum(1 for r in ok if r.background)
        normal_count = len(ok) - bg_count

        sep = "=" * 72
        self._log.info(sep)
        self._log.info(
            "处理完成  成功 %d（普通 %d + Background %d）/ 失败 %d / 共 %d",
            len(ok), normal_count, bg_count, len(failed), len(results),
        )
        if failed:
            self._log.warning("失败项:")
            for r in failed:
                self._log.warning("  %s  %s", r.stem, r.error)
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
        prog="xfan_video_uploader",
        description="批量上传 xfan_video 记录（mp4 + jpg + json）",
    )
    parser.add_argument("root_dir", help="包含子文件夹的根目录")
    parser.add_argument(
        "--env", default="prod", choices=["test", "prod"],
        help="数据库环境（默认 prod）",
    )
    parser.add_argument("--dry-run", action="store_true", help="试运行，不实际上传和写库")
    parser.add_argument("--video-prefix", default="xfan", help="S3 视频前缀（默认 xfan）")
    parser.add_argument("--cover-prefix", default="xfan/cover", help="S3 封面前缀（默认 xfan/cover）")
    parser.add_argument("--instruct-prefix", default="xfan/instruct", help="S3 指令前缀（默认 xfan/instruct）")

    args = parser.parse_args()

    uploader = XfanVideoUploader(
        env=args.env,
        video_prefix=args.video_prefix,
        cover_prefix=args.cover_prefix,
        instruct_prefix=args.instruct_prefix,
    )
    results = uploader.run(args.root_dir, dry_run=args.dry_run)
    sys.exit(0 if all(r.success for r in results) else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # ===== 在这里填写参数 =====
        ROOT_DIR = r"D:\ftp\260309\33"
        ENV = "prod"
        DRY_RUN = False
        # ==========================

        _setup_logging()
        XfanVideoUploader(env=ENV).run(ROOT_DIR, dry_run=DRY_RUN)
