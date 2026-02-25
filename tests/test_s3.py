"""单元测试 — s3 模块（mock boto3，不发起真实 AWS 请求）。"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import tempfile

# ---------------------------------------------------------------------------
# 在真实 boto3 / botocore 不存在时注入 stub
# ---------------------------------------------------------------------------
if "boto3" not in sys.modules:
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = MagicMock()  # type: ignore[attr-defined]
    sys.modules["boto3"] = boto3_stub

if "botocore" not in sys.modules:
    botocore_stub = types.ModuleType("botocore")
    botocore_exc_stub = types.ModuleType("botocore.exceptions")

    class _ClientError(Exception):
        def __init__(self, error_response: dict, operation_name: str = "op") -> None:
            self.response = error_response
            super().__init__(str(error_response))

    botocore_exc_stub.ClientError = _ClientError  # type: ignore[attr-defined]
    botocore_stub.exceptions = botocore_exc_stub  # type: ignore[attr-defined]
    sys.modules["botocore"] = botocore_stub
    sys.modules["botocore.exceptions"] = botocore_exc_stub

from daily_py.s3.uploader import S3Uploader
from daily_py.s3.config import S3_CONFIG, create_uploader


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_uploader(bucket: str = "test-bucket", base_url: str = "") -> tuple:
    """返回 (uploader, mock_s3_client)。"""
    mock_client = MagicMock()
    with patch("daily_py.s3.uploader.boto3") as mock_boto3:
        mock_boto3.client.return_value = mock_client
        uploader = S3Uploader(
            bucket=bucket,
            aws_access_key_id="AKID",
            aws_secret_access_key="SECRET",
            region_name="us-west-1",
            base_url=base_url,
        )
    return uploader, mock_client


# ---------------------------------------------------------------------------
# S3Uploader 测试
# ---------------------------------------------------------------------------

class TestS3Uploader(unittest.TestCase):

    # ---- upload_file ------------------------------------------------------

    def test_upload_file_returns_s3_url(self):
        """无 base_url 时返回标准 S3 URL。"""
        uploader, mock_client = _make_uploader()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"fake-image")
            tmp_path = f.name

        url = uploader.upload_file(tmp_path, "images/photo.jpg")

        self.assertEqual(url, "https://test-bucket.s3.us-west-1.amazonaws.com/images/photo.jpg")

    def test_upload_file_returns_cdn_url(self):
        """设置 base_url 时返回自定义 CDN 域名 URL。"""
        uploader, mock_client = _make_uploader(
            bucket="cdn.metaxsire.com",
            base_url="https://cdn.metaxsire.com",
        )
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp_path = f.name

        url = uploader.upload_file(tmp_path, "media_video/Nepo_Hoes_32.mp4")

        self.assertEqual(url, "https://cdn.metaxsire.com/media_video/Nepo_Hoes_32.mp4")
        mock_client.upload_file.assert_called_once()
        args = mock_client.upload_file.call_args
        self.assertEqual(args[0][1], "cdn.metaxsire.com")
        self.assertEqual(args[0][2], "media_video/Nepo_Hoes_32.mp4")
        self.assertIn("video/mp4", args[1]["ExtraArgs"]["ContentType"])

    def test_upload_file_no_acl_regardless_of_public_flag(self):
        """bucket 禁用 ACL，public 参数不再写入 ACL 头。"""
        for public in (True, False):
            with self.subTest(public=public):
                uploader, mock_client = _make_uploader()
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    tmp_path = f.name
                uploader.upload_file(tmp_path, "img.png", public=public)
                extra = mock_client.upload_file.call_args[1]["ExtraArgs"]
                self.assertNotIn("ACL", extra)

    def test_upload_file_not_found(self):
        uploader, _ = _make_uploader()
        with self.assertRaises(FileNotFoundError):
            uploader.upload_file("/nonexistent/path.jpg", "key.jpg")

    def test_upload_file_custom_content_type(self):
        uploader, mock_client = _make_uploader()
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            tmp_path = f.name

        uploader.upload_file(tmp_path, "data.bin", content_type="application/x-custom")
        extra = mock_client.upload_file.call_args[1]["ExtraArgs"]
        self.assertEqual(extra["ContentType"], "application/x-custom")

    # ---- upload_bytes -----------------------------------------------------

    def test_upload_bytes_returns_cdn_url(self):
        uploader, mock_client = _make_uploader(
            bucket="cdn.metaxsire.com",
            base_url="https://cdn.metaxsire.com",
        )
        url = uploader.upload_bytes(b"hello", "texts/hello.txt", "text/plain")

        self.assertEqual(url, "https://cdn.metaxsire.com/texts/hello.txt")
        mock_client.put_object.assert_called_once_with(
            Bucket="cdn.metaxsire.com",
            Key="texts/hello.txt",
            Body=b"hello",
            ContentType="text/plain",
        )

    def test_upload_bytes_no_acl(self):
        """ACL 已从 put_object 调用中移除。"""
        for public in (True, False):
            with self.subTest(public=public):
                uploader, mock_client = _make_uploader(
                    bucket="cdn.metaxsire.com",
                    base_url="https://cdn.metaxsire.com",
                )
                uploader.upload_bytes(b"data", "k", public=public)
                call_kwargs = mock_client.put_object.call_args[1]
                self.assertNotIn("ACL", call_kwargs)

    # ---- upload_dir -------------------------------------------------------

    def test_upload_dir(self):
        uploader, mock_client = _make_uploader()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.txt").write_text("aaa")
            (Path(tmpdir) / "b.txt").write_text("bbb")

            urls = uploader.upload_dir(tmpdir, s3_prefix="files")

        self.assertEqual(len(urls), 2)
        self.assertEqual(mock_client.upload_file.call_count, 2)
        keys = {c[0][2] for c in mock_client.upload_file.call_args_list}
        self.assertIn("files/a.txt", keys)
        self.assertIn("files/b.txt", keys)

    def test_upload_dir_no_prefix(self):
        uploader, mock_client = _make_uploader()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "x.txt").write_text("x")
            uploader.upload_dir(tmpdir)

        key = mock_client.upload_file.call_args[0][2]
        self.assertEqual(key, "x.txt")  # 无前缀时不含 /

    def test_upload_dir_not_found(self):
        uploader, _ = _make_uploader()
        with self.assertRaises(NotADirectoryError):
            uploader.upload_dir("/no/such/dir")

    def test_upload_dir_recursive(self):
        uploader, mock_client = _make_uploader()
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Path(tmpdir) / "sub"
            sub.mkdir()
            (Path(tmpdir) / "root.txt").write_text("r")
            (sub / "nested.txt").write_text("n")

            urls = uploader.upload_dir(tmpdir, recursive=True)

        self.assertEqual(len(urls), 2)

    # ---- URL 生成 ---------------------------------------------------------

    def test_get_public_url_standard_s3(self):
        """无 base_url 时使用标准 S3 路径。"""
        uploader, _ = _make_uploader("my-bucket")
        url = uploader.get_public_url("folder/file.mp4")
        self.assertEqual(url, "https://my-bucket.s3.us-west-1.amazonaws.com/folder/file.mp4")

    def test_get_public_url_cdn_domain(self):
        """设置 base_url 后使用自定义域名。"""
        uploader, _ = _make_uploader(
            bucket="cdn.metaxsire.com",
            base_url="https://cdn.metaxsire.com",
        )
        url = uploader.get_public_url("media_video/Nepo_Hoes_32.mp4")
        self.assertEqual(url, "https://cdn.metaxsire.com/media_video/Nepo_Hoes_32.mp4")

    def test_get_public_url_base_url_trailing_slash(self):
        """base_url 末尾有斜杠时也能正确拼接。"""
        uploader, _ = _make_uploader(
            bucket="cdn.metaxsire.com",
            base_url="https://cdn.metaxsire.com/",  # 带尾部斜杠
        )
        url = uploader.get_public_url("images/a.jpg")
        self.assertEqual(url, "https://cdn.metaxsire.com/images/a.jpg")

    def test_get_presigned_url(self):
        uploader, mock_client = _make_uploader()
        mock_client.generate_presigned_url.return_value = "https://presigned.example.com/key"

        url = uploader.get_presigned_url("private/doc.pdf", expires_in=7200)

        self.assertEqual(url, "https://presigned.example.com/key")
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "private/doc.pdf"},
            ExpiresIn=7200,
        )

    # ---- exists -----------------------------------------------------------

    def test_exists_true(self):
        uploader, mock_client = _make_uploader()
        mock_client.head_object.return_value = {}
        self.assertTrue(uploader.exists("some/key.jpg"))
        mock_client.head_object.assert_called_once_with(
            Bucket="test-bucket", Key="some/key.jpg"
        )

    def test_exists_false_on_404(self):
        from botocore.exceptions import ClientError
        uploader, mock_client = _make_uploader()
        mock_client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")
        self.assertFalse(uploader.exists("missing/key.jpg"))

    def test_exists_raises_on_other_error(self):
        from botocore.exceptions import ClientError
        uploader, mock_client = _make_uploader()
        mock_client.head_object.side_effect = ClientError({"Error": {"Code": "403"}}, "HeadObject")
        with self.assertRaises(ClientError):
            uploader.exists("forbidden/key.jpg")

    # ---- delete -----------------------------------------------------------

    def test_delete(self):
        uploader, mock_client = _make_uploader()
        result = uploader.delete("old/file.txt")
        self.assertTrue(result)
        mock_client.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="old/file.txt"
        )

    # ---- list_objects -----------------------------------------------------

    def test_list_objects_single_page(self):
        uploader, mock_client = _make_uploader()
        mock_client.list_objects_v2.return_value = {
            "Contents": [{"Key": "a.txt"}, {"Key": "b.txt"}],
            "IsTruncated": False,
        }
        keys = uploader.list_objects(prefix="")
        self.assertEqual(keys, ["a.txt", "b.txt"])

    def test_list_objects_pagination(self):
        uploader, mock_client = _make_uploader()
        mock_client.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": "p1.txt"}],
                "IsTruncated": True,
                "NextContinuationToken": "token-1",
            },
            {
                "Contents": [{"Key": "p2.txt"}],
                "IsTruncated": False,
            },
        ]
        keys = uploader.list_objects(prefix="data/")
        self.assertEqual(keys, ["p1.txt", "p2.txt"])
        self.assertEqual(mock_client.list_objects_v2.call_count, 2)

    def test_list_objects_empty(self):
        uploader, mock_client = _make_uploader()
        mock_client.list_objects_v2.return_value = {"IsTruncated": False}
        self.assertEqual(uploader.list_objects(), [])


# ---------------------------------------------------------------------------
# config / create_uploader 测试
# ---------------------------------------------------------------------------

class TestS3Config(unittest.TestCase):
    def test_config_has_required_keys(self):
        for key in ("aws_access_key_id", "aws_secret_access_key", "region_name", "bucket", "base_url"):
            self.assertIn(key, S3_CONFIG)

    def test_config_region(self):
        self.assertEqual(S3_CONFIG["region_name"], "us-west-1")

    def test_config_bucket_and_base_url(self):
        self.assertEqual(S3_CONFIG["bucket"], "cdn.metaxsire.com")
        self.assertEqual(S3_CONFIG["base_url"], "https://cdn.metaxsire.com")

    def test_create_uploader_default_config(self):
        """create_uploader() 无参数时使用预设 bucket 和 base_url。"""
        with patch("daily_py.s3.uploader.boto3") as mock_boto3:
            mock_boto3.client.return_value = MagicMock()
            uploader = create_uploader()
        self.assertIsInstance(uploader, S3Uploader)
        self.assertEqual(uploader._bucket, "cdn.metaxsire.com")
        self.assertEqual(uploader._region, "us-west-1")
        self.assertEqual(uploader._base_url, "https://cdn.metaxsire.com")
        # 验证生成的 URL 格式
        url = uploader.get_public_url("media_video/Nepo_Hoes_32.mp4")
        self.assertEqual(url, "https://cdn.metaxsire.com/media_video/Nepo_Hoes_32.mp4")

    def test_create_uploader_with_explicit_bucket(self):
        with patch("daily_py.s3.uploader.boto3") as mock_boto3:
            mock_boto3.client.return_value = MagicMock()
            uploader = create_uploader("other-bucket")
        self.assertEqual(uploader._bucket, "other-bucket")

    def test_create_uploader_empty_bucket_raises(self):
        original = S3_CONFIG["bucket"]
        S3_CONFIG["bucket"] = ""
        try:
            with self.assertRaises(ValueError):
                create_uploader()
        finally:
            S3_CONFIG["bucket"] = original

    def test_create_uploader_uses_config_bucket(self):
        original_bucket = S3_CONFIG["bucket"]
        original_base = S3_CONFIG["base_url"]
        S3_CONFIG["bucket"] = "preset-bucket"
        S3_CONFIG["base_url"] = ""
        try:
            with patch("daily_py.s3.uploader.boto3") as mock_boto3:
                mock_boto3.client.return_value = MagicMock()
                uploader = create_uploader()
            self.assertEqual(uploader._bucket, "preset-bucket")
        finally:
            S3_CONFIG["bucket"] = original_bucket
            S3_CONFIG["base_url"] = original_base


if __name__ == "__main__":
    unittest.main()
