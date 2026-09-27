# GOSHORE 手机版：本地多账号 + 全功能移植 - 实施计划

## Task 1: 数据层多身份改造
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 将 SCHEMA 拆分为"共享表"（documents、docs_fts、shizheng）与"个人表"（answers、marks、speed_rounds、speed_items、wordfill_questions/answers、wrong_reasons、review_plan、cards/card_reviews/card_plan、essay_grades、formula_rounds/items、doubts、explain_cache），桌面端 init 行为保持不变。
  - 引入身份上下文（contextvar：当前 uid）；`connect()` 身份化：打开个人库 data_<uid>.db → ATTACH 共享 goshor.db（只读 URI）→ 建 TEMP 视图映射共享表名；桌面端走原路径（单库、单视图身份，零变化）。
  - 个人库首次打开时按"个人表"子集建表。
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-10
- **Test Requirements**:
  - `rule` TR-1.1: 桌面端启动与回归全绿（编译检查 + API 冒烟 + 页面验证），无行为变化
  - `rule` TR-1.2: 在个人库连接上执行典型读写 SQL（作答/收藏/复习/统计）结果正确；共享表经视图可查询且不可写（写操作报只读）
  - `rule` TR-1.3: 两个不同 uid 连接的个人数据互不可见（同 doc_id 作答隔离）
- **Completion Evidence**:
  - TR-1.1：goshor-regression 全绿（7 项 API + 25 页面 + 5 深度断言），输出见会话
  - TR-1.2/TR-1.3：scripts/_t1_test.py PASS（含只读断言、uid1/uid2 隔离、难度覆写、时政缓存、LIKE 搜题、stats/weekly 可运行）；新账号库 118,784 字节（远低于 5MB）

## Task 2: 账户系统后端
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 账户库 users/accounts.db（id、username UNIQUE、salt、pw_hash、created_at）；PBKDF2-HMAC-SHA256（20 万次、16 字节盐）。
  - 会话文件 users/session.json（uid，默认游客 0）；服务启动时载入。
  - 注册（含游客数据迁入：data_0.db → data_<uid>.db 后重建空游客库）、登录校验、登出；任何返回不含密码/哈希。
  - 老版本升级迁移：首次新逻辑启动时，把 goshor.db 中全部个人表数据复制进 data_0.db（按条数校验），旧表留库但被 TEMP 视图遮蔽。
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3, AC-4
- **Test Requirements**:
  - `rule` TR-2.1: 注册/登录/登出接口行为符合 FR-1~FR-6；重复用户名、用户名<2 字符、密码<6 字符、错误密码均被拒绝并返回中文信息
  - `rule` TR-2.2: 注册勾选迁入游客数据时，新库各表条数与游客库一致且游客库清空；未勾选时游客数据保留
  - `rule` TR-2.3: 升级迁移演练：构造含个人数据的旧库 → 执行迁移 → data_0 条数 ≥ 旧库、统计一致
  - `rule` TR-2.4: 所有 auth 相关响应中不存在 salt/pw_hash/密码字段

## Task 3: 手机前端账号体系
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - 登录页、注册页（用户名/密码/确认密码/迁入游客勾选）、登出确认；启动时按 /api/auth/me 决定默认页。
  - 游客身份显示轻提示条；「我的」页显示当前账号、切换/登出入口。
  - 会话过期/异常时自动回到登录页。
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3
- **Test Requirements**:
  - `rule` TR-3.1: 注册成功自动进入首页并显示用户名；错误提示中文可见；登录/登出/切换流程 0 JS 错误
  - `rubric` TR-3.2: 账号页面可用性；1-5；锚点 1=无法完成登录，3=可用但粗糙，5=与现有纸墨风一致；阈值 ≥4；证据：截图 + CDP 操作记录

## Task 4: 手机端导航中枢改造
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 调整底部 tab（首页/刷题/更多/我的 等），新增「全部功能」中枢页，按桌面 5 组（总览/行测精练/综应专区/复习巩固/题库管理）列出 21 个入口。
  - 保持做题覆盖页、inRun 返回逻辑、二次点击当前 tab 重渲染等现有行为。
- **Acceptance Criteria Addressed**: AC-5
- **Test Requirements**:
  - `rule` TR-4.1: 中枢页 21 个入口全部存在且分组正确；点击可路由；0 JS 错误
  - `rubric` TR-4.2: 导航清晰度；1-5；锚点 1=找不到功能，3=需要摸索，5=一目了然；阈值 ≥4；证据：截图

## Task 5: 行测精练功能全栈（判断专项/词语填空/速算）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 4
- **Description**:
  - 服务器移植 /api/speed/*（generate/result/type-stats/history，含 speed_items 落库）、/api/wordfill/*（generate/practice/answer/stats）、判断专项相关端点（random_paper 的 trap/考点参数等）；组卷与列式复用现有端点。
  - 手机页面：词语填空（文章多空连续作答）、速算（限时题型轮次）、判断专项（组卷设置+做题流）。
- **Acceptance Criteria Addressed**: AC-5, AC-6
- **Test Requirements**:
  - `rule` TR-5.1: 三功能各完成一轮"生成→作答→判分→记录可查"，判分与桌面规则一致、统计数字相应增加
  - `rule` TR-5.2: 历史/类型统计接口在手机端返回正确数据
  - `rubric` TR-5.3: 三页面手机端交互质量 1-5；阈值 ≥4；证据：每组至少 1 张截图

## Task 6: 综应专区功能全栈（申论/文献/时政/AI批改 + AI 流式）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 4
- **Description**:
  - 服务器移植：/api/knowledge/essay、/api/essay/*（rubrics/grade/history/questions）、/api/shizheng/*（列表/generate/quiz）、科技文献相关端点、AI 批改所需的 AI 调用。
  - 新增 AI 流式响应能力（http.server chunked/SSE，接 ai 生成器）。
  - build.gradle 增加 Chaquopy pip 依赖：httpx 及传递依赖（安装前先探测轮子可用性，不可用则改用标准库 urllib 实现 AI 调用）。
  - 手机页面：申论综应（题目+作答+AI 评分历史）、科技文献（长文+小题群）、时政（期次选择+自测）、AI批改入口。
- **Acceptance Criteria Addressed**: AC-5, AC-6, AC-7, AC-9
- **Test Requirements**:
  - `rule` TR-6.1: 无 Key/断网时 AI 操作显示中文提示且无未捕获异常；配置真实 Key 联网时 AI 内容成功返回（流式可见）
  - `rule` TR-6.2: 时政可按期次出题作答；科技文献长文与小题可读；申论题目列表与评分历史可用
  - `rule` TR-6.3: httpx 依赖安装成功且 APK 增量 ≤ 30 MB；若 httpx 无轮子，urllib 方案下 AI 调用同样通过
  - `rubric` TR-6.4: 四页面手机端阅读与作答体验 1-5；阈值 ≥4；证据：每页面截图

## Task 7: 复习巩固功能全栈（今日复习/错题本/收藏/辨析卡）
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1, Task 4
- **Description**:
  - 服务器移植 /api/reviews、/api/wrong-reasons（含 ai-suggest）、/api/cards/*（import/facets/review/progress）、/api/due-cards；错题本/收藏已有端点核对完善。
  - 手机页面：今日复习（到期列表+重做）、辨析卡（翻面/评分/到期）、错因标注。
- **Acceptance Criteria Addressed**: AC-5, AC-6
- **Test Requirements**:
  - `rule` TR-7.1: 四页面数据正确（与本人统计一致），重做/标注/卡片评分后数据变化正确
  - `rule` TR-7.2: 0 JS 错误、无 404/500
  - `rubric` TR-7.3: 卡片翻面与复习列表交互 1-5；阈值 ≥4；证据：截图

## Task 8: 题库管理功能全栈（搜题/疑点/导入/设置）
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1, Task 4
- **Description**:
  - 搜题：新增 LIKE 模糊匹配实现（替代手机库缺失的 docs_fts），/api/search 返回分页结果并可打开题目。
  - 疑点：/api/doubts、/api/doubts/sync、/api/doubt/status、/api/doubt/recheck；导入：/api/import/json/preview、/api/import/web/preview、/api/import/commit（导入题目进入当前账号私有集合）；设置：/api/settings 读写（按身份独立，含 AI Key 字段、不回显明文）。
  - 对应手机页面四个。
- **Acceptance Criteria Addressed**: AC-5, AC-7
- **Test Requirements**:
  - `rule` TR-8.1: 搜题用典型关键词可命中并打开详情；空结果有提示
  - `rule` TR-8.2: 疑点列表/状态变更可用；导入预览→提交流程可用且仅本人可见
  - `rule` TR-8.3: 设置写入后读回生效（Key 不回显）；切换账号设置互不相同
  - `rule` TR-8.4: 0 JS 错误
  - `rubric` TR-8.5: 四页面手机端可用性 1-5；阈值 ≥4；证据：截图

## Task 9: 总览补充（做题记录）与备份恢复
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1, Task 4
- **Description**:
  - 移植 /api/history（按时间明细分页）与手机页面（周报/今日已有）。
  - 移植 /api/backup/export、/api/backup/import；备份默认排除 API Key；手机端设置页提供导出（系统分享/保存到下载目录）与导入（文件选择）入口。
- **Acceptance Criteria Addressed**: AC-5, AC-8
- **Test Requirements**:
  - `rule` TR-9.1: 做题记录与实际作答一致、可分页
  - `rule` TR-9.2: 导出→清空→导入后关键表条数一致；备份内容不含 Key
  - `rule` TR-9.3: 0 JS 错误
  - `rubric` TR-9.4: 记录页与备份流程可用性 1-5；阈值 ≥4；证据：截图

## Task 10: 全量端到端验证与发布
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2~9
- **Description**:
  - 执行完整升级演练（旧版→做题→覆盖新版→数据核对）。
  - CDP 逐页验证 21 功能 + 账号隔离矩阵（游客/A/B 交叉比对）；硬件返回键与做题退出回归。
  - logcat 零 JS ERROR；体积/存储阈值核对；桌面端回归复核。
  - APK 复制到桌面命名「上岸自习室.apk」。
- **Acceptance Criteria Addressed**: AC-1~AC-11
- **Test Requirements**:
  - `rule` TR-10.1: AC-1~AC-10 全部有独立通过证据（脚本输出/截图/命令输出）
  - `rule` TR-10.2: 桌面回归全绿；APK 就位
  - `rubric` TR-10.3: 整体手机端质量评审（含 AC-11 全部截图）1-5；阈值 ≥4
