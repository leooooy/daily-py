"""novel 表批量上传工具。

扫描目录中同名的 .txt / .jpg / .mp3 文件，上传到 S3 后写入 ``novel`` 表。

三种文件必须齐全才会处理，缺少任一类型则跳过该组。
文件名格式为 ``{id}_{title}``，下划线前的数字为 novel.id，其余部分为标题
（下划线替换为空格），例如::

    73_Love's_Masterpiece_in_Paint_and_Prose.mp3
    73_Love's_Masterpiece_in_Paint_and_Prose.jpg
    73_Love's_Masterpiece_in_Paint_and_Prose.txt

→ id=73, title="Love's Masterpiece in Paint and Prose"

Usage::

    python -m daily_py.services.novel.novel_batch_upload D:/novel_files --env prod

"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from daily_py.db.config import create_connection
from daily_py.db.models.novel import Novel
from daily_py.db.repositories.novel_repository import NovelRepository
from daily_py.image_handler import ImageHandler
from daily_py.s3.config import create_uploader


_SUPPORTED_EXTS: Set[str] = {".mp3", ".jpg", ".jpeg", ".png", ".txt"}


@dataclass
class UploadResult:
    """单组文件的处理结果。"""

    stem: str
    novel_id: int = 0
    cover_url: str = ""
    audio_url: str = ""
    success: bool = False
    skipped: bool = False
    error: str = ""

    def __str__(self) -> str:
        if self.success:
            return f"[OK]   {self.stem} → novel_id={self.novel_id}"
        if self.skipped:
            return f"[SKIP] {self.stem}  {self.error}"
        return f"[ERR]  {self.stem}  {self.error}"


def _parse_stem(stem: str) -> Tuple[Optional[int], str]:
    """解析文件名 stem，格式: {id}_{title}。

    例如 ``73_Love's_Masterpiece_in_Paint_and_Prose``
    返回 ``(73, "Love's Masterpiece in Paint and Prose")``。
    """
    m = re.match(r"^(\d+)_(.+)$", stem)
    if m:
        return int(m.group(1)), m.group(2).replace("_", " ")
    return None, stem.replace("_", " ")


class NovelBatchUploader:
    """批量上传小说资源（txt + jpg + mp3）到 S3，并写入 novel 表。

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
        service_level_limits: int = 0,
    ) -> None:
        self._env = env
        self._s3_prefix = s3_prefix.strip("/")
        self._service_level_limits = service_level_limits
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
        novel_repo = NovelRepository(db)
        s3 = create_uploader()
        ih = ImageHandler()

        results: List[UploadResult] = []
        for i, (stem, files) in enumerate(sorted(groups.items()), 1):
            self._log.info("--- [%d/%d] %s ---", i, len(groups), stem)

            # 三种文件必须齐全
            missing = []
            if "txt" not in files:
                missing.append(".txt")
            if "img" not in files:
                missing.append(".jpg/.png")
            if "mp3" not in files:
                missing.append(".mp3")
            if missing:
                r = UploadResult(
                    stem=stem, skipped=True,
                    error=f"缺少文件: {', '.join(missing)}",
                )
                results.append(r)
                self._log.info(str(r))
                continue

            r = self._process_one(stem, files, novel_repo, s3, ih, dry_run)
            results.append(r)
            self._log.info(str(r))

        self._print_summary(results)
        return results

    def _insert_with_id(self, novel_repo: NovelRepository, novel: Novel) -> int:
        """插入记录并指定 id（不依赖自增）。"""
        data = novel.to_dict()
        skip = {"create_time", "update_time"}
        fields = [k for k in data if k not in skip]
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        sql = f"INSERT INTO {novel_repo.table_name} ({columns}) VALUES ({placeholders})"
        values = tuple(data[f] for f in fields)
        with novel_repo._db.cursor() as cur:
            cur.execute(sql, values)
            return novel.id

    def _process_one(
        self,
        stem: str,
        files: Dict[str, Path],
        novel_repo: NovelRepository,
        s3,
        ih: ImageHandler,
        dry_run: bool,
    ) -> UploadResult:
        result = UploadResult(stem=stem)
        novel_id, title = _parse_stem(stem)

        if novel_id is None:
            result.skipped = True
            result.error = "文件名无法解析 id（需 {id}_{title} 格式）"
            return result

        try:
            txt_path: Path = files["txt"]
            img_path: Path = files["img"]
            mp3_path: Path = files["mp3"]

            self._log.info("  id=%d  title=%s", novel_id, title)

            # ① 读取 txt 内容
            content = txt_path.read_text(encoding="utf-8")
            self._log.info("  txt 字符数: %d", len(content))

            # ② 获取图片尺寸
            img_w, img_h = ih.get_image_size(img_path)
            self._log.info("  图片尺寸: %dx%d", img_w, img_h)

            # ---- dry-run ----
            if dry_run:
                self._log.info(
                    "  [DRY] id=%d  title=%s  txt=%d chars  img=%dx%d  mp3=%s",
                    novel_id, title, len(content), img_w, img_h, mp3_path.name,
                )
                result.success = True
                result.novel_id = novel_id
                return result

            # ③ 上传图片到 S3
            img_key = f"{self._s3_prefix}/{img_path.name}"
            ct = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"
            result.cover_url = s3.upload_file(str(img_path), img_key, content_type=ct)
            self._log.info("  img → %s", result.cover_url)

            # ④ 上传 mp3 到 S3
            mp3_key = f"{self._s3_prefix}/{mp3_path.name}"
            result.audio_url = s3.upload_file(
                str(mp3_path), mp3_key, content_type="audio/mpeg",
            )
            self._log.info("  mp3 → %s", result.audio_url)

            # ⑤ 插入 novel 表（指定 id）
            novel = Novel(
                id=novel_id,
                title=title,
                content=content,
                cover=result.cover_url,
                cover_width=img_w,
                cover_height=img_h,
                audio_url=result.audio_url,
                service_level_limits=self._service_level_limits,
                deleted_flag=1,
            )
            self._insert_with_id(novel_repo, novel)
            result.novel_id = novel_id
            self._log.info("  novel id=%d", novel_id)

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
        prog="novel_batch_upload",
        description="批量上传小说资源（txt+jpg+mp3）到 S3 并写入 novel 表",
    )
    parser.add_argument("input_dir", help="包含 txt/jpg/mp3 文件的本地目录")
    parser.add_argument(
        "--env", default="prod", choices=["test", "prod"],
        help="数据库环境（默认 prod）",
    )
    parser.add_argument(
        "--s3-prefix", default="media_resource/novel",
        help="S3 上传路径前缀（默认 media_resource/novel）",
    )
    parser.add_argument(
        "--service-level-limits", type=int, default=0,
        help="服务等级限制，数字越大限制级越高（默认 0）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="试运行，不实际上传和写库",
    )
    args = parser.parse_args()

    uploader = NovelBatchUploader(
        env=args.env, s3_prefix=args.s3_prefix,
        service_level_limits=args.service_level_limits,
    )
    results = uploader.run(args.input_dir, dry_run=args.dry_run)
    sys.exit(0 if all(r.success or r.skipped for r in results) else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # ===== 在这里填写参数 =====
        INPUT_DIR = r"Z:\NS资料\1.metaXsire内容-正常\1、商业版APP\5.小说\3.12-0级小说（待上传）"
        ENV = "prod"
        S3_PREFIX = "media_resource/novel"
        SERVICE_LEVEL_LIMITS = 0
        DRY_RUN = False
        # ==========================

        _setup_logging()
        NovelBatchUploader(
            env=ENV, s3_prefix=S3_PREFIX,
            service_level_limits=SERVICE_LEVEL_LIMITS,
        ).run(INPUT_DIR, dry_run=DRY_RUN)
