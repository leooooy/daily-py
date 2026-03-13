"""HuggingFace 模型下载工具。

将 HuggingFace Hub 上的模型下载到本地目录，供离线使用。

Usage::

    from daily_py.services.model_downloader import ModelDownloader

    dl = ModelDownloader()
    path = dl.download("Qwen/Qwen3-ForcedAligner-0.6B")
    print(path)  # D:\my_models\Qwen3-ForcedAligner-0.6B
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

_DEFAULT_BASE_DIR = r"D:\my_models"


class ModelDownloader:
    """HuggingFace Hub 模型下载器。

    Parameters
    ----------
    base_dir : str
        本地模型存储根目录，默认 ``D:\\my_models``。
        模型会下载到 ``base_dir/模型名`` 子目录下。
    token : str, optional
        HuggingFace token（私有模型需要）。
    progress_callback : callable, optional
        进度回调 ``(str) -> None``。
    """

    def __init__(
        self,
        base_dir: str = _DEFAULT_BASE_DIR,
        token: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._token = token
        self._log = logger or logging.getLogger(__name__)
        self._progress = progress_callback or self._log.info

    def _ensure_hub(self):
        try:
            from huggingface_hub import snapshot_download  # noqa: F401
            return True
        except ImportError:
            raise ImportError(
                "需要 huggingface_hub 库。\n"
                "安装命令: pip install huggingface_hub"
            )

    def download(
        self,
        repo_id: str,
        *,
        local_dir: Optional[str] = None,
        revision: Optional[str] = None,
    ) -> Path:
        """下载模型到本地。

        Parameters
        ----------
        repo_id : str
            HuggingFace 仓库 ID，如 ``Qwen/Qwen3-ForcedAligner-0.6B``。
        local_dir : str, optional
            自定义本地目录。默认为 ``base_dir/模型名``。
        revision : str, optional
            指定版本/分支，默认 main。

        Returns
        -------
        Path
            下载后的本地模型目录路径。
        """
        self._ensure_hub()
        from huggingface_hub import snapshot_download

        # 模型名取 repo_id 的最后一段: "Qwen/Qwen3-ForcedAligner-0.6B" -> "Qwen3-ForcedAligner-0.6B"
        model_name = repo_id.split("/")[-1]
        target = Path(local_dir) if local_dir else self._base_dir / model_name
        target.parent.mkdir(parents=True, exist_ok=True)

        if self._is_complete(target):
            self._progress(f"模型已存在: {target}")
            return target

        self._progress(f"开始下载: {repo_id} -> {target}")

        kwargs = {
            "repo_id": repo_id,
            "local_dir": str(target),
        }
        if revision:
            kwargs["revision"] = revision
        if self._token:
            kwargs["token"] = self._token

        snapshot_download(**kwargs)

        self._progress(f"下载完成: {target}")
        return target

    def list_models(self) -> list[dict]:
        """列出本地已下载的模型。

        Returns
        -------
        list of dict
            每个字典包含 name, path, size_mb。
        """
        if not self._base_dir.exists():
            return []

        models = []
        for d in sorted(self._base_dir.iterdir()):
            if not d.is_dir():
                continue
            # 计算目录大小
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            models.append({
                "name": d.name,
                "path": str(d),
                "size_mb": round(size / 1024 / 1024, 1),
            })
        return models

    @staticmethod
    def _is_complete(path: Path) -> bool:
        """简单判断模型是否已下载完成（存在 config.json）。"""
        return path.is_dir() and (path / "config.json").exists()


if __name__ == "__main__":
    import sys
    #python -m daily_py.services.model_downloader Qwen/Qwen3-ForcedAligner-0.6B D:\my_models
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    repo = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3-ForcedAligner-0.6B"
    base = sys.argv[2] if len(sys.argv) > 2 else _DEFAULT_BASE_DIR

    dl = ModelDownloader(base_dir=base)
    path = dl.download(repo)
    print(f"模型路径: {path}")
