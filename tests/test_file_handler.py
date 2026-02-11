import pytest
import tempfile
import shutil
from pathlib import Path

from daily_py import FileHandler


class TestFileHandler:
    @pytest.fixture
    def fh(self):
        return FileHandler()

    @pytest.fixture
    def tmpdir(self):
        d = Path(tempfile.mkdtemp())
        yield d
        shutil.rmtree(d)

    def test_delete_file(self, fh: FileHandler, tmpdir: Path):
        p = tmpdir / "a.txt"
        p.write_text("hello", encoding="utf-8")
        assert p.exists()
        assert fh.delete_file(p) is True
        assert not p.exists()

    def test_rename_file(self, fh: FileHandler, tmpdir: Path):
        p = tmpdir / "a.txt"
        p.write_text("x", encoding="utf-8")
        newp = tmpdir / "b.txt"
        assert fh.rename_file(p, newp) is True
        assert newp.exists()
        assert not p.exists()

    def test_copy_and_move(self, fh: FileHandler, tmpdir: Path):
        src = tmpdir / "src.txt"
        src.write_text("data", encoding="utf-8")
        dst = tmpdir / "dst.txt"
        fh.copy_file(src, dst)
        assert dst.exists()
        moved_to = tmpdir / "sub" / "dst2.txt"
        moved_to.parent.mkdir(parents=True, exist_ok=True)
        fh.move_file(dst, moved_to)
        assert moved_to.exists()
        assert not dst.exists()

    def test_list_and_info(self, fh: FileHandler, tmpdir: Path):
        (tmpdir / "f1.txt").write_text("1", encoding="utf-8")
        (tmpdir / "f2.txt").write_text("2", encoding="utf-8")
        files = fh.list_files(tmpdir, pattern="*.txt")
        assert len(files) == 2
        info = fh.get_file_info(tmpdir / "f1.txt")
        assert info["name"] == "f1.txt"
