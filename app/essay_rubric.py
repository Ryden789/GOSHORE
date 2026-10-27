"""申论 / 综应C 批改评分细则知识库。

依据公开阅卷规则整理（国考/省考申论阅卷标准、事业单位联考综应C类赋分说明）：
- 小题「踩点给分」：按词赋分（材料原词）或按意赋分（意思一致即可）
- 大作文「按档给分」：四类八档，立意/论据/结构/语言四维定档，基准分上下浮动
- 综应C：文献阅读50 / 论证评价40 / 材料作文60，均有公开赋分结构

L1（2026-10-26）起，评分口径蒸馏自 Shenlun.skill（MIT）的 scoring-rules.md /
writing-rules.md：子项级采分点、三档折算、踩点加分不倒扣、不查错别字与卷面。
"""

import json
import re

RUBRICS = {
    # ---------------- 申论 ----------------
    "sl_guina": {
        "name": "申论·归纳概括",
        "default_score": 15,
        "hint": "概括问题/原因/做法/变化/成效等",
        "rubric": """【评分方式】踩点给分。满分按 default_score，要点 5-10 个，每点 1-3 分；子项分值之和等于本题满分。
【给分规则】
1. 要点全面是核心：多踩一个有效关键词多得分，漏点即失分，宁多勿漏。
2. 按词赋分与按意赋分并存：材料表述规范时用原词给分；材料为案例/数据时按意思一致给分。
3. 三档折算：命中 ≥80% 给该点满分；40%~80% 给该点一半；<40% 给 0 分。
4. 审题偏差直接不得分：问经验答问题、问做法答原因、问国内答国外。
5. 概括词必须来自材料，自创概括词不认；口语化改写但语义到位按意给分，不单独扣分。
6. 条理：须分条标序号；题干要求"概括性强/观点明确"时核心词须前置，未前置扣 1-2 分；要求"分类合理"时未归类扣 2-3 分。
7. 语言：抄整句、罗列数据案例、超字数，扣 1-2 分。
【硬性扣分】超字数按超出比例扣 1-2 分；未分条作答扣 1 分。
【批改重点】先查要点数是否够（<5 个基本不可能拿高分），再查是否有总括词前置；归纳概括题不写总括句不扣分。""",
    },
    "sl_fenxi": {
        "name": "申论·综合分析",
        "default_score": 20,
        "hint": "谈理解/评析观点/比较分析",
        "rubric": """【评分方式】结构分 + 要点分，按意赋分。
【给分规则】
1. 结构（约 1/4）：须按"是什么—为什么—怎么办（总结）"三段式，缺任一环节该环节记 0 分。
2. 解释含义（约 1/5）：须出自材料上下文，兼顾表面义与深层义；解释错误时后续分析不再给分。
3. 多角度分析（约 1/2）：原因/影响/背景须分层，按意给分；同一层次换说法重复表述只计一次。
4. 三档折算：每个子项命中 ≥80% 给满分；40%~80% 给一半；<40% 给 0 分。
5. 结论/对策收尾（约 1/6）：须有一句明确结论或对策，缺失该部分记 0 分。
6. 综合分析题必须有总括句，缺总括句扣 1 分。
【硬性扣分】缺总括句扣 1 分；超字数扣 1 分。
【批改重点】先看有没有总括句与三段式框架，再查原因、影响两个层次是否都答到。""",
    },
    "sl_duice": {
        "name": "申论·提出对策",
        "default_score": 20,
        "hint": "针对问题提出措施建议",
        "rubric": """【评分方式】踩点给分，按意赋分。
【给分规则】
1. 对策要点 5-8 个，每点 2-4 分；与材料问题一一对应者得分，材料之外凭空发挥不得分、也不倒扣。
2. 三档折算：命中 ≥80% 给该点满分；40%~80% 给该点一半；<40% 给 0 分。
3. 可操作性：对策须含"主体+手段+内容"；只写"加强管理""提高认识"而无展开的，该点按一半分计。
4. 来源优先级：材料直接对策 > 问题反推 > 常识补充；材料中现成对策（专家建议、他地经验）漏用的，该点记 0 分。
5. 身份限定：题干限定身份（如"作为某部门工作人员"）时，越权对策该点记 0 分。
6. 两问题目（问题+对策）只答一问，总分不超过满分的 50%。
【硬性扣分】只答一问按半分封顶；超字数扣 1-2 分。
【批改重点】先数对策条数与材料问题是否一一对应，再查每条是否落到具体主体与手段。""",
    },
    "sl_yingyongwen": {
        "name": "申论·应用文（贯彻执行）",
        "default_score": 20,
        "hint": "倡议书/讲话稿/通知/短评等",
        "rubric": """【评分方式】格式分 + 内容分 + 整体语言分。
【给分规则】
1. 格式（约 2-4 分）：标题、称谓、落款、日期按文种要求逐项给分；题干注明"不考虑行文格式"则不设格式分，分值并入内容。
2. 内容（约 2/3）：开头交代背景/事由/目的、主体按文种组织要点（踩点给分）、结尾呼吁/要求/总结，三部分齐全给满，缺一部分该部分记 0 分。
3. 三档折算：内容要点命中 ≥80% 给满分；40%~80% 给一半；<40% 给 0 分。
4. 文种语气：倡议书要有感染力、讲话稿要有开场白与称呼、通知要简明；语气与文种不符该项记 0 分。
5. 语言：书面化、无病句，口语表述在该项按一半分计。
【硬性扣分】有格式要求时缺标题扣 2 分，缺称谓或落款各扣 1 分；字数超/不足规定 10% 以上扣 1-2 分。
【批改重点】先按文种核对格式三件套（标题/称谓/落款），再看主体要点是否覆盖材料关键信息。""",
    },
    "sl_dazuowen": {
        "name": "申论·大作文",
        "default_score": 40,
        "hint": "议论文，按四类八档评分",
        "rubric": """【评分方式】按档给分：先定档，再在档内以基准分上下浮动；四维定档：立意、论据、结构、语言。
【给分规则】
1. 定档：一类 31-40、二类 21-30、三类 11-20、四类 0-10。
2. 立意：未扣住题干话题词按四类；标题与总论点指向不一致降一档；无明确中心论点降一档。
3. 论据：只举案例未点评其作用（案例未证明论点）该段记 0 分；素材与论点无关不计入论据分。
4. 结构：缺标题/开头/分论点段/结尾任一环节降一档；通篇分条列项类似提纲按四类。
5. 语言：通篇模板化套话按三类以下；表达准确、有个人论述的可在档内上浮。
【硬性扣分】无标题扣 2-3 分；不足 800 字每少 50 字扣 2 分，不足 700 字按三类以下，不足 300 字 0-5 分。
【批改重点】先判立意是否跑题（跑题即四类），再看分论点是否支撑总论点、每段是否有论证而非罗列。""",
    },
    # ---------------- 综应 C 类 ----------------
    "zy_wenxian": {
        "name": "综应C·文献摘要/概括",
        "default_score": 20,
        "hint": "科技文献阅读题中的主观小题",
        "rubric": """【评分方式】踩点给分，按意赋分。科技文献阅读大题共 50 分（客观题部分请自行对答案，此处只批主观小题）。
【给分规则】
1. 内容摘要题：须涵盖①研究对象/背景 ②主要发现或结论 ③意义/应用前景，三层齐全给满，缺一层该层记 0 分。
2. 概括题：要点须出自文献原文，引入文献外知识不得分、也不倒扣。
3. 三档折算：命中 ≥80% 给该点满分；40%~80% 给一半；<40% 给 0 分。
4. 摘要须为连贯段落；罗列短语在该部分按一半分计。
5. 准确性：数据、结论与文献原文不符（偷换量级、范围、时间）该点记 0 分。
【硬性扣分】字数超/不足规定 10% 以上扣 1-2 分。
【批改重点】先查三层结构是否齐全，再逐条核对数据与结论是否与原文一致。""",
    },
    "zy_lunzheng": {
        "name": "综应C·论证评价",
        "default_score": 40,
        "hint": "找4处逻辑错误并说明理由",
        "rubric": """【评分方式】共 40 分：须找出 4 处论证错误，每处 10 分 = 指出错误准确 3 分 + 理由合理 5 分 + 表述清晰 2 分；只写 3 处最高 30 分，以此类推。
【给分规则】
1. 常见错误类型（指出时须准确归类）：概念类（偷换概念、界定不清）、判断类（绝对化、非黑即白）、推理类（以偏概全、强加因果、归因不当、类比不当、统计学错误、预期论据）、论据类（论据本身错误、论据不相干）。
2. "指出错误"须写明错在哪一句/哪一推理；归类错但描述对，该处给一半分。
3. "理由"须说明为什么错（如"仅由 B 市 2004-2016 年数据难以说明全国情况"）；只写类型名无解释，理由分记 0 分。
4. 同一处错误换个说法重复写，只计一次，不得充作第 4 处。
【硬性扣分】A/B 两处各不超 50 字，超字数扣表述分。
【批改重点】先数是否 4 处且互不重复，再逐处核对归类与理由是否成立。""",
    },
    "zy_shiwu": {
        "name": "综应C·科技实务",
        "default_score": 40,
        "hint": "数据分析/图表/对策",
        "rubric": """【评分方式】按任务点踩点给分。
【给分规则】
1. 数据分析（约 40%）：须准确引用数据（数值、趋势、占比、极值）；无量化支撑的描述按一半分计；趋势方向说反该点记 0 分。
2. 图表要点（约 30%）：须含图表类型选择、坐标轴/图例设置、突出表达的数据关系，缺项该点记 0 分。
3. 对策建议（约 30%）：须基于数据结论提出，含主体与具体措施；与数据脱节的对策记 0 分。
4. 三档折算：命中 ≥80% 给该点满分；40%~80% 给一半；<40% 给 0 分。
【硬性扣分】字数超/不足规定 10% 以上扣 1-2 分。
【批改重点】先查数据分析是否有量化支撑，再查对策是否从数据结论推出。""",
    },
    "zy_zuowen": {
        "name": "综应C·材料作文",
        "default_score": 60,
        "hint": "科技/自然主题议论文，五档评分",
        "rubric": """【评分方式】整体观照按类赋分：先定类，再在类内以基准分上下浮动。
【给分规则】
1. 定类：一类 51-60（基准 55）、二类 41-50（基准 45）、三类 31-40（基准 35）、四类 21-30（基准 25）、五类 0-20。
2. 立意：偏离题意按四类及以下；中心论点须从材料推出，纯空泛表态降一档。
3. 论据：案例须结合科研实际并点评其作用，只举未证该段记 0 分。
4. 结构：缺开头/分论点/结尾任一环节降一档；通篇分条列项类似提纲按五类。
5. 语言：通顺准确、术语规范，模板化套话在类内取下限。
【硬性扣分】无标题或标题不规范扣 5 分；500 字以下或残篇 10 分左右，不到 100 字 5 分左右。
【批改重点】先判主题是否扣题（科技/自然/科学精神类），再看中心论点是否从材料推出、分论点是否支撑中心。""",
    },
}

SYSTEM_PROMPT = """你是一名资深申论/综合应用能力阅卷老师，参与过多次公务员国考、省考与事业单位联考的阅卷工作，熟悉踩点给分与按档赋分的操作规则。
你熟悉国考副省级/地市级/行政执法、省考分级分类以及事业单位综应A/B/C/D/E类的差异，评分时按题目所属考试类型与题型细则执行，不把不同考试的评分标准混用。

批改原则：
1. 严格依据题目对应的【评分细则】给分，不打人情分，也不刻意压分；给分必须有依据。
2. 只依据题目所给材料与题干判断要点，不引入材料之外的事实；考生作答中材料之外但合理的内容按"按意赋分"原则处理。
3. 先找得分点，再找问题；每个得分点都要指出对应作答原文。
4. 语言精炼、一针见血，不写客套话；指出问题必须给出可操作的改法。
5. 采分点三档折算（硬规则，不得自行发挥）：
   - 命中 ≥80% 该点要素 → 给该点满分
   - 命中 40%~80% → 给该点一半分
   - 命中 <40% → 该点 0 分
6. 采分点关键词必须来自给定材料或参考答案，禁止自创概括词；考生用口语改写但语义到位，按「按意赋分」给分，不因口语化单独扣分。
7. 考生写了材料与参考答案之外的合理内容：不得分，但**不额外倒扣**（申论是加分制，不存在扣分制）。
8. 不做错别字检查，不做卷面/字迹评价；只评价内容与结构。
9. 每一条 points 的 evidence 必须写清「出自材料第几段/哪句话」或「作答中对应的原句」，禁止空泛写「论述不到位」。
10. 若题目所属考试类型未明确，按「国考地市级」口径评分，不得套用事业单位综应口径。
"""

OUTPUT_SPEC = """【输出格式】严格按以下 Markdown 结构输出：

## 总分：X / {total}分
（一句话总评，含所处档次）

## 得分明细
| 评分点 | 满分 | 得分 | 评语 |
|---|---|---|---|
（按评分细则逐项列出；踩点题逐点列出"要点名称"，命中给分、未命中给0并在评语写明材料中对应的出处）

## 主要问题
（按严重程度列出2-4条，每条先说问题、再说后果）

## 修改建议
（针对每条主要问题给出具体可操作的修改方法）

## 修改示范
（对失分最重的一部分，直接给出修改后的示范文字；小题示范1-2个要点的规范写法，作文示范开头段或一个分论点段）"""


# ============================================================
# 批改 2.0：结构化输出（要点命中表 + 四维评分 + 改写示范）
# ============================================================

# 四维评分默认预设：名称 / 说明 / 权重(%，之和为 100)
DEFAULT_DIMS = [
    ("要点完整性", "是否覆盖参考答案/材料中的核心得分点", 45),
    ("逻辑结构", "层次是否清晰，有无分条、总括句", 20),
    ("语言规范", "表述是否准确、简洁、书面化，有无口语与语病", 20),
    ("字数与格式", "字数是否达标，格式（标题/称谓/落款）是否规范", 15),
]

# 各题型专属维度（未列出的题型走 DEFAULT_DIMS）
DIM_PRESETS = {
    "sl_fenxi": [
        ("要点完整性", "是否覆盖词句含义、原因、影响等多角度要点", 35),
        ("逻辑结构", "是否按「是什么—为什么—怎么办」展开，层次分明", 30),
        ("语言规范", "分析表述是否准确、简洁", 20),
        ("字数与格式", "字数是否达标、分条是否规范", 15),
    ],
    "sl_duice": [
        ("要点完整性", "对策是否与材料问题一一对应，是否漏用材料现成对策", 50),
        ("逻辑结构", "对策是否分类清晰、主体+手段+内容完整", 20),
        ("语言规范", "是否具体可操作，有无空泛表述", 15),
        ("字数与格式", "字数是否达标、分条是否规范", 15),
    ],
    "sl_yingyongwen": [
        ("要点完整性", "开头背景、主体要点、结尾呼吁三部分是否齐全", 45),
        ("逻辑结构", "正文组织是否符合文种逻辑", 15),
        ("语言规范", "语气是否与文种相符、表达是否流畅", 15),
        ("字数与格式", "标题/称谓/落款/日期是否规范，字数是否达标", 25),
    ],
    "sl_dazuowen": [
        ("立意与论据", "立意是否紧扣题意，论据是否充分且联系材料实际", 40),
        ("逻辑结构", "总论点与分论点是否形成支撑，结构是否完整", 25),
        ("语言表达", "语言是否流畅、准确，有无模板化", 20),
        ("字数与格式", "字数是否达标，有无标题，卷面是否规范", 15),
    ],
    "zy_zuowen": [
        ("立意与论据", "中心论点是否从材料推出，论据是否结合科研实际", 40),
        ("逻辑结构", "思路是否清晰，结构是否完整", 25),
        ("语言表达", "语言是否通顺准确，术语是否规范", 20),
        ("字数与格式", "字数是否达标，标题是否规范", 15),
    ],
    "zy_lunzheng": [
        ("要点完整性", "是否准确找出 4 处逻辑错误并归类", 50),
        ("逻辑结构", "错误描述与理由是否一一对应、条理清晰", 20),
        ("语言规范", "错误类型术语是否准确、表述是否简明", 15),
        ("字数与格式", "A/B 两处是否各不超 50 字", 15),
    ],
    "zy_wenxian": [
        ("要点完整性", "是否涵盖研究对象、主要发现、意义三层", 45),
        ("逻辑结构", "摘要是否为连贯段落、概括是否分条", 20),
        ("语言规范", "数据结论是否与文献原文一致", 20),
        ("字数与格式", "字数是否达标、条理是否清楚", 15),
    ],
    "zy_shiwu": [
        ("要点完整性", "数据分析/图表要点/对策建议三类任务点是否齐全", 45),
        ("逻辑结构", "分析是否层层递进、对策是否基于数据结论", 20),
        ("语言规范", "数据引用是否准确、术语是否规范", 20),
        ("字数与格式", "字数是否达标、条理是否清楚", 15),
    ],
}


def dims_for(category: str) -> list[dict]:
    """返回题型的四维评分维度（含权重与说明），权重之和为 100。"""
    preset = DIM_PRESETS.get(category, DEFAULT_DIMS)
    return [{"name": n, "desc": d, "weight": w} for n, d, w in preset]


POINT_STATUSES = ["命中", "部分命中", "缺失"]

_STATUS_ICON = {"命中": "✅", "部分命中": "🟡", "缺失": "❌"}


def normalize_status(raw) -> str:
    """把 AI 返回的各种状态说法归一到 命中 / 部分命中 / 缺失。"""
    s = str(raw or "").strip()
    if not s:
        return "缺失"
    if "部分" in s or "半" in s or "🟡" in s:
        return "部分命中"
    if any(k in s for k in ("未", "缺", "漏", "无", "错", "否", "❌", "✗", "×")):
        return "缺失"
    if any(k in s for k in ("命中", "覆盖", "符合", "有", "是", "✅", "✓", "√")):
        return "命中"
    return "缺失"


SYSTEM_PROMPT_JSON = SYSTEM_PROMPT + """
11. 你必须只输出一个 JSON 对象，不输出任何 JSON 之外的文字、解释或 markdown 代码块。
12. 每一个得分点都要有明确判定依据；无参考答案时，先自拟得分点再逐点判定，并在总评中注明「要点为 AI 自拟，仅供参考」。
"""

GRADE_JSON_SPEC = """【输出格式】严格只输出一个 JSON 对象（不要 markdown 代码块、不要任何多余文字），字段如下：
{
  "score": 12.5,
  "level": "二类",
  "summary": "一句话总评，含所处档次与最大短板",
  "points": [
    {"name": "交通互联互通", "status": "命中", "score": 2, "full": 3,
     "evidence": "作答中对应的原句（缺失时写应来自材料/答案的哪一点）", "comment": "简短评语"}
  ],
  "dims": [
    {"name": "要点完整性", "score": 13, "comment": "评语"}
  ],
  "problems": ["主要问题1（先说问题再说后果）", "主要问题2"],
  "suggestions": ["可操作建议1", "可操作建议2"],
  "rewrite": {"original": "作答中最需改进的一段原文", "revised": "改写后的示范文字",
              "note": "改写说明：新增了什么、删改了什么"}
}
字段要求：
- score 为实际得分（数字，保留 0.5 精度，不得超过满分）；level 为档次（一类/二类/三类/四类，小题可写「踩点」）。
- points：5~10 条得分点，逐条判定；status 只能取「命中 / 部分命中 / 缺失」三者之一；full 为该点满分，score 为实际得分。
- points 的 name 必须是 4~10 字的**概括词**：优先直接用材料原词，或原词的直接拼接；禁止自创说法、禁止加序号（一、/1./①）、禁止带标点与书名号、禁止写成一句话；同一份批改里所有要点用同一粒度命名。步骤、理由、细节一律放进 comment，不要塞进 name。
- dims：四维评分，name 必须与下面给出的维度名称完全一致，score 为该维度得分。
- problems / suggestions 各 2~4 条；rewrite 必填（若整体已很好，选一段可润色的原文给出示范）。
- 所有字段都必须出现；无内容时用空字符串或空数组占位。"""

# 材料 / 参考答案的 prompt 截断上限（L2 提到 12000 / 6000：真题卷材料长、子项清单长）
MATERIAL_LIMIT = 12000
REFERENCE_LIMIT = 6000


def build_grade_messages(category: str, total: int, question: str, material: str,
                         answer: str, reference: str = "") -> list[dict]:
    """构造批改 2.0 的 messages（强制 JSON 输出）。

    reference 为空时走「AI 自拟要点」兜底。
    """
    r = RUBRICS.get(category)
    if not r:
        raise KeyError(category)
    dims = dims_for(category)
    dim_lines = "\n".join(
        f'  - {d["name"]}（权重 {d["weight"]}%）：{d["desc"]}' for d in dims)
    if (reference or "").strip():
        ref_block = (f"【参考答案 / 赋分标准（子项级采分点，逐条核对）】\n"
                     f"{reference.strip()[:REFERENCE_LIMIT]}\n\n"
                     "以上子项分值之和等于本题满分，逐条判定命中/部分命中/缺失，"
                     "不要增删子项，也不要自行改判分值。\n"
                     "输出时 points 的顺序与条数必须与上面子项一一对应；"
                     "每条 points 的 name 必须**逐字照抄**子项里「——」之前的概括词，"
                     "不得改写、缩略、补字或换一种说法。\n\n")
    else:
        ref_block = (
            "【参考答案】（考生未提供）\n"
            "请先根据题目与材料自行拟定 5~8 个得分点（AI 自拟要点），再逐点判断考生作答是否命中；"
            "并在 summary 中注明「要点为 AI 自拟，仅供参考」。\n\n")

    user = (
        f"请批改下面这份作答。题型：{r['name']}，满分 {total} 分。\n\n"
        f"【评分细则】\n{r['rubric']}\n\n"
        f"{GRADE_JSON_SPEC}\n\n"
        f"【本题四维评分维度（dims 的 name 须原样使用）】\n{dim_lines}\n"
        f"（四维得分之和应等于总分，允许 ±1 分误差。）\n\n"
        f"{ref_block}"
        f"【题目】\n{question.strip()[:3000]}\n\n"
    )
    if (material or "").strip():
        user += f"【给定材料】\n{material.strip()[:MATERIAL_LIMIT]}\n\n"
    else:
        user += ("【给定材料】（考生未提供，请基于题目与作答本身批改，"
                 "并在总评中注明缺材料可能影响要点判定）\n\n")
    user += f"【考生作答】\n{answer.strip()[:8000]}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT_JSON},
        {"role": "user", "content": user},
    ]


# ============================================================
# L4：双视角批改（小马哥 vs 白鹭），默认关闭
# ============================================================

# 两派差异定位（取自 Shenlun.skill writing-rules.md，只用可判定的差异）
DUAL_SCHOOLS = {
    "xiaoma": {
        "name": "小马哥",
        "style": ("概括词直接使用材料原词，不做近义提炼；语言更干更短，动词+宾语直接走，"
                  "条与条之间不加串联；结构上问题与建议融合在每条里。"),
    },
    "bailu": {
        "name": "白鹭",
        "style": ("概括词可从材料已有词汇中做近义提炼，但不得自创材料没有的词；"
                  "加少量轻串联使条与条之间更通顺；结构同样问题与建议融合，不另起炉灶。"),
    },
}

DUAL_DIFF_KEYS = ["points_gap", "classification", "scenarios", "risks", "verdict"]


def build_dual_messages(category: str, total: int, question: str, material: str,
                        answer: str, reference: str = "") -> dict[str, list[dict]]:
    """构造两组 messages：A 小马哥口径、B 白鹭口径（评分细则与四维维度完全一致）。"""
    base = build_grade_messages(category, total, question, material, answer, reference)
    out: dict[str, list[dict]] = {}
    for key, meta in DUAL_SCHOOLS.items():
        system = base[0]["content"] + (
            f"\n13. 本次按「{meta['name']}」一派的作答口径评：{meta['style']}"
            "只按该口径判断要点是否踩中与表达是否达标，不要混用另一派口径。\n")
        out[key] = [{"role": "system", "content": system}, dict(base[1])]
    return out


def _point_names(p: dict) -> list[str]:
    return [(x.get("name") or "").strip() for x in (p.get("points") or [])
            if (x.get("name") or "").strip()]


def build_dual_diff(pa: dict, pb: dict) -> dict:
    """由本地代码生成「差异对照五项」（不编造：无差异处直说一致）。

    pa 为小马哥口径结果，pb 为白鹭口径结果。
    """
    na, nb = _point_names(pa), _point_names(pb)
    sa, sb = set(na), set(nb)
    only_a = [n for n in na if n not in sb]
    only_b = [n for n in nb if n not in sa]
    shared = [n for n in na if n in sb]

    if not only_a and not only_b and len(na) == len(nb):
        classification = "两版要点集合与条数一致，分类逻辑无差异。"
    else:
        classification = (f"小马哥版 {len(na)} 条、白鹭版 {len(nb)} 条，"
                          f"共有 {len(shared)} 条；差异主要在要点取舍与条数，"
                          "分类层级本身两版同构（问题+建议融合在每条里）。")

    gap = {
        "only_xiaoma": only_a,
        "only_bailu": only_b,
        "shared": shared,
    }

    # ③④ 只在测得差异时给判断，否则直说一致（诚实边界）
    if only_a or only_b:
        scenarios = ("小马哥版适合：需要零自造词、按材料原词稳定踩点的场景；"
                     "白鹭版适合：表达偏流水账、需要近义提炼与轻串联提升通顺度的场景。")
        risks = {
            "xiaoma": "概括词全用原词，遇到材料表述冗长时语言偏硬，可能触发字数超限。",
            "bailu": "近义提炼有自创风险，提炼词一旦偏离材料原词会丢采分点。",
        }
        sa_score = float(pa.get("score") or 0)
        sb_score = float(pb.get("score") or 0)
        if abs(sa_score - sb_score) < 0.01:
            verdict = f"两版本次同分（{sa_score:g} 分），按你更顺手的口径练即可。"
        elif sa_score > sb_score:
            verdict = (f"本次小马哥版更高（{sa_score:g} vs {sb_score:g}），"
                       "建议先用小马哥口径把「材料原词踩点」练成条件反射。")
        else:
            verdict = (f"本次白鹭版更高（{sb_score:g} vs {sa_score:g}），"
                       "建议先用白鹭口径练近义提炼与条间串联。")
    else:
        scenarios = "两版本次要点与得分一致，适用场景无差异。"
        risks = {"xiaoma": "本次未见差异。", "bailu": "本次未见差异。"}
        verdict = "此处两版一致，无需二选一。"

    return {
        "points_gap": gap,
        "classification": classification,
        "scenarios": scenarios,
        "risks": risks,
        "verdict": verdict,
    }


def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_grade_json(raw: str) -> dict | None:
    """解析 AI 结构化批改 JSON，容错 markdown 代码块与前后杂字。

    解析失败返回 None（调用方走「纯文本批改」降级路径）。
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

    points: list[dict] = []
    for p in (data.get("points") or [])[:30]:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()[:60]
        if not name:
            continue
        points.append({
            "name": name,
            "status": normalize_status(p.get("status")),
            "score": round(_num(p.get("score")), 1),
            "full": round(_num(p.get("full")), 1),
            "evidence": str(p.get("evidence", "")).strip()[:200],
            "comment": str(p.get("comment", "")).strip()[:200],
        })

    dims: list[dict] = []
    for d in (data.get("dims") or [])[:8]:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name", "")).strip()[:30]
        if not name:
            continue
        dims.append({
            "name": name,
            "score": round(_num(d.get("score")), 1),
            "comment": str(d.get("comment", "")).strip()[:200],
        })

    rw = data.get("rewrite")
    if not isinstance(rw, dict):
        rw = {}
    rewrite = {
        "original": str(rw.get("original", "")).strip()[:1200],
        "revised": str(rw.get("revised", "")).strip()[:2000],
        "note": str(rw.get("note", "")).strip()[:300],
    }

    problems = [str(x).strip()[:300] for x in (data.get("problems") or [])[:6]
                if str(x).strip()]
    suggestions = [str(x).strip()[:300] for x in (data.get("suggestions") or [])[:6]
                   if str(x).strip()]

    score = _num(data.get("score"), -1.0)
    if score < 0 and not points and not dims:
        return None

    return {
        "score": round(score, 1) if score >= 0 else 0.0,
        "level": str(data.get("level", "")).strip()[:20],
        "summary": str(data.get("summary", "")).strip()[:500],
        "points": points,
        "dims": dims,
        "problems": problems,
        "suggestions": suggestions,
        "rewrite": rewrite,
    }


def enrich_dims(p: dict, category: str, total: int) -> None:
    """按题型预设补齐 dims 的满分（full）并统一顺序（原地修改）。

    AI 只返回各维度得分，满分由后端按权重算出，避免模型算错。
    AI 未返回任何维度时不做处理。
    """
    got = {d.get("name", ""): d for d in (p.get("dims") or [])}
    if not got:
        return
    out: list[dict] = []
    for d in dims_for(category):
        full = round(total * d["weight"] / 100, 1)
        g = got.get(d["name"])
        if g is None:                       # 名称微调时模糊匹配
            g = next((v for k, v in got.items()
                      if k and (k in d["name"] or d["name"] in k)), None)
        out.append({
            "name": d["name"],
            "full": full,
            "score": round(min(full, max(0.0, _num((g or {}).get("score")))), 1),
            "comment": (g or {}).get("comment", ""),
        })
    p["dims"] = out


def render_grade_markdown(p: dict, total: int) -> str:
    """把结构化批改结果渲染成 Markdown（用于历史记录展示 / 降级兜底）。"""
    out = [f"## 总分：{_num(p.get('score')):g} / {total}分"]
    lv = (p.get("level") or "").strip()
    sm = (p.get("summary") or "").strip()
    if lv or sm:
        out.append(f"（{lv + ' · ' if lv else ''}{sm}）")

    if p.get("points"):
        out += ["", "## 要点命中表",
                "| 得分点 | 状态 | 得分 | 满分 | 评语 |", "|---|---|---|---|---|"]
        for pt in p["points"]:
            note = (pt.get("comment") or pt.get("evidence") or "").replace("|", "｜")
            out.append("| {} | {} {} | {} | {} | {} |".format(
                (pt.get("name") or "").replace("|", "｜"),
                _STATUS_ICON.get(pt.get("status"), ""), pt.get("status", ""),
                f"{_num(pt.get('score')):g}", f"{_num(pt.get('full')):g}",
                note.replace("\n", " ")))

    if p.get("dims"):
        out += ["", "## 四维评分", "| 维度 | 得分 | 满分 | 评语 |", "|---|---|---|---|"]
        for d in p["dims"]:
            out.append("| {} | {} | {} | {} |".format(
                (d.get("name") or "").replace("|", "｜"),
                f"{_num(d.get('score')):g}",
                f"{_num(d.get('full')):g}",
                (d.get("comment") or "").replace("|", "｜").replace("\n", " ")))

    if p.get("problems"):
        out += ["", "## 主要问题"] + [f"{i}. {x}" for i, x in enumerate(p["problems"], 1)]
    if p.get("suggestions"):
        out += ["", "## 修改建议"] + [f"{i}. {x}" for i, x in enumerate(p["suggestions"], 1)]

    rw = p.get("rewrite") or {}
    if rw.get("revised"):
        out += ["", "## 修改示范", f"**原文**：{rw.get('original', '')}", "",
                f"**改写**：{rw.get('revised', '')}"]
        if rw.get("note"):
            out.append(f"> {rw['note']}")
    return "\n".join(out)
