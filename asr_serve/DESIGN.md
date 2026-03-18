# ASR 引导强制对齐服务 — 设计文档

## 目标

给定一段音频和其对应的原始文本（音频是按该文本配音的），输出原始文本中**每个单词**的精确起止时间戳（秒），供 App 实现文字自动滚动。

核心难点：音频可能长达 30+ 分钟，而强制对齐模型（Qwen3-ForcedAligner）单次只能处理约 5 分钟的音频。直接分段对齐时，文本切割依赖时间比例估算，语速不均会导致严重偏移。

## 整体流程

```
┌─────────────────────────────────────────────────────────────┐
│                     输入                                     │
│  audio.mp3 (30 min)  +  text.txt (原始文本)                  │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ① 音频分段
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  ffprobe 获取总时长                                          │
│  ffmpeg silencedetect 检测静音点                              │
│  在静音点切割，每段 ≤ 2 分钟                                  │
│  → [seg1(0:00-1:58), seg2(1:58-3:55), ..., segN]            │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ② 逐段 ASR 识别
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Qwen3-ASR-1.7B 对每段音频做语音识别                          │
│  → seg1_text, seg2_text, ..., segN_text                      │
│                                                              │
│  ASR 文本反映音频里「实际说了什么」，                           │
│  与原始文本高度一致（因为音频就是按原文配音的）                  │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ③ 定位每段在原文中的位置
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  _locate_segments: 将 ASR 文本拼接后与原始文本 diff            │
│  找到每对相邻段的交界处在原文中的映射位置                       │
│  取中点作为切割边界，保证严格相邻、无 gap、无 overlap            │
│                                                              │
│    seg1 末尾 → 映射到原文 500                                 │
│    seg2 开头 → 映射到原文 520                                 │
│    切割点 = (500+520)/2 = 510                                │
│                                                              │
│    seg1 → original[0:510]                                    │
│    seg2 → original[510:1038]                                 │
│    segN → original[...:end]                                  │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ④ 逐段强制对齐
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  Qwen3-ForcedAligner-0.6B 对每段音频 + ASR 文本做强制对齐      │
│  → 每段得到字符级时间戳                                       │
│                                                              │
│  关键：用 ASR 识别出的文本对齐，而不是原始文本。                │
│  因为 ASR 文本和音频严丝合缝，对齐精度最高。                   │
│                                                              │
│  对齐后用 _fix_tail 修复段尾失效的时间戳，                     │
│  再将每段内的时间戳加上该段的起始偏移量。                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ⑤ 映射回原始文本
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  _map_to_original: 逐段将 ASR 字符时间戳映射到原文字符         │
│  (difflib.SequenceMatcher 逐字符对齐)                        │
│                                                              │
│  处理四种 diff 操作：                                         │
│    equal   — ASR 和原文一致，直接复制时间戳                    │
│    replace — ASR 识别错误，按时间跨度等比插值                   │
│    insert  — 原文有但 ASR 没识别的字符，继承邻近时间            │
│    delete  — ASR 多出的字符，丢弃                              │
│                                                              │
│  结果：原始文本的每个字符都有了时间戳                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ⑥ 合并为单词
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  _merge_to_words: 字符 → 单词                                │
│  按空格/换行分割字符组                                        │
│  剥离首尾标点（引号、逗号等），保留内部标点（don't）            │
│  每个单词的 start = 首字符 start, end = 末字符 end             │
│  平滑零时长单词（在前后有效时间之间等比插值）                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
                    输出 JSON
```

## 关键方法详解

### `align_with_asr` — 主入口（server.py:408）

整个对齐的编排函数，协调以下流程：

```python
def align_with_asr(audio, text, language) -> List[Word]:
    # 1. 获取音频时长，分段
    # 2. 第一遍循环：逐段 ASR 识别 → seg_asr_texts[]
    # 3. _locate_segments：确定每段对应原文的字符范围
    # 4. 第二遍循环：逐段对齐 + 映射
    #    - models.align(段音频, ASR文本) → 字符级时间戳
    #    - _fix_tail：修复段尾失效
    #    - 加时间偏移 (+seg_start)
    #    - _map_to_original：映射到原文字符
    # 5. _merge_to_words：字符 → 单词
```

为什么要跑两遍循环？因为 `_locate_segments` 需要**所有段的 ASR 文本**才能做全局 diff 定位。如果边 ASR 边对齐，就无法知道每段对应原文的哪个位置。

### `_locate_segments` — 段级定位（server.py:237）

**核心问题**：ASR 识别出 seg1 说了 "The king stood"，seg2 说了 "before the throne"，怎么知道它们分别对应原文的哪些字符？

**算法**：

```
输入:
  seg_texts = ["The king stood", "before the throne"]
  original  = "# Chapter 1\nThe king stood before the throne."

步骤 1: 拼接 ASR 文本
  full = "The king stoodbefore the throne"

步骤 2: diff(full, original)
  得到字符级映射 a2o: {ASR字符索引 → 原文字符索引}
  例如: a2o[0]=12, a2o[1]=13, ...  (跳过了 "# Chapter 1\n")

步骤 3: 找段间切割点
  seg1 末尾 (ASR 索引 14) → 映射到原文位置 26
  seg2 开头 (ASR 索引 14) → 映射到原文位置 26
  切割点 = (26+26)/2 = 26

步骤 4: 构建 boundaries
  boundaries = [0, 26, 46]
  → seg1 = original[0:26]  = "# Chapter 1\nThe king stood"
  → seg2 = original[26:46] = " before the throne."
```

**三个保证**：

| 保证 | 实现方式 |
|------|---------|
| 严格相邻（无 gap） | 用 `boundaries` 数组，每段 `[b[i], b[i+1])`，天然无缝 |
| 无 overlap | 取中点切割 + `max(cut, boundaries[-1])` 强制单调递增 |
| 完整覆盖 | `boundaries[0]=0`，`boundaries[-1]=len(original)` |

**边界情况处理**：

| 情况 | 处理 |
|------|------|
| 只有 1 段 | 直接返回 `[(0, len)]` |
| ASR 全空 | 按段数等分原文 |
| 某段 ASR 在 diff 中无映射 | 按比例估算 `orig_len * (i+1) / n` |
| 计算出的 cut 比上一个小（倒退） | `max(cut, boundaries[-1])` 修正 |

### `_map_to_original` — 字符级映射（server.py:200）

将一段 ASR 对齐结果的时间戳，映射到该段对应的原始文本的每个字符。

```
输入:
  asr_words = [Word("The", 0.0, 0.12), Word("king", 0.12, 0.45)]
  original  = "# Chapter 1\nThe king"  (该段对应的原文片段)

步骤 1: 展开 ASR 为字符级时间戳
  asr_text = "Theking"
  ts = [(0.0,0.12), (0.0,0.12), (0.0,0.12),    # T, h, e
        (0.12,0.45), (0.12,0.45), (0.12,0.45), (0.12,0.45)]  # k, i, n, g

步骤 2: diff(asr_text, original)
  opcodes:
    insert  → "# Chapter 1\n"  (原文有, ASR 没有)
    equal   → "The"
    insert  → " "              (空格)
    equal   → "king"

步骤 3: 按 opcode 分配时间戳
  "#"        → (0.0, 0.0)    ← insert: 继承邻近时间，零时长
  " "        → (0.0, 0.0)
  "C"..."1"  → (0.0, 0.0)
  "\n"       → (0.0, 0.0)
  "T"        → (0.0, 0.12)   ← equal: 直接复制
  "h"        → (0.0, 0.12)
  "e"        → (0.0, 0.12)
  " "        → (0.12, 0.12)  ← insert
  "k"        → (0.12, 0.45)  ← equal
  "i"        → (0.12, 0.45)
  "n"        → (0.12, 0.45)
  "g"        → (0.12, 0.45)
```

**replace 的处理**：当 ASR 识别错误（如 ASR="there" 原文="their"），取对应时间跨度，按原文字符数等比分配。这样即使个别字不对，整体时间分布仍然合理。

### `_fix_tail` — 段尾修复（server.py:160）

**问题**：强制对齐模型在接近段末尾时经常失效，输出一串 `start == end` 的词。

```
正常部分:  word="The"   0.0→0.12  (有效, end-start >= 0.01)
           word="king"  0.12→0.45 (有效)
           word="said"  0.45→0.8  (有效)  ← last_valid
坍缩部分:  word="to"    0.8→0.8   (零时长)
           word="the"   0.8→0.8   (零时长)
           word="queen" 0.8→0.8   (零时长)
```

**修复算法**：

```python
# 1. 找到最后一个有效词 (last_valid)
# 2. 统计有效部分的语速: rate = valid_chars / valid_end
#    例如: 15 字符 / 0.8 秒 = 18.75 字符/秒
# 3. 从 valid_end 开始，按语速逐词推算:
#    "to"    → 0.8 → 0.8 + 2/18.75 = 0.907
#    "the"   → 0.907 → 0.907 + 3/18.75 = 1.067
#    "queen" → 1.067 → 1.067 + 5/18.75 = 1.334

# 特殊情况: 全部坍缩 (last_valid < 0)
# → 按字符数比例均分整个段时长
```

### `_merge_to_words` — 字符合并为单词（server.py:320）

三步处理：

**Step 1 — 按空白符分组**：

```
字符流: [T,h,e, ,k,i,n,g,',s, ,c,r,o,w,n,.]
         ───────  ──────────  ────────────
         group1    group2       group3
```

**Step 2 — 剥离首尾标点**：

```
group: [",B,u,t]  → 去掉首部 " → [B,u,t]     → "But"
group: [c,r,o,w,n,.]  → 去掉尾部 . → [c,r,o,w,n] → "crown"
group: [d,o,n,',t]  → 保留内部 ' → [d,o,n,',t]  → "don't"
group: [*,*]  → 全非字母数字 → 跳过
```

判断规则：`isalnum()` — 保留字母和数字，剥离其他。只剥首尾，不动中间。

**Step 3 — 平滑零时长**：

```
word: "The"     0.0 → 0.12   (有效)
word: "Chapter" 0.12 → 0.12  (零时长)  ← prev_end=0.12
word: "Two"     0.12 → 0.12  (零时长)
word: "began"   0.45 → 0.78  (有效)  ← next_start=0.45

连续零时长: ["Chapter", "Two"], n=2
span = 0.45 - 0.12 = 0.33
"Chapter" → 0.12 → 0.12 + 0.33/2 = 0.285
"Two"     → 0.285 → 0.285 + 0.33/2 = 0.45
```

找到一组连续零时长词，取前后最近有效时间点的跨度，等比分配。

### `_build_segments` — 音频分段（server.py:128）

```
输入: total=1800s (30min), silences=[(58,59), (119,120), (178,179), ...]
      max_seg=120s, min_seg=30s

算法:
  seg_start = 0
  while seg_start < total:
    limit = seg_start + 120  (上限)
    在 [seg_start+30, limit] 范围内找最后一个静音中点
    → best_cut = 119.5  (最后一个在范围内的静音中点)
    记录 (0, 119.5)
    seg_start = 119.5
    ...继续

为什么找「最后一个」？
  → 让每段尽量长，减少段数，减少段间接缝处的精度损失
为什么要求至少 30s？
  → 避免碎片段（太短的段 ASR 和对齐效果都差）
```

### `_detect_silences` — 静音检测（server.py:113）

```bash
ffmpeg -i audio.mp3 -af "silencedetect=noise=-30dB:d=0.3" -f null -

# 输出 stderr:
# [silencedetect] silence_start: 58.234
# [silencedetect] silence_end: 59.012 | silence_duration: 0.778
# [silencedetect] silence_start: 119.456
# ...
```

用正则提取所有 `(silence_start, silence_end)` 对，静音中点 `(start+end)/2` 作为候选切割点。

参数含义：
- `noise=-30dB`：低于 -30dB 视为静音（正常语音约 -20dB ~ -10dB）
- `d=0.3`：持续至少 0.3 秒的静音才算（过滤掉词间短暂停顿）

## 如何保证原始文本每个单词都有时间戳

### 问题

强制对齐模型输出的是 ASR 文本的时间戳，而我们需要的是原始文本的时间戳。ASR 文本和原始文本之间存在差异：

| 差异类型 | 示例 | 处理方式 |
|---------|------|---------|
| 完全一致 | ASR: "the king" → 原文: "the king" | 直接复制时间戳 |
| ASR 识别错误 | ASR: "there" → 原文: "their" | 用对应位置的时间跨度等比分配 |
| 原文有额外内容 | 原文有 `**Chapter 2**` 但音频没读 | 继承相邻字符的时间（零时长标记） |
| ASR 多出内容 | ASR 幻听了一些词 | 丢弃多余部分 |

### 解决方案：三层映射

```
层级          方法                  粒度      输入 → 输出
───────────────────────────────────────────────────────────────
段级映射      _locate_segments      段 → 字符范围   ASR段文本[] → 原文[start:end][]
字符级映射    _map_to_original      字符 → 字符     ASR字符时间戳 → 原文字符时间戳
单词合并      _merge_to_words       字符 → 单词     字符时间戳[] → 单词时间戳[]
```

每一层都用 `difflib.SequenceMatcher` 做序列对齐，保证即使 ASR 和原文不完全一致，也能正确映射。

## 提高准确率的优化

### 1. 静音点切割（而非固定时长切割）

```
❌ 固定切割：每 2 分钟切一刀 → 可能切在单词中间
✅ 静音切割：ffmpeg silencedetect 找静音点 → 在自然停顿处切割
```

- 阈值：-30dB，最短 0.3 秒
- 每段上限 2 分钟（比模型限制 5 分钟保守很多）
- 最短段 30 秒（或上限的 25%），避免碎片段

### 2. ASR 引导（而非时间比例估算文本）

```
❌ 旧方案：30 分钟音频，原文 10000 字 → 前 2 分钟估算对应前 667 字
   问题：语速不均匀，累积偏移严重

✅ 新方案：ASR 识别每段音频说了什么 → 精确知道每段对应哪些文本
   ASR 和原文做 diff → 得到准确的文本切割位置
```

### 3. 尾部修复 (`_fix_tail`)

强制对齐模型在段尾常出现失效（所有词的时间戳坍缩到同一点）：

```
word: "the"    start: 115.2  end: 115.5  ← 正常
word: "king"   start: 115.5  end: 116.0  ← 正常
word: "said"   start: 116.0  end: 116.0  ← 坍缩！
word: "to"     start: 116.0  end: 116.0  ← 坍缩！
```

修复策略：用已对齐部分计算平均语速（字符/秒），推算尾部每个词的时长。如果全部坍缩，按字符数比例均分段时长。

### 4. 零时长平滑

对齐后某些单词可能是零时长（start == end），通常是因为：
- 原文中音频没有读的部分（如 markdown 标记 `**`、章节标题）
- ASR 漏掉的短词

处理：找到前后最近的有效时间点，将连续零时长单词等比插值填充。

### 5. 文本预处理

- 过滤代码块：移除 `` ```json ... ``` `` 等嵌入的代码块（原文有但音频不会读）
- 多编码尝试：依次 UTF-8 → UTF-8-BOM → GBK 读取文本
- 标点剥离：输出单词去掉首尾标点（`"But` → `But`），但保留内部标点（`don't`）

### 6. 分段上限保守设定

模型标称支持 5 分钟，但实际在 3-4 分钟后精度下降。设为 2 分钟上限，牺牲速度换精度。

## API 接口

### POST /align — 单文件对齐

```json
// 请求
{
  "audio": "/path/to/audio.mp3",
  "text": "/path/to/text.txt",
  "language": "English"
}

// 响应
{
  "word_count": 5000,
  "output_file": "/root/qwen-aligner-service/output/1_Burn_the_Throne.json",
  "words": [
    {"word": "The", "start": 0.0, "end": 0.12},
    {"word": "king", "start": 0.12, "end": 0.45}
  ]
}
```

### POST /batch — 批量对齐

```json
// 请求（路径留空则用默认 input/output 目录）
{
  "input_dir": "",
  "output_dir": "",
  "language": "English"
}

// 响应
{
  "total": 5,
  "success": 5,
  "failed": 0,
  "results": [
    {"audio": "ch1.mp3", "text": "ch1.txt", "word_count": 3200, "output_file": "...", "success": true}
  ]
}
```

input 目录中同名的 `.mp3` 和 `.txt` 自动配对（按 stem 匹配）。

### GET /health — 健康检查

```json
{"status": "ok", "device": "cuda", "models_loaded": true}
```

## 输出 JSON 格式

```json
{
  "audio": "1_Burn_the_Throne.mp3",
  "text": "1_Burn_the_Throne.txt",
  "word_count": 5000,
  "words": [
    {"word": "The", "start": 0.0, "end": 0.12},
    {"word": "king", "start": 0.12, "end": 0.45},
    {"word": "stood", "start": 0.45, "end": 0.78}
  ]
}
```

每个单词只包含纯文本（无标点），时间戳单位为秒，精确到毫秒。

## 部署

```bash
# 服务器: 192.168.0.5
ssh root@192.168.0.5
source /root/.venv/bin/activate
cd /root/qwen-aligner-service

# 指定 GPU 启动
CUDA_VISIBLE_DEVICES=2 python server.py
```

模型路径通过环境变量配置，默认：
- 对齐模型: `/models/huggingface/hub/models--Qwen--Qwen3-ForcedAligner-0.6B/snapshots/...`
- ASR 模型: `/models/huggingface/hub/models--Qwen--Qwen3-ASR-1.7B/snapshots/...`

## 后续：alignment_url 写入数据库

对齐 JSON 生成后，上传到 S3 并更新 `novel` 表的 `alignment_url` 字段：

```bash
python -m daily_py.services.novel.alignment_url_batch_update D:/output/timestamps --env prod
```

文件名需为 `{id}_{title}.json` 格式，工具自动从文件名提取 novel id。

## 文件结构

```
asr_serve/
  server.py          # FastAPI 服务，包含所有对齐逻辑
  requirements.txt   # Python 依赖
  start.sh           # 启动脚本
  DESIGN.md          # 本文档

daily_py/services/novel/
  alignment_url_batch_update.py  # 批量上传 JSON 到 S3 并更新数据库
```
