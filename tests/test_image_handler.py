import os
import tempfile
import shutil
from pathlib import Path

import pytest

from daily_py.image_handler import ImageHandler
try:
    from daily_py.image_handler import HAS_CV2, HAS_MOVIEPY
except Exception:
    HAS_CV2 = False
    HAS_MOVIEPY = False


class TestImageHandler:
    @pytest.fixture
    def ih(self):
        return ImageHandler()

    @pytest.fixture
    def tmpdir(self):
        d = Path(tempfile.mkdtemp())
        yield d
        shutil.rmtree(d)

    def test_get_image_size(self, ih: ImageHandler, tmpdir: Path):
        img_path = tmpdir / "test.png"
        # create simple image 64x48
        from PIL import Image
        im = Image.new("RGB", (64, 48), color=(255, 0, 0))
        im.save(img_path)
        w, h = ih.get_image_size(img_path)
        assert (w, h) == (64, 48)

    def test_resize_image(self, ih: ImageHandler, tmpdir: Path):
        img_path = tmpdir / "test2.png"
        from PIL import Image
        Image.new("RGB", (200, 100), color=(0, 255, 0)).save(img_path)
        out_path = tmpdir / "resized.png"
        ih.resize_image(img_path, out_path, (100, 100), keep_aspect=True)
        from PIL import Image as PILImage
        with PILImage.open(out_path) as im:
            assert im.size == (100, 100)

    def test_compress_image(self, ih: ImageHandler, tmpdir: Path):
        img_path = tmpdir / "compress_me.jpg"
        from PIL import Image
        Image.new("RGB", (800, 600), color=(123, 222, 123)).save(img_path, format="JPEG", quality=95)
        out_path = tmpdir / "compress_me_out.jpg"
        ih.compress_image(img_path, out_path, quality=20)
        assert out_path.exists()
        assert out_path.stat().st_size <= img_path.stat().st_size

    @pytest.mark.skipif(not HAS_CV2, reason="cv2 not installed")
    def test_remove_watermark_with_cv2(self, ih: ImageHandler, tmpdir: Path):
        # 简单图片+水印区域，确保方法可执行
        import numpy as np
        import cv2
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.rectangle(img, (0, 0), (20, 20), (255, 255, 255), -1)
        in_path = tmpdir / "watermark.png"
        cv2.imwrite(str(in_path), img)
        out_path = tmpdir / "watermark_no.png"
        ih.remove_watermark(in_path, out_path, bbox=(0, 0, 20, 20), inpaint_radius=3)
        assert out_path.exists()

    @pytest.mark.skipif(not HAS_MOVIEPY, reason="moviepy not installed")
    def test_extract_frame_stub(self, ih: ImageHandler, tmpdir: Path):
        # 测试提取帧功能，若 moviepy 未安装则跳过
        pass
