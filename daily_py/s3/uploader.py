"""S3 文件上传工具。"""

import mimetypes
from pathlib import Path
from typing import List, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError as _e:
    raise ImportError(
        "boto3 未安装，请执行：pip install boto3"
    ) from _e


class S3Uploader:
    """轻量级 S3 上传工具。

    Example::

        uploader = S3Uploader(
            bucket="my-bucket",
            aws_access_key_id="AKID...",
            aws_secret_access_key="secret...",
            region_name="us-west-1",
        )
        url = uploader.upload_file("./photo.jpg", "images/photo.jpg")
    """

    def __init__(
        self,
        bucket: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region_name: str = "us-east-1",
        base_url: str = "",
    ) -> None:
        self._bucket = bucket
        self._region = region_name
        # 自定义 CDN 域名，优先于标准 S3 URL
        # 例如 "https://cdn.metaxsire.com" → https://cdn.metaxsire.com/{key}
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._client = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )

    # ------------------------------------------------------------------
    # 上传
    # ------------------------------------------------------------------

    def upload_file(
        self,
        local_path: str,
        s3_key: str,
        content_type: Optional[str] = None,
        public: bool = True,
    ) -> str:
        """上传本地文件到 S3，返回访问 URL。

        Args:
            local_path: 本地文件路径。
            s3_key: S3 对象键（相对于 bucket 根目录的路径）。
            content_type: MIME 类型，为 ``None`` 时自动推断。
            public: 保留参数（兼容旧接口），bucket 的公开访问由 Bucket Policy 控制，
                    不再通过对象 ACL 设置（避免 AccessControlListNotSupported 错误）。

        Returns:
            文件的公开访问 URL。
        """
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在：{local_path}")

        ct = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        extra: dict = {"ContentType": ct}

        self._client.upload_file(str(path), self._bucket, s3_key, ExtraArgs=extra)
        return self.get_public_url(s3_key)

    def upload_bytes(
        self,
        data: bytes,
        s3_key: str,
        content_type: str = "application/octet-stream",
        public: bool = True,
    ) -> str:
        """上传字节数据到 S3，返回访问 URL。

        Args:
            data: 要上传的字节内容。
            s3_key: S3 对象键。
            content_type: MIME 类型。
            public: 是否公开可读。
        """
        extra: dict = {"ContentType": content_type}

        self._client.put_object(Bucket=self._bucket, Key=s3_key, Body=data, **extra)
        return self.get_public_url(s3_key)

    def upload_dir(
        self,
        local_dir: str,
        s3_prefix: str = "",
        public: bool = True,
        recursive: bool = True,
    ) -> List[str]:
        """批量上传目录下的所有文件，返回 URL 列表。

        Args:
            local_dir: 本地目录路径。
            s3_prefix: S3 路径前缀，例如 ``"images/2024"``。
            public: 是否公开可读。
            recursive: 是否递归子目录。

        Returns:
            所有已上传文件的公开 URL 列表。
        """
        base = Path(local_dir)
        if not base.is_dir():
            raise NotADirectoryError(f"目录不存在：{local_dir}")

        pattern = "**/*" if recursive else "*"
        urls: List[str] = []
        for path in sorted(base.glob(pattern)):
            if path.is_file():
                rel = path.relative_to(base).as_posix()
                key = f"{s3_prefix}/{rel}".lstrip("/") if s3_prefix else rel
                url = self.upload_file(str(path), key, public=public)
                urls.append(url)
        return urls

    # ------------------------------------------------------------------
    # URL
    # ------------------------------------------------------------------

    def get_public_url(self, s3_key: str) -> str:
        """返回对象的公开访问 URL。

        若构造时传入了 ``base_url``（自定义 CDN 域名），则返回
        ``{base_url}/{key}``，否则返回标准 S3 路径。
        """
        if self._base_url:
            return f"{self._base_url}/{s3_key}"
        return f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{s3_key}"

    def get_presigned_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """生成带签名的临时访问 URL（私有对象也可访问）。

        Args:
            s3_key: S3 对象键。
            expires_in: 有效期（秒），默认 3600（1 小时）。
        """
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    # ------------------------------------------------------------------
    # 管理
    # ------------------------------------------------------------------

    def exists(self, s3_key: str) -> bool:
        """检查对象是否存在。"""
        try:
            self._client.head_object(Bucket=self._bucket, Key=s3_key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def delete(self, s3_key: str) -> bool:
        """删除指定对象，返回 ``True`` 表示成功。"""
        self._client.delete_object(Bucket=self._bucket, Key=s3_key)
        return True

    def list_objects(self, prefix: str = "") -> List[str]:
        """列出 bucket 内指定前缀下的所有对象键（自动处理分页）。"""
        keys: List[str] = []
        kwargs: dict = {"Bucket": self._bucket, "Prefix": prefix}
        while True:
            resp = self._client.list_objects_v2(**kwargs)
            keys.extend(obj["Key"] for obj in resp.get("Contents", []))
            if not resp.get("IsTruncated"):
                break
            kwargs["ContinuationToken"] = resp["NextContinuationToken"]
        return keys
