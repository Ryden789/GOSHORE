# GOSHORE 项目 · TRAE 积分节省操作清单

> 原则：**能用本地工具就别让 AI 做，能用短上下文就别给长文件，能用 Seed-Turbo 就别用 DeepSeek-Pro**

---

## 一、模型选择（直接省 50~75%）

### 优先级排序

| 模型 | 折扣 | 适用场景 | 何时用 |
| --- | --- | --- | --- |
| **Seed-2.1-Turbo** | 会员 2.5 折 | 通用对话、简单代码、查资料 | 默认首选 |
| **Seed-Code** | 会员 2.5 折 | 写/改代码、补全、重构 | 写代码时首选 |
| **GLM-5.2** | 会员 5 折 | 复杂推理、架构设计、深度分析 | 需要深聊时 |
| **DeepSeek-Flash** | 会员全时段 5 折 | 长文本处理、推理加速 | 需大上下文时 |
| **DeepSeek-Pro** | 会员闲时 5 折 | 极复杂任务 | 万不得已才用 |

### GOSHORE 典型场景对应

| 你要做的事 | 推荐模型 | 避免模型 |
| --- | --- | --- |
| 改 `db.py` 加一列 | Seed-Code | DeepSeek-Pro |
| 写 `m.js` 新功能 | Seed-Code | DeepSeek-Flash |
| 分析 schema 迁移方案 | GLM-5.2 | DeepSeek-Pro |
| 查文档/API 用法 | Seed-Turbo | 任何大模型 |
| 生成 APK 构建脚本 | Seed-Code | GLM-5.2 |
| 设计数据库表结构 | GLM-5.2 | DeepSeek-Pro |

---

## 二、上下文控制（最大隐形杀手）

### ✅ 正确做法

| 操作 | 示例 |
| --- | --- |
| **只给相关片段** | "db.py L287-291 有个 ALTER TABLE，帮我改成版本化迁移" |
| **指定行号范围** | "m.js L201-212 的 api() 函数，参考 app.js L29-43 改错误处理" |
| **搜索结果贴摘要** | Grep 找到 3 处匹配 → 只贴这 3 段各 10 行 |
| **SQL 错误先自己跑** | `SELECT COUNT(*) FROM documents WHERE difficulty=""` 先出结果再告诉 AI |
| **新会话重新开始** | 一个话题聊超 10 轮 → 开新会话，旧上下文别续 |

### ❌ 绝对禁止

| 浪费行为 | 原因 |
| --- | --- |
| 粘整个 `db.py`（1900行）让 AI 改一个函数 | 输入 Token = 全文件 × 3~5，单次消耗 500+ |
| "帮我看看 app.js 有什么问题" | 全文件 2900 行，AI 还要逐行检查 → 输出也多 |
| 长对话续聊 20+ 轮 | 每轮都带完整历史，后期单次消耗是初期 5~10 倍 |
| 上传 `goshor.db` 让 AI 分析 | 210MB 文件，AI 根本吃不下还白费 Token |

### GOSHORE 常用文件精确定位速查

| 功能 | 文件 | 行号 | 平时只读这几行 |
| --- | --- | --- | --- |
| 数据库连接 | `app/db.py` | L266-356 | 90 行 |
| 版本化迁移 | `app/db.py` | L327-356 | 30 行 |
| reindex | `app/db.py` | L466-510 | 45 行 |
| 难度打标 | `app/db.py` | L2084-2120 | 37 行 |
| 桌面端 api() | `static/app.js` | L29-50 | 22 行 |
| 移动端 api() | `static/m/m.js` | L201-212 | 12 行 |
| 桌面端路由 | `static/app.js` | L199-219 | 21 行 |
| 移动端真题套卷 | `static/m/m.js` | L939-947 | 9 行 |
| WebView 壳 | `MainActivity.java` | L48-200 | 153 行 |
| 移动端服务器 | `goshor_server.py` | L1-50 | 50 行 |

---

## 三、能用本地工具就别让 AI 做

### 0 积分操作清单

| 任务 | 工具 | 命令/操作 |
| --- | --- | --- |
| 全文搜索代码 | Grep | `Grep pattern "difficulty"` 或 `"def migrate"` |
| 按文件名找 | Glob | `Glob pattern "**/*schema*"` |
| 统计行数 | Shell | `python -c "print(sum(1 for _ in open('app/db.py')))"` |
| 编译检查 | Shell | `python -m compileall -q app` |
| 跑回归 | Shell | `python .trae/skills/goshor-regression/scripts/regression.py` |
| 数据库查询 | Shell | `python -c "import sqlite3;c=sqlite3.connect('data/goshor.db');print(c.execute('SELECT difficulty,COUNT(*) FROM documents GROUP BY difficulty').fetchall())"` |
| APK 构建 | Shell | `gradle clean assembleDebug` |
| Git 操作 | Shell | `git log --oneline -5` / `git diff HEAD~1` |
| 端口占用检查 | Shell | `Get-NetTCPConnection -LocalPort 8765 -State Listen` |
| Python 语法验证 | Shell | `python -c "import ast; ast.parse(open('app/db.py').read()); print('OK')"` |

### 典型场景对比

| 场景 | ❌ 让 AI 做（费积分） | ✅ 本地先做（省积分） |
| --- | --- | --- |
| "db.py 里哪些地方用了 difficulty？" | AI 粘全文件搜 | Grep `"difficulty" path:"d:/GOSHORE/app/db.py"` → 30 秒出结果 |
| "帮我看看 SQL 对不对" | AI 读数据库+分析 | Shell 跑 SQL → 贴结果给 AI 分析 |
| "这个 JS 报错是什么？" | AI 读整个 m.js | 浏览器 F12 看 stack trace → 只贴报错栈 |
| "帮我写 git commit message" | AI 读 diff | `git diff HEAD~1` → 贴 diff 给 AI（短得多） |
| "代码总量多少？" | AI 数文件 | `Get-ChildItem -Recurse | Group-Object Extension` |

---

## 四、任务拆分策略

### 拆分 vs 不拆分

| ❌ 一句话大任务 | ✅ 拆成 3 小步 |
| --- | --- |
| "帮我给 db.py 加完整的版本化迁移机制" | 1. "写 `_migrate()` 函数框架，读 `_meta.schema_version`" <br> 2. "加 v0→v1 的 difficulty/material_fp/guessed 三列 ALTER" <br> 3. "在 init_db() 和 connect() 中调用 _migrate" |
| "重写 m.js 的辨析卡页面" | 1. "先看当前 drawCardLibrary 函数结构（L1473-1573）" <br> 2. "改成 allCards + cards 双变量 + applyFilters()" <br> 3. "加 300ms 防抖搜索框" |
| "APK 构建失败帮我修" | 1. 贴 Gradle 报错最后 30 行 → 定位问题 <br> 2. 贴相关 build.gradle 片段 → 修改 <br> 3. 构建验证结果 → 确认 |

### 拆分原则

- 每步输入 ≤ 50 行代码
- 每步有明确单一目标
- 中间结果自己先验证（compileall / 跑 SQL）再下一步
- 遇到 AI 输出错误，先本地修正再继续

---

## 五、积分获取最大化

| 途径 | 积分 | 有效期 | 操作 |
| --- | --- | --- | --- |
| 每日签到 | 150/200 | 31 天 | 每天打开 TRAE 点一下 |
| 每月登录 | 500 | 当月 | 每月 1 号打开一次 |
| 邀请新用户 | 500/人（封顶 3500） | 31 天 | 分享邀请链接 |
| 增购 | 1000 积分 = ¥50 | 31 天 | 积分见底再买 |
| 会员 Lite | 2000/月 | 31 天 | ¥45/月，适合重度使用 |

**积分消耗顺序**：有效期最短优先 → 奖励积分优先于会员积分

---

## 六、GOSHORE 专属省积分 Tips

### 1. 数据库问题先用 SQLite 自测

```powershell
# 查难度分布（1 秒出结果，0 积分）
python -c "import sqlite3;c=sqlite3.connect('data/goshor.db');print(c.execute('SELECT difficulty,COUNT(*) FROM documents GROUP BY difficulty').fetchall())"

# 查某模块题目数
python -c "import sqlite3;c=sqlite3.connect('data/goshor.db');print(c.execute(\"SELECT module,COUNT(*) FROM documents GROUP BY module\").fetchall())"

# 验证 ALTER TABLE 是否生效
python -c "import sqlite3;c=sqlite3.connect('data/goshor.db');print(c.execute('PRAGMA table_info(answers)').fetchall())"
```

### 2. 移动端改动先在桌面端验证

- 桌面端改 `app/db.py` → `compileall` → 跑回归 → 再同步到 `.tools/mobile_py/app/db.py`
- 不要直接在移动端副本上改，双份维护 = 双倍 AI 调用

### 3. API 问题先用 curl 自测

```powershell
# 测 stats 接口
curl.exe -s http://127.0.0.1:8765/api/stats -o NUL -w "%{http_code}"

# 测 facets
curl.exe -s http://127.0.0.1:8765/api/facets | python -m json.tool
```

### 4. 前端样式问题自己改

- 改 CSS 颜色/间距：直接改 `m.css` / `styles.css`，不用问 AI
- 改 JS 文案/提示：直接改字符串，不用让 AI "润色"
- 调试 `onclick` 不触发：F12 Console 看报错 → 自己定位

### 5. APK 构建问题先搜常见坑

| 问题 | 自己查 | 不用问 AI |
| --- | --- | --- |
| `VersionNumber` 类找不到 | Gradle 版本不对（必须 8.9） | |
| payload.zip 残留 | 必须 `gradle clean` 再构建 | |
| Chaquopy 许可证 | 免费版限 50MB | |
| `copyAssetDir` 后旧文件还在 | 加 `deleteRecursively(dst)` | |

---

## 七、积分消耗红线

| 单次操作 | 正常消耗 | 超过即止损 |
| --- | --- | --- |
| 改一个函数 | 50~100 | >300 → 检查是否给了太长上下文 |
| 新写一个功能 | 200~400 | >800 → 拆分任务 |
| 排查一个 bug | 100~300 | >500 → 先本地自测定位 |
| 架构讨论 | 300~600 | >1000 → 分多轮 |

**月预算参考**：

| 套餐 | 月积分 | 日均 | 能做什么 |
| --- | --- | --- | --- |
| 免费（签到+登录） | ~5000 | ~160 | 改 3-5 个函数 |
| Lite 套餐 | 2000 | ~65 | 改 1-2 个函数 |
| Pro 套餐 | 4000 | ~130 | 改 2-3 个函数 + 1 个小功能 |

---

**文档版本**：V1.0  
**适用项目**：GOSHORE 上岸自习室  
**关联文档**：`交接文档.md`（项目架构参考）
