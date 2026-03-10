"""DailyPy - 图像处理工具
提供获取图片尺寸、视频截帧、图片缩放、压缩、以及简单的去水印等功能。
依赖：Pillow (PIL) 作为图像处理核心；可选依赖 OpenCV(cv2) 与 moviepy 以实现水印去除与视频帧提取。
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Optional, Tuple, Union, Dict, Any
import logging

from PIL import Image, ExifTags
import subprocess
import shutil

# Windows：隐藏控制台窗口，防止子进程弹窗或因管道阻塞卡死
_SUBPROCESS_FLAGS: dict = {}
if hasattr(subprocess, "CREATE_NO_WINDOW"):
    _SUBPROCESS_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW
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


def _find_ffmpeg(name: str = "ffmpeg") -> Optional[str]:
    """在 PATH 和 Windows 常见安装位置中查找 ffmpeg/ffprobe 可执行文件。"""
    found = shutil.which(name)
    print(f"路径查找{name}: {found}")
    if found:
        return found
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg" / "bin",
            Path(os.environ.get("ProgramFiles", "")) / "ffmpeg" / "bin",
            Path("C:/ffmpeg/bin"),
            Path("D:/ffmpeg/bin"),
        ]
        suffix = ".exe"
        for d in candidates:
            p = d / (name + suffix)
            if p.is_file():
                return str(p)
    return None


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
        self._ffmpeg_path = _find_ffmpeg("ffmpeg")
        self.ffmpeg_available = self._ffmpeg_path is not None
        if not self.ffmpeg_available:
            self.logger.warning(
                "未检测到 ffmpeg，部分视频功能不可用。"
                "请安装 ffmpeg 并加入 PATH，或放置到 C:/ffmpeg/bin/"
            )

    def _resolve(self, path: Union[str, Path]) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.base_path / p
        return p

    _VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts", ".mpg", ".mpeg", ".3gp"}
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".ico", ".svg"}

    @staticmethod
    def _is_url(s: str) -> bool:
        from urllib.parse import urlparse
        try:
            r = urlparse(str(s))
            return r.scheme in ("http", "https")
        except Exception:
            return False

    @staticmethod
    def _ext_from_url(url: str) -> str:
        """从 URL 路径中提取文件扩展名。"""
        from urllib.parse import urlparse
        path = urlparse(url).path
        return Path(path).suffix.lower()

    def _probe_with_ffprobe(self, source: str) -> Optional[Dict[str, Any]]:
        """用 ffprobe 探测媒体源（本地路径或 URL），返回解析后的 JSON 或 None。"""
        import json as _json
        ffprobe = _find_ffmpeg("ffprobe")
        if not ffprobe:
            return None
        cmd = [
            ffprobe, "-v", "error",
            "-show_format", "-show_streams",
            "-print_format", "json",
            source,
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, errors="replace",
            **_SUBPROCESS_FLAGS,
        )
        if res.returncode == 0 and res.stdout.strip():
            return _json.loads(res.stdout)
        return None

    def _fill_video_info(self, base_info: Dict[str, Any], probe: Dict[str, Any]) -> None:
        """从 ffprobe JSON 结果中填充视频信息到 base_info。"""
        fmt = probe.get("format", {})
        base_info["format"] = fmt.get("format_long_name", fmt.get("format_name", ""))
        base_info["duration_sec"] = float(fmt.get("duration", 0))
        base_info["bit_rate"] = int(fmt.get("bit_rate", 0))
        for stream in probe.get("streams", []):
            codec_type = stream.get("codec_type", "")
            if codec_type == "video":
                base_info["video_codec"] = stream.get("codec_name", "")
                base_info["video_profile"] = stream.get("profile", "")
                base_info["width"] = stream.get("width", 0)
                base_info["height"] = stream.get("height", 0)
                base_info["video_bit_rate"] = int(stream.get("bit_rate", 0))
                base_info["frame_rate"] = stream.get("r_frame_rate", "")
                base_info["pix_fmt"] = stream.get("pix_fmt", "")
            elif codec_type == "audio":
                base_info["audio_codec"] = stream.get("codec_name", "")
                base_info["audio_sample_rate"] = stream.get("sample_rate", "")
                base_info["audio_channels"] = stream.get("channels", 0)
                base_info["audio_bit_rate"] = int(stream.get("bit_rate", 0))

    # 0) 获取媒体文件详细信息
    def get_media_info(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """获取媒体文件的详细信息。支持本地路径和 HTTP/HTTPS URL。

        视频：使用 ffprobe 获取完整编码信息（ffprobe 原生支持 URL，无需下载）。
        图片（本地）：使用 PIL 获取尺寸、格式、EXIF。
        图片（URL）：使用 ffprobe 获取基本信息。

        Returns:
            字典，包含 type（'video'/'image'）及各属性。
        """
        source = str(file_path)
        is_url = self._is_url(source)

        if is_url:
            ext = self._ext_from_url(source)
            base_info: Dict[str, Any] = {"source_url": source}
            # 从 URL 路径提取文件名
            from urllib.parse import urlparse
            url_path = urlparse(source).path
            base_info["file_name"] = Path(url_path).name or source

            probe = self._probe_with_ffprobe(source)
            if probe:
                # 根据流类型判断 type
                has_video = any(s.get("codec_type") == "video" for s in probe.get("streams", []))
                if has_video or ext in self._VIDEO_EXTS:
                    base_info["type"] = "video"
                elif ext in self._IMAGE_EXTS:
                    base_info["type"] = "image"
                else:
                    base_info["type"] = "video" if has_video else "unknown"
                self._fill_video_info(base_info, probe)
                # 文件大小从 format.size 获取
                fmt_size = probe.get("format", {}).get("size")
                if fmt_size:
                    base_info["file_size"] = int(fmt_size)
            else:
                base_info["type"] = "unknown"
                base_info["error"] = "ffprobe 不可用，无法探测远程媒体"
            return base_info

        # 本地文件
        p = self._resolve(file_path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")

        stat = p.stat()
        base_info = {
            "file_name": p.name,
            "file_size": stat.st_size,
            "absolute_path": str(p.resolve()),
        }
        ext = p.suffix.lower()

        if ext in self._VIDEO_EXTS:
            base_info["type"] = "video"
            probe = self._probe_with_ffprobe(str(p))
            if probe:
                self._fill_video_info(base_info, probe)
            else:
                try:
                    w, h = self.get_video_size(p)
                    base_info["width"] = w
                    base_info["height"] = h
                except Exception:
                    pass
                try:
                    dur = self.get_video_duration(p)
                    base_info["duration_sec"] = dur / 1000.0
                except Exception:
                    pass

        elif ext in self._IMAGE_EXTS:
            base_info["type"] = "image"
            try:
                with Image.open(p) as img:
                    base_info["width"] = img.width
                    base_info["height"] = img.height
                    base_info["image_format"] = img.format or ""
                    base_info["image_mode"] = img.mode
                    exif = self.get_exif(p)
                    if exif:
                        base_info["exif"] = exif
            except Exception as e:
                base_info["error"] = str(e)
        else:
            base_info["type"] = "unknown"

        return base_info

    # 1) 获取图片宽高
    def get_image_size(self, image_path: Union[str, Path]) -> Tuple[int, int]:
        p = self._resolve(image_path)
        if not p.exists():
            raise FileNotFoundError(f"图片不存在: {p}")
        with Image.open(p) as img:
            return img.width, img.height

    # 2) 视频某帧截图
    def extract_frame(self, video_path: Union[str, Path], time_sec: float, output_path: Optional[Union[str, Path]] = None, backend: str = "auto") -> Path:
        """从视频中提取指定时间点的一帧，支持本地路径和 URL。"""
        is_url = self._is_url(str(video_path))
        video_src = str(video_path) if is_url else str(self._resolve(video_path))

        if backend == "ffmpeg" or (backend == "auto" and self.ffmpeg_available):
            if not self.ffmpeg_available:
                raise RuntimeError("FFmpeg 未检测到，但请求使用 ffmpeg 后端进行帧提取")
            if output_path:
                out = Path(output_path)
            elif is_url:
                out = Path.cwd() / f"frame_{time_sec:.1f}s.png"
            else:
                out = Path(video_src).with_suffix(".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            cmd = [self._ffmpeg_path, "-y", "-ss", str(time_sec), "-i", video_src, "-frames:v", "1", "-f", "image2", str(out)]
            self.logger.info(f"使用 FFmpeg 提取帧: {cmd}")
            res = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **_SUBPROCESS_FLAGS,
            )
            if res.returncode != 0 or not out.exists():
                raise RuntimeError(f"FFmpeg 提取帧失败（returncode={res.returncode}）")
            self.logger.info(f"已从视频 {video_src} 在 {time_sec}s 处截取帧并保存到 {out}")
            return out
        else:
            if is_url:
                raise RuntimeError("MoviePy 后端不支持 URL，请确保 ffmpeg 可用")
            if not HAS_MOVIEPY:
                raise ImportError("需要安装 moviepy 才能使用 extract_frame，请执行: pip install moviepy")
            video_p = self._resolve(video_path)
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


    # 3) 获取视频时长（毫秒）
    def get_video_duration(self, video_path: Union[str, Path]) -> float:
        """获取视频时长（毫秒）。

        后端优先级：ffprobe → moviepy → cv2。

        Returns:
            时长（毫秒，浮点数）。
        Raises:
            FileNotFoundError: 视频文件不存在。
            RuntimeError: 三种后端均不可用。
        """
        video_p = self._resolve(video_path)
        if not video_p.exists():
            raise FileNotFoundError(f"视频不存在: {video_p}")

        # ① ffprobe（最轻量，不需要加载整个视频）
        ffprobe = _find_ffmpeg("ffprobe")
        if ffprobe:
            cmd = [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_p),
            ]
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                errors="replace",
                **_SUBPROCESS_FLAGS,
            )
            if res.returncode == 0 and res.stdout.strip():
                try:
                    # 解析 "123.456789" 秒字符串 → 直接组合整数毫秒，避免浮点乘法
                    s = res.stdout.strip()
                    int_part, _, frac_part = s.partition(".")
                    ms = int(int_part) * 1000 + int((frac_part + "000")[:3])
                    return float(ms)
                except (ValueError, IndexError):
                    pass

        # ② moviepy（无原生 ms API，round 取整避免浮点误差）
        if HAS_MOVIEPY:
            clip = VideoFileClip(str(video_p))
            ms = round(clip.duration * 1000)
            clip.close()
            return float(ms)

        # ③ cv2 — 跳到末尾，直接读 CAP_PROP_POS_MSEC（原生毫秒）
        if HAS_CV2:
            import cv2 as _cv2
            cap = _cv2.VideoCapture(str(video_p))
            cap.set(_cv2.CAP_PROP_POS_AVI_RATIO, 1.0)
            ms = cap.get(_cv2.CAP_PROP_POS_MSEC)
            cap.release()
            if ms > 0:
                return ms

        raise RuntimeError(
            f"无法获取视频时长 {video_p}，请安装 ffprobe、moviepy 或 cv2"
        )

    # 4a) 获取视频宽高
    def get_video_size(self, video_path: Union[str, Path]) -> Tuple[int, int]:
        """获取视频宽高（像素）。

        优先使用 ffprobe，回退到 cv2。

        Returns:
            (width, height)
        Raises:
            FileNotFoundError: 视频文件不存在。
            RuntimeError: 所有后端均不可用。
        """
        video_p = self._resolve(video_path)
        if not video_p.exists():
            raise FileNotFoundError(f"视频不存在: {video_p}")

        ffprobe = _find_ffmpeg("ffprobe")
        if ffprobe:
            cmd = [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                str(video_p),
            ]
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, errors="replace",
                **_SUBPROCESS_FLAGS,
            )
            if res.returncode == 0 and res.stdout.strip():
                parts = res.stdout.strip().split(",")
                if len(parts) >= 2:
                    try:
                        return int(parts[0]), int(parts[1])
                    except ValueError:
                        pass

        if HAS_CV2:
            import cv2 as _cv2
            cap = _cv2.VideoCapture(str(video_p))
            w = int(cap.get(_cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if w > 0 and h > 0:
                return w, h

        raise RuntimeError(f"无法获取视频尺寸 {video_p}，请安装 ffprobe 或 cv2")

    # 4b) 修复视频宽高奇数尺寸（H.264 要求偶数）
    def ensure_even_dimensions(self, video_path: Union[str, Path]) -> bool:
        """若视频宽或高为奇数，使用 ffmpeg crop 裁剪为偶数并原地覆盖。

        H.264/H.265 编码要求宽高均为偶数；奇数尺寸会导致部分播放器或上传平台报错。
        crop 滤镜 ``trunc(iw/2)*2:trunc(ih/2)*2`` 最多裁去各边 1 像素，画质无损失。

        Returns:
            True 表示文件已被修改，False 表示无需修改（宽高均已为偶数）。
        Raises:
            RuntimeError: ffmpeg 不可用，或转码失败。
        """
        video_p = self._resolve(video_path)
        w, h = self.get_video_size(video_p)
        if w % 2 == 0 and h % 2 == 0:
            return False

        if not self.ffmpeg_available:
            raise RuntimeError(
                f"视频 {video_p.name} 尺寸含奇数（{w}x{h}），但 ffmpeg 不可用，无法自动修复"
            )

        self.logger.info("视频尺寸含奇数（%dx%d），使用 ffmpeg 裁剪为偶数: %s", w, h, video_p.name)
        tmp = video_p.with_name(video_p.stem + "_even_tmp" + video_p.suffix)
        cmd = [
            self._ffmpeg_path, "-y",
            "-i", str(video_p),
            "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:a", "copy",
            str(tmp),
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_SUBPROCESS_FLAGS,
        )
        if res.returncode != 0 or not tmp.exists():
            if tmp.exists():
                tmp.unlink()
            raise RuntimeError(
                f"ffmpeg 裁剪奇数尺寸失败（returncode={res.returncode}）: {video_p.name}"
            )

        new_w = w - w % 2
        new_h = h - h % 2
        tmp.replace(video_p)
        self.logger.info("已修复奇数尺寸 %dx%d → %dx%d: %s", w, h, new_w, new_h, video_p.name)
        return True

    # 4) 缩放图片，支持保持纵横比并填充
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

    # 7) 读取 EXIF 元数据
    def get_exif(self, image_path: Union[str, Path]) -> Dict[str, Any]:
        """读取图片的 EXIF 元数据，返回 {标签名: 值} 字典。若图片无 EXIF 则返回空字典。"""
        p = self._resolve(image_path)
        if not p.exists():
            raise FileNotFoundError(f"图片不存在: {p}")
        with Image.open(p) as img:
            raw_exif = img.getexif()
            result: Dict[str, Any] = {}
            for tag_id, value in raw_exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="replace")
                    except Exception:
                        value = repr(value)
                result[tag_name] = value
        self.logger.info(f"读取 EXIF：{p}，共 {len(result)} 个标签")
        return result

    # 8) 清除 EXIF 元数据
    def clear_exif(self, input_path: Union[str, Path], output_path: Optional[Union[str, Path]] = None) -> Path:
        """清除图片所有 EXIF 元数据，默认输出为 *_noexif.* 文件。"""
        in_p = self._resolve(input_path)
        if not in_p.exists():
            raise FileNotFoundError(f"图片不存在: {in_p}")
        out_p = self._resolve(output_path) if output_path else in_p.parent / (in_p.stem + "_noexif" + in_p.suffix)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(in_p) as img:
            fmt = img.format or out_p.suffix.lstrip(".").upper() or "JPEG"
            img.save(out_p, format=fmt, exif=b"")
        self.logger.info(f"已清除 EXIF：{in_p} -> {out_p}")
        return out_p

    # 9) 写入/更新 EXIF 元数据
    def set_exif(self, input_path: Union[str, Path], tags: Dict[str, Any], output_path: Optional[Union[str, Path]] = None) -> Path:
        """更新图片 EXIF 标签。tags 为 {标签名或标签ID: 值} 字典。
        支持常用标签名如 'DateTime'、'Artist'、'Copyright'、'ImageDescription'。
        需要安装 piexif：pip install piexif
        """
        try:
            import piexif  # type: ignore
        except ImportError:
            raise ImportError("set_exif 需要 piexif 库，请执行: pip install piexif")
        in_p = self._resolve(input_path)
        if not in_p.exists():
            raise FileNotFoundError(f"图片不存在: {in_p}")
        out_p = self._resolve(output_path) if output_path else in_p.parent / (in_p.stem + "_exif" + in_p.suffix)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        name_to_id = {v: k for k, v in ExifTags.TAGS.items()}
        try:
            exif_dict = piexif.load(str(in_p))
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

        for tag_key, value in tags.items():
            tag_id = name_to_id.get(tag_key, tag_key) if isinstance(tag_key, str) else tag_key
            if isinstance(value, str):
                value = value.encode("utf-8")
            exif_dict["0th"][tag_id] = value

        exif_bytes = piexif.dump(exif_dict)
        with Image.open(in_p) as img:
            fmt = img.format or out_p.suffix.lstrip(".").upper() or "JPEG"
            img.save(out_p, format=fmt, exif=exif_bytes)
        self.logger.info(f"已更新 EXIF 标签 {list(tags.keys())}：{in_p} -> {out_p}")
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
