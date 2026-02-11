"""DailyPy - 通用文件处理器
提供删除、重命名、移动、复制、压缩、解压、备份等常用文件操作。
"""

from __future__ import annotations

import io
import os
import shutil
import zipfile
import tarfile
import time
import logging
from pathlib import Path
from typing import List, Optional, Union, Dict, Any


class FileHandler:
    """通用文件处理器，实现常见的文件操作。"""

    def __init__(self, base_path: Optional[Union[str, Path]] = None, logger: Optional[logging.Logger] = None):
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.logger = logger or logging.getLogger(__name__)
        if not self.logger.handlers:
            self.logger.addHandler(logging.StreamHandler())
            self.logger.setLevel(logging.INFO)

    def _resolve(self, path_like: Union[str, Path]) -> Path:
        p = Path(path_like)
        if not p.is_absolute():
            p = self.base_path / p
        return p

    # 删除文件或目录
    def delete_file(self, file_path: Union[str, Path]) -> bool:
        path = self._resolve(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        self.logger.info(f"已删除: {path}")
        return True

    # 重命名文件或目录
    def rename_file(self, old_path: Union[str, Path], new_path: Union[str, Path]) -> bool:
        old_p = self._resolve(old_path)
        new_p = self._resolve(new_path)
        if not old_p.exists():
            raise FileNotFoundError(f"源文件不存在: {old_p}")
        if new_p.exists():
            raise FileExistsError(f"目标已存在: {new_p}")
        old_p.rename(new_p)
        self.logger.info(f"已重命名: {old_p} -> {new_p}")
        return True

    # 移动文件或目录
    def move_file(self, src_path: Union[str, Path], dst_path: Union[str, Path]) -> bool:
        src = self._resolve(src_path)
        dst = self._resolve(dst_path)
        if not src.exists():
            raise FileNotFoundError(f"源文件不存在: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        self.logger.info(f"已移动: {src} -> {dst}")
        return True

    # 复制文件或目录
    def copy_file(self, src_path: Union[str, Path], dst_path: Union[str, Path]) -> bool:
        src = self._resolve(src_path)
        dst = self._resolve(dst_path)
        if not src.exists():
            raise FileNotFoundError(f"源文件不存在: {src}")
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        self.logger.info(f"已复制: {src} -> {dst}")
        return True

    # 创建目录
    def create_directory(self, dir_path: Union[str, Path], parents: bool = True) -> bool:
        path = self._resolve(dir_path)
        path.mkdir(parents=parents, exist_ok=True)
        self.logger.info(f"目录创建完成: {path}")
        return True

    # 列出目录中的文件
    def list_files(self, directory: Union[str, Path], pattern: str = "*") -> List[Path]:
        dir_path = self._resolve(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"目录不存在: {dir_path}")
        return [p for p in sorted(dir_path.glob(pattern)) if p.is_file()]

    # 获取文件信息
    def get_file_info(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        p = self._resolve(file_path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        stat = p.stat()
        return {
            "name": p.name,
            "size": stat.st_size,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "extension": p.suffix,
            "absolute_path": str(p.resolve()),
        }

    # 压缩文件（支持 zip、tar、tar.gz、bz2、xz 等）
    def compress_files(self, files: List[Union[str, Path]], archive_path: Union[str, Path], format: str = "zip") -> bool:
        archive_path = Path(archive_path)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        file_paths = [Path(f) for f in files]
        if format == "zip":
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fp in file_paths:
                    if fp.exists():
                        zf.write(fp, arcname=fp.name)
            return True
        elif format in ("tar", "gztar", "bz2", "xz tar"):  # simplified
            base = archive_path.with_suffix("")
            shutil.make_archive(str(base), format.replace(" tar", "tar"), root_dir=str(file_paths[0].parent) if file_paths else ".")
            return True
        else:
            raise ValueError(f"不支持的归档格式: {format}")

    # 解压缩归档
    def extract_archive(self, archive_path: Union[str, Path], extract_to: Union[str, Path]) -> bool:
        ap = Path(archive_path)
        dst = Path(extract_to)
        if not ap.exists():
            raise FileNotFoundError(f"压缩文件不存在: {ap}")
        dst.mkdir(parents=True, exist_ok=True)
        if ap.suffix.lower() == ".zip":
            with zipfile.ZipFile(ap, 'r') as zf:
                zf.extractall(dst)
        else:
            shutil.unpack_archive(str(ap), str(dst))
        self.logger.info(f"解压完成: {ap} -> {dst}")
        return True

    # 备份文件
    def backup_file(self, file_path: Union[str, Path], backup_dir: Optional[Union[str, Path]] = None) -> Path:
        f = self._resolve(file_path)
        if not f.exists():
            raise FileNotFoundError(f"文件不存在: {f}")
        bdir = Path(backup_dir) if backup_dir else f.parent / "backup"
        bdir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"{f.stem}_{ts}{f.suffix}"
        backup_path = bdir / backup_name
        shutil.copy2(f, backup_path)
        self.logger.info(f"已创建备份: {f} -> {backup_path}")
        return backup_path

    # 清理空目录
    def clean_empty_dirs(self, directory: Union[str, Path]) -> int:
        base = self._resolve(directory)
        removed = 0
        for root, dirs, files in os.walk(base, topdown=False):
            for d in dirs:
                p = Path(root) / d
                try:
                    if not any(p.iterdir()):
                        p.rmdir()
                        removed += 1
                        self.logger.info(f"已删除空目录: {p}")
                except OSError:
                    pass
        return removed

    # 查找重复文件（简单基于大小和名称）
    def find_duplicate_files(self, directory: Union[str, Path]) -> Dict[str, List[Path]]:
        dir_path = self._resolve(directory)
        dups: Dict[str, List[Path]] = {}
        seen: Dict[str, Path] = {}
        for p in dir_path.rglob('*'):
            if p.is_file():
                key = f"{p.stat().st_size}_{p.name}"
                if key in seen:
                    dups.setdefault(key, [seen[key]]).append(p)
                else:
                    seen[key] = p
        return dups

    # 批量重命名
    def batch_rename(self, directory: Union[str, Path], pattern: str, replacement: str, use_regex: bool = False) -> int:
        import re
        dir_path = self._resolve(directory)
        renamed = 0
        for p in dir_path.iterdir():
            if p.is_file():
                old_name = p.name
                if use_regex:
                    new_name = re.sub(pattern, replacement, old_name)
                else:
                    new_name = old_name.replace(pattern, replacement)
                if new_name != old_name:
                    new_path = p.parent / new_name
                    if not new_path.exists():
                        p.rename(new_path)
                        renamed += 1
                        self.logger.info(f"重命名: {old_name} -> {new_name}")
        return renamed
