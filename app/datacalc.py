"""资料分析本机复算：只在题干明确写出标签与数字时给算式，其余一律不输出。

答疑里最常见的坑是「数字在截图里、模型凭印象算」。本模块不读图，只从用户
输入的文本里抓「现期 / 基期 / 增长率 / 部分 / 整体」这类**带标签**的数字，
按固定公式算一遍并列算式；标签缺失、单位不一致或结果不成立时返回空串，
宁可不算也不编造。
"""
from __future__ import annotations

import re

# 单位只用于「同一道题内是否一致」的判断，不做换算：万/亿口径不同就不算。
_UNIT = r"(万|亿)?"
_NUM = r"([0-9][0-9,]*(?:\.[0-9]+)?)"
_ITEM = re.compile(
    r"(现期(?:值|量|数)?|基期(?:值|量|数)?|增长率|增速|增幅|增长量|部分|整体|总量)"
    r"[^0-9%]{0,12}" + _NUM + r"\s*" + _UNIT + r"\s*(%)?"
)
# 同一标签在一句话里可能出现多次，只取第一次，避免把例题解析里的数字也算进来
_ALIAS = {
    "现期值": "now", "现期量": "now", "现期数": "now", "现期": "now",
    "基期值": "base", "基期量": "base", "基期数": "base", "基期": "base",
    "增长率": "rate", "增速": "rate", "增幅": "rate",
    "增长量": "delta",
    "部分": "part", "整体": "whole", "总量": "whole",
}


def _parse(text: str) -> dict:
    """抽出各类标签的第一个数值，返回 {key: (value, unit, is_percent)}。"""
    found: dict = {}
    for m in _ITEM.finditer(text or ""):
        label = _ALIAS.get(m.group(1))
        if not label or label in found:
            continue
        raw = m.group(2).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        found[label] = (value, m.group(3) or "", bool(m.group(4)))
    return found


def _pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def _num(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return f"{round(v):,}"
    return f"{v:,.2f}"


def _unit_note(items: list[tuple[str, str]]) -> str | None:
    """单位一致才继续算；不一致返回 None（调用方据此放弃这一条）。"""
    units = {u for _, u in items}
    return "" if len(units) > 1 else next(iter(units), "")


def analyze(text: str) -> str:
    """文本 → 本机复算块；算不出或条件不足时返回空串。"""
    got = _parse(text)
    lines: list[str] = []

    if "now" in got and "base" in got:
        (a, ua, _), (b, ub, _) = got["now"], got["base"]
        unit = _unit_note([(str(a), ua), (str(b), ub)])
        if unit is not None and b:
            d = a - b
            lines.append(
                f"- 现期 {_num(a)}{ua}、基期 {_num(b)}{ub} → "
                f"增长量 = {_num(a)}-{_num(b)} = {_num(d)}{unit or ''}；"
                f"增长率 = {_num(d)}/{_num(b)} = {_pct(d / b)}"
            )

    if "now" in got and "rate" in got:
        (a, ua, _), (r, _, is_pct) = got["now"], got["rate"]
        rate = r / 100 if is_pct else r
        if rate > -1:
            base = a / (1 + rate)
            delta = a - base
            lines.append(
                f"- 现期 {_num(a)}{ua}、增长率 {_pct(rate)} → "
                f"基期 = {_num(a)}/(1+{_pct(rate)}) = {_num(base)}{ua}；"
                f"增长量 = {_num(a)}-{_num(base)} = {_num(delta)}{ua}"
            )

    if "base" in got and "rate" in got:
        (b, ub, _), (r, _, is_pct) = got["base"], got["rate"]
        rate = r / 100 if is_pct else r
        now = b * (1 + rate)
        lines.append(
            f"- 基期 {_num(b)}{ub}、增长率 {_pct(rate)} → "
            f"现期 = {_num(b)}×(1+{_pct(rate)}) = {_num(now)}{ub}；"
            f"增长量 = {_num(now)}-{_num(b)} = {_num(now - b)}{ub}"
        )

    if "part" in got and "whole" in got:
        (a, ua, _), (b, ub, _) = got["part"], got["whole"]
        unit = _unit_note([(str(a), ua), (str(b), ub)])
        if unit is not None and b:
            lines.append(
                f"- 部分 {_num(a)}{ua}、整体 {_num(b)}{ub} → "
                f"比重 = {_num(a)}/{_num(b)} = {_pct(a / b)}"
            )

    if not lines:
        return ""
    return (
        "【资料分析本机复算·按题干标签计算（可核对）】\n"
        + "\n".join(lines)
        + "\n使用限制：数字与标签按你输入的原文提取，单位不同或标签含义有歧义时本机不算；"
          "图中数字本机不读取。引用时请保留完整算式。"
    )
