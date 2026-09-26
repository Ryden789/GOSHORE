# -*- coding: utf-8 -*-
"""AI 生成模拟题补充题库（第二轮）：常识判断 100 + 数量关系 100，准确性第一。

用法：python scripts/gen_mock2.py
流程：每题一次 DeepSeek 调用（temperature=0.5）→ 本地校验（最多重试 3 次）
      → importer.commit_items 入库（与 gen_mock.py 同一入库路径：写 md 到 vault
      99-自导入/{模块}/ 并 upsert 进 goshor.db）。
"""
from __future__ import annotations

import ast
import asyncio
import difflib
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai, db, importer

# ---------------- 出题计划 ----------------

# 常识判断 100 题：科技常识40 / 前沿科技15 / 生活10 / 法律15 / 时政政治10 / 人文历史10
CS_PLAN = [
    ("物理常识（经典力学、光学、电学、热学定律与现象，教材级确定结论）", 15),
    ("化学常识（常见物质性质、化学反应、元素周期表、生活中的化学，教材级确定结论）", 10),
    ("生物常识（细胞、遗传、人体生理、生态，教材级确定结论）", 15),
    ("前沿科技（航天工程、人工智能、新能源的基本原理与公认事实，禁止考最新/首次/之最）", 15),
    ("生活常识（安全、健康、急救、家用电器等无争议知识）", 10),
    ("法律常识（宪法、民法典、刑法、行政法的现行条文与基本原则）", 15),
    ("政治理论（马克思主义基本原理、宪法规定的国家制度等稳定考点）", 10),
    ("人文历史（中国古代史、传统文化、文学常识等公认史实）", 10),
]

# 数量关系 100 题：9 类题型
NUM_PLAN = [
    ("工程问题（合作/轮流/效率变化）", 12),
    ("行程问题（相遇追及/流水行船/环形跑道）", 12),
    ("利润问题（成本售价折扣/分段计费）", 11),
    ("排列组合（分类分步/捆绑插空/分配）", 11),
    ("概率问题（古典概型/独立事件/条件概率）", 11),
    ("几何问题（平面几何面积/立体几何体积/勾股定理）", 11),
    ("容斥原理（两集合/三集合）", 11),
    ("年龄与日期问题（年龄差不变/星期推算）", 10),
    ("方程应用（和差倍比/鸡兔同笼/不定方程）", 11),
]

# 解析中禁止出现的"改题过程"痕迹（出现即说明题干数据与答案不一致）
RESIDUE_RE = re.compile(
    r"需调整|改为|重新构造|最终采用|应改为|调整题干|调整数据|修正|重新设计|重新审题|"
    r"有误|无整数解|不是整数|不在选项|选项无|存在歧义|不唯一|两个正确|也正确|需修改|需重新|数据需"
)

PROMPT_CS = """你是事业单位C类行测命题专家。请出 1 道高质量单选模拟题，模块【常识判断】，方向：{topic}。

硬性要求：
1. 先确定正确答案，再围绕它构造题干与三个干扰项；答案必须唯一、无争议。
2. 只考确定无疑的事实：经典定律、公认史实、现行法律条文、教材级科技常识。
   禁止出现"最新/首次/之最/截至某年"等易过时或有争议的表述。
3. 干扰项要"像真的"：与正确答案相近但有明确错误点（张冠李戴/偷换概念/程度错误）。
4. analysis 必须写明判断依据（如"依据《民法典》第X条""依据牛顿第一定律"），并逐项说明三个干扰项错在哪。
5. 不要与以下已出题目重复：{avoid}

只输出一个 JSON 对象，不要 markdown 代码块、不要任何额外文字。格式：
{{"stem": "题干", "options": [{{"label": "A", "text": "..."}}, {{"label": "B", "text": "..."}}, {{"label": "C", "text": "..."}}, {{"label": "D", "text": "..."}}], "answer": "B", "analysis": "解析", "module": "常识判断", "kaodian": "细分考点", "year": "2026", "exam": "AI模拟·常识判断"}}

随机种子：{seed}（仅用于错开主题，不要输出）。"""

PROMPT_NUM = """你是行测数量关系命题专家。请出 1 道单选模拟题，模块【数量关系】，题型：{topic}。

硬性流程（必须逐步遵守）：
1. 先在内部选定正确答案数值 N（整数或简洁小数），再倒推构造题干数据，使题干条件恰好唯一推出 N。
2. 构造完成后必须正向重算验证：analysis 中写出完整算式与每一步结果，确认结果等于 N 且唯一。
3. 若题目含"至少/至多/最少/最多"等临界表述，必须在 analysis 中单独验证临界值取等时仍成立。
4. 四个选项数值要有明显区分度（相邻选项差不小于 2 或不小于正确值的 10%）；正确项不得贴区间边界。
5. 数字简洁、可手算；难度：{difficulty}。
6. 不要与以下已出题目重复：{avoid}
7. 【最关键】analysis 只写针对最终定稿题干的正式解析：直接列式、算出答案、一句话验证。题干中的数据必须与解析所用数据完全一致。严禁在 analysis 中保留任何草稿/改题过程（如"改为""需调整""重新构造""此数据不行"等），一经发现即为废题。

只输出一个 JSON 对象，不要 markdown 代码块、不要任何额外文字。格式：
{{"stem": "题干", "options": [{{"label": "A", "text": "..."}}, {{"label": "B", "text": "..."}}, {{"label": "C", "text": "..."}}, {{"label": "D", "text": "..."}}], "answer": "B", "analysis": "解析（含完整算式）", "module": "数量关系", "kaodian": "细分考点", "year": "2026", "exam": "AI模拟·数量关系"}}

随机种子：{seed}（仅用于错开主题，不要输出）。"""

DIFF_NUM = ["基础（30-60秒可解）"] * 4 + ["中等"] * 4 + ["较难"] * 2


# ---------------- 解析与校验 ----------------

def extract_one(text: str) -> dict | None:
    """从模型回复中提取单个题目 JSON 对象（兼容 markdown 代码块、单元素数组）。"""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    # 优先按"单个对象"解析：首个 { 到末个 }（数组场景下也正好取到元素对象）
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        try:
            obj = json.loads(text[i : j + 1])
            if isinstance(obj, dict) and obj.get("stem"):
                return obj
        except json.JSONDecodeError:
            pass
    # 兜底：数组形式
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            arr = json.loads(m.group(0))
            if isinstance(arr, list):
                for x in arr:
                    if isinstance(x, dict) and x.get("stem"):
                        return x
        except json.JSONDecodeError:
            pass
    return None


def validate(item: dict, module: str) -> str:
    """返回空串表示通过，否则返回错误原因。"""
    stem = str(item.get("stem") or "").strip()
    if not (10 <= len(stem) <= 500):
        return f"题干长度异常({len(stem)})"
    opts = item.get("options") or []
    if not isinstance(opts, list) or len(opts) != 4:
        return f"选项数={len(opts) if isinstance(opts, list) else '?'}，须为4"
    labels = [str(o.get("label", "")).upper() for o in opts if isinstance(o, dict)]
    if sorted(labels) != ["A", "B", "C", "D"]:
        return f"选项标签异常：{labels}"
    texts = [str(o.get("text") or "").strip() for o in opts]
    if any(not t for t in texts):
        return "存在空选项"
    if len(set(texts)) != 4:
        return "选项文本重复"
    ans = str(item.get("answer") or "").strip().upper()
    if ans not in ("A", "B", "C", "D"):
        return f"答案非法：{ans!r}"
    ana = str(item.get("analysis") or "").strip()
    if not (40 <= len(ana) <= 2000):
        return f"解析长度异常({len(ana)})"
    if str(item.get("module") or "").strip() != module:
        return f"模块字段错误：{item.get('module')!r}"
    if not str(item.get("kaodian") or "").strip():
        return "考点为空"
    if module == "数量关系":
        if not re.search(r"\d", ana) or ("=" not in ana and "＝" not in ana):
            return "数量题解析缺少算式"
    else:
        has_basis = re.search(r"依据|根据|因为|可知|规定|定律|原理|属于|符合", ana)
        per_option = len(re.findall(r"[ABCD]项", ana)) >= 2
        if not (has_basis or per_option):
            return "常识题解析缺少判断依据"
    if RESIDUE_RE.search(ana):
        return f"解析含改题/草稿痕迹：{RESIDUE_RE.search(ana).group(0)}"
    # 解析结论字母须与答案一致
    m = re.search(r"选\s*([ABCD])", ana)
    if m and m.group(1) != str(item.get("answer") or "").strip().upper():
        return f"解析结论选{m.group(1)}与答案{ans}不一致"
    return ""


def _norm(s: str) -> str:
    return re.sub(r"[\s，。、；：？！“”‘’（）()【】《》0-9]", "", s)


def is_dup(stem: str, opt_texts: list[str], existing: list[tuple[str, str]]) -> bool:
    """与库内同模块题目及本次已生成题目查重。

    常识题题干常为"下列关于…说法正确的是"的套话，仅按题干会误杀，
    故题干高度相似时还要选项文本也有明显重叠才算重复。
    """
    a = _norm(stem)[:100]
    ao = _norm("".join(opt_texts))[:200]
    if not a:
        return True
    for b, bo in existing:
        if not b:
            continue
        if a == b:
            return True
        if len(a) < 12 or len(b) < 12:
            continue
        sm = difflib.SequenceMatcher(None, a, b)
        if sm.real_quick_ratio() < 0.7:
            continue
        rs = sm.ratio()
        if rs > 0.92:
            return True
        if rs > 0.75 and bo:
            ro = difflib.SequenceMatcher(None, ao, bo).ratio()
            if ro > 0.55:
                return True
    return False


# ---------------- 数量题算式抽查 ----------------

_EXPR_RE = re.compile(r"([\d\.\+\-\*×xX÷\/\(\)\s]{3,}?)\s*[=＝]\s*(-?\d+(?:\.\d+)?(?:\s*\/\s*\d+)?)")

_ALLOWED = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Num, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Load,
)


def safe_eval(expr: str) -> float | None:
    expr = expr.replace("×", "*").replace("÷", "/").replace("x", "*").replace("X", "*")
    if not re.fullmatch(r"[\d\.\+\-\*/\(\)\s]+", expr):
        return None
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            return None
    try:
        return float(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, {}))
    except Exception:
        return None


def spot_check_num(item: dict) -> list[str]:
    """从 analysis 抽取 算式=结果 做机器复算，返回不一致列表（抽查性质）。"""
    problems = []
    ana = str(item.get("analysis") or "")
    for m in _EXPR_RE.finditer(ana):
        lhs = m.group(1).strip()
        rhs_val = safe_eval(m.group(2))
        if rhs_val is None:
            continue
        # 左端过短（如只有一个数）跳过
        if not re.search(r"[\+\-\*×xX÷\/]", lhs):
            continue
        val = safe_eval(lhs)
        if val is None:
            continue
        if abs(val - rhs_val) > max(0.01, abs(rhs_val) * 1e-6):
            problems.append(f"{lhs} = {val} ≠ {m.group(2)}")
    return problems


# ---------------- 生成与入库 ----------------

async def gen_one(module: str, topic: str, difficulty: str, avoid: list[tuple[str, str]], last_err: str = "") -> tuple[dict | None, str]:
    avoid_str = "、".join(re.sub(r"\s+", "", s)[:20] for s, _ in avoid[-15:]) if avoid else "（无）"
    if module == "常识判断":
        prompt = PROMPT_CS.format(topic=topic, avoid=avoid_str, seed=random.randint(1000, 9999))
    else:
        prompt = PROMPT_NUM.format(topic=topic, difficulty=difficulty, avoid=avoid_str, seed=random.randint(1000, 9999))
    if last_err:
        prompt += f"\n\n【注意】你上一次的输出存在问题：{last_err}。本次请务必修正。"
    try:
        content = await ai.chat_once([{"role": "user", "content": prompt}], temperature=0.5)
    except RuntimeError as e:
        return None, f"API失败：{e}"
    item = extract_one(content)
    if not item:
        return None, "JSON解析失败"
    # 模块/年份/试卷字段以本地为准，模型漏填或错填时直接纠正
    item["module"] = module
    item.setdefault("year", "2026")
    if not item.get("exam"):
        item["exam"] = f"AI模拟·{module}"
    err = validate(item, module)
    if err:
        return None, err
    item, err = importer.normalize_item(item, 1)
    if not item:
        return None, err
    return item, ""


def load_existing_stems(module: str) -> list[tuple[str, str]]:
    conn = db.connect()
    rows = conn.execute("SELECT data FROM documents WHERE module=?", (module,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            d = json.loads(r["data"]) or {}
            s = d.get("stem", "")
            opts = "".join(str(o.get("text", "")) for o in (d.get("options") or []) if isinstance(o, dict))
        except Exception:
            s, opts = "", ""
        if s:
            out.append((s, opts))
    return out


async def main():
    topup = "topup" in sys.argv  # 补漏模式：只跑数量关系，每类 3 题
    cs_plan = [] if topup else CS_PLAN
    num_plan = [(t, 1) for t, _ in NUM_PLAN] if topup else NUM_PLAN
    plan = [("常识判断", t, c) for t, c in cs_plan] + [("数量关系", t, c) for t, c in num_plan]
    total_target = sum(c for _, _, c in plan)
    print(f"目标 {total_target} 题（常识 {sum(c for _,c in cs_plan)} + 数量 {sum(c for _,c in num_plan)}）{'[补漏模式]' if topup else ''}")

    existing = {"常识判断": load_existing_stems("常识判断"), "数量关系": load_existing_stems("数量关系")}
    print(f"库内已有题干：常识 {len(existing['常识判断'])}，数量 {len(existing['数量关系'])}")

    saved_n = skip_n = 0
    qi = 0  # 数量题序号（用于难度配比）
    for module, topic, count in plan:
        for k in range(count):
            difficulty = DIFF_NUM[qi % 10] if module == "数量关系" else "中等"
            item, reason = None, ""
            for attempt in range(1, 4):
                cand, reason = await gen_one(module, topic, difficulty, existing[module], reason)
                if cand is None:
                    print(f"  [重试{attempt}] {module}|{topic[:12]}：{reason}")
                    continue
                opt_texts = [str(o.get("text", "")) for o in cand.get("options", [])]
                if is_dup(cand["stem"], opt_texts, existing[module]):
                    reason = "题干与已有题目重复"
                    print(f"  [重试{attempt}] {module}|{topic[:12]}：{reason}")
                    cand = None
                    continue
                if module == "数量关系":
                    problems = spot_check_num(cand)
                    if problems:
                        reason = f"算式复算不一致：{problems[0]}"
                        print(f"  [重试{attempt}] {module}|{topic[:12]}：{reason}")
                        cand = None
                        continue
                    qi += 1
                item = cand
                break
            if item is None:
                skip_n += 1
                print(f"[跳过] {module}|{topic[:12]} 第{k+1}题（3次均失败，最后原因：{reason}）")
                await asyncio.sleep(random.uniform(1, 2))
                continue
            res = importer.commit_items([item], {"year": "2026"})
            if res.get("saved") == 1:
                saved_n += 1
                opt_texts = [str(o.get("text", "")) for o in item.get("options", [])]
                existing[module].append((item["stem"], opt_texts))
                done = saved_n + skip_n
                print(f"[{done}/{total_target}] 入库✓ {module}|{topic[:12]} | {item['stem'][:24]}…")
                if done % 10 == 0:
                    print(f"  === 累计：入库 {saved_n}，跳过 {skip_n} ===")
            else:
                skip_n += 1
                print(f"[入库失败] {module}|{topic[:12]}：{res.get('failed')}")
            await asyncio.sleep(random.uniform(1, 2))

    print(f"\n完成：入库 {saved_n}，跳过 {skip_n}")
    conn = db.connect()
    for m in ("常识判断", "数量关系"):
        c = conn.execute("SELECT COUNT(*) c FROM documents WHERE module=?", (m,)).fetchone()["c"]
        print(f"  {m} 现有 {c} 题")
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
