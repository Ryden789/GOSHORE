"""速查回流数据（L-3）：把错题与申论扣分点映射到速查考点。

- 行测：`answers` 的错题按 `documents.kaodian` 聚合，再用关键词匹配落到考点；
- 申论：`essay_weak_points` 的扣分点按名称匹配到方法论考点；
- 匹配不上的一律丢弃（前端静默不显示），保证「没有数据就不打扰」。

接口：`GET /api/notes/weak` → `{"xc": {"ziliao": {"考点标题": 3}}, "sl": {...}}`。
"""
from __future__ import annotations

from app import db, note_match, shenlun_notes, xingce_notes


def xc_weak() -> dict[str, dict[str, int]]:
    groups = {g["name"]: g for g in xingce_notes.NOTES["groups"]}
    out: dict[str, dict[str, int]] = {}
    for module, kaodian, n in db.wrong_by_kaodian():
        g = groups.get(module)
        if not g:
            continue
        p = note_match.best_point(kaodian, g["points"])
        if not p:
            continue
        bucket = out.setdefault(g["key"], {})
        bucket[p["title"]] = bucket.get(p["title"], 0) + n
    return out


def sl_weak() -> dict[str, dict[str, int]]:
    pairs = [(g, p) for g in shenlun_notes.NOTES["groups"] for p in g["points"]]
    out: dict[str, dict[str, int]] = {}
    for category, point_name, n in db.essay_weak_by_point():
        theme = f"{category} {point_name}"
        best, best_seg = None, ""
        for g, p in pairs:
            seg = note_match.segments(theme, note_match.blob(p))
            if len(seg) > len(best_seg):
                best, best_seg = (g, p), seg
        if not best or len(best_seg) < 3:
            continue
        g, p = best
        bucket = out.setdefault(g["key"], {})
        bucket[p["title"]] = bucket.get(p["title"], 0) + n
    return out


def build() -> dict[str, dict[str, dict[str, int]]]:
    return {"xc": xc_weak(), "sl": sl_weak()}
