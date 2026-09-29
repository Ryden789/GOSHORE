# 花生十三高频1000词 → 辨析卡 JSON 构建器（内容全部原文保留，不做任何改写）
import sys, re, json
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
import fitz

UP = r"D:\BaiduNetdiskDownload\（上册）【花生十三】-高频成语实词1000词.pdf"
MEM = r"D:\BaiduNetdiskDownload\花生十三高频1000词记忆版(黑白).pdf"
OUT = r"d:\GOSHORE\data\cards\花生高频1000词.json"

PAGE_ART = re.compile(r"第\s*\d+\s*页|1000\s*词|高频成语实词")
GROUP_H_START = re.compile(r"【第([一二三四五六七八九十百零]+)组】")
GROUP_TAIL = re.compile(r"^(.*?)（\s*(\d+)\s*个）?$")
CN = re.compile(r"^[\u4e00-\u9fff]+$")
CN2 = re.compile(r"^[\u4e00-\u9fff]{2}$")
SENT_PUNCT = "。，；：！？、"

def clean_lines(t):
    out = []
    for l in t.split("\n"):
        l = l.strip()
        if l and not PAGE_ART.fullmatch(l):
            out.append(l)
    return out

# ================= 上册：总览映射 + ✎ 成语条目 =================
doc = fitz.open(UP)
up_full = "\n".join(p.get_text() for p in doc)
doc.close()
cut = up_full.find("1.1")
summary, entries_part = up_full[:cut], up_full[cut:]

# --- 总览表：词 → (组名, 小类) ---
word_meta, lines = {}, clean_lines(summary)
i, cur_group, cur_sub = 0, "", ""
while i < len(lines):
    if lines[i].startswith("【第"):
        m = re.search(r"组】\s*([^\n（】]*)", lines[i])
        cur_group = m.group(1).strip() if m else ""
        cur_sub = ""
        i += 1
        if i < len(lines) and re.fullmatch(r"\d+", lines[i]):
            i += 1
        continue
    if i + 1 < len(lines) and re.fullmatch(r"\d+", lines[i + 1]) and not re.search(r"[、，]", lines[i]):
        cur_sub = lines[i]; i += 2; continue
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
            word_meta[w.strip()] = (cur_group, cur_sub)
        continue
    i += 1

# --- ✎ 条目 ---
cy_cards = {}   # word -> body verbatim
cy_order = []
for chunk in re.split(r"✎", entries_part)[1:]:
    ls = clean_lines(chunk)
    if not ls:
        continue
    # chunk 开头可能是跨页章节分隔行
    if re.fullmatch(r"【第[一二三四五六七八九十百零]+组】", ls[0]):
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
        # 跨页时嵌入的章节分隔行（【第X组】+ 组名（N 个））不属于词条内容
        if re.fullmatch(r"【第[一二三四五六七八九十百零]+组】", l):
            j += 1
            if j < len(ls) and re.search(r"（\s*\d+\s*个）", ls[j]):
                j += 1
            continue
        body_lines.append(l)
        j += 1
    body = "\n".join(body_lines).strip()
    if word and word not in cy_cards:
        cy_cards[word] = body
        cy_order.append(word)

print("上册：总览映射", len(word_meta), "| ✎成语", len(cy_cards))

# ================= 记忆版：通用分组解析 =================
doc = fitz.open(MEM)
mem_full = "\n".join(p.get_text() for p in doc)
doc.close()

# 实词连续区起点（第四十四组）；实词重启区起点（第二个【第一组】）
p44 = mem_full.find("【第四十四组】")
g1s = [m.start() for m in re.finditer(r"【第一组】", mem_full)]
restart = g1s[-1] if g1s else len(mem_full)
print("边界: 连续实词 p44 =", p44, "| 重启实词 =", restart)

def split_groups(text):
    """切成 [(组名, [行...])]，兼容组名跨行与数量括号跨行。"""
    pos = [(m.start(), m.group(1)) for m in GROUP_H_START.finditer(text)]
    groups = []
    for k, (s, num) in enumerate(pos):
        e = pos[k + 1][0] if k + 1 < len(pos) else len(text)
        body = clean_lines(text[s:e])
        # body[0]=【第X组】；之后收组名直到 “个）” 闭合
        j, nameparts = 1, []
        while j < len(body) and not "".join(nameparts).rstrip("（").endswith("个）"):
            nameparts.append(body[j]); j += 1
            joined = "".join(nameparts)
            if "个）" in joined:
                break
        gname = re.sub(r"（.*$", "", "".join(nameparts)).strip()
        groups.append((gname, body[j:]))
    return groups

def explanation_like(span_lines):
    joined = "".join(span_lines)
    return any(c in joined for c in SENT_PUNCT) or len(joined) >= 12

def parse_word_groups(text, anchor):
    """通用词条解析。anchor: 候选词锚点正则；用'后续块像解释'确认锚点、剔除小类行。

    实词区词长混杂（2字为主，比喻象征组为3字如 风向标/压舱石）：
    组内2字候选≥2时仅用2字锚点（防3字小类行误判）；否则补充3字锚点。
    """
    out = []   # (word, group, subcategory, explanation)
    for gname, body in split_groups(text):
        prev_sub_new = []
        use3 = sum(1 for l in body if CN2.fullmatch(l)) < 2
        cands = [k for k, l in enumerate(body)
                 if (anchor.fullmatch(l) or (use3 and re.fullmatch(r"[\u4e00-\u9fff]{3}", l)))]
        cands = sorted(set(cands))
        confirmed = []
        for ii, ck in enumerate(cands):
            nxt = cands[ii + 1] if ii + 1 < len(cands) else len(body)
            if explanation_like(body[ck + 1:nxt]):
                confirmed.append(ck)
        for ci, ck in enumerate(confirmed):
            nxt = confirmed[ci + 1] if ci + 1 < len(confirmed) else len(body)
            block = body[ck + 1:nxt]
            conf_words = {body[k] for k in confirmed}
            # 尾部短标签行 = 下一词小类（长度≤10、无句末标点）；词表预览行（同本组确认词）剔除
            sub_new, p = [], len(block) - 1
            while p >= 0:
                t = block[p]
                if (len(t) <= 10 and not any(c in t for c in "。；：！？")
                        and CN.fullmatch(t.rstrip("、")) and t not in conf_words):
                    sub_new.insert(0, t); p -= 1
                else:
                    break
            expl = "\n".join(block[:p + 1]).strip()
            # 本词小类 = 上一词块尾切出的短标签；首个词取词前非解释性短行（如"雕刻（具象与抽象分化）"）
            if ci == 0:
                sub = "".join(l for l in body[:ck]
                              if not explanation_like([l]) and l not in conf_words).strip()
            else:
                sub = "".join(prev_sub_new).strip()
            prev_sub_new = sub_new
            out.append((body[ck], gname, sub, expl))
    return out

# 成语区（→ restart 之前全部是成语，含连续编号到第六十七组）：锚点 3-8 字
cy_extra = parse_word_groups(mem_full[:restart], re.compile(r"^[\u4e00-\u9fff]{3,8}$"))
# 实词区（重启编号区）：锚点 2 字
sc = parse_word_groups(mem_full[restart:], CN2)
print("记忆版：候选成语条目", len(cy_extra), "| 实词条目", len(sc))

# ================= 组装卡片 JSON =================
cards = []
n = 0
for word in cy_order:
    n += 1
    g, sub = word_meta.get(word, ("", ""))
    tags = [f"小类：{sub}"] if sub else []
    cards.append({
        "id": f"HS-C{n:03d}", "type": "word_card", "module": "言语理解与表达",
        "subtype": "花生高频·成语辨析", "category": g or "成语辨析",
        "stem": word, "analysis": cy_cards[word], "answer": word,
        "options": [], "source": "花生十三高频成语实词1000词", "tags": tags,
    })
# 记忆版独有成语（上册没覆盖）
existing = set(cy_cards)
added_cy = []
for word, g, sub, expl in cy_extra:
    if word in existing or not expl:
        continue
    existing.add(word); added_cy.append((word, g, sub, expl))
for word, g, sub, expl in added_cy:
    n += 1
    cards.append({
        "id": f"HS-C{n:03d}", "type": "word_card", "module": "言语理解与表达",
        "subtype": "花生高频·成语辨析", "category": g or "成语辨析",
        "stem": word, "analysis": expl, "answer": word,
        "options": [], "source": "花生十三（记忆版补录）",
        "tags": [f"小类：{sub}"] if sub else [],
    })

# 实词（按出现顺序，跨区去重）
m0 = n
seen_sc = set()
for word, g, sub, expl in sc:
    if word in seen_sc or not expl:
        continue
    seen_sc.add(word); n += 1
    cards.append({
        "id": f"HS-S{n-m0:03d}", "type": "word_card", "module": "言语理解与表达",
        "subtype": "花生高频·实词辨析", "category": g or "实词辨析",
        "stem": word, "analysis": expl, "answer": word,
        "options": [], "source": "花生十三高频成语实词1000词",
        "tags": [f"小类：{sub}"] if sub else [],
    })

obj = {
    "meta": {"name": "花生十三高频成语实词1000词", "version": 1,
             "note": "内容原样保留自花生十三原书，仅做格式转换；成语含释义辨析与例句，实词含侧重点与搭配对象"},
    "cards": cards,
}
Path(OUT).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n输出：{len(cards)} 卡（成语 {m0}，其中记忆版补录 {len(added_cy)}；实词 {n-m0}）")
print("补录成语:", [w for w, *_ in added_cy])
