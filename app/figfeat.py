"""图形推理（非黑白格）的本机像素统计：只给可核对的特征，不下规律结论。

黑白格九宫格由 `gridread` 做确定性求解；其余图推（线条、图形、数量类等）
无法靠像素唯一确定规律，但「墨迹占比 / 连通块数 / 封闭区域数 / 对称度」
这些属性是像素可测的。本模块把它们算出来作为证据交给模型，并明确写清
「本机只统计、不判断规律」，避免模型再编造一套无法核对的推理。

识别不出图块或缺少 Pillow/numpy 时返回空串，答疑退回原有看图流程。
"""
from __future__ import annotations

import numpy as np

from .gridread import _decode_gray

DARK = 110          # 与 gridread 同口径：截图纯黑白，110 足够二值化
STAT_SIDE = 160     # 统计前的缩放上限，控制连通块/封闭区域的开销
MIN_BLOCK = 28      # 图块最小边长（像素）
MIN_GAP = 10        # 空白分隔带最小宽度，小于它的空白不算分割


def _ink_runs(profile, threshold, gap: int = MIN_GAP):
    """一维墨迹剖面 → 连续区间。

    `profile` 是每行/列的墨迹像素数；低于阈值视为空白。空白宽度不足 `gap`
    的间隔并入同一区间，避免图形内部的一小段空隙把整块切开。
    """
    idx = np.flatnonzero(profile >= threshold)
    if not len(idx):
        return []
    out = []
    start = prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev < gap:
            prev = i
            continue
        out.append((start, prev))
        start = prev = i
    out.append((start, prev))
    return out


def _split_blocks(dark):
    """按空白行/列把整图切成图块，返回 [(y0, y1, x0, x1), ...]。

    只用于「一行或多行排列的独立小图」；切不出两个及以上图块时返回 []，
    调用方按单图处理。
    """
    h, w = dark.shape
    row_th = max(2, int(0.004 * w))
    col_th = max(2, int(0.004 * h))
    bands = [b for b in _ink_runs(dark.sum(axis=1), row_th)
             if b[1] - b[0] + 1 >= MIN_BLOCK]
    blocks = []
    for y0, y1 in bands:
        sub = dark[y0:y1 + 1]
        segs = [s for s in _ink_runs(sub.sum(axis=0), col_th)
                if s[1] - s[0] + 1 >= MIN_BLOCK]
        for x0, x1 in segs:
            blocks.append((y0, y1, x0, x1))
    return blocks if len(blocks) >= 2 else []


def _components(mask, min_pixels: int = 10) -> int:
    """4-连通暗色块数量（近似「笔画/连通块」）。"""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    count = 0
    for y in range(h):
        for x in range(w):
            if mask[y, x] and not seen[y, x]:
                stack = [(y, x)]
                seen[y, x] = True
                size = 0
                while stack:
                    cy, cx = stack.pop()
                    size += 1
                    for ny, nx in ((cy - 1, cx), (cy + 1, cx),
                                   (cy, cx - 1), (cy, cx + 1)):
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] \
                                and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
                if size >= min_pixels:
                    count += 1
    return count


def _holes(mask, min_pixels: int = 10) -> int:
    """封闭区域数（近似「面」）：不接触边界、且面积达标的空白连通块。"""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    count = 0
    for y in range(h):
        for x in range(w):
            if not mask[y, x] and not seen[y, x]:
                stack = [(y, x)]
                seen[y, x] = True
                size = 0
                touches = False
                while stack:
                    cy, cx = stack.pop()
                    size += 1
                    if cy in (0, h - 1) or cx in (0, w - 1):
                        touches = True
                    for ny, nx in ((cy - 1, cx), (cy + 1, cx),
                                   (cy, cx - 1), (cy, cx + 1)):
                        if 0 <= ny < h and 0 <= nx < w and not mask[ny, nx] \
                                and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
                if not touches and size >= min_pixels:
                    count += 1
    return count


def _resize(mask, side: int = 96):
    """按索引重采样成 side×side，够看对称性且不需要新依赖。"""
    h, w = mask.shape
    ys = (np.arange(side) * h // side).astype(int)
    xs = (np.arange(side) * w // side).astype(int)
    return mask[ys][:, xs]


def _crop(mask):
    idx = np.flatnonzero(mask.any(axis=1))
    jdx = np.flatnonzero(mask.any(axis=0))
    if not len(idx) or not len(jdx):
        return None
    return mask[idx[0]:idx[-1] + 1, jdx[0]:jdx[-1] + 1]


def _sym_score(mask, mode: str) -> float:
    """镜像/对角重合率（1=完全对称）。"""
    sq = _resize(_crop(mask))
    ref = sq.T if mode == "diag" else (np.fliplr(sq) if mode == "lr" else np.flipud(sq))
    return float(np.mean(sq == ref))


def _stats(gray) -> dict:
    dark = gray < DARK
    h, w = dark.shape
    out = {
        "w": w, "h": h,
        "ink": float(dark.mean()),
        "comps": _components(dark),
        "holes": _holes(dark),
    }
    if dark.any():
        out["lr"] = _sym_score(dark, "lr")
        out["ud"] = _sym_score(dark, "ud")
        if 0.7 <= w / max(1, h) <= 1.43:
            out["diag"] = _sym_score(dark, "diag")
    return out


def _line(label: str, st: dict) -> str:
    parts = [f"墨迹 {st['ink'] * 100:.1f}%",
             f"连通块 {st['comps']}", f"封闭区域 {st['holes']}"]
    parts.append(f"左右对称 {st.get('lr', 0) * 100:.0f}%")
    parts.append(f"上下对称 {st.get('ud', 0) * 100:.0f}%")
    if "diag" in st:
        parts.append(f"对角对称 {st['diag'] * 100:.0f}%")
    return f"- {label}（{st['w']}×{st['h']}）：" + "，".join(parts)


def analyze(url: str) -> str:
    """图片 → 本机像素统计底稿；读不出或特征过少时返回空串。"""
    gray = _decode_gray(url)
    if gray is None or min(gray.shape) < 60:
        return ""
    # 大图先缩到统计上限，避免 BFS 在大图上卡秒级
    scale = max(1, max(gray.shape) // STAT_SIDE)
    if scale > 1:
        gray = gray[::scale, ::scale]
    dark = gray < DARK
    if float(dark.mean()) < 0.001:
        return ""
    blocks = _split_blocks(dark)
    lines = ["【图形特征底稿·本机像素统计（只统计，不下结论）】",
             f"- 图像 {gray.shape[1]}×{gray.shape[0]}，墨迹占比 {float(dark.mean()) * 100:.1f}%"]
    if blocks:
        lines.append(f"- 按空白分隔检出 {len(blocks)} 个图块（从左到右、从上到下编号）")
        for n, (y0, y1, x0, x1) in enumerate(blocks[:9], 1):
            st = _stats(gray[y0:y1 + 1, x0:x1 + 1])
            lines.append(_line(f"图块{n}", st))
    else:
        lines.append(_line("整图", _stats(gray)))
    lines.append("使用限制：以上是像素级统计，不能判定平移/旋转/翻转/叠加/遍历等规律；"
                 "你要据此自行逐条验证，并明确说明哪些结论本机未验证、无法核对。")
    return "\n".join(lines)
