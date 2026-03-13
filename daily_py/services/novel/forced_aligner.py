"""强制对齐工具：音频 + 文本 → 词级时间戳（JSON / SRT / VTT）。

使用 Qwen3-ForcedAligner-0.6B 模型对已知文本与配音音频做强制对齐，
输出每个词/字的精确起止时间，供 App 实现文字自动滚动。

Usage::

    # 单文件
    python -m daily_py.services.novel.forced_aligner audio.mp3 text.txt -o output/

    # 批量（按文件名 stem 匹配）
    python -m daily_py.services.novel.forced_aligner --audio-dir audios/ --text-dir texts/ -o output/
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"}
_SENTENCE_ENDINGS = set("。！？.!?")

# 长音频分段参数
_MAX_SEGMENT_SEC = 240.0   # 单段上限 4 分钟（模型限制 5 分钟，留余量）
_SILENCE_DB = -30          # 静音检测阈值 dB
_MIN_SILENCE_SEC = 0.3     # 最短静音时长（秒）
_TEXT_BUFFER_RATIO = 0.8   # 每段文本的前向缓冲比例（80%）

# Windows 下隐藏控制台窗口
_SUBPROCESS_FLAGS: dict = {}
if hasattr(subprocess, "CREATE_NO_WINDOW"):
    _SUBPROCESS_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class AlignedWord:
    """单个词/字的对齐结果。"""
    word: str
    start: float  # 秒
    end: float    # 秒


@dataclass
class AlignmentResult:
    """单个文件的对齐结果。"""
    audio_file: str
    text_file: str
    words: List[AlignedWord] = field(default_factory=list)
    output_json: str = ""
    output_srt: str = ""
    output_vtt: str = ""
    success: bool = False
    skipped: bool = False
    error: str = ""

    def __str__(self) -> str:
        if self.success:
            return f"[OK]   {self.audio_file} ({len(self.words)} words)"
        if self.skipped:
            return f"[SKIP] {self.audio_file}  {self.error}"
        return f"[ERR]  {self.audio_file}  {self.error}"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str:
    """依次尝试 utf-8 / utf-8-sig / gbk 读取文本。"""
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=enc).strip()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise UnicodeDecodeError("utf-8/gbk", b"", 0, 1, f"无法解码文件: {path}")


def _fmt_duration(seconds: float) -> str:
    """格式化秒数为 mm:ss。"""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _ts_srt(seconds: float) -> str:
    """SRT 时间格式: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _ts_vtt(seconds: float) -> str:
    """VTT 时间格式: MM:SS.mmm"""
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:06.3f}"


def group_words_into_segments(
    words: List[AlignedWord],
    max_chars: int = 40,
) -> List[Tuple[float, float, str]]:
    """将词列表分段，用于 SRT/VTT 字幕。

    分段规则：
    1. 遇到句末标点（。！？.!?）立即结束当前段
    2. 当前段字符数超过 max_chars 时结束
    3. 返回 (start_sec, end_sec, text) 列表
    """
    if not words:
        return []

    segments: List[Tuple[float, float, str]] = []
    seg_start = words[0].start
    seg_text = ""
    seg_end = words[0].end

    for w in words:
        seg_text += w.word
        seg_end = w.end

        # 在句末标点或达到字数上限时切段
        ends_with_punct = w.word and w.word[-1] in _SENTENCE_ENDINGS
        if ends_with_punct or len(seg_text) >= max_chars:
            segments.append((seg_start, seg_end, seg_text))
            seg_text = ""
            seg_start = seg_end  # 下一段从这里开始

    # 剩余文本
    if seg_text:
        segments.append((seg_start, seg_end, seg_text))

    return segments


# ---------------------------------------------------------------------------
# 核心类
# ---------------------------------------------------------------------------

class ForcedAligner:
    """强制对齐处理器。

    Parameters
    ----------
    model_path : str
        HuggingFace 模型路径或本地目录。
    device : str
        推理设备，"cpu" 或 "cuda"。
    progress_callback : callable, optional
        接收进度消息的回调函数 ``(str) -> None``。
    """

    def __init__(
        self,
        model_path: str = "Qwen/Qwen3-ForcedAligner-0.6B",
        device: str = "cpu",
        language: str = "Chinese",
        logger: Optional[logging.Logger] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._model_path = model_path
        self._device = device
        self._language = language
        self._log = logger or logging.getLogger(__name__)
        self._progress = progress_callback or self._log.info
        self._model = None

    # ---- 模型管理 ----

    def load_model(self) -> None:
        """加载 Qwen3ForcedAligner（懒加载，首次 align 时自动调用）。"""
        if self._model is not None:
            return
        try:
            import torch  # noqa: F401
            from qwen_asr import Qwen3ForcedAligner
        except ImportError:
            raise ImportError(
                "需要 torch 和 qwen-asr 库。\n"
                "安装命令: pip install torch qwen-asr"
            )

        self._progress(f"加载模型: {self._model_path} (device={self._device})...")
        dtype = torch.float32 if self._device == "cpu" else torch.bfloat16
        self._model = Qwen3ForcedAligner.from_pretrained(
            self._model_path,
            dtype=dtype,
            device_map=self._device,
        )
        self._progress("模型加载完成。")

    # ---- 对齐推理（单段） ----

    def _run_alignment(self, audio_path: str, text: str) -> List[AlignedWord]:
        """调用模型的 align 方法，返回词级时间戳（适用于 ≤5 分钟音频）。"""
        results = self._model.align(
            audio=audio_path,
            text=text,
            language=self._language,
        )

        # results 是 list of list of segment，取第一个音频的结果
        if not results or not results[0]:
            return []

        words: List[AlignedWord] = []
        for seg in results[0]:
            words.append(AlignedWord(
                word=seg.text,
                start=seg.start_time,
                end=seg.end_time,
            ))
        return words

    # ---- 长音频分段对齐 ----

    @staticmethod
    def _find_tool(name: str) -> str:
        path = shutil.which(name)
        if not path:
            raise RuntimeError(f"长音频分段需要 {name}，但未在 PATH 中找到")
        return path

    def _get_audio_duration(self, audio_path: str) -> float:
        """用 ffprobe 获取音频总时长（秒）。"""
        ffprobe = self._find_tool("ffprobe")
        cmd = [
            ffprobe, "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0", audio_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, **_SUBPROCESS_FLAGS)
        if res.returncode != 0:
            raise RuntimeError(f"ffprobe 失败: {res.stderr.strip()}")
        return float(res.stdout.strip())

    def _detect_silences(self, audio_path: str) -> List[Tuple[float, float]]:
        """用 ffmpeg silencedetect 检测静音区间，返回 [(start, end), ...]。"""
        ffmpeg = self._find_tool("ffmpeg")
        cmd = [
            ffmpeg, "-i", audio_path,
            "-af", f"silencedetect=noise={_SILENCE_DB}dB:d={_MIN_SILENCE_SEC}",
            "-f", "null", "-",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, **_SUBPROCESS_FLAGS)
        stderr = res.stderr

        # 解析 silence_start / silence_end
        starts = [float(m.group(1)) for m in re.finditer(r"silence_start:\s*([\d.]+)", stderr)]
        ends = [float(m.group(1)) for m in re.finditer(r"silence_end:\s*([\d.]+)", stderr)]

        silences: List[Tuple[float, float]] = []
        for i, s in enumerate(starts):
            e = ends[i] if i < len(ends) else s + _MIN_SILENCE_SEC
            silences.append((s, e))
        return silences

    def _build_segments(
        self, total_duration: float, silences: List[Tuple[float, float]],
        max_seg: float = _MAX_SEGMENT_SEC,
    ) -> List[Tuple[float, float]]:
        """根据静音点构建 ≤ max_seg 秒的分段列表 [(start, end), ...]。

        策略：从上一个切割点开始，找最后一个在 max_seg 范围内的静音中点作为切割点。
        """
        if total_duration <= max_seg:
            return [(0.0, total_duration)]

        # 静音中点作为候选切割点
        cut_candidates = sorted(set((s + e) / 2 for s, e in silences))

        segments: List[Tuple[float, float]] = []
        seg_start = 0.0

        while seg_start < total_duration - 1.0:
            seg_end_limit = seg_start + max_seg

            if seg_end_limit >= total_duration:
                segments.append((seg_start, total_duration))
                break

            # 在 [seg_start, seg_end_limit] 范围内找最后一个切割点
            best_cut = None
            for c in cut_candidates:
                if seg_start + 30 < c <= seg_end_limit:  # 至少 30s 的段
                    best_cut = c

            if best_cut is None:
                # 没有合适的静音点，强制按 max_seg 切
                best_cut = seg_end_limit

            segments.append((seg_start, best_cut))
            seg_start = best_cut

        return segments

    def _extract_audio_segment(self, src: str, start: float, end: float, dst: str) -> None:
        """用 ffmpeg 提取音频片段 [start, end)。"""
        ffmpeg = self._find_tool("ffmpeg")
        cmd = [
            ffmpeg, "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", src,
            "-c", "copy",
            dst,
        ]
        res = subprocess.run(
            cmd, capture_output=True, text=True, **_SUBPROCESS_FLAGS,
        )
        if res.returncode != 0:
            raise RuntimeError(f"提取音频片段失败: {res.stderr.strip()}")

    def _align_long_audio(self, audio_path: str, text: str) -> List[AlignedWord]:
        """自动分段对齐长音频（>4 分钟）。

        流程：
        1. ffprobe 获取总时长
        2. ffmpeg silencedetect 找静音点
        3. 在静音点切割，每段 ≤ 4 分钟
        4. 每段用比例估算 + 前向缓冲分配文本
        5. 分段对齐后按时间戳有效性确定文本消耗量
        6. 合并所有结果（时间戳加偏移）
        """
        total_duration = self._get_audio_duration(audio_path)
        self._progress(f"音频总时长: {_fmt_duration(total_duration)}")

        if total_duration <= _MAX_SEGMENT_SEC:
            self._progress("音频 ≤ 4 分钟，直接对齐。")
            return self._run_alignment(audio_path, text)

        # 检测静音并构建分段
        self._progress("检测静音点...")
        silences = self._detect_silences(audio_path)
        segments = self._build_segments(total_duration, silences)
        self._progress(f"分为 {len(segments)} 段: "
                       + ", ".join(f"{_fmt_duration(s)}-{_fmt_duration(e)}" for s, e in segments))

        all_words: List[AlignedWord] = []
        text_pos = 0  # 当前文本消耗位置（字符索引）
        total_text_len = len(text)

        for idx, (seg_start, seg_end) in enumerate(segments):
            seg_dur = seg_end - seg_start
            seg_label = f"[{idx + 1}/{len(segments)}] {_fmt_duration(seg_start)}-{_fmt_duration(seg_end)}"
            self._progress(f"--- 分段 {seg_label} ---")

            # 估算本段对应的文本长度（按时间比例 + 前向缓冲）
            ratio = seg_dur / total_duration
            est_chars = int(total_text_len * ratio)
            buffer_chars = int(est_chars * _TEXT_BUFFER_RATIO)
            chunk_end = min(total_text_len, text_pos + est_chars + buffer_chars)

            # 最后一段：用剩余全部文本
            if idx == len(segments) - 1:
                chunk_end = total_text_len

            chunk_text = text[text_pos:chunk_end]
            if not chunk_text.strip():
                self._progress(f"  跳过（无剩余文本）")
                continue

            self._progress(f"  文本范围: [{text_pos}:{chunk_end}] ({len(chunk_text)} 字)")

            # 提取音频片段到临时文件
            suffix = Path(audio_path).suffix or ".wav"
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(tmp_fd)
            try:
                self._extract_audio_segment(audio_path, seg_start, seg_end, tmp_path)

                # 对齐本段
                seg_words = self._run_alignment(tmp_path, chunk_text)
                self._progress(f"  对齐得到 {len(seg_words)} 个词")

                if not seg_words:
                    self._progress(f"  警告: 本段未产生对齐结果")
                    continue

                # 筛选有效词：时间戳在 [0, seg_dur] 内且 start != end
                valid_words: List[AlignedWord] = []
                consumed_chars = 0
                for w in seg_words:
                    in_range = -0.5 <= w.start <= seg_dur + 0.5
                    has_span = abs(w.end - w.start) > 0.001
                    if in_range and has_span:
                        valid_words.append(AlignedWord(
                            word=w.word,
                            start=round(w.start + seg_start, 3),
                            end=round(w.end + seg_start, 3),
                        ))
                        consumed_chars += len(w.word)
                    elif in_range:
                        # start == end 但在范围内，可能是短词，保留但标记
                        valid_words.append(AlignedWord(
                            word=w.word,
                            start=round(w.start + seg_start, 3),
                            end=round(w.end + seg_start, 3),
                        ))
                        consumed_chars += len(w.word)

                self._progress(
                    f"  有效词: {len(valid_words)}, 消耗文本: {consumed_chars} 字"
                )

                all_words.extend(valid_words)

                # 推进文本游标
                if consumed_chars > 0:
                    text_pos += consumed_chars
                else:
                    # 如果没有有效词，按比例推进（防止卡住）
                    text_pos += est_chars

            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        self._progress(f"分段对齐完成，共 {len(all_words)} 个词")
        return all_words

    # ---- 输出写入 ----

    def _write_json(
        self, result: AlignmentResult, output_dir: Path, audio_path: str, text_path: str,
    ) -> str:
        stem = Path(audio_path).stem
        out = output_dir / f"{stem}.align.json"
        data = {
            "audio": Path(audio_path).name,
            "text": Path(text_path).name,
            "word_count": len(result.words),
            "words": [
                {"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3)}
                for w in result.words
            ],
        }
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(out)

    def _write_srt(
        self, words: List[AlignedWord], output_dir: Path, stem: str, max_chars: int,
    ) -> str:
        out = output_dir / f"{stem}.srt"
        segments = group_words_into_segments(words, max_chars=max_chars)
        lines: List[str] = []
        for i, (start, end, text) in enumerate(segments, 1):
            lines.append(str(i))
            lines.append(f"{_ts_srt(start)} --> {_ts_srt(end)}")
            lines.append(text)
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        return str(out)

    def _write_vtt(
        self, words: List[AlignedWord], output_dir: Path, stem: str, max_chars: int,
    ) -> str:
        out = output_dir / f"{stem}.vtt"
        segments = group_words_into_segments(words, max_chars=max_chars)
        lines: List[str] = ["WEBVTT", ""]
        for start, end, text in segments:
            lines.append(f"{_ts_vtt(start)} --> {_ts_vtt(end)}")
            lines.append(text)
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        return str(out)

    # ---- 文件匹配 ----

    @staticmethod
    def find_matching_pairs(
        audio_dir: Path, text_dir: Path,
    ) -> Tuple[List[Tuple[Path, Path]], List[Path], List[Path]]:
        """按文件名 stem 匹配音频和文本。

        Returns
        -------
        matched : list of (audio_path, text_path)
        unmatched_audio : 无对应文本的音频
        unmatched_text : 无对应音频的文本
        """
        audio_files = {
            f.stem: f for f in sorted(audio_dir.iterdir())
            if f.is_file() and f.suffix.lower() in _AUDIO_EXTS
        }
        text_files = {
            f.stem: f for f in sorted(text_dir.iterdir())
            if f.is_file() and f.suffix.lower() == ".txt"
        }

        matched = []
        for stem in sorted(audio_files):
            if stem in text_files:
                matched.append((audio_files[stem], text_files[stem]))

        unmatched_audio = [audio_files[s] for s in sorted(audio_files) if s not in text_files]
        unmatched_text = [text_files[s] for s in sorted(text_files) if s not in audio_files]

        return matched, unmatched_audio, unmatched_text

    # ---- 主要 API ----

    def align(
        self,
        audio_path: str,
        text_path: str,
        output_dir: str,
        *,
        formats: Sequence[str] = ("json", "srt", "vtt"),
        srt_max_chars: int = 40,
    ) -> AlignmentResult:
        """对单个音频+文本执行强制对齐。"""
        result = AlignmentResult(audio_file=audio_path, text_file=text_path)

        try:
            self.load_model()

            a_path = Path(audio_path)
            t_path = Path(text_path)
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            text = _read_text(t_path)
            if not text:
                result.error = "文本文件为空"
                return result

            self._progress(f"对齐中: {a_path.name} ...")
            result.words = self._align_long_audio(str(a_path), text)

            if not result.words:
                result.error = "对齐未产生任何词级时间戳"
                return result

            stem = a_path.stem
            fmt_set = set(f.lower() for f in formats)
            if "json" in fmt_set:
                result.output_json = self._write_json(result, out_dir, audio_path, text_path)
            if "srt" in fmt_set:
                result.output_srt = self._write_srt(result.words, out_dir, stem, srt_max_chars)
            if "vtt" in fmt_set:
                result.output_vtt = self._write_vtt(result.words, out_dir, stem, srt_max_chars)

            result.success = True
            self._progress(f"完成: {a_path.name} → {len(result.words)} words")

        except Exception as exc:
            result.error = str(exc)
            self._log.exception("对齐 %s 时出错", audio_path)

        return result

    def batch_align(
        self,
        audio_dir: str,
        text_dir: str,
        output_dir: str,
        *,
        formats: Sequence[str] = ("json", "srt", "vtt"),
        srt_max_chars: int = 40,
    ) -> List[AlignmentResult]:
        """批量对齐：按文件名 stem 匹配音频与文本。"""
        a_dir = Path(audio_dir)
        t_dir = Path(text_dir)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        matched, unmatched_a, unmatched_t = self.find_matching_pairs(a_dir, t_dir)

        for f in unmatched_a:
            self._progress(f"[跳过] 无对应文本: {f.name}")
        for f in unmatched_t:
            self._progress(f"[跳过] 无对应音频: {f.name}")

        if not matched:
            self._progress("未找到匹配的音频-文本对。")
            return []

        self._progress(f"找到 {len(matched)} 对匹配文件，开始对齐...")
        self.load_model()

        results: List[AlignmentResult] = []
        for i, (a_path, t_path) in enumerate(matched, 1):
            self._progress(f"--- [{i}/{len(matched)}] {a_path.name} ---")
            r = self.align(
                str(a_path), str(t_path), str(out_dir),
                formats=formats, srt_max_chars=srt_max_chars,
            )
            results.append(r)
            self._progress(str(r))

        self._print_summary(results)
        return results

    def _print_summary(self, results: List[AlignmentResult]) -> None:
        ok = [r for r in results if r.success]
        skipped = [r for r in results if r.skipped]
        failed = [r for r in results if not r.success and not r.skipped]

        sep = "=" * 60
        self._progress(sep)
        self._progress(
            f"完成  成功 {len(ok)} / 跳过 {len(skipped)} / 失败 {len(failed)} / 共 {len(results)}"
        )
        if failed:
            self._progress("失败项:")
            for r in failed:
                self._progress(f"  {r.audio_file}  {r.error}")
        self._progress(sep)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main() -> None:
    import argparse

    _setup_logging()

    parser = argparse.ArgumentParser(
        prog="forced_aligner",
        description="强制对齐：音频 + 文本 → 词级时间戳 (JSON/SRT/VTT)",
    )
    # 单文件模式
    parser.add_argument("audio_file", nargs="?", help="音频文件路径")
    parser.add_argument("text_file", nargs="?", help="文本文件路径")
    # 批量模式
    parser.add_argument("--audio-dir", help="音频文件夹（批量模式）")
    parser.add_argument("--text-dir", help="文本文件夹（批量模式）")
    # 通用参数
    parser.add_argument("-o", "--output-dir", required=True, help="输出目录")
    parser.add_argument(
        "--formats", nargs="+", default=["json", "srt", "vtt"],
        choices=["json", "srt", "vtt"], help="输出格式（默认全部）",
    )
    parser.add_argument("--srt-max-chars", type=int, default=40, help="SRT/VTT 每行最大字数")
    parser.add_argument("--model", default="Qwen/Qwen3-ForcedAligner-0.6B", help="模型路径")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="推理设备")
    parser.add_argument(
        "--language", default="Chinese",
        choices=["Chinese", "English", "Japanese", "Korean",
                 "French", "German", "Italian", "Portuguese",
                 "Russian", "Spanish", "Cantonese"],
        help="音频语言（默认 Chinese）",
    )

    args = parser.parse_args()

    aligner = ForcedAligner(
        model_path=args.model, device=args.device, language=args.language,
    )

    if args.audio_dir and args.text_dir:
        results = aligner.batch_align(
            args.audio_dir, args.text_dir, args.output_dir,
            formats=tuple(args.formats), srt_max_chars=args.srt_max_chars,
        )
        sys.exit(0 if all(r.success or r.skipped for r in results) else 1)
    elif args.audio_file and args.text_file:
        r = aligner.align(
            args.audio_file, args.text_file, args.output_dir,
            formats=tuple(args.formats), srt_max_chars=args.srt_max_chars,
        )
        sys.exit(0 if r.success else 1)
    else:
        parser.error("请指定 audio_file + text_file（单文件）或 --audio-dir + --text-dir（批量）")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # ===== IDE 直接运行：在此填写参数 =====
        AUDIO_DIR = r"D:\audios"
        TEXT_DIR = r"D:\texts"
        OUTPUT_DIR = r"D:\output\timestamps"
        MODEL = "Qwen/Qwen3-ForcedAligner-0.6B"
        # ======================================

        _setup_logging()
        aligner = ForcedAligner(model_path=MODEL)
        aligner.batch_align(AUDIO_DIR, TEXT_DIR, OUTPUT_DIR)
