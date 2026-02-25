"""单元测试 — MediaVideoUploader（全 mock，无真实 S3 / DB / ffprobe 调用）。"""

import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# 注入 mysql / boto3 stub（无需真实驱动）
# ---------------------------------------------------------------------------
if "mysql" not in sys.modules:
    _mysql = types.ModuleType("mysql")
    _connector = types.ModuleType("mysql.connector")
    _connector.connect = MagicMock()  # type: ignore[attr-defined]
    _mysql.connector = _connector  # type: ignore[attr-defined]
    sys.modules["mysql"] = _mysql
    sys.modules["mysql.connector"] = _connector

if "boto3" not in sys.modules:
    _boto3 = types.ModuleType("boto3")
    _boto3.client = MagicMock()  # type: ignore[attr-defined]
    sys.modules["boto3"] = _boto3

if "botocore" not in sys.modules:
    _botocore = types.ModuleType("botocore")
    _botocore_exc = types.ModuleType("botocore.exceptions")
    class _CE(Exception):
        def __init__(self, r, op="op"):
            self.response = r
            super().__init__(str(r))
    _botocore_exc.ClientError = _CE  # type: ignore[attr-defined]
    _botocore.exceptions = _botocore_exc  # type: ignore[attr-defined]
    sys.modules["botocore"] = _botocore
    sys.modules["botocore.exceptions"] = _botocore_exc

from daily_py.db.models.media_video import MediaVideo
from daily_py.db.repositories.media_video_repository import MediaVideoRepository
from daily_py.image_handler import ImageHandler
from daily_py.media_video_uploader import MediaVideoUploader, UploadResult
from daily_py.s3.uploader import S3Uploader


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_uploader(**kwargs) -> tuple:
    """返回 (MediaVideoUploader, mock_repo, mock_s3, mock_ih)。"""
    mock_repo = MagicMock(spec=MediaVideoRepository)
    mock_repo.insert.return_value = 42

    mock_s3 = MagicMock(spec=S3Uploader)
    # 上传后返回形如 https://cdn.metaxsire.com/{key} 的 URL
    mock_s3.upload_file.side_effect = (
        lambda path, key, **kw: f"https://cdn.metaxsire.com/{key}"
    )

    mock_ih = MagicMock(spec=ImageHandler)
    mock_ih.get_video_duration.return_value = 120.5   # 120 秒
    mock_ih.get_image_size.return_value = (1920, 1080)

    uploader = MediaVideoUploader(mock_repo, mock_s3, mock_ih, **kwargs)
    return uploader, mock_repo, mock_s3, mock_ih


# ---------------------------------------------------------------------------
# 主流程测试
# ---------------------------------------------------------------------------

class TestUploadFolder(unittest.TestCase):

    def test_mp4_and_json_pair(self):
        """同名 .mp4 + .json 都应被上传，DB 插入一次。"""
        uploader, mock_repo, mock_s3, mock_ih = _make_uploader()

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "video1.mp4").write_bytes(b"fake")
            (Path(tmpdir) / "video1.json").write_text("{}")

            results = uploader.upload_folder(tmpdir)

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertTrue(r.success, r.error)
        self.assertEqual(r.stem, "video1")
        self.assertEqual(r.media_id, 42)
        self.assertEqual(r.duration, 120)

        # 三次上传：mp4 / json / cover
        self.assertEqual(mock_s3.upload_file.call_count, 3)
        uploaded_keys = {c[0][1] for c in mock_s3.upload_file.call_args_list}
        self.assertIn("media_video/video1.mp4", uploaded_keys)
        self.assertIn("media_instruct/video1.json", uploaded_keys)
        self.assertIn("media_cover/video1.jpg", uploaded_keys)

        # 封面截取的 output_path 应与 .mp4 同级（video1.jpg）
        frame_kwargs = mock_ih.extract_frame.call_args[1]
        cover_out = Path(frame_kwargs["output_path"])
        self.assertEqual(cover_out.name, "video1.jpg")
        self.assertEqual(cover_out.parent, Path(tmpdir))

        # URL 格式正确
        self.assertEqual(r.media_url, "https://cdn.metaxsire.com/media_video/video1.mp4")
        self.assertEqual(r.media_instruct_url, "https://cdn.metaxsire.com/media_instruct/video1.json")
        self.assertEqual(r.media_cover_url, "https://cdn.metaxsire.com/media_cover/video1.jpg")

        # DB 插入的 MediaVideo 字段正确
        mock_repo.insert.assert_called_once()
        video: MediaVideo = mock_repo.insert.call_args[0][0]
        self.assertIsInstance(video, MediaVideo)
        self.assertEqual(video.media_name, "video1")
        self.assertEqual(video.duration, 120)
        self.assertEqual(video.media_cover_width, 1920)
        self.assertEqual(video.media_cover_height, 1080)
        self.assertEqual(video.deleted_flag, 1)

    def test_mp4_without_json(self):
        """没有对应 .json 时，media_instruct_url 为空，仅上传两次（mp4 + cover）。"""
        uploader, mock_repo, mock_s3, _ = _make_uploader()

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "solo.mp4").write_bytes(b"fake")
            results = uploader.upload_folder(tmpdir)

        r = results[0]
        self.assertTrue(r.success, r.error)
        self.assertEqual(mock_s3.upload_file.call_count, 2)
        self.assertEqual(r.media_instruct_url, "")

        video: MediaVideo = mock_repo.insert.call_args[0][0]
        self.assertEqual(video.media_instruct_url, "")

    def test_multiple_mp4_files(self):
        """目录中有多个 .mp4 文件时，每个都处理一次。"""
        uploader, mock_repo, mock_s3, _ = _make_uploader()

        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                (Path(tmpdir) / f"v{i}.mp4").write_bytes(b"x")

            results = uploader.upload_folder(tmpdir)

        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.success for r in results))
        self.assertEqual(mock_repo.insert.call_count, 3)

    def test_no_mp4_returns_empty(self):
        uploader, _, _, _ = _make_uploader()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "readme.txt").write_text("hi")
            results = uploader.upload_folder(tmpdir)
        self.assertEqual(results, [])

    def test_nonexistent_folder_raises(self):
        uploader, _, _, _ = _make_uploader()
        with self.assertRaises(NotADirectoryError):
            uploader.upload_folder("/no/such/dir")

    def test_recursive(self):
        """recursive=True 时应扫描子目录。"""
        uploader, mock_repo, _, _ = _make_uploader()

        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Path(tmpdir) / "sub"
            sub.mkdir()
            (Path(tmpdir) / "root.mp4").write_bytes(b"r")
            (sub / "nested.mp4").write_bytes(b"n")

            results = uploader.upload_folder(tmpdir, recursive=True)

        self.assertEqual(len(results), 2)
        self.assertEqual(mock_repo.insert.call_count, 2)

    def test_non_recursive_skips_subdirs(self):
        """recursive=False 时不扫描子目录。"""
        uploader, mock_repo, _, _ = _make_uploader()

        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Path(tmpdir) / "sub"
            sub.mkdir()
            (Path(tmpdir) / "root.mp4").write_bytes(b"r")
            (sub / "nested.mp4").write_bytes(b"n")

            results = uploader.upload_folder(tmpdir, recursive=False)

        self.assertEqual(len(results), 1)
        self.assertEqual(mock_repo.insert.call_count, 1)

    # ---- dry_run ---------------------------------------------------------

    def test_dry_run_no_upload_no_db(self):
        uploader, mock_repo, mock_s3, _ = _make_uploader()

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.mp4").write_bytes(b"x")
            (Path(tmpdir) / "a.json").write_text("{}")
            results = uploader.upload_folder(tmpdir, dry_run=True)

        r = results[0]
        self.assertTrue(r.success)
        mock_s3.upload_file.assert_not_called()
        mock_repo.insert.assert_not_called()
        self.assertIn("[dry-run]", r.media_url)
        self.assertIn("[dry-run]", r.media_instruct_url)
        self.assertIn("[dry-run]", r.media_cover_url)

    # ---- 错误隔离 ---------------------------------------------------------

    def test_one_failure_does_not_block_others(self):
        """其中一个文件处理失败，不影响其他文件继续处理。"""
        uploader, mock_repo, mock_s3, mock_ih = _make_uploader()

        call_count = [0]

        def duration_side_effect(path):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("ffprobe 不可用")
            return 60.0

        mock_ih.get_video_duration.side_effect = duration_side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "bad.mp4").write_bytes(b"x")
            (Path(tmpdir) / "good.mp4").write_bytes(b"x")
            results = uploader.upload_folder(tmpdir)

        fails = [r for r in results if not r.success]
        oks = [r for r in results if r.success]
        self.assertEqual(len(fails), 1)
        self.assertEqual(len(oks), 1)
        self.assertIn("ffprobe", fails[0].error)

    # ---- S3 前缀自定义 ----------------------------------------------------

    def test_custom_prefixes(self):
        uploader, _, mock_s3, _ = _make_uploader(
            video_prefix="vids",
            json_prefix="jsons",
            cover_prefix="covers",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "x.mp4").write_bytes(b"x")
            (Path(tmpdir) / "x.json").write_text("{}")
            uploader.upload_folder(tmpdir)

        keys = {c[0][1] for c in mock_s3.upload_file.call_args_list}
        self.assertIn("vids/x.mp4", keys)
        self.assertIn("jsons/x.json", keys)
        self.assertIn("covers/x.jpg", keys)

    # ---- 默认字段值 -------------------------------------------------------

    def test_default_type_and_show_status(self):
        uploader, mock_repo, _, _ = _make_uploader(
            default_type=2,
            default_show_status=0,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "v.mp4").write_bytes(b"x")
            uploader.upload_folder(tmpdir)

        video: MediaVideo = mock_repo.insert.call_args[0][0]
        self.assertEqual(video.type, 2)
        self.assertEqual(video.show_status, 0)

    # ---- content_type 检验 ------------------------------------------------

    def test_upload_content_types(self):
        uploader, _, mock_s3, _ = _make_uploader()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "v.mp4").write_bytes(b"x")
            (Path(tmpdir) / "v.json").write_text("{}")
            uploader.upload_folder(tmpdir)

        ct_map = {
            c[0][1]: c[1].get("content_type", "")
            for c in mock_s3.upload_file.call_args_list
        }
        self.assertEqual(ct_map.get("media_video/v.mp4"), "video/mp4")
        self.assertEqual(ct_map.get("media_instruct/v.json"), "application/json")
        self.assertEqual(ct_map.get("media_cover/v.jpg"), "image/jpeg")

    # ---- cover 截帧参数 ---------------------------------------------------

    def test_cover_time_capped_at_10_percent_of_duration(self):
        """视频 5s，cover_time_sec=10 → 实际截帧在 min(10, 5*0.1)=0.5s。"""
        uploader, _, _, mock_ih = _make_uploader(cover_time_sec=10.0)
        mock_ih.get_video_duration.return_value = 5.0

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "short.mp4").write_bytes(b"x")
            uploader.upload_folder(tmpdir)

        _, actual_time = mock_ih.extract_frame.call_args[0][:2]
        self.assertAlmostEqual(actual_time, 0.5, places=5)

    def test_cover_time_used_when_smaller(self):
        """视频 120s，cover_time_sec=1 → 实际截帧在 min(1, 12)=1s。"""
        uploader, _, _, mock_ih = _make_uploader(cover_time_sec=1.0)
        mock_ih.get_video_duration.return_value = 120.0

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "long.mp4").write_bytes(b"x")
            uploader.upload_folder(tmpdir)

        _, actual_time = mock_ih.extract_frame.call_args[0][:2]
        self.assertAlmostEqual(actual_time, 1.0, places=5)


# ---------------------------------------------------------------------------
# UploadResult.__str__ 测试
# ---------------------------------------------------------------------------

class TestUploadResult(unittest.TestCase):
    def test_str_success(self):
        r = UploadResult(stem="vid", success=True, media_id=7,
                         duration=90, media_url="https://cdn/v.mp4")
        self.assertIn("[OK]", str(r))
        self.assertIn("id=7", str(r))

    def test_str_failure(self):
        r = UploadResult(stem="bad", success=False, error="timeout")
        self.assertIn("[ERR]", str(r))
        self.assertIn("timeout", str(r))


if __name__ == "__main__":
    unittest.main()
