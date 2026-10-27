# 开源项目可借鉴内容评估：ERRRC/kaogong-shuati

> 评估日期：2026-10-27
> 评估对象：https://github.com/ERRRC/kaogong-shuati
> 评估目的：为 GOSHORE 的功能补齐与毕业设计选题提供参考

---

## 一、仓库概况

| 项 | 值 |
|---|---|
| 仓库地址 | https://github.com/ERRRC/kaogong-shuati |
| 项目描述 | 考公刷题 App（公考/国考/省考/事业单位）：行测 申论 题库 · 错题本 · AI 解析。中文名「没钱考什么公」 |
| Star / Fork | 123 / 26 |
| 许可 | MIT |
| 主要语言 | JavaScript |
| 创建 / 最后推送 | 2026-08-29 / 2026-09-24（已停止更新） |
| 仓库规模 | 9425 个文件，716 MB |
| 顶层结构 | `public/`（8802）、`ref-skills/`（265）、`skills/`（164）、`app/`（58）、`docs/`（29）、`lib/`（6） |

本地相关资源：`d:\人文\kaogongzhentizhengliu\`（考公脑库 · Obsidian 端，22,375 篇笔记，含资料分析 3,569 题、判断推理 7,713 题、考点 MOC 10,375 篇、配图 21,829 张）。

---

## 二、可借鉴内容（按价值排序）

### ⭐A. 申论 Skill 的契约化实现（最高价值）

路径：`skills/shenlun-review-pro/shenlun-review-skill/`

```
SKILL.md (10KB)
references/
  analysis-core.md (21.5KB)          分析内核
  explanation-core.md (7.4KB)        讲解内核
  input-boundary.md (9.4KB)          输入边界约束
  contracts/
    scoring-result.schema.json (12.4KB)      评分结果结构
    score-ledger.schema.json (6.5KB)         分数账簿
    reference-answer-set.schema.json (4.3KB) 参考答案集
    scoring-input.schema.json (15.9KB)       评分输入
    learning-state.schema.json (1.7KB)       学习状态
    method-card.schema.json (3.1KB)          方法卡
    draft-comparison.schema.json (4.1KB)     初稿对比
    paper-analysis.schema.json / task-spec.schema.json / state-write-input.schema.json
    grade-once.md (17.1KB) / analyze-once-runtime.md / grade-once-runtime.md
  config/scoring-weights.json (2.9KB)
  method-libraries/
    method-index.json (68.8KB) + method-routing.json (9.4KB)
    按题型索引/（归纳概括、综合分析、提出对策、贯彻执行、申发论述）
    方法卡/sl-card-0001~N.json
assets/report-template.html + report.css
```

**借鉴要点**

1. 用 JSON Schema 把评阅的输入、输出、中间状态全部显式契约化，替代"一段 rubric 文本 + 模型自由发挥"
2. 配有一次性执行语义文档（grade-once / analyze-once），明确单次调用中允许多少推理步骤
3. 方法库按题型索引 + 方法卡（结构化 JSON）双层组织，支持路由（method-routing.json）
4. 评分权重外置为配置文件，可调

**对 GOSHORE 的意义**：当前评阅为「rubric 字符串 + 约定校验」的轻量实现；本方案是升级方向，也是毕业设计"方法形式化"章节的现成素材。

另注：该仓库 `ref-skills/Shenlun.skill-master/` 即已安装的 `coffe-d/Shenlun.skill` 原样拷贝（bai-lu-methodology / xiaoma-methodology / yuan-dong-methodology / real-exams 四套文件同名同结构），说明该方案与现有 skill 体系同源。

### ⭐B. 题库离线分发方案（补 GOSHORE 无题库的短板）

| 做法 | 文件 | 体积 | 价值 |
|---|---|---|---|
| SQLite 分片入库 | `tiku.db.part-00` ~ `part-03` | 每片 90MB / 末片 34MB | 绕过 GitHub 单文件 100MB 限制，将 GB 级题库纳入版本管理 |
| 索引分离 | `tiku-index.db` | 15MB | 索引与题体分库，按需加载 |
| 材料库独立 | `materials.db` | 27MB | 资料分析材料与题目解耦 |
| 浏览器内直查 SQLite | `public/vendor/sqljs/sql-wasm.wasm` | 644KB | 零后端，纯前端查询 |
| 移动端原生数据库桥 | `app/android/app/src/main/java/com/kaogong/app/NativeDbBridge.java` | 6.5KB | Capacitor 下改用原生 SQLite，避开 WASM 性能损耗 |

**对 GOSHORE 的意义**：现有题库仅 240 道示例题，该方案给出"离线题库 + Web/移动多端"的完整解法，可直接复用目录与加载策略。

### C. PDF / OCR / 题目结构化管线

| 文件 | 体积 | 作用 |
|---|---|---|
| `lib/pdf-ocr.mjs` | 5.3KB | OCR 回退链路 |
| `lib/pdf-text.mjs` | 6.8KB | PDF 文本层抽取 |
| `ref-skills/daily-gongkao-skill-main/data/ocr_question_bank/*.json` | 44.9KB / 36KB | OCR 后题目的 JSON 格式模板 |
| `ref-skills/daily-gongkao-skill-main/scripts/grade_answers.py` | 9KB | 答案评分脚本 |
| `ref-skills/daily-gongkao-skill-main/scripts/daily_push.py` | 9.4KB | 每日推送 |
| `lib/xingce-chapter-map.mjs` | 4.9KB | 行测章节映射（组卷标签体系） |
| `lib/fenbi-tree.mjs` | 6.5KB | 题库树结构 |
| `diag-pdf-full.mjs` / `diag-pdf-structure.mjs` / `diag-stems.mjs` | 2~3KB | PDF 结构诊断脚本 |
| `public/vendor/pdfjs/`、`public/vendor/xlsx/` | — | 前端解析 PDF / Excel |

**对 GOSHORE 的意义**：真题卷导入（PDF → 结构化题目）是当前最耗时的环节，该仓库的抽取与诊断脚本可直接借用作参考实现。

### D. 工程组织与文档范式

| 文件 | 体积 | 价值 |
|---|---|---|
| `docs/design/intelligent-paper-contract.md` | 20.6KB | 智能组卷契约设计文档 |
| `quiz-compose-design.md` | 25.7KB | 组卷设计 |
| `docs/design/design-system-web.md` / `design-system-app.md` | 各 2.5KB | 设计系统规范（Web / App 双端） |
| `docs/plans/2026-08-15-custom-bank-implementation.md` | 11.5KB | 自定义题库实施计划 |
| `docs/performance-optimization-2026-08-11.md` | 9.5KB | 性能优化留痕 |
| `docs/题库预处理提示词-通用版.md` | 7.3KB | 题库预处理提示词 |
| `app-roadmap.md` / `app-mobile-plan.md` | 5.7KB / 16.1KB | 路线图与移动端规划 |
| 根目录 `test-*.mjs`（20+ 个） | 7~18KB | 无框架的轻量自测脚本组织方式 |
| `build-app-assets.mjs` / `build-skill-bundle.mjs` | 13.2KB / 1.7KB | 多端资源与 skill 打包流水线 |
| `auth-user-isolation-design.md` | 13.2KB | 多用户隔离设计 |

---

## 三、与 GOSHORE 现状的对应关系

| GOSHORE 现有短板 | 可借鉴方案 | 预期收益 |
|---|---|---|
| 题库仅示例 240 题 | 分片 SQLite + sql.js + NativeDbBridge | 支撑大规模离线题库，多端统一数据源 |
| 评阅为 rubric 字符串 + 约定校验 | JSON Schema 契约体系 + 方法卡 + 权重配置 | 评阅结构可校验、可版本化 |
| 真题卷导入靠人工 | pdf-text / pdf-ocr + OCR JSON 模板 + 诊断脚本 | 缩短导入链路 |
| 设计文档偏过程记录 | 契约式设计文档写法（intelligent-paper-contract） | 提升毕设设计章节质量 |
| 前端样式零散 | design-system-web / app 双端设计系统规范 | 呼应设计 token 化改造 |

---

## 四、不建议照搬的内容

1. **仓库体积**：716MB、`public/` 下 8802 个文件、`public/tarzan-img/` 8778 张图片全部入库。建议图片走按需下载或独立资源包，不进入主仓库
2. **`server.mjs` 162.5KB 单文件**：与 GOSHORE 的 `app.js` 359KB 属同类结构问题，不应相互传染
3. **图标迭代残留**：`make-icons.mjs`、`make-icons-v2/v3/v4/final`、`make-icons-preview/preview2` 共 6 个脚本，属过程垃圾，只学思路不搬产物
4. **题库数据本体**：`tiku.db` 未声明数据许可，题目多为真题与机构题，**仅借架构，不搬数据**

---

## 五、授权与合规

| 内容 | 许可 | 使用边界 |
|---|---|---|
| 该项目代码 | MIT | 可借用、修改，需保留版权声明 |
| `tiku.db` / `materials.db` 题库数据 | 未声明 | 不复制数据 |
| 本地 `kaogongzhentizhengliu` | 标注与分类部分 CC BY-NC 4.0（非商业）；真题题干、选项、材料、配图版权归原出题机构及题库平台 | 个人学习、毕设演示合规；**答辩时不得声称题库为自有成果**，商用需另行授权 |

---

## 六、对毕业设计选题的影响（重要）

该项目已实现「将申论 Skill 接入软件完成自动评阅」这一工程路径，若毕设仅定位为"把 skill 接进 GOSHORE"，创新性会与既有开源实现重合。

**差异化定位建议**：本课题的重心在**方法形式化与可复现性验证**——通过基准注入与输出契约约束，量化评阅结果的标准差下降幅度，并以消融实验分离各要素贡献。论文相关工作章节应明确写为：

> 现有开源实现（如本仓库的技能包集成方案）已完成评阅流程的工程落地，但未公开可复现性度量与消融实验数据；本课题在此基础上补充方法的形式化描述、契约规则集与量化验证体系。

即：借其实现思路，立自己的创新点。

---

## 七、下一步建议

1. 精读 `skills/shenlun-review-pro/shenlun-review-skill/SKILL.md`（10KB）与 `references/contracts/scoring-result.schema.json`（12.4KB），提炼为 GOSHORE 可用的评分契约草案
2. 对比该仓库 `contracts/` 与 GOSHORE 现有 `exam_bank.py` 的数据结构，评估迁移成本
3. 若采纳题库分发方案，先做小规模验证（单模块分片 + sql.js 查询），避免一次性引入 GB 级数据
