"""媒体视频批量上传工具。

工作流（每个 .mp4 文件）：

1. 在同目录查找同名 .json → media_instruct_url（可选）
2. 用 ImageHandler 获取视频时长 → duration
3. 截取封面帧 → 上传 S3 → media_cover_url / media_cover_width / media_cover_height
4. 上传 .mp4 → S3 → media_url
5. 上传 .json → S3 → media_instruct_url
6. 构造 MediaVideo 并插入数据库

Example::

    from daily_py.db.config import create_connection
    from daily_py.db.repositories.media_video_repository import MediaVideoRepository
    from daily_py.s3.config import create_uploader
    from daily_py.media_video_uploader import MediaVideoUploader

    db   = create_connection("prod")
    repo = MediaVideoRepository(db)
    s3   = create_uploader()

    uploader = MediaVideoUploader(repo, s3)
    results  = uploader.upload_folder("D:/videos", recursive=True)
    for r in results:
        print(r)
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .db.models.media_video import MediaVideo
from .db.repositories.media_video_repository import MediaVideoRepository
from .image_handler import ImageHandler
from .s3.uploader import S3Uploader


@dataclass
class UploadResult:
    """单个视频文件的处理结果。"""

    stem: str                   # 文件名（不含扩展）
    success: bool
    media_id: int = 0           # DB 自增 ID（失败时为 0）
    media_url: str = ""
    media_instruct_url: str = ""
    media_cover_url: str = ""
    duration: int = 0           # 秒
    error: str = ""

    def __str__(self) -> str:
        if self.success:
            return (
                f"[OK]  {self.stem}  id={self.media_id}"
                f"  dur={self.duration}s  url={self.media_url}"
            )
        return f"[ERR] {self.stem}  {self.error}"


class MediaVideoUploader:
    """批量将本地视频上传到 S3 并写入 media_video 表。

    配对规则
    --------
    - 同目录下同名的 ``.mp4`` 和 ``.json`` 组成一对。
    - ``.json`` 为可选；缺失时 ``media_instruct_url`` 留空。

    S3 前缀
    -------
    - 视频  → ``{video_prefix}/{filename}.mp4``
    - 指令  → ``{json_prefix}/{filename}.json``
    - 封面  → ``{cover_prefix}/{stem}.jpg``
    """

    def __init__(
        self,
        repo: MediaVideoRepository,
        uploader: S3Uploader,
        image_handler: Optional[ImageHandler] = None,
        *,
        video_prefix: str = "media_video",
        json_prefix: str = "media_instruct",
        cover_prefix: str = "media_cover",
        cover_time_sec: float = 1.0,
        default_type: int = 0,
        default_show_status: int = 1,
        default_service_level_limits: int = 0,
        default_common: Optional[int] = None,
    ) -> None:
        self._repo = repo
        self._s3 = uploader
        self._ih = image_handler or ImageHandler()
        self._video_prefix = video_prefix.rstrip("/")
        self._json_prefix = json_prefix.rstrip("/")
        self._cover_prefix = cover_prefix.rstrip("/")
        self._cover_time = cover_time_sec
        self._default_type = default_type
        self._default_show_status = default_show_status
        self._default_service_level_limits = default_service_level_limits
        self._default_common = default_common
        self._log = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def upload_folder(
        self,
        folder: str,
        recursive: bool = False,
        dry_run: bool = False,
    ) -> List[UploadResult]:
        """扫描目录，处理所有 .mp4 文件并返回结果列表。

        Args:
            folder: 本地目录路径。
            recursive: 是否递归子目录。
            dry_run: 试运行模式，不实际上传也不写数据库，仅打印会执行的操作。

        Returns:
            每个 .mp4 文件对应一个 :class:`UploadResult`。
        """
        base = Path(folder)
        if not base.is_dir():
            raise NotADirectoryError(f"目录不存在: {folder}")

        pattern = "**/*.mp4" if recursive else "*.mp4"
        mp4_files = sorted(base.glob(pattern))

        if not mp4_files:
            self._log.warning("目录 %s 中未找到 .mp4 文件", folder)
            return []

        self._log.info("共找到 %d 个 .mp4 文件（recursive=%s, dry_run=%s）",
                       len(mp4_files), recursive, dry_run)

        results: List[UploadResult] = []
        for mp4 in mp4_files:
            json_path = mp4.with_suffix(".json")
            r = self._process_one(mp4, json_path if json_path.exists() else None, dry_run=dry_run)
            results.append(r)
            self._log.info(str(r))

        ok = sum(1 for r in results if r.success)
        self._log.info("完成：%d 成功 / %d 失败", ok, len(results) - ok)
        return results

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _process_one(
        self,
        mp4_path: Path,
        json_path: Optional[Path],
        dry_run: bool = False,
    ) -> UploadResult:
        stem = mp4_path.stem
        result = UploadResult(stem=stem, success=False)
        timings: Dict[str, float] = {}

        def _t(label: str, fn, *args, **kwargs):
            t0 = time.perf_counter()
            ret = fn(*args, **kwargs)
            timings[label] = time.perf_counter() - t0
            return ret

        try:
            # ① 获取视频时长
            duration_f = _t("①时长", self._ih.get_video_duration, mp4_path)
            duration = max(0, int(duration_f))
            result.duration = duration

            # ② 截取封面帧
            cover_at = min(self._cover_time, max(0.0, duration_f * 0.1)) if duration_f > 0 else 0.0
            cover_tmp = mp4_path.parent / f"{stem}.jpg"
            _t("②截帧", self._ih.extract_frame, mp4_path, cover_at, output_path=cover_tmp)

            # ③ 获取封面尺寸
            cover_w, cover_h = _t("③封面尺寸", self._ih.get_image_size, cover_tmp)

            # ---- dry-run ----
            if dry_run:
                result.media_url = f"[dry-run] {self._video_prefix}/{mp4_path.name}"
                result.media_instruct_url = (
                    f"[dry-run] {self._json_prefix}/{mp4_path.stem}.json"
                    if json_path else ""
                )
                result.media_cover_url = f"[dry-run] {self._cover_prefix}/{stem}.jpg"
                result.success = True
                self._log_timings(stem, timings)
                return result

            # ④ 上传 .mp4
            video_key = f"{self._video_prefix}/{mp4_path.name}"
            result.media_url = _t(
                "④上传mp4",
                self._s3.upload_file, str(mp4_path), video_key, content_type="video/mp4",
            )

            # ⑤ 上传 .json（可选）
            if json_path:
                json_key = f"{self._json_prefix}/{json_path.name}"
                result.media_instruct_url = _t(
                    "⑤上传json",
                    self._s3.upload_file, str(json_path), json_key, content_type="application/json",
                )

            # ⑥ 上传封面
            cover_key = f"{self._cover_prefix}/{stem}.jpg"
            result.media_cover_url = _t(
                "⑥上传封面",
                self._s3.upload_file, str(cover_tmp), cover_key, content_type="image/jpeg",
            )

            # ⑦ 写入数据库
            video = MediaVideo(
                media_name=stem,
                media_url=result.media_url,
                media_instruct_url=result.media_instruct_url,
                media_cover_url=result.media_cover_url,
                media_cover_width=cover_w,
                media_cover_height=cover_h,
                duration=duration,
                type=self._default_type,
                service_level_limits=self._default_service_level_limits,
                show_status=self._default_show_status,
                common=self._default_common,
                app_version_type=1,
                deleted_flag=1,
            )
            result.media_id = _t("⑦写DB", self._repo.insert, video)
            result.success = True

        except Exception as exc:
            result.error = str(exc)
            self._log.exception("处理 %s 时出错", mp4_path.name)

        self._log_timings(stem, timings)
        return result

    def _log_timings(self, stem: str, timings: Dict[str, float]) -> None:
        if not timings:
            return
        total = sum(timings.values())
        if total == 0:
            return
        bottleneck = max(timings, key=timings.__getitem__)
        parts = "  ".join(f"{k} {v:.1f}s ({v/total*100:.0f}%)" for k, v in timings.items())
        self._log.info(
            "⏱ %s | 总计 %.1fs | 瓶颈: %s  ||  %s",
            stem, total, bottleneck, parts,
        )
