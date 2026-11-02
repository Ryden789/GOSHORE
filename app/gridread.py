"""黑白格图形推理：本机像素转写 + 黑白叠加求解。

只处理一种稳定布局：3×3 九宫格（每格是 3×3 黑白小格）+ 下方 4 个同构选项。
识别置信度不够时返回 None，绝不用猜出来的矩阵去喂模型；转写成功后即使解不出
规律，也会明确写「本机无法判定」，供提示词禁止模型乱选。
"""
from __future__ import annotations

import base64
import io
import re

import numpy as np

_DATA_RE = re.compile(r"^data:image/(?:jpeg|jpg|png|webp);base64,(.+)$", re.I)

DARK = 110            # 二值化阈值：截图是纯黑白，110 足够
MIN_LINE_COVER = 0.78 # 线在区域内的覆盖率下限（黑块整列只有约 1/3）
MAX_LINE_WIDTH = 7    # 线宽上限；黑块整列/整行厚约 25~35px，会被排除


# -------------------------- 图像解码 --------------------------

def _decode_gray(url: str):
    m = _DATA_RE.fullmatch((url or "").strip())
    if not m:
        return None
    try:
        blob = base64.b64decode(m.group(1))
    except Exception:
        return None
    try:
        from PIL import Image, ImageOps
    except ImportError:          # 安卓端没带 Pillow 时静默降级
        return None
    try:
        im = Image.open(io.BytesIO(blob))
        im = ImageOps.exif_transpose(im).convert("L")
    except Exception:
        return None
    return np.asarray(im, dtype=np.uint8)


# -------------------------- 线检测 --------------------------

def _runs(mask, gap: int = 1):
    """一维布尔序列的连续 True 区间，允许 gap 像素的空隙。"""
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    out = []
    start = prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev <= gap:
            prev = i
            continue
        out.append((start, prev))
        start = prev = i
    out.append((start, prev))
    return out


def _group(vals, gap: int = 3):
    """把相邻的行号/列号并成一组，返回每组中心。"""
    groups: list[list[int]] = []
    for v in vals:
        if groups and v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [(g[0] + g[-1]) // 2 for g in groups]


def _line_centers(sub, axis: int, min_cover: float = MIN_LINE_COVER,
                  max_width: int = MAX_LINE_WIDTH):
    """在二值子图里找线：axis=0 找竖线（按列累加），axis=1 找横线。

    只保留「覆盖率够高且宽度够窄」的组——黑块整列/整行虽然也高，但太宽。
    """
    total = sub.shape[0] if axis == 0 else sub.shape[1]
    prof = sub.sum(axis=axis)
    idx = [i for i, v in enumerate(prof) if v >= min_cover * total]
    centers = []
    for c in _group(idx, gap=2):
        # 重新确定该组的宽度
        lo = hi = c
        while lo - 1 >= 0 and prof[lo - 1] >= min_cover * total:
            lo -= 1
        while hi + 1 < len(prof) and prof[hi + 1] >= min_cover * total:
            hi += 1
        if hi - lo + 1 <= max_width:
            centers.append(c)
    return centers


def _even_fill(lines, total: int):
    """线检不全时按外框等距补齐成 4 条。

    某一整行/整列都是黑块时，压在那里的分隔线会与黑块连成一片，被线宽上限
    过滤掉，只剩外框两条；此时用外框 3 等分补齐，格子中心位置不受影响。
    只检到两条内部线时跨度只占区域一小半，属于「外框没进来」，不能当外框补齐。
    """
    if len(lines) != 2:
        return None
    a, b = lines[0], lines[-1]
    if b - a < max(24, int(0.55 * total)):
        return None
    return [a + (b - a) * i // 3 for i in range(4)]


def _read_mini(dark, x0: int, x1: int, y0: int, y1: int, inset: int = 4):
    """读一个「3×3 黑白小格」图形，返回 3×3 的 0/1 矩阵；读不准返回 None。"""
    xa, xb = x0 + inset, x1 - inset + 1
    ya, yb = y0 + inset, y1 - inset + 1
    if xb - xa < 24 or yb - ya < 24:
        return None
    sub = dark[ya:yb, xa:xb]
    xs = _line_centers(sub, axis=0)
    ys = _line_centers(sub, axis=1)
    # 整行/整列黑块会把内部分隔线吃掉，按外框补齐
    if len(xs) != 4:
        xs = _even_fill(xs, sub.shape[1])
    if len(ys) != 4:
        ys = _even_fill(ys, sub.shape[0])
    if not xs or not ys:
        return None
    # 线距必须大致均匀，防止把黑块边缘误当分隔线
    for lines in (xs, ys):
        gaps = [lines[i + 1] - lines[i] for i in range(3)]
        if min(gaps) < 12 or max(gaps) > min(gaps) * 1.6:
            return None
    mat = []
    for r in range(3):
        row = []
        for c in range(3):
            cx = (xs[c] + xs[c + 1]) // 2
            cy = (ys[r] + ys[r + 1]) // 2
            patch = sub[cy - 2:cy + 3, cx - 2:cx + 3]
            frac = float(patch.mean())      # sub 已是二值暗色掩码，1=黑
            if 0.18 < frac < 0.82:
                return None          # 灰度模糊/压线，判不准
            row.append(1 if frac >= 0.82 else 0)
        mat.append(row)
    return mat


# -------------------------- 整图转写 --------------------------

def _pick_uniform(lines, gap_min: int = 40, ratio: float = 1.35):
    """从候选线里挑 4 条等距的（九宫格 3×3）。

    候选里既有表格外框，也有各小格内部的分隔线和下方选项框边框。所以不能
    只看「连续 4 条」，也不能只看跨度：按「两个理想等分点附近各取一条」枚举，
    再取间距最均匀的一组（选项框被并进来时第 2 个间距会明显变大）。
    """
    best = None
    n = len(lines)
    for i in range(n - 3):
        for l in range(i + 3, n):
            span = lines[l] - lines[i]
            step = span / 3.0
            if step < gap_min:
                continue
            j = min((t for t in range(i + 1, l)),
                    key=lambda t: abs(lines[t] - (lines[i] + step)))
            if j + 1 >= l:
                continue
            k = min((t for t in range(j + 1, l)),
                    key=lambda t: abs(lines[t] - (lines[i] + 2 * step)))
            win = [lines[i], lines[j], lines[k], lines[l]]
            gaps = [win[t + 1] - win[t] for t in range(3)]
            if min(gaps) < gap_min or max(gaps) > min(gaps) * ratio:
                continue
            key = (round(max(gaps) / min(gaps), 2), -span, win[0])
            if best is None or key < best[0]:
                best = (key, win)
    return best[1] if best else None


def _read_mini_any(dark, x0: int, x1: int, y0: int, y1: int):
    """在候选框里找一个 3×3 小格。

    选项框有两种可能：整框外边框（内缩 10px 才是小格）或小格自身的边框
    （不需要内缩）。逐个内缩量试，取第一个读得准的。
    """
    for inset in (0, 3, 5, 8, 10, 12):
        m = _read_mini(dark, x0, x1, y0, y1, inset=inset)
        if m is not None:
            return m
    return None


def _read_panels_and_options(gray):
    dark = gray < DARK
    h, w = dark.shape
    if h < 260 or w < 260:
        return None

    # 主九宫格：找贯穿 30% 以上宽/高的长线
    min_h = max(60, int(0.28 * w))
    min_v = max(60, int(0.28 * h))
    hrows = [y for y in range(h)
             if any(b - a + 1 >= min_h for a, b in _runs(dark[y], 1))]
    vcols = [x for x in range(w)
             if any(b - a + 1 >= min_v for a, b in _runs(dark[:, x], 1))]
    hc = _pick_uniform(_group(hrows))
    vc = _pick_uniform(_group(vcols))
    if hc is None or vc is None:
        return None

    panels = []
    for r in range(3):
        row = []
        for c in range(3):
            row.append(_read_mini(dark, vc[c], vc[c + 1], hc[r], hc[r + 1]))
        panels.append(row)
    # 只允许「右下角问号位」缺一格；缺在别处说明布局不是本题型
    missing = [(r, c) for r in range(3) for c in range(3) if panels[r][c] is None]
    if len(missing) != 1 or missing[0] != (2, 2):
        return None

    # 选项：主网格下方，找「同一行有多段 8%~35% 宽」的横线组
    lo, hi = int(0.08 * w), int(0.35 * w)
    cand = []
    for y in range(hc[3] + 8, h):
        n = sum(1 for a, b in _runs(dark[y], 1) if lo <= b - a + 1 <= hi)
        if n >= 2:
            cand.append(y)
    bands = _group(cand, gap=4)
    if len(bands) < 2:
        return None
    yt, yb = bands[0], bands[-1]
    if yb - yt < 60:
        return None
    # 选项框上边界所在行：取该组中间一行，找四段等宽横线
    rows = [y for y in range(yt - 4, yt + 5)
            if any(lo <= b - a + 1 <= hi for a, b in _runs(dark[y], 1))]
    if not rows:
        return None
    segs = [(a, b) for a, b in _runs(dark[rows[len(rows) // 2]], 1)
            if lo <= b - a + 1 <= hi]
    if len(segs) != 4:
        return None
    widths = [b - a + 1 for a, b in segs]
    if max(widths) > min(widths) * 1.25:
        return None
    options = {}
    for name, (x0, x1) in zip("ABCD", segs):
        options[name] = _read_mini_any(dark, x0, x1, yt, yb)
    if any(m is None for m in options.values()):
        return None
    return panels, options


# -------------------------- 求解 --------------------------

_TRANSFORMS = [
    ("", lambda a: a),
    ("水平翻转", np.fliplr),
    ("垂直翻转", np.flipud),
    ("旋转 90°", lambda a: np.rot90(a, -1)),
    ("旋转 180°", lambda a: np.rot90(a, 2)),
    ("旋转 270°", lambda a: np.rot90(a, 1)),
    ("转置", lambda a: a.T),
    ("反对角翻转", lambda a: np.rot90(np.fliplr(a), 2)),
]

_OPS = [
    ("xor", "去同存异（黑+黑=白、白+白=白、黑白相异=黑）", lambda x, y: x ^ y),
    ("xnor", "去异存同（同色为黑、异色为白）", lambda x, y: 1 - (x ^ y)),
    ("and", "黑块取交（只有重合处为黑）", lambda x, y: x & y),
    ("or", "黑块取并（任一为黑则黑）", lambda x, y: x | y),
    ("a_not_b", "只保留第一幅独有的黑块", lambda x, y: x & (1 - y)),
    ("b_not_a", "只保留第二幅独有的黑块", lambda x, y: y & (1 - x)),
]


def _grid(g):
    return np.array(g, dtype=np.int8)


def _fmt(m) -> str:
    return "/".join("".join("■" if v else "□" for v in row) for row in m)


def solve(panels, options):
    """枚举「方向 × 运算 × 对称」；至少两组独立验证通过才认。

    九宫格右下角是问号位（panels[2][2] 为 None），前两行/前两列用来验证规律。
    """
    P = [[None if panels[r][c] is None else _grid(panels[r][c])
          for c in range(3)] for r in range(3)]
    hits = []
    for axis in ("col", "row"):
        if axis == "col":
            groups = [tuple(P[r][c] for r in range(3)) for c in range(3)]
            ver = groups[:2]                     # 第 1、2 列
            a, b = groups[2][0], groups[2][1]    # 第 3 列上面两格
        else:
            groups = [tuple(P[r][c] for c in range(3)) for r in range(3)]
            ver = groups[:2]                     # 第 1、2 行
            a, b = groups[2][0], groups[2][1]    # 第 3 行前两格
        for opk, desc, op in _OPS:
            for tname, tf in _TRANSFORMS:
                for rname, rf in _TRANSFORMS:
                    ok = True
                    for g in ver:
                        if not np.array_equal(rf(op(tf(g[0]), tf(g[1]))),
                                              g[2]):
                            ok = False
                            break
                    if not ok:
                        continue
                    pred = rf(op(tf(a), tf(b)))
                    matched = [k for k, o in options.items()
                               if np.array_equal(_grid(o), pred)]
                    if matched:
                        hits.append({
                            "axis": axis, "op": opk, "desc": desc,
                            "t2": tname, "res": rname,
                            "pred": pred.tolist(), "answers": matched,
                        })
    if not hits:
        return None, "未找到可用规律"
    answers = {a for h in hits for a in h["answers"]}
    if len(answers) > 1:
        return None, "多个规律指向不同选项，无法唯一判定"
    best = sorted(hits, key=lambda h: (
        h["t2"] != "" or h["res"] != "",
        [o[0] for o in _OPS].index(h["op"]),
        h["axis"] != "col",
    ))[0]
    return best, ""


# -------------------------- 输出底稿 --------------------------

def _block(panels, options, rule, reason: str) -> str:
    lines = ["【黑白格转写与本地求解·本机像素识别】",
             "九宫格（■黑 □白，逐格转写；? 为题面问号格）："]
    for r in range(3):
        parts = [f"{r + 1}-{c + 1} " + ("?" if panels[r][c] is None
                                         else _fmt(panels[r][c]))
                 for c in range(3)]
        lines.append("  " + "   ".join(parts))
    lines.append("选项：")
    for k in "ABCD":
        lines.append(f"  {k} {_fmt(options[k])}")
    if rule:
        how = ("按列" if rule["axis"] == "col" else "按行")
        move = "同位置叠加"
        if rule["t2"] or rule["res"]:
            move = "先" + (f"把第二幅{rule['t2']}" if rule["t2"] else "") \
                   + ("、" if rule["t2"] and rule["res"] else "") \
                   + (f"叠加结果{rule['res']}" if rule["res"] else "")
        lines += [
            "",
            f"【本机求解】{how}、{rule['desc']}，{move}："
            f"第 1 {'列' if rule['axis'] == 'col' else '行'}、"
            f"第 2 {'列' if rule['axis'] == 'col' else '行'}两组独立验证全部通过；"
            f"第 3 {'列' if rule['axis'] == 'col' else '行'}推出 "
            f"{_fmt(rule['pred'])}，与 {rule['answers'][0]} 唯一匹配。",
            f"【结论】{rule['answers'][0]}。以上转写与答案来自本机像素与确定性计算，"
            "必须以此为准；不得改写答案，也不要再自行「验证」出不同结论。",
        ]
    else:
        lines += [
            "",
            f"【本机求解】{reason}（按行/按列 × 6 种运算 × 8 种对称均未通过两组独立验证）。",
            "本机无法判定。禁止给出任何选项；只讲可能的思路，并明确说明无法判定。",
        ]
    return "\n".join(lines)


def analyze(url: str):
    """对一张 data URL 图片做转写+求解；不是该布局/读不准时返回 None。"""
    gray = _decode_gray(url)
    if gray is None:
        return None
    got = _read_panels_and_options(gray)
    if not got:
        return None
    panels, options = got
    rule, reason = solve(panels, options)
    return {
        "panels": panels,
        "options": options,
        "answer": rule["answers"][0] if rule else None,
        "rule": rule,
        "reason": reason,
        "block": _block(panels, options, rule, reason),
    }
