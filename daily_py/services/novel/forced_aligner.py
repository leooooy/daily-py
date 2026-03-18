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

import difflib
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
_MAX_SEGMENT_SEC = 240.0       # 直接对齐：单段上限 4 分钟
_MAX_ASR_SEGMENT_SEC = 120.0   # ASR 引导对齐：单段上限 2 分钟（更短 = 更精确）
_SILENCE_DB = -30              # 静音检测阈值 dB
_MIN_SILENCE_SEC = 0.3         # 最短静音时长（秒）
_TEXT_BUFFER_RATIO = 0.8       # 每段文本的前向缓冲比例（80%）

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
            min_seg = min(30.0, max_seg * 0.25)  # 最短段：30s 或 max_seg 的 25%
            best_cut = None
            for c in cut_candidates:
                if seg_start + min_seg < c <= seg_end_limit:
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

    # ---- ASR 引导的长音频分段对齐 ----

    @staticmethod
    def _map_asr_to_original(
        asr_words: List[AlignedWord], original_text: str,
    ) -> List[AlignedWord]:
        """将 ASR 对齐结果的时间戳映射到原始文本的每个字。

        使用 difflib.SequenceMatcher 对 ASR 识别文本与原始文本做序列对齐，
        将 ASR 每个字符的时间戳映射到原始文本对应字符上。
        """
        if not asr_words:
            return []

        asr_text = "".join(w.word for w in asr_words)

        # 构建 ASR 文本每个字符的时间戳索引
        char_timestamps: List[Tuple[float, float]] = []
        for w in asr_words:
            for _ in w.word:
                char_timestamps.append((w.start, w.end))

        # 序列对齐
        sm = difflib.SequenceMatcher(None, asr_text, original_text, autojunk=False)
        result: List[AlignedWord] = []

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(j2 - j1):
                    ts = char_timestamps[i1 + k]
                    result.append(AlignedWord(original_text[j1 + k], ts[0], ts[1]))
            elif tag == "replace":
                # ASR 识别错误的字，用对应区间的时间戳均匀分配
                orig_len = j2 - j1
                ts_start = char_timestamps[i1][0]
                ts_end = char_timestamps[min(i2, len(char_timestamps)) - 1][1]
                span = ts_end - ts_start
                for k in range(orig_len):
                    t0 = ts_start + span * k / orig_len
                    t1 = ts_start + span * (k + 1) / orig_len
                    result.append(AlignedWord(
                        original_text[j1 + k], round(t0, 3), round(t1, 3),
                    ))
            elif tag == "insert":
                # 原文有但 ASR 没识别到的字（如标点），继承前一个时间戳
                if result:
                    ts = (result[-1].end, result[-1].end)
                elif i1 < len(char_timestamps):
                    ts = char_timestamps[i1]
                else:
                    ts = (0.0, 0.0)
                for j in range(j1, j2):
                    result.append(AlignedWord(original_text[j], ts[0], ts[1]))
            # tag == "delete": ASR 多出的字，丢弃

        return result

    @staticmethod
    def _merge_chars_to_words(chars: List[AlignedWord]) -> List[AlignedWord]:
        """将字符级对齐结果合并为单词级。

        1. 按空白分组为 word_chars 列表
        2. 每组剥离首尾标点，用剥离后首字符 start / 末字符 end 作为单词时间戳
        3. 平滑零时长词（start==end）：在前后有效词之间插值
        """
        if not chars:
            return []

        # 第一步：按空白分组
        groups: List[List[AlignedWord]] = []
        current: List[AlignedWord] = []
        for ch in chars:
            if ch.word in (" ", "\n", "\r", "\t"):
                if current:
                    groups.append(current)
                    current = []
            else:
                current.append(ch)
        if current:
            groups.append(current)

        # 第二步：每组剥离首尾标点，取时间戳
        words: List[AlignedWord] = []
        for grp in groups:
            # 剥离前导标点
            while grp and not grp[0].word.isalnum():
                grp = grp[1:]
            # 剥离尾部标点
            while grp and not grp[-1].word.isalnum():
                grp = grp[:-1]
            if not grp:
                continue
            text = "".join(c.word for c in grp)
            if not any(c.isalnum() for c in text):
                continue
            words.append(AlignedWord(text, grp[0].start, grp[-1].end))

        # 第三步：平滑零时长词（start == end 或时长 < 0.01s）
        # 在前后有效词之间线性插值
        for i, w in enumerate(words):
            if abs(w.end - w.start) >= 0.01:
                continue
            # 找前一个有效词的 end
            prev_end = None
            for j in range(i - 1, -1, -1):
                if abs(words[j].end - words[j].start) >= 0.01:
                    prev_end = words[j].end
                    break
            # 找后一个有效词的 start
            next_start = None
            for j in range(i + 1, len(words)):
                if abs(words[j].end - words[j].start) >= 0.01:
                    next_start = words[j].start
                    break
            if prev_end is not None and next_start is not None:
                # 在 [prev_end, next_start] 区间内，按比例分配给连续的零时长词
                # 先找连续零时长词的范围
                zero_start = i
                while zero_start > 0 and abs(words[zero_start - 1].end - words[zero_start - 1].start) < 0.01:
                    zero_start -= 1
                zero_end = i
                while zero_end < len(words) - 1 and abs(words[zero_end + 1].end - words[zero_end + 1].start) < 0.01:
                    zero_end += 1
                n = zero_end - zero_start + 1
                span = next_start - prev_end
                for k in range(n):
                    idx = zero_start + k
                    words[idx].start = round(prev_end + span * k / n, 3)
                    words[idx].end = round(prev_end + span * (k + 1) / n, 3)

        return words

    def _load_asr_model(self, asr_model_path: str):
        """加载 ASR 模型并返回。"""
        import torch
        from qwen_asr import Qwen3ASRModel

        self._progress(f"加载 ASR 模型: {asr_model_path} ...")
        dtype = torch.float32 if self._device == "cpu" else torch.bfloat16
        asr_model = Qwen3ASRModel.from_pretrained(
            asr_model_path, dtype=dtype, device_map=self._device,
        )
        self._progress("ASR 模型加载完成。")
        return asr_model

    def _asr_transcribe_segment(self, asr_model, audio_path: str) -> str:
        """用 ASR 模型识别单段音频，返回文本。"""
        results = asr_model.transcribe(audio=audio_path, language=self._language)
        if not results or not results[0].text.strip():
            return ""
        return results[0].text

    def _fix_segment_alignment(
        self, words: List[AlignedWord], seg_dur: float,
    ) -> List[AlignedWord]:
        """修复段内对齐尾部失效：用已对齐部分的语速推算零时长词。

        对齐模型经常在段尾停止产生有效时间戳，导致后面的词全部
        start==end 塌缩到同一时间点。本方法检测这种情况，用已对齐
        部分的平均字符速率（chars/sec）来外推剩余词的时间戳。
        """
        if not words:
            return words

        # 找最后一个有效词（duration >= 0.01s）的索引
        last_valid = -1
        valid_chars = 0
        valid_end = 0.0
        for i, w in enumerate(words):
            if abs(w.end - w.start) >= 0.01:
                last_valid = i
                valid_chars += len(w.word)
                valid_end = w.end

        if last_valid < 0:
            # 全部失效，按段时长均匀分配
            total_chars = sum(len(w.word) for w in words)
            if total_chars == 0:
                return words
            pos = 0.0
            for w in words:
                c = len(w.word)
                w.start = round(pos, 3)
                pos += seg_dur * c / total_chars
                w.end = round(pos, 3)
            return words

        tail_count = len(words) - last_valid - 1
        if tail_count == 0:
            return words  # 没有尾部失效

        tail_chars = sum(len(words[i].word) for i in range(last_valid + 1, len(words)))
        self._progress(
            f"  尾部修复: {tail_count} 个词({tail_chars} 字符)失效 "
            f"@ {valid_end:.1f}s, 用语速推算至 {seg_dur:.1f}s"
        )

        # 计算已对齐部分的字符速率
        if valid_end > 0 and valid_chars > 0:
            char_rate = valid_chars / valid_end  # chars per second
        else:
            char_rate = 15.0  # 英语默认约 15 chars/sec

        # 从 valid_end 开始，按字符速率推算
        cursor = valid_end
        for i in range(last_valid + 1, len(words)):
            w = words[i]
            c = len(w.word)
            duration = c / char_rate
            w.start = round(cursor, 3)
            w.end = round(min(cursor + duration, seg_dur), 3)
            cursor = w.end

        return words

    @staticmethod
    def _locate_segments_in_original(
        seg_asr_texts: List[str], original_text: str,
    ) -> List[Tuple[int, int]]:
        """确定每段 ASR 文本对应原始文本的字符范围。

        用 SequenceMatcher 将拼接的 ASR 文本与原文对齐，
        再根据每段 ASR 文本的长度切分出对应的原文范围。
        """
        # 拼接所有 ASR 文本，记录每段的起止位置
        asr_full = "".join(seg_asr_texts)
        seg_asr_ranges: List[Tuple[int, int]] = []
        pos = 0
        for t in seg_asr_texts:
            seg_asr_ranges.append((pos, pos + len(t)))
            pos += len(t)

        if not asr_full:
            # 全部 ASR 为空，均分原文
            n = len(seg_asr_texts)
            chunk = len(original_text) // max(n, 1)
            return [(i * chunk, min((i + 1) * chunk, len(original_text))) for i in range(n)]

        # 全局对齐，建立 ASR 字符索引 → 原文字符索引 的映射
        sm = difflib.SequenceMatcher(None, asr_full, original_text, autojunk=False)
        # asr_idx → orig_idx 映射表（仅 equal 和 replace 块）
        asr_to_orig: dict = {}  # asr_char_idx -> orig_char_idx

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    asr_to_orig[i1 + k] = j1 + k
            elif tag == "replace":
                asr_len = i2 - i1
                orig_len = j2 - j1
                for k in range(asr_len):
                    # 按比例映射
                    asr_to_orig[i1 + k] = j1 + int(orig_len * k / asr_len)

        # 根据每段 ASR 范围，找到对应的原文范围
        result: List[Tuple[int, int]] = []
        for seg_idx, (asr_start, asr_end) in enumerate(seg_asr_ranges):
            if asr_start == asr_end:
                # 空 ASR 段
                if result:
                    result.append((result[-1][1], result[-1][1]))
                else:
                    result.append((0, 0))
                continue

            # 找这段 ASR 第一个字符和最后一个字符在原文中的位置
            orig_s = None
            for i in range(asr_start, asr_end):
                if i in asr_to_orig:
                    orig_s = asr_to_orig[i]
                    break
            orig_e = None
            for i in range(asr_end - 1, asr_start - 1, -1):
                if i in asr_to_orig:
                    orig_e = asr_to_orig[i] + 1
                    break

            if orig_s is None:
                orig_s = result[-1][1] if result else 0
            if orig_e is None:
                orig_e = orig_s

            result.append((orig_s, orig_e))

        # 扩展范围：填充段间间隙（原文中未被任何段覆盖的部分归入前一段）
        for i in range(len(result) - 1):
            if result[i][1] < result[i + 1][0]:
                # 间隙归入前段末尾
                result[i] = (result[i][0], result[i + 1][0])
        # 最后一段扩展到原文末尾
        if result:
            result[-1] = (result[-1][0], len(original_text))
            # 第一段扩展到原文开头
            result[0] = (0, result[0][1])

        return result

    def _align_long_audio_with_asr(
        self, audio_path: str, original_text: str,
        asr_model_path: str = "Qwen/Qwen3-ASR-0.6B",
    ) -> List[AlignedWord]:
        """ASR 引导的长音频分段对齐。

        流程：
        1. 分段（同 _align_long_audio）
        2. 每段用 ASR 识别实际文字
        3. 每段用 ASR 文字做强制对齐 → 精确时间戳
        4. 合并所有 ASR 对齐结果
        5. 用 difflib 将 ASR 时间戳映射回原始文本
        """
        import torch

        total_duration = self._get_audio_duration(audio_path)
        self._progress(f"音频总时长: {_fmt_duration(total_duration)}")

        if total_duration <= _MAX_ASR_SEGMENT_SEC:
            # 短音频：ASR → 对齐 → 映射
            self._progress("音频 ≤ 2 分钟，直接 ASR 引导对齐。")
            asr_model = self._load_asr_model(asr_model_path)
            asr_text = self._asr_transcribe_segment(asr_model, audio_path)
            del asr_model
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

            if not asr_text:
                self._progress("ASR 未识别到文字，回退到直接对齐。")
                return self._run_alignment(audio_path, original_text)

            self._progress(f"ASR 识别: {len(asr_text)} 字")
            self.load_model()
            asr_words = self._run_alignment(audio_path, asr_text)
            if not asr_words:
                self._progress("ASR 文字对齐失败，回退到直接对齐。")
                return self._run_alignment(audio_path, original_text)

            asr_words = self._fix_segment_alignment(asr_words, total_duration)
            mapped = self._map_asr_to_original(asr_words, original_text)
            words = self._merge_chars_to_words(mapped)
            self._progress(f"映射完成: {len(mapped)} 字 → {len(words)} 词")
            return words

        # --- 长音频分段（ASR 引导用 2 分钟短段，提高精度） ---
        self._progress("检测静音点...")
        silences = self._detect_silences(audio_path)
        segments = self._build_segments(total_duration, silences, max_seg=_MAX_ASR_SEGMENT_SEC)
        self._progress(f"分为 {len(segments)} 段: "
                       + ", ".join(f"{_fmt_duration(s)}-{_fmt_duration(e)}" for s, e in segments))

        # 第一遍：ASR 识别每段文字
        self._progress("=== 第一遍：ASR 识别每段音频 ===")
        asr_model = self._load_asr_model(asr_model_path)
        seg_asr_texts: List[str] = []

        for idx, (seg_start, seg_end) in enumerate(segments):
            seg_label = f"[{idx + 1}/{len(segments)}] {_fmt_duration(seg_start)}-{_fmt_duration(seg_end)}"
            self._progress(f"--- ASR {seg_label} ---")

            suffix = Path(audio_path).suffix or ".wav"
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(tmp_fd)
            try:
                self._extract_audio_segment(audio_path, seg_start, seg_end, tmp_path)
                asr_text = self._asr_transcribe_segment(asr_model, tmp_path)
                self._progress(f"  ASR: {len(asr_text)} 字 — {asr_text[:60]}...")
                seg_asr_texts.append(asr_text)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        # 释放 ASR 模型
        del asr_model
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

        # 第二步：确定每段 ASR 文本对应原始文本的哪个范围
        self._progress("=== 定位每段 ASR 文本在原文中的位置 ===")
        seg_orig_ranges = self._locate_segments_in_original(
            seg_asr_texts, original_text,
        )
        for idx, (os_start, os_end) in enumerate(seg_orig_ranges):
            self._progress(
                f"  段 {idx + 1}: 原文 [{os_start}:{os_end}] ({os_end - os_start} 字)"
            )

        # 第三遍：逐段对齐 + 逐段映射回原文
        self._progress("=== 第三遍：逐段对齐并映射 ===")
        self.load_model()
        all_words: List[AlignedWord] = []

        for idx, (seg_start, seg_end) in enumerate(segments):
            seg_dur = seg_end - seg_start
            seg_label = f"[{idx + 1}/{len(segments)}] {_fmt_duration(seg_start)}-{_fmt_duration(seg_end)}"
            asr_text = seg_asr_texts[idx]
            orig_start, orig_end = seg_orig_ranges[idx]
            orig_chunk = original_text[orig_start:orig_end]

            if not asr_text.strip():
                self._progress(f"--- 对齐 {seg_label} --- 跳过（ASR 无文字）")
                # 原文中该段对应的非语音内容（如章节标题），给零时长标记
                if orig_chunk.strip():
                    for ch in orig_chunk:
                        all_words.append(AlignedWord(ch, seg_start, seg_start))
                continue

            self._progress(f"--- 对齐 {seg_label} ---")

            suffix = Path(audio_path).suffix or ".wav"
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(tmp_fd)
            try:
                self._extract_audio_segment(audio_path, seg_start, seg_end, tmp_path)
                seg_words = self._run_alignment(tmp_path, asr_text)
                self._progress(f"  对齐得到 {len(seg_words)} 个词")

                # 修复对齐尾部失效
                seg_words = self._fix_segment_alignment(seg_words, seg_dur)

                # 加上时间偏移
                for w in seg_words:
                    w.start = round(w.start + seg_start, 3)
                    w.end = round(w.end + seg_start, 3)

                # 逐段映射到原文片段（防止跨段错配）
                if orig_chunk.strip():
                    mapped = self._map_asr_to_original(seg_words, orig_chunk)
                    self._progress(f"  映射: {len(seg_words)} ASR词 → {len(mapped)} 原文字符")
                    all_words.extend(mapped)
                else:
                    all_words.extend(seg_words)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        self._progress(f"逐段对齐完成，共 {len(all_words)} 个字符")

        # 合并为单词
        words = self._merge_chars_to_words(all_words)
        self._progress(f"合并为 {len(words)} 个词")
        return words

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

    def align_with_asr(
        self,
        audio_path: str,
        text_path: str,
        output_dir: str,
        *,
        asr_model_path: str = "Qwen/Qwen3-ASR-0.6B",
        formats: Sequence[str] = ("json", "srt", "vtt"),
        srt_max_chars: int = 40,
    ) -> AlignmentResult:
        """ASR 引导对齐：音频 + 原始文本 → 时间戳严格对应原始文本。

        流程:
        1. 分段 ASR 识别音频实际内容
        2. 用 ASR 文字做强制对齐得到精确时间戳
        3. 将时间戳映射回原始文本的每个字
        """
        result = AlignmentResult(audio_file=audio_path, text_file=text_path)

        try:
            a_path = Path(audio_path)
            t_path = Path(text_path)
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            text = _read_text(t_path)
            if not text:
                result.error = "文本文件为空"
                return result

            self._progress(f"ASR 引导对齐: {a_path.name} ...")
            result.words = self._align_long_audio_with_asr(
                str(a_path), text, asr_model_path=asr_model_path,
            )

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

        except ImportError:
            result.error = (
                "需要 torch 和 qwen-asr 库。\n"
                "安装命令: pip install torch qwen-asr"
            )
        except Exception as exc:
            result.error = str(exc)
            self._log.exception("ASR 引导对齐 %s 时出错", audio_path)

        return result

    def batch_align_with_asr(
        self,
        audio_dir: str,
        text_dir: str,
        output_dir: str,
        *,
        asr_model_path: str = "Qwen/Qwen3-ASR-0.6B",
        formats: Sequence[str] = ("json", "srt", "vtt"),
        srt_max_chars: int = 40,
    ) -> List[AlignmentResult]:
        """批量 ASR 引导对齐：按文件名 stem 匹配音频与文本。"""
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

        self._progress(f"找到 {len(matched)} 对匹配文件，开始 ASR 引导对齐...")

        results: List[AlignmentResult] = []
        for i, (a_path, t_path) in enumerate(matched, 1):
            self._progress(f"--- [{i}/{len(matched)}] {a_path.name} ---")
            r = self.align_with_asr(
                str(a_path), str(t_path), str(out_dir),
                asr_model_path=asr_model_path,
                formats=formats, srt_max_chars=srt_max_chars,
            )
            results.append(r)
            self._progress(str(r))

        self._print_summary(results)
        return results

    # ---- 预切割合并对齐 ----

    @staticmethod
    def _extract_sort_key(stem: str) -> Tuple[str, int]:
        """从文件名 stem 提取排序键: (前缀, 序号)。

        xxx_1 → ('xxx', 1),  chapter_02 → ('chapter', 2)
        """
        m = re.search(r'(\d+)$', stem)
        if m:
            prefix = stem[:m.start()].rstrip("_- ")
            return (prefix, int(m.group(1)))
        return (stem, 0)

    @staticmethod
    def find_presplit_pairs(
        folder: Path,
    ) -> List[Tuple[Path, Path]]:
        """扫描单个文件夹，按 stem 匹配音频+文本对，按序号排序。

        Returns
        -------
        list of (audio_path, text_path)，已按文件名序号排序。
        """
        audio_map: dict = {}
        text_map: dict = {}
        for f in sorted(folder.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() in _AUDIO_EXTS:
                audio_map[f.stem] = f
            elif f.suffix.lower() == ".txt":
                text_map[f.stem] = f

        # 匹配
        matched = []
        for stem in audio_map:
            if stem in text_map:
                matched.append((audio_map[stem], text_map[stem]))

        # 按序号排序
        matched.sort(key=lambda pair: ForcedAligner._extract_sort_key(pair[0].stem))
        return matched

    def align_presplit(
        self,
        folder: str,
        output_dir: str,
        *,
        output_name: str = "",
    ) -> AlignmentResult:
        """预切割合并对齐：同一文件夹里的音频+文本对按序号对齐，合并为一个 JSON。

        Parameters
        ----------
        folder : str
            包含 xxx_1.mp3 + xxx_1.txt 等配对文件的文件夹。
        output_dir : str
            输出目录。
        output_name : str
            输出 JSON 文件名（不含扩展名），默认用文件夹名。
        """
        result = AlignmentResult(audio_file=folder, text_file=folder)

        try:
            self.load_model()
            f_dir = Path(folder)
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            pairs = self.find_presplit_pairs(f_dir)
            if not pairs:
                result.error = "未找到匹配的音频-文本对"
                self._progress(result.error)
                return result

            self._progress(f"找到 {len(pairs)} 对文件，按序号排列:")
            for a, t in pairs:
                self._progress(f"  {a.name}  ←→  {t.name}")

            all_words: List[AlignedWord] = []
            seg_names: List[str] = []
            time_offset = 0.0  # 累计时间偏移

            for idx, (a_path, t_path) in enumerate(pairs):
                self._progress(f"--- [{idx + 1}/{len(pairs)}] {a_path.name} ---")

                text = _read_text(t_path)
                if not text.strip():
                    self._progress(f"  跳过（文本为空）")
                    continue

                seg_names.append(a_path.name)

                # 获取本段音频时长
                seg_dur = self._get_audio_duration(str(a_path))
                self._progress(f"  时长: {_fmt_duration(seg_dur)}, 偏移: {_fmt_duration(time_offset)}")

                # 直接对齐（每段 <5min）
                seg_words = self._run_alignment(str(a_path), text)
                self._progress(f"  对齐得到 {len(seg_words)} 个词")

                # 修复尾部失效
                seg_words = self._fix_segment_alignment(seg_words, seg_dur)

                # 合并为单词级（剥离标点 + 平滑）
                seg_merged = self._merge_chars_to_words(seg_words)
                self._progress(f"  合并为 {len(seg_merged)} 个单词")

                # 加上累计时间偏移
                for w in seg_merged:
                    all_words.append(AlignedWord(
                        word=w.word,
                        start=round(w.start + time_offset, 3),
                        end=round(w.end + time_offset, 3),
                    ))

                time_offset += seg_dur

            if not all_words:
                result.error = "对齐未产生任何词级时间戳"
                return result

            # 写合并 JSON
            name = output_name or f_dir.name
            out = out_dir / f"{name}.align.json"
            data = {
                "segments": seg_names,
                "word_count": len(all_words),
                "total_duration": round(time_offset, 3),
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end}
                    for w in all_words
                ],
            }
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            result.words = all_words
            result.output_json = str(out)
            result.success = True
            self._progress(f"完成: {len(all_words)} 词, 总时长 {_fmt_duration(time_offset)}")
            self._progress(f"  JSON: {out}")

        except Exception as exc:
            result.error = str(exc)
            self._log.exception("预切割对齐 %s 时出错", folder)

        return result

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

    # ---- ASR 语音识别（无需文本） ----

    def transcribe_audio(
        self,
        audio_path: str,
        output_dir: str,
        *,
        asr_model_path: str = "Qwen/Qwen3-ASR-0.6B",
    ) -> AlignmentResult:
        """ASR 语音识别 + 强制对齐：仅需音频，输出每个字的起止时间 JSON。

        流程:
        1. Qwen3ASRModel 识别音频 → 文字
        2. 识别出的文字作为 text 传给 _align_long_audio → 词级时间戳
        """
        result = AlignmentResult(audio_file=audio_path, text_file="")

        try:
            import torch
            from qwen_asr import Qwen3ASRModel

            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            a_path = Path(audio_path)

            dtype = torch.float32 if self._device == "cpu" else torch.bfloat16

            # ---- 第一步：ASR 识别文字（不要时间戳） ----
            self._progress(f"加载 ASR 模型: {asr_model_path} ...")
            asr_model = Qwen3ASRModel.from_pretrained(
                asr_model_path,
                dtype=dtype,
                device_map=self._device,
            )
            self._progress("ASR 模型加载完成。")

            self._progress(f"ASR 识别中: {a_path.name} ...")
            asr_results = asr_model.transcribe(
                audio=audio_path,
                language=self._language,
            )

            if not asr_results or not asr_results[0].text.strip():
                result.error = "ASR 未识别到任何文字"
                return result

            recognized_text = asr_results[0].text
            self._progress(f"ASR 识别完成，共 {len(recognized_text)} 字")
            self._progress(f"  文本: {recognized_text[:120]}...")

            # 释放 ASR 模型，节省内存
            del asr_model
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

            # ---- 第二步：用识别出的文字做强制对齐 ----
            self._progress("加载对齐模型，开始强制对齐...")
            self.load_model()
            result.words = self._align_long_audio(str(a_path), recognized_text)

            if not result.words:
                result.error = "强制对齐未产生任何词级时间戳"
                return result

            # 写 JSON
            stem = a_path.stem
            out = out_dir / f"{stem}.asr.json"
            data = {
                "audio": a_path.name,
                "text": recognized_text,
                "word_count": len(result.words),
                "words": [
                    {"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3)}
                    for w in result.words
                ],
            }
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            result.output_json = str(out)

            result.success = True
            self._progress(f"完成: {a_path.name} → {len(result.words)} words")
            self._progress(f"  JSON: {out}")

        except ImportError:
            result.error = (
                "需要 torch 和 qwen-asr 库。\n"
                "安装命令: pip install torch qwen-asr"
            )
        except Exception as exc:
            result.error = str(exc)
            self._log.exception("ASR+对齐 %s 时出错", audio_path)

        return result

    def batch_transcribe(
        self,
        audio_dir: str,
        output_dir: str,
        *,
        asr_model_path: str = "Qwen/Qwen3-ASR-0.6B",
    ) -> List[AlignmentResult]:
        """批量 ASR + 强制对齐。"""
        a_dir = Path(audio_dir)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        audio_files = sorted(
            f for f in a_dir.iterdir()
            if f.is_file() and f.suffix.lower() in _AUDIO_EXTS
        )
        if not audio_files:
            self._progress("未找到音频文件。")
            return []

        self._progress(f"找到 {len(audio_files)} 个音频文件，开始 ASR + 对齐...")
        results: List[AlignmentResult] = []
        for i, af in enumerate(audio_files, 1):
            self._progress(f"--- [{i}/{len(audio_files)}] {af.name} ---")
            r = self.transcribe_audio(
                str(af), str(out_dir), asr_model_path=asr_model_path,
            )
            results.append(r)
            self._progress(str(r))

        self._print_summary(results)
        return results


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
    parser.add_argument(
        "--asr-guided", action="store_true",
        help="ASR 引导对齐：先 ASR 识别再对齐，时间戳映射回原始文本（长音频推荐）",
    )
    parser.add_argument(
        "--asr-model", default="Qwen/Qwen3-ASR-0.6B",
        help="ASR 模型路径（仅 --asr-guided 时使用）",
    )
    # 预切割合并模式
    parser.add_argument(
        "--presplit-dir",
        help="预切割合并模式：文件夹内含同名音频+文本对（如 xxx_1.mp3 + xxx_1.txt），按序号合并为一个 JSON",
    )

    args = parser.parse_args()

    aligner = ForcedAligner(
        model_path=args.model, device=args.device, language=args.language,
    )

    if args.presplit_dir:
        r = aligner.align_presplit(args.presplit_dir, args.output_dir)
        sys.exit(0 if r.success else 1)
    elif args.audio_dir and args.text_dir:
        if args.asr_guided:
            results = aligner.batch_align_with_asr(
                args.audio_dir, args.text_dir, args.output_dir,
                asr_model_path=args.asr_model,
                formats=tuple(args.formats), srt_max_chars=args.srt_max_chars,
            )
        else:
            results = aligner.batch_align(
                args.audio_dir, args.text_dir, args.output_dir,
                formats=tuple(args.formats), srt_max_chars=args.srt_max_chars,
            )
        sys.exit(0 if all(r.success or r.skipped for r in results) else 1)
    elif args.audio_file and args.text_file:
        if args.asr_guided:
            r = aligner.align_with_asr(
                args.audio_file, args.text_file, args.output_dir,
                asr_model_path=args.asr_model,
                formats=tuple(args.formats), srt_max_chars=args.srt_max_chars,
            )
        else:
            r = aligner.align(
                args.audio_file, args.text_file, args.output_dir,
                formats=tuple(args.formats), srt_max_chars=args.srt_max_chars,
            )
        sys.exit(0 if r.success else 1)
    else:
        parser.error("请指定 audio_file + text_file / --audio-dir + --text-dir / --presplit-dir")


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
