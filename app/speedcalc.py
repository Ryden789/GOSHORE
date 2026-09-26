"""速算训练场：程序按规则生成题目，答案由程序确定。

支持题型：
- arith       基础四则（2~4 位，可配位数）
- div_trunc   截位直除（a ÷ 1.xxx，四选一）
- frac_pct    特殊分数 ↔ 百分数（数字作答）
- base_growth 已知现期、r 求基期（四选一）
- growth_amt  增长量 = 现期 × r/(1+r)（四选一，干扰项含基期坑值）
"""
from __future__ import annotations

import random
from fractions import Fraction

# (分子, 分母, 百分数)
FRACTIONS = [
    (1, 2, 50), (1, 3, 33.3), (2, 3, 66.7), (1, 4, 25), (3, 4, 75),
    (1, 5, 20), (2, 5, 40), (3, 5, 60), (4, 5, 80),
    (1, 6, 16.7), (5, 6, 83.3), (1, 7, 14.3), (2, 7, 28.6), (3, 7, 42.9),
    (1, 8, 12.5), (3, 8, 37.5), (5, 8, 62.5), (7, 8, 87.5),
    (1, 9, 11.1), (2, 9, 22.2), (7, 9, 77.8), (1, 11, 9.1),
    (1, 12, 8.3), (1, 13, 7.7), (1, 15, 6.7), (1, 16, 6.25),
]
# 便于精确出题的增长率
RATES_NICE = [5, 8, 10, 12.5, 15, 20, 25, 33.3, 40, 50, 66.7]
RATES_AMOUNT = [10, 12.5, 14.3, 16.7, 20, 25, 33.3, 37.5, 50, 66.7, 87.5]

TYPE_LABELS = {
    "arith": "基础四则",
    "div_trunc": "截位直除",
    "frac_pct": "百化分",
    "base_growth": "基期计算",
    "growth_amt": "增长量计算",
}


def _rand_int(digits: int) -> int:
    return random.randint(10 ** (digits - 1), 10 ** digits - 1)


def _fmt(x: float) -> str:
    if abs(x) >= 100:
        return f"{round(x):,}".replace(",", "")
    if abs(x) >= 10:
        return f"{x:.1f}"
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _choice_options(answer: float, pits: list[float]) -> list[dict]:
    candidates = [answer] + pits
    formatted, seen = [], set()
    for v in candidates:
        t = _fmt(v)
        if t not in seen and float("inf") != v:
            seen.add(t)
            formatted.append((v, t))
    # 兜底补足干扰项
    k = 1
    while len(formatted) < 4:
        for delta in (0.05, 0.08, 0.12, 0.15):
            v = answer * (1 + (delta * k if k % 2 else -delta * k))
            t = _fmt(v)
            if t not in seen:
                seen.add(t)
                formatted.append((v, t))
            if len(formatted) == 4:
                break
        k += 1
    random.shuffle(formatted)
    options = []
    answer_label = ""
    for i, (_, t) in enumerate(formatted):
        label = "ABCD"[i]
        options.append({"label": label, "text": t})
        if _fmt(answer) == t:
            answer_label = label
    return options, answer_label


def _gen_arith(cfg: dict) -> dict:
    digits = int(cfg.get("digits", 3))
    ops = cfg.get("ops", ["+", "-", "×"])
    op = random.choice(ops)
    a, b = _rand_int(digits), _rand_int(digits)
    if op == "+":
        ans = a + b
        q = f"{a} + {b} ="
    elif op == "-":
        a, b = max(a, b), min(a, b)
        ans = a - b
        q = f"{a} − {b} ="
    elif op == "×":
        # 乘法用小一点的位数，避免过难
        a = random.randint(11, 99)
        b = random.randint(11, 99)
        ans = a * b
        q = f"{a} × {b} ="
    else:  # 整除
        q_div = random.randint(2, 19)
        ans = _rand_int(digits)
        a = q_div * ans
        q = f"{a} ÷ {q_div} ="
    return {
        "type": "arith",
        "q": q,
        "input": "number",
        "answer": str(ans),
        "explain": q.replace("=", "") + f"= {ans}",
    }


def _gen_div_trunc(cfg: dict) -> dict:
    a = random.randint(3000, 9999)
    d = round(random.uniform(1.05, 1.6), 3)
    ans = a / d
    pits = [
        a / (d * (1 + random.uniform(0.03, 0.08))),
        ans * (1 + random.uniform(0.05, 0.12)),
        ans * (1 - random.uniform(0.05, 0.12)),
    ]
    options, label = _choice_options(ans, pits)
    return {
        "type": "div_trunc",
        "q": f"{a} ÷ {_fmt(d)} ≈ ?",
        "input": "choice",
        "options": options,
        "answer": label,
        "explain": f"{a} ÷ {_fmt(d)} ≈ {_fmt(ans)}，截位直除对照选项",
    }


def _gen_frac_pct(cfg: dict) -> dict:
    n, d, pct = random.choice(FRACTIONS)
    if random.random() < 0.25:  # 少量反向：百分数 → 分数
        return {
            "type": "frac_pct",
            "q": f"{pct}% 约等于哪个分数？（请输入，如 1/8）",
            "input": "fraction",
            "answer": f"{n}/{d}",
            "tolerance": 0,
            "explain": f"{pct}% ≈ {n}/{d}",
        }
    return {
        "type": "frac_pct",
        "q": f"{n}/{d} ≈ ?%（保留一位小数即可）",
        "input": "number",
        "answer": str(pct),
        "tolerance": 0.15,
        "explain": f"{n}/{d} ≈ {pct}%",
    }


def _gen_base_growth(cfg: dict) -> dict:
    a = random.randint(3000, 49999)
    r = random.choice(RATES_NICE)
    ans = a / (1 + r / 100)
    pits = [
        a * (1 - r / 100),          # 常见错误：现期 ×(1−r)
        ans * (1 + random.uniform(0.04, 0.1)),
        ans * (1 - random.uniform(0.04, 0.1)),
    ]
    options, label = _choice_options(ans, pits)
    return {
        "type": "base_growth",
        "q": f"现期 {a}，同比增长 {_fmt(r)}%，基期 ≈ ?",
        "input": "choice",
        "options": options,
        "answer": label,
        "explain": f"基期 = {a} ÷ (1+{_fmt(r)}%) ≈ {_fmt(ans)}",
    }


def _gen_growth_amount(cfg: dict) -> dict:
    a = random.randint(3000, 49999)
    r = random.choice(RATES_AMOUNT)
    base = a / (1 + r / 100)
    ans = a - base
    fr = Fraction(str(r / 100)).limit_denominator(20)
    pits = [
        base,                                   # 坑：误算成基期
        a * r / 100,                            # 坑：忘记除以 1+r
        ans * (1 + random.uniform(0.08, 0.2)),
    ]
    options, label = _choice_options(ans, pits)
    return {
        "type": "growth_amt",
        "q": f"现期 {a}，同比增长 {_fmt(r)}%，增长量 ≈ ?",
        "input": "choice",
        "options": options,
        "answer": label,
        "explain": (
            f"增长量 = {a}×{_fmt(r)}%÷(1+{_fmt(r)}%) ≈ {_fmt(ans)}"
            f"（百化分：{_fmt(r)}%≈{fr.numerator}/{fr.denominator}）"
        ),
    }


_GENERATORS = {
    "arith": _gen_arith,
    "div_trunc": _gen_div_trunc,
    "frac_pct": _gen_frac_pct,
    "base_growth": _gen_base_growth,
    "growth_amt": _gen_growth_amount,
}


def generate(cfg: dict, n: int = 10) -> list[dict]:
    types = cfg.get("types") or list(_GENERATORS)
    types = [t for t in types if t in _GENERATORS]
    if not types:
        types = list(_GENERATORS)
    out = []
    for i in range(n):
        t = types[i % len(types)]
        p = _GENERATORS[t](cfg)
        p["id"] = i + 1
        out.append(p)
    random.shuffle(out)
    for i, p in enumerate(out):
        p["id"] = i + 1
    return out
