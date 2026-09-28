#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「词语填空」离线预置题包（免 API Key 降级方案）。

题源：data/goshor.db 中 module='言语理解' 的逻辑填空真题。
  - 一族题干带「填入画横线部分最恰当的一项是」指令句，挖空处为下划线/括号/空格；
  - 另一族题干无指令句但含下划线挖空，且自带人工解析。
清洗：剔除含 HTML 图片/公式/链接/控制字符的题；要求 4 个选项、唯一正确项、
      各选项词数与空格数一致、同一空位各选项词字数一致（成语对成语）。
组题：正确项为原题答案词，干扰项取同题其余选项（天然易混）。
      多空题可整题保留（direct），也可拆成单空题（split：其余空回填原题正确词）。
输出：static/m/wordfill_seed.json，字段与 app/wordfill.py 的 AI 命题格式一致，
      逐题通过 app.wordfill._structural_check 校验。

用法：python scripts/gen_wordfill_seed.py [--count 200] [--db data/goshor.db]
                                           [--out static/m/wordfill_seed.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.wordfill import BLANK_TOKEN, _split_words, _structural_check  # noqa: E402

# ---------------- 题源清洗规则 ----------------

INSTR = re.compile(r"\s*(依次)?填入[^。！？\n]{0,40}?(一项|两项|三项|词语)[^。！？\n]{0,15}?[：:]?\s*$")
BLANKPAT = re.compile(r"_{2,}|（\s*）|\(\s*\)|[ 　]+")
USCORE = re.compile(r"_{2,}")
HTML_RE = re.compile(r"<[a-zA-Z/]|\[img\]|data:image|https?://|[\x00-\x08\x0b\x0c\x0e-\x1f]")
AI_MARK = "（AI 双盲一致判定，人工复核请走「疑点」页）"

MIN_LEN, PREF_LEN, HARD_LEN = 20, 120, 150  # 题干长度（不含空格占位）
MAX_PER_WORD = 2      # 同一目标词最多出现次数
MAX_PER_SRC = 2       # 同一来源真题最多产出题数


# ---------------- 词义卡片（用于解析模板） ----------------

def load_glosses(cards_dir: Path) -> dict:
    """从 data/cards 的词语辨析卡提取 词 -> 简明释义。"""
    gloss = {}
    for name in ("词语辨析·扩充100词.json", "词语辨析·高频成语实词60.json"):
        fp = cards_dir / name
        if not fp.exists():
            continue
        for card in json.loads(fp.read_text(encoding="utf-8")).get("cards", []):
            ana = card.get("analysis", "")
            m = re.search(r"【释义】\**\s*(.+?)(?:\n|$)", ana)
            if not m:
                continue
            for w, g in re.findall(r"([一-鿿]{2,8})：([^。\n；;]{2,60})", m.group(1)):
                gloss.setdefault(w, g.strip())
    fp = cards_dir / "题库_词语辨析150.json"
    if fp.exists():
        for q in json.loads(fp.read_text(encoding="utf-8")).get("questions", []):
            w, a = q.get("answer", "").strip(), q.get("analysis", "").strip()
            m = re.search(r"（(.{2,40})）", a)
            if w and m and len(w) <= 8:
                gloss.setdefault(w, m.group(1).strip())
    return gloss


# ---------------- 候选抽取 ----------------

def iter_candidates(db_path: Path):
    """产出候选字典。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, data FROM documents WHERE module='言语理解'"
    ).fetchall()
    conn.close()
    for r in rows:
        try:
            d = json.loads(r["data"])
        except (TypeError, json.JSONDecodeError):
            continue
        opts = d.get("options", [])
        if len(opts) != 4:
            continue
        if sum(1 for o in opts if o.get("correct")) != 1:
            continue
        texts = [str(o.get("text", "")).strip() for o in opts]
        if not all(1 <= len(t) <= 20 for t in texts):
            continue
        words4 = [t.split() for t in texts]
        n = len(words4[0])
        if not (1 <= n <= 3) or not all(len(w) == n for w in words4):
            continue
        stem = str(d.get("stem", ""))
        has_instr = bool(INSTR.search(stem))
        if has_instr:
            body = INSTR.sub("", stem).strip()
        elif USCORE.search(stem):
            body = stem.strip()  # 无指令句一族：仅信下划线挖空
        else:
            continue
        marks = list(BLANKPAT.finditer(body))
        if len(marks) != n:
            continue
        cols = list(zip(*words4))
        # 同一空位各选项词字数必须一致（成语对成语、实词对实词）
        if not all(len({len(w) for w in col}) == 1 for col in cols):
            continue
        blob = stem + " " + " ".join(texts) + " " + str(d.get("official", ""))
        if HTML_RE.search(blob):
            continue
        correct_idx = next(i for i, o in enumerate(opts) if o.get("correct"))
        official = re.sub(r"^答案：?[A-D]\s*", "", str(d.get("official", "")))
        official = official.replace(AI_MARK, "").strip()
        yield {
            "src": r["id"], "body": body, "n": n, "marks": marks,
            "words4": words4, "cols": cols, "ci": correct_idx,
            "official": official,
        }


def render_passage(body: str, marks: list, fills: list) -> str:
    """按各空替换内容（BLANK_TOKEN 或回填词）重建文段。"""
    out, last = [], 0
    for m, fill in zip(marks, fills):
        out.append(body[last:m.start()])
        out.append(fill)
        last = m.end()
    out.append(body[last:])
    return "".join(out).strip()


def passage_len(passage: str) -> int:
    return len(passage.replace(BLANK_TOKEN, ""))


# ---------------- 解析生成 ----------------

def build_analysis(gloss: dict, words: list, distractors: list,
                   official: str, src_id: int, split_note: str = "") -> str:
    src = f"（来源：真题 #{src_id}）"
    if len(official) >= 40:
        return f"{official}{src}"
    parts = []
    if split_note:
        parts.append(split_note)
    cw = "、".join(f"「{w}」" for w in words)
    parts.append(f"应填{cw}。")
    gs = [f"「{w}」{gloss[w]}" for w in words if w in gloss]
    if gs:
        parts.append("词义：" + "；".join(gs) + "。")
    if distractors:
        dg = [f"「{w}」（{gloss[w]}）" for w in distractors if w in gloss]
        if dg:
            parts.append("干扰项辨析：" + "；".join(dg) + "，均不如正解贴切。")
        parts.append("其余选项"
                     + "、".join(f"「{w}」" for w in distractors)
                     + "与横线处语境不符。")
    parts.append(src)
    return "".join(parts)


# ---------------- 题目装配 ----------------

def category_of(correct_words: list) -> str:
    lens = {len(w) for w in correct_words}
    if lens == {4}:
        return "成语"
    if max(lens) <= 3:
        return "实词"
    return "混搭"


def difficulty_of(n: int, correct_words: list) -> str:
    if n >= 3:
        return "hard"
    if n == 2:
        return "mid"
    return "mid" if max(len(w) for w in correct_words) >= 4 else "easy"


def remap_letters(text: str, old2new: dict) -> str:
    """把解析中引用的原选项字母（A项 / A、C两项 / A。B项 等）映射为洗牌后的字母。

    单字母 A-D 只在其后紧跟中文/引号/数字/标点（即作为选项引用）时替换，
    后随英文字母（如 AIDS）则不替换。
    """
    if not text or len(old2new) < 4:
        return text
    def _sub(m):
        return old2new.get(m.group(0), m.group(0))
    return re.sub(r"[A-D](?![A-Za-z])", _sub, text)


def make_item(item_id: int, src_id: int, passage: str, opt_words: list,
              correct_pos: int, gloss: dict, official: str,
              split_note: str = "") -> dict:
    """opt_words: 4 个选项（每个是词列表）；correct_pos: 正确选项下标。"""
    rng = random.Random(src_id * 131 + item_id)
    order = list(range(4))
    rng.shuffle(order)
    labels = ["A", "B", "C", "D"]
    options = [{"label": labels[k], "text": " / ".join(opt_words[i])}
               for k, i in enumerate(order)]
    answer = labels[order.index(correct_pos)]
    correct_words = opt_words[correct_pos]
    distractors = [opt_words[i][p] for p in range(len(correct_words))
                   for i in range(4) if i != correct_pos]
    old2new = {labels[i]: labels[k] for k, i in enumerate(order)}
    official = remap_letters(official, old2new)
    analysis = build_analysis(gloss, correct_words, distractors,
                              official, src_id, split_note)
    return {
        "id": item_id,
        "passage": passage,
        "blanks": len(correct_words),
        "options": options,
        "answer": answer,
        "analysis": analysis,
        "words": correct_words,
        "category": category_of(correct_words),
        "difficulty": difficulty_of(len(correct_words), correct_words),
        "verified": True,
    }


# ---------------- 校验 ----------------

def validate(items: list, expect: int) -> list:
    errs = []
    if len(items) != expect:
        errs.append(f"题量 {len(items)} != {expect}")
    seen_hash, word_cnt = set(), {}
    for it in items:
        tag = f"#{it['id']}"
        probe = {k: it[k] for k in ("passage", "options", "answer",
                                    "analysis", "words", "blanks")}
        reason = _structural_check(probe)  # 与线上 AI 命题同一套结构校验
        if reason:
            errs.append(f"{tag} 结构校验: {reason}")
        if not (MIN_LEN <= passage_len(it["passage"]) <= HARD_LEN):
            errs.append(f"{tag} 题干长度越界: {passage_len(it['passage'])}")
        right = next(o for o in it["options"] if o["label"] == it["answer"])
        right_words = _split_words(right["text"])
        if right_words != it["words"]:
            errs.append(f"{tag} words 与答案选项不一致")
        for o in it["options"]:
            if not o["text"].strip():
                errs.append(f"{tag} 空选项")
            ow = _split_words(o["text"])
            if [len(w) for w in ow] != [len(w) for w in right_words]:
                errs.append(f"{tag} 选项词字数不一致: {o}")
        if not it["analysis"].strip() or not it["passage"].strip():
            errs.append(f"{tag} 空字段")
        # 解析中的选项字母引用须与洗牌后的选项内容一致（如 B项“言之凿凿”）
        for m in re.finditer(r"([A-D])项[“\"']([^”\"']{1,12})[”\"']", it["analysis"]):
            ref = next(o for o in it["options"] if o["label"] == m.group(1))
            if m.group(2) not in ref["text"]:
                errs.append(f"{tag} 解析字母引用错位: {m.group(0)} != {ref['text']}")
        h = hashlib.md5(it["passage"].encode()).hexdigest()
        if h in seen_hash:
            errs.append(f"{tag} 题干哈希重复")
        seen_hash.add(h)
        for w in it["words"]:
            word_cnt[w] = word_cnt.get(w, 0) + 1
    for w, c in word_cnt.items():
        if c > MAX_PER_WORD:
            errs.append(f"目标词「{w}」出现 {c} 次 > {MAX_PER_WORD}")
    return errs


# ---------------- 主流程 ----------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--db", default="data/goshor.db")
    ap.add_argument("--out", default="static/m/wordfill_seed.json")
    ap.add_argument("--cards", default="data/cards")
    args = ap.parse_args()

    gloss = load_glosses(Path(args.cards))
    print(f"[seed] 词义卡片: {len(gloss)} 条")

    cands = []
    for c in iter_candidates(Path(args.db)):
        passage_all = render_passage(c["body"], c["marks"], [BLANK_TOKEN] * c["n"])
        c["plen"] = passage_len(passage_all)
        if MIN_LEN <= c["plen"] <= HARD_LEN:
            cands.append(c)
    print(f"[seed] 清洗后候选真题: {len(cands)} 道")

    items, used_src = [], {}
    word_use = {}
    hashes = set()

    def word_ok(ws):
        return all(word_use.get(w, 0) < MAX_PER_WORD for w in ws)

    def accept(item, src_id):
        h = hashlib.md5(item["passage"].encode()).hexdigest()
        if h in hashes:
            return False
        hashes.add(h)
        items.append(item)
        used_src[src_id] = used_src.get(src_id, 0) + 1
        for w in item["words"]:
            word_use[w] = word_use.get(w, 0) + 1
        return True

    def try_direct(c, item_id):
        if not word_ok(c["words4"][c["ci"]]):
            return False
        passage = render_passage(c["body"], c["marks"], [BLANK_TOKEN] * c["n"])
        return accept(make_item(item_id, c["src"], passage, c["words4"],
                                c["ci"], gloss, c["official"]), c["src"])

    def try_split(c, pos, item_id):
        ws = [c["cols"][pos][c["ci"]]]
        if not word_ok(ws):
            return False
        fills = [c["cols"][p][c["ci"]] for p in range(c["n"])]
        fills[pos] = BLANK_TOKEN
        passage = render_passage(c["body"], c["marks"], fills)
        opts = [[c["cols"][pos][i]] for i in range(4)]
        note = (f"本题由{c['n']}空真题拆编，仅保留第{pos + 1}空，"
                f"其余空已回填原题正确词。")
        return accept(make_item(item_id, c["src"], passage, opts,
                                c["ci"], gloss, c["official"], note), c["src"])

    nid = 0
    # 第 1 轮：整题保留，题干 ≤120 优先
    for c in sorted(cands, key=lambda x: (x["plen"], x["src"])):
        if len(items) >= args.count:
            break
        if c["plen"] <= PREF_LEN and try_direct(c, nid + 1):
            nid += 1
    # 第 2 轮：整题保留，120 < 题干 ≤150
    for c in sorted(cands, key=lambda x: (x["plen"], x["src"])):
        if len(items) >= args.count:
            break
        if PREF_LEN < c["plen"] <= HARD_LEN and c["src"] not in used_src:
            if try_direct(c, nid + 1):
                nid += 1
    # 第 3 轮：多空真题拆单空（每源最多 2 题）
    for c in sorted(cands, key=lambda x: (x["plen"], x["src"])):
        if len(items) >= args.count:
            break
        if c["n"] < 2:
            continue
        for pos in range(c["n"]):
            if len(items) >= args.count:
                break
            if used_src.get(c["src"], 0) >= MAX_PER_SRC:
                break
            if try_split(c, pos, nid + 1):
                nid += 1

    print(f"[seed] 生成题目: {len(items)} 道（目标 {args.count}）")

    errs = validate(items, args.count)
    if errs:
        print(f"[seed] 校验失败 {len(errs)} 项：")
        for e in errs[:30]:
            print("  -", e)
        return 1

    stats = {"total": len(items), "category": {}, "difficulty": {}, "blanks": {}}
    for it in items:
        for key, val in (("category", it["category"]),
                         ("difficulty", it["difficulty"]),
                         ("blanks", it["blanks"])):
            stats[key][val] = stats[key].get(val, 0) + 1

    out = {
        "meta": {
            "name": "词语填空预置题库",
            "version": 1,
            "count": len(items),
            "source": "data/goshor.db 言语理解真题改造",
            "stats": stats,
        },
        "items": items,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"[seed] 校验通过，已写入 {out_path}（{len(items)} 题）")
    print(f"[seed] 分布: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
