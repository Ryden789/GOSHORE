# 花生十三高频1000词 → 辨析卡 JSON 构建器（内容全部原文保留，不做任何改写）
# 数据源：上册（成语1-40组）+ 下册（成语41-67组 + 实词14组），均 ✎ 锚点 + 原书例句
import sys, re, json
from pathlib import Path
from difflib import SequenceMatcher
sys.stdout.reconfigure(encoding="utf-8")
import fitz

UP = r"D:\BaiduNetdiskDownload\（上册）【花生十三】-高频成语实词1000词.pdf"
DOWN = r"D:\BaiduNetdiskDownload\（下册）【花生十三】-高频成语实词1000词(0).pdf"
OUT = r"d:\GOSHORE\data\cards\花生高频1000词.json"

PAGE_ART = re.compile(r"第\s*\d+\s*页|1000\s*词|高频成语实词")
GROUP_H = re.compile(r"【第([一二三四五六七八九十百零]+)组】")
CN = re.compile(r"^[\u4e00-\u9fff]+$")
TOC_DOTS = re.compile(r"[.\s\d]+$")

def clean_lines(t):
    return [l.strip() for l in t.split("\n")
            if l.strip() and not PAGE_ART.fullmatch(l.strip())]

def parse_summary(summary, word_meta, sub_lines=None):
    """总览表（书前目录）→ 词 → (组名, 小类)，合并进 word_meta。

    同时收集真实小类标题（含跨行拼接版与原始片段）到 sub_lines。
    """
    if sub_lines is None:
        sub_lines = set()
    lines = clean_lines(summary)
    i, cur_group, cur_sub = 0, "", ""
    while i < len(lines):
        if lines[i].startswith("【第"):
            m = re.search(r"组】\s*([^\n（】]*)", lines[i])
            cur_group = m.group(1).strip() if m else ""
            cur_sub = ""
            i += 1
            # 组名独占一行（详细总览表）：无条件消费；跨行组名
            # （下一行后不跟数量）继续拼接
            if not cur_group and i < len(lines) and not lines[i].startswith("【"):
                cur_group = TOC_DOTS.sub("", lines[i]).strip()
                i += 1
            while (cur_group and i < len(lines) and not lines[i].startswith("【")
                   and i + 1 < len(lines)
                   and not re.fullmatch(r"\d+", lines[i + 1])
                   and "、" not in lines[i]
                   and "、" not in lines[i + 1]):
                cur_group += TOC_DOTS.sub("", lines[i]).strip()
                i += 1
            if i < len(lines) and re.fullmatch(r"\d+", lines[i]):
                i += 1
            continue
        # 小类标题（后跟数量行）；允许小类名跨行拼接（无顿号的短行）
        if "、" not in lines[i] and not lines[i].startswith("✎"):
            acc, k = lines[i], i + 1
            while (k < len(lines) and not re.fullmatch(r"\d+", lines[k])
                   and "、" not in lines[k] and "【" not in lines[k]
                   and len(acc + lines[k]) <= 20):
                acc += lines[k]; k += 1
            if k < len(lines) and re.fullmatch(r"\d+", lines[k]):
                cur_sub = acc
                sub_lines.add(acc)
                for x in lines[i:k]:
                    sub_lines.add(x)
                i = k + 1
                continue
        if "、" in lines[i]:
            start_i, words = i, []
            while i < len(lines) and not lines[i].startswith("【") and not (
                    i + 1 < len(lines) and re.fullmatch(r"\d+", lines[i + 1])):
                words.extend(w for w in re.split(r"[、，]", lines[i]) if w)
                i += 1
            if i == start_i:
                words.extend(w for w in re.split(r"[、，]", lines[i]) if w)
                i += 1
            for w in words:
                w = TOC_DOTS.sub("", w).strip()
                if w:
                    word_meta[w] = (cur_group, cur_sub)
            continue
        # 数量行后独占一行的词条（如“追逐 / 1 / 趋之若鹜”）
        if (i > 0 and re.fullmatch(r"\d+", lines[i - 1]) and cur_group
                and re.fullmatch(r"[\u4e00-\u9fff]{1,8}", lines[i])):
            word_meta[lines[i]] = (cur_group, cur_sub)
            i += 1
            continue
        i += 1
    return word_meta, sub_lines

def looks_like_wordlist(line):
    """词表预览行：含、且切分后各片段是短汉字词（允许引号/括号尾巴）。"""
    if "、" not in line:
        return False
    parts = [p.strip("“”\"（）() ") for p in re.split(r"[、，]", line) if p.strip()]
    return parts and all(re.fullmatch(r"[\u4e00-\u9fff]{1,8}", p) for p in parts)

def parse_entries(text, stop_at_next_group_preview=False, tail_clean=None):
    """✎ 条目 → [(word, body)]，body 原文保留。

    stop_at_next_group_preview：下册（成语/实词）组标题后跟的是下一组词表
    预览（与上词条无关），遇组标题后若剩余行全为词表则整体截断。
    tail_clean=(known_words, sub_lines)：正文 chunk 尾部残留的下一小类
    标题与词表行（无组标题的情况）按词表已知数据剔除。
    """
    cards, order = {}, []
    for chunk in re.split(r"✎", text)[1:]:
        ls = clean_lines(chunk)
        if not ls:
            continue
        if GROUP_H.fullmatch(ls[0]):
            ls.pop(0)
            if ls and re.search(r"（\s*\d+\s*个）", ls[0]):
                ls.pop(0)
        if not ls:
            continue
        word, body_lines = ls[0], []
        j = 1
        while j < len(ls):
            l = ls[j]
            if re.match(r"例题\d+", l):
                break
            if GROUP_H.fullmatch(l):
                # 组标题行 + 组名（N 个）
                j += 1
                if j < len(ls) and re.search(r"（\s*\d+\s*个）", ls[j]):
                    j += 1
                if stop_at_next_group_preview:
                    rest = ls[j:]
                    if rest and all(looks_like_wordlist(x) or not x for x in rest):
                        break
                continue
            body_lines.append(l)
            j += 1
        body = "\n".join(body_lines).strip()
        # 尾部章节标记（如 “67.2” / “真题示例”）不属于词条
        bl = body.split("\n")
        while bl and (re.fullmatch(r"\d+(?:\.\d+)*", bl[-1].strip())
                      or bl[-1].strip() in ("真题示例",)):
            bl.pop()
        # 尾部下一小类词表/标签（原书排版：小类标题在 ✎ 词之前）
        if tail_clean:
            known_words, sub_lines = tail_clean
            seen_wordlist = False
            while True:
                while bl and not bl[-1].strip():
                    bl.pop()
                if not bl:
                    break
                last = bl[-1].strip()
                parts = [p.strip("“”\"（）()？?。；; ")
                         for p in re.split(r"[、，]", last) if p.strip()]
                wordlist = (
                    "、" in last and not last.endswith(("？", "?"))
                    and parts and all(p in known_words for p in parts))
                if wordlist:
                    bl.pop(); seen_wordlist = True; continue
                # 跨行词表续行（无顿号的单词行，其上方已确认词表）
                if (seen_wordlist and parts and len(parts) == 1
                        and parts[0] in known_words
                        and not re.search(r"[。？?!！]", last)):
                    bl.pop(); continue
                # 词表上方紧邻的小类标题（必须是总览中的真实小类名）
                if seen_wordlist and last in sub_lines:
                    bl.pop(); continue
                break
        body = "\n".join(bl).strip()
        if word and word not in cards:
            cards[word] = body
            order.append(word)
    return cards, order

def parse_shici_toc(toc, front_toc_lines=None):
    """实词目录解析。

    toc（详细表 + 书前回顾片段）：
    A) 详细表：【第X组】组名（可跨行）/小类（可跨行，本身可能含、）/数量/词表
    B) 书前回顾：仅含第一组（其余在全书书前总目录 front_toc_lines）
    标准组名以书前总目录为准。
    返回 meta(词→(组名,小类)), known_words, sub_lines(小类原始行集合)
    """
    raw_lines = [l.strip() for l in toc.split("\n")]
    # 截断：书前回顾起点（带 （N个） 的【组行）
    stop = len(raw_lines)
    for i, l in enumerate(raw_lines):
        if l.startswith("【第") and "个）" in l:
            stop = i
            break
    lines = raw_lines[:stop]

    # 标准组名：全书书前总目录 + 本 toc 回顾片段
    gnames = {}
    for src_lines in (front_toc_lines or [], raw_lines[stop:]):
        for l in src_lines:
            m = re.match(r"【第([一二三四五六七八九十]+)组】(.*?)（\s*\d+\s*个）", l.strip())
            if m:
                gnames[m.group(1)] = m.group(2).strip()

    # 组标题位置（详细表）
    group_starts = [i for i, l in enumerate(lines) if GROUP_H.fullmatch(l)]

    # 数量行
    qs = [i for i, l in enumerate(lines) if re.fullmatch(r"\d+", l)]

    def name_match(acc, gname):
        """组名拼接受纳：精确，或同长度高度相似（如“两者区分/两组区分”）。"""
        if acc == gname:
            return True
        if len(acc) >= len(gname) and gname and \
                SequenceMatcher(None, acc, gname).ratio() >= 0.75:
            return True
        return False

    def sub_start(q, name_end):
        """数量行 q 对应小类的起始行索引（向上回溯，止于组名行）。"""
        k = q - 1
        started = False
        while k > name_end - 1:
            t = lines[k]
            if not t or t == "\u200b":
                k -= 1; continue
            if started and "、" in t:
                break
            started = True
            k -= 1
        return k + 1

    meta, known_words, sub_lines = {}, set(), set()
    for qi, q in enumerate(qs):
        # 所属组
        gs = max(x for x in group_starts if x < q)
        num = GROUP_H.fullmatch(lines[gs]).group(1)
        gname = gnames.get(num, "")
        # 组名行边界：从组标题后拼行直到 == 标准组名
        name_end = gs + 1
        acc = ""
        while name_end < q:
            acc += lines[name_end]
            name_end += 1
            if name_match(acc, gname):
                break
        # 小类回溯（允许含、的首行；跨行片段无句读）
        s0 = sub_start(q, name_end)
        parts = [t for t in lines[s0:q] if t and t != "\u200b"]
        for t in parts:
            sub_lines.add(t)
        sub = "".join(parts).strip()
        # 词表：止于下一个数量行的小类起始
        if qi + 1 < len(qs):
            nxt_gs = max(x for x in group_starts if x < qs[qi + 1])
            nxt_num = GROUP_H.fullmatch(lines[nxt_gs]).group(1)
            nxt_gname = gnames.get(nxt_num, "")
            nxt_name_end = nxt_gs + 1
            acc = ""
            while nxt_name_end < qs[qi + 1]:
                acc += lines[nxt_name_end]
                nxt_name_end += 1
                if name_match(acc, nxt_gname):
                    break
            end = sub_start(qs[qi + 1], nxt_name_end)
        else:
            end = len(lines)
        words = []
        for j in range(q + 1, end):
            t = lines[j]
            if not t or t == "\u200b" or GROUP_H.fullmatch(t):
                continue
            words.extend(w.strip() for w in re.split(r"[、，]", t) if w.strip())
        for w in words:
            known_words.add(w)
            meta[w] = (gname, sub)
    return meta, known_words, sub_lines

# ================= 上册 =================
doc = fitz.open(UP)
up_full = "\n".join(p.get_text() for p in doc)
doc.close()
cut = up_full.find("1.1")
word_meta, cy_subs = parse_summary(up_full[:cut], {})
cy1_cards, cy1_order = parse_entries(
    up_full[cut:], tail_clean=(set(word_meta), cy_subs))
print("上册：总览映射", len(word_meta), "| ✎成语", len(cy1_cards))

# ================= 下册 =================
doc = fitz.open(DOWN)
down_full = "\n".join(p.get_text() for p in doc)
doc.close()
cut2 = down_full.find("1.1")
word_meta, cy_subs = parse_summary(
    down_full[:cut2], word_meta, cy_subs)   # 合并下册总览
body2 = down_full[cut2:]

# 成语区：到实词目录起点（正文第一个【第一组】）
cy2_toc_start = body2.find("【第一组】")
# 实词正文起点：含“1.1 实词解释”的章节头
sc_head = body2.find("1.1", cy2_toc_start)
cy2_part = body2[:cy2_toc_start]
sc_part = body2[sc_head:]

cy2_cards, cy2_order = parse_entries(
    cy2_part, stop_at_next_group_preview=True,
    tail_clean=(set(word_meta), cy_subs))
print("下册：总览映射合计", len(word_meta), "| ✎成语", len(cy2_cards))

# 实词目录 → 组/小类；实词正文 ✎（尾部词表按目录数据清理）
sc_toc = body2[cy2_toc_start:sc_head]
sc_meta, sc_words, sc_subs = parse_shici_toc(
    sc_toc, front_toc_lines=down_full[:cut2].split("\n"))
sc_cards, sc_order = parse_entries(
    sc_part, stop_at_next_group_preview=True,
    tail_clean=(sc_words, sc_subs))
print("实词：目录映射", len(sc_meta), "| ✎条目", len(sc_cards))

# ================= 组装卡片 JSON =================
cards = []
n = 0
def add_cy(word, source, meta_src):
    global n
    n += 1
    g, sub = meta_src.get(word, ("", ""))
    cards.append({
        "id": f"HS-C{n:03d}", "type": "word_card", "module": "言语理解与表达",
        "subtype": "花生高频·成语辨析", "category": g or "成语辨析",
        "stem": word, "analysis": source[word], "answer": word,
        "options": [], "source": "花生十三高频成语实词1000词",
        "tags": [f"小类：{sub}"] if sub else [],
    })

for word in cy1_order:
    add_cy(word, cy1_cards, word_meta)
seen_cy = set(cy1_order)
m_cy = n
for word in cy2_order:
    if word in seen_cy:
        continue
    seen_cy.add(word)
    add_cy(word, cy2_cards, word_meta)

m0 = n
seen_sc = set()
for word in sc_order:
    if word in seen_sc:
        continue
    seen_sc.add(word); n += 1
    g, sub = sc_meta.get(word, ("", ""))
    cards.append({
        "id": f"HS-S{n-m0:03d}", "type": "word_card", "module": "言语理解与表达",
        "subtype": "花生高频·实词辨析", "category": g or "实词辨析",
        "stem": word, "analysis": sc_cards[word], "answer": word,
        "options": [], "source": "花生十三高频成语实词1000词",
        "tags": [f"小类：{sub}"] if sub else [],
    })

obj = {
    "meta": {"name": "花生十三高频成语实词1000词", "version": 2,
             "note": "内容原样保留自花生十三上下册原书，仅做格式转换；成语含释义辨析与例句，实词含侧重点、搭配对象与例句"},
    "cards": cards,
}
Path(OUT).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n输出：{len(cards)} 卡（上册成语 {m_cy}，下册新增成语 {m0-m_cy}，实词 {n-m0}）")
print("成语合计:", m0, "| 实词:", n-m0)
