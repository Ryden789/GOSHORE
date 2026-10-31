"""`app/dedupe.py` 去重引擎的回归测试（P1 / 调研文档 12.4）。

守四件事：

  1. **归一化口径与 qid 一致**：题号前缀 / 题型标注 / 全半角 / 空白都不影响去重，
     否则「加了（单选题）标记的同一题」会被当成新题进库。
  2. **确定性**：同输入跑两次、以及打乱输入顺序，结论必须一模一样 ——
     验收要求 `import_report.json` 同输入两次运行完全一致，去重是其中一环。
  3. **严格键 vs 近重复分层**：完全同题记 `dup_of`；改几个字的近重复聚组；
     改一段的落人工复核队列，**不**自动合并。
  4. **保留规则可解释**：一组严格重复里保留完整度最高的那条，同分取路径小的。
"""
from __future__ import annotations

from app import dedupe


def _item(key, stem, options=None, path=None, score=0):
    return {"key": key, "stem": stem, "options": options or [],
            "path": path if path is not None else f"{key}.md", "score": score}


def _unique_text(n: int) -> str:
    """构造 n 个互不相同的 CJK 字符，让 3-gram 互不重复（便于精确推算 Jaccard）。"""
    return "".join(chr(0x4E00 + i * 7) for i in range(n))


def _mutate(text: str, positions, ch="★") -> str:
    out = list(text)
    for p in positions:
        out[p] = ch
    return "".join(out)


# ---------------- 归一化 / 切片 ----------------

def test_shingles_ignore_question_number_and_type_tag():
    # 顺序按题库实际写法：题号在前、题型标注在后（剥离规则也是这个顺序）
    a = dedupe.shingles("1. （单选题）甲比乙快，因为甲先到。")
    b = dedupe.shingles("甲比乙快,因为甲先到.")
    assert a == b and a


def test_normalization_preserves_decimal_point():
    a = _item("a", "某人用时1.5小时")
    b = _item("b", "某人用时15小时")
    assert dedupe.shingles(a["stem"]) != dedupe.shingles(b["stem"])
    assert dedupe.plan([a, b]).dup_of == {}


def test_shingles_empty_for_blank():
    assert dedupe.shingles("") == ()
    assert dedupe.shingles("   ") == ()


def test_short_stem_becomes_single_shingle():
    # 短到切不出 3-gram 时整串当一个 shingle，不返回空（否则短题不参与去重）
    assert dedupe.shingles("见解析") == ("见解析",)


# ---------------- 素描 ----------------

def test_sketch_is_deterministic_and_order_independent():
    text = _unique_text(60)
    g1 = dedupe.shingles(text)
    g2 = tuple(reversed(g1))
    assert dedupe.sketch(g1) == dedupe.sketch(g1)   # 两次相同
    assert dedupe.sketch(g1) == dedupe.sketch(g2)   # 与 shingle 顺序无关
    assert dedupe.sketch(g1) == tuple(sorted(dedupe.sketch(g1)))  # 升序
    assert len(dedupe.sketch(g1)) <= dedupe.SKETCH_SIZE


def test_hash64_is_stable_across_calls():
    # 不能用内置 hash()：它随 PYTHONHASHSEED 变，报告就不可复现了
    assert dedupe.hash64("甲比乙快") == dedupe.hash64("甲比乙快")


def test_jaccard_bounds():
    assert dedupe.jaccard([], ["a"]) == 0.0
    assert dedupe.jaccard(["a"], []) == 0.0
    assert dedupe.jaccard(["a", "b"], ["a", "b"]) == 1.0
    assert dedupe.jaccard(["a", "b"], ["b", "c"]) == 1 / 3


# ---------------- 严格重复 ----------------

def test_strict_duplicate_keeps_richest_and_records_dup_of():
    base = "甲的速度是乙的两倍，两人同时出发相向而行，几小时后相遇？"
    items = [
        _item("k1", base, ["A. 2小时", "B. 3小时"], path="a.md", score=2),
        _item("k2", "1. " + base, ["B. 3小时", "A. 2小时"], path="b.md", score=9),
    ]
    r = dedupe.plan(items)
    assert r.stats["strict_dups"] == 1
    # 选项顺序与题号前缀都不该影响「同题」判定
    assert r.dup_of == {"k1": "k2"}
    assert r.stats["strict_groups"] == 1


def test_strict_duplicate_tie_breaks_on_path():
    stem = "某班有男生20人，女生30人，男生占比多少？"
    r = dedupe.plan([_item("k2", stem, path="b.md"),
                     _item("k1", stem, path="a.md")])
    assert r.dup_of == {"k2": "k1"}


# ---------------- 近重复 ----------------

def test_near_duplicate_grouped_at_or_above_threshold():
    stem = _unique_text(200)
    variant = _mutate(stem, [50])           # 改 1 个字 → Jaccard 很高
    jac = dedupe.jaccard(dedupe.shingles(stem), dedupe.shingles(variant))
    assert jac >= dedupe.NEAR_DUP

    r = dedupe.plan([_item("a", stem), _item("b", variant)])
    assert r.stats["variant_groups"] == 1
    assert r.stats["variant_items"] == 2
    assert r.variant_group["a"] == r.variant_group["b"]
    assert r.variant_group["a"].startswith("vg-")


def test_borderline_pair_goes_to_review_not_merged():
    stem = _unique_text(200)
    variant = _mutate(stem, [20, 60, 100, 140, 180, 190])   # 6 字 → 0.8~0.9
    jac = dedupe.jaccard(dedupe.shingles(stem), dedupe.shingles(variant))
    assert dedupe.REVIEW_LOW <= jac < dedupe.NEAR_DUP

    r = dedupe.plan([_item("a", stem), _item("b", variant)])
    assert r.variant_group == {}                 # 不自动合并
    assert len(r.review_pairs) == 1
    p = r.review_pairs[0]
    assert (p["a"], p["b"]) == ("a", "b")
    assert dedupe.REVIEW_LOW <= p["jaccard"] < dedupe.NEAR_DUP


def test_unrelated_questions_not_grouped():
    r = dedupe.plan([_item("a", _unique_text(120)), _item("b", _unique_text(80))])
    assert r.variant_group == {} and r.review_pairs == []


# ---------------- 确定性 ----------------

def test_plan_is_independent_of_input_order():
    stem = _unique_text(200)
    items = [
        _item("a", stem),
        _item("b", stem, path="b.md"),                      # 严格重复
        _item("c", _mutate(stem, [30])),                    # 近重复
        _item("d", _mutate(stem, [10, 80, 150, 170, 180, 190])),  # 待复核
    ]
    r1 = dedupe.plan(items)
    r2 = dedupe.plan(list(reversed(items)))
    assert r1.dup_of == r2.dup_of
    assert r1.variant_group == r2.variant_group
    assert r1.review_pairs == r2.review_pairs
    assert r1.stats == r2.stats


def test_items_without_stem_are_counted_but_skipped():
    r = dedupe.plan([_item("k1", ""), _item("k2", "甲比乙快")])
    assert r.stats["without_stem"] == 1
    assert r.stats["total"] == 2
    assert r.dup_of == {} and r.variant_group == {}


def test_summary_is_human_readable():
    r = dedupe.plan([_item("a", "甲比乙快")])
    assert "共 1 条" in r.summary()
