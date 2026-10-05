# -*- coding: utf-8 -*-
"""学习路径规划（功能 2.1）：纯算法，不依赖 AI，零成本可离线跑。

输入能力雷达（各模块正确率）与考试日期，输出未来 N 天「每天练什么、练多少」。

设计原则：
1. **弱项加权**：模块分额 = 真题常规占比 × 弱项系数；正确率越低分额越高。
   未练的模块按「中等偏上」优先级处理（1.25），避免因没数据被完全忽略。
2. **保持考试结构**：以真题模块占比为基准，弱项加权后归一化，避免计划失衡。
3. **颗粒度**：题量取 5 的整数倍，方便直接调用组卷接口。
4. **考点轮换**：若提供薄弱考点池，每天给主练模块轮换指定一个考点。
5. **考前倒排**：有考试日期则按剩余天数压缩计划，考前最后一天安排全真模考。
"""
from __future__ import annotations

from datetime import date, timedelta

# 真题各模块常规占比（国考 / 事业单位联考行测近似）
MODULE_WEIGHT = {
    "言语理解": 0.26,
    "判断推理": 0.26,
    "数量关系": 0.14,
    "资料分析": 0.20,
    "常识判断": 0.14,
}

DAILY_N_DEFAULT = 30
DAYS_DEFAULT = 14
SLOT = 5                 # 题量颗粒度：每天每个模块题量都是 5 的倍数
MIN_DAILY_N = 10


def _weak_multiplier(rate, n: int) -> float:
    """弱项系数：正确率越低系数越大；未练按 1.25（略高于平均）。"""
    if not n or rate is None:
        return 1.25
    # 正确率 1.0 → 0.6；0.6 → 1.0；0.0 → 1.6
    return max(0.6, min(1.6, 1.6 - float(rate)))


def _shares(radar: list[dict]) -> dict[str, float]:
    """各模块分额（已归一化，和为 1）。"""
    raw: dict[str, float] = {}
    for m, w in MODULE_WEIGHT.items():
        r = next((x for x in radar if x.get("module") == m), None)
        mult = _weak_multiplier((r or {}).get("rate"), (r or {}).get("n", 0))
        raw[m] = w * mult
    tot = sum(raw.values()) or 1.0
    return {m: v / tot for m, v in raw.items()}


def _allocate(shares: dict[str, float], slots: int, offset: int = 0) -> dict[str, int]:
    """最大余额法把 slots 个槽位分给各模块；offset 用于跨天轮换打破平局。"""
    if slots <= 0 or not shares:
        return {}
    raw = {m: shares[m] * slots for m in shares}
    base = {m: int(raw[m]) for m in raw}
    used = sum(base.values())
    order = sorted(raw, key=lambda m: (-(raw[m] - base[m]), -(shares[m]), m))
    i = 0
    while used < slots and order:
        m = order[(i + offset) % len(order)]
        base[m] += 1
        used += 1
        i += 1
    return {m: v for m, v in base.items() if v > 0}


def build_plan(radar: list[dict], exam_date: str | None = None,
               days: int = DAYS_DEFAULT, daily_n: int = DAILY_N_DEFAULT,
               start: date | None = None,
               kaodian_pool: dict[str, list[str]] | None = None) -> list[dict]:
    """生成学习计划。

    radar: [{module, rate, n}]（含综应维度；综应不参与客观题分配）
    exam_date: 'YYYY-MM-DD'，可选；提供则按考试倒排并压缩天数
    kaodian_pool: {module: [薄弱考点...]}，每天给主练模块轮换指定考点
    返回: [{day:'YYYY-MM-DD', module, n, kaodian, done:0}]，按天升序
    """
    start = start or date.today()
    exam = None
    if exam_date:
        try:
            exam = date.fromisoformat(exam_date)
        except (ValueError, TypeError):
            exam = None

    days = max(1, int(days))
    if exam and exam > start:
        days = max(7, min(days, (exam - start).days))

    daily_n = max(MIN_DAILY_N, int(daily_n))
    shares = _shares(radar)
    slots_total = max(1, round(daily_n / SLOT))

    pool = kaodian_pool or {}
    kd_idx: dict[str, int] = {}
    items: list[dict] = []

    for d in range(days):
        today = start + timedelta(days=d)
        day = today.isoformat()
        # 考前最后一天：全真模考（整卷按考试题量）
        if exam and (today + timedelta(days=1)) == exam:
            items.append({"day": day, "module": "模考", "n": daily_n,
                          "kaodian": "", "done": 0})
            continue
        alloc = _allocate(shares, slots_total, offset=d)
        # 主练模块 = 当天题量最多的模块，用于挂考点
        main_m = max(alloc, key=lambda m: alloc[m]) if alloc else ""
        for m in sorted(alloc, key=lambda x: list(MODULE_WEIGHT).index(x)):
            kd = ""
            ks = pool.get(m) or []
            if ks:
                kd = ks[kd_idx.get(m, 0) % len(ks)]
                kd_idx[m] = kd_idx.get(m, 0) + 1
            items.append({"day": day, "module": m, "n": alloc[m] * SLOT,
                          "kaodian": kd if m == main_m else "", "done": 0})
    return items
