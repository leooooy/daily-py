"""小说资源批量上传工具。

扫描目录中同名的 .mp3 / .jpg / .txt 文件，上传到 S3 后同时写入
``recommond_table`` 和 ``media_resource`` 两张表。

文件名即标题（下划线替换为空格），例如::

    Melodies_of_the_Soul.mp3
    Melodies_of_the_Soul.jpg
    Melodies_of_the_Soul.txt

三个文件组成一条记录：
- .mp3 → media_resource.media_url  +  recommond_table.duration
- .jpg → media_resource.media_cover_url  +  recommond_table.poster  +  宽高
- .txt → recommond_table.novel_text_url

两表共享同一个 id（recommond_table 自增获取，media_resource 用同值字符串）。

Usage::

    python -m daily_py.services.recommond.novel_resource_batch_upload D:/novel_files --env prod

"""

from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from daily_py.db.config import create_connection
from daily_py.db.models.media_resource import MediaResource
from daily_py.db.models.recommond import Recommond
from daily_py.db.repositories.media_resource_repository import MediaResourceRepository
from daily_py.db.repositories.recommond_repository import RecommondRepository
from daily_py.image_handler import ImageHandler
from daily_py.s3.config import create_uploader


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

_SUPPORTED_EXTS: Set[str] = {".mp3", ".jpg", ".jpeg", ".png", ".txt"}


@dataclass
class UploadResult:
    """单组文件的处理结果。"""

    stem: str
    recommond_id: int = 0
    media_url: str = ""
    cover_url: str = ""
    text_url: str = ""
    success: bool = False
    skipped: bool = False
    error: str = ""

    def __str__(self) -> str:
        if self.success:
            return f"[OK]   {self.stem} → recommond_id={self.recommond_id}"
        if self.skipped:
            return f"[SKIP] {self.stem}  {self.error}"
        return f"[ERR]  {self.stem}  {self.error}"


def _stem_to_title(stem: str) -> str:
    """文件名 stem 转标题：下划线替换为空格。"""
    return stem.replace("_", " ")


# ---------------------------------------------------------------------------
# 上传器
# ---------------------------------------------------------------------------

class NovelResourceUploader:
    """批量上传小说资源（mp3 + jpg + txt）到 S3，并写入 recommond_table 和 media_resource。

    Parameters
    ----------
    env : str
        数据库环境，``"test"`` 或 ``"prod"``。
    s3_prefix : str
        S3 上传路径前缀，默认 ``"media_resource"``。
    """

    def __init__(
        self,
        env: str = "prod",
        *,
        s3_prefix: str = "media_resource",
    ) -> None:
        self._env = env
        self._s3_prefix = s3_prefix.strip("/")
        self._log = logging.getLogger(__name__)

    def run(self, input_dir: str, dry_run: bool = False) -> List[UploadResult]:
        """执行完整的批量上传流程。"""
        base = Path(input_dir)
        if not base.is_dir():
            raise NotADirectoryError(f"目录不存在：{input_dir}")

        # 按 stem 分组
        groups: Dict[str, Dict[str, Path]] = defaultdict(dict)
        for f in sorted(base.iterdir()):
            if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS:
                ext = f.suffix.lower()
                if ext in (".jpg", ".jpeg", ".png"):
                    groups[f.stem]["img"] = f
                elif ext == ".mp3":
                    groups[f.stem]["mp3"] = f
                elif ext == ".txt":
                    groups[f.stem]["txt"] = f

        self._log.info("在 %s 中找到 %d 组文件", input_dir, len(groups))

        if not groups:
            return []

        db = create_connection(self._env)
        recommond_repo = RecommondRepository(db)
        resource_repo = MediaResourceRepository(db)
        s3 = create_uploader()
        ih = ImageHandler()

        results: List[UploadResult] = []
        for i, (stem, files) in enumerate(sorted(groups.items()), 1):
            self._log.info("--- [%d/%d] %s ---", i, len(groups), stem)

            if "mp3" not in files:
                r = UploadResult(stem=stem, skipped=True, error="缺少 .mp3 文件")
                results.append(r)
                self._log.info(str(r))
                continue

            r = self._process_one(
                stem, files, recommond_repo, resource_repo, s3, ih, dry_run,
            )
            results.append(r)
            self._log.info(str(r))

        self._print_summary(results)
        return results

    def _process_one(
        self,
        stem: str,
        files: Dict[str, Path],
        recommond_repo: RecommondRepository,
        resource_repo: MediaResourceRepository,
        s3,
        ih: ImageHandler,
        dry_run: bool,
    ) -> UploadResult:
        result = UploadResult(stem=stem)
        title = _stem_to_title(stem)

        try:
            mp3_path: Path = files["mp3"]
            img_path: Optional[Path] = files.get("img")
            txt_path: Optional[Path] = files.get("txt")

            # ① 获取 mp3 时长（毫秒）
            duration_ms = int(ih.get_video_duration(mp3_path))
            self._log.info("  mp3 时长: %d ms", duration_ms)

            # ② 获取图片尺寸
            img_w = img_h = 0
            if img_path:
                img_w, img_h = ih.get_image_size(img_path)
                self._log.info("  图片尺寸: %dx%d", img_w, img_h)

            # ---- dry-run ----
            if dry_run:
                self._log.info(
                    "  [DRY] %s  duration=%dms  img=%s  txt=%s",
                    stem, duration_ms,
                    "YES" if img_path else "NO",
                    "YES" if txt_path else "NO",
                )
                result.success = True
                return result

            # ③ 上传 mp3
            mp3_key = f"{self._s3_prefix}/{mp3_path.name}"
            result.media_url = s3.upload_file(
                str(mp3_path), mp3_key, content_type="audio/mpeg",
            )
            self._log.info("  mp3 → %s", result.media_url)

            # ④ 上传图片
            if img_path:
                img_key = f"{self._s3_prefix}/{img_path.name}"
                ct = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"
                result.cover_url = s3.upload_file(str(img_path), img_key, content_type=ct)
                self._log.info("  img → %s", result.cover_url)

            # ⑤ 上传 txt
            if txt_path:
                txt_key = f"{self._s3_prefix}/{txt_path.name}"
                result.text_url = s3.upload_file(
                    str(txt_path), txt_key, content_type="text/plain",
                )
                self._log.info("  txt → %s", result.text_url)

            # ⑥ 插入 recommond_table（获取自增 id）
            recommond = Recommond(
                name=title,
                poster=result.cover_url or None,
                status=1,
                type="audio",
                duration=duration_ms,
                image_height=img_h,
                image_width=img_w,
                service_level_limits=0,
                deleted_flag=1,
                is_old_version=0,
                novel_text_url=result.text_url or None,
            )
            rec_id = recommond_repo.insert(recommond)
            result.recommond_id = rec_id
            self._log.info("  recommond_table id=%d", rec_id)

            # ⑦ 插入 media_resource（用同一 id）
            resource = MediaResource(
                id=str(rec_id),
                media_name=title,
                media_url=result.media_url,
                media_cover_url=result.cover_url or None,
                media_cover_height=img_h,
                media_cover_width=img_w,
                media_size=0,
                service_level_limits=0,
                media_category="audio",
                visibility="public",
                user_id="metaxsire",
                media_state=2,
                reward_token=0,
                likes_count=0,
                collection_count=0,
                provider_module="recommend:novel",
                deleted_flag=1,
                show_order=0,
                xgame_support=0,
                vr_mode=0,
                common=1,
            )
            resource_repo.insert(resource)
            self._log.info("  media_resource id=%s", rec_id)

            result.success = True

        except Exception as exc:
            result.error = str(exc)
            self._log.exception("处理 %s 时出错", stem)

        return result

    def _print_summary(self, results: List[UploadResult]) -> None:
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
                self._log.info("  %s  %s", r.stem, r.error)
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
        prog="novel_resource_batch_upload",
        description="批量上传小说资源（mp3+jpg+txt）到 S3 并写入 recommond_table 和 media_resource",
    )
    parser.add_argument("input_dir", help="包含 mp3/jpg/txt 文件的本地目录")
    parser.add_argument(
        "--env", default="prod", choices=["test", "prod"],
        help="数据库环境（默认 prod）",
    )
    parser.add_argument(
        "--s3-prefix", default="media_resource",
        help="S3 上传路径前缀（默认 media_resource）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="试运行，不实际上传和写库",
    )
    args = parser.parse_args()

    uploader = NovelResourceUploader(env=args.env, s3_prefix=args.s3_prefix)
    results = uploader.run(args.input_dir, dry_run=args.dry_run)
    sys.exit(0 if all(r.success or r.skipped for r in results) else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # ===== 在这里填写参数 =====
        INPUT_DIR = r"D:\novel_resources"
        ENV = "prod"
        S3_PREFIX = "media_resource"
        DRY_RUN = False
        # ==========================

        _setup_logging()
        NovelResourceUploader(env=ENV, s3_prefix=S3_PREFIX).run(INPUT_DIR, dry_run=DRY_RUN)
