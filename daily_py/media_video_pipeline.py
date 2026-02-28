"""媒体视频上传流水线 — 真实环境一键运行。

整合 DBConnection、MediaVideoRepository、S3Uploader、ImageHandler、
MediaVideoUploader，无需手动组装依赖。

Example::

    from daily_py.media_video_pipeline import MediaVideoPipeline

    # 测试环境（默认）
    pipeline = MediaVideoPipeline(env="test")
    results  = pipeline.run("D:/videos")

    # 生产环境
    pipeline = MediaVideoPipeline(env="prod")
    results  = pipeline.run("D:/videos", recursive=True)

    # 试运行（不实际上传，只打印将要执行的操作）
    results  = pipeline.run("D:/videos", dry_run=True)

CLI::

    python -m daily_py.media_video_pipeline D:/videos --env test --recursive
"""

import logging
import sys
from typing import List, Optional


from .media_video_uploader import MediaVideoUploader, UploadResult


def _setup_logging() -> None:
    """配置简洁的控制台日志，若根 logger 已有 handler 则跳过。"""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s",
                                           datefmt="%H:%M:%S"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


class MediaVideoPipeline:
    """真实上传流水线——自动从配置文件读取 DB / S3 凭证，无需手动传参。

    Parameters
    ----------
    env:
        数据库环境，``"test"``（内网 192.168.0.200）或 ``"prod"``（AWS RDS）。
    video_prefix:
        S3 中视频文件的路径前缀，默认 ``"media_video"``。
    json_prefix:
        S3 中指令 JSON 的路径前缀，默认 ``"media_instruct"``。
    cover_prefix:
        S3 中封面图的路径前缀，默认 ``"media_cover"``。
    cover_time_sec:
        截取封面的时间点（秒），实际取 ``min(cover_time_sec, duration * 10%)``，默认 ``1.0``。
    default_type:
        写入 DB 时 ``media_video.type`` 的默认值，默认 ``0``。
    default_show_status:
        写入 DB 时 ``media_video.show_status`` 的默认值，默认 ``1``（显示）。
    default_service_level_limits:
        写入 DB 时 ``media_video.service_level_limits`` 的默认值，默认 ``0``。
    default_common:
        写入 DB 时 ``media_video.common`` 的默认值，默认 ``None``（NULL）。
    """

    def __init__(
        self,
        env: str = "test",
        *,
        video_prefix: str = "media_video",
        json_prefix: str = "media_instruct",
        cover_prefix: str = "media_cover",
        cover_time_sec: Optional[float] = 1.0,
        default_type: int = 0,
        default_show_status: int = 1,
        default_service_level_limits: int = 0,
        default_common: Optional[int] = None,
        toy_models: Optional[List[str]] = None,
    ) -> None:
        _setup_logging()
        self._env = env
        self._toy_models = toy_models or []
        self._uploader_kwargs = dict(
            video_prefix=video_prefix,
            json_prefix=json_prefix,
            cover_prefix=cover_prefix,
            cover_time_sec=cover_time_sec,
            default_type=default_type,
            default_show_status=default_show_status,
            default_service_level_limits=default_service_level_limits,
            default_common=default_common,
        )
        self._log = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def run(
        self,
        folder: str,
        recursive: bool = False,
        dry_run: bool = False,
    ) -> List[UploadResult]:
        """执行完整上传流程。

        Parameters
        ----------
        folder:
            包含 .mp4（以及可选的同名 .json）的本地目录。
        recursive:
            是否递归扫描子目录。
        dry_run:
            试运行，只扫描文件、截取封面、打印将要执行的操作，
            不实际上传到 S3，也不写数据库。

        Returns
        -------
        List[UploadResult]
            每个 .mp4 对应一条结果记录。
        """
        from .db.config import create_connection
        from .db.repositories.media_video_repository import MediaVideoRepository
        from .image_handler import ImageHandler
        from .s3.config import create_uploader

        self._log.info("=" * 60)
        self._log.info("MediaVideoPipeline  env=%-6s  dry_run=%s", self._env, dry_run)
        self._log.info("folder: %s  (recursive=%s)", folder, recursive)
        self._log.info("=" * 60)

        # 组装依赖
        db = create_connection(self._env)
        self._log.info("DB  → %s", db.env_info)

        s3 = create_uploader()
        self._log.info("S3  → bucket=%s  base_url=%s", s3._bucket, s3._base_url)

        ih = ImageHandler()
        repo = MediaVideoRepository(db)

        toy_model_repo = None
        if self._toy_models:
            from .db.repositories.toy_model_video_repository import ToyModelVideoRepository
            toy_model_repo = ToyModelVideoRepository(db)

        uploader = MediaVideoUploader(
            repo, s3, ih,
            toy_model_repo=toy_model_repo,
            toy_models=self._toy_models,
            **self._uploader_kwargs,
        )

        # 执行上传
        results = uploader.upload_folder(folder, recursive=recursive, dry_run=dry_run)

        # 打印汇总
        self._print_summary(results, dry_run=dry_run)
        return results

    # ------------------------------------------------------------------
    # 格式化输出
    # ------------------------------------------------------------------

    @staticmethod
    def _print_summary(results: List[UploadResult], dry_run: bool = False) -> None:
        if not results:
            print("\n  （未找到任何 .mp4 文件）")
            return

        ok    = [r for r in results if r.success]
        fails = [r for r in results if not r.success]
        tag   = "  [DRY-RUN]" if dry_run else ""

        sep = "─" * 72
        print(f"\n{sep}")
        print(f"  上传完成{tag}   成功 {len(ok)} / 失败 {len(fails)} / 共 {len(results)}")
        print(sep)

        # 成功项
        for r in ok:
            print(f"  ✓  {r.stem:<30}  dur={r.duration:>4}s  id={r.media_id}")
            print(f"       媒体:  {r.media_url}")
            if r.media_instruct_url:
                print(f"       指令:  {r.media_instruct_url}")
            print(f"       封面:  {r.media_cover_url}")

        # 失败项
        if fails:
            print(f"\n  失败项：")
            for r in fails:
                print(f"  ✗  {r.stem:<30}  {r.error}")

        print(sep)


# ---------------------------------------------------------------------------
# CLI 入口：python -m daily_py.media_video_pipeline <folder> [options]
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="media_video_pipeline",
        description="批量上传本地视频文件夹到 S3 并写入数据库",
    )
    parser.add_argument("folder", help="包含 .mp4 文件的本地目录")
    parser.add_argument("--env", default="test", choices=["test", "prod"],
                        help="数据库环境（默认 test）")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="递归扫描子目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="试运行，不实际上传也不写库")
    parser.add_argument("--video-prefix",  default="media_video")
    parser.add_argument("--json-prefix",   default="media_instruct")
    parser.add_argument("--cover-prefix",  default="media_cover")
    parser.add_argument("--cover-time",    type=float, default=1.0,
                        help="截取封面的时间点（秒，默认 1.0）")
    parser.add_argument("--type",          type=int, default=0,
                        dest="default_type", help="media_video.type 默认值")
    parser.add_argument("--show-status",   type=int, default=1,
                        dest="default_show_status")

    args = parser.parse_args()

    pipeline = MediaVideoPipeline(
        env=args.env,
        video_prefix=args.video_prefix,
        json_prefix=args.json_prefix,
        cover_prefix=args.cover_prefix,
        cover_time_sec=args.cover_time,
        default_type=args.default_type,
        default_show_status=args.default_show_status,
    )
    results = pipeline.run(
        args.folder,
        recursive=args.recursive,
        dry_run=args.dry_run,
    )
    # 有失败项时以非零状态码退出，方便 CI 感知
    sys.exit(0 if all(r.success for r in results) else 1)


if __name__ == "__main__":
    _main()
