"""ASR 引导强制对齐服务 — 最小可执行模块。

部署到 GPU 服务器，通过 HTTP 接口调用：

    POST /align
    {
        "audio": "/path/to/audio.mp3",
        "text": "/path/to/text.txt",
        "language": "English"
    }

启动::

    source /root/qwen-asr-serve/.venv/bin/activate
    cd /root/qwen-asr-serve/align
    python server.py
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

ALIGN_MODEL = os.getenv("ALIGN_MODEL", "/models/huggingface/hub/models--Qwen--Qwen3-ForcedAligner-0.6B/snapshots/c7cbfc2048c462b0d63a45797104fc9db3ad62b7")
ASR_MODEL = os.getenv("ASR_MODEL", "/models/huggingface/hub/models--Qwen--Qwen3-ASR-1.7B/snapshots/7278e1e70fe206f11671096ffdd38061171dd6e5")

# ALIGN_MODEL = os.getenv("ALIGN_MODEL", "D:\my_models\Qwen3-ForcedAligner-0.6B")
# ASR_MODEL = os.getenv("ASR_MODEL", "D:\my_models\Qwen3-ASR-0.6B")

DEVICE = os.getenv("DEVICE", "cuda")
# DEVICE = os.getenv("DEVICE", "cpu")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9098"))

# 分段参数
_MAX_SEG_SEC = 120.0      # ASR 引导：每段上限 2 分钟
_SILENCE_DB = -30
_MIN_SILENCE_SEC = 0.3

_AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"}

log = logging.getLogger("asr-align")

# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class Word:
    word: str
    start: float
    end: float


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _find_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"需要 {name}，但未在 PATH 中找到")
    return path


def _read_text(path: str) -> str:
    p = Path(path)
    raw = None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            raw = p.read_text(encoding=enc).strip()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if raw is None:
        raise ValueError(f"无法解码文件: {path}")
    # 过滤 ```json ... ``` / ```xxx ... ``` 代码块
    raw = re.sub(r'```\w*\s*\n.*?\n```', '', raw, flags=re.DOTALL)
    return raw.strip()


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _get_duration(audio: str) -> float:
    cmd = [_find_tool("ffprobe"), "-v", "quiet",
           "-show_entries", "format=duration", "-of", "csv=p=0", audio]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {r.stderr.strip()}")
    return float(r.stdout.strip())


def _detect_silences(audio: str) -> List[Tuple[float, float]]:
    cmd = [_find_tool("ffmpeg"), "-i", audio,
           "-af", f"silencedetect=noise={_SILENCE_DB}dB:d={_MIN_SILENCE_SEC}",
           "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    starts = [float(m.group(1)) for m in re.finditer(r"silence_start:\s*([\d.]+)", r.stderr)]
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end:\s*([\d.]+)", r.stderr)]
    silences = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else s + _MIN_SILENCE_SEC
        silences.append((s, e))
    return silences


def _build_segments(total: float, silences: List[Tuple[float, float]],
                    max_seg: float = _MAX_SEG_SEC) -> List[Tuple[float, float]]:
    if total <= max_seg:
        return [(0.0, total)]
    cuts = sorted(set((s + e) / 2 for s, e in silences))
    segs, start = [], 0.0
    min_seg = min(30.0, max_seg * 0.25)
    while start < total - 1.0:
        limit = start + max_seg
        if limit >= total:
            segs.append((start, total)); break
        best = None
        for c in cuts:
            if start + min_seg < c <= limit:
                best = c
        if best is None:
            best = limit
        segs.append((start, best)); start = best
    return segs


def _extract_segment(src: str, start: float, end: float, dst: str):
    cmd = [_find_tool("ffmpeg"), "-y", "-ss", str(start), "-to", str(end),
           "-i", src, "-c", "copy", dst]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"提取失败: {r.stderr.strip()}")


# ---------------------------------------------------------------------------
# 对齐修复
# ---------------------------------------------------------------------------

def _fix_tail(words: List[Word], seg_dur: float) -> List[Word]:
    """修复段内对齐尾部失效：用已对齐部分的语速推算。"""
    if not words:
        return words
    last_valid = -1
    valid_chars, valid_end = 0, 0.0
    for i, w in enumerate(words):
        if abs(w.end - w.start) >= 0.01:
            last_valid = i
            valid_chars += len(w.word)
            valid_end = w.end
    if last_valid < 0:
        total_c = sum(len(w.word) for w in words)
        if total_c == 0:
            return words
        pos = 0.0
        for w in words:
            c = len(w.word)
            w.start = round(pos, 3)
            pos += seg_dur * c / total_c
            w.end = round(pos, 3)
        return words
    tail = len(words) - last_valid - 1
    if tail == 0:
        return words
    rate = valid_chars / valid_end if valid_end > 0 and valid_chars > 0 else 15.0
    cursor = valid_end
    for i in range(last_valid + 1, len(words)):
        w = words[i]
        dur = len(w.word) / rate
        w.start = round(cursor, 3)
        w.end = round(min(cursor + dur, seg_dur), 3)
        cursor = w.end
    return words


# ---------------------------------------------------------------------------
# 文本映射
# ---------------------------------------------------------------------------

def _map_to_original(asr_words: List[Word], original: str) -> List[Word]:
    """将 ASR 对齐结果映射到原始文本每个字符。"""
    if not asr_words:
        return []
    asr_text = "".join(w.word for w in asr_words)
    ts: List[Tuple[float, float]] = []
    for w in asr_words:
        for _ in w.word:
            ts.append((w.start, w.end))
    sm = difflib.SequenceMatcher(None, asr_text, original, autojunk=False)
    result: List[Word] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                t = ts[i1 + k]
                result.append(Word(original[j1 + k], t[0], t[1]))
        elif tag == "replace":
            orig_len = j2 - j1
            t_start = ts[i1][0]
            t_end = ts[min(i2, len(ts)) - 1][1]
            span = t_end - t_start
            for k in range(orig_len):
                t0 = t_start + span * k / orig_len
                t1 = t_start + span * (k + 1) / orig_len
                result.append(Word(original[j1 + k], round(t0, 3), round(t1, 3)))
        elif tag == "insert":
            if result:
                t = (result[-1].end, result[-1].end)
            elif i1 < len(ts):
                t = ts[i1]
            else:
                t = (0.0, 0.0)
            for j in range(j1, j2):
                result.append(Word(original[j], t[0], t[1]))
    return result


def _locate_segments(seg_texts: List[str], original: str) -> List[Tuple[int, int]]:
    """确定每段 ASR 文本对应原始文本的字符范围。

    保证：
    1. 所有段严格相邻，seg[i].end == seg[i+1].start
    2. 第一段从 0 开始，最后一段到 len(original) 结束
    3. 没有 gap 和 overlap

    策略：先用 diff 找到每段的「中心映射点」，再取相邻段中心点的中间值作为切割边界。
    """
    n = len(seg_texts)
    orig_len = len(original)

    if n == 0:
        return []
    if n == 1:
        return [(0, orig_len)]

    full = "".join(seg_texts)
    if not full:
        ch = orig_len // max(n, 1)
        return [(i * ch, min((i + 1) * ch, orig_len)) for i in range(n)]

    # 构建 ASR 拼接文本中每段的字符范围
    asr_ranges: List[Tuple[int, int]] = []
    pos = 0
    for t in seg_texts:
        asr_ranges.append((pos, pos + len(t)))
        pos += len(t)

    # diff：ASR 拼接文本 ↔ 原始文本，建立字符映射
    sm = difflib.SequenceMatcher(None, full, original, autojunk=False)
    a2o: dict = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                a2o[i1 + k] = j1 + k
        elif tag == "replace":
            al, ol = i2 - i1, j2 - j1
            for k in range(al):
                a2o[i1 + k] = j1 + int(ol * k / al)

    # 找每段的边界映射点：段末尾在原文中的位置
    # 用段与段之间的「交界区域」的中点作为切割线
    boundaries = [0]  # 第一段从 0 开始
    for i in range(n - 1):
        # 前一段的末尾位置（在原文中）
        asr_end = asr_ranges[i][1]
        end_pos = None
        for j in range(asr_end - 1, asr_ranges[i][0] - 1, -1):
            if j in a2o:
                end_pos = a2o[j] + 1
                break

        # 后一段的开头位置（在原文中）
        asr_start = asr_ranges[i + 1][0]
        start_pos = None
        for j in range(asr_start, asr_ranges[i + 1][1]):
            if j in a2o:
                start_pos = a2o[j]
                break

        # 取中点作为切割边界
        if end_pos is not None and start_pos is not None:
            cut = (end_pos + start_pos) // 2
        elif end_pos is not None:
            cut = end_pos
        elif start_pos is not None:
            cut = start_pos
        else:
            # 两段都没有映射，按比例估算
            cut = orig_len * (i + 1) // n

        # 保证单调递增
        cut = max(cut, boundaries[-1])
        cut = min(cut, orig_len)
        boundaries.append(cut)

    boundaries.append(orig_len)  # 最后一段到末尾

    return [(boundaries[i], boundaries[i + 1]) for i in range(n)]


def _merge_to_words(chars: List[Word]) -> List[Word]:
    """字符级 → 单词级（剥离标点、平滑零时长）。"""
    if not chars:
        return []
    groups: List[List[Word]] = []
    cur: List[Word] = []
    for ch in chars:
        if ch.word in (" ", "\n", "\r", "\t"):
            if cur:
                groups.append(cur); cur = []
        else:
            cur.append(ch)
    if cur:
        groups.append(cur)
    words: List[Word] = []
    for grp in groups:
        while grp and not grp[0].word.isalnum():
            grp = grp[1:]
        while grp and not grp[-1].word.isalnum():
            grp = grp[:-1]
        if not grp or not any(c.word.isalnum() for c in grp):
            continue
        words.append(Word("".join(c.word for c in grp), grp[0].start, grp[-1].end))
    # 平滑零时长
    for i, w in enumerate(words):
        if abs(w.end - w.start) >= 0.01:
            continue
        prev_end = next((words[j].end for j in range(i - 1, -1, -1)
                         if abs(words[j].end - words[j].start) >= 0.01), None)
        next_start = next((words[j].start for j in range(i + 1, len(words))
                           if abs(words[j].end - words[j].start) >= 0.01), None)
        if prev_end is not None and next_start is not None:
            zs = i
            while zs > 0 and abs(words[zs - 1].end - words[zs - 1].start) < 0.01:
                zs -= 1
            ze = i
            while ze < len(words) - 1 and abs(words[ze + 1].end - words[ze + 1].start) < 0.01:
                ze += 1
            n = ze - zs + 1
            span = next_start - prev_end
            for k in range(n):
                words[zs + k].start = round(prev_end + span * k / n, 3)
                words[zs + k].end = round(prev_end + span * (k + 1) / n, 3)
    return words


# ---------------------------------------------------------------------------
# 模型管理（全局单例）
# ---------------------------------------------------------------------------

class Models:
    def __init__(self):
        self.aligner = None
        self.asr = None

    def load(self):
        if self.aligner is not None:
            return
        import torch
        from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner

        dtype = torch.float32 if DEVICE == "cpu" else torch.bfloat16
        log.info("加载 ASR 模型: %s", ASR_MODEL)
        self.asr = Qwen3ASRModel.from_pretrained(ASR_MODEL, dtype=dtype, device_map=DEVICE)
        log.info("加载对齐模型: %s", ALIGN_MODEL)
        self.aligner = Qwen3ForcedAligner.from_pretrained(ALIGN_MODEL, dtype=dtype, device_map=DEVICE)
        log.info("模型加载完成 (device=%s)", DEVICE)

    def transcribe(self, audio: str, lang: str) -> str:
        r = self.asr.transcribe(audio=audio, language=lang)
        if not r or not r[0].text.strip():
            return ""
        return r[0].text

    def align(self, audio: str, text: str, lang: str) -> List[Word]:
        r = self.aligner.align(audio=audio, text=text, language=lang)
        if not r or not r[0]:
            return []
        return [Word(s.text, s.start_time, s.end_time) for s in r[0]]


models = Models()


# ---------------------------------------------------------------------------
# 核心对齐逻辑
# ---------------------------------------------------------------------------

def align_with_asr(audio: str, text: str, language: str) -> List[Word]:
    """ASR 引导对齐：分段 ASR → 分段对齐 → 逐段映射回原文 → 合并为单词。"""
    models.load()

    total_dur = _get_duration(audio)
    log.info("音频时长: %s", _fmt(total_dur))

    # 分段
    if total_dur <= _MAX_SEG_SEC:
        segments = [(0.0, total_dur)]
    else:
        silences = _detect_silences(audio)
        segments = _build_segments(total_dur, silences)
    log.info("分为 %d 段: %s", len(segments),
             ", ".join(f"{_fmt(s)}-{_fmt(e)}" for s, e in segments))

    # 第一遍：ASR 每段
    log.info("=== ASR 识别 ===")
    seg_asr_texts: List[str] = []
    for idx, (ss, se) in enumerate(segments):
        suffix = Path(audio).suffix or ".wav"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.close()
        try:
            if len(segments) == 1:
                asr_text = models.transcribe(audio, language)
            else:
                _extract_segment(audio, ss, se, tmp.name)
                asr_text = models.transcribe(tmp.name, language)
            log.info("  段 %d/%d: %d 字", idx + 1, len(segments), len(asr_text))
            seg_asr_texts.append(asr_text)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    # 定位每段在原文中的位置
    seg_ranges = _locate_segments(seg_asr_texts, text)

    # 第二遍：逐段对齐 + 逐段映射
    log.info("=== 对齐 + 映射 ===")
    all_chars: List[Word] = []

    for idx, (ss, se) in enumerate(segments):
        seg_dur = se - ss
        asr_text = seg_asr_texts[idx]
        orig_s, orig_e = seg_ranges[idx]
        orig_chunk = text[orig_s:orig_e]

        if not asr_text.strip():
            if orig_chunk.strip():
                for ch in orig_chunk:
                    all_chars.append(Word(ch, ss, ss))
            continue

        suffix = Path(audio).suffix or ".wav"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.close()
        try:
            if len(segments) == 1:
                seg_words = models.align(audio, asr_text, language)
            else:
                _extract_segment(audio, ss, se, tmp.name)
                seg_words = models.align(tmp.name, asr_text, language)

            seg_words = _fix_tail(seg_words, seg_dur)

            # 加时间偏移
            for w in seg_words:
                w.start = round(w.start + ss, 3)
                w.end = round(w.end + ss, 3)

            # 映射到原文片段
            if orig_chunk.strip():
                mapped = _map_to_original(seg_words, orig_chunk)
                all_chars.extend(mapped)
            else:
                all_chars.extend(seg_words)

            log.info("  段 %d/%d: %d ASR词 → %d 原文字符",
                     idx + 1, len(segments), len(seg_words),
                     len(mapped) if orig_chunk.strip() else len(seg_words))
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    return _merge_to_words(all_chars)


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

app = FastAPI(title="ASR Forced Aligner")


OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/root/qwen-aligner-service/output")
INPUT_DIR = os.getenv("INPUT_DIR", "/root/qwen-aligner-service/input")

_AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"}


class AlignRequest(BaseModel):
    audio: str
    text: str
    language: str = "English"


class BatchRequest(BaseModel):
    input_dir: str = ""     # 留空则用 INPUT_DIR
    output_dir: str = ""    # 留空则用 OUTPUT_DIR
    language: str = "English"


class AlignResponse(BaseModel):
    word_count: int
    output_file: str
    words: List[dict]


class BatchItemResult(BaseModel):
    audio: str
    text: str
    word_count: int
    output_file: str
    success: bool
    error: str = ""


class BatchResponse(BaseModel):
    total: int
    success: int
    failed: int
    results: List[BatchItemResult]


@app.post("/align", response_model=AlignResponse)
def do_align(req: AlignRequest):
    if not Path(req.audio).is_file():
        raise HTTPException(400, f"音频文件不存在: {req.audio}")
    if not Path(req.text).is_file():
        raise HTTPException(400, f"文本文件不存在: {req.text}")

    text = _read_text(req.text)
    if not text:
        raise HTTPException(400, "文本文件为空")

    log.info("请求: audio=%s text=%s lang=%s", req.audio, req.text, req.language)
    words = align_with_asr(req.audio, text, req.language)

    # 写 JSON 到服务器
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(req.audio).stem
    out_path = out_dir / f"{stem}.json"
    data = {
        "audio": Path(req.audio).name,
        "text": Path(req.text).name,
        "word_count": len(words),
        "words": [{"word": w.word, "start": w.start, "end": w.end} for w in words],
    }
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("输出: %s (%d 词)", out_path, len(words))

    return AlignResponse(
        word_count=len(words),
        output_file=str(out_path),
        words=data["words"],
    )


@app.post("/batch", response_model=BatchResponse)
def do_batch(req: BatchRequest):
    """批量对齐：扫描 input_dir 下同名 mp3+txt，输出到 output_dir。"""
    in_dir = Path(req.input_dir or INPUT_DIR)
    out_dir = Path(req.output_dir or OUTPUT_DIR)

    if not in_dir.is_dir():
        raise HTTPException(400, f"输入目录不存在: {in_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 按 stem 匹配音频和文本
    audio_map = {
        f.stem: f for f in sorted(in_dir.iterdir())
        if f.is_file() and f.suffix.lower() in _AUDIO_EXTS
    }
    text_map = {
        f.stem: f for f in sorted(in_dir.iterdir())
        if f.is_file() and f.suffix.lower() == ".txt"
    }

    matched = [(audio_map[s], text_map[s]) for s in sorted(audio_map) if s in text_map]
    if not matched:
        raise HTTPException(400, f"未找到匹配的音频-文本对 (目录: {in_dir})")

    log.info("批量对齐: %d 对文件, 语言=%s", len(matched), req.language)

    results: List[BatchItemResult] = []
    for i, (audio_path, text_path) in enumerate(matched, 1):
        log.info("--- [%d/%d] %s ---", i, len(matched), audio_path.name)
        try:
            text = _read_text(str(text_path))
            if not text:
                results.append(BatchItemResult(
                    audio=audio_path.name, text=text_path.name,
                    word_count=0, output_file="", success=False, error="文本为空",
                ))
                continue

            words = align_with_asr(str(audio_path), text, req.language)

            # 写 JSON
            stem = audio_path.stem
            out_path = out_dir / f"{stem}.json"
            data = {
                "audio": audio_path.name,
                "text": text_path.name,
                "word_count": len(words),
                "words": [{"word": w.word, "start": w.start, "end": w.end} for w in words],
            }
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info("完成: %s → %d 词", audio_path.name, len(words))

            results.append(BatchItemResult(
                audio=audio_path.name, text=text_path.name,
                word_count=len(words), output_file=str(out_path), success=True,
            ))
        except Exception as exc:
            log.exception("对齐 %s 失败", audio_path.name)
            results.append(BatchItemResult(
                audio=audio_path.name, text=text_path.name,
                word_count=0, output_file="", success=False, error=str(exc),
            ))

    ok = sum(1 for r in results if r.success)
    log.info("批量完成: 成功 %d / 失败 %d / 共 %d", ok, len(results) - ok, len(results))

    return BatchResponse(total=len(results), success=ok, failed=len(results) - ok, results=results)


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE,
            "models_loaded": models.aligner is not None}


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("启动服务: %s:%d  device=%s", HOST, PORT, DEVICE)
    log.info("对齐模型: %s", ALIGN_MODEL)
    log.info("ASR 模型: %s", ASR_MODEL)
    uvicorn.run(app, host=HOST, port=PORT)



