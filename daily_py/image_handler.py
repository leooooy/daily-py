"""DailyPy - 图像处理工具
提供获取图片尺寸、视频截帧、图片缩放、压缩、以及简单的去水印等功能。
依赖：Pillow (PIL) 作为图像处理核心；可选依赖 OpenCV(cv2) 与 moviepy 以实现水印去除与视频帧提取。
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional, Tuple, Union, Dict, Any
import logging

from PIL import Image
import subprocess
import shutil
try:
    import cv2  # type: ignore
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

try:
    from moviepy.editor import VideoFileClip  # type: ignore
    HAS_MOVIEPY = True
except Exception:
    HAS_MOVIEPY = False

import numpy as np

# Pillow 兼容性：尽量使用 RESAMPLE 常量，兼容旧版本
try:
    RESAMPLE = Image.Resampling.LANCZOS  # type: ignore
except Exception:
    try:
        RESAMPLE = Image.LANCZOS  # type: ignore
    except Exception:
        RESAMPLE = Image.NEAREST  # type: ignore


class ImageHandler:
    """图像处理器
    提供常用的图像/视频处理能力：尺寸获取、帧提取、缩放、压缩、去水印等。
    """

    def __init__(self, base_path: Optional[Union[str, Path]] = None, logger: Optional[logging.Logger] = None):
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.logger = logger or logging.getLogger(__name__)
        if not self.logger.handlers:
            self.logger.addHandler(logging.StreamHandler())
            self.logger.setLevel(logging.INFO)
        # 预检测 ffmpeg 是否可用，作为后端选项之一
        self._ffmpeg_path = shutil.which("ffmpeg")
        self.ffmpeg_available = self._ffmpeg_path is not None

    def _resolve(self, path: Union[str, Path]) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.base_path / p
        return p

    # 1) 获取图片宽高
    def get_image_size(self, image_path: Union[str, Path]) -> Tuple[int, int]:
        p = self._resolve(image_path)
        if not p.exists():
            raise FileNotFoundError(f"图片不存在: {p}")
        with Image.open(p) as img:
            return img.width, img.height

    # 2) 视频某帧截图
    def extract_frame(self, video_path: Union[str, Path], time_sec: float, output_path: Optional[Union[str, Path]] = None, backend: str = "auto") -> Path:
        """从视频中提取指定时间点的一帧，支持三种后端：ffmpeg、moviepy、auto（优先 ffmpeg）"""
        # 优先选择 ffmpeg 后端
        video_p = self._resolve(video_path)
        if backend == "ffmpeg" or (backend == "auto" and (self.ffmpeg_available)):
            if not self.ffmpeg_available:
                raise RuntimeError("FFmpeg 未检测到，但请求使用 ffmpeg 后端进行帧提取")
            out = Path(output_path) if output_path else video_p.with_suffix(".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            # 构造 FFmpeg 命令：截取时间点帧，输出为 PNG
            cmd = [self._ffmpeg_path, "-ss", str(time_sec), "-i", str(video_p), "-frames:v", "1", "-f", "image2", str(out)]
            self.logger.info(f"使用 FFmpeg 提取帧: {cmd}")
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"FFmpeg 提取帧失败: {res.stderr}")
            self.logger.info(f"已从视频 {video_p} 在 {time_sec}s 处截取帧并保存到 {out}")
            return out
        else:
            if not HAS_MOVIEPY:
                raise ImportError("需要安装 moviepy 才能使用 extract_frame，请执行: pip install moviepy")
            clip = VideoFileClip(str(video_p)) if HAS_MOVIEPY else None  # type: ignore
            if clip is None:
                raise ImportError("MoviePy 未可用")
            frame = clip.get_frame(float(time_sec))  # numpy array (H, W, 3)
            output = Path(output_path) if output_path else Path(video_p).with_suffix(".png")
            output.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(frame).save(output)
            clip.close()
            self.logger.info(f"已从视频 {video_p} 在 {time_sec}s 处截取帧并保存到 {output}")
            return output


    # 3) 缩放图片，支持保持纵横比并填充
    def resize_image(self, input_path: Union[str, Path], output_path: Union[str, Path], size: Union[Tuple[int, int], int],
                     keep_aspect: bool = True, fill_color: Tuple[int, int, int] = (255, 255, 255)) -> Path:
        in_p = self._resolve(input_path)
        out_p = self._resolve(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(in_p) as im:
            if isinstance(size, int):
                max_dim = max(im.size)
                ratio = float(size) / float(max_dim)
                new_w = int(im.width * ratio)
                new_h = int(im.height * ratio)
                target = (new_w, new_h)
            else:
                target = size

            if keep_aspect and isinstance(size, tuple):
                # 先缩略到尽可能接近目标尺寸的大小，然后居中填充
                im.thumbnail(target, RESAMPLE)
                canvas = Image.new(im.mode, target, fill_color)
                paste_pos = ((target[0] - im.width) // 2, (target[1] - im.height) // 2)
                canvas.paste(im, paste_pos)
                result = canvas
            else:
                result = im.resize(target, RESAMPLE)

            result.save(out_p)
        self.logger.info(f"图片已重新大小：{in_p} -> {out_p}（目标尺寸: {target}）")
        return out_p

    # 4) 图片压缩
    def compress_image(self, input_path: Union[str, Path], output_path: Optional[Union[str, Path]] = None, quality: int = 85, optimize: bool = True) -> Path:
        in_p = self._resolve(input_path)
        if not in_p.exists():
            raise FileNotFoundError(f"图片不存在: {in_p}")
        if output_path:
            out_p = self._resolve(output_path)
        else:
            out_p = in_p.parent / (in_p.stem + "_compressed" + in_p.suffix)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(in_p) as im:
            fmt = im.format or out_p.suffix.replace(".", "").upper()
            if fmt.upper() in ["JPEG", "JPG"]:
                im.save(out_p, format="JPEG", quality=quality, optimize=optimize)
            elif fmt.upper() == "PNG":
                im.save(out_p, format="PNG", optimize=optimize)
            else:
                im.save(out_p, quality=quality, optimize=optimize)
        self.logger.info(f"图片已压缩：{in_p} -> {out_p}，质量={quality}")
        return out_p

    # 5) 去水印（简单实现，使用 OpenCV inpaint）
    def remove_watermark(self, input_path: Union[str, Path], output_path: Optional[Union[str, Path]] = None, bbox: Optional[Tuple[int, int, int, int]] = None, inpaint_radius: int = 3) -> Path:
        if not HAS_CV2:
            raise ImportError("去水印需要 OpenCV(cv2)，请先安装: pip install opencv-python")
        if bbox is None:
            raise ValueError("请提供水印区域 bbox (x, y, w, h)")
        from numpy import zeros
        in_p = self._resolve(input_path)
        if not in_p.exists():
            raise FileNotFoundError(f"图片不存在: {in_p}")
        # 使用局部导入以避免静态分析问题
        import cv2 as _cv2
        img = _cv2.imread(str(in_p))
        if img is None:
            raise ValueError(f"无法读取图片: {in_p}")
        x, y, w, h = bbox
        mask = zeros(img.shape[:2], dtype=np.uint8)
        mask[y:y+h, x:x+w] = 255
        dst = _cv2.inpaint(img, mask, inpaint_radius, _cv2.INPAINT_TELEA)
        out_p = Path(output_path) if output_path else in_p.parent / (in_p.stem + "_nwatermarked" + in_p.suffix)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        _cv2.imwrite(str(out_p), dst)
        self.logger.info(f"已去水印：{in_p} -> {out_p}")
        return out_p

    # 6) 转换格式
    def convert_format(self, input_path: Union[str, Path], output_format: str, output_path: Optional[Union[str, Path]] = None) -> Path:
        in_p = self._resolve(input_path)
        if not in_p.exists():
            raise FileNotFoundError(f"图片不存在: {in_p}")
        if output_path:
            out_p = self._resolve(output_path)
        else:
            out_p = in_p.with_suffix("." + output_format.lower())
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(in_p) as im:
            im.save(out_p, format=output_format.upper())
        self.logger.info(f"已将格式转换为 {output_format.upper()}：{in_p} -> {out_p}")
        return out_p
