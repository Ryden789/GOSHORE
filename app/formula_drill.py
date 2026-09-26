"""资料分析「列式专项」：程序生成情境，只练列式判断、不做计算。

训练目标：看到材料条件 → 判断题型 → 选出正确列式。把资料分析的“列式反应”练快，
考场拿到式子后再配合速算（speedcalc）求结果。

题型（12 类，覆盖资料分析高频考法）：
- zengliang      增长量：现期×r/(1+r)
- jiqi           基期值：现期/(1+r)
- zengsu         增长率：(现期-基期)/基期
- xian_bizhong   现期比重：部分/整体
- ji_bizhong     基期比重：(C/D)×(1+r₂)/(1+r₁)
- bi_cha         比重差：(C/D)×(r₁-r₂)/(1+r₁)
- pingjun        现期平均数：总量/个数
- pingjun_su     平均数增长率：(r₁-r₂)/(1+r₂)
- beishu         倍数：A/B
- junian         年均增长量：(末年-初年)/年份差
- genian         隔年增长率：r₁+r₂+r₁r₂
- zengliang_bj   增长量比较：比较 A×r/(1+r)
"""
from __future__ import annotations

import random

RATES = [5, 6, 7, 7.5, 8, 9, 10, 12, 12.5, 15, 18, 20, 25]
# 两期增速（隔年用，错开）
RATES2 = [3, 4, 5, 6, 7, 8, 10, 12, 14]

TYPE_LABELS = {
    "zengliang": "增长量",
    "jiqi": "基期值",
    "zengsu": "增长率",
    "xian_bizhong": "现期比重",
    "ji_bizhong": "基期比重",
    "bi_cha": "比重差",
    "pingjun": "现期平均数",
    "pingjun_su": "平均数增长率",
    "beishu": "倍数",
    "junian": "年均增长量",
    "genian": "隔年增长率",
    "zengliang_bj": "增长量比较",
}

# 每题公式讲解（结算/答错时展示）
TIPS = {
    "zengliang": "已知现期A和增速r求增长量：A×r/(1+r)。最常见的坑是直接用A×r（那是拿现期当基期）。",
    "jiqi": "已知现期A和增速r求基期：A/(1+r)。注意是除不是乘。",
    "zengsu": "已知现期A和基期B求增长率：(A-B)/B，分母是基期B，不是现期A。",
    "xian_bizhong": "现期比重＝部分÷整体，先认清谁是整体。",
    "ji_bizhong": "基期比重＝(部分现期/整体现期)×(1+整体增速r₂)/(1+部分增速r₁)，增速调整因子别放反。",
    "bi_cha": "比重差(百分点)＝(C/D)×(r₁-r₂)/(1+r₁)，符号由部分与整体的增速差决定。",
    "pingjun": "现期平均数＝后量÷前量（单位“/”后面的量是分母），如单价＝总价÷数量。",
    "pingjun_su": "平均数增长率＝(总量增速r₁-个数增速r₂)/(1+r₂)，分母是个数增速。",
    "beishu": "A是B的几倍＝A/B；“A比B多几倍”＝A/B-1，注意问法。",
    "junian": "年均增长量＝(末年值-初年值)/间隔年份数，间隔数＝末年-初年（不+1）。",
    "genian": "隔年增长率＝r₁+r₂+r₁×r₂，别忘了两个增速的乘积项。",
    "zengliang_bj": "增长量比较直接比A×r/(1+r)：大大则大；一大一小看乘积或估算。",
}

SUBJECTS_GROWTH = [
    ("规模以上工业增加值", "亿元"), ("社会消费品零售总额", "亿元"),
    ("地区生产总值", "亿元"), ("粮食总产量", "万吨"),
    ("快递业务量", "亿件"), ("外贸进出口总值", "亿元"),
]
SUBJECTS_PART = [
    ("高新技术产品出口额", "外贸出口总额"),
    ("第三产业增加值", "地区生产总值"),
    ("地方教育支出", "一般公共预算支出"),
    ("乡村消费品零售额", "社会消费品零售总额"),
]
SUBJECTS_AVG = [
    ("商品房销售总额", "销售面积", "万元/平方米"),
    ("粮食总产量", "播种面积", "吨/公顷"),
    ("快递业务总收入", "业务量", "元/件"),
    ("规模以上工业利润总额", "企业数", "万元/家"),
]


def _r() -> int:
    return random.choice(RATES)


def _r2() -> int:
    return random.choice(RATES2)


def _base_q(t: str, ctx: str, ask: str, correct: str, pits: list[str]) -> dict:
    """组装：四个列式打乱，确定答案字母。"""
    opts = [correct] + pits
    random.shuffle(opts)
    answer = ""
    options = []
    for i, text in enumerate(opts):
        label = "ABCD"[i]
        options.append({"label": label, "text": text})
        if text == correct:
            answer = label
    return {
        "type": t, "type_name": TYPE_LABELS[t],
        "context": ctx, "q": ask,
        "options": options, "answer": answer, "tip": TIPS[t],
    }


# ---------------- 各题型生成 ----------------

def _gen_zengliang() -> dict:
    name, unit = random.choice(SUBJECTS_GROWTH)
    a = random.randint(120, 4800) * 10
    r = _r()
    if unit == "亿元":
        ctx = f"2025年某市{name}为{a}亿元，比上年增长{r}%。"
    elif unit == "万吨":
        ctx = f"2025年某省{name}为{a}万吨，比上年增长{r}%。"
    else:
        ctx = f"2025年全国{name}为{a}亿件，比上年增长{r}%。"
    ask = f"2025年该指标比上年增加了多少？下列列式正确的是（只列式，不计算）"
    correct = f"{a}×{r}%/(1+{r}%)"
    pits = [f"{a}×{r}%", f"{a}/(1+{r}%)", f"{a}×(1+{r}%)"]
    return _base_q("zengliang", ctx, ask, correct, pits)


def _gen_jiqi() -> dict:
    name, unit = random.choice(SUBJECTS_GROWTH)
    a = random.randint(120, 4800) * 10
    r = _r()
    if unit == "亿元":
        ctx = f"2025年某市{name}为{a}亿元，比上年增长{r}%。"
    elif unit == "万吨":
        ctx = f"2025年某省{name}为{a}万吨，比上年增长{r}%。"
    else:
        ctx = f"2025年全国{name}为{a}亿件，比上年增长{r}%。"
    ask = "2024年该指标约为多少？下列列式正确的是（只列式，不计算）"
    correct = f"{a}/(1+{r}%)"
    pits = [f"{a}×(1+{r}%)", f"{a}×{r}%", f"{a}-{a}×{r}%"]
    return _base_q("jiqi", ctx, ask, correct, pits)


def _gen_zengsu() -> dict:
    name, unit = random.choice(SUBJECTS_GROWTH)
    b = random.randint(200, 3000) * 10
    delta = random.randint(20, 600) * 10
    a = b + delta
    if unit == "亿元":
        ctx = f"某市{name}2024年为{b}亿元，2025年为{a}亿元。"
    elif unit == "万吨":
        ctx = f"某省{name}2024年为{b}万吨，2025年为a万吨。".replace("a", str(a))
    else:
        ctx = f"全国{name}2024年为{b}亿件，2025年为{a}亿件。"
    ask = "2025年该指标比上年增长百分之几？下列列式正确的是"
    correct = f"({a}-{b})/{b}"
    pits = [f"({a}-{b})/{a}", f"{b}/{a}", f"({a}-{b})/{b}-1"]
    return _base_q("zengsu", ctx, ask, correct, pits)


def _gen_xian_bizhong() -> dict:
    part, whole = random.choice(SUBJECTS_PART)
    d = random.randint(500, 4000) * 10
    c = random.randint(20, max(21, int(d * 0.6)))
    c = min(c, d - 10)
    ctx = f"2025年某市{whole}为{d}亿元，其中{part}为{c}亿元。"
    ask = f"2025年{part}占{whole}的比重约为多少？下列列式正确的是"
    correct = f"{c}/{d}"
    pits = [f"{d}/{c}", f"{c}/({c}+{d})", f"{c}×{d}"]
    return _base_q("xian_bizhong", ctx, ask, correct, pits)


def _gen_ji_bizhong() -> dict:
    part, whole = random.choice(SUBJECTS_PART)
    d = random.randint(500, 4000) * 10
    c = random.randint(30, max(40, int(d * 0.5)))
    r1, r2 = _r(), _r()
    while r1 == r2:
        r2 = _r()
    ctx = (f"2025年某市{whole}为{d}亿元，同比增长{r2}%；其中{part}为{c}亿元，"
           f"同比增长{r1}%。")
    ask = "2024年该部分占整体的比重约为多少？下列列式正确的是"
    correct = f"({c}/{d})×(1+{r2}%)/(1+{r1}%)"
    pits = [
        f"{c}/{d}",
        f"({c}/{d})×(1+{r1}%)/(1+{r2}%)",
        f"{c}×(1+{r1}%)/{d}",
    ]
    return _base_q("ji_bizhong", ctx, ask, correct, pits)


def _gen_bi_cha() -> dict:
    part, whole = random.choice(SUBJECTS_PART)
    d = random.randint(500, 4000) * 10
    c = random.randint(30, max(40, int(d * 0.5)))
    r1, r2 = _r(), _r()
    while r1 == r2:
        r2 = _r()
    ctx = (f"2025年某市{whole}为{d}亿元，同比增长{r2}%；其中{part}为{c}亿元，"
           f"同比增长{r1}%。")
    ask = "2025年该部分占整体的比重比上年上升或下降了多少个百分点？下列列式正确的是"
    correct = f"({c}/{d})×({r1}%-{r2}%)/(1+{r1}%)"
    pits = [
        f"({c}/{d})×({r2}%-{r1}%)/(1+{r2}%)",
        f"({c}/{d})×({r1}%-{r2}%)",
        f"({r1}%-{r2}%)/(1+{r1}%)",
    ]
    return _base_q("bi_cha", ctx, ask, correct, pits)


def _gen_pingjun() -> dict:
    total_name, n_name, _unit = random.choice(SUBJECTS_AVG)
    n = random.randint(120, 3000)
    t = n * random.randint(5, 80)
    ctx = f"2025年某市{total_name}为{t}亿元，{n_name}为{n}万。"
    if "面积" in n_name:
        ctx = f"2025年某市{total_name}为{t}亿元，{n_name}为{n}万平方米。"
    ask = f"2025年该市平均每单位{n_name}的{total_name}约为多少？下列列式正确的是"
    correct = f"{t}/{n}"
    pits = [f"{n}/{t}", f"{t}×{n}", f"{t}-{n}"]
    return _base_q("pingjun", ctx, ask, correct, pits)


def _gen_pingjun_su() -> dict:
    total_name, n_name, _u = random.choice(SUBJECTS_AVG)
    r1, r2 = _r(), _r()
    while r1 == r2:
        r2 = _r()
    ctx = f"2025年某市{total_name}比上年增长{r1}%，{n_name}比上年增长{r2}%。"
    ask = f"2025年平均每单位{n_name}的{total_name}比上年增长百分之几？下列列式正确的是"
    correct = f"({r1}%-{r2}%)/(1+{r2}%)"
    pits = [f"{r1}%-{r2}%", f"({r1}%-{r2}%)/(1+{r1}%)", f"({r2}%-{r1}%)/(1+{r1}%)"]
    return _base_q("pingjun_su", ctx, ask, correct, pits)


def _gen_beishu() -> dict:
    b = random.randint(100, 2000)
    k = random.randint(2, 6)
    a = b * k
    ctx = f"2025年甲市地区生产总值为{a}亿元，乙市为{b}亿元。"
    ask = "2025年甲市地区生产总值是乙市的多少倍？下列列式正确的是"
    correct = f"{a}/{b}"
    pits = [f"{b}/{a}", f"{a}-{b}", f"{a}/({a}+{b})"]
    return _base_q("beishu", ctx, ask, correct, pits)


def _gen_junian() -> dict:
    years = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
    y1, y2 = 2020, 2025
    n_gap = y2 - y1
    b = random.randint(200, 2000) * 10
    m = b + random.randint(100, 1500) * 10
    ctx = f"某市社会消费品零售总额{y1}年为{b}亿元，{y2}年为{m}亿元。"
    ask = f"{y1}—{y2}年间，该市社会消费品零售总额年均增加多少亿元？下列列式正确的是"
    correct = f"({m}-{b})/{n_gap}"
    pits = [f"({m}-{b})/{n_gap + 1}", f"{m}/{n_gap}", f"({m}+{b})/{n_gap}"]
    return _base_q("junian", ctx, ask, correct, pits)


def _gen_genian() -> dict:
    r1, r2 = _r(), _r2()
    ctx = f"某市地区生产总值2024年比上年增长{r1}%，2025年比上年增长{r2}%。"
    ask = "该市地区生产总值2025年比2023年增长百分之几？下列列式正确的是"
    correct = f"{r1}%+{r2}%+{r1}%×{r2}%"
    pits = [f"{r1}%+{r2}%", f"{r1}%×{r2}%", f"(1+{r1}%)×(1+{r2}%)"]
    return _base_q("genian", ctx, ask, correct, pits)


def _gen_zengliang_bj() -> dict:
    name, _u = random.choice(SUBJECTS_GROWTH)
    a1 = random.randint(300, 4000) * 10
    a2 = random.randint(300, 4000) * 10
    r1, r2 = _r(), _r()
    while r1 == r2:
        r2 = _r()
    ctx = (f"2025年甲市{name}为{a1}亿元、同比增长{r1}%，乙市同指标为{a2}亿元、"
           f"同比增长{r2}%。")
    ask = "不计算具体数值，判断2025年哪个市该指标的同比增加量更大？下列比较式正确的是"
    correct = f"比 {a1}×{r1}%/(1+{r1}%) 与 {a2}×{r2}%/(1+{r2}%)"
    pits = [
        f"比 {a1}×{r1}% 与 {a2}×{r2}%",
        f"比 {a1}/{r1} 与 {a2}/{r2}",
        f"比 {a1}×(1+{r1}%) 与 {a2}×(1+{r2}%)",
    ]
    return _base_q("zengliang_bj", ctx, ask, correct, pits)


_GENERATORS = {
    "zengliang": _gen_zengliang,
    "jiqi": _gen_jiqi,
    "zengsu": _gen_zengsu,
    "xian_bizhong": _gen_xian_bizhong,
    "ji_bizhong": _gen_ji_bizhong,
    "bi_cha": _gen_bi_cha,
    "pingjun": _gen_pingjun,
    "pingjun_su": _gen_pingjun_su,
    "beishu": _gen_beishu,
    "junian": _gen_junian,
    "genian": _gen_genian,
    "zengliang_bj": _gen_zengliang_bj,
}


def generate(types: list[str], n: int) -> list[dict]:
    """生成 n 道题（题型在 types 中等概率轮换）。"""
    keys = [t for t in types if t in _GENERATORS]
    if not keys:
        keys = list(_GENERATORS.keys())
    out = []
    for _ in range(n):
        out.append(_GENERATORS[random.choice(keys)]())
    return out
