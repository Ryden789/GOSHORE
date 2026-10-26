# data/real_exams —— 申论真题采分点库

本地真题索引 + 子项级采分点。批改时命中高置信度真题，就用这里固定的子项清单
代替模型自拟要点，分数才稳定（见 `docs/03-开发/2026-10-26-申论评分接入ShenlunSkill方案.md`）。

## 文件结构

```
INDEX.json         # 索引：{version, items:[{exam_id, exam_full_name, sheet_type, keywords}]}
<exam_id>.json     # 单套卷：题目 + 子项级采分点
```

单套卷 schema：

```json
{
  "exam_id": "2024-GX-A",
  "exam_full_name": "2024年广西公务员考试申论A卷（2024多省联考）",
  "year": 2024,
  "sheet_type": "A卷",
  "total_questions": 4,
  "overall_theme": "……",
  "keywords": ["传统", "现代"],
  "questions": [{
    "q_no": 1, "category": "sl_guina", "full_score": 15,
    "question_text": "原题逐字录入（含「要求」）",
    "material_digest": "材料概要 2–3 句",
    "points": [{"name": "采分点", "full": 4, "evidence": "材料出处", "source": "出处说明"}]
  }]
}
```

## 硬性校验（`app/exam_bank.py` 加载时执行，不合规直接拒载）

1. `Σ points.full` 必须**精确等于** `full_score`（差 0.5 分都不收）；
2. `name` / `evidence` / `source` 不能为空，也不能是「待补充」这类占位符；
3. `source` **禁止**写「官方标准答案」——本项目手上的是机构拆解版；
4. `exam_id` 全局唯一且必须已登记在 `INDEX.json`；
5. `category` 必须存在于 `essay_rubric.RUBRICS`。

## 数据来源与口径

- 入库素材：`D:\人文\Shenlun.skill`（MIT，见 `docs/03-开发/third-party/shenlun-skill-LICENSE`）
  的 `skills/shenlun-xiaoti/references/real-exams/*.md`，逐题抄录题干与阅卷采分点；
- `source` 统一写「机构答案拆解（Shenlun.skill real-exams/<file>.md）」；
- **只录采分点齐全的题**：源文件里标 `[待补充]` 的题不入库（校验也会拒收），
  因此部分卷只含 1–2 道题，但 `total_questions` 仍按整卷题数填写；
- `evidence` 只写到「材料X｜主题（关键细节）」这一层：源文件给的是材料概要，
  不是逐字原文，**不编造「第几段第几句」**；
- 分值校准：源文件有 3 套题的子项之和与满分不闭合（22 vs 20、14 vs 15），
  按满分等比校准并在该点 `source` 里写明原始分值与校准后的数值，方便复核。

## 如何新增一套卷

1. 在 `INDEX.json` 的 `items` 里登记 `exam_id / exam_full_name / sheet_type / keywords`
   （`keywords` 取地名、机构名、专有名词等**有区分度**的词，3 个以上重叠才算高置信）；
2. 新建 `<exam_id>.json`，逐题录入；分值对不上就校准并写进 `source`；
3. 在仓库根跑 `python -c "from app import exam_bank; exam_bank.clear_cache(); print(exam_bank.all_exams())"`，
   能打印出全部卷即通过校验；
4. `python -m pytest tests/test_exam_bank.py -q`。

## 目录优先级（`app/exam_bank.py: exams_dir()`）

1. `GOSHORE_EXAM_DIR` 环境变量（便携部署 / 测试）；
2. 用户数据目录 `DATA_DIR/real_exams`（源码运行即本目录；桌面冻结版是
   `%LOCALAPPDATA%\GOSHORE\data\real_exams`）——**只要它里面有 `INDEX.json` 就整份用它**；
3. 打包内置副本 `BUNDLE_DIR/data/real_exams`（桌面版由 `tools/build_desktop_exe.py`
   以 `--add-data` 打进 exe）。

桌面版新装用户没有第 2 项的目录，靠第 3 项才有真题可用；想换上自己的卷子，
在用户数据目录建 `real_exams/` 并放一份完整的 `INDEX.json` + `<exam_id>.json` 即可，内置副本不会被改动。
