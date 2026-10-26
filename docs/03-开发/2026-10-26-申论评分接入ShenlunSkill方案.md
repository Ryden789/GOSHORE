# 2026-10-26 申论评分接入 Shenlun Skill —— 详细设计

> 状态：已实施（L1–L3 上线，L4 骨架待接入；落地差异与实测见第十一节）
> 目标读者：执行本任务的开发者（含能力较弱的模型，本文所有改动点均给出文件、函数、行号、可直接粘贴的文本）
> 前置：`D:\GOSHORE` 为工作副本；`D:\人文\Shenlun.skill` 为方法论来源（MIT 协议）

---

## 一、背景与目标

### 1.1 现状问题

当前 AI 批改链路（`app/main.py` L2452 `api_essay_grade`）：

```
RUBRICS[category].rubric  →  build_grade_messages()  →  DeepSeek 单次调用  →  parse_grade_json()  →  enrich_dims()  →  render_grade_markdown()
```

存在的三个精度问题：

| 编号 | 问题 | 后果 |
|---|---|---|
| P1 | 评分细则只有 200–400 字通用规则，无「踩点三档折算」的量化口径 | 同一篇答案两次批改分数漂移 3–5 分 |
| P2 | 无真题子项采分点，默认走「AI 自拟要点」 | 每次自拟的要点名不同，评分不可复现、不可横向对比 |
| P3 | 材料上限 8000 字（`build_grade_messages` L319） | 国考卷材料常超 8000 字，截尾直接漏后段要点 |

### 1.2 目标（可量化验收）

- **G1 可复现**：同一题目 + 同一作答，连续批改 3 次，总分标准差 ≤ 1.5 分（当前目测 3–5 分）
- **G2 可解释**：每个得分点必须带材料出处，`evidence` 非空率 ≥ 95%
- **G3 不出圈**：`score` 越界、`status` 非三态、`dims` 缺失等契约违规为 0（由 `app/ai_eval.py` 现有 golden 机制守）
- **G4 特色**：命中真题库时，评分基于固定子项清单，可对外宣称「同答案同考卷评分可复现」

### 1.3 非目标

- 不做多轮追问式批改（软件是单次提交 → 出报告，交互式能力留在对话侧）
- 不把 `Shenlun.skill` 的白鹭（18.3KB）/小马哥（17.9KB）方法论全文塞进 prompt
- 不改前端 UI 结构（仅在批改结果区增加「采分点来源：真题库 / AI 自拟」标识）

---

## 二、方案总览

四层递进，**每层独立可交付、可回滚**：

| 层 | 内容 | 触碰文件 | 预估工时 | 依赖 |
|---|---|---|---|---|
| **L1** | 评分规则口径升级（纯字符串） | `app/essay_rubric.py` | 0.5 天 | 无 |
| **L2** | 真题采分点库 + 匹配接入 | 新增 `app/exam_bank.py`、新增 `data/real_exams/`、`app/main.py` 1 处分支、`app/essay_rubric.py` 截断上限 | 1 天 | L1 |
| **L3** | 失分点 → 错因 → 艾宾浩斯闭环 | `app/main.py` 1 处写入、`app/db.py` 视现有错因表决定 | 0.5 天 | L2 |
| **L4** | 双视角批改（小马哥版 + 白鹭版） | 新增 prompt 变体 + 开关 | 1 天 | L2 |

**交付顺序固定为 L1 → L2 → L3 →（L4 可选）**，每层完成后跑一次回归，未通过不进下一层。

---

## 三、L1：评分规则口径升级

### 3.1 来源

从 `D:\人文\Shenlun.skill\skills\shenlun-xiaoti\references\` 蒸馏，**只抄可判定的硬规则，丢掉叙述性内容**：

| 源文件 | 提取内容 |
|---|---|
| `scoring-rules.md` | 采分点覆盖法三档折算、编造不得分不倒扣、口语化不单独扣分 |
| `writing-rules.md` | 概括词必须来自材料、答案不写非得分句、字数/句式纪律 |
| `bai-lu-methodology.md` 第八节 | 差异对照五项（L4 用，L1 暂不接） |
| `xiaoma-methodology.md` | 结构逻辑（L4 用，L1 暂不接） |

### 3.2 改动点 A：`SYSTEM_PROMPT` 增补硬规则

文件：`app/essay_rubric.py` L139–147

在现有「批改原则 1–4」之后追加第 5–10 条，**逐字使用**：

```
5. 采分点三档折算（硬规则，不得自行发挥）：
   - 命中 ≥80% 该点要素 → 给该点满分
   - 命中 40%~80% → 给该点一半分
   - 命中 <40% → 该点 0 分
6. 采分点关键词必须来自给定材料或参考答案，禁止自创概括词；考生用口语改写但语义到位，按「按意赋分」给分，不因口语化单独扣分。
7. 考生写了材料与参考答案之外的合理内容：不得分，但**不额外倒扣**（申论是加分制，不存在扣分制）。
8. 不做错别字检查，不做卷面/字迹评价；只评价内容与结构。
9. 每一条 points 的 evidence 必须写清「出自材料第几段/哪句话」或「作答中对应的原句」，禁止空泛写「论述不到位」。
10. 若题目所属考试类型未明确，按「国考地市级」口径评分，不得套用事业单位综应口径。
```

### 3.3 改动点 B：五段 rubric 内容替换

文件：`app/essay_rubric.py` L15–137 的 `RUBRICS` 字典。**保留全部 key（`sl_guina` / `sl_fenxi` / `sl_duice` / `sl_yingyongwen` / `sl_dazuowen` / `zy_*`），保留 `default_score` 与 `hint` 不变，只重写 `rubric` 字符串。**

每段 rubric 必须包含且仅包含四个小节（便于模型定位）：

```
【评分方式】踩点给分 / 结构分+要点分 / 按档给分（三选一，与题型匹配）
【给分规则】N 条，每条可判定、可对照，不得出现"酌情""适当"等模糊词
【硬性扣分】仅列公认项（无标题、字数不足、通篇提纲），无则不写
【批改重点】1–2 句，指向本题型最易失分处
```

以 `sl_guina` 为样板（替换原 L19–26 的 rubric 值）：

```
【评分方式】踩点给分。满分按 default_score，要点 5–10 个，每点 1–3 分。
【给分规则】
1. 要点全面是核心：多踩一个有效关键词多得分，漏点即失分，宁多勿漏。
2. 按词赋分与按意赋分并存：材料表述规范时用原词给分；材料为案例/数据时按意思一致给分。
3. 三档折算：命中≥80% 给满分；40%~80% 给一半；<40% 给 0。
4. 审题偏差直接不得分：问经验答问题、问做法答原因、问国内答国外。
5. 概括词必须来自材料，自创概括词不认；口语化改写但语义到位按意给分，不单独扣分。
6. 条理：须分条标序号；题干要求"概括性强/观点明确"时核心词须前置，未前置扣 1–2 分；要求"分类合理"时未归类扣 2–3 分。
7. 语言：抄整句、罗列数据案例、超字数，扣 1–2 分。
【硬性扣分】超字数按超出比例扣 1–2 分；未分条作答扣 1 分。
【批改重点】先查要点数是否够（<5 个基本不可能拿高分），再查是否有总括词前置。
```

其余四段按同一结构重写，规则取自 `references/scoring-rules.md` 对应章节与现有 rubric 的公认项，**不引入任何来源不明的条款**。

### 3.4 L1 验收

```powershell
cd D:\GOSHORE
python -m pytest tests/test_essay_grade.py -q
python -m pytest tests/test_api.py -q
python scripts/eval_ai.py            # 离线 golden，门槛 95
```

三条全绿才算完成。额外人工验证：用同一道归纳概括题、同一份答案连续批改 3 次，记录总分，标准差须 ≤1.5（未达则回到 3.2 强化第 5 条措辞）。

---

## 四、L2：真题采分点库

### 4.1 目录与文件格式

新增目录：

```
data/real_exams/
├── INDEX.json                 # 匹配索引
├── 2024-guokao-dishiji.json   # 一整套卷 = 一个文件，内含多题
└── ...
```

**单套卷文件结构**（严格按此 schema，字段缺失即校验失败）：

```json
{
  "exam_id": "2024-GK-DSJ",
  "exam_full_name": "2024年国家公务员考试申论（地市级）",
  "year": 2024,
  "sheet_type": "地市级",
  "total_questions": 5,
  "overall_theme": "一句话概括全卷主题",
  "keywords": ["关键词1", "关键词2"],
  "questions": [
    {
      "q_no": 1,
      "category": "sl_guina",
      "full_score": 15,
      "question_text": "原题题干，逐字录入，不改写",
      "material_digest": "材料概要，2-3 句",
      "points": [
        {
          "name": "子项名（来自材料原词）",
          "full": 3,
          "evidence": "材料出处（第几段哪句话）",
          "source": "机构答案拆解"
        }
      ]
    }
  ]
}
```

**硬性校验（在 `exam_bank.py` 载入时执行，不通过直接抛错拒载）**：

1. `Σ points[].full == questions[].full_score`（允许 ±0）
2. 每个 `points[].name` 非空且非「待补充」
3. `source` 必须标明来源，**禁止标成「官方标准答案」**（国考不公布标准答案）
4. `exam_id` 全局唯一，且与 `INDEX.json` 中登记一致

### 4.2 `INDEX.json` 结构

```json
{
  "version": 1,
  "items": [
    {
      "exam_id": "2024-GK-DSJ",
      "exam_full_name": "2024年国家公务员考试申论（地市级）",
      "sheet_type": "地市级",
      "keywords": ["传统", "现代", "城乡融合", "..."]
    }
  ]
}
```

### 4.3 匹配算法

新增 `app/exam_bank.py`，对外三个函数：

```python
def load_index() -> dict            # 读取 data/real_exams/INDEX.json，进程内缓存（lru_cache）
def match(question: str, material: str = "") -> dict | None
    # 关键词交集法：
    #   1. 从 question + material[:2000] 中提取关键词（与 INDEX 各条目 keywords 做交集计数）
    #   2. 交集 ≥3 → 返回 {exam_id, q_no, confidence: "high"}
    #   3. 交集 1–2 → 返回 {exam_id, q_no, confidence: "medium"}
    #   4. 交集 0 → 返回 None
def get_question(exam_id: str, q_no: int | None = None) -> dict | None
    # q_no 为空时按题干相似度在套卷内选题
def build_reference(exam_id: str, q_no: int) -> str
    # 把 points 渲染成 build_grade_messages 可用的 reference 文本，格式：
    #   "1. {name} —— {full}分（材料出处：{evidence}）\n2. ..."
```

匹配阈值（`≥3` / `1–2`）与 `Shenlun.skill` 的 `real-exams/INDEX.md` 规则保持一致，便于日后合并数据。

### 4.4 `app/main.py` 接入点

文件：`app/main.py` L2452–2463

在 `build_grade_messages` 调用**之前**插入真题库查询，`b.reference` 非空时以用户传入为准（不覆盖）：

```python
ref_text = (b.reference or "").strip()
ref_origin = "user" if ref_text else ""
if not ref_text:
    hit = exam_bank.match(b.question, b.material)
    if hit and hit["confidence"] == "high":
        ref_text = exam_bank.build_reference(hit["exam_id"], hit["q_no"])
        ref_origin = "exam_bank"

messages = essay_rubric.build_grade_messages(
    b.category, total, b.question, b.material, b.answer, ref_text)
```

在末端 SSE 结果中追加一个字段（前端可选展示，不展示也不报错）：

```python
yield _sse({"type": "result", "data": parsed, "total": total,
            "reference_origin": ref_origin or "ai_generated"})
```

### 4.5 材料截断上限

文件：`app/essay_rubric.py` L319

```python
# 原：material.strip()[:8000]
# 改：
material.strip()[:12000]
```

同步把 L302 的参考答案截断 `[:4000]` 提到 `[:6000]`（真题子项清单会更长）。

### 4.6 L2 验收

1. 构造 3 条用例：命中真题（高置信）、部分命中（中置信）、完全不命中 → 分别验证 `ref_origin` 为 `exam_bank` / `ai_generated` / `ai_generated`
2. 命中真题时批改 3 次，`points[].name` 三次重复率 ≥70%、总分标准差 ≤1.5
3. 未命中时行为与改造前完全一致（回归对比日志）
4. `python -m pytest tests/ -q` 全绿

---

## 五、L3：失分点 → 错因 → 复习闭环

### 5.1 映射表

`points[].status == "缺失" / "部分命中"` 的项，按类型映射到现有错因体系（`category` 决定默认错因，可在前端二次修改）：

| category | 默认错因类型 |
|---|---|
| `sl_guina` / `zy_wenxian` | 要点遗漏 |
| `sl_fenxi` | 结构缺失（缺总括句/缺环节） |
| `sl_duice` | 对策不可操作 |
| `sl_yingyongwen` | 格式失分 |
| `sl_dazuowen` / `zy_zuowen` | 立意偏差 / 论证单薄（按 `dims` 最低分项判定） |

### 5.2 写入

在 `api_essay_grade` 的 `db.save_essay_grade` 之后追加：

- 每条缺失/部分命中的 point 生成一条复习任务，来源标记 `essay_grade:{gid}`
- 去重键：`(category, point_name)`，同名累计 ≥2 次则在错题库标「反复错」

**这一步必须先确认 `app/db.py` 现有错因/复习表结构**（已有错题错因与艾宾浩斯排期能力，优先复用，不新建表）。若结构不匹配，先在本文件追加差异说明再动手，不允许另起一套。

### 5.3 L3 验收

批改一次后，错题本新增条目数与 `points` 中缺失项数一致；复习驾驶舱能看到该条目并带来源标记。

---

## 六、L4：双视角批改（可选，默认关闭）

### 6.1 做法

新增 `essay_rubric.build_dual_messages()`，返回两组 messages：

- A 组：小马哥口径（结构固定、要素融合：一律「上位概括词 + 具体做法」）
- B 组：白鹭口径（结构随题干、要素分栏：题干有几个要素就分几栏）

两次调用各自产出 `points`，再由本地代码生成「差异对照五项」：①各自多踩/漏了哪个点 ②分类逻辑差异 ③适用场景 ④各自风险 ⑤落点（用户更适合哪套）。

### 6.2 成本与开关

- 调用次数 ×2，延迟约 ×2
- 设置项 `dual_grade_enabled`，**默认 false**；开启时前端显示「双视角」标识
- 诚实边界：某些环节两版不分歧（如总括句有无），必须直说「此处两版一致」，不得为凑对照编造差异

---

## 七、数据生产流程（关键，决定库能不能长大）

### 7.1 红线

- **国考不公布标准答案**，所有子项采分点均为机构答案拆解，`source` 字段必须标明
- **不得凭印象填充**：材料原文没拿到就不建该题记录，宁可留空
- `name` 必须是材料原词，禁止自造概括词

### 7.2 单题入库步骤（每题约 15–25 分钟）

1. 拿到整套卷原文（PDF/Word/图片）→ 用 `_tools/docx_extract.py` 或图片识读转文字
2. 逐字录入 `question_text`，不改写、不省略
3. 按材料段落拆 5–10 个子项，每项写 `name` + `full` 分值 + `evidence`（材料出处）
4. 校验 `Σ full == full_score`
5. 在 `INDEX.json` 登记该卷的 `keywords`（写全主题词，宁可多写）

### 7.3 冷启动顺序（不建议一次性建库）

按「边练边沉淀」执行：每完整做一套国考卷，就把该卷入库。国考地市级 2021–2026 共 6 套、小题约 24 题，会在 6 次训练中自然攒齐。

---

## 八、回归与评测

### 8.1 必跑命令

```powershell
cd D:\GOSHORE
python -m pytest tests/test_essay_grade.py tests/test_api.py -q
python -m pytest tests/ -q
python scripts/eval_ai.py               # 离线，门槛 95
python -m app.ai_eval --live            # 可选，需 DeepSeek Key，真实调用
```

### 8.2 新增评测用例

在 `tests/golden/ai_golden.jsonl` 追加 `feature: "essay_grade"` 用例，覆盖：

1. 命中真题库的正常输出
2. 未命中（AI 自拟）的正常输出
3. 坏输出：`points` 为空数组（期望被契约校验拦下）
4. 坏输出：`status` 写成「未命中」（期望 `normalize_status` 归一为「缺失」）
5. 坏输出：`score` 超过满分（期望 `api_essay_grade` L2478 的钳制生效）

### 8.3 一致性评测（本方案的特色指标）

写一个一次性脚本 `scripts/eval_grade_consistency.py`：

- 输入：1 道题 + 1 份作答
- 动作：连续批改 3 次
- 输出：`score` 均值/标准差、`points[].name` 集合两两 Jaccard 相似度
- 门槛：标准差 ≤1.5 且 Jaccard ≥0.7

该脚本的产出可直接写进 README 作为「可复现评分」的证据。

---

## 九、风险与回滚

| 风险 | 处置 |
|---|---|
| 改 rubric 后模型行为漂移，分数整体偏低/偏高 | 每层改完先跑 8.1，对比改造前后同一批答案的分数分布；偏移 >3 分则回滚该层 |
| 真题库数据不可信污染评分 | `source` 字段强制 + 载入校验（4.1 硬性校验 1–4）；无来源不入库 |
| 材料提到 12000 字后 token 成本上升 | 仅在命中真题库或材料确实超长时触发；监控单次批改 token 数，超预算则改分段摘要 |
| `Shenlun.skill` 为 MIT，需保留声明 | 在 `NOTICE.md` 追加：本项目的申论评分规则参考自 coffe-d/Shenlun.skill（MIT），并保留其 LICENSE 副本至 `docs/03-开发/third-party/shenlun-skill-LICENSE` |
| L3 与现有 db 结构冲突 | 先勘察 `app/db.py` 错因/复习表，强制复用；不匹配则停工重新设计，不并行维护两套 |

---

## 十、实施顺序（工时合计约 2 天，L4 另计 1 天）

1. **L1**（0.5 天）：改 `SYSTEM_PROMPT` 6 条 + 五段 rubric → 跑 8.1 → 人工一致性抽查
2. **L2**（1 天）：建 `app/exam_bank.py` + 目录与 schema + `INDEX.json` + `main.py` 分支 + 截断上限 → 跑 8.1
3. **样例入库**（0.5 天，可与 L2 并行）：先入 1 套国考卷的第 1 题，跑通端到端
4. **L3**（0.5 天）：勘察 db → 接入错因 → 验证复习驾驶舱
5. **L4**（可选 1 天）：双视角开关

**最终交付判定**：G1–G4 四项指标全部达标，且 `pytest` 与离线 golden 全绿。

---

## 十一、实施记录（2026-10-26）

> 状态：L1 / L2 / L3 已落地，L4 代码骨架已就位但未接入端点（默认关闭）。

### 11.1 与设计不一致之处（差异说明）

| 设计原文 | 实际落地 | 原因 |
|---|---|---|
| L3「先勘察 db 的错因/复习表，强制复用，不匹配则停工重新设计」 | **新建** `essay_weak_points` 表，不复用 `review_plan` / `wrong_reasons` | 勘察确认这两张表都以 `doc_id INTEGER PRIMARY KEY` 关联 `documents`（行测题库）；申论得分点没有 document 行，硬复用会让 `due_reviews()` 的 `JOIN documents` 打空、复习驾驶舱永远看不到申论失分点。按设计要求先停工核对，确认结构不匹配后才新建，并在 `app/db.py` 建表处写明理由 |
| L2 材料截断 8000→12000、参考答案 4000→6000 | 已按设计改成常量 `MATERIAL_LIMIT=12000` / `REFERENCE_LIMIT=6000` | 无差异 |
| L2「`match` 关键词交集 ≥3 高置信」 | 增加题面相似度二次校验（difflib ≥0.45）与题型约束（传 `category` 时只匹配同题型） | 只靠关键词会把「同样提到 Q市/数字化」的不同题认成同一题，误用别题子项清单比不用更糟 |
| 8.2「points 空数组（期望契约拦下）」 | 保持 `parse_grade_json` 不因 `points: []` 返回 `None`，改由 golden 用例 `essay-010` 的「得分点 5~10 条」检查检出 | 解析层拒收会把「模型给了四维、只是漏了要点表」也降级成纯文本，用户反而看不到四维分；有缺陷就让评测把他抓出来 |
| L2 采点数据「9 题」 | 实际入库 4 套卷 9 题；其中 2023-FJ-XIANXIANG Q1、2023-SC-SHI Q1 的源文件子项和与满分不符，已等比校准并在 `source` 写明 | 上游 real-exams 是人工整理稿，存在 14≠15、22≠20 的算术不一致；不校准会直接触发硬校验拒载 |

### 11.2 G1–G4 实测

| 目标 | 结果 | 取证方式 |
|---|---|---|
| G1 连批 3 次总分标准差 ≤1.5 | **0.00**（6/6/6 分） | `python scripts/eval_grade_consistency.py`（命中真题库路径） |
| G1 附加：要点名称 Jaccard ≥0.7 | **1.00**（5 条子项名称逐次一致） | 同上。为此在参考答案块加了「name 必须逐字照抄子项概括词」的硬约束 |
| G1（AI 自拟路径） | 标准差 0.00，但 Jaccard 仅 0.20 | `--no-bank` 复测：无固定子项时模型每次自拟的概括词不同。**结论：稳定性来自真题库，不是 prompt** |
| G2 evidence 非空率 ≥95% | 已加入离线评测检查（`essay-012` 60% → 被检出） | `python scripts/eval_ai.py` |
| G3 契约违规 0 | 38/38 golden 通过，100.00 | 同上 |
| G4 命中真题库时固定子项清单 | 命中即固定 5 条、满分按题库校准 | `tests/test_essay_grade.py::test_grade_endpoint_uses_bank_points_and_reports_origin` |

### 11.3 新增/改动文件清单

- 新增：`app/exam_bank.py`、`data/real_exams/`（`INDEX.json` + 4 套卷 + `_README.md`）、
  `tests/test_exam_bank.py`、`scripts/eval_grade_consistency.py`、`scripts/_add_essay_golden.py`、
  `docs/03-开发/third-party/shenlun-skill-LICENSE`
- 改动：`app/essay_rubric.py`（rubric 重写 + 6 条硬规则 + 截断常量 + L4 骨架）、
  `app/main.py`（`resolve_grade_reference` + `/api/essay/weak` + 落库后记录失分点）、
  `app/db.py`（`essay_weak_points` 表及 4 个函数）、`app/ai_eval.py`（G2 检查）、
  `static/app.js` 与 `static/m/m.js`（「采分点来源」一行）、`tests/golden/ai_golden.jsonl`（+5 条）、
  `NOTICE.md`（第三方声明）、`README.md`（综应专区条目 + 备份清单加 `real_exams/`）、
  `static/index.html` / `static/m/index.html` / `static/sw.js`（前端缓存号升版）、
  `tools/build_desktop_exe.py`（`--add-data data/real_exams`，否则冻结版永远空转）

### 11.3.1 冻结版的一处坑：内置副本

桌面版发的是「一个 exe + 可选的 data/」，新用户机器上没有 `DATA_DIR/real_exams`。若 `exams_dir()`
只认 `DATA_DIR`，真题库在冻结版里就是永久空转 —— 功能代码全在，用户却始终走 AI 自拟。
现在 `exams_dir()` 的优先级是 `GOSHORE_EXAM_DIR` → `DATA_DIR/real_exams`（有 `INDEX.json` 才用）
→ `BUNDLE_DIR/data/real_exams` 内置副本；构建脚本把 `data/real_exams` 以 `--add-data` 打进 exe。
三条路径各有一条单测（`tests/test_exam_bank.py::test_exams_dir_*`）。

### 11.3.2 L3 验收口径的落点

设计 5.3 要求「复习驾驶舱能看到该条目并带来源标记」。落地方式是**不动** `review_dashboard()`
的 SQL，而是在 `/api/review/dashboard` 的响应里加一块 `essay_weak = {summary, items}`，
桌面端「今日复习」页在驾驶舱面板里多一块「申论失分点」（条数 / 今日到期 / 反复错 + 前 6 条
`失分点 · 错因 · 缺 N 次`），移动端在同一张卡片里列前 5 条。

为什么不在 `review_plan` 里混排：那张表的每一行都必须能 `JOIN documents` 回原题，申论失分点
没有 document 行，混进去会让 `due_reviews()` 整段打空。所以是「同一页两个数据源」，而不是一张表。

`items[].source` 形如 `essay_grade:123`（来源批改记录 id），`items[].reason` 是 5.1 的错因映射结果，
`miss_count >= 2` 即标「反复错」。

### 11.4 有意未做 / 待接线

| 项 | 现状 | 说明 |
|---|---|---|
| L4 双视角评分的**端点与前端** | 只有纯函数 `build_dual_messages` / `build_dual_diff` + 2 条单测 | 设计把 L4 标为「可选、默认关闭」，且非目标写明「不改前端 UI 结构」。现在接端点会带出一块无 UI 的死开关；等真要上双视角时，再加 `dual_grade_enabled` 设置项 + `result` 事件的 `dual` 字段 + 差异对照卡片，纯函数可直接复用 |
| 历史批改记录的「采分点来源」 | 不展示 | `reference_origin` 只在当次 SSE `result` 事件里返回，`essay_grades` 表没存这个字段；要支持历史回看得加列 + 迁移，当前收益不抵成本 |
| 真题库的**逐字材料原文** | `evidence` 只写到「材料/段落主题」级 | 上游 real-exams 只给材料概要，没有逐字原文；编造「第几段第几句」等于给假证据 |

### 11.5 发布注意

前端资源有改（`static/app.js`、`static/m/m.js`），已按 `static/sw.js` 顶部发布约定同步升级缓存号：
`VERSION` 改为 `goshore-20261101-grade1`，桌面 `static/index.html` 与移动 `static/m/index.html` 里
**全部** `?v=` 一并统一成 `20261101-grade1`。注意 `tests/test_time_analysis.py::test_cache_version_bumped`
要求两端的 `?v=YYYYMMDD` 只允许**一个**日期号且与 `sw.js` 的 `goshore-YYYYMMDD` 相等——只改 `app.js`
一行会直接把这个回归测试打红（第一次就是这样挂的）。漏改则老用户继续跑 Service Worker 缓存里的旧 JS，
界面上看不到「采分点来源」那一行。

### 11.6 本地冒烟（不进 CI）

`scripts/_smoke_weak_ui.py`（`scripts/_*.py` 已在 `.gitignore`，属一次性工具）：
建临时库 → 塞 3 条失分点 → 起 8899 → Playwright 截「今日复习」的驾驶舱卡片（桌面 1280px +
移动 390px），断言页面文本里有「申论失分点」与具体考点名。产物在 `.smoke/`（已忽略）。

踩过的两个坑：

1. **不能用 `GOSHORE_DATA_DIR` 隔离数据**：`app/config.py::_resolve_data_dir` 只在冻结版读它，
   源码运行时会被忽略 —— 冒烟数据直接写进了真实的 `data/user.db`（已清理）。正确做法是像
   `tests/conftest.py::_isolate_split_paths` 那样改 `db.DB_PATH/CONTENT_DB_PATH/USER_DB_PATH`。
   另外本机 `data/` 已是拆分库模式（`user.db` + `content.db`），只改 `DB_PATH` 会读到真实个人库。
2. **空库首次启动要几十秒**（自检 + 迁移 + 灌示例题库），等 10 秒就判「服务没起来」是假阴性。
3. 第一次的 UI 版本用 `review-bar-row` 装长文案，`<small>` 被挤成竖排 —— 长文本行不要复用那种
   flex 三栏样式，改用 `flex + white-space:nowrap` 的普通行。


