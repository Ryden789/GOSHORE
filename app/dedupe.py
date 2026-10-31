"""题库去重引擎（P1，调研文档 12.4）。

四步走，每步都可单独验证：

  1. **归一化** —— 复用 `app.qid.normalize_text`，与内容指纹同一套口径。
     两处口径一旦分叉，就会出现「指纹说同题、去重说不同题」的自相矛盾。
  2. **严格键** —— `qid.dedupe_key` 完全相同即同一道题（题干与选项集合都一致）。
     一组里保留「最完整」的一条，其余记 `dup_of`，**不删**：删掉的题如果
     还有历史作答，删了就是静默丢数据。
  3. **近重复** —— 题干 3-gram shingle 的 MinHash bottom-k 素描（k=128），
     按 32 段 × 4 行 banding 出候选对，再用**精确** Jaccard 复核：
     ≥ 0.90 判近重复并聚成 `variant_group`（同组只推送一道题）；
     0.80~0.90 不自动合并，进人工复核队列。
  4. **变式标记** —— 由调用方按 `variant_group` 落库（`variant_of` 的判定需要
     知道哪条是「母题」，那是业务规则，不在本模块里拍板）。

为什么不用 `datasketch`：本机离线、无新依赖是硬约束（见 pyproject 的依赖清单），
而且验收要求「同输入两次运行结果完全一致」——banding 用的桶键必须是纯函数。
`blake2b` + bottom-k 满足这两条；Python 内置 `hash()` 因为有 `PYTHONHASHSEED`
而**不能**用。

口径与出处：`docs/03-开发/2026-10-27-行测方向开源项目调研.md` 12.4 / 12.7。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app import qid as qidmod

# shingle 长度：3 字符。中文题干的区分度主要落在三字词上；
# 取 2 会撞得一塌糊涂，取 4 则「同一题改几个字」就判不出来了。
SHINGLE = 3

# 素描长度与 banding 参数：32 段 × 4 行 = 128。
# 4 行/段对 J=0.8 的单段命中率是 0.8^4≈0.41，32 段至少命中一段的概率 ≈ 1，
# 即 0.8 以上的近重复不会被 banding 漏掉（真正漏判交给精确 Jaccard 拦）。
SKETCH_SIZE = 128
BANDS = 32
ROWS = SKETCH_SIZE // BANDS

# 近重复阈值（12.4 第三步）
NEAR_DUP = 0.90
# 人工复核区间下界（12.4 第三步：0.8~0.9 进复核队列，不自动合并）
REVIEW_LOW = 0.80

# 只对前 320 个归一化字符做 shingle。
# 行测题干绝大多数在 120 字内，320 字已经覆盖「长材料 + 长设问」；
# 不设上限时，一道带大段材料的题会拖慢全库（2.3 万题的素描是瓶颈步骤）。
TEXT_CAP = 320


def shingles(text: str) -> tuple[str, ...]:
    """把文本切成 3-gram 集合（去重前，保序）。

    先按 `qid.normalize_text` 归一（去题号、去题型标注、去空白、统一标点），
    这样「1. （单选题）甲比乙快。」和「甲比乙快.」会切出同一组 shingle。
    标点归一后仍保留，避免把小数等不同内容判成严格重复。
    """
    s = qidmod.normalize_text(text)
    if not s:
        return ()
    s = s[:TEXT_CAP]
    if len(s) < SHINGLE:
        # 极短题干（如「见解析」）不足以切 gram，整串当一个 shingle。
        # 这类题天然会被判近重复 —— 但它们的题干本身就没有区分度，属真实现象。
        return (s,)
    return tuple(s[i:i + SHINGLE] for i in range(len(s) - SHINGLE + 1))


def hash64(token: str) -> int:
    """确定性 64 位整数哈希。不用内置 `hash()`：它随 `PYTHONHASHSEED` 变。"""
    return int.from_bytes(
        hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")


def sketch(grams) -> tuple[int, ...]:
    """MinHash bottom-k 素描：取最小的 k 个 shingle 哈希值（升序）。

    bottom-k 与「k 个独立置换取最小」是同一族估计量（KMV），但只需一次哈希
    每个 shingle —— 128 个置换的话，2.3 万题就是 300 亿次整数运算，跑不动。
    素描有序（升序）是 banding 的前提：顺序固定，桶键才是纯函数。
    """
    if not grams:
        return ()
    return tuple(sorted({hash64(g) for g in grams})[:SKETCH_SIZE])


def jaccard(a, b) -> float:
    """精确 Jaccard（集合口径）。两个空集按 0 处理，不返回 1。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    return inter / (len(sa) + len(sb) - inter)


def _candidates(sketches: list[tuple[int, ...]]) -> set[tuple[int, int]]:
    """banding 出候选对（下标对，i < j）。

    空素描 / 短于一段的素描不参与 —— 否则它们全落进同一个空桶，
    两万道题互相配对会直接把内存打爆。
    """
    buckets: dict[tuple[int, tuple[int, ...]], list[int]] = {}
    for i, sk in enumerate(sketches):
        for b in range(BANDS):
            start = b * ROWS
            band = sk[start:start + ROWS]
            if len(band) < ROWS:
                break
            buckets.setdefault((b, band), []).append(i)
    pairs: set[tuple[int, int]] = set()
    for idxs in buckets.values():
        if len(idxs) < 2:
            continue
        for x in range(len(idxs)):
            for y in range(x + 1, len(idxs)):
                pairs.add((idxs[x], idxs[y]))
    return pairs


@dataclass
class Result:
    """去重结论。只读，不改库 —— 落库是导入器的事。"""

    # 重复项 key -> 保留项 key（严格键判定的完全重复）
    dup_of: dict[str, str] = field(default_factory=dict)
    # 近重复成员 key -> 组号（`vg-<10 hex>`），同组只推送一道
    variant_group: dict[str, str] = field(default_factory=dict)
    # 人工复核队列：0.8 <= J < 0.9 的对，按 (a, b) 排序，a < b
    review_pairs: list[dict] = field(default_factory=list)
    # 统计口径，直接写进 import_report.json
    stats: dict = field(default_factory=dict)

    def summary(self) -> str:
        s = self.stats
        return (f"共 {s.get('total', 0)} 条，可比 {s.get('with_stem', 0)} 条；"
                f"严格重复 {s.get('strict_dups', 0)} 条（{s.get('strict_groups', 0)} 组），"
                f"近重复 {s.get('variant_items', 0)} 条（{s.get('variant_groups', 0)} 组），"
                f"待复核 {s.get('review_pairs', 0)} 对")


def plan(items, *, near: float = NEAR_DUP, review_low: float = REVIEW_LOW,
         progress=None) -> Result:
    """对一批题做去重规划。

    `items` 是字典序列，每项至少含：
      - `key`   稳定标识（qid 或 vault 相对路径），同批内唯一
      - `path`  相对路径（用于确定性排序与「保留哪条」）
      - `stem`  题干原文
      - `options` 选项原文列表（可为空）
      - `score` 完整度打分（可选，默认 0）：同一组严格重复里保留分数最高的那条

    确定性约定：结果只依赖 `items` 的**内容集合**，与传入顺序无关 ——
    排序键是 `(path, key)`，保留规则是 `(score 降序, path 升序)`。
    """
    entries = sorted(
        (dict(it) for it in items),
        key=lambda it: (str(it.get("path") or ""), str(it.get("key") or "")),
    )

    # ---- 第二步：严格键 ----
    groups: dict[str, list[dict]] = {}
    without_stem = 0
    for it in entries:
        stem = it.get("stem") or ""
        opts = it.get("options") or []
        dk = qidmod.dedupe_key(stem, opts)
        if not dk:
            without_stem += 1
            continue
        groups.setdefault(dk, []).append(it)

    dup_of: dict[str, str] = {}
    keepers: list[dict] = []
    strict_groups = 0
    for members in groups.values():
        keepers.append(_pick(members))
        if len(members) > 1:
            strict_groups += 1
            keeper = keepers[-1]
            for m in members:
                if m["key"] != keeper["key"]:
                    dup_of[m["key"]] = keeper["key"]

    # ---- 第三步：近重复（只在保留项之间找） ----
    keepers.sort(key=lambda it: (str(it.get("path") or ""), str(it["key"])))
    sketches = []
    for i, it in enumerate(keepers):
        if it.get("stem"):
            sketches.append(sketch(shingles(it["stem"])))
        else:
            sketches.append(())
        if progress and (i + 1) % 500 == 0:
            progress(i + 1, len(keepers), "sketch")

    pairs = _candidates(sketches)
    if progress:
        progress(len(keepers), len(keepers), "candidates")

    # 精确复核时才切 shingle：候选对通常只有几千对，重切一遍比常驻内存便宜
    # （12k 题 × 100 shingle 常驻约 60MB，在手机上不可接受）。
    grams_cache: dict[int, tuple[str, ...]] = {}

    def grams(i: int):
        g = grams_cache.get(i)
        if g is None:
            g = shingles(keepers[i].get("stem") or "")
            grams_cache[i] = g
        return g

    parent = list(range(len(keepers)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    review: list[dict] = []
    checked = 0
    for i, j in sorted(pairs):
        jac = jaccard(grams(i), grams(j))
        checked += 1
        if jac >= near:
            union(i, j)
        elif jac >= review_low:
            a, b = keepers[i], keepers[j]
            ka, kb = str(a["key"]), str(b["key"])
            review.append({"a": min(ka, kb), "b": max(ka, kb),
                           "jaccard": round(jac, 4)})

    by_root: dict[int, list[int]] = {}
    for i in range(len(keepers)):
        by_root.setdefault(find(i), []).append(i)

    variant_group: dict[str, str] = {}
    variant_groups = 0
    for members_idx in by_root.values():
        if len(members_idx) < 2:
            continue
        keys = sorted(str(keepers[i]["key"]) for i in members_idx)
        gid = "vg-" + hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()[:10]
        variant_groups += 1
        for k in keys:
            variant_group[k] = gid

    review.sort(key=lambda p: (p["a"], p["b"]))
    stats = {
        "total": len(entries),
        "with_stem": len(entries) - without_stem,
        "without_stem": without_stem,
        "strict_groups": strict_groups,
        "strict_dups": len(dup_of),
        "near_candidates": checked,
        "variant_groups": variant_groups,
        "variant_items": len(variant_group),
        "review_pairs": len(review),
        "params": {
            "shingle": SHINGLE,
            "sketch_size": SKETCH_SIZE,
            "bands": BANDS,
            "rows": ROWS,
            "text_cap": TEXT_CAP,
            "near_dup": near,
            "review_low": review_low,
            "hash": "blake2b-64",
        },
    }
    return Result(dup_of=dup_of, variant_group=variant_group,
                  review_pairs=review, stats=stats)


def _pick(members: list[dict]) -> dict:
    """同一组严格重复里保留哪条：完整度分高者优先，同分取路径字典序小的。"""
    return min(
        members,
        key=lambda it: (-int(it.get("score") or 0),
                        str(it.get("path") or ""), str(it.get("key") or "")),
    )
