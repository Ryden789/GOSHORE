"""稳定题号模块（`app/qid.py`）的回归测试。

背景见 `docs/03-开发/2026-10-27-行测方向开源项目调研.md` 9.1 / 12.5 / 14.4：
`documents.id` 是自增主键，换源目录 / 重建 content.db / 跨设备导入都会重排，
复习与错题记录若绑在自增 id 上就会整片错位。qid 是这批个人数据的新主键，
本文件守住它的三条性质：

  1. **确定性**：同内容必得同 qid，且与来源、空白、选项顺序、label 无关
  2. **区分性**：内容不同必得不同 qid
  3. **稳定性判定**：空串与 `imp-*`（旧自导入规则）必须被判为不稳定
"""
from __future__ import annotations

from app import qid as q


# ---------------- 归一化 ----------------

def test_normalize_strips_whitespace_and_fullwidth():
    """空白与全角字符不影响归一结果。"""
    assert q.normalize_text("  下列　说法 正确\r\n的是 ") == "下列说法正确的是"
    # NFKC 把全角字母数字压成半角
    assert q.normalize_text("ＡＢＣ１２３") == "ABC123"
    # 全角括号题号与半角等价：都当题号前缀削掉
    assert q.normalize_text("（１）下列说法") == "下列说法"
    assert q.normalize_text("(1)下列说法") == "下列说法"
    # 括号里的数字若不是题号（后面没有分隔符），保留
    assert q.normalize_text("（１亿元）") == "(1亿元)"


def test_normalize_drops_question_number_prefix():
    """「1.」「第3题」「2、」这类题号前缀要去掉。"""
    assert q.normalize_text("1. 下列说法正确的是") == "下列说法正确的是"
    assert q.normalize_text("第3题 下列说法正确的是") == "下列说法正确的是"
    assert q.normalize_text("2、下列说法正确的是") == "下列说法正确的是"
    assert q.normalize_text("（4）下列说法正确的是") == "下列说法正确的是"


def test_normalize_keeps_leading_year():
    """题号前缀必须带分隔符：`2019年…` 不能被削成 `年…`。

    这是最容易写错的一条 —— 行测题干里「年份开头」极常见，
    正则若写成 `^\\d+` 就会把年份吃掉，让大批题算出同一个指纹。
    """
    assert q.normalize_text("2019年某市GDP增长5%") == "2019年某市GDP增长5%"
    assert q.normalize_text("2023年国考行测第45题") == "2023年国考行测第45题"


def test_normalize_drops_type_tag():
    """「（单选题）」这类题型标注属于元信息，不进内容身份。"""
    assert q.normalize_text("（单选题）下列说法正确的是") == "下列说法正确的是"
    assert q.normalize_text("【多选题】下列说法正确的是") == "下列说法正确的是"


def test_normalize_handles_dirty_input():
    """None / 非字符串 / 空串都要安全。"""
    assert q.normalize_text(None) == ""
    assert q.normalize_text(123) == "123"
    assert q.normalize_text("") == ""


# ---------------- 指纹 ----------------

STEM = "某市2019年GDP为1000亿元，2020年增长10%，问2020年GDP为多少？"
OPTS = [{"label": "A", "text": "1100亿元"}, {"label": "B", "text": "1010亿元"},
        {"label": "C", "text": "1090亿元"}, {"label": "D", "text": "1200亿元"}]


def test_fingerprint_is_deterministic():
    a = q.content_fingerprint(STEM, OPTS)
    b = q.content_fingerprint(STEM, OPTS)
    assert a == b
    assert a.startswith(q.FP_PREFIX)
    assert len(a) == len(q.FP_PREFIX) + q.FP_LEN


def test_fingerprint_ignores_whitespace_and_label():
    """空白、label、选项顺序都不改变内容指纹。"""
    base = q.content_fingerprint(STEM, OPTS)
    noisy_stem = "  某市2019年GDP为1000亿元，\n 2020年增长10%，问2020年GDP为多少？ "
    assert q.content_fingerprint(noisy_stem, OPTS) == base
    # label 换位 / 选项顺序打乱
    shuffled = [
        {"label": "D", "text": "1200亿元"}, {"label": "C", "text": "1090亿元"},
        {"label": "B", "text": "1010亿元"}, {"label": "A", "text": "1100亿元"},
    ]
    assert q.content_fingerprint(STEM, shuffled) == base
    # 裸字符串选项（自导入题的另一种形态）
    assert q.content_fingerprint(STEM, ["1100亿元", "1010亿元", "1090亿元", "1200亿元"]) == base


def test_fingerprint_distinguishes_content():
    """题干或选项任一不同，指纹必须不同。"""
    base = q.content_fingerprint(STEM, OPTS)
    assert q.content_fingerprint(STEM + "（保留两位小数）", OPTS) != base
    changed = [dict(o) for o in OPTS]
    changed[0]["text"] = "1101亿元"
    assert q.content_fingerprint(STEM, changed) != base


def test_fingerprint_empty_stem_returns_empty():
    """无题干时返回空串，绝不凭空造一个 `fp-` 出来（那会让一堆题撞键）。"""
    assert q.content_fingerprint("", OPTS) == ""
    assert q.content_fingerprint("   ", OPTS) == ""
    assert q.content_fingerprint(None, None) == ""


def test_dedupe_key_is_full_length_and_same_source():
    """严格去重键与指纹同源，只是不截断。"""
    fp = q.content_fingerprint(STEM, OPTS)
    dk = q.dedupe_key(STEM, OPTS)
    assert len(dk) == 64
    assert dk.startswith(fp[len(q.FP_PREFIX):])
    assert q.dedupe_key("", OPTS) == ""


# ---------------- 稳定性判定 ----------------

def test_is_unstable_recognises_legacy_import_qid():
    assert q.is_unstable("") is True
    assert q.is_unstable(None) is True
    assert q.is_unstable("   ") is True
    assert q.is_unstable("imp-20261027120000-10000001") is True
    assert q.is_unstable("fp-0123456789abcdef") is False
    assert q.is_unstable("2023国考-地市-判断-045") is False


def test_stable_qid_keeps_official_and_replaces_unstable():
    official = "2023国考-地市-判断-045"
    assert q.stable_qid(official, STEM, OPTS) == official
    fp = q.content_fingerprint(STEM, OPTS)
    assert q.stable_qid("", STEM, OPTS) == fp
    assert q.stable_qid("imp-20261027-10000001", STEM, OPTS) == fp
    # 既没编号也没题干 → 空串，调用方应保留原值而不是覆盖成空
    assert q.stable_qid("imp-20261027-1", "", []) == ""


def test_from_data_and_text_from_data():
    data = {"stem": STEM, "options": OPTS}
    assert q.from_data(data) == q.content_fingerprint(STEM, OPTS)
    assert q.text_from_data(data) == (STEM, OPTS)
    assert q.from_data({}) == ""
    assert q.from_data(None) == ""
    assert q.text_from_data({"options": "坏数据"}) == ("", [])


def test_fingerprint_version_is_recorded():
    """归一化规则一变指纹就变，版本号必须存在且能被迁移写进 `_meta`。"""
    assert q.FINGERPRINT_VERSION and isinstance(q.FINGERPRINT_VERSION, str)
