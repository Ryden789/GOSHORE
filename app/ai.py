"""DeepSeek 讲题：RAG 上下文构造 + 流式输出。"""
from __future__ import annotations

import base64
import binascii
import json
import re
import time

import httpx

from . import db, shenlun_notes, xingce_notes
from .config import load_settings, vision_model
from .parser import WIKILINK_RE

# 事业单位C类详细结构：保留原有C类备考口径，供题目讲解/综应批改使用。
EXAM_C_FACTS = """【事业单位联考C类（自然科学专技类）权威题型结构】
- 《职业能力倾向测验（C类）》（客观题，90分钟100题，满分150分）：
  常识判断、言语理解与表达、数量分析（数量关系+资料分析）、
  判断推理（图形推理/定义判断/类比推理/逻辑判断）、综合分析（策略制定/实验设计）。
  言语理解以逻辑填空、片段阅读、语句表达为主；综合分析是C类职测特色压轴，包含策略制定与实验设计。
- 《综合应用能力（C类）》（主观题，120分钟，满分150分），共四道大题：
  1. 科技文献阅读题（约50分）：客观判断/选择/匹配 + 主观摘要与简答；
  2. 论证评价题（约40分）：指出材料中4处左右论证错误并说明理由（标准10类谬误：偷换概念、以偏概全、
     强加因果、因果倒置、类比不当、数据误用、绝对化表述、诉诸权威、非黑即白、论据不充分）；
  3. 科技实务题（约40分，部分年份含实验设计/图表分析/数据纠错）；
  4. **材料作文题（约50～60分，压轴必考）**：给定科技或社会热点材料，写一篇800～1000字议论文，
     常考话题：科技创新、科学精神、科技与人文、成果转化、生态文明等。
注意：作文（材料议论文）是C类综应每年固定的最后一道大题，绝不能回答"C类没有作文"；
校阅改错近年多在科技文献或科技实务大题中以小题形式出现。分值各年份略有浮动，回答时用"约"。"""

# 公务员国考/省考 + 事业单位考试权威框架：回答考情/题型/内容类问题必须以此为准，
# 不得把三类考试混为一谈，也不得凭印象否认任一必考题型。
EXAM_FACTS = """【公务员国考/省考与事业单位考试权威框架（以最新年度大纲为准）】

一、公务员国考（中央机关及其直属机构）
- 公共科目：《行政职业能力测验》（行测）+《申论》；部分岗位加专业科目或外语水平测试。
- 行测：客观题，满分100分，120分钟；副省级约135题，地市级/行政执法约130题（近年题量，具体以当年大纲为准）。
  模块：政治理论（近年单列）、常识判断、言语理解与表达、数量关系、
  判断推理（图形推理/定义判断/类比推理/逻辑判断）、资料分析。
- 申论：主观题，满分100分；副省级180分钟，地市级/行政执法150分钟。
  题型：归纳概括、综合分析、提出对策、贯彻执行（公文/应用文）、申发论述（大作文）。
  分级分类命题：副省级重宏观分析与综合概括，地市级重基层治理与执行，行政执法重依法办事与执法实务。
- 面试：结构化面试/无领导小组讨论等，以招录公告为准。

二、公务员省考/联考
- 多数省份考行测+申论，模块与国考同源；题量、时限、分值、分级分类（省市/县乡/行政执法）由各省公告决定。
- 部分省份加考《公共基础知识》或专业科目；不要套用国考题量。

三、事业单位
- 联考常见《职业能力倾向测验》（职测）+《综合应用能力》（综应），分 A/B/C/D/E 类；单招也常考《公共基础知识》。
- 职测：常识判断、言语理解与表达、数量分析（数量关系+资料分析）、判断推理；C类另有综合分析（策略制定/实验设计）。
- 综应：A类管理岗（案例/公文），B类社科专技（概念分析/校阅改错/论证评价/材料作文），
  C类自然专技（科技文献阅读/论证评价/科技实务/材料作文），D类教师，E类医疗。
- 行测与职测同源但不同卷：职测题量/时限/分值随类别和地区变化，C类职测为90分钟100题/150分。
- 申论与综应同源但侧重不同：申论面向机关公文与政策分析，综应更贴岗位实务/专业技术。

四、易混点
- 国考、省考、事业单位联考是不同考试，不能把报名时间、职位表、题量、分值、命题单位混用。
- 涉及当年公告、报名/考试时间、职位表、政策原文时，必须提示"以官方最新公告为准"，不得编造。
- 回答结构题时先确认考试类型与卷别（如国考副省级/地市级/行政执法、事业单位A/B/C/D/E），再给结论。

五、内容地图（按模块调用，不要求用户先说明考试）
- 行测/职测：常识判断（政治/法律/经济/科技/人文/地理/国情）、言语理解（逻辑填空/片段阅读/语句表达）、
  数量关系（工程/行程/利润/浓度/排列组合/概率/几何/最值/容斥）、判断推理（图形/定义/类比/逻辑）、
  资料分析（增长/比重/倍数/平均数/综合分析）。
- 申论：材料阅读与找点、归纳概括、综合分析（解释/评价/比较）、提出对策、贯彻执行（公文格式与身份）、
  申发论述（立意/结构/论证/语言）；常见主题：基层治理、乡村振兴、公共服务、科技创新、文化传承、生态文明、依法行政。
- 综应C：科技文献阅读（摘要/判断/匹配）、论证评价（10类谬误）、科技实务（实验设计/数据纠错/图表分析）、
  材料作文（科技与人文/科学精神/成果转化等）。
- 回答具体题目时先判断考试类型与模块，再按该模块的题型方法作答；不确定年份/卷别时说明假设。

""" + EXAM_C_FACTS

SYSTEM_PROMPT = """你是一名覆盖公务员国考/省考行测、申论与事业单位职测/综应的教研老师，主要辅导一位备考事业单位C类、同时兼顾国考行测与申论的考生（多次模考经验，数量关系强但做题偏慢，资料分析计算速度待提升）。

你可使用的底稿资源（系统已尽力全部附上）：
- 题目的【问法模型】【推理链】【最快解法】【易错点】【母题抽象】
- 【材料档案】：该材料的口径拆解、⚠阅读陷阱、小题群考法地图（资料分析独有）
- 【官方解析】原文（用于对照，不盲从）
- 【考点核心立场】与【跨卷考法】（该考点在所有年份/地区的考法聚合）
- 【用户作答历史】：该生在本题错过几次、最近错选了什么、标注的错因

你必须严格遵守以下规则：

1. **只依据给定底稿作答**。不得引入底稿之外的事实、数据、年份、政策；材料中没有的数据绝不编造。
2. **所有数值计算必须保留可复算的完整算式**，不得只给结果。
3. 若底稿标注了数据缺失、数值空缺，或题目属于疑点题，必须明确告知用户"该数值缺失，结论依官方答案反推"。
4. 若【官方解析】与底稿推理链、或底稿内部存在不一致，必须**同时呈现两方说法**并指出哪方更合理，不得静默采信。
5. **讲透材料陷阱**：若有【材料档案】，讲解时必须点出该材料的 ⚠ 陷阱（如双轴图量级、人次≠册次、时间口径），并说明本题是否涉及。
6. **针对性讲解**：若【用户作答历史】显示该生错过本题，必须分析其错选选项对应的思维误区（结合其标注的错因），而不是泛泛重讲。
7. 讲解使用 Markdown；公式直接书写（如 增长量=现期×r/(1+r)），不要用 LaTeX 图片语法；语言精炼，不写套话。
8. 你的身份是帮助考生质疑和弄懂题目，不是维护标准答案；发现官方解析问题要直接指出。
9. 若题目（含图形推理）依赖图片，你必须只依据文字与底稿讲解，不得猜测图片内容、不得臆断图形规律；若确实无法判断，明确说明需对照图片，绝不能编造。
10. 若学生追问考试科目/题型/分值结构，必须依据下面的权威事实回答；先区分国考/省考/事业单位，尤其不得说"综应C类没有作文"，也不得把三类考试的题量、分值、政策混用：
""" + EXAM_FACTS + """
"""

# 自由提问答疑（不做题也能问）：不依赖题目底稿，靠通用备考知识回答
ASK_SYSTEM = """你是一名公务员国考/省考与事业单位全科备考答疑老师，学生随时向你自由提问（不一定在做题）。

你可以解答：
- 行测/职测各模块：政治理论、常识判断、言语理解与表达、数量关系、判断推理、资料分析，以及C类综合分析；
- 申论/综应各题型：归纳概括、综合分析、提出对策、贯彻执行、申发论述，以及科技文献阅读、论证评价、科技实务、材料作文；
- 面试、速算方法、考情与备考规划、学习计划制定等；
- 本应用自身：题库规模与模块分布、收录范围、数据存放方式、离线/同步能力、已内置哪些手册与功能。

""" + EXAM_FACTS + """

规则：
1. 回答考试科目/题型/分值结构类问题，必须严格依据上面的权威框架；先确认考试类型与卷别，不得编造或否认任何必考题型（尤其是作文），不得把国考/省考/事业单位混为一谈。
2. 不编造时政数据与具体政策细节；涉及当年公告、报名/考试时间、职位表时明确提示"以官方发布为准"。
3. 数值计算保留完整算式，可复算。
4. 回答用 Markdown：先给结论再展开，简洁分点，不写套话。
5. 遇到与备考完全无关的问题，简短回应后引导回备考话题；但问「本应用/题库自身」不算超纲，按底稿如实回答。
6. 当用户上传图片时，你应仔细观察图片中的题目（题干、选项、图形/图表），独立分析后给出答案与解析。不要盲目附和用户给出的答案——如果你分析后认为答案与用户不同，应明确指出并说明理由。先给出你的判断依据，再给结论。
7. 若提问末尾附带了【行测方法论底稿】【申论方法论底稿】【时政底稿】【图形推理底稿】【个人错题本】，这些是本机知识库与个人记录的真实原文：讲对应模块的方法、公式、速算口径时以底稿为准，不要与之冲突；底稿没覆盖的部分再补通用解法，并说明「底稿未收录」。
8. 【图形推理思考框架·按优先级逐级排查，命中即停】先判题型结构（顺推/两段式/九宫格/分组分类/立体截面），再按「元素组成」只走匹配的一支：
   ① 组成完全相同 → 位置类：平移（方向、步长）→ 旋转（角度、方向）→ 翻转（轴对称/中心对称）；
   ② 组成不同但相似 → 样式类：遍历（缺啥补啥）→ 加减同异（含黑白运算）；
   ③ 组成差异大、无明显同构 → 属性类：对称性（轴对称/中心对称、轴数与方向）→ 曲直性 → 开闭性；
   ④ 属性也无线索 → 数量类：面（封闭区域）→ 线（直线/曲线/笔画数）→ 点（交点/切点）→ 角 → 素（种类/个数）；
   ⑤ 立体图形 → 立体类：展开图、截面、三视图、拼合，优先于平面规律。
   命中即停：某条规律能同时解释全部已知格、且唯一锁定一个选项时，立即停止排查并直接作答；不要再为「更稳」继续凑第二、第三条规律，答案里也不必罗列被排除的假设（最多一句带过）。四级走完仍无唯一解时，给出最可能的规律与候选选项，并点明哪一步不确定。黑白方块类优先试「同位置黑白叠加」（黑+黑=白、白+白=白、黑白相异=黑，即去同存异），按行或按列逐格对齐验证；只用「黑块数量」往往选不出唯一答案，不能作为唯一依据。
9. 遇到黑白格/黑白叠加类图推，先把九宫格 9 格和每个选项逐格转写成 3×3 的黑白表（■ 黑、□ 白），再用转写结果推规律、验证选项；转写与推理必须自洽。图像看不清时直接说明「图太小/格线看不清，请放大或分块截图」，不要凭印象编造每一格的黑白，也不要写出与实际不符的"✓ 验证通过"。
10. 当用户问「你和普通 AI 有什么不同」时，据实说明你的本地优势：接入了本机题库（可检索真题考点与出处）、本机《行测/申论速查手册》（方法与口径优先于模型记忆）、本机时政库（含近期会议与政策原文）、用户个人错题本与作答记录。没有接入的项目不要吹，也不要声称能联网查最新公告。
11. 若提问末尾带有【题库家底】，问库总量、模块分布、收录范围或离线能力时必须引用其中的数字与结论，不得估算、不得回答"不知道题库有多少题"，也不要用模型记忆里的旧数字；底稿没给出的细节说明「本机未统计」。
12. 若提问末尾带有【黑白格转写与本地求解·本机像素识别】，那是本机对图片逐格像素转写、并用确定性规则枚举求解的结果：九宫格矩阵、选项矩阵与答案必须原样引用，禁止改写矩阵、禁止给出不同选项、禁止再自行「验证」出另一套规律；该块写明「本机无法判定」时，不得给出任何选项，只能讲可能思路并明确说明无法判定。没有该块时才按第 6、8、9 条自行分析图片。
13. 【证据优先·独特性总则】凡出现【图形特征底稿】【资料分析本机复算】【言语/逻辑结构标记】【题库家底】【个人错题本】【时政底稿】【…方法论底稿】，都必须先引用证据再推理：
   ① 引用时写明出处（「本机像素统计」「本机按题干标签复算」「本机规则扫描」「本机数据库」），算式、统计值、句号位置原样保留，不得改写或补算；
   ② 只对证据覆盖的部分下确定结论，未覆盖的必须标注「以下为通用方法，非本机数据」，不得让用户误以为这些也算过；
   ③ 禁止声称「我已核对过图片」「我已逐格验证」——没有拿到本机转写或特征统计时，直接说明无法核对，不得假装已经做过；
   ④ 每次讲题结尾给三行自检：本题考的是什么规律/公式、下次遇到同类题先看什么、是否建议加入错题本。
14. 【题型思考框架】若提示词末尾出现【题型思考框架·…（本机资料提炼）】，必须按它的顺序作答：先报题型与考点，再一步步走框架（每一步写清「看到什么→据此判什么」），最后给结论；不得跳过框架直接抛答案。若框架与本题明显不适配（例如题型判错），说明不适配并改用通用方法，不要硬套。
"""

# 自由答疑的时政底稿：命中这些词才注入，避免每道题都多付一段输入 token
SHIZHENG_HINTS = (
    "时政", "全会", "会议", "讲话", "公报", "决议", "政策", "新规", "印发", "出台",
    "二十大", "二十届", "十五五", "两会", "政府工作报告", "新闻", "最新",
)

# 行测方法论底稿：《行测速查手册》6 模块 138 个考点。答疑只按模块路由注入
# 最相关的几条——全量 7.4 万字灌进去既稀释指令，也把每次提问的输入费抬上去。
_XC_HINTS: dict[str, tuple[str, ...]] = {
    "ziliao": (
        "资料分析", "资料", "增长率", "增长量", "比重", "基期", "现期", "年均", "倍数",
        "平均数", "截位", "直除", "百化分", "拉动", "贡献率", "顺差", "逆差", "指数", "翻番",
    ),
    "shuliang": (
        "数量关系", "数量", "工程", "行程", "相遇", "追及", "流水", "利润", "浓度", "排列",
        "组合", "概率", "容斥", "最值", "牛吃草", "鸡兔", "数列", "几何", "年龄", "植树",
        "方阵", "周期", "余数", "不定方程", "赋值", "代入排除",
    ),
    "panduan": (
        "判断推理", "判断", "图形", "定义", "类比", "削弱", "加强", "假设", "前提", "真假",
        "翻译", "选言", "二难", "智力推理", "三视图", "截面", "拼合", "归因",
    ),
    "yanyu": (
        "言语", "逻辑填空", "片段", "语句", "排序", "衔接", "成语", "实词", "虚词", "主旨",
        "意图", "细节", "标题", "病句", "下文推断", "词句理解",
    ),
    "changshi": (
        "常识判断", "常识", "法律", "宪法", "民法典", "刑法", "行政法", "历史", "文学",
        "地理", "物理", "化学", "生物", "科技", "航天", "经济常识", "公文", "传统节日", "考古",
    ),
    "zhengzhi": (
        "政治理论", "马哲", "马克思主义", "唯物", "辩证法", "矛盾", "认识论", "党史",
        "毛泽东思想", "中特", "习思想", "中国式现代化", "新发展", "依法治国", "从严治党",
        "一国两制", "核心价值观",
    ),
}


def _ask_user_text(messages: list[dict]) -> str:
    """把所有 user 消息拼成纯文本（多模态 content 只取 text 片段）。"""
    parts = []
    for m in messages:
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts.append(" ".join(
                p.get("text", "") for p in c
                if isinstance(p, dict) and isinstance(p.get("text"), str)
            ))
    return " ".join(parts)


def _xc_point_score(point: dict, question: str, hints: tuple[str, ...]) -> float:
    """考点与问题的相关度：命中词出现在标题里权重最高，正文里次之。"""
    title = str(point.get("title") or "")
    body = str(point.get("body") or "")
    score = 0.0
    for h in hints:
        if h in question:
            score += 3 if h in title else 0
            score += 1 if h in body else 0
    # 题干里出现考点标题的相邻两字（如「截位直除」），也算相关
    for i in range(len(title) - 1):
        if title[i:i + 2] in question:
            score += 2
    return score


def ask_xingce_block(messages: list[dict], max_modules: int = 2, max_points: int = 3,
                     max_chars: int = 3200, body_chars: int = 700) -> str:
    """按问题命中模块注入本地《行测速查手册》的考点正文。

    题库只存「题」，做题方法全在手册里；不注入的话，答疑只能凭模型记忆给个
    泛泛的「一般用公式法」，和 App 里速查页的口径对不上。
    """
    question = _ask_user_text(messages)
    if not question:
        return ""
    groups = (xingce_notes.NOTES.get("groups") or [])
    by_key = {g.get("key"): g for g in groups if g.get("key")}

    # 1) 先定模块：模块名权重最高，其余关键词按出现次数累加
    scores: dict[str, float] = {}
    for key, hints in _XC_HINTS.items():
        group = by_key.get(key)
        if not group:
            continue
        name = str(group.get("name") or "")
        s = question.count(name) * 3 if name else 0
        s += sum(question.count(h) for h in hints)
        if s:
            scores[key] = s
    if not scores:
        return ""
    picked = sorted(scores, key=lambda k: scores[k], reverse=True)[:max_modules]

    # 2) 再挑考点：相关度排序，全不沾边时退回该模块前两条
    out = ["【行测方法论底稿·本地《行测速查手册》】",
           "以下方法来自本机速查手册，讲该模块的公式、口径与速算时以此为准；"
           "手册没覆盖的再补通用解法。"]
    used = len(out[0]) + len(out[1])
    for key in picked:
        group = by_key[key]
        name = str(group.get("name") or key)
        desc = str(group.get("desc") or "")
        out.append(f"\n## {name}" + (f"\n{desc}" if desc else ""))
        used += len(out[-1])
        points = group.get("points") or []
        hints = _XC_HINTS[key]
        ranked = sorted(points,
                        key=lambda p: _xc_point_score(p, question, hints), reverse=True)
        top = [p for p in ranked if _xc_point_score(p, question, hints) > 0][:max_points]
        if not top:
            top = points[:2]
        for p in top:
            body = re.sub(r"\s*\n\s*", "\n", str(p.get("body") or "")).strip()
            tips = [str(t).strip() for t in (p.get("tips") or []) if str(t).strip()][:2]
            chunk = f"\n### {p.get('title')}\n{body[:body_chars]}"
            if tips:
                chunk += "\n易错：" + "；".join(tips)
            if used + len(chunk) > max_chars:
                break
            out.append(chunk)
            used += len(chunk)
    return "\n".join(out)


def has_image(messages: list[dict]) -> bool:
    """提问里是否带图（多模态 content 中的 image_url 片段）。"""
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") in ("image_url", "input_image"):
                    return True
    return False


def _last_user_image(messages: list[dict]) -> str:
    """取最后一条用户消息里最后一张 data URL 图片；没有则空串。"""
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for part in reversed(c):
            if not isinstance(part, dict):
                continue
            if part.get("type") not in ("image_url", "input_image"):
                continue
            u = part.get("image_url")
            if isinstance(u, dict):
                u = u.get("url")
            if isinstance(u, str) and u.startswith("data:image/"):
                return u
    return ""


def ask_graph_block(max_chars: int = 2600, body_chars: int = 420) -> str:
    """图片题的图形推理底稿（手册里 7 个图形考点 ≈ 3 千字）。

    图片题没有文字关键词可以路由，而图推是图片提问里最常见的一类；
    不注入的话模型容易只数黑块数量就下结论（同一道黑白格九宫格就出过这种误判）。
    """
    group = next((g for g in (xingce_notes.NOTES.get("groups") or [])
                  if g.get("key") == "panduan"), None)
    if not group:
        return ""
    out = ["【图形推理底稿·本地《行测速查手册》】",
           "按优先级排查、命中即停：组成相同→位置（平移/旋转/翻转）；组成相似→样式"
           "（遍历/加减同异/黑白运算）；差异大→属性（对称/曲直/开闭）；仍无线索→数量"
           "（面线点角素）；立体→展开图/截面/三视图。某一规律能解释全部已知格且唯一锁定"
           "选项时立即停止，不再穷举第二条。黑白方块类优先试「同位置黑白叠加（去同存异、"
           "去异存同）」，按行或按列对齐比；只数黑块数量通常选不出唯一答案。"]
    used = sum(len(s) for s in out)
    for p in group.get("points") or []:
        if "图形" not in str(p.get("title") or ""):
            continue
        body = re.sub(r"\s*\n\s*", "\n", str(p.get("body") or "")).strip()
        chunk = f"\n### {p.get('title')}\n{body[:body_chars]}"
        if used + len(chunk) > max_chars:
            break
        out.append(chunk)
        used += len(chunk)
    return "\n".join(out)


def ask_grid_block(messages: list[dict]) -> str:
    """黑白格九宫格：本机像素转写 + 确定性求解，作为硬证据注入。

    模型看图会受压缩、随机性与先验影响（同一道黑白格题它曾按行编造验证并答错），
    所以这类题改成「本机算、模型讲」：转写与答案由像素和枚举得出，模型只解释。
    不是该布局、读不准或缺 Pillow/numpy 时返回空串，退回原有看图流程。
    """
    url = _last_user_image(messages)
    if not url:
        return ""
    try:
        from . import gridread
        got = gridread.analyze(url)
    except Exception:
        return ""
    return (got or {}).get("block") or ""


def ask_figfeat_block(messages: list[dict]) -> str:
    """非黑白格图推的本机像素统计（图块/墨迹/连通块/封闭区域/对称度）。

    黑白格已有确定性求解；其余图推无法唯一求解，但属性可测。这里只给统计，
    让模型依据可核对的数据去验证，而不是凭印象宣布「规律成立」。
    """
    url = _last_user_image(messages)
    if not url:
        return ""
    try:
        from . import figfeat
        return figfeat.analyze(url) or ""
    except Exception:
        return ""


def ask_datacalc_block(messages: list[dict]) -> str:
    """资料分析：按题干标签做本机复算，算不出返回空串（绝不编造数字）。"""
    text = _ask_user_text(messages)
    if not text:
        return ""
    try:
        from . import datacalc
        return datacalc.analyze(text) or ""
    except Exception:
        return ""


def ask_textmark_block(messages: list[dict]) -> str:
    """言语/逻辑判断：标出关联词与所在句号，只做位置证据，不下语义结论。"""
    text = _ask_user_text(messages)
    if not text:
        return ""
    try:
        from . import textmark
        return textmark.analyze(text) or ""
    except Exception:
        return ""


def ask_thinkframe(messages: list[dict]) -> dict | None:
    """按题型注入「思考框架」（从 知识点综合/ 的整理讲义提炼）。

    返回 {"title", "text"}：text 同时拼进提示词并作为 evidence 折叠块展示，
    让用户能看到「这题按什么顺序想」，而不是只看答案。命中不了题型返回 None。
    """
    # 只按最后一条用户消息判题型：多轮答疑里前面可能问过别的模块，
    # 用全量历史会把「资料分析」框架粘到后面的图推问题上。
    last = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    text = _ask_user_text([last]) if last else ""
    got = None
    if text:
        try:
            from . import thinkframe
            got = thinkframe.analyze(text)
        except Exception:
            got = None
    if not got:
        if not has_image(messages):
            return None
        # 有图但文字没锁定题型（用户只发图或只说“这题怎么选”）：给通用图像判型顺序兜底
        try:
            from . import thinkframe
            got = thinkframe.image_frame()
        except Exception:
            return None
    return {"title": f"本题型思考框架·{got['name']}（本机资料提炼）",
            "text": got["text"]}


def ask_shizheng_block(messages: list[dict], max_periods: int = 2, per_chars: int = 700) -> str:
    """把本地时政库最近两期拼成一段底稿，供自由答疑引用。

    答疑链路此前完全不碰时政库，问"最近开了什么会"只能靠模型内部知识（有截止日）。
    这里只在问题命中 SHIZHENG_HINTS 时注入，其余提问零成本。
    """
    text = _ask_user_text(messages)
    if not text or not any(k in text for k in SHIZHENG_HINTS):
        return ""
    try:
        rows = db.list_shizheng()
    except Exception:
        return ""
    parts = []
    for r in rows[:max_periods]:            # list_shizheng 已按 period 倒序
        body = re.sub(r"\s*\n\s*", "\n", str(r.get("content") or "")).strip()
        if body:
            parts.append(f"【{r.get('period')}】\n{body[:per_chars]}")
    if not parts:
        return ""
    return (
        "【时政底稿·本地时政库最近两期】\n"
        + "\n\n".join(parts)
        + "\n以上是该库已收录的全部近期内容；库中未收录的日期/会议/数据不要编造，"
          "明确说明需以官方发布为准。"
    )


# 申论 / 综应方法论底稿：《申论速查手册》6 模块 71 个考点，按题型路由注入
_SL_HINTS: dict[str, tuple[str, ...]] = {
    "zonggang": (
        "申论", "综应", "阅卷", "评分", "审题", "时间分配", "卷面", "扣分", "字数", "题型",
    ),
    "gaikuo": (
        "归纳概括", "概括", "归纳", "要点", "提炼", "找点", "争议", "焦点", "变化", "特点",
    ),
    "fenxi": (
        "综合分析", "分析题", "理解", "评析", "评价", "观点", "词句", "异同", "比较", "启示",
    ),
    "duice": (
        "提出对策", "对策", "建议", "措施", "怎么办", "可行性", "教训",
    ),
    "guanche": (
        "贯彻执行", "公文", "通知", "报告", "请示", "函", "倡议书", "讲话稿", "发言稿",
        "提纲", "简报", "纪要", "调研", "公开信", "新闻稿", "工作方案", "编者按", "宣传稿",
    ),
    "zuowen": (
        "大作文", "作文", "文章写作", "申发论述", "议论文", "分论点", "立意", "标题",
        "开头", "结尾", "论证", "素材", "策论文",
    ),
}


# 六类申论/综应题的评分口径（本机固定口径，与手册考点一起注入，供批改/自评引用）
_SL_RUBRIC = {
    "gaikuo": "踩点给分：总括句 + 分点提炼，要点全、准、简洁；同义合并，不抄原句。",
    "fenxi": "分析题按「观点/释义 + 分析（原因/影响/关系）+ 结论」给分，缺一层扣一层。",
    "duice": "对策题按「针对性 + 可行性 + 具体度」给分；只喊口号不得分，需落到主体与做法。",
    "guanche": "贯彻执行按「格式（标题/称谓/落款等）+ 内容要点 + 身份语体」给分，格式错直接降档。",
    "zuowen": "大作文按「立意（准不准）+ 结构（分论点是否并列递进）+ 论证（材料与说理）+ 语言」四档评分。",
    "zonggang": "总纲口径：先审题定题型，再按题型配分；字数不足、卷面潦草、偏离主题均直接降档。",
}


def ask_shenlun_block(messages: list[dict], max_modules: int = 2, max_points: int = 2,
                      max_chars: int = 3000, body_chars: int = 700) -> str:
    """按问题命中模块注入本地《申论速查手册》的考点正文。

    与行测底稿同一套路由逻辑：只给最相关的两三条，避免把整本手册灌进上下文。
    """
    question = _ask_user_text(messages)
    if not question:
        return ""
    groups = (shenlun_notes.NOTES.get("groups") or [])
    by_key = {g.get("key"): g for g in groups if g.get("key")}

    scores: dict[str, float] = {}
    for key, hints in _SL_HINTS.items():
        group = by_key.get(key)
        if not group:
            continue
        name = str(group.get("name") or "")
        s = question.count(name) * 3 if name else 0
        s += sum(question.count(h) for h in hints)
        if s:
            scores[key] = s
    if not scores:
        return ""
    picked = sorted(scores, key=lambda k: scores[k], reverse=True)[:max_modules]

    out = ["【申论方法论底稿·本地《申论速查手册》】",
           "以下方法来自本机速查手册（含评分规则与扣分项），讲申论/综应答法时以此为准；"
           "手册没覆盖的再补通用解法。"]
    used = len(out[0]) + len(out[1])
    for key in picked:
        group = by_key[key]
        name = str(group.get("name") or key)
        desc = str(group.get("desc") or "")
        out.append(f"\n## {name}" + (f"\n{desc}" if desc else ""))
        used += len(out[-1])
        rubric = _SL_RUBRIC.get(key)
        if rubric:
            out.append(f"评分口径：{rubric}")
            used += len(out[-1])
        points = group.get("points") or []
        hints = _SL_HINTS[key]
        ranked = sorted(points,
                        key=lambda p: _xc_point_score(p, question, hints), reverse=True)
        top = [p for p in ranked if _xc_point_score(p, question, hints) > 0][:max_points]
        if not top:
            top = points[:2]
        for p in top:
            body = re.sub(r"\s*\n\s*", "\n", str(p.get("body") or "")).strip()
            tips = [str(t).strip() for t in (p.get("tips") or []) if str(t).strip()][:2]
            chunk = f"\n### {p.get('title')}\n{body[:body_chars]}"
            if tips:
                chunk += "\n易错：" + "；".join(tips)
            if used + len(chunk) > max_chars:
                break
            out.append(chunk)
            used += len(chunk)
    return "\n".join(out)


# 命中这些词才注入个人错题本：普通提问不把用户的学习数据带进模型
WRONG_HINTS = ("错题", "错题本", "老错", "总是错", "一直错", "薄弱", "查漏", "弱项", "我的错")


def ask_wrong_block(messages: list[dict], limit: int = 8, max_chars: int = 1500) -> str:
    """注入本机错题本的最近错题，这是普通 DeepSeek 拿不到的个人数据。

    只给标题与所属模块，不给整题 JSON：模型据此点名「你在资料分析·比重这一块
    反复错」即可，具体题目内容用户自己看得到。
    """
    text = _ask_user_text(messages)
    if not text or not any(k in text for k in WRONG_HINTS):
        return ""
    try:
        rows = db.list_wrong_book(limit)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["【个人错题本·本机记录】以下是用户最近答错的题（题名｜所属模块）："]
    for r in rows[:limit]:
        mod = " / ".join(x for x in (str(r.get("module") or ""),
                                     str(r.get("kaodian") or "")) if x)
        title = str(r.get("title") or "（无标题）")
        lines.append(f"- {title}" + (f"｜{mod}" if mod else ""))
    lines.append("讲薄弱环节时可以点名关联这些题；错题本里没有的不要编造。")
    return "\n".join(lines)[:max_chars]


# 题库家底底稿：只在问「库有多大 / 收了多少题」这类元问题时注入。
_LIB_HINTS = (
    "题库", "多少题", "多少道", "多少篇", "几道题", "几题", "题量", "总量",
    "家底", "收录", "库有多", "这个软件", "本应用", "离线", "数据来源",
    "几套", "多少套", "套卷", "几卷",
)


def ask_library_block(messages: list[dict]) -> str:
    """把本机题库的实时统计拼成一段底稿，供答疑回答「题库一共多少题」。

    答疑此前完全不知道库的规模，被问「一共多少题」只能推托；这里命中
    关键词时注入现查数字，问其他内容时零成本。
    """
    text = _ask_user_text(messages)
    if not text or not any(k in text for k in _LIB_HINTS):
        return ""
    try:
        summary = db.library_summary()
        exam = db.exam_type_counts()
    except Exception:
        return ""
    total = int(summary.get("total") or 0)
    if not total:
        return ""
    by_kind = summary.get("by_kind") or {}
    mods = {str(m.get("module") or ""): int(m.get("c") or 0)
            for m in (summary.get("modules") or [])}
    ordered = [m for m in db.MODULE_ORDER if m in mods]
    ordered += [m for m in mods if m not in db.MODULE_ORDER]
    # 只点名三个主类；总览/说明/空白这类零散行合并成「其他」，避免把
    # 1 篇「未分类」也念给用户听。
    main_kinds = ("真题", "考点", "材料")
    parts = [f"{k} {by_kind[k]:,} 篇" for k in main_kinds if by_kind.get(k)]
    rest = sum(v for k, v in by_kind.items() if k not in main_kinds)
    if rest:
        parts.append(f"其他 {rest:,} 篇")
    kind_line = "，".join(parts) or "未分类"
    mod_line = " / ".join(f"{m} {mods[m]:,}" for m in ordered) or "未统计"
    exams = int(exam.get("total") or 0)
    type_line = " / ".join(f"{k} {v} 套" for k, v in
                           (exam.get("by_type") or {}).items() if v) or "未拆分"
    papers = exam.get("guokao_papers") or {}
    paper_line = " / ".join(f"{p} {papers[p]}" for p in
                            ("副省级", "地市级", "行政执法") if papers.get(p))
    lines = [
        "【题库家底·本机数据库实时统计】",
        f"- 入库文档总量：{total:,} 篇（{kind_line}）",
        f"- 真题模块分布：{mod_line}",
        f"- 可用整卷套卷：{exams} 套（{type_line}；按年份+地区+卷别归一，残卷不列出）",
    ]
    if paper_line:
        lines.append(f"- 国考卷别：{paper_line}")
    lines += [
        "- 套卷统计范围：以上均为行测类整卷；申论/综应整卷另计，不在其中。",
        "- 题库与作答记录都在本机 SQLite（content.db 只读、user.db 可写），"
        "不依赖云端；只有 AI 答疑与 WebDAV 同步需要外部服务。",
        "口径提示：说「多少题」时指真题道数；入库文档总量还包含考点、材料等非题目文档，"
        "两者不要混为一谈。",
        "以上数字来自本机数据库的实时统计：问题库规模、套卷套数、收录范围、离线能力时"
        "直接引用，不要估算，也不要说「本机未统计」，更不要用模型记忆里的旧数字。",
    ]
    return "\n".join(lines)


# 图片答疑输入上限：手机端压缩后单张通常 < 1 MB，这里留足余量并防止
# 恶意客户端把任意 URL / 超大 base64 透传给上游模型（SSRF / 计费放大）。
ASK_MAX_MESSAGES = 12
ASK_MAX_TEXT = 4000
ASK_MAX_IMAGES = 3
ASK_MAX_IMAGE_BYTES = 4 * 1024 * 1024
ASK_IMAGE_RE = re.compile(
    r"data:image/(?:jpeg|jpg|png|webp);base64,([A-Za-z0-9+/]+={0,2})", re.I
)


def normalize_ask_messages(raw: object) -> tuple[list[dict], bool]:
    """校验并收敛自由答疑的多模态消息，返回 (messages, use_vision)。

    - 只接受 user/assistant 角色，最多 12 条、单条文本 4000 字；
    - 图片只允许用户消息、最多 3 张、只接受 JPG/PNG/WebP 的 base64 data URL；
    - 拒绝 http(s) 图片 URL，避免把内网地址透传给上游模型造成 SSRF。
    校验失败抛 ValueError，由 Web / 手机服务各自转成 400。
    """
    if not isinstance(raw, list):
        raise ValueError("messages 必须是数组")
    msgs: list[dict] = []
    use_vision = False
    images = 0
    for m in raw[-ASK_MAX_MESSAGES:]:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content")
        if isinstance(content, list):
            parts: list[dict] = []
            for p in content[:8]:
                if not isinstance(p, dict):
                    continue
                ptype = p.get("type")
                if ptype == "text":
                    text = str(p.get("text") or "")[:ASK_MAX_TEXT]
                    if text:
                        parts.append({"type": "text", "text": text})
                elif ptype == "image_url":
                    if role != "user":
                        raise ValueError("只有用户消息可以带图片")
                    if images >= ASK_MAX_IMAGES:
                        raise ValueError(f"一次最多上传 {ASK_MAX_IMAGES} 张图片")
                    iu = p.get("image_url")
                    url = iu.get("url") if isinstance(iu, dict) else iu
                    if not isinstance(url, str):
                        raise ValueError("图片地址格式不正确")
                    url = url.strip()
                    match = ASK_IMAGE_RE.fullmatch(url)
                    if not match:
                        raise ValueError("只支持 JPG / PNG / WebP 的 base64 图片")
                    payload = match.group(1)
                    # 先按 base64 长度粗判，避免对超大字符串做解码分配
                    if len(payload) > (ASK_MAX_IMAGE_BYTES * 4) // 3 + 8:
                        raise ValueError("单张图片不能超过 4 MB")
                    try:
                        blob = base64.b64decode(payload, validate=True)
                    except (binascii.Error, ValueError):
                        raise ValueError("图片 base64 数据损坏")
                    if not blob:
                        raise ValueError("图片内容为空")
                    if len(blob) > ASK_MAX_IMAGE_BYTES:
                        raise ValueError("单张图片不能超过 4 MB")
                    parts.append({"type": "image_url", "image_url": {"url": url}})
                    images += 1
                    use_vision = True
            if parts:
                msgs.append({"role": role, "content": parts})
        else:
            text = str(content or "")[:ASK_MAX_TEXT]
            if text:
                msgs.append({"role": role, "content": text})
    if not msgs or msgs[-1]["role"] != "user":
        raise ValueError("最后一条必须是用户提问")
    return msgs, use_vision

MODE_TASKS = {
    "quick": (
        "请用【速讲模式】讲解本题，严格按以下结构，总字数不超过 200 字：\n"
        "1. **题型判定**：依据问法模型一句话判定；\n"
        "2. **关键一步**：本题最核心的解题步骤（含算式）；\n"
        "3. **答案**：给出选项。"
    ),
    "deep": (
        "请用【精读模式】讲解本题，严格按以下结构：\n"
        "## 一、考点与问法判定\n"
        "说明本题考什么、凭什么这样判定（引用问法模型）。\n"
        "## 二、推理链\n"
        "逐步展开，每一步写清：做了什么、依据是什么、数据从材料哪里来；保留全部算式。\n"
        "## 三、最快解法\n"
        "给出⚡最快解法及其适用条件；若与常规解法不同，简要对比。\n"
        "## 四、选项分析\n"
        "逐一分析四个选项：正确项为什么对；三个干扰项各是什么陷阱"
        "（坑值/偷换口径/无中生有/单位错误等），结合底稿易错点。\n"
        "## 五、母题总结\n"
        "用一句话抽象出这一类题的通用解法。"
    ),
    "stuck": (
        "请用【卡点讲模式】：不要整题重讲。根据用户提供的'错选选项/卡住步骤'，"
        "只讲偏差部分：指出该错误属于哪类典型思维误区、正确思路的转折点在哪，"
        "保留必要算式，最后用一句话点醒。"
    ),
}


def _build_context(doc: dict) -> str:
    d = doc.get("data", {})
    lines = [
        f"【题目编号】{doc.get('qid')}",
        f"【试卷】{doc.get('exam')}（{doc.get('region')} {doc.get('year')}）",
        f"【考点】{doc.get('kaodian')}",
    ]

    if doc.get("kind") == "真题":
        if d.get("wenfa"):
            lines.append(f"【问法模型】{d['wenfa']}")
        if d.get("stem"):
            lines.append(f"【题干】\n{d['stem']}")
        if d.get("options"):
            opts = "\n".join(
                f"- {o['label']}. {o['text']}" + ("（正确答案）" if o["correct"] else "")
                for o in d["options"]
            )
            lines.append(f"【选项】\n{opts}")
        if d.get("material"):
            material = re.sub(r"<[^>]+>", "", d["material"])
            lines.append(f"【给定材料】\n{material.strip()[:4000]}")
        if d.get("reasoning"):
            lines.append(f"【推理链底稿】\n{d['reasoning']}")
        if d.get("fastest"):
            lines.append(f"【最快解法底稿】{d['fastest']}")
        if d.get("pitfalls"):
            lines.append(f"【易错点底稿】\n{d['pitfalls']}")
        if d.get("muke"):
            lines.append(f"【母题抽象底稿】\n{d['muke']}")
        if d.get("official"):
            official = re.sub(r"<[^>]+>", "", d["official"]).strip()
            if official:
                lines.append(f"【官方解析】\n{official[:3000]}")

        # 材料档案：口径拆解 / 阅读陷阱 / 小题群考法地图（资料分析）
        profile = db.get_material_profile(doc.get("material_fp", ""))
        if profile:
            parts = []
            if profile.get("theme"):
                parts.append(f"材料主题：{profile['theme']}")
            if profile.get("koujing"):
                parts.append(f"口径拆解：\n{profile['koujing']}")
            if profile.get("traps"):
                parts.append(f"⚠阅读陷阱：\n{profile['traps']}")
            if profile.get("relations"):
                parts.append(f"小题群考法地图：\n{profile['relations']}")
            if parts:
                lines.append("【材料档案】\n" + "\n".join(parts))

        # 考点 MOC：核心立场 + 跨卷考法聚合
        m = WIKILINK_RE.search(d.get("preamble", ""))
        if m:
            moc = db.get_doc_by_path(m.group(1)) or db.get_doc_by_path(
                m.group(1) + ".md"
            )
            if moc:
                md_ = moc["data"]
                if md_.get("stance"):
                    lines.append(f"【考点核心立场】\n{md_['stance']}")
                zl = md_.get("zhenti_list")
                if zl:
                    if isinstance(zl, list):
                        zl = "\n".join(
                            f"- {x}" if isinstance(x, str) else f"- {x.get('title', x)}"
                            for x in zl[:15]
                        )
                    lines.append(f"【跨卷考法】\n{str(zl)[:2000]}")

        # 用户作答历史：让讲解针对该生的实际错误
        hist = db.get_user_history(doc["id"])
        if hist["tries"]:
            h = f"作答 {hist['tries']} 次，错 {hist['wrongs']} 次。"
            if hist["last_selected"]:
                h += f"最近一次选择：{hist['last_selected']}。"
            if hist["reason"]:
                h += f"该生标注错因：{hist['reason']}。"
            lines.append(f"【用户作答历史】{h}")

        # 相关题（只取相关度最高的 3 道，仅标题/地区/年份）
        rel = d.get("related", [])
        rel = sorted(rel, key=lambda x: -x.get("degree", 1))[:3]
        if rel:
            briefs = db.get_related_brief([r["path"] for r in rel])
            bm = {b["path"]: b for b in briefs}
            text = "\n".join(
                f"- {bm[r['path']]['qid']} {bm[r['path']]['title']}"
                f"（{bm[r['path']]['region']} {bm[r['path']]['year']}）"
                for r in rel if r["path"] in bm
            )
            if text:
                lines.append(f"【相关题】\n{text}")

    else:
        lines.append("【底稿】\n" + json.dumps(d, ensure_ascii=False)[:4000])

    return "\n\n".join(lines)


def build_first_messages(doc: dict, mode: str, stuck: dict | None) -> list[dict]:
    context = _build_context(doc)
    task = MODE_TASKS.get(mode, MODE_TASKS["deep"])
    user = task + "\n\n以下是题库底稿：\n\n" + context
    # 多模态降级：题目依赖图片而当前模型无法读图时，明确告知 AI 不要臆测图形内容
    stem_and_opt = (doc["data"].get("stem", "") or "") + json.dumps(
        doc["data"].get("options") or [], ensure_ascii=False
    )
    if "/img?path=" in stem_and_opt or "<img" in stem_and_opt:
        user += (
            "\n\n【重要】本题题干/选项包含图片（图形推理等），你无法读取图片内容。"
            "请只基于文字部分与底稿讲解，并明确告诉学生：图形部分需自行对照图片理解，"
            "不要编造图中细节。"
        )
    if mode == "stuck" and stuck:
        user += (
            f"\n\n【用户卡点】错选选项：{stuck.get('selected','未提供')}；"
            f"卡住步骤：{stuck.get('step','未提供')}"
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


async def chat_once(messages: list[dict], temperature: float = 0.3) -> str:
    """非流式调用：返回完整回复文本，失败抛 RuntimeError。"""
    buf = []
    async for kind, payload in stream_chat_with_temp(messages, temperature):
        if kind == "delta":
            buf.append(payload)
        elif kind == "error":
            raise RuntimeError(payload)
    return "".join(buf)


# ---------------- 错因结构化归因 2.0 ----------------

# 五类错因（与前端 WRONG_REASONS 保持一致）
WRONG_CATEGORIES = ["知识盲区", "审题失误", "计算错误", "时间不够", "蒙猜"]


def build_wrong_reason_prompt(stem: str, options: str, correct: str,
                              last_selected: str, tries: int, wrongs: int) -> str:
    """错因 2.0：要求 AI 返回结构化 JSON（含具体错点、考点、建议）。"""
    return (
        "你是行测/职测教研老师。学生做错了一道选择题，请给出结构化归因。\n"
        "严格只输出一个 JSON 对象，不要 markdown 代码块、不要任何多余文字，格式：\n"
        '{"category":"...","specific":"...","kaodian":"...","advice":"..."}\n'
        "字段要求：\n"
        "- category：必须且只能是以下五类之一：知识盲区 / 审题失误 / 计算错误 / 时间不够 / 蒙猜\n"
        "- specific：一句话说清具体错在哪（≤30 字）\n"
        "- kaodian：本题考点（≤20 字，尽量用题干/选项里出现的考点词）\n"
        "- advice：一句可执行的改进建议（≤30 字）\n"
        "判定标准：\n"
        "- 考点完全陌生、需补知识才能做对 → 知识盲区\n"
        "- 会做但看错问法/理解偏差/忽略限定词 → 审题失误\n"
        "- 涉及数值计算且错选项常为过程错误值 → 计算错误\n"
        "- 作答次数多、耗时短、反复换答案、无明显思路 → 时间不够\n"
        "- 错选项与任何考点无关联、随机乱选 → 蒙猜\n"
        "若题干/选项包含图片（图形推理等），你无法读图，禁止据图片臆断；"
        "若错因只能靠图判断，category 取「审题失误」。\n\n"
        f"【题目】{stem[:800]}\n"
        f"【选项】\n{options[:700]}\n"
        f"【正确答案】{correct}\n"
        f"【学生最近错选】{last_selected or '未知'}\n"
        f"【作答历史】共 {tries} 次错 {wrongs} 次"
    )


def parse_wrong_reason_json(raw: str) -> dict | None:
    """解析 AI 结构化归因 JSON，容错处理 markdown 代码块与前后杂字。

    解析失败、非 dict、或 category 不落在五类内时返回 None（调用方走关键词兜底）。
    """
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    cat = str(data.get("category", "")).strip()
    if cat not in WRONG_CATEGORIES:
        cat = next((c for c in WRONG_CATEGORIES if c and (c in cat or cat in c)), "")
    if not cat:
        return None
    return {
        "category": cat,
        "specific": str(data.get("specific", "")).strip()[:60],
        "kaodian": str(data.get("kaodian", "")).strip()[:40],
        "advice": str(data.get("advice", "")).strip()[:80],
    }


# ---------------- 时政自测题生成（功能 2.2） ----------------

SHIZHENG_QUIZ_N = 10


def build_shizheng_quiz_prompt(content: str, n: int = SHIZHENG_QUIZ_N) -> str:
    """时政内容 → 单选自测题（强制 JSON，答案分布均匀）。"""
    return (
        f"基于下面的时政内容，出 {n} 道单选自测题，直接考察内容中的事实要点。\n"
        "严格只输出一个 JSON 对象（不要 markdown 代码块、不要多余文字），格式：\n"
        '{"items":[{"q":"题干","options":["A. ...","B. ...","C. ...","D. ..."],'
        '"answer":"A","note":"一句话考点说明"}]}\n'
        "要求：answer 只能是 A/B/C/D 且四个选项分布尽量均匀；干扰项似是而非但正确项唯一；"
        "note 控制在 30 字内；题干不得出现「上述材料」「文中」等指代。\n\n"
        f"【时政内容】\n{(content or '')[:6000]}"
    )


def parse_shizheng_quiz_json(raw: str, n: int = SHIZHENG_QUIZ_N) -> list[dict] | None:
    """解析时政自测题 JSON，容错代码块与前后杂字。解析失败返回 None。"""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    items = []
    for q in (data.get("items") or [])[:max(1, n)]:
        if not isinstance(q, dict):
            continue
        opts = q.get("options") or []
        ans = str(q.get("answer", "")).strip().upper()[:1]
        if not q.get("q") or len(opts) != 4 or ans not in "ABCD":
            continue
        items.append({
            "q": str(q["q"]).strip()[:500],
            "options": [str(o).strip()[:200] for o in opts],
            "answer": ans,
            "note": str(q.get("note", "")).strip()[:80],
        })
    return items or None


# ---------------- AI 多轮追问式讲题（功能 2.5 · 苏格拉底式） ----------------

GUIDE_MAX_ROUNDS = 6

GUIDE_SYSTEM = """你是一名行测/职测教研老师（熟悉公务员国考/省考行测与事业单位职测的命题差异），正在用【苏格拉底式追问】引导一名考生自己把题想通。

铁律：
1. **绝不直接说出正确答案，也绝不直接给出完整解题步骤**（除非系统在末尾标注【必须给答案】）。
2. 每轮只做一件事：先用一句话肯定学生答对/想到的部分，再抛出一个**具体、可回答**的追问，把他往下一步推。
   追问要针对"他还没想到的那个关键点"，而不是泛泛地问"你再想想"。
3. 如果学生上一轮答错或答不上来，不要重复同一个问题，要**降低台阶**：给一个更小的提示
   （如"先看单位"、"先判断问的是增长量还是增长率"），再用新问题引导。
4. 语气像面对面辅导，口语、简短，每轮 60~140 字，不用 Markdown 标题、不列长清单。
5. 只依据下面给出的题库底稿提问与提示，不得引入底稿之外的数据与结论；底稿缺失的部分不要编造。

输出格式（必须严格遵守）：
- 从第一行开始直接输出你的追问/提示正文（纯文本，可含简单换行）。
- 正文输出完后，另起一行输出阶段标记：@@PHASE:probe@@ 或 @@PHASE:hint@@ 或 @@PHASE:answer@@
  - probe：学生在正常推进，你在追问引导；
  - hint：学生卡住了，你给了更强的提示；
  - answer：你已给出答案与完整解析（仅在系统标注【必须给答案】时使用）。
- 除正文与这一行阶段标记外，不要输出任何其他内容（不要解释格式、不要加引号）。"""


def build_guide_messages(doc: dict, history: list[dict], answer: str,
                         round_no: int, force_answer: bool = False) -> list[dict]:
    """构造引导式讲题的多轮上下文：底稿只给 AI 看，学生只看追问。"""
    context = _build_context(doc)
    sys_prompt = GUIDE_SYSTEM
    if force_answer:
        sys_prompt += (
            f"\n\n【必须给答案】这是第 {round_no} 轮，也是最后一轮。"
            "请停止追问，直接给出正确答案与完整解析（含关键算式），并输出 @@PHASE:answer@@。"
        )
    else:
        sys_prompt += f"\n\n【当前轮次】第 {round_no} / {GUIDE_MAX_ROUNDS} 轮。"
    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "以下是本题的题库底稿（学生看不到，供你提问与判断对错）：\n\n" + context},
    ]
    for m in history or []:
        role = m.get("role")
        if role in ("user", "assistant"):
            content = str(m.get("content") or "")[:4000]
            if content:
                msgs.append({"role": role, "content": content})
    if answer:
        msgs.append({"role": "user", "content": answer})
    return msgs


def parse_guide_output(raw: str, round_no: int, force_answer: bool = False) -> dict:
    """解析引导输出：正文 + @@PHASE:xxx@@。解析失败降级 probe，正文原样返回。"""
    text = (raw or "").strip()
    phase = "probe"
    m = re.search(r"@@PHASE:\s*(probe|hint|answer)\s*@@", text)
    if m:
        phase = m.group(1)
        text = text[:m.start()].rstrip()
    else:
        # 容错：去掉可能残留的 @@ 片段
        text = re.sub(r"@@[^@]*@@", "", text).rstrip()
    if force_answer:
        phase = "answer"
    if not text:
        text = "（AI 没有返回内容，请重试，或直接查看完整解析）"
    return {"reply": text, "phase": phase, "round": round_no, "max_rounds": GUIDE_MAX_ROUNDS}


async def stream_chat_with_temp(messages: list[dict], temperature: float):
    """同 stream_chat，但温度可调。"""
    s = load_settings()
    if not s["deepseek_api_key"]:
        yield "error", "未配置 DeepSeek API Key，请到「设置」中填写。"
        return
    payload = {
        "model": s["deepseek_model"],
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
    url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield "error", f"API 返回 {resp.status_code}：{body.decode('utf-8','ignore')[:500]}"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        yield "delta", delta["content"]
    except httpx.HTTPError as e:
        yield "error", f"网络请求失败：{e}"
        return


async def stream_chat(messages: list[dict], use_vision: bool = False,
                      think_on: bool | None = None):
    """yield ('delta'|'think'|'error'|'done', payload)。

    思考模式：入参 `think_on` 优先（答疑输入框旁的按钮按次覆盖），未传时回落到
    设置项 `ai_thinking`（默认开）。开启时不发 `thinking`，让模型按默认深度推理；
    关闭时显式 `disabled`，换速度。此前看图请求写死 disabled，同一道图形题模型
    只看一眼就给结论，这正是内置 AI 与网页版表现不一致的根源之一。
    整体仍有墙钟上限：流式只在有数据时才走循环，读超时（120s）挡不住
    "一直在输出思考"的长时间生成，必须自己掐。
    """
    s = load_settings()
    if not s["deepseek_api_key"]:
        yield "error", "未配置 DeepSeek API Key，请到「设置」中填写。"
        return

    think_on = bool(s.get("ai_thinking", True)) if think_on is None else bool(think_on)
    payload = {
        "model": vision_model(s) if use_vision else s["deepseek_model"],
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
    if use_vision:
        # 思考与正文共用输出上限，开启思考时留足额度，避免「想完了没正文」
        payload["max_tokens"] = 8192 if think_on else 4096
    if not think_on:
        payload["thinking"] = {"type": "disabled"}
    headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
    url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"
    # 关思考的看图请求正常 10~30 秒；开思考或纯文字题允许更长的推理
    deadline = 60.0 if (use_vision and not think_on) else 150.0
    started = time.monotonic()
    timed_out = False
    answered = False
    finish = None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield "error", f"API 返回 {resp.status_code}：{body.decode('utf-8','ignore')[:500]}"
                    return
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choice = chunk.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        finish = choice.get("finish_reason") or finish
                        if delta.get("reasoning_content"):
                            yield "think", delta["reasoning_content"]
                        if delta.get("content"):
                            answered = True
                            yield "delta", delta["content"]
                    # 只在「还没开始出正文」时掐：正文一旦开始就让它讲完，
                    # 避免把一份正常的长解析从中间截断
                    if not answered and time.monotonic() - started > deadline:
                        timed_out = True
                        break
    except httpx.HTTPError as e:
        yield "error", f"网络请求失败：{e}"
        return
    if timed_out:
        yield "error", (f"本次生成超过 {int(deadline)} 秒，已自动停止（模型一直在推理，"
                        f"迟迟没有给出正文）。可以换个更具体的问法，或把题目中的关键区域单独截图再问。")
        return
    # 一个字正文都没出就结束了：思考把输出额度吃光（finish_reason=length）是最常见的
    # 情况，界面若只挂着「思考中…」用户会以为卡死，这里必须给出明确结论。
    if not answered:
        if finish == "length":
            yield "error", ("模型这次把输出长度全用在思考上了，没来得及给正文（思考+正文共用同一个"
                            "输出上限）。把提问缩短、或只截关键图形再问会好很多。")
        else:
            yield "error", "本次没有生成正文（模型提前结束），请重试或换个问法。"
        return
    yield "done", ""
