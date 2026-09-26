# -*- coding: utf-8 -*-
"""AI 生成「科技文献阅读」客观题 20 道（事业单位C类《综合应用能力》第一大题题型）。

用法：python scripts/gen_wenxian.py
结构：6 篇内置科技文献（火星古气候/地震预警/CRISPR/珊瑚白化/量子通信/钙钛矿电池），
      每 3-4 题共享一篇文献，同组小题共用 material_fp（ai-wenxian-01…06）。
题型：细节理解 / 主旨概括 / 合理推断 / 论证评价（全部四选一单选）。
流程：每题一次 DeepSeek 调用（先定答案字母，再倒推干扰项）→ 本地硬校验（选项结构/
      逐项解析/草稿痕迹/结论一致，失败重试 3 次）→ 写 md（含"给定材料"节）到 vault
      99-自导入/科技文献/ → parse + db._upsert 入 goshor.db → 补写 material_fp。
      documents.module='综合分析', kaodian='科技文献阅读', exam='AI模拟·科技文献阅读'。
      qid 固定（aim-wenxian-01…20），重跑自动跳过已入库题。
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai, db, importer, parser
from app.config import load_settings

# ---------------- 文献与出题计划 ----------------

GROUPS = [
    {
        "fp": "ai-wenxian-01",
        "title": "火星古气候",
        "material": (
            "火星表面平均温度约为零下63摄氏度，大气压不足地球的百分之一，液态水无法在其表面"
            "长期稳定存在。然而，多颗环绕火星的轨道探测器在古老的南部高原上发现了密集的河谷"
            "网和湖盆地貌，其年代约为35亿至37亿年前。2021年登陆耶泽罗撞击坑的“毅力号”火星车，"
            "在坑底三角洲沉积中发现了交错层理的砂岩和细粒黏土矿物。某研究团队据此提出：耶泽罗"
            "撞击坑在远古时期曾是一个持续存在数万年以上的湖泊，河流从上游带入泥沙并形成三角洲。"
            "该团队同时指出，火星在诺亚纪晚期可能拥有比今天浓密得多的二氧化碳大气。另一些研究者"
            "则提醒，交错层理砂岩也可能在风沙环境中由沙丘移动形成，仅凭沉积构造尚不能断定一定"
            "存在持久湖泊，还需要找到只在水下环境形成的矿物组合作为旁证。"
        ),
        "questions": [
            ("A", "detail", "考查火星当前的环境条件：表面平均温度约零下63℃、大气稀薄、液态水无法长期稳定存在。"),
            ("B", "main", "考查研究团队的核心观点：依据三角洲沉积推断耶泽罗撞击坑曾长期存在湖泊。"),
            ("C", "infer", "考查合理推断：若河谷网确由流水塑造，可推断火星远古大气比现在浓密。"),
            ("D", "arg", "考查论证评价：另一些研究者指出交错层理也可由风沙沙丘形成，这削弱了“持久湖泊”结论。"),
        ],
    },
    {
        "fp": "ai-wenxian-02",
        "title": "地震预警",
        "material": (
            "地震发生时，震源处同时产生纵波（P波）和横波（S波）。P波传播速度较快（每秒约6"
            "千米）但携带能量小、破坏弱；S波传播速度较慢（每秒约3.5千米）却振幅大，是造成建筑"
            "破坏的主要原因。地震预警系统利用P波与S波到达同一台站的时间差，以及电子信号传播"
            "远快于地震波的特点，在S波到达目标城市前数秒至数十秒发出警报。某研究团队利用200个"
            "台站的记录，对一次7.2级地震进行了预警回算：距震中50千米以内的城市，P波与S波几乎"
            "同时到达，系统来不及发出有效警报；距震中100千米的城市平均可获得约15秒预警时间。"
            "团队据此认为，进一步加密台站后，该系统可在未来地震中“完全避免人员伤亡”。也有专家"
            "指出，预警信息发出后，居民停止电梯、关闭燃气并疏散到安全地带至少需要20秒，15秒"
            "并不足以完成全部避险动作。"
        ),
        "questions": [
            ("B", "detail", "考查P波与S波的性质差异：P波快而破坏弱，S波慢但破坏大。"),
            ("C", "infer", "考查对预警盲区的理解：距震中50千米内P、S波几乎同时到达，无法有效预警。"),
            ("D", "arg", "考查论证评价：专家指出完成避险动作至少需20秒，削弱了“15秒预警即可避免伤亡”的说法。"),
        ],
    },
    {
        "fp": "ai-wenxian-03",
        "title": "CRISPR基因编辑",
        "material": (
            "CRISPR-Cas9原本是细菌用来抵御噬菌体入侵的获得性免疫系统：细菌将入侵病毒的DNA片段"
            "储存到自身基因组中，当同一病毒再次入侵时，转录出的向导RNA引导Cas9蛋白识别并切割"
            "病毒DNA。科学家将这一机制改造为基因编辑工具，可对特定基因位点进行敲除或替换。某"
            "医学团队利用该技术治疗患有某种遗传性血液病的实验小鼠：单次治疗后，40只受试小鼠中"
            "36只的相关血液指标恢复正常，且未观察到明显急性毒性。团队负责人在新闻发布会上表示，"
            "既然小鼠实验有效率达到九成，该疗法“三年内即可用于治愈人类患者”。列席的伦理学家"
            "则提出三点疑问：其一，小鼠与人类在基因背景和免疫反应上差异显著；其二，该团队尚未"
            "检测向导RNA是否在非目标位点造成脱靶切割；其三，此前已有研究者因违规将胚胎基因编辑"
            "用于人类生殖而受到法律惩处。"
        ),
        "questions": [
            ("A", "detail", "考查CRISPR的天然来源与机制：它本是细菌抵御噬菌体的免疫系统，由向导RNA引导Cas9切割靶DNA。"),
            ("C", "main", "考查团队研究本身的结论：在受试小鼠中约九成血液指标恢复正常、无明显急性毒性。"),
            ("D", "arg", "考查论证评价：伦理学家指出小鼠与人差异大且未检测脱靶，削弱了“三年内治愈人类患者”的推断。"),
            ("B", "infer", "考查合理推断：若不检测脱靶切割，疗法可能在正常基因上造成意外损伤。"),
        ],
    },
    {
        "fp": "ai-wenxian-04",
        "title": "珊瑚白化",
        "material": (
            "造礁珊瑚与体内的虫黄藻形成共生关系：虫黄藻通过光合作用为珊瑚提供糖类等营养，珊瑚"
            "则为虫黄藻提供庇护场所和代谢原料，珊瑚鲜艳的颜色也主要来自虫黄藻。当海水温度比"
            "当地夏季最高水温持续高出1至2摄氏度达数周时，珊瑚会排出大部分虫黄藻，骨骼因失去"
            "色素覆盖而显现白色，这一现象称为珊瑚白化。白化的珊瑚并未立即死亡，若温度及时回落，"
            "虫黄藻可重新定殖。某海洋研究团队对同一海域的两片礁区进行了调查：甲礁区长期禁渔、"
            "水质较好，白化珊瑚约占四成；乙礁区允许捕鱼且曾受游客踩踏，白化珊瑚约占六成。团队"
            "由此得出结论：实施禁渔管理可以防止珊瑚白化。评审专家则指出，两片礁区的水深和水流"
            "交换条件并不相同，且白化的根本诱因是持续高温，禁渔最多提高珊瑚在白化后的恢复力，"
            "并不能阻止高温引发的白化发生。"
        ),
        "questions": [
            ("C", "detail", "考查白化机制：海水持续升温1至2℃达数周，珊瑚排出虫黄藻而显白。"),
            ("A", "infer", "考查合理推断：白化不等于死亡，温度及时回落后虫黄藻可重新定殖。"),
            ("D", "arg", "考查论证评价：专家指出两礁区水深水流不同且根本诱因是高温，削弱“禁渔可防止白化”的结论。"),
        ],
    },
    {
        "fp": "ai-wenxian-05",
        "title": "量子通信",
        "material": (
            "量子密钥分发是量子信息科学最先走向实用的方向之一，其安全性建立在量子力学基本原理"
            "之上：未知量子态不可被精确克隆，而对量子态的测量通常会改变其状态。因此，窃听者在"
            "密钥传输途中进行截获测量时，通信双方可以通过抽样比对发现误码异常，从而舍弃可能"
            "泄露的密钥。2017年，“墨子号”科学实验卫星与地面站实现了星地双向量子纠缠分发；同年，"
            "长距离光纤量子保密通信骨干线路“京沪干线”开通。某科普文章在介绍上述成果时写道：量子"
            "通信利用量子纠缠实现了信息的超光速传输，而且其保密性在任何情况下都不可能被攻破。"
            "该领域的研究者对此提出更正：纠缠本身不能用来超光速传递信息，因为测量结果完全随机、"
            "无法人为编码；实际系统的安全性还依赖光源与探测器等器件的可靠性，针对器件缺陷发起"
            "的侧信道攻击已有公开报道。"
        ),
        "questions": [
            ("B", "detail", "考查安全性原理：未知量子态不可克隆，窃听测量会留下可被抽样发现的异常。"),
            ("D", "main", "考查文段主旨：量子密钥分发已走向实用，但其能力与安全性边界常被公众表述夸大。"),
            ("C", "arg", "考查论证评价：研究者指出纠缠不能超光速传信、侧信道攻击真实存在，直接反驳科普文章的两处断言。"),
        ],
    },
    {
        "fp": "ai-wenxian-06",
        "title": "钙钛矿太阳能电池",
        "material": (
            "钙钛矿太阳能电池所用材料是一类具有ABX3型晶体结构的金属卤化物，与传统晶硅电池不同，"
            "它可以通过旋涂、刮涂等溶液工艺成膜，所需温度低、设备投资少，并可制备在柔性衬底上。"
            "2009年首次报道时，其光电转换效率仅约3.8%；此后十余年间，实验室小面积器件的认证"
            "效率已超过26%，逼近晶硅电池的水平。某新能源公司在发布会上展示了一块面积为0.1平方"
            "厘米、效率达26%的器件，并宣布将在一年内建成产线、全面替代地面电站使用的晶硅组件。"
            "参与评审的工程师指出三点问题：小面积器件的高效率在放大为平方米级组件时通常明显"
            "下降；钙钛矿薄膜在湿热和紫外线照射下会逐渐分解，而地面电站组件通常要求25年以上寿命；"
            "此外，含铅钙钛矿在组件破损后可能造成铅泄漏，需要封装回收方案。"
        ),
        "questions": [
            ("A", "detail", "考查钙钛矿电池的工艺特点：可溶液法低温成膜、设备投资少、可做柔性器件。"),
            ("B", "infer", "考查合理推断：效率从3.8%升至26%说明材料体系优化空间大，但不等于已满足电站寿命要求。"),
            ("A", "arg", "考查论证评价：工程师指出面积放大效率下降、25年寿命与铅泄漏问题，削弱“一年内全面替代晶硅”的结论。"),
        ],
    },
]

# 题型考查指令
KIND_DIRS = {
    "detail": ("细节理解", "考查对材料中具体事实、数据、机制表述的准确理解，正确项必须与材料表述严格一致。"),
    "main": ("主旨概括", "考查对文段或研究核心观点的整体把握，正确项须概括准确全面。"),
    "infer": ("合理推断", "考查依据材料信息作出合理推断，正确项应是材料信息的必然或高概率延伸。"),
    "arg": ("论证评价", "考查识别论证缺陷与支持、削弱关系，须围绕材料中的论点、论据和论证方式设问。"),
}

PROMPT = """你是事业单位C类《综合应用能力》「科技文献阅读」命题专家。请基于下面给定的科技文献，命制 1 道单项选择题。

【科技文献】（命题的唯一信息来源）
{material}

【本题考查方向】{kind_name}：{kind_desc}
【命题着力点】{hint}

硬性要求：
1. 先确定正确答案的内容，必须严格依据材料、由材料信息唯一确定，不能依赖材料之外的专业常识；再倒推设计三个干扰项。
2. 正确答案必须放在 {letter} 选项。
3. 干扰项须有明确错误点，从下列类型中选取：偷换概念、以偏概全（把部分说成全部、约数变全称）、混淆时态（把推测说成已证实）、绝对化（把可能变必然）、无中生有、因果倒置或强加因果、超出材料支持范围过度推断；干扰项不能与正确答案等价。
4. stem 只写设问句本身（一句话，如“根据上文，下列说法正确的是”“最能质疑上述观点的是”），不要复述材料，不带“根据以下材料”之类前缀。
5. analysis 为正式解析：①开头写明结论“故选{letter}”；②指出正确项依据材料何处（可引用材料关键表述）；③用“A项”“B项”“C项”“D项”的表述逐一指出干扰项各错在哪，并点明错误类型（如“偷换概念”“绝对化”“以偏概全”“过度推断”）。解析中禁止出现“改为、应改为、调整为、需调整”等修改类表述，一经发现即废题。
6. 设问与选项须避开以下已有题目：{avoid}

只输出一个 JSON 对象，不要 markdown 代码块、不要任何额外文字。格式：
{{"stem": "设问句", "options": [{{"label": "A", "text": "..."}}, {{"label": "B", "text": "..."}}, {{"label": "C", "text": "..."}}, {{"label": "D", "text": "..."}}], "answer": "{letter}", "analysis": "解析", "kaodian": "科技文献阅读"}}

随机种子：{seed}（仅用于错开表述，不要输出）。"""

# ---------------- 硬校验 ----------------

RESIDUE_RE = re.compile(
    r"需调整|调整为|改为|重新构造|重新设计|重新审题|调整题干|需修改|需重新|"
    r"存在歧义|不唯一|两个正确|也正确|草稿|待定|待完善"
)


def extract_one(text: str) -> dict | None:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        try:
            obj = json.loads(text[i:j + 1])
            if isinstance(obj, dict) and obj.get("stem"):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def validate_raw(item: dict, letter: str) -> str:
    she = re.sub(r"\s+", "", str(item.get("stem") or ""))
    if not (6 <= len(she) <= 120):
        return f"设问长度异常({len(she)})"
    if "材料" in she[:6]:
        return "设问不应以材料复述开头"
    opts = item.get("options") or []
    if not isinstance(opts, list) or len(opts) != 4:
        return f"选项数={len(opts) if isinstance(opts, list) else '?'}，须为4"
    labels = [str(o.get("label", "")).upper() for o in opts if isinstance(o, dict)]
    if labels != ["A", "B", "C", "D"]:
        return f"选项标签异常：{labels}"
    texts = []
    for o in opts:
        if not isinstance(o, dict):
            return "选项格式异常"
        t = re.sub(r"^[A-D][\.、．:：]\s*", "", str(o.get("text") or "").strip())
        if not t:
            return "存在空选项"
        if len(t) > 160:
            return "选项过长"
        texts.append(t)
    if len(set(texts)) != 4:
        return "选项文本重复"
    ans = str(item.get("answer") or "").strip().upper()
    if ans != letter:
        return f"答案{ans or '（空）'}不在指定位置{letter}"
    ana = str(item.get("analysis") or "").strip()
    if not (40 <= len(ana) <= 2000):
        return f"解析长度异常({len(ana)})"
    letters = set(re.findall(r"([ABCD])[项选]", ana))
    if len(letters) < 3:
        return "解析未逐项分析（至少出现3个选项字母）"
    if RESIDUE_RE.search(ana):
        return f"解析含改题/草稿痕迹：{RESIDUE_RE.search(ana).group(0)}"
    m = re.search(r"故选\s*([ABCD])|答案[为是]\s*([ABCD])", ana)
    if m and (m.group(1) or m.group(2)) != ans:
        return f"解析结论与答案{ans}不一致"
    return ""


def _norm(s: str) -> str:
    return re.sub(r"[\s，。、；：？！“”‘’（）()【】《》0-9]", "", s)


def is_dup(she: str, opt_texts: list[str], seen_keys: list[str]) -> bool:
    key = _norm(she + "".join(opt_texts))
    if not key:
        return True
    return any(key == k for k in seen_keys)


# ---------------- 入库 ----------------

def db_retry(fn, desc: str):
    last = None
    for i in range(5):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and i < 4:
                last = e
                time.sleep(2)
                continue
            raise
    raise RuntimeError(f"{desc}重试5次仍失败：{last}")


def build_markdown(item: dict, qid: str, title: str, material: str) -> str:
    opts = []
    for o in item["options"]:
        mark = " ✅" if o["label"] == item["answer"] else ""
        opts.append(f"- {o['label']}. {o['text']}{mark}")
    return f"""---
类型: 真题
qid: {qid}
地区: 
年份: "2026"
试卷: AI模拟·科技文献阅读
考点: 科技文献阅读
tags: [自导入]
---

# {title}

## 题干
{item['stem']}

## 给定材料
{material}

## 选项
{chr(10).join(opts)}

## 官方解析
答案：{item['answer']}

{item['analysis']}
"""


def commit_question(item: dict, material: str, qid: str, title: str, fp: str) -> None:
    s = load_settings()
    vault = Path(s["vault_path"])
    rel = f"99-自导入/综合分析/{qid}.md"
    md_path = vault / rel
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(build_markdown(item, qid, title, material), encoding="utf-8")
    p = parser.parse(rel, md_path.read_text(encoding="utf-8"))

    def _do():
        conn = db.connect()
        try:
            db._upsert(conn, p, md_path.stat().st_mtime)
            conn.execute("UPDATE documents SET material_fp=? WHERE path=?", (fp, rel))
            conn.commit()
        finally:
            conn.close()

    db_retry(_do, f"入库{qid}")


def qid_exists(qid: str) -> bool:
    def _do():
        conn = db.connect()
        try:
            return conn.execute("SELECT 1 FROM documents WHERE qid=?", (qid,)).fetchone() is not None
        finally:
            conn.close()

    return db_retry(_do, f"查询{qid}")


# ---------------- 生成 ----------------

async def gen_one(group: dict, letter: str, kind: str, hint: str,
                  avoid: list[str], last_err: str = ""):
    kind_name, kind_desc = KIND_DIRS[kind]
    avoid_str = "、".join(a[:20] for a in avoid[-12:]) if avoid else "（无）"
    prompt = PROMPT.format(
        material=group["material"], kind_name=kind_name, kind_desc=kind_desc,
        hint=hint, letter=letter, avoid=avoid_str, seed=random.randint(1000, 9999))
    if last_err:
        prompt += f"\n\n【注意】你上一次的输出存在问题：{last_err}。本次请务必修正。"
    try:
        content = await ai.chat_once([{"role": "user", "content": prompt}], temperature=0.5)
    except RuntimeError as e:
        return None, f"API失败：{e}"
    raw = extract_one(content)
    if not raw:
        return None, "JSON解析失败"
    err = validate_raw(raw, letter)
    if err:
        return None, err

    she = str(raw.get("stem") or "").strip()
    opts = []
    for i, o in enumerate(raw["options"]):
        t = re.sub(r"^[A-D][\.、．:：]\s*", "", str(o.get("text") or "").strip())
        opts.append({"label": "ABCD"[i], "text": t})

    final = {
        "stem": f"{group['prefix']}\n{she}",
        "options": opts,
        "answer": letter,
        "analysis": str(raw.get("analysis") or "").strip(),
        "module": "综合分析",
        "kaodian": "科技文献阅读",
        "region": "",
        "year": "2026",
        "exam": "AI模拟·科技文献阅读",
    }
    if not (10 <= len(final["stem"]) <= 800):
        return None, f"最终题干长度异常({len(final['stem'])})"
    item, err = importer.normalize_item(final, 1)
    if not item:
        return None, err
    return item, ""


async def main():
    qno = 0
    plan = []
    for g in GROUPS:
        start = qno + 1
        qno += len(g["questions"])
        g = dict(g)
        g["prefix"] = f"根据以下材料，回答第{start}-{qno}题。"
        for j, (letter, kind, hint) in enumerate(g["questions"]):
            plan.append((g, start + j, letter, kind, hint))
    total = len(plan)
    print(f"目标 {total} 题（科技文献阅读：细节/主旨/推断/论证评价）", flush=True)

    db_retry(lambda: db.init_db(db.connect()), "初始化数据库")

    seen_keys: list[str] = []
    saved = skip_exist = skip_fail = 0
    for g, n, letter, kind, hint in plan:
        qid = f"aim-wenxian-{n:02d}"
        if qid_exists(qid):
            skip_exist += 1
            print(f"[{n}/{total}] {qid} 已存在，跳过", flush=True)
            continue
        she_ask_prev = [k[0] for k in seen_keys]
        item, reason = None, ""
        for attempt in range(1, 4):
            cand, reason = await gen_one(g, letter, kind, hint, she_ask_prev, reason)
            if cand is None:
                print(f"  [重试{attempt}] 第{n}题（{kind}）：{reason}", flush=True)
                continue
            she = cand["stem"].split("\n")[-1]
            if is_dup(she, [o["text"] for o in cand["options"]],
                      [k for _, k in seen_keys]):
                reason = "与本次已生成题重复"
                print(f"  [重试{attempt}] 第{n}题：{reason}", flush=True)
                continue
            item = cand
            break
        if item is None:
            skip_fail += 1
            print(f"[跳过] 第{n}题（3次均失败，最后原因：{reason}）", flush=True)
            continue
        she = item["stem"].split("\n")[-1]
        title = f"科技文献·{n:02d}·{she[:14]}"
        try:
            commit_question(item, g["material"], qid, title, g["fp"])
        except Exception as e:
            skip_fail += 1
            print(f"[跳过] {qid} 入库失败：{e}", flush=True)
            continue
        saved += 1
        she = item["stem"].split("\n")[-1]
        seen_keys.append((she[:20], _norm(she + "".join(o["text"] for o in item["options"]))))
        print(f"[{saved + skip_fail}/{total}] {qid} 已入库（{kind}，答案{letter}）", flush=True)

    print(f"\n完成：入库 {saved}，已存在 {skip_exist}，失败 {skip_fail}", flush=True)
    conn = db.connect()
    try:
        n = conn.execute(
            "SELECT COUNT(*) c FROM documents WHERE kaodian='科技文献阅读'"
        ).fetchone()[0]
    finally:
        conn.close()
    print("科技文献阅读题总数:", n, flush=True)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
