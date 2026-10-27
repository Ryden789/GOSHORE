"""稳定题号（qid）生成：归一化 + 内容指纹。

为什么需要这个模块
------------------
`documents.id` 是 `lastrowid` 自增主键，稳定性只靠 `path UNIQUE +
ON CONFLICT(path)` 撑着。三种场景下它会整片重排：

  1. 换题库源目录（老库路径全变 → 全新建行）
  2. `content.db` 重建 / 跨设备导入
  3. 去重合并时保留哪一条不确定

复习排期（`review_plan`）、错题归因（`wrong_reasons`）、掌握度（`mastery`）、
收藏（`marks`）、笔记（`doc_notes`）一旦按自增 id 绑定，重导入后就会「串题」：
打开某道题看到的是别人的进度，而且**不报错**。qid 是题库自带的稳定编号，
没有自带编号时用「题干 + 选项」归一化后的内容指纹兜底。

口径与出处见 `docs/03-开发/2026-10-27-行测方向开源项目调研.md`
的 9.1 / 12.5 / 14.4 三节。

版本约定
--------
`FINGERPRINT_VERSION` 必须与归一化规则**同步**修改：规则一变，同一道题算出的
指纹就变，历史 qid 需要按版本批量重算并保留映射（`qid_map` 表 + `_meta`
里的 `qid_fp_version`）。不改版本号就改规则，会让「同一题两个 qid」悄悄混进库。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

# 指纹算法版本。归一化规则（`normalize_text` / `_option_text`）任何改动都要 +1。
FINGERPRINT_VERSION = "v1"

# 内容指纹前缀。与题库自带编号（如「2023国考-地市-判断-045」）一眼可分。
FP_PREFIX = "fp-"

# 自导入题的历史前缀。旧实现是 `imp-<批次>-<自增id>`，id 会重排 ⇒ 不稳定。
LEGACY_IMPORT_PREFIX = "imp-"

# 指纹取多少位十六进制。16 位 = 64 bit，题库量级（10^5）下碰撞概率可忽略，
# 且比全长 64 位短得多，写进日志/分享码里可读。
FP_LEN = 16

# 「1.」「第3题」「2、」「（4）」这类题号前缀。三条约束都来自真实题干：
#   ① 数字后必须**跟分隔符**：`2019年某市…` 不能被削成 `年某市…`
#   ② 分隔符后不能紧跟数字：`1.5万元…` 不能被削成 `5万元…`
#   ③ 括号形态限 1~2 位：`(2019)年…` 是年份不是题号
_TI_NUM_PREFIX = re.compile(
    r"^\s*(?:"
    r"第\s*[0-9]+\s*(?:小?题)?\s*[.、．。:：]?"
    r"|[（(【\[]\s*[0-9]{1,2}\s*[)）】\]]"
    r"|[0-9]{1,3}\s*[.、．)）](?![0-9])"
    r")\s*"
)

# 题型标注：「（单选题）」「(多选)」「【判断题】」。
# 「单选」「多选」要单列：`单选题` 是「单选 + 题」，`单项选择题` 才是「单项选择 + 题」。
_TI_TYPE_TAG = re.compile(
    r"[（(【\[]\s*"
    r"(?:单项选择|多项选择|不定项选择|单选|多选|选择|判断|填空|简答|论述|计算|分析)"
    r"题?\s*[)）】\]]"
)

# 引号/破折号归一：NFKC 不动这些，但不同来源确实混用。
_QUOTE_MAP = str.maketrans({
    "\u201c": '"', "\u201d": '"',      # “ ”
    "\u2018": "'", "\u2019": "'",      # ‘ ’
    "\uff02": '"', "\uff07": "'",      # ＂ ＇
    "\u3002": ".",                     # 。 → .
    "\u2014": "-", "\u2013": "-",      # — –
})

_WS = re.compile(r"\s+")


def normalize_text(text) -> str:
    """把题干/选项文本归一成「同内容同串」，用于算指纹与去重。

    规则（顺序有意义）：
      1. `NFKC`：全角转半角、异体字归一
      2. 去题号前缀、去题型标注（这两步依赖原文标点，必须在压缩空白之前做）
      3. 引号/破折号/句号归一
      4. 去掉**全部**空白（换行、全角空格都算）

    非字符串一律当空串（脏数据不抛异常）。
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:               # pragma: no cover - str() 几乎不抛
            return ""
    s = unicodedata.normalize("NFKC", text)
    s = _TI_NUM_PREFIX.sub("", s)
    s = _TI_TYPE_TAG.sub("", s)
    s = s.translate(_QUOTE_MAP)
    return _WS.sub("", s)


def _option_text(opt) -> str:
    """选项归一：兼容 `{"label","text"}` 与裸字符串两种形态。

    刻意**不带 label**：同一组选项打乱顺序（A/B/C/D 换位）时内容指纹应当不变，
    否则「同源变式」会被当成两道新题。label 属于展示层，不属于内容身份。
    """
    if isinstance(opt, dict):
        return normalize_text(opt.get("text", ""))
    return normalize_text(opt)


def content_fingerprint(stem, options=None) -> str:
    """由「题干 + 选项集合」算内容指纹，返回 `fp-<16 hex>`。

    选项先各自归一、再**排序**后拼接：顺序无关，内容相关。
    无题干时返回空串（调用方据此跳过，不要凭空造一个 `fp-` 出来）。
    """
    s = normalize_text(stem)
    if not s:
        return ""
    opts = sorted(_option_text(o) for o in (options or []))
    raw = s + "|" + "|".join(opts)
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return FP_PREFIX + h[:FP_LEN]


def dedupe_key(stem, options=None) -> str:
    """严格去重键（12.4 第二步）：与指纹同源，但不截断、不带前缀。

    用途不同：`content_fingerprint` 是给人看的稳定题号，
    `dedupe_key` 是给集合查重用的全长哈希（碰撞概率再低一个量级）。
    """
    s = normalize_text(stem)
    if not s:
        return ""
    opts = sorted(_option_text(o) for o in (options or []))
    return hashlib.sha256((s + "|" + "|".join(opts)).encode("utf-8")).hexdigest()


def is_unstable(qid) -> bool:
    """这个 qid 是否**不能**当稳定键用。

    两类：空串（题库没给编号且还没补指纹）、`imp-*`（旧自导入规则，含自增 id）。
    迁移与对账都按这个判定决定「要不要重算指纹」。
    """
    s = str(qid or "").strip()
    if not s:
        return True
    return s.startswith(LEGACY_IMPORT_PREFIX)


def stable_qid(existing, stem, options=None) -> str:
    """优先沿用题库自带编号；否则（空 / imp-*）用内容指纹。

    返回空串表示「既没有稳定编号，也算不出指纹（无题干）」——调用方应保留原值，
    不要用空串覆盖。
    """
    cur = str(existing or "").strip()
    if cur and not is_unstable(cur):
        return cur
    return content_fingerprint(stem, options)


def from_data(data: dict) -> str:
    """从 `documents.data` 解析出的字典算指纹（题库与自导入题共用一套规则）。"""
    if not isinstance(data, dict):
        return ""
    return content_fingerprint(data.get("stem", ""), data.get("options") or [])


def text_from_data(data: dict) -> tuple[str, list]:
    """取 `(stem, options)` 供对账/导入复用；脏数据返回 `("", [])`。"""
    if not isinstance(data, dict):
        return "", []
    opts = data.get("options")
    return data.get("stem", "") or "", opts if isinstance(opts, list) else []
