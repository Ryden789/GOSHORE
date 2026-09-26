# -*- coding: utf-8 -*-
"""AI 生成模拟题（综合分析模块）：策略制定 10 题 + 实验设计 10 题（事业单位C类职测特色题型）。

用法：python scripts/gen_mock_zh.py
结构：6 则固定情境材料（策略制定 3 组 4+3+3、实验设计 3 组 4+3+3），每 3-5 题共享
      一则材料，同组小题共用 material_fp（ai-zhfx-01…06）。
流程：每题一次 DeepSeek 调用（先定答案字母，再倒推构造设问与干扰项）→ 本地硬校验
      （草稿痕迹/结论字母=答案/逐项解析/算式复算，失败重试 3 次）→ 写 md（含"给定材料"节）
      到 vault 99-自导入/综合分析/ → parse + db._upsert 入 data/goshor.db → 补写 material_fp。
      qid 固定（aim-zhfx-01…20），重跑自动跳过已入库题。
      服务器占用 SQLite 时遇 database is locked 等 2 秒重试（最多 5 次）。
"""
from __future__ import annotations

import ast
import asyncio
import difflib
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

# ---------------- 出题计划 ----------------

GROUPS = [
    {
        "fp": "ai-zhfx-01",
        "kaodian": "策略制定",
        "material": (
            "某社区接到暴雨红色预警，居委会张主任需立即处置多起突发情况：①独居老人王奶奶"
            "（85岁，行动不便）来电称家中已进水、无法自行离开；②地下车库开始积水，内有十余辆"
            "私家车；③居民微信群有人散布“上游堤坝决口”的消息，部分居民恐慌，还有人想去河边"
            "围观；④社区活动中心内存放的价值约2万元的公共文体物资正被雨水浸泡。张主任手下有"
            "6名工作人员和1辆巡逻车。《社区防汛应急预案》规定：坚持生命安全高于一切；转移安置"
            "群众后须第一时间上报街道办；对外发布信息须以街道办核实的口径为准。"
        ),
        "questions": [
            {"letter": "A", "hint": "生命安全优先于财产和秩序：王奶奶是被困人员，人身安全最紧迫，"
                                   "应第一时间转移被困老人；挪车、辟谣、抢救物资都不能凌驾于救人之上。"},
            {"letter": "B", "hint": "按预案程序办事：转移安置后须第一时间上报街道办并妥善安置、请求支援；"
                                   "自行联系其外地子女、让她留在险境、通知媒体，都不符合预案要求。"},
            {"letter": "C", "hint": "信息不足时先核实再发布：对外信息必须以街道办核实的口径为准，"
                                   "应先向上级核实上游是否决口，再统一发布权威信息；擅自断言、置之不理、"
                                   "以个人名义担保都不可取。"},
            {"letter": "D", "hint": "统筹兼顾、按优先级分配人力：优先安排人手逐户排查转移独居老人，"
                                   "同时兼顾挪车与物资转移，并保持通讯畅通；全员押一件事或原地等待都"
                                   "会顾此失彼。"},
        ],
    },
    {
        "fp": "ai-zhfx-02",
        "kaodian": "策略制定",
        "material": (
            "某街道拟于三周后举办一场慈善义卖活动，可用预算2万元，街道办明确三项要求：确保活动"
            "安全、收支全程透明、尽量扩大居民参与。现有三个备选方案：甲方案，周六在区中心广场"
            "举办，预计1500人参与，需租借舞台音响等花费8000元，预计义卖收入3万元；按大型群众性"
            "活动安全管理规定，须提前向公安机关申请安全许可，办理约需两周。乙方案，同日在街道"
            "文化馆室内举办，预计300人参与，场地自有，仅需物料费2000元，预计收入8000元，无需"
            "额外审批。丙方案，在临河景观步道举办，预计1200人参与，需花费5000元，预计收入2.5"
            "万元，但该场地尚未取得河道管理部门的使用许可。"
        ),
        "questions": [
            {"letter": "B", "hint": "成本-收益与程序合规权衡：距活动还有三周、许可约两周可办结，"
                                   "甲方案收益最大、参与面最广且依法合规，优于收益较低的乙和未取得"
                                   "许可的丙。"},
            {"letter": "C", "hint": "程序合规是底线：许可无法在活动前办结时，正确选择是无需审批、"
                                   "成本收益仍达标的乙方案；“先办后补许可”违反规定，无限推迟则"
                                   "不必要地放弃合规可行的方案。"},
            {"letter": "D", "hint": "收支透明是街道办明确要求：活动结束后首要工作是核算并公示全部"
                                   "收支明细，接受居民监督；截留私分结余、只作口头汇报、封存账目"
                                   "都违反要求。"},
        ],
    },
    {
        "fp": "ai-zhfx-03",
        "kaodian": "策略制定",
        "material": (
            "某第三方检测实验室本周同时接到三项任务：A任务为某企业委托的批量化食品安全检测，"
            "合同约定本周五前出具报告，逾期须按合同支付违约金2万元；B任务为上级应急管理部门"
            "指派的突发水质污染应急检测，检测结果直接关系下游水厂是否暂停取水，要求48小时内"
            "完成；C任务为常规土壤质量抽检，完成时限为下月底，暂无不良影响。实验室现有2名资深"
            "检测员、3名初级检测员，检测设备可同时开展多类项目。"
        ),
        "questions": [
            {"letter": "A", "hint": "公共安全优先于经济利益：B任务关系下游饮水安全且时限最紧"
                                   "（48小时），应优先集中资源完成；2万元违约金不能凌驾于公共"
                                   "安全之上。"},
            {"letter": "B", "hint": "统筹并行、按轻重缓急排程：2名资深检测员分别牵头应急任务B和"
                                   "合同任务A，3名初级检测员分组辅助，C任务暂缓；全员押一项任务"
                                   "都会误事。"},
            {"letter": "D", "hint": "诚信履约、程序合规：预计延迟应主动与委托企业沟通说明、协商新的"
                                   "交付时间并书面确认；隐瞒拖延、凑数出具未完成的报告、拒接电话"
                                   "都不可取。"},
        ],
    },
    {
        "fp": "ai-zhfx-04",
        "kaodian": "实验设计",
        "material": (
            "某中学科学兴趣小组探究“光照强度对豌豆幼苗生长的影响”。小组将同一批豌豆种子同时"
            "播种，培育出40株长势相近的幼苗，随机均分为甲、乙、丙、丁4组（每组10株），分别置于"
            "强光、中光、弱光、黑暗四种条件下培养；各组除光照强度不同外，温度、水分、土壤和施肥"
            "等条件均相同且适宜。两周后测量各组平均株高：中光组32厘米、弱光组28厘米、强光组25"
            "厘米、黑暗组12厘米。小组有人据此得出结论：“光照越强，豌豆幼苗长得越高。”"
        ),
        "questions": [
            {"letter": "A", "hint": "结论必须与实验数据一致：数据显示中光组平均株高最高，强光组低于"
                                   "中光组和弱光组，“光照越强长得越高”与数据矛盾，不成立。"},
            {"letter": "B", "hint": "对照组识别：黑暗组不接受光照处理，作为空白对照，为其他各组提供"
                                   "比较基准，用于确定光照对生长的影响。"},
            {"letter": "C", "hint": "随机分组与“长势相近”能减少个体差异等无关变量干扰，每组10株的"
                                   "样本量对中学探究实验基本够用，该设计基本合理。"},
            {"letter": "D", "hint": "重复验证：在相同条件下重复多轮实验、以多轮平均值代替单次结果，"
                                   "可减少偶然误差，是最必要的改进；其他做法要么破坏对照，要么引入"
                                   "新变量。"},
        ],
    },
    {
        "fp": "ai-zhfx-05",
        "kaodian": "实验设计",
        "material": (
            "某团队宣称保健品X能显著缓解疲劳，并公布调查数据：1000名自愿购买并服用X的白领，"
            "连续服用三个月后，85%的人自述“精力有所改善”。该团队据此得出结论：“服用X能有效"
            "缓解疲劳。”"
        ),
        "questions": [
            {"letter": "A", "hint": "实验设计缺少对照组：没有不服用的对照，“精力改善”可能来自安慰剂"
                                   "效应、自然恢复或主观期望，无法归因于X，这是最核心的缺陷；样本量"
                                   "1000人并不算小。"},
            {"letter": "C", "hint": "验证因果的金标准是随机双盲安慰剂对照试验：随机分组排除自选择，"
                                   "安慰剂对照排除安慰剂效应，双盲排除主观偏差；扩大人数、更换测量"
                                   "指标都无法弥补无对照的根本缺陷。"},
            {"letter": "D", "hint": "自选择偏倚（混杂变量）：自愿购买并坚持服用的人往往作息更规律、"
                                   "更注重锻炼，“精力改善”可能源于健康生活方式而非X，该质疑削弱了"
                                   "原结论的因果解释。"},
        ],
    },
    {
        "fp": "ai-zhfx-06",
        "kaodian": "实验设计",
        "material": (
            "某工厂研发出两种新型合金A、B，拟替代原用合金O制作承重桥架。检验员从每种合金的待检"
            "批次中随机抽取5根尺寸形状完全相同的试条，在同一台万能试验机上以相同加载速率进行"
            "抗拉强度测试；每轮测试记录数据，共重复3轮，取平均值作为该合金的强度代表值。结果："
            "合金A平均520兆帕，合金B平均480兆帕，合金O平均450兆帕，且每轮数据与平均值的偏差"
            "均小于2%。"
        ),
        "questions": [
            {"letter": "B", "hint": "控制无关变量：试条尺寸形状相同、使用同一台试验机、相同加载速率，"
                                   "保证除“合金种类”外其他条件一致；随机抽样保证代表性。"},
            {"letter": "C", "hint": "依据数据推断：合金A平均强度最高，且A与O相差70兆帕，远超2%的"
                                   "轮间波动（约10兆帕），差异真实存在，从强度角度应选A。"},
            {"letter": "A", "hint": "外推有效性：实际桥架长期处于不同温度、湿度等环境中，需在不同"
                                   "环境条件下重复同样的测试，才能判断结论能否推广到实际工况；"
                                   "提高加载速率会使数据与原条件不可比。"},
        ],
    },
]

# ---------------- 提示词 ----------------

PROMPT_CL = """你是事业单位C类职测「综合分析·策略制定」命题专家。请基于下面给定的情境材料，命制 1 道单选题。

【情境材料】（命题的唯一信息来源）
{material}

【命题方向】正确答案必须体现以下公共管理判断：
{hint}

硬性要求：
1. 先确定正确答案的内容，再倒推设计三个干扰项；答案必须由“材料信息+公共管理常识”唯一确定，不存在第二个同样合理的选项，不得依赖材料之外的信息。
2. 正确答案必须放在 {letter} 选项。
3. 干扰项须有明确错误点，常见类型：违反“生命安全优先于秩序和财产”、信息不足时不先核实就行动、程序不合规或越权、成本明显更高或收益明显更低、治标不治本、超出材料授权范围。干扰项不能与正确答案等价。
4. stem 只写设问句本身（一句话，如“此时最优先采取的措施是”），不要复述材料，不要带“根据以下材料”之类前缀。
5. analysis 为正式解析：①开头写明结论“故选{letter}”；②结合材料关键信息说明正确项为什么对；③用“A项”“B项”“C项”“D项”的表述逐一指出三个干扰项各错在哪。解析中禁止出现“改为、应改为、调整为、需调整”等修改类表述（用“应选、最合理的是”代替），一经发现即废题。
6. 设问与选项都要避开以下已有题目：{avoid}

只输出一个 JSON 对象，不要 markdown 代码块、不要任何额外文字。格式：
{{"stem": "设问句", "options": [{{"label": "A", "text": "..."}}, {{"label": "B", "text": "..."}}, {{"label": "C", "text": "..."}}, {{"label": "D", "text": "..."}}], "answer": "{letter}", "analysis": "解析", "kaodian": "策略制定"}}

随机种子：{seed}（仅用于错开表述，不要输出）。"""

PROMPT_EXP = """你是事业单位C类职测「综合分析·实验设计」命题专家。请基于下面给定的实验情境材料，命制 1 道单选题。

【实验情境】（命题的唯一信息来源）
{material}

【命题方向】正确答案必须体现以下实验设计逻辑：
{hint}

硬性要求：
1. 先确定正确答案的内容，再倒推设计三个干扰项；答案必须由实验设计逻辑（对照原则、单一变量原则、随机分组与重复、相关不等于因果、结论必须与数据一致）结合材料唯一确定，不存在第二个同样合理的选项。
2. 正确答案必须放在 {letter} 选项。
3. 干扰项须有明确错误点，常见类型：破坏对照或引入新变量、把相关当因果、忽视样本量/随机分组/重复的缺陷、结论超出数据支持范围、改变条件后与原数据不可比、无中生有。干扰项不能与正确答案等价。
4. stem 只写设问句本身（一句话，如“最能支持上述结论的是”“该实验的对照组是”“最必要的改进是”），不要复述材料，不要带“根据以下材料”之类前缀。
5. analysis 为正式解析：①开头写明结论“故选{letter}”；②依据实验设计原理说明正确项为什么对；③用“A项”“B项”“C项”“D项”的表述逐一指出三个干扰项各错在哪。解析中禁止出现“改为、应改为、调整为、需调整”等修改类表述（用“应选、最合理的是”代替），一经发现即废题。
6. 设问与选项都要避开以下已有题目：{avoid}

只输出一个 JSON 对象，不要 markdown 代码块、不要任何额外文字。格式：
{{"stem": "设问句", "options": [{{"label": "A", "text": "..."}}, {{"label": "B", "text": "..."}}, {{"label": "C", "text": "..."}}, {{"label": "D", "text": "..."}}], "answer": "{letter}", "analysis": "解析", "kaodian": "实验设计"}}

随机种子：{seed}（仅用于错开表述，不要输出）。"""

# ---------------- 硬校验 ----------------

# 解析中禁止出现的“改题过程”痕迹（针对策略/实验题定制，避开“最终采用”“有误”等合法表述）
RESIDUE_RE = re.compile(
    r"需调整|调整为|改为|重新构造|重新设计|重新审题|调整题干|调整数据|需修改|需重新|数据需|"
    r"无整数解|不是整数|不在选项|存在歧义|不唯一|两个正确|也正确|草稿|此数据不行|待定|待完善"
)


def extract_one(text: str) -> dict | None:
    """从模型回复中提取单个题目 JSON 对象（兼容 markdown 代码块、单元素数组）。"""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        try:
            obj = json.loads(text[i : j + 1])
            if isinstance(obj, dict) and obj.get("stem"):
                return obj
        except json.JSONDecodeError:
            pass
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


def validate_raw(item: dict, letter: str, kaodian: str) -> str:
    """校验 AI 原始输出（设问句），返回空串表示通过。"""
    she = re.sub(r"\s+", "", str(item.get("stem") or ""))
    if not (6 <= len(she) <= 200):
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
        texts.append(t)
    if len(set(texts)) != 4:
        return "选项文本重复"
    ans = str(item.get("answer") or "").strip().upper()
    if ans != letter:
        return f"答案{ans or '（空）'}不在指定位置{letter}"
    ana = str(item.get("analysis") or "").strip()
    if not (40 <= len(ana) <= 2000):
        return f"解析长度异常({len(ana)})"
    if str(item.get("kaodian") or "").strip() not in ("", kaodian):
        return f"考点字段错误：{item.get('kaodian')!r}"
    letters = set(re.findall(r"([ABCD])[项选]", ana))
    if len(letters) < 3:
        return "解析未用“A项/B项/C项/D项”逐项分析（至少出现3个选项字母）"
    if RESIDUE_RE.search(ana):
        return f"解析含改题/草稿痕迹：{RESIDUE_RE.search(ana).group(0)}"
    # 解析结论字母须与答案一致
    m = re.search(r"故选\s*([ABCD])|答案[为是]\s*([ABCD])", ana)
    if m and (m.group(1) or m.group(2)) != ans:
        return f"解析结论选{m.group(1) or m.group(2)}与答案{ans}不一致"
    return ""


def _norm(s: str) -> str:
    return re.sub(r"[\s，。、；：？！“”‘’（）()【】《》0-9]", "", s)


def is_dup(she: str, opt_texts: list[str], seen_keys: list[str]) -> bool:
    """与本次已生成题目查重（设问+选项合并键）。"""
    key = _norm(she + "".join(opt_texts))
    if not key:
        return True
    for k in seen_keys:
        if key == k:
            return True
        if len(key) < 12 or len(k) < 12:
            continue
        sm = difflib.SequenceMatcher(None, key[:120], k[:120])
        if sm.real_quick_ratio() < 0.75:
            continue
        if sm.ratio() > 0.75:
            return True
    return False


# ---------------- 算式抽查（沿用 gen_mock2 思路） ----------------

_EXPR_RE = re.compile(r"([\d\.\+\-\*×xX÷\/\(\)\s]{3,}?)\s*[=＝]\s*(-?\d+(?:\.\d+)?)")

_ALLOWED = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Load,
)


def safe_eval(expr: str):
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
        if rhs_val is None or not re.search(r"[\+\-\*×xX÷\/]", lhs):
            continue
        val = safe_eval(lhs)
        if val is None:
            continue
        if abs(val - rhs_val) > max(0.01, abs(rhs_val) * 1e-6):
            problems.append(f"{lhs} = {val} ≠ {m.group(2)}")
    return problems


# ---------------- 入库 ----------------

def db_retry(fn, desc: str):
    """数据库操作遇 database is locked 等 2 秒重试（最多5次）。"""
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
    raise RuntimeError(f"{desc} 重试5次仍失败：{last}")


def build_markdown(item: dict, qid: str, title: str, material: str) -> str:
    opts = []
    for o in item["options"]:
        mark = " ✅" if o["label"] == item["answer"] else ""
        opts.append(f"- {o['label']}. {o['text']}{mark}")
    return f"""---
类型: 真题
qid: {qid}
地区: 
年份: "{item['year']}"
试卷: {item['exam']}
考点: {item['kaodian']}
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
    """写 md（含给定材料节）到 vault → parse + upsert 入 goshor.db → 补写 material_fp。"""
    s = load_settings()
    vault = Path(s["vault_path"])
    if not vault.exists():
        raise RuntimeError(f"vault 路径不存在：{vault}")
    rel = f"99-自导入/综合分析/{qid}.md"
    text = build_markdown(item, qid, title, material)
    md_path = vault / rel
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(text, encoding="utf-8")
    p = parser.parse(rel, text)

    def _do():
        conn = db.connect()
        try:
            db._upsert(conn, p, md_path.stat().st_mtime)
            conn.execute(
                "UPDATE documents SET material_fp=? WHERE path=?", (fp, rel)
            )
            conn.commit()
        finally:
            conn.close()

    db_retry(_do, f"入库{qid}")


def qid_exists(qid: str) -> bool:
    def _do():
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM documents WHERE qid=?", (qid,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    return db_retry(_do, f"查询{qid}")


# ---------------- 生成 ----------------

async def gen_one(group: dict, letter: str, hint: str, avoid: list[str], last_err: str = ""):
    """生成一题：DeepSeek 调用 + 校验 + 组装最终题干。返回 (item, err)。"""
    tpl = PROMPT_CL if group["kaodian"] == "策略制定" else PROMPT_EXP
    avoid_str = "、".join(a[:20] for a in avoid[-12:]) if avoid else "（无）"
    prompt = tpl.format(
        material=group["material"], hint=hint, letter=letter,
        avoid=avoid_str, seed=random.randint(1000, 9999),
    )
    if last_err:
        prompt += f"\n\n【注意】你上一次的输出存在问题：{last_err}。本次请务必修正。"
    try:
        content = await ai.chat_once([{"role": "user", "content": prompt}], temperature=0.5)
    except RuntimeError as e:
        return None, f"API失败：{e}"
    raw = extract_one(content)
    if not raw:
        return None, "JSON解析失败"
    err = validate_raw(raw, letter, group["kaodian"])
    if err:
        return None, err
    ana = str(raw.get("analysis") or "").strip()
    problems = spot_check_num({"analysis": ana})
    if problems:
        return None, f"算式复算不一致：{problems[0]}"

    she = re.sub(r"\s+", "", str(raw.get("stem") or "").strip())
    opts = []
    for i, o in enumerate(raw["options"]):
        t = re.sub(r"^[A-D][\.、．:：]\s*", "", str(o.get("text") or "").strip())
        opts.append({"label": "ABCD"[i], "text": t})

    final = {
        "stem": f"{group['prefix']}{group['material']}\n{she}",
        "options": opts,
        "answer": letter,
        "analysis": ana,
        "module": "综合分析",
        "kaodian": group["kaodian"],
        "region": "",
        "year": "2026",
        "exam": "AI模拟·C类综合分析",
    }
    if not (10 <= len(final["stem"]) <= 1600):
        return None, f"最终题干长度异常({len(final['stem'])})"
    item, err = importer.normalize_item(final, 1)
    if not item:
        return None, err
    return item, ""


async def main():
    # 展开计划：组内题号连续，prefix 为“根据以下材料，回答第N-M题。”
    qno = 0
    plan = []
    for g in GROUPS:
        start = qno + 1
        qno += len(g["questions"])
        g = dict(g)
        g["prefix"] = f"根据以下材料，回答第{start}-{qno}题。"
        for j, q in enumerate(g["questions"]):
            plan.append((g, start + j, q["letter"], q["hint"]))
    total = len(plan)
    print(f"目标 {total} 题（策略制定 {sum(len(g['questions']) for g in GROUPS[:3])}"
          f" + 实验设计 {sum(len(g['questions']) for g in GROUPS[3:])}）", flush=True)

    def _init():
        conn = db.connect()
        try:
            db.init_db(conn)
        finally:
            conn.close()

    db_retry(_init, "初始化数据库")

    seen_keys: list[str] = []
    saved = skip_exist = skip_fail = 0
    for g, n, letter, hint in plan:
        qid = f"aim-zhfx-{n:02d}"
        if qid_exists(qid):
            skip_exist += 1
            saved += 1
            print(f"[{saved + skip_fail}/{total}] {qid} 已存在，跳过", flush=True)
            continue
        she_ask_prev = [k[0] for k in seen_keys]
        item = None
        reason = ""
        for attempt in range(1, 4):
            cand, reason = await gen_one(g, letter, hint, she_ask_prev, reason)
            if cand is None:
                print(f"  [重试{attempt}] {g['kaodian']}|第{n}题：{reason}", flush=True)
                continue
            opt_texts = [o["text"] for o in cand["options"]]
            if is_dup(re.sub(r"^[\s\S]*?\n", "", cand["stem"]),
                      opt_texts, [k for _, k in seen_keys]):
                reason = "与本次已生成题重复"
                print(f"  [重试{attempt}] {g['kaodian']}|第{n}题：{reason}", flush=True)
                continue
            item = cand
            break
        if item is None:
            skip_fail += 1
            print(f"[跳过] {g['kaodian']}|第{n}题（3次均失败，最后原因：{reason}）", flush=True)
            await asyncio.sleep(random.uniform(1, 2))
            continue
        she = item["stem"].split("\n")[-1]
        title = f"{g['kaodian']}·{n:02d}·{she[:16]}"
        try:
            commit_question(item, g["material"], qid, title, g["fp"])
        except Exception as e:
            skip_fail += 1
            print(f"[入库失败] {qid}：{e}", flush=True)
            await asyncio.sleep(random.uniform(1, 2))
            continue
        saved += 1
        seen_keys.append((she, _norm(she + "".join(o["text"] for o in item["options"]))))
        print(f"[{saved + skip_fail}/{total}] 入库✓ {qid}|{g['kaodian']}|答案{item['answer']}"
              f"|{she[:24]}", flush=True)
        await asyncio.sleep(random.uniform(1, 2))

    print(f"\n完成：本次入库 {saved - skip_exist}，已存在 {skip_exist}，失败跳过 {skip_fail}",
          flush=True)
    conn = db.connect()
    zt = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE module='综合分析' AND kind='真题'"
    ).fetchone()["c"]
    print(f"综合分析模块真题总数：{zt}", flush=True)
    for r in conn.execute(
        "SELECT kaodian, COUNT(*) c FROM documents "
        "WHERE module='综合分析' AND kind='真题' GROUP BY kaodian"
    ):
        print(f"  {r['kaodian']}：{r['c']} 题", flush=True)
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
