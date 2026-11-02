"""言语理解 / 逻辑判断的结构标记：只标关联词与句子位置，不替模型断语义。

这类题的标准解法第一步就是找「转折、结论、对策、条件」等标志词，再定重点句。
本机用规则把标志词和所在句号标出来，作为可核对证据注入；至于主旨是什么、
哪个选项最强，仍由模型据此判断——所以块内明确写「只标位置，不下结论」。
"""
from __future__ import annotations

import re

# (类别, 关键词, 判读提示)。单字词（却、才、更）容易误命中，只用多字词。
_MARKERS = (
    ("转折", ("但是", "然而", "不过", "却", "事实上", "其实", "相反", "反之"),
     "转折之后通常是文段重点"),
    ("结论", ("因此", "所以", "可见", "由此可见", "总之", "综上", "故而", "于是"),
     "结论词之后多为主旨/推论"),
    ("对策", ("应该", "需要", "必须", "应当", "建议", "亟需", "务必"),
     "对策句常是意图判断与落实的落点"),
    ("递进", ("而且", "甚至", "不仅如此", "并且"),
     "递进之后语义更重"),
    ("条件", ("只有", "除非", "只要", "否则"),
     "条件关系（只有…才 / 除非…否则）决定推理方向"),
    ("假设", ("如果", "倘若", "假如", "一旦"),
     "假设句常引导结论或对策"),
    ("并列", ("一方面", "另一方面", "同时", "此外", "另外"),
     "并列项要概括全面，不能只取其一"),
    ("比较", ("相比", "超过", "低于", "高于", "不如"),
     "比较项注意基期、方向与幅度"),
)

# 只在「言语 / 逻辑判断」类提问上触发，避免把结构标记塞进申论、常识等提问
_TRIGGER = (
    "主旨", "意在", "意图", "主要说明", "概括", "复述", "标题", "下文", "衔接",
    "排序", "语句", "逻辑填空", "成语", "实词", "文段", "以下哪项", "最能",
    "支持", "削弱", "加强", "假设", "前提", "结论", "推出", "真假", "翻译",
)

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


def _sentences(text: str) -> list[str]:
    out = []
    for chunk in _SENT_SPLIT.split(text.strip()):
        s = re.sub(r"\s+", "", chunk)
        if s:
            out.append(s)
    return out


def _snippet(sentence: str, marker: str, width: int = 42) -> str:
    i = sentence.find(marker)
    if i < 0:
        return sentence[:width]
    start = max(0, i - 12)
    return sentence[start:start + width]


def analyze(text: str) -> str:
    """文本 → 结构标记块；不像言语/逻辑题或没有标志词时返回空串。"""
    text = (text or "").strip()
    if len(text) < 40 or not any(k in text for k in _TRIGGER):
        return ""
    sents = _sentences(text)
    if len(sents) < 2:
        return ""
    hits = []
    for name, words, tip in _MARKERS:
        for idx, sent in enumerate(sents):
            found = next((w for w in words if w in sent), "")
            if not found:
                continue
            hits.append((idx, name, found, tip, sent))
            break
    if not hits:
        return ""
    hits.sort(key=lambda h: h[0])
    lines = ["【言语/逻辑结构标记·本机规则扫描（只标位置，不下结论）】",
             f"- 文段 {len(sents)} 句，约 {len(text)} 字"]
    for idx, name, word, tip, sent in hits:
        lines.append(f"- {name}：第 {idx + 1} 句命中「{word}」——{tip}；"
                     f"原句「{_snippet(sent, word)}」")
    lines.append(f"- 首句「{sents[0][:42]}」；尾句「{sents[-1][:42]}」")
    lines.append("使用限制：本机只匹配关联词与句子位置，语义、选项取舍与逻辑链仍由你判断；"
                 "没有标到的关联词不要当作已经验证。")
    return "\n".join(lines)
